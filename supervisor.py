# supervisor.py (修复版：修正导入，移除 max_tokens 硬编码)
import json
import re
import os
import time
import asyncio
import uuid
import random
from concurrent.futures import ThreadPoolExecutor
from message_bus import MessageBus
from model_router import ModelRouter  # 修正导入
from atomic_actions import save_file, generate_text, create_folder
from creation_manager import CreationManager


class Supervisor:
    def __init__(self, bus: MessageBus, palace_memory=None):
        self.bus = bus
        self.router = getattr(bus, 'model_router', None) or ModelRouter(max_concurrent_requests=1)
        self.executor = ThreadPoolExecutor(max_workers=5)
        bus.subscribe("user.goal", self.on_goal)
        self.desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
        self.creation_mgr = CreationManager(bus, palace_memory)
        self.palace = palace_memory

    def on_goal(self, goal: str):
        loop = getattr(self.bus, 'global_loop', None)
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(self._async_on_goal(goal), loop)
        else:
            try:
                asyncio.run(self._async_on_goal(goal))
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self._async_on_goal(goal))

    async def _async_on_goal(self, goal: str):
        creation_keywords = ["续写", "创作", "第", "章", "小说", "故事", "写一篇", "写一部", "写个", "写本", "写一册"]
        is_creation = any(kw in goal for kw in creation_keywords)

        if is_creation:
            novel_name = self._extract_novel_name(goal)
            if not novel_name:
                novel_name = f"小说创作_{time.strftime('%Y%m%d_%H%M%S')}"
                print(f"[Supervisor] 自动生成作品名：{novel_name}")

            project_path = self.creation_mgr.ensure_project_structure(novel_name)
            self.bus.publish("output.display", f"📁 项目已就绪：{novel_name}")

            chapter_match = re.search(r'第(\d+)章', goal)
            chapter_num = int(chapter_match.group(1)) if chapter_match else None

            if chapter_num == 1 or chapter_num is None:
                await self._ensure_initial_settings(project_path, novel_name, goal)

            await self.creation_mgr.generate_chapter(project_path, goal, chapter_num)
            return

        # 原有任务拆解模式
        subtasks = self.decompose_goal(goal)
        if not subtasks:
            self.bus.publish("output.display", f"无法拆解目标：{goal}")
            return

        print(f"[Supervisor] 拆解得到 {len(subtasks)} 个子任务")
        await self._execute_subtasks(subtasks, goal)

    def _extract_novel_name(self, goal: str) -> str:
        patterns = [
            r'续写[《]([^》]+)[》]',
            r'创作[《]([^》]+)[》]',
            r'《([^》]+)》续写',
            r'《([^》]+)》第',
            r'名为[《]([^》]+)[》]',
            r'小说[《]([^》]+)[》]',
        ]
        for pattern in patterns:
            match = re.search(pattern, goal)
            if match:
                return match.group(1)
        return ""

    def _extract_genre_and_protagonist(self, goal: str) -> tuple:
        """从用户目标中识别体裁与主角姓名"""
        genre_match = re.search(r'(修仙|玄幻|科幻|悬疑|言情|武侠|都市|历史|游戏|同人|末世|无限流|奇幻)', goal)
        genre = genre_match.group(1) if genre_match else random.choice(["修仙", "玄幻", "都市"])
        
        name_match = re.search(r'主角[是为]?[：:]?\s*([^\s，。、]{2,4})', goal)
        if name_match:
            protagonist = name_match.group(1)
        else:
            surnames = ["林", "苏", "李", "王", "张", "陈", "萧", "叶", "楚", "秦", "顾", "沈", "陆", "周"]
            names = ["逸", "尘", "云", "天", "宇", "欣", "瑶", "雪", "凡", "辰", "轩", "涵", "泽", "皓"]
            protagonist = random.choice(surnames) + random.choice(names)
            if random.random() > 0.5:
                protagonist += random.choice(names)
        return genre, protagonist

    def _get_creative_preferences(self) -> str:
        """
        从记忆宫殿中检索用户的历史创作偏好（体裁、风格、命名习惯等）。
        返回一段格式化的参考文本，用于注入初始设定生成的 prompt。
        """
        if not self.palace:
            return ""

        preferences = []
        try:
            queries = [
                ("用户偏好的小说体裁", "用户 偏好 体裁 创作 风格"),
                ("用户常用的主角姓名", "主角 姓名 命名 习惯"),
                ("用户喜欢的世界观设定", "世界观 设定 偏好"),
            ]
            for desc, query in queries:
                results = self.palace.retrieve_by_semantic(
                    query=query,
                    top_k=2,
                    threshold=0.4,
                    mem_type="self_meta",
                    include_chaos=False
                )
                if not results:
                    results = self.palace.retrieve_by_semantic(
                        query=query,
                        top_k=2,
                        threshold=0.4,
                        mem_type="fact",
                        include_chaos=False
                    )
                for r in results:
                    if r.get('answer'):
                        preferences.append(f"- {desc}：{r['answer'][:100]}")
            
            if preferences:
                return "【用户创作偏好参考】\n" + "\n".join(preferences) + "\n"
        except Exception as e:
            print(f"检索创作偏好失败: {e}")
        return ""

    async def _ensure_initial_settings(self, project_path: str, novel_name: str, goal: str):
        world_path = os.path.join(project_path, "00_世界设定", "世界设定.txt")
        char_path = os.path.join(project_path, "01_人物设定", "人物设定.json")

        need_generate = False
        if os.path.exists(world_path):
            with open(world_path, "r", encoding="utf-8") as f:
                content = f.read()
                if "【时代背景】\n【主要地域】" in content and len(content) < 100:
                    need_generate = True
        else:
            need_generate = True

        if need_generate:
            self.bus.publish("output.display", "📝 正在生成初始设定...")
            genre, protagonist = self._extract_genre_and_protagonist(goal)
            age = random.randint(16, 24)

            preferences_hint = self._get_creative_preferences()

            prompt = f"""请为{genre}小说《{novel_name}》生成初始设定，包括：
1. 时代背景（一句话）
2. 主要地域（2-3个地点）
3. 力量体系（简要说明，若为科幻或都市可改为相应设定）
4. 主角姓名固定为{protagonist}，{age}岁，性格勇敢善良但内心略有软弱，背景和目标请合理设定。

{preferences_hint}
输出纯中文，分段落清晰呈现。"""
            # 移除 max_tokens 硬编码，由配置决定
            result = await generate_text({"prompt": prompt}, {})
            if result.get("success"):
                content = result.get("content", "")
                with open(world_path, "w", encoding="utf-8") as f:
                    f.write(f"【作品名称】{novel_name}\n\n" + content)
                self._update_character_json(char_path, protagonist, age, content)
                self.bus.publish("output.display", "✅ 初始设定已生成")

    def _update_character_json(self, char_path: str, name: str, age: int, content: str):
        try:
            with open(char_path, "r", encoding="utf-8") as f:
                chars = json.load(f)
            chars["protagonist"] = {
                "name": name,
                "age": age,
                "traits": ["勇敢", "善良", "内心略有软弱"],
                "background": "自幼孤苦，被隐士收养",
                "goal": "成为强大的存在"
            }
            with open(char_path, "w", encoding="utf-8") as f:
                json.dump(chars, f, indent=2, ensure_ascii=False)
        except:
            pass

    async def _execute_subtasks(self, subtasks: list, goal: str):
        for task in subtasks:
            if isinstance(task, dict):
                action = task.get("action")
                if action == "generate_text":
                    prompt = task.get("prompt", "")
                    # 移除 max_tokens 硬编码
                    await generate_text({"prompt": prompt}, {})
                elif action == "save_file":
                    filename = task.get("filename", "untitled.txt")
                    content = task.get("content", "")
                    if content:
                        await save_file({"filename": filename, "location": "desktop", "content": content}, {})
                elif action == "create_folder":
                    path = task.get("path", "")
                    await create_folder({"path": path, "location": "desktop"}, {})
        self.bus.publish("output.display", "✅ 所有任务执行完毕。")

    def decompose_goal(self, goal: str, retry=2):
        prompt = f"""你是一个任务规划器。请将以下用户目标拆解为具体可执行的子任务，并以JSON数组返回。
支持的动作：generate_text, save_file, create_folder。
用户目标：{goal}
只输出JSON数组。"""
        for attempt in range(retry + 1):
            try:
                response = self.router.call("executor", [{"role": "user", "content": prompt}])
                json_match = re.search(r'\[.*\]', response, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group())
            except:
                continue
        return None

    def _sanitize_filename(self, filename: str) -> str:
        allowed_pattern = r'[^\u4e00-\u9fa5a-zA-Z0-9._\-/\\]'
        cleaned = re.sub(allowed_pattern, '', filename)
        return cleaned.strip() or "untitled.txt"