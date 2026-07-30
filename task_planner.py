# task_planner.py (v14.11 - 清理冗余关键词规则，保留核心规划能力)
import json
import re
import asyncio
from openai import OpenAI
from config import DEFAULT_BASE_URL, DEFAULT_MODEL, DEFAULT_API_KEY
from model_router import ModelRouter


class TaskPlanner:
    def __init__(self, router: ModelRouter = None):
        self.client = OpenAI(base_url=DEFAULT_BASE_URL, api_key=DEFAULT_API_KEY)
        self.model = DEFAULT_MODEL
        self.router = router or ModelRouter(max_concurrent_requests=1)

        self.available_actions = [
            "generate_text", "create_folder", "save_file",
            "summarize_text", "open_browser", "send_email", "execute_command",
            "copy_file", "generate_patch", "web_browser_search",
            "retrieve_memory_semantic", "retrieve_memory_by_path",
            "retrieve_memory_by_tags", "retrieve_memory_by_time",
            "get_memory_detail", "retrieve_memory_timeline",
            "capture_screen", "analyze_image_with_qwen",
            "capture_full_page_screenshot", "extract_full_page_text",
            "execute_script", "deep_read"
        ]

    def _clean_json_string(self, s: str) -> str:
        return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', s)

    def _build_context_description(self, context: dict = None) -> str:
        context = context or {}
        lines = []
        if context.get("desktop_files"):
            lines.append(f"桌面上当前可见的文件/文件夹：{', '.join(context['desktop_files'][:10])}")
        if context.get("current_app"):
            lines.append(f"当前活跃的应用程序：{context['current_app']}")
        if context.get("memory_hint"):
            lines.append(f"记忆宫殿中的相关信息：{context['memory_hint']}")
        if context.get("recent_conversation"):
            lines.append(f"近期对话摘要：{context['recent_conversation']}")
        if context.get("system_state"):
            state = context["system_state"]
            lines.append(f"系统状态：好奇心能量 {state.get('curiosity_energy', 0.5):.0%}，主导欲望 {state.get('dominant_desire', '求知')}")
        return "\n".join(lines) if lines else "（无额外情境信息）"

    def parse_instruction(self, user_input: str, context: dict = None) -> dict:
        context = context or {}
        context_desc = self._build_context_description(context)
        actions_list = "\n".join([f"- {action}" for action in self.available_actions])

        prompt = f"""你是一个智能任务规划器。请将用户的指令分解为可执行的任务序列。

【可用原子动作】
{actions_list}

【当前情境】
{context_desc}

【用户指令】
{user_input}

请严格按照以下两步进行推理，并最终输出 JSON 格式的任务规划：

【第一步：理解内容是什么】
分析用户指令和当前情境，明确：
- 用户真正想要达成的最终目标是什么？
- 当前环境提供了哪些可利用的资源或信息？
- 指令中是否存在模糊点？

【第二步：规划你想做什么】
将用户目标分解为具体、有序的任务序列。输出格式为 JSON 对象，支持两种结构：

1. 单任务：
{{"intent": "execute" 或 "chat", "task_type": "动作名称", "params": {{"参数名": "参数值"}}}}

2. 多子任务：
{{"intent": "execute", "subtasks": [
    {{"task_type": "动作名称", "params": {{...}}}},
    ...
]}}

注意：
- 如果涉及深度阅读或文本解读，请使用 deep_read 动作。
- 如果涉及编写并运行脚本，请使用 generate_text + save_file + execute_script。
- 如果涉及视觉理解，请使用 capture_screen + analyze_image_with_qwen。
- 只输出 JSON，不要其他任何内容。"""
        try:
            if self.router:
                content = self.router.call(
                    role="task_planner",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                )
            else:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                )
                content = response.choices[0].message.content

            content = content.strip()
            content = self._clean_json_string(content)
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
            else:
                parsed = json.loads(content)

            parsed = self._normalize_parsed(parsed)
            return parsed
        except Exception as e:
            print(f"任务规划器LLM解析失败，降级到本地规则: {e}")
            return self._fallback_parse(user_input)

    def _normalize_parsed(self, parsed: dict) -> dict:
        if "subtasks" in parsed:
            for sub in parsed["subtasks"]:
                self._normalize_subtask(sub)
        elif "task_type" in parsed:
            self._normalize_subtask(parsed)
        return parsed

    def _normalize_subtask(self, task: dict):
        task_type = task.get("task_type", "")
        params = task.get("params", {})
        if task_type in ("create_file", "save_file"):
            if not params.get("location"):
                params["location"] = "desktop"
        elif task_type == "create_folder":
            if not params.get("location"):
                params["location"] = "desktop"
        task["params"] = params

    def _fallback_parse(self, user_input: str) -> dict:
        """本地降级规则：只处理最基础、最明确的模式，其余交给 LLM"""
        # 1. 文件创建模式
        desktop_match = re.search(r'在\s*桌\s*面\s*创\s*建\s*[“"\']?([^“”"\'\s]+\.(?:txt|py|md|json|js|html|css))[”"\']?', user_input)
        if not desktop_match:
            desktop_match = re.search(r'在\s*Desktop\s*创\s*建\s*[“"\']?([^“”"\'\s]+\.(?:txt|py|md|json|js|html|css))[”"\']?', user_input)
        if not desktop_match:
            desktop_match = re.search(r'创\s*建\s*桌\s*面\s*文\s*件\s*[“"\']?([^“”"\'\s]+\.(?:txt|py|md|json|js|html|css))[”"\']?', user_input)

        if desktop_match:
            filename = desktop_match.group(1)
            content = ""
            content_match = re.search(r'内容[是为:：]\s*[“"\']?(.+?)[”"\']?(?:$|，|。|！|\n)', user_input)
            if content_match:
                content = content_match.group(1).strip()
            return {
                "intent": "execute",
                "task_type": "create_file",
                "params": {"filename": filename, "content": content, "location": "desktop"}
            }

        # 2. 发送邮件模式
        if "发送邮件" in user_input or "发邮件" in user_input:
            to_match = re.search(r'给[：:]\s*([^\s，。！,]+)', user_input)
            if not to_match:
                to_match = re.search(r'[给发][至到]?\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', user_input)
            body_match = re.search(r'内容[是为:：]\s*["\']?(.+?)["\']?(?:$|，|。|！)', user_input)
            if not body_match:
                body_match = re.search(r'正文[是为:：]\s*["\']?(.+?)["\']?(?:$|，|。|！)', user_input)
            to_addr = to_match.group(1) if to_match else ""
            body = body_match.group(1) if body_match else "这是来自念言AI的测试邮件。"
            return {
                "intent": "execute",
                "task_type": "send_email",
                "params": {"to": to_addr, "subject": "来自智脑AI", "body": body}
            }

        # 3. 搜索模式
        if "搜索" in user_input or "查" in user_input:
            query_match = re.search(r'[“"]([^”"]+)[”"]', user_input)
            if query_match:
                query = query_match.group(1)
            else:
                parts = user_input.split("搜索", 1)
                query = parts[1].strip() if len(parts) > 1 else user_input
            return {
                "intent": "execute",
                "task_type": "web_browser_search",
                "params": {"query": query}
            }

        # 4. 创建文件夹模式
        folder_match = re.search(r'(创建|新建).*文件夹.*[“"]([^”"]+)[”"]', user_input)
        if folder_match:
            folder_name = folder_match.group(2)
            return {
                "intent": "execute",
                "task_type": "create_folder",
                "params": {"path": folder_name, "location": "desktop"}
            }

        # 5. 兜底：单文件
        filename_match = re.search(r'([a-zA-Z0-9_\-\.]+\.(txt|py|md|json))', user_input)
        filename = filename_match.group(1) if filename_match else "untitled.txt"
        content_match = re.search(r'内容[是为:：]\s*(.+?)(?:$|\n|，且|，并)', user_input, re.DOTALL) or \
                        re.search(r'内容为\s*[`]?(.+?)[`]?(?:$|\n|，|。)', user_input, re.DOTALL)
        content = content_match.group(1).strip() if content_match else ""
        location = "desktop" if ("桌面" in user_input or "Desktop" in user_input) else "desktop"
        return {
            "intent": "execute",
            "task_type": "create_file",
            "params": {"filename": filename, "content": content, "location": location}
        }

    def plan_tasks(self, parsed: dict) -> list:
        if "subtasks" in parsed:
            tasks = []
            for sub in parsed["subtasks"]:
                task_type = sub.get("task_type")
                params = sub.get("params", {})
                action_task = self._build_action_task(task_type, params)
                if action_task:
                    if isinstance(action_task, list):
                        tasks.extend(action_task)
                    else:
                        tasks.append(action_task)
            return tasks

        task_type = parsed.get("task_type", "chat")
        params = parsed.get("params", {})
        action_task = self._build_action_task(task_type, params)
        if action_task:
            if isinstance(action_task, list):
                return action_task
            else:
                return [action_task]
        return [{"action": "chat", "params": {}}]

    def _build_action_task(self, task_type: str, params: dict):
        if task_type == "write_story":
            genre = params.get("genre", "")
            word_count = params.get("word_count", 500)
            prompt = f"写一篇{word_count}字的{genre}小说。" if genre else f"写一篇{word_count}字的小说。"
            filename = params.get("filename", f"{genre}_story.txt" if genre else "story.txt")
            return [
                {"action": "generate_text", "params": {"prompt": prompt}},
                {"action": "save_file", "params": {"filename": filename, "location": params.get("output", "desktop")}}
            ]
        elif task_type == "create_file":
            filename = params.get("filename", "untitled.txt")
            content = params.get("content", "")
            location = params.get("location") or "desktop"
            if not content and params.get("prompt"):
                return [
                    {"action": "generate_text", "params": {"prompt": params["prompt"]}},
                    {"action": "save_file", "params": {"filename": filename, "location": location}}
                ]
            return {"action": "save_file", "params": {"filename": filename, "location": location, "content": content}}
        elif task_type == "create_folder":
            path = params.get("path", "")
            location = params.get("location") or "desktop"
            return {"action": "create_folder", "params": {"path": path, "location": location}}
        elif task_type == "generate_code":
            prompt = params.get("prompt", "")
            filename = params.get("filename", "script.py")
            location = params.get("location") or "desktop"
            return [
                {"action": "generate_text", "params": {"prompt": prompt}},
                {"action": "save_file", "params": {"filename": filename, "location": location}}
            ]
        elif task_type == "search_and_summarize":
            query = params.get("query", "")
            word_count = params.get("word_count", 300)
            return [
                {"action": "web_browser_search", "params": {"query": query}},
                {"action": "summarize_text", "params": {"max_length": word_count}},
                {"action": "save_file", "params": {"filename": "summary.txt", "location": params.get("output", "desktop")}}
            ]
        elif task_type == "open_web":
            if params.get("search"):
                return {"action": "open_browser", "params": {"search": params["search"]}}
            elif params.get("url"):
                return {"action": "open_browser", "params": {"url": params["url"]}}
        elif task_type == "send_email":
            return {"action": "send_email", "params": params}
        elif task_type == "run_command":
            return {"action": "execute_command", "params": params}
        elif task_type == "copy_file":
            return {"action": "copy_file", "params": params}
        elif task_type == "generate_patch":
            return {"action": "generate_patch", "params": params}
        elif task_type == "extract_full_page_text":
            return {"action": "extract_full_page_text", "params": params}
        elif task_type == "capture_full_page_screenshot":
            return {"action": "capture_full_page_screenshot", "params": params}
        elif task_type == "web_browser_search":
            return {"action": "web_browser_search", "params": params}
        elif task_type == "visual_explore":
            return [
                {"action": "capture_screen", "params": {}},
                {"action": "analyze_image_with_qwen", "params": {"prompt": params.get("prompt", "描述屏幕内容")}}
            ]
        elif task_type == "execute_script":
            return {
                "action": "execute_script",
                "params": {
                    "script": params.get("script", ""),
                    "filename": params.get("filename", None),
                    "location": params.get("location") or "desktop",
                    "timeout": params.get("timeout", 30)
                }
            }
        elif task_type == "deep_read":
            return {
                "action": "deep_read",
                "params": {
                    "mode": params.get("mode", "novel"),
                    "source": params.get("source", ""),
                    "target_length": params.get("target_length", 32000)
                }
            }

        if task_type in self.available_actions:
            return {"action": task_type, "params": params}

        return {"action": "chat", "params": {}}