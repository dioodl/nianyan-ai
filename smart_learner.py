# smart_learner.py (v14.11 - 工具目录集成)
import asyncio
import random
import socket
import time
import json
import os
import traceback
from message_bus import MessageBus
from auto_learner import AutoLearner
from config import BOOKSHELF_DIR, ENABLE_SMART_LEARNER, BOOKSHELF_READ_HISTORY

from tools.tool_dispatcher import dispatch, is_tool_available
from prompts.registry import get_prompt

try:
    from task_queue import TaskPriority
    TASK_QUEUE_AVAILABLE = True
except ImportError:
    TASK_QUEUE_AVAILABLE = False
    class TaskPriority:
        LOW = 4


class SmartLearner:
    """
    智能决策器 v14.11 - 跨学科议会深度自习 + 书架书籍优先探索 + 已读标记 + 工具目录集成
    """
    def __init__(self, bus: MessageBus, palace_memory, auto_learner: AutoLearner, cognitive_engine=None):
        self.bus = bus
        self.palace = palace_memory
        self.learner = auto_learner
        self.cognitive_engine = cognitive_engine
        self.last_decision_time = 0
        self.decision_interval = 3600
        self.paused_by_user = False
        self.global_loop = getattr(bus, 'global_loop', None)
        self.router = getattr(bus, 'model_router', None)

        self._deep_seminar_semaphore = asyncio.Semaphore(2)
        self._deep_task_lock = asyncio.Lock()

        self.cross_discipline_perspectives = {
            "philosopher": {
                "perspective": "哲学",
                "prompt": get_prompt("smart_learner/perspective_philosopher.txt") or "你是一位哲学家，擅长追问本质、审视前提、进行概念分析。请从你的专业视角，对以下学习主题给出简短而深刻的见解（不超过100字）。"
            },
            "scientist": {
                "perspective": "科学",
                "prompt": get_prompt("smart_learner/perspective_scientist.txt") or "你是一位科学家，擅长寻找规律、建立模型、进行系统性思考。请从你的专业视角，对以下学习主题给出简短而深刻的见解（不超过100字）。"
            },
            "poet": {
                "perspective": "诗意",
                "prompt": get_prompt("smart_learner/perspective_poet.txt") or "你是一位诗人，擅长用隐喻和意象捕捉事物的灵魂，寻找美感与共鸣。请从你的专业视角，对以下学习主题给出简短而深刻的见解（不超过100字）。"
            },
            "historian": {
                "perspective": "历史",
                "prompt": get_prompt("smart_learner/perspective_historian.txt") or "你是一位历史学者，擅长追溯渊源、发现模式、从时间维度理解变迁。请从你的专业视角，对以下学习主题给出简短而深刻的见解（不超过100字）。"
            },
            "practitioner": {
                "perspective": "实践",
                "prompt": get_prompt("smart_learner/perspective_practitioner.txt") or "你是一位实践者，关注如何落地、第一步做什么、有什么具体方法。请从你的专业视角，对以下学习主题给出简短而深刻的见解（不超过100字）。"
            },
            "skeptic": {
                "perspective": "批判",
                "prompt": get_prompt("smart_learner/perspective_skeptic.txt") or "你是一位温和的怀疑者，擅长发现漏洞、指出边界条件、提出反例。请从你的专业视角，对以下学习主题给出简短而深刻的见解（不超过100字）。"
            }
        }

        self.default_topics = [
            "最新人工智能技术进展",
            "Python异步编程最佳实践",
            "机器学习模型优化技巧",
            "深度学习框架对比"
        ]

        if ENABLE_SMART_LEARNER:
            bus.subscribe("system.idle", self.on_idle)
            bus.subscribe("control.user_activity", self.on_user_activity_pause)
            bus.subscribe("system.idle", self.on_system_idle)
            bus.subscribe("smart_learner.manual", self.on_manual_learn)
            bus.subscribe("smart_learner.stop", self.on_manual_stop)
            bus.subscribe("smart_learner.deep_study", self.on_manual_deep_study)

    # ---------- 辅助方法 ----------
    def on_user_activity_pause(self, data):
        self.paused_by_user = True
        print("⏸️ [SmartLearner] 收到用户活动信号，暂停决策")

    def on_system_idle(self, data):
        if self.paused_by_user:
            self.paused_by_user = False
            print("▶️ [SmartLearner] 系统空闲，恢复决策")
        else:
            self.paused_by_user = False

    def manual_learn(self):
        if self.paused_by_user:
            print("⏸️ [SmartLearner] 用户暂停中，忽略手动自习")
            return
        loop = self.global_loop
        if not loop: loop = getattr(self.bus, 'global_loop', None)
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(self.decide_and_learn(), loop)
            print("📚 [SmartLearner] 手动触发自习")

    def on_manual_learn(self, data): self.manual_learn()
    def manual_stop(self): self.paused_by_user = True; print("⏹️ [SmartLearner] 手动停止自习")
    def on_manual_stop(self, data): self.manual_stop()

    def manual_deep_study(self):
        if self.paused_by_user: return
        loop = self.global_loop
        if not loop: loop = getattr(self.bus, 'global_loop', None)
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(self._manual_deep_study_async(), loop)
            print("🧠 [SmartLearner] 手动触发深度自习")

    def on_manual_deep_study(self, data): self.manual_deep_study()

    async def _manual_deep_study_async(self):
        query = self.get_curiosity_topic()
        await self._deep_seminar_learn(query)

    def is_network_available(self) -> bool:
        try: socket.create_connection(("8.8.8.8", 53), timeout=3); return True
        except OSError: return False

    def list_unread_bookshelf_files(self) -> list:
        if not os.path.exists(BOOKSHELF_DIR): return []
        read = set()
        if os.path.exists(BOOKSHELF_READ_HISTORY):
            try:
                with open(BOOKSHELF_READ_HISTORY, 'r', encoding='utf-8') as f: read = set(json.load(f))
            except: pass
        return [f for f in os.listdir(BOOKSHELF_DIR) if f.endswith(('.txt', '.json', '.jsonl', '.md')) and f not in read]

    def count_unread_bookshelf_files(self) -> int: return len(self.list_unread_bookshelf_files())

    def _mark_book_as_read(self, book_name: str):
        read = set()
        if os.path.exists(BOOKSHELF_READ_HISTORY):
            try:
                with open(BOOKSHELF_READ_HISTORY, 'r', encoding='utf-8') as f: read = set(json.load(f))
            except: pass
        read.add(book_name)
        try:
            with open(BOOKSHELF_READ_HISTORY, 'w', encoding='utf-8') as f: json.dump(list(read), f)
            print(f"📘 [SmartLearner] 已标记已读: {book_name}")
        except Exception as e: print(f"⚠️ 标记已读失败: {e}")

    def get_curiosity_topic(self) -> str:
        unread_files = self.list_unread_bookshelf_files()
        if unread_files:
            chosen = random.choice(unread_files)
            print(f"📚 [SmartLearner] 书架选题: {chosen}")
            return f"阅读书籍：{chosen}"

        try:
            from error_knowledge import ErrorKnowledge
            ek = ErrorKnowledge(self.palace)
            errors = ek.get_unsolved_errors(limit=3)
            if errors:
                topic = errors[0].get('question', '').replace('[错误报告] ', '')
                if topic:
                    print(f"📋 [SmartLearner] 错误驱动选题: {topic}")
                    return f"修复问题：{topic}"
        except: pass

        try:
            index = self.palace.index
            candidates = []
            energy = self.cognitive_engine.get_state().get("curiosity_energy", 0.5) if self.cognitive_engine else 0.5
            min_crack = 1 if energy > 0.6 else 2
            for entry in index.get("entries", []):
                if entry.get("is_chaos"): continue
                cd, ut, sm = entry.get("crack_depth", 0), entry.get("utility", 0.5), entry.get("summary", "")
                if cd >= min_crack and ut < 0.7 and sm: candidates.append((cd * (1 - ut), sm))
            if candidates:
                candidates.sort(key=lambda x: x[0], reverse=True)
                topic = f"深入学习：{candidates[0][1]}"
                print(f"💡 [SmartLearner] 好奇心选题: {topic}")
                return topic
        except: pass

        try:
            if self.palace:
                all_entries = self.palace.index.get("entries", [])
                if all_entries:
                    sample = random.sample(all_entries, min(10, len(all_entries)))
                    best_entry, lowest_sim = None, 1.0
                    for entry in sample:
                        summary = entry.get("summary", "")
                        if not summary: continue
                        similar = self.palace.retrieve_by_semantic(query=summary, top_k=1, threshold=0.0, mem_type="fact")
                        if similar:
                            sim = similar[0].get("similarity", 1.0)
                            if sim < lowest_sim: lowest_sim, best_entry = sim, entry
                    if best_entry and lowest_sim < 0.3:
                        topic = f"探索陌生领域：{best_entry.get('summary', '未知话题')}"
                        print(f"🌌 [SmartLearner] 最陌生话题选题: {topic}")
                        return topic
        except: pass

        fallback = random.choice(self.default_topics)
        print(f"💡 [SmartLearner] 使用默认话题: {fallback}")
        return fallback

    async def learn_from_search(self, query: str):
        print(f"🌐 [SmartLearner] 开始浏览器搜索: {query[:50]}...")
        if not is_tool_available("web_browser_search"):
            return {"success": False, "error": "浏览器搜索工具未安装"}
        try: result = await dispatch("web_browser_search", {"query": query}, {})
        except Exception as e: result = {"success": False, "error": str(e)}
        if result is None: result = {"success": False, "error": "搜索返回空值"}
        elif not isinstance(result, dict): result = {"success": False, "error": f"搜索返回异常类型"}
        if result.get("success"):
            self.palace.add_to_chaos(question=query, answer=result.get("results", ""), utility=0.7, source="smart_learner", mem_type="fact")
            self.bus.publish("output.display", f"🔍 智能学习：{query[:40]}...")
        return result

    async def _deep_seminar_learn(self, query: str):
        async with self._deep_task_lock:
            print(f"🎓 [深度研讨] 启动跨学科议会，探讨：{query[:50]}...")
            self.bus.publish("thinking.log", f"🎓 跨学科议会研讨：{query[:50]}")
            if not self.router: return await self._fallback_summarize(query)

            book_name = None
            if query.startswith("阅读书籍："):
                book_name = query[len("阅读书籍："):]
                book_path = os.path.join(BOOKSHELF_DIR, book_name)
                if os.path.exists(book_path):
                    try:
                        with open(book_path, 'r', encoding='utf-8') as f: content = f.read()[:3000]
                        query = f"书中内容摘要：{content}\n请围绕这本书的核心思想进行跨学科研讨。"
                    except Exception as e: print(f"⚠️ 读取书籍失败: {e}")

            async def call_perspective(name, config):
                async with self._deep_seminar_semaphore:
                    prompt = f"{config['prompt']}\n{query}"
                    try:
                        ans = await self.router.call_async(role="parliament_member", messages=[{"role": "user", "content": prompt}], temperature=0.7)
                        return name, ans, config['perspective']
                    except Exception as e: return name, f"[发言失败: {e}]", config['perspective']

            tasks = [call_perspective(name, cfg) for name, cfg in self.cross_discipline_perspectives.items()]
            results = await asyncio.gather(*tasks)

            valid_responses = [(n, a, p) for n, a, p in results if not a.startswith("[发言失败]")]
            if len(valid_responses) < 2: return await self._fallback_summarize(query)

            perspectives_text = "\n\n".join([f"【{p}视角】: {a}" for _, a, p in valid_responses])

            # 获取工具目录描述
            tools_desc = ""
            if hasattr(self.bus, 'tools_catalog'):
                tools_desc = self.bus.tools_catalog.get_tools_description()

            mentor_template = get_prompt("smart_learner/mentor_summary.txt") or (
                "你是一位博学的导师。以下是对学习主题「{query}」的多视角讨论。\n\n各视角发言：\n{perspectives_text}\n\n"
                "请你作为导师，完成以下任务：\n1. 综合各视角，提炼出3-5个核心知识点或洞见。\n"
                "2. 指出不同视角之间的共识与分歧，以及它们如何互补。\n3. 提出一个值得进一步深入探索的问题或方向。\n"
                "在提出探索方向时，请参考当前可用的工具来建议具体的行动计划。\n{tools_description}\n"
                "4. 用精炼、有启发性的语言输出总结，不超过300字。\n\n直接输出总结内容，不要加前缀。"
            )
            mentor_prompt = mentor_template.format(query=query, perspectives_text=perspectives_text, tools_description=tools_desc)

            try:
                final_summary = await self.router.call_async(role="creator", messages=[{"role": "user", "content": mentor_prompt}], temperature=0.6)
            except Exception as e:
                print(f"❌ [深度研讨] 导师总结失败: {e}")
                return await self._fallback_summarize(query)

            self.palace.add_to_chaos(question=f"跨学科研讨：{query}", answer=final_summary, utility=0.9, source="deep_seminar", mem_type="fact")
            print(f"✅ [深度研讨] 知识已内化，长度 {len(final_summary)} 字符")

            if self.cognitive_engine and hasattr(self.cognitive_engine, 'desire_vector'):
                desire = self.cognitive_engine.desire_vector
                if hasattr(desire, 'modify'): desire.modify("explore", 0.03); desire.modify("curiosity", 0.02)

            if book_name:
                self._mark_book_as_read(book_name)
                self.bus.publish("output.display", f"📚 深度自习完成：已读完《{book_name}》，并内化知识点。")
            else:
                self.bus.publish("output.display", f"📚 深度研讨完成：{query[:30]}...")
            return final_summary

    async def _fallback_summarize(self, query: str):
        print("📝 [深度研讨] 降级为本地简单总结...")
        return f"关于「{query}」的研讨未能深入，但已记录主题。"

    async def learn_from_deep_study(self):
        if self.router:
            query = self.get_curiosity_topic()
            await self._deep_seminar_learn(query)
        else:
            if self.learner and not self.learner.running: self.learner.start(); await asyncio.sleep(1)
            self.bus.publish("auto_learn.deep_study", None)

    async def _do_learn(self, query: str, energy: float):
        self.bus.publish("output.display", f"💡 好奇心驱动学习（能量 {energy:.0%}）：{query[:50]}...")
        if self.cognitive_engine: self.cognitive_engine.consume_energy(0.05, "smart_learn")
        online = self.is_network_available()
        if online and is_tool_available("web_browser_search"):
            result = await self.learn_from_search(query)
            if result.get("success"):
                if self.cognitive_engine: self.cognitive_engine.add_energy(0.1, "smart_learn_success")
            else:
                self.bus.publish("output.display", f"⚠️ 智能学习失败")
                if self.cognitive_engine: self.cognitive_engine.add_energy(0.02, "smart_learn_failed_effort")
        else:
            await self._deep_seminar_learn(query)
            if self.cognitive_engine: self.cognitive_engine.add_energy(0.08, "deep_seminar_success")

    async def decide_and_learn(self):
        if self.paused_by_user: return
        now = time.time()
        if now - self.last_decision_time < self.decision_interval: return
        self.last_decision_time = now
        if self.cognitive_engine:
            energy = self.cognitive_engine.get_state()["curiosity_energy"]
            if energy < 0.2: self.bus.publish("output.display", "🔋 好奇心能量过低，暂缓主动学习"); return
        else: energy = 0.5
        query = self.get_curiosity_topic()
        task_queue = getattr(self.bus, 'task_queue', None)
        if TASK_QUEUE_AVAILABLE and task_queue:
            def sync_learn():
                loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
                try: return loop.run_until_complete(self._do_learn(query, energy))
                except Exception as e: print(f"❌ [SmartLearner] 同步学习执行失败: {e}"); return {"success": False, "error": str(e)}
                finally: loop.close()
            task_queue.submit(name=f"智能学习: {query[:30]}", coro_or_func=sync_learn, priority=TaskPriority.LOW, timeout=None, retry_count=2, skip_lock=False)
            print(f"📋 [SmartLearner] 学习任务已入队")
        else: await self._do_learn(query, energy)

    def on_idle(self, data):
        if self.paused_by_user: return
        loop = self.global_loop or getattr(self.bus, 'global_loop', None)
        if loop and loop.is_running(): asyncio.run_coroutine_threadsafe(self.decide_and_learn(), loop)