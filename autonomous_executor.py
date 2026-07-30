# autonomous_executor.py (v14.11 - 集成动态权限管理器)
"""
自主执行器 - 让念言具备从理解到执行的完整闭环能力
==============================================
接收自然语言目标，自主完成：理解 → 规划 → 优化 → 执行 → 达成目的
v14.7 - 智能任务优化器 + 反思-重规划闭环：失败时发布事件，触发内部议会反思。
v14.8 - 添加模型路由器引用，保持架构统一。
v14.10- 适配工具调度器，统一通过 task_executor 或调度器执行任务。
v14.11- 集成动态权限管理器，敏感操作请求用户授权。
"""

import asyncio
import time
import re
from typing import Dict, Any, List, Optional
from task_planner import TaskPlanner
from message_bus import MessageBus
from model_router import ModelRouter

# 导入工具调度器，用于 fallback 场景
from tools.tool_dispatcher import dispatch, is_tool_available


class AutonomousExecutor:
    """
    自主执行器。
    接收一个目标，自动规划并执行原子任务序列，直到目标达成或失败。
    失败时发布 task.failed.need_reflection 事件，启动七情议会反思研讨会。
    """

    def __init__(self, bus: MessageBus, task_executor=None, palace_memory=None):
        self.bus = bus
        self.task_executor = task_executor
        self.palace = palace_memory
        self.planner = TaskPlanner(router=getattr(bus, 'model_router', None))

        # 路由器：从 bus 获取，便于未来扩展（当前未直接使用）
        self.router = getattr(bus, 'model_router', None) or ModelRouter(max_concurrent_requests=1)

        # 执行上下文：用于在任务间传递数据
        self.context: Dict[str, Any] = {}

    async def execute_goal(self, goal: str, user_id: str = "system") -> Dict[str, Any]:
        """
        自主执行一个目标。
        返回执行结果摘要，包含成功状态、执行步骤数、耗时和详细结果。
        """
        start_time = time.time()
        self.bus.publish("output.display", f"🎯 收到自主目标：{goal}")
        print(f"[AutonomousExecutor] 开始执行目标: {goal[:80]}...")

        # 判断是否为纯信息获取类目标（不需要竞争主动行为锁）
        info_keywords = ["搜索", "查", "总结", "分析", "描述", "解释", "什么是", "如何", "帮我搜", "打开", "提取", "阅读"]
        is_info_task = any(kw in goal for kw in info_keywords)

        lock = getattr(self.bus, 'active_behavior_lock', None)
        acquired = False
        if not is_info_task and lock:
            acquired = lock.acquire(blocking=False)
            if not acquired:
                print("[AutonomousExecutor] 非信息任务，锁获取失败，跳过执行")
                return {"success": False, "error": "active_behavior_lock_busy"}

        try:
            if is_info_task:
                print("[AutonomousExecutor] 信息类任务，跳过主动行为锁")

            # ========== 第一步：理解与规划 ==========
            self.bus.publish("thinking.log", f"📋 正在理解目标：{goal}")
            print("[AutonomousExecutor] 正在调用规划器 parse_instruction...")
            parsed = self._plan_goal(goal)
            print(f"[AutonomousExecutor] 规划器返回: {parsed}")

            if not parsed:
                self.bus.publish("output.display", "❌ 无法理解该目标，请提供更多信息。")
                print("[AutonomousExecutor] 规划失败，返回空")
                return {"success": False, "error": "规划失败"}

            # ========== 第二步：转换为原子任务序列并优化 ==========
            raw_tasks = self.planner.plan_tasks(parsed)
            print(f"[AutonomousExecutor] plan_tasks 原始返回: {raw_tasks}")

            # 智能优化任务序列
            tasks = self._optimize_tasks(raw_tasks, goal)
            print(f"[AutonomousExecutor] 优化后任务序列: {tasks}")

            if not tasks:
                self.bus.publish("output.display", "❌ 无法生成执行计划。")
                print("[AutonomousExecutor] 任务序列为空")
                return {"success": False, "error": "无可用任务"}

            self.bus.publish("output.display", f"📝 已生成 {len(tasks)} 个执行步骤")

            # ========== 第三步：依次执行任务 ==========
            results = []
            for i, task in enumerate(tasks):
                action = task.get('action')
                print(f"[AutonomousExecutor] 执行步骤 {i+1}/{len(tasks)}: {action}")
                self.bus.publish("thinking.log", f"⚡ 执行步骤 {i+1}/{len(tasks)}：{action}")
                
                # 在执行前，从上下文中补全缺失的常用参数
                task = self._enrich_task_params(task)
                
                result = await self._execute_task(task)
                print(f"[AutonomousExecutor] 步骤 {i+1} 结果: success={result.get('success')}, error={result.get('error', 'N/A')}")
                results.append(result)

                if result.get("success"):
                    self._update_context(task, result)
                else:
                    if not self._is_recoverable(task, result):
                        error_msg = result.get('error', '未知错误')
                        self.bus.publish("output.display", f"❌ 步骤 {i+1} 失败，执行中止：{error_msg}")
                        
                        # ========== 发布反思事件 ==========
                        self._publish_reflection_event(
                            goal=goal,
                            failed_step=i + 1,
                            failed_action=action,
                            error=error_msg,
                            completed_results=results[:i],
                            remaining_tasks=tasks[i+1:],
                            user_id=user_id
                        )
                        
                        return {
                            "success": False,
                            "error": error_msg,
                            "completed_steps": i,
                            "results": results
                        }
                    else:
                        self.bus.publish("thinking.log", f"⚠️ 步骤 {i+1} 失败但可恢复，继续执行后续任务")

            # ========== 第四步：报告结果 ==========
            duration = time.time() - start_time
            
            # 提取最终结果内容用于显示
            final_content = self._extract_final_content(results)
            if final_content:
                # 发布到聊天窗口
                self.bus.publish("output.display", f"📝 {final_content[:800]}")
                # 如果内容较长，自动保存到桌面
                if len(final_content) > 500:
                    from atomic_actions import save_file
                    filename = f"阅读结果_{time.strftime('%Y%m%d_%H%M%S')}.txt"
                    await save_file({"filename": filename, "location": "desktop", "content": final_content}, {})
                    self.bus.publish("output.display", f"📁 完整内容已保存到桌面：{filename}")

            self.bus.publish("output.display", f"✅ 目标达成！（耗时 {duration:.1f} 秒）")

            if self.palace:
                self._store_execution_memory(goal, tasks, results, duration)

            return {
                "success": True,
                "goal": goal,
                "steps": len(tasks),
                "duration": duration,
                "results": results
            }
        finally:
            if acquired and lock:
                lock.release()

    def _publish_reflection_event(self, goal: str, failed_step: int, failed_action: str,
                                   error: str, completed_results: List[Dict], 
                                   remaining_tasks: List[Dict], user_id: str):
        """
        发布任务失败反思事件，携带完整的失败上下文。
        """
        reflection_data = {
            "goal": goal,
            "failed_step": failed_step,
            "failed_action": failed_action,
            "error": error,
            "completed_results": completed_results,
            "remaining_tasks": remaining_tasks,
            "context": self.context.copy(),
            "user_id": user_id,
            "timestamp": time.time()
        }
        self.bus.publish("task.failed.need_reflection", reflection_data)
        print(f"[AutonomousExecutor] 已发布反思事件: {failed_action} 失败 - {error[:50]}")

    def _optimize_tasks(self, tasks: List[Dict], goal: str) -> List[Dict]:
        """
        智能优化任务序列：
        1. 移除冗余的 open_browser（如果后续有 extract_full_page_text 或 web_browser_search）
        2. 合并重复的 URL 参数
        3. 确保 summarize_text 有 text 来源
        """
        if not tasks:
            return tasks

        optimized = []
        seen_url = None

        # 先从任务序列中提取第一个有效的 URL
        for task in tasks:
            params = task.get("params", {})
            if params.get("url"):
                seen_url = params.get("url")
                break
            if params.get("query"):
                seen_url = params.get("query")

        for task in tasks:
            action = task.get("action")
            params = task.get("params", {}).copy()

            # 规则1：如果动作是 open_browser 且没有提供 URL，则跳过（冗余）
            if action == "open_browser":
                if not params.get("url") and not params.get("search"):
                    print(f"[AutonomousExecutor] 优化: 移除无参数的 open_browser")
                    continue

            # 规则2：如果动作是 extract_full_page_text 且参数为空，尝试从上下文补全
            if action == "extract_full_page_text" and not params.get("url"):
                if seen_url:
                    params["url"] = seen_url
                    print(f"[AutonomousExecutor] 优化: 为 extract_full_page_text 补全 URL: {seen_url}")
                else:
                    url_match = re.search(r'(https?://[^\s]+)', goal)
                    if url_match:
                        params["url"] = url_match.group(1)
                        seen_url = url_match.group(1)
                        print(f"[AutonomousExecutor] 优化: 从目标提取 URL: {seen_url}")

            # 规则3：如果动作是 web_browser_search 且没有 query，尝试补全
            if action == "web_browser_search" and not params.get("query"):
                if seen_url:
                    params["query"] = seen_url
                    print(f"[AutonomousExecutor] 优化: 为 web_browser_search 补全 query: {seen_url}")

            # 规则4：如果动作是 summarize_text，确保它知道从上下文获取文本
            if action == "summarize_text":
                if not params.get("text"):
                    params["text"] = ""
                    print(f"[AutonomousExecutor] 优化: summarize_text 将从上下文获取文本")

            optimized.append({"action": action, "params": params})

        return optimized

    def _enrich_task_params(self, task: Dict) -> Dict:
        """
        在执行前，从上下文中补全缺失的常用参数。
        """
        action = task.get("action")
        params = task.get("params", {}).copy()

        if action == "save_file" and not params.get("content"):
            content = self.context.get("last_generated_content") or self.context.get("last_summary")
            if content:
                params["content"] = content
                print(f"[AutonomousExecutor] 从上下文补全 save_file 内容 ({len(content)} 字符)")

        if action == "summarize_text" and not params.get("text"):
            text = self.context.get("last_extracted_text") or self.context.get("last_search_results")
            if text:
                params["text"] = text
                print(f"[AutonomousExecutor] 从上下文补全 summarize_text 文本 ({len(text)} 字符)")

        return {"action": action, "params": params}

    def _plan_goal(self, goal: str) -> Optional[Dict]:
        """调用任务规划器解析目标"""
        try:
            context = self._build_context()
            return self.planner.parse_instruction(goal, context)
        except Exception as e:
            print(f"[AutonomousExecutor] 规划器异常: {e}")
            return None

    def _build_context(self) -> Dict:
        """构建供规划器参考的情境"""
        ctx = {}
        
        if self.palace:
            try:
                memories = self.palace.retrieve_by_semantic(
                    query="任务执行 操作 文件",
                    top_k=3, threshold=0.3, mem_type="fact"
                )
                if memories:
                    ctx["memory_hint"] = "; ".join([m['answer'][:100] for m in memories])
            except Exception as e:
                print(f"[AutonomousExecutor] 获取记忆提示失败: {e}")

        ctx.update(self.context)
        return ctx

    async def _execute_task(self, task: Dict) -> Dict:
        """执行单个原子任务，优先使用 task_executor，fallback 时统一调度。增加权限检查。"""
        action = task.get("action")
        params = task.get("params", {})

        # ========== v14.11 新增：权限检查 ==========
        perm_mgr = getattr(self.bus, 'permission_manager', None)
        if perm_mgr:
            # 构建目标描述
            target = params.get("filename") or params.get("url") or params.get("path") or ""
            if not target:
                target = params.get("query") or params.get("command") or task.get("action", "")
            req = perm_mgr.request_permission(
                action=action,
                target=str(target),
                reason=f"自主执行目标中的 {action} 操作",
                source_module="autonomous_executor"
            )
            # L2/L3 操作需要等待用户审批
            if req.risk_level.value in ("medium", "high"):
                approved = perm_mgr.wait_for_approval(req, timeout=30.0)
                if not approved:
                    return {"success": False, "error": "用户拒绝授权或审批超时"}
        # ========== 权限检查结束 ==========

        max_retries = 2 if action in ("web_browser_search", "extract_full_page_text") else 1
        last_error = None

        for attempt in range(max_retries):
            try:
                if self.task_executor:
                    print(f"[AutonomousExecutor] 通过 task_executor 执行 {action}")
                    result = await self.task_executor.execute_task(task, self.context)
                else:
                    # Fallback：先尝试核心原子动作，再尝试工具调度器
                    from atomic_actions import ACTION_MAP
                    if action in ACTION_MAP:
                        print(f"[AutonomousExecutor] 直接调用原子动作 {action}")
                        result = await ACTION_MAP[action](params, self.context)
                    elif is_tool_available(action):
                        print(f"[AutonomousExecutor] 通过工具调度器执行 {action}")
                        result = await dispatch(action, params, self.context)
                    else:
                        return {"success": False, "error": f"未知动作: {action}"}

                if result.get("success") or attempt == max_retries - 1:
                    return result
                print(f"[AutonomousExecutor] {action} 第 {attempt+1} 次尝试失败，重试中...")
                await asyncio.sleep(2)
            except Exception as e:
                last_error = str(e)
                print(f"[AutonomousExecutor] {action} 异常: {e}")
                if attempt == max_retries - 1:
                    return {"success": False, "error": last_error}
                await asyncio.sleep(2)

        return {"success": False, "error": last_error or "未知错误"}

    def _update_context(self, task: Dict, result: Dict):
        """将任务执行结果存入上下文，供后续任务使用"""
        action = task.get("action")
        params = task.get("params", {})

        if action == "capture_screen":
            self.context["last_screenshot"] = result.get("image_base64")
        elif action == "analyze_image_with_qwen":
            self.context["last_image_description"] = result.get("description")
        elif action == "generate_text":
            content = result.get("content")
            if content:
                self.context["last_generated_content"] = content
        elif action == "retrieve_memory_semantic":
            self.context["last_memory_results"] = result.get("results", [])
        elif action == "web_browser_search":
            self.context["last_search_results"] = result.get("results")
        elif action == "extract_full_page_text":
            text = result.get("text")
            if text:
                self.context["last_extracted_text"] = text
                self.context["last_search_results"] = text
        elif action == "save_file":
            self.context["last_saved_file"] = result.get("filepath")
        elif action == "create_folder":
            self.context["last_created_folder"] = result.get("path")
        elif action == "summarize_text":
            summary = result.get("summary")
            if summary:
                self.context["last_summary"] = summary
        elif action == "execute_script":
            output = result.get("output")
            if output:
                self.context["last_script_output"] = output

        output_var = params.get("output_var")
        if output_var and result.get("success"):
            if "content" in result:
                self.context[output_var] = result["content"]
            elif "description" in result:
                self.context[output_var] = result["description"]
            elif "results" in result:
                self.context[output_var] = result["results"]
            elif "text" in result:
                self.context[output_var] = result["text"]
            elif "output" in result:
                self.context[output_var] = result["output"]

    def _is_recoverable(self, task: Dict, result: Dict) -> bool:
        """判断任务失败是否可恢复"""
        action = task.get("action")
        if action in ("web_browser_search", "retrieve_memory_semantic",
                      "retrieve_memory_by_tags", "retrieve_memory_by_time", "extract_full_page_text"):
            return True
        if action in ("analyze_image_with_qwen", "capture_screen"):
            return True
        return False

    def _extract_final_content(self, results: List[Dict]) -> str:
        """从执行结果中提取最终内容用于显示"""
        for result in reversed(results):
            if result.get("success"):
                if "summary" in result:
                    return result["summary"]
                if "description" in result:
                    return result["description"]
                if "content" in result:
                    return result["content"]
                if "results" in result:
                    return result["results"]
                if "text" in result:
                    return result["text"]
                if "output" in result:
                    return result["output"]
        return ""

    def _store_execution_memory(self, goal: str, tasks: List[Dict], results: List[Dict], duration: float):
        """将本次执行记录存入记忆宫殿"""
        try:
            summary = f"目标：{goal}。共执行 {len(tasks)} 个步骤，耗时 {duration:.1f} 秒。"
            details = []
            for i, (task, res) in enumerate(zip(tasks, results)):
                status = "✅" if res.get("success") else "❌"
                details.append(f"{status} 步骤{i+1}: {task.get('action')}")
            full_answer = summary + "\n" + "\n".join(details)

            self.palace.add_to_chaos(
                question=f"自主执行记录：{goal[:50]}",
                answer=full_answer,
                utility=0.7,
                source="autonomous_executor",
                mem_type="task_execution"
            )
        except Exception as e:
            print(f"[AutonomousExecutor] 存储执行记忆失败: {e}")

    def clear_context(self):
        """清空执行上下文"""
        self.context.clear()