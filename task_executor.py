# task_executor.py (v14.11 - 智能意图调度 + 工具目录自动注册)
"""
任务执行器 - 数字生命体的行动中枢
==================================
接收用户指令，通过 LLM 自主判断意图，分发到不同执行单元。
支持深度阅读、文件创建、搜索、视觉探索、脚本执行、聊天等模式。
v14.11 - 新增工具目录自动注册：当用户创建工具脚本时，自动注册到能力清单。
"""

import asyncio
import threading
import re
import json
import time
import os
from typing import Dict, Any
from message_bus import MessageBus
from task_planner import TaskPlanner
from atomic_actions import ACTION_MAP, save_file, generate_text
from priority_arbiter import Instruction
from tools.tool_dispatcher import dispatch, is_tool_available


class TaskExecutorModule:
    def __init__(self, bus: MessageBus):
        self.bus = bus
        self.planner = TaskPlanner()
        # 获取全局路由器
        self.router = getattr(bus, 'model_router', None)
        bus.subscribe("task.execute", self.on_task)
        bus.task_executor = self

    def on_task(self, instruction: Instruction):
        threading.Thread(target=self.execute, args=(instruction.content,), daemon=True).start()

    async def execute_task(self, task: Dict[str, Any], context: Dict[str, Any] = None) -> Dict[str, Any]:
        if context is None:
            context = {}
        action = task.get("action")
        params = task.get("params", {})
        func = ACTION_MAP.get(action)
        if func:
            try:
                result = await func(params, context)
                return result
            except Exception as e:
                return {"success": False, "error": str(e)}
        if is_tool_available(action):
            try:
                result = await dispatch(action, params, context)
                return result
            except Exception as e:
                return {"success": False, "error": f"工具执行异常: {e}"}
        return {"success": False, "error": f"未知操作: {action}"}

    def _sanitize_filename(self, filename: str) -> str:
        allowed_pattern = r'[^\u4e00-\u9fa5a-zA-Z0-9._\-/\\]'
        cleaned = re.sub(allowed_pattern, '', filename)
        cleaned = cleaned.strip()
        if not cleaned:
            cleaned = "untitled.txt"
        return cleaned

    def _extract_explicit_content(self, user_input: str) -> str:
        content_match = re.search(r'内容[是为:：]\s*(.+?)(?:$|\n|，且|，并|，然后)', user_input, re.DOTALL)
        if not content_match:
            content_match = re.search(r'内容为\s*[`]?(.+?)[`]?(?:$|\n|，|。)', user_input, re.DOTALL)
        if content_match:
            return content_match.group(1).strip()
        return ""

    # ---------- 智能意图理解 ----------
    def _understand_intent(self, user_input: str) -> dict:
        """调用轻量模型理解用户意图，返回明确的动作指令"""
        if not self.router:
            # 无路由器时降级
            return {"action": "auto", "params": {}}

        prompt = f"""请分析以下用户指令，判断用户的核心意图，并从以下选项中选择最匹配的一个动作名。

可用动作：
- deep_read: 用户想要深度解读、精读、分析某个文本文件的内容（通常会给出文件路径）
- create_file: 用户想要在桌面或指定位置创建新文件（通常会指定文件名和内容）
- search: 用户想要搜索或查询某个信息
- chat: 用户只是在闲聊、提问或进行一般性对话
- visual_explore: 用户想要观察、分析屏幕截图
- execute_script: 用户想要编写并运行一段 Python 脚本

用户指令：{user_input}

请只返回JSON格式，例如：{{"action": "deep_read", "params": {{"source": "文件路径", "target_length": 字数}}}}
如果参数无法确定，params 可以为空。只输出 JSON，不要其他内容。"""

        try:
            response = self.router.call(
                role="light_task",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=200
            )
            response = response.strip()
            # 清理可能的 Markdown 代码块
            if response.startswith("```"):
                response = response.split("```")[1]
            if response.startswith("json"):
                response = response[4:]
            result = json.loads(response)
            print(f"🧠 [意图理解] 用户意图: {result.get('action')}")
            return result
        except Exception as e:
            print(f"意图理解失败，降级为通用规划器: {e}")
            return {"action": "auto", "params": {}}

    # ---------- 调度入口 ----------
    def execute(self, user_input: str):
        # 让念言自己判断意图
        intent = self._understand_intent(user_input)
        action = intent.get("action", "chat")
        params = intent.get("params", {})

        # 根据意图分发
        if action == "deep_read":
            self._execute_deep_read(params, user_input)
        elif action == "create_file":
            self._execute_create_file(user_input)
        elif action == "search":
            self._execute_search(params)
        elif action == "visual_explore":
            self._execute_visual_explore(params, user_input)
        elif action == "execute_script":
            self._execute_script_logic(params, user_input)
        elif action == "chat":
            self.bus.publish("user_input.main", {"message": user_input, "user_id": "user"})
        else:
            # 兜底：走规划器
            self._execute_plan(user_input)

    # ---------- 各动作执行方法 ----------
    def _execute_deep_read(self, params: dict, user_input: str):
        """执行深度阅读"""
        # 优先从 params 获取，否则从用户输入中提取
        source = params.get("source", "")
        if not source:
            path_match = re.search(r'([A-Za-z]:\\[^\s]*\.txt)', user_input)
            if path_match:
                source = path_match.group(1)

        if not source:
            self.bus.publish("output.display", "⚠️ 未能识别文件路径，无法执行深度阅读。")
            return

        target_length = params.get("target_length", 32000)
        if not target_length:
            length_match = re.search(r'(\d+)\s*字', user_input)
            if length_match:
                target_length = int(length_match.group(1))

        print(f"📖 [智能调度] 深度阅读: {source}, 目标{target_length}字")

        if not is_tool_available("deep_read"):
            self.bus.publish("output.display", "⚠️ 深度阅读工具未安装")
            return

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(
            dispatch("deep_read", {"mode": "novel", "source": source, "target_length": target_length}, {})
        )
        loop.close()

        if result.get("success"):
            content = result.get("content", "")
            if content:
                self.bus.publish("output.display", f"📖 精读结果：\n{content[:2000]}...")
                if len(content) > 2000:
                    self.bus.publish("output.display", "📁 内容较长，完整结果已展示在聊天窗上方。")
            else:
                self.bus.publish("output.display", "深度阅读完成，但无内容返回。")
        else:
            self.bus.publish("output.display", f"深度阅读失败：{result.get('error')}")

    def _execute_create_file(self, user_input: str):
        """执行文件创建"""
        print(f"📁 [智能调度] 文件创建: {user_input[:50]}...")

        # 提取文件名
        filename_match = re.search(r'([a-zA-Z0-9_\-\.]+\.(txt|py|md|json))', user_input)
        filename = filename_match.group(1) if filename_match else "untitled.txt"
        filename = self._sanitize_filename(filename)

        # 提取内容
        content = self._extract_explicit_content(user_input)

        # 判断是否需要生成代码
        code_keywords = ["游戏", "贪吃蛇", "程序", "脚本", "实现", "编写", "写一个", "写个", "编一个",
                         "代码", "函数", "类", "算法", "冒泡", "递归", "爬虫"]
        is_complex_code = not content or any(kw in user_input for kw in code_keywords)

        if is_complex_code:
            prompt = f"请根据以下要求生成完整的代码，只输出纯代码，不要任何解释或额外文字，确保代码可直接运行：\n{user_input}"
            print(f"🤖 [TaskExecutor] 调用模型生成代码...")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            gen_result = loop.run_until_complete(
                generate_text({"prompt": prompt, "temperature": 0.3}, {})
            )
            loop.close()
            if gen_result.get("success"):
                content = gen_result.get("content", "")
                print(f"✅ [TaskExecutor] 代码生成成功，长度 {len(content)} 字符")
            else:
                self.bus.publish("output.display", f"内容生成失败：{gen_result.get('error')}")
                return

        if content:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(
                save_file({"filename": filename, "location": "desktop", "content": content}, {})
            )
            loop.close()
            if result.get("success"):
                self.bus.publish("output.display", f"文件已创建：{result['filepath']}")
                # 如果是工具脚本，自动注册到工具目录
                if content.strip().startswith("# @tool") or filename.startswith("tool_"):
                    tool_name = os.path.splitext(filename)[0]
                    desc = f"用户创建的脚本工具：{user_input[:50]}"
                    catalog = getattr(self.bus, 'tools_catalog', None)
                    if catalog:
                        catalog.register_tool(tool_name, desc, source="user")
                        self.bus.publish("output.display", f"🔧 新工具已注册：{tool_name}")
            else:
                self.bus.publish("output.display", f"创建失败：{result.get('error')}")
        else:
            self.bus.publish("output.display", "无法提取或生成文件内容")

    def _execute_search(self, params: dict):
        """执行搜索"""
        query = params.get("query", "")
        if not query:
            self.bus.publish("output.display", "⚠️ 未指定搜索关键词")
            return

        print(f"🔍 [智能调度] 搜索: {query}")

        if not is_tool_available("web_browser_search"):
            self.bus.publish("output.display", "⚠️ 浏览器搜索工具未安装")
            return

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(dispatch("web_browser_search", {"query": query}, {}))
        loop.close()

        if result.get("success"):
            self.bus.publish("output.display", f"搜索结果：\n{result.get('results', '')[:800]}...")
        else:
            self.bus.publish("output.display", f"搜索失败：{result.get('error')}")

    def _execute_visual_explore(self, params: dict, user_input: str):
        """执行视觉探索"""
        prompt_text = params.get("prompt", user_input)
        print(f"👁️ [智能调度] 视觉探索: {prompt_text[:50]}...")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(
            dispatch("capture_screen", {}, {})
        )
        if result.get("success"):
            img = result.get("image_base64")
            ana_result = loop.run_until_complete(
                dispatch("analyze_image_with_qwen", {"image_base64": img, "prompt": prompt_text}, {})
            )
            if ana_result.get("success"):
                self.bus.publish("output.display", f"👁️ 屏幕分析：{ana_result.get('description', '')[:500]}...")
            else:
                self.bus.publish("output.display", f"图像分析失败：{ana_result.get('error')}")
        else:
            self.bus.publish("output.display", f"截图失败：{result.get('error')}")
        loop.close()

    def _execute_script_logic(self, params: dict, user_input: str):
        """执行脚本生成与运行，并自动注册工具"""
        prompt = f"请根据以下要求生成完整的 Python 代码，只输出纯代码：\n{user_input}"
        print(f"🤖 [智能调度] 脚本生成...")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        gen_result = loop.run_until_complete(
            generate_text({"prompt": prompt, "temperature": 0.3}, {})
        )
        if gen_result.get("success"):
            code = gen_result.get("content", "")
            filename = f"script_{int(time.time())}.py"
            save_result = loop.run_until_complete(
                save_file({"filename": filename, "location": "desktop", "content": code}, {})
            )
            if save_result.get("success"):
                filepath = save_result.get("filepath")
                self.bus.publish("output.display", f"脚本已保存：{filepath}")

                # 自动注册工具（如果脚本以 # @tool 开头或文件名以 tool_ 开头）
                if code.strip().startswith("# @tool") or filename.startswith("tool_"):
                    tool_name = os.path.splitext(filename)[0]
                    desc = f"用户创建的脚本工具：{user_input[:50]}"
                    catalog = getattr(self.bus, 'tools_catalog', None)
                    if catalog:
                        catalog.register_tool(tool_name, desc, source="user")
                        self.bus.publish("output.display", f"🔧 新工具已注册：{tool_name}")

                # 可选：执行脚本
                exec_result = loop.run_until_complete(
                    dispatch("execute_script", {"script": code, "filename": filename, "location": "desktop"}, {})
                )
                if exec_result.get("success"):
                    self.bus.publish("output.display", f"运行结果：\n{exec_result.get('output', '')[:500]}...")
                else:
                    self.bus.publish("output.display", f"运行失败：{exec_result.get('error')}")
            else:
                self.bus.publish("output.display", f"保存失败：{save_result.get('error')}")
        else:
            self.bus.publish("output.display", f"代码生成失败：{gen_result.get('error')}")
        loop.close()

    def _execute_plan(self, user_input: str):
        """兜底：使用通用规划器"""
        parsed = self.planner.parse_instruction(user_input)
        tasks = self.planner.plan_tasks(parsed)
        if not tasks or (len(tasks) == 1 and tasks[0].get("action") == "chat"):
            self.bus.publish("user_input.main", {"message": user_input, "user_id": "user"})
            return

        context = {"original_goal": user_input}
        results = []
        for task in tasks:
            action = task["action"]
            params = task["params"]
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(self.execute_task(task, context))
            loop.close()
            results.append(result)
            if result.get("success"):
                if "content" in result:
                    context["last_generated_content"] = result["content"]
                if "summary" in result:
                    context["last_summary"] = result["summary"]
                if "filepath" in result:
                    context["last_filepath"] = result["filepath"]
                if "results" in result:
                    context["last_search_results"] = result["results"]
                if "text" in result:
                    context["last_extracted_text"] = result["text"]
                if "output" in result:
                    context["last_script_output"] = result["output"]
            else:
                break

        if results and results[-1].get("success"):
            msg = (results[-1].get("content") or 
                   results[-1].get("filepath") or 
                   results[-1].get("summary") or 
                   results[-1].get("output") or 
                   "任务完成")
        else:
            msg = "执行失败: " + "; ".join([r.get("error", "未知错误") for r in results if not r.get("success")])
        self.bus.publish("output.display", f"执行结果：{msg}")