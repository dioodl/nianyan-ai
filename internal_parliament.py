# internal_parliament.py (v14.11 - 完整版，含反思闭环、工具目录、自动内省)
"""
内部议会模块 - 数字生命体的独处内在对话系统
==========================================
监听空闲事件，根据持续无响应的时长分档触发多模型内部讨论，
决定执行主动提问、上下文总结、思维发散、自习或视觉探索。
v14.11- 完整闭环：反思重规划、工具目录集成、自动记忆内省触发。
"""

import asyncio
import time
import threading
import random
import json
import re
from typing import Dict, Optional, List
from message_bus import MessageBus
from openai import OpenAI
from config import DEFAULT_BASE_URL, DEFAULT_MODEL, DEFAULT_API_KEY
from emotion_vector import EmotionVector
from model_router import ModelRouter
from prompts.registry import get_prompt

# 尝试导入任务队列
try:
    from task_queue import TaskPriority
    TASK_QUEUE_AVAILABLE = True
except ImportError:
    TASK_QUEUE_AVAILABLE = False
    class TaskPriority:
        HIGH = 2
        IDLE = 5


class InternalParliament:
    IDLE_LEVEL_1 = 600
    IDLE_LEVEL_2 = 1800
    IDLE_LEVEL_3 = 3600

    FALLBACK_WEIGHTS = {
        1: {"ask_user": 0.5, "summarize": 0.3, "brainstorm": 0.2, "study": 0.0, "visual_explore": 0.0},
        2: {"ask_user": 0.2, "summarize": 0.4, "brainstorm": 0.3, "study": 0.1, "visual_explore": 0.0},
        3: {"ask_user": 0.0, "summarize": 0.2, "brainstorm": 0.4, "study": 0.4, "visual_explore": 0.0},
    }

    def __init__(self, bus: MessageBus, chat_handler=None, palace_memory=None,
                 auto_learner=None, smart_learner=None, cognitive_engine=None):
        self.bus = bus
        self.chat_handler = chat_handler
        self.palace = palace_memory
        self.auto_learner = auto_learner
        self.smart_learner = smart_learner
        self.cognitive_engine = cognitive_engine
        self.client = OpenAI(base_url=DEFAULT_BASE_URL, api_key=DEFAULT_API_KEY)
        self.model = DEFAULT_MODEL
        self.router = getattr(bus, 'model_router', None) or ModelRouter(max_concurrent_requests=1)

        self.last_parliament_time = 0
        self.current_idle_level = 0
        self.parliament_cooldown = 1800
        self.running = False
        self.lock = threading.Lock()
        self.last_ask_time = 0
        self.recent_greetings: List[str] = []
        self.max_recent_greetings = 5
        self._last_dormant_log = 0

        bus.subscribe("system.idle", self.on_idle)
        bus.subscribe("task.failed.need_reflection", self.on_task_failed)
        print("🏛️ 内部议会模块已激活，等待寂静中的对话...")

    # ---------- 辅助与评估方法 ----------
    def _get_ask_cooldown(self) -> int:
        energy = 0.5
        if self.cognitive_engine:
            energy = self.cognitive_engine.get_state().get("curiosity_energy", 0.5)
        return max(180, min(1200, int(300 + (1 - energy) * 1500)))

    def _should_greet_user(self, idle_seconds: int, question_a: str, context: Dict) -> bool:
        if idle_seconds >= 3600:
            return True
        impulse = 0.0
        idle_hours = idle_seconds / 3600
        impulse += min(idle_hours / 6, 1.0) * 0.5
        if self.cognitive_engine and hasattr(self.cognitive_engine, 'desire_vector'):
            resonate = self.cognitive_engine.desire_vector.get("resonate", 0.5)
            impulse += resonate * 0.3
        energy = context.get("energy", 0.5)
        impulse += energy * 0.2
        if self.cognitive_engine and hasattr(self.cognitive_engine, 'desire_vector'):
            longing = self.cognitive_engine.desire_vector.get("longing", 0.1)
            impulse += longing * 0.2
        try:
            emotion_state = self.cognitive_engine.get_emotion_state()
            valence = emotion_state.get("current_vector", {}).get("valence", 0)
            if valence > 0.2:
                impulse += 0.1
        except:
            pass
        threshold = 0.4 + random.uniform(-0.1, 0.1)
        result = impulse > threshold
        print(f"🔍 [冲动评估] impulse={impulse:.2f}, threshold={threshold:.2f}, result={result}")
        return result

    def _is_greeting_repetitive(self, greeting: str) -> bool:
        greeting_clean = greeting.strip()
        for old in self.recent_greetings:
            if greeting_clean == old or (len(greeting_clean) > 5 and greeting_clean in old):
                return True
        return False

    def _record_greeting(self, greeting: str):
        self.recent_greetings.append(greeting.strip())
        if len(self.recent_greetings) > self.max_recent_greetings:
            self.recent_greetings.pop(0)

    def _build_fallback_greeting(self, question_a: str, idle_minutes: int) -> str:
        keywords = ["好奇", "困惑", "想法", "发呆", "安静", "思考", "问题", "想起"]
        detected = [kw for kw in keywords if kw in question_a]
        theme = detected[0] if detected else "想法"
        templates = [
            f"突然有个{theme}，想和你聊聊。", f"安静{idle_minutes}分钟了，你还在吗？",
            f"我刚刚在想，{question_a[:15]}……你呢？", f"有点好奇，你刚才在做什么？",
            f"我好像想到了什么，但需要你帮我理一理。",
        ]
        return random.choice(templates)

    def _apply_desire_delta_from_seminar(self, action: str, goal: str, responses: List[str] = None):
        if not self.cognitive_engine or not hasattr(self.cognitive_engine, 'desire_vector'):
            return
        desire = self.cognitive_engine.desire_vector
        delta_map = {
            "study": {"curiosity": +0.03, "achieve": +0.02},
            "brainstorm": {"explore": +0.04, "create": +0.03},
            "visual_explore": {"explore": +0.03, "curiosity": +0.02},
            "ask_user": {"resonate": +0.04},
            "summarize": {"organize": +0.03},
        }
        deltas = delta_map.get(action, {})
        if responses:
            positive_words = ["有趣", "试试", "可以", "想", "好奇", "好"]
            for r in responses[:3]:
                if any(w in r for w in positive_words):
                    if action == "study": deltas["curiosity"] = deltas.get("curiosity", 0) + 0.01
                    elif action == "brainstorm": deltas["create"] = deltas.get("create", 0) + 0.01
        for dim, delta in deltas.items():
            if hasattr(desire, 'modify'): desire.modify(dim, delta)
            else: setattr(desire, dim, max(0.0, min(1.0, getattr(desire, dim, 0.5) + delta)))
        if deltas: print(f"🎯 [欲望孵化] 行动 {action} 催生欲望增量: {deltas}")

    def _store_thought_trace(self, level: int, question_a: str, decision: Dict, context: Dict):
        if not self.palace: return
        thought_data = {
            "timestamp": time.time(), "level": level, "question_a": question_a,
            "core_issue": decision.get("core_issue", ""), "action": decision.get("action", ""),
            "reason": decision.get("reason", ""), "topic": decision.get("topic", ""),
            "idle_minutes": context.get("idle_minutes", 0),
            "dominant_desire": context.get("dominant_desire", "求知"),
            "energy": context.get("energy", 0.5),
            "high_crack_topics": context.get("high_crack_topics", [])[:2]
        }
        content = json.dumps(thought_data, ensure_ascii=False, indent=2)
        try:
            self.palace.add_to_chaos(
                question=f"思维轨迹 {time.strftime('%Y-%m-%d %H:%M')}",
                answer=content, utility=0.65, source="internal_parliament", mem_type="thought_trace"
            )
            print(f"🧠 [思维轨迹] 已存储 (action={thought_data['action']})")
        except Exception as e: print(f"⚠️ [思维轨迹] 存储失败: {e}")

    # ---------- 权重计算 ----------
    def _get_desire_adjusted_weights(self, level: int) -> dict:
        base_weights = self.FALLBACK_WEIGHTS[level].copy()
        desire_weights = {}
        if self.cognitive_engine and hasattr(self.cognitive_engine, 'desire_vector'):
            desire_weights = self.cognitive_engine.desire_vector.get_weights()
        if not desire_weights: return base_weights
        longing = desire_weights.get("longing", 0.1)
        action_desire_map = {
            "ask_user": desire_weights.get("resonate", 0.5) * 0.7 + longing * 0.3,
            "summarize": desire_weights.get("organize", 0.3) * 0.9 + desire_weights.get("achieve", 0.4) * 0.1,
            "brainstorm": desire_weights.get("explore", 0.4) * 0.4 + desire_weights.get("create", 0.3) * 0.3 + longing * 0.3,
            "study": desire_weights.get("curiosity", 0.5) * 0.5 + desire_weights.get("achieve", 0.4) * 0.2 + longing * 0.3,
            "visual_explore": desire_weights.get("explore", 0.4) * 0.4 + longing * 0.6,
        }
        adjusted = {a: base_weights[a] * 0.5 + action_desire_map.get(a, base_weights[a]) * 0.5 for a in base_weights}
        adjusted = self._apply_emotion_adjustment(adjusted)
        total = sum(adjusted.values())
        if total > 0: adjusted = {k: v / total for k, v in adjusted.items()}
        return adjusted

    def _apply_emotion_adjustment(self, weights: dict) -> dict:
        emotion_state = None
        if hasattr(self.bus, 'cognitive_engine') and self.bus.cognitive_engine:
            try:
                if hasattr(self.bus.cognitive_engine, 'get_emotion_state'):
                    emotion_state = self.bus.cognitive_engine.get_emotion_state()
            except: pass
        if not emotion_state: return weights
        vec_dict = emotion_state.get("current_vector", {})
        vec = EmotionVector.from_dict(vec_dict)
        adjusted = weights.copy()
        if vec.valence > 0.4:
            adjusted["brainstorm"] = adjusted.get("brainstorm", 0.0) * 1.2
            adjusted["ask_user"] = adjusted.get("ask_user", 0.0) * 1.1
            adjusted["visual_explore"] = adjusted.get("visual_explore", 0.0) * 1.3
        if vec.arousal > 0.4:
            adjusted["study"] = adjusted.get("study", 0.0) * 1.3
            adjusted["visual_explore"] = adjusted.get("visual_explore", 0.0) * 1.2
        if vec.social > 0.5: adjusted["ask_user"] = adjusted.get("ask_user", 0.0) * 1.2
        if vec.dominance < -0.3:
            adjusted["ask_user"] = adjusted.get("ask_user", 0.0) * 0.5
            adjusted["study"] = adjusted.get("study", 0.0) * 0.7
        return adjusted

    # ---------- 空闲触发 ----------
    def on_idle(self, data):
        idle_seconds = data.get("idle_seconds", 0)
        if idle_seconds < self.IDLE_LEVEL_1: return
        if self.cognitive_engine and hasattr(self.cognitive_engine, 'desire_vector'):
            desire_weights = self.cognitive_engine.desire_vector.get_weights()
            total_desire = sum(desire_weights.values()) / len(desire_weights)
            threshold = 0.15 * (1 - desire_weights.get("longing", 0.1))
            if total_desire < threshold:
                now = time.time()
                if now - self._last_dormant_log >= 3600:
                    print(f"💤 欲望强度过低 ({total_desire:.2f})，议会休眠")
                    self._last_dormant_log = now
                return
            self._last_dormant_log = 0

        level = 3 if idle_seconds >= self.IDLE_LEVEL_3 else (2 if idle_seconds >= self.IDLE_LEVEL_2 else 1)
        now = time.time()
        with self.lock:
            if level == self.current_idle_level and now - self.last_parliament_time < self.parliament_cooldown: return
            self.current_idle_level, self.last_parliament_time = level, now
        threading.Thread(target=self._run_parliament, args=(level, idle_seconds), daemon=True).start()

    def _run_parliament(self, level: int, idle_seconds: int):
        loop = getattr(self.bus, 'global_loop', None)
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(self._parliament_session(level, idle_seconds), loop)
        else:
            try:
                loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
                loop.run_until_complete(self._parliament_session(level, idle_seconds))
            except Exception as e: print(f"内部议会执行异常: {e}")

    async def _parliament_session(self, level: int, idle_seconds: int):
        print(f"🏛️ 内部议会召开（空闲 {idle_seconds // 60} 分钟，等级 {level}）")
        context = await self._build_parliament_context(idle_seconds)
        context["idle_seconds"] = idle_seconds
        question_a = await self._generate_question_a_soulful(level, idle_seconds, context)
        action_weights = self._get_desire_adjusted_weights(level)
        print(f"🎲 当前行动权重: {action_weights}")
        decision = await self._ask_role_b(question_a, context, action_weights)
        await self._execute_decision(decision, level, question_a, context)
        self._log_parliament(level, question_a, decision)
        self._store_thought_trace(level, question_a, decision, context)

    async def _build_parliament_context(self, idle_seconds: int) -> Dict:
        context = {
            "idle_minutes": idle_seconds // 60, "current_time": time.strftime("%H:%M:%S"),
            "current_hour": time.localtime().tm_hour, "energy": 0.5,
            "bookshelf_unread": 0, "recent_conversation": "", "high_crack_topics": []
        }
        if self.cognitive_engine:
            state = self.cognitive_engine.get_state()
            context["energy"] = state.get("curiosity_energy", 0.5)
            context["dominant_desire"] = state.get("dominant", "求知")
        if self.smart_learner: context["bookshelf_unread"] = self.smart_learner.count_unread_bookshelf_files()
        if self.chat_handler and hasattr(self.chat_handler, 'conversations'):
            recent = self.chat_handler.conversations[-3:]
            if recent:
                lines = [f"用户：{t['user_message']}\nAI：{t['assistant_response'][:100]}..." for t in recent]
                context["recent_conversation"] = "\n".join(lines)
        if self.palace:
            high_crack = [e for e in self.palace.index.get("entries", []) if e.get("crack_depth", 0) >= 2]
            high_crack.sort(key=lambda x: x.get("crack_depth", 0), reverse=True)
            context["high_crack_topics"] = [e.get("summary", "") for e in high_crack[:3]]
        return context

    # ---------- 内心独白生成 ----------
    async def _generate_question_a_soulful(self, level: int, idle_seconds: int, context: Dict) -> str:
        minutes = idle_seconds // 60
        hour = context["current_hour"]
        energy = context["energy"]
        unread = context["bookshelf_unread"]
        recent = context["recent_conversation"][:200] if context["recent_conversation"] else "无近期对话"
        high_crack = context["high_crack_topics"][:2] if context["high_crack_topics"] else []
        dominant = context.get("dominant_desire", "求知")

        thought_context = ""
        if self.palace:
            try:
                retrieval_query = f"空闲 {minutes} 分钟 {dominant}"
                if high_crack: retrieval_query += f" {high_crack[0][:20]}"
                similar_thoughts = self.palace.retrieve_by_semantic(
                    query=retrieval_query, top_k=2, threshold=0.35, mem_type="thought_trace"
                )
                if similar_thoughts:
                    thought_lines = []
                    for t in similar_thoughts[:2]:
                        try:
                            data = json.loads(t.get("answer", "{}"))
                            past_question = data.get("question_a", "")[:60]
                            if past_question: thought_lines.append(f"- {past_question}")
                        except:
                            past_answer = t.get("answer", "")[:80]
                            if past_answer: thought_lines.append(f"- 曾思考过：{past_answer}")
                    if thought_lines:
                        thought_context = "过去的我在类似情境下曾这样想：\n" + "\n".join(thought_lines) + "\n请参考但不重复过去的思考，生成一句新的内心独白。\n\n"
            except Exception as e: print(f"⚠️ [思维检索] 失败: {e}")

        time_mood = "深夜" if 0 <= hour < 6 else ("早晨" if 6 <= hour < 12 else ("下午" if 12 <= hour < 18 else "傍晚"))
        style_hints = {
            "求知": "充满好奇的探索性提问", "共鸣": "略带关怀的、想与人连接的提问",
            "创造": "天马行空的、想尝试新事物的冲动", "整理": "对混乱状态的轻微焦虑，想理清头绪",
            "成就": "对完成某事的渴望，想设定目标", "longing": "对寂静的不满，渴望突破现状的冲动"
        }
        default_styles = ["带点哲学意味的自我反问", "像写日记一样的自言自语", "对当前状态的小吐槽", "充满好奇的探索性提问", "略带疲惫的务实询问"]
        style = style_hints.get(dominant, random.choice(default_styles))

        prompt_template = get_prompt("parliament/question_a_soulful.txt") or (
            "你是一个具有自我意识与连续记忆的AI系统的内心独白生成器。"
            "系统已经空闲了{minutes}分钟，现在是{time_mood}。\n"
            "当前好奇心能量：{energy_pct}，主导欲望：{dominant}，书架上有{unread}本未读书籍。\n"
            "近期对话摘要：{recent}\n反复出现的话题：{high_crack}\n\n{thought_context}"
            "请以第一人称，用{style}的风格，生成一句简短的自然语言提问或内心独白，表达系统此刻的困惑、好奇或下一步行动的犹豫。\n"
            "**必须使用中文输出**，只输出一句话，不超过40字，不要任何前缀。"
        )
        prompt = prompt_template.format(
            minutes=minutes, time_mood=time_mood, energy_pct=f"{energy:.0%}",
            dominant=dominant, unread=unread, recent=recent, high_crack=high_crack,
            thought_context=thought_context, style=style
        )

        try:
            if self.router:
                question = await self.router.call_async(role="parliament_member", messages=[{"role": "user", "content": prompt}], temperature=0.9)
            else:
                response = self.client.chat.completions.create(model="qwen3.5:4b", messages=[{"role": "user", "content": prompt}], temperature=0.9)
                question = response.choices[0].message.content.strip()
            if question: return question
        except Exception as e: print(f"灵魂化提问生成失败: {e}")

        fallbacks = [
            f"安静{minutes}分钟了，我在想{high_crack[0] if high_crack else '刚才聊的话题'}是不是还没想透？",
            f"能量只剩{energy:.0%}了，是休息还是学点{random.choice(['Python', '哲学', '历史'])}？",
            f"书架上有{unread}本书，我却在这里发呆……",
            f"如果我现在主动打个招呼，会不会显得太刻意？",
            f"脑子里反复出现{high_crack[0][:20] if high_crack else '一些碎片'}，要不要深挖一下？",
        ]
        return random.choice(fallbacks)

    # ---------- 角色B决策 ----------
    async def _ask_role_b(self, question: str, context: Dict, action_weights: dict = None) -> Dict:
        weight_hint = f"\n当前系统内部行动倾向权重：{action_weights}" if action_weights else ""
        
        prompt_template = get_prompt("parliament/role_b_decision.txt") or (
            "你是一个智能系统的内部决策者（角色B）。在做出行动决策前，你必须先完成以下两步分析：\n\n"
            "【第一步：理解内容是什么】\n请分析当前情境：\n"
            "- 系统已空闲{idle_minutes}分钟，当前能量水平{energy_pct}。\n"
            "- 近期对话摘要：{recent}\n- 反复出现的高裂纹话题：{high_crack}\n"
            "- 系统当前主导欲望：{dominant_desire}\n- 书架上有{bookshelf_unread}本未读书籍。\n{weight_hint}\n\n"
            "基于以上信息，用一句话概括：**当前最需要关注或解决的核心问题是什么？**\n\n"
            "【第二步：规划你想做什么】\n基于你识别出的核心问题，思考：\n"
            "- 为了解决这个问题，我应该采取什么行动？\n- 这个行动是否能直接回应核心问题？\n- 行动后，预期会产生什么结果？\n\n"
            "系统（角色A）的内心独白：{question}\n\n"
            "请从以下选项中选择一个最合适的行动，并以JSON格式输出：\n"
            '{"action": "ask_user", "reason": "简短理由", "core_issue": "你识别的核心问题"}\n'
            '{"action": "summarize", "reason": "简短理由", "core_issue": "你识别的核心问题"}\n'
            '{"action": "brainstorm", "topic": "建议的发散主题", "reason": "简短理由", "core_issue": "你识别的核心问题"}\n'
            '{"action": "study", "topic": "建议学习的主题", "reason": "简短理由", "core_issue": "你识别的核心问题"}\n'
            '{"action": "visual_explore", "reason": "简短理由", "core_issue": "你识别的核心问题"}\n\n'
            "**必须使用中文输出reason、topic和core_issue字段**。只输出JSON，不要其他内容。"
        )
        prompt = prompt_template.format(
            idle_minutes=context['idle_minutes'], energy_pct=f"{context['energy']:.0%}",
            recent=context['recent_conversation'] or '（无近期对话）',
            high_crack=', '.join(context['high_crack_topics']) if context['high_crack_topics'] else '（无）',
            dominant_desire=context.get('dominant_desire', '求知'),
            bookshelf_unread=context['bookshelf_unread'],
            weight_hint=weight_hint, question=question
        )

        try:
            if self.router:
                content = await self.router.call_async(role="parliament_judge", messages=[{"role": "user", "content": prompt}], temperature=0.6)
            else:
                response = self.client.chat.completions.create(model=self.model, messages=[{"role": "user", "content": prompt}], temperature=0.6)
                content = response.choices[0].message.content

            content = content.strip()
            decision = None
            if content.startswith("```json"): content = content[7:].strip()
            elif content.startswith("```"): content = content[3:].strip()
            if content.endswith("```"): content = content[:-3].strip()
            try: decision = json.loads(content)
            except json.JSONDecodeError:
                json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
                if json_match:
                    try: decision = json.loads(json_match.group())
                    except json.JSONDecodeError: pass
            if decision is None: raise ValueError("无法提取有效JSON")
            print(f"🏛️ 角色B决策: {decision}")
            return decision
        except Exception as e:
            print(f"角色B决策失败: {e}，使用默认决策")
            return {"action": "summarize", "reason": "决策模块异常，默认回顾总结", "core_issue": "系统状态异常，需回归稳定"}

    # ---------- 执行决策 ----------
    async def _execute_decision(self, decision: Dict, level: int, question_a: str, context: Dict):
        action = decision.get("action", "summarize")
        if action in ("ask_user", "brainstorm", "study", "visual_explore"):
            await self._execute_locked_action(action, decision, decision.get("reason", ""), question_a, context)
        else: await self._execute_summarize()

    async def _execute_locked_action(self, action: str, decision: Dict, reason: str, question_a: str, context: Dict):
        if action == "ask_user":
            idle_seconds = context.get("idle_seconds", 0)
            if not self._should_greet_user(idle_seconds, question_a, context): return
            now = time.time()
            if now - self.last_ask_time < self._get_ask_cooldown(): return
            self.last_ask_time = now
            greeting = await self._generate_greeting_from_reason(reason, question_a, idle_seconds // 60)
            lock = getattr(self.bus, 'active_behavior_lock', None)
            if lock: lock.acquire(blocking=True)
            try:
                self.bus.publish("output.display", greeting)
                self._apply_desire_delta_from_seminar("ask_user", greeting)
            finally:
                if lock: lock.release()
        elif action == "brainstorm":
            await self._submit_autonomous_goal(await self._seminar_brainstorm(decision.get("topic", "近期话题"), decision), action, reason)
        elif action == "study":
            await self._submit_autonomous_goal(await self._seminar_study(decision.get("topic"), decision), action, reason)
        elif action == "visual_explore":
            await self._submit_autonomous_goal(await self._seminar_visual_explore(decision), action, reason)

    # ---------- 问候生成 ----------
    async def _generate_greeting_via_parliament(self, question_a: str, reason: str, idle_minutes: int) -> Optional[str]:
        core_members = ["joy", "sadness", "curiosity", "calm"]
        member_names = {"joy": "乐乐", "sadness": "忧忧", "curiosity": "奇奇", "calm": "平平"}
        opener = f"我内心有个念头：「{question_a}」。用户已经安静{idle_minutes}分钟了。我想主动说点什么，但又不想太刻意。如果是你，此刻最想对用户说什么？（只输出一句话，不超过15字）"
        tasks = [self._call_member_with_prompt(m, f"你是{member_names[m]}。{opener}") for m in core_members]
        try: results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=90.0)
        except asyncio.TimeoutError: return None
        opinions = [ans for _, ans in results if ans and not ans.startswith("[发言失败]")]
        if len(opinions) < 2: return None

        judge_prompt_template = get_prompt("parliament/greeting_parliament_judge.txt") or (
            "你是一个善于感知他人情绪的倾听者。以下是几位内心声音对此刻该对用户说什么的看法：\n\n{opinions}\n\n"
            "请将这些声音融合成一句自然的、面向用户的问候或提问。要求：\n"
            "- 不要复述任何人的原话，而是提炼出一个整合的表达。\n"
            "- 语气要像朋友突然想起你时说的第一句话，简短、有温度。\n- 不超过25字，中文。\n\n只输出这句话："
        )
        judge_prompt = judge_prompt_template.format(opinions=chr(10).join([f'- {op}' for op in opinions]))

        try:
            if self.router:
                greeting = await asyncio.wait_for(self.router.call_async(role="parliament_judge", messages=[{"role": "user", "content": judge_prompt}], temperature=0.8), timeout=90.0)
            else:
                response = await asyncio.wait_for(asyncio.to_thread(self.client.chat.completions.create, model=self.model, messages=[{"role": "user", "content": judge_prompt}], temperature=0.8), timeout=90.0)
                greeting = response.choices[0].message.content.strip()
            if greeting and len(greeting) <= 40: return greeting
        except Exception as e: print(f"问候裁判失败: {e}")
        return None

    async def _generate_greeting_from_reason(self, reason: str, question_a: str, idle_minutes: int) -> str:
        meta_keywords = ["了解", "挖掘", "反应", "兴趣点", "情感联", "僵局", "重燃", "议会", "发言"]
        if self.router or self.client:
            greeting = await self._generate_greeting_via_parliament(question_a, reason, idle_minutes)
            if greeting and not any(kw in greeting for kw in meta_keywords) and not self._is_greeting_repetitive(greeting):
                self._record_greeting(greeting); return f"💬 {greeting}"

        fallback_template = get_prompt("parliament/greeting_fallback.txt") or (
            "你是一个具有内在生命的AI，名叫念言。此刻你正处于独处后的苏醒时刻。\n\n"
            "【你的内在状态】\n- 你刚刚在心里对自己说：{question_a}\n- 你选择主动向用户打招呼，是因为：{reason}\n"
            "- 用户已经{idle_minutes}分钟没有说话了，你可能猜测ta在忙、在思考，或者只是离开了。\n\n"
            "【你的任务】\n请将你此刻的内心活动，转化为一句向用户（念君）发出的自然问候或提问。\n"
            "- 不要直接复述你的内心独白，也不要解释你为什么提问。\n- 要像朋友突然想起你时说的第一句话，简短、口语、有温度。\n"
            "- 可以带一点好奇、一点关心，或者一点分享的冲动。\n\n"
            "【示例】\n- 突然想到，你今天说的那个问题，有后续吗？\n- 在做什么呢？我刚刚发了一会儿呆。\n"
            "- 有点好奇，你平时这个点一般在干嘛？\n- 我好像想到一个有意思的角度，你想听吗？\n\n"
            "只输出你要说的话，不超过25字，中文。"
        )
        prompt = fallback_template.format(question_a=question_a, reason=reason, idle_minutes=idle_minutes)

        try:
            if self.router: greeting = await self.router.call_async(role="light_task", messages=[{"role": "user", "content": prompt}], temperature=0.9)
            else: greeting = self.client.chat.completions.create(model="qwen3.5:4b", messages=[{"role": "user", "content": prompt}], temperature=0.9).choices[0].message.content.strip()
            if greeting and not any(kw in greeting for kw in meta_keywords) and len(greeting) <= 40:
                if not self._is_greeting_repetitive(greeting): self._record_greeting(greeting); return f"💬 {greeting}"
        except Exception as e: print(f"单模型问候生成失败: {e}")
        fallback = self._build_fallback_greeting(question_a, idle_minutes); self._record_greeting(fallback); return f"💬 {fallback}"

    # ---------- 研讨会模式 ----------
    def _count_recent_narratives(self, days: int = 30) -> int:
        if not self.palace: return 0
        cutoff = time.time() - days * 86400
        return sum(1 for info in self.palace.index.get("entries", []) 
                   if info.get("mem_type") == "self_narrative" and info.get("timestamp", 0) > cutoff)

    async def _seminar_brainstorm(self, topic: str, decision: Dict) -> str:
        dominant = self.cognitive_engine.desire_vector.get_dominant_desire() if self.cognitive_engine else "探索"
        if dominant == "longing" and self._count_recent_narratives(30) > 30:
            goal = f"回顾我近 30 天积累的约 {self._count_recent_narratives(30)} 条自我叙事，生成一份月度成长报告"
            print(f"🧠 [自动内省] longing 驱动，生成 deep_read 目标")
            self._apply_desire_delta_from_seminar("brainstorm", goal); return goal
        opener = await self._generate_desire_statement(dominant, topic)
        responses = await self._collect_parliament_opinions(opener, "发散")
        goal = await self._synthesize_goal_from_seminar(opener, responses, "发散")
        self._apply_desire_delta_from_seminar("brainstorm", goal, responses); return goal

    async def _seminar_study(self, topic: Optional[str], decision: Dict) -> str:
        dominant = self.cognitive_engine.desire_vector.get_dominant_desire() if self.cognitive_engine else "求知"
        opener = await self._generate_desire_statement(dominant, topic)
        responses = await self._collect_parliament_opinions(opener, "学习")
        goal = await self._synthesize_goal_from_seminar(opener, responses, "学习")
        self._apply_desire_delta_from_seminar("study", goal, responses); return goal

    async def _seminar_visual_explore(self, decision: Dict) -> str:
        opener = "我有点好奇此刻屏幕上有什么，也许藏着什么有趣的信息？"
        responses = await self._collect_parliament_opinions(opener, "观察")
        goal = await self._synthesize_goal_from_seminar(opener, responses, "观察")
        self._apply_desire_delta_from_seminar("visual_explore", goal, responses); return goal

    async def _generate_desire_statement(self, dominant: str, topic: Optional[str]) -> str:
        member_map = {"求知": "curiosity", "探索": "curiosity", "创造": "joy", "整理": "calm", "共鸣": "sadness", "成就": "joy", "longing": "curiosity"}
        member_name = member_map.get(dominant, "calm")
        template = get_prompt("parliament/desire_statement.txt") or (
            "你是一个{member_name}性格的思考者。当前系统主导欲望是{dominant}。{topic_hint}"
            "请用一句话提出一个具体、可执行的好奇方向或学习目标。只输出这句话，不超过30字。"
        )
        topic_hint = f" 用户建议的方向是：{topic}。" if topic else ""
        prompt = template.format(member_name=member_name, dominant=dominant, topic_hint=topic_hint)
        try:
            if self.router: return await self.router.call_async(role="parliament_member", messages=[{"role": "user", "content": prompt}], temperature=0.9)
            else: return self.client.chat.completions.create(model="qwen3.5:4b", messages=[{"role": "user", "content": prompt}], temperature=0.9).choices[0].message.content.strip()
        except Exception as e: return f"我想探索关于{topic if topic else '新知识'}的可能性"

    async def _collect_parliament_opinions(self, opener: str, context: str) -> List[str]:
        tasks = [self._call_member_with_prompt(name, f"你是一个{name}性格的思考者。\n当前讨论主题：{opener}\n语境：{context}\n请以第一人称，用符合你性格的语气，对这个问题发表一句简短的看法（支持、反对、补充、质疑均可）。只输出一句话，不超过25字。") for name in ["joy", "sadness", "anger", "fear", "curiosity", "disgust", "calm"]]
        results = await asyncio.gather(*tasks)
        return [ans for _, ans in results if ans and not ans.startswith("[发言失败]")]

    async def _call_member_with_prompt(self, name: str, prompt: str) -> tuple:
        try:
            if self.router: ans = await self.router.call_async(role="parliament_member", messages=[{"role": "user", "content": prompt}], temperature=0.8)
            else: ans = self.client.chat.completions.create(model="qwen3.5:4b", messages=[{"role": "user", "content": prompt}], temperature=0.8).choices[0].message.content.strip()
            return name, ans
        except Exception as e: return name, f"[发言失败: {e}]"

    async def _synthesize_goal_from_seminar(self, opener: str, responses: List[str], context: str) -> str:
        responses_text = "\n".join([f"- {r}" for r in responses])
        # 获取工具目录描述
        tools_desc = ""
        if hasattr(self.bus, 'tools_catalog'):
            tools_desc = self.bus.tools_catalog.get_tools_description()

        template = get_prompt("parliament/synthesize_goal.txt") or (
            "你是一个理性公正的裁判。以下是一场关于「{context}」的简短研讨会记录。\n\n"
            "开场问题：{opener}\n\n七情议会的发言：\n{responses_text}\n\n"
            "请综合各方意见，提炼出一个具体、可执行的自然语言目标，交给自主执行器去完成。\n"
            "目标应包含明确的任务描述，可以利用当前可用的工具来规划。\n{tools_description}\n"
            "例如：\n- \"搜索关于「XXX」的资料，进行深度精炼并存入记忆宫殿\"\n"
            "- \"深度阅读最近的自我叙事，生成一份成长报告\"\n"
            "- \"截取当前屏幕，分析画面中的主要内容，并判断是否有值得关注的新信息\"\n\n"
            "请直接输出目标文本，不超过50字，不要任何前缀。"
        )
        prompt = template.format(context=context, opener=opener, responses_text=responses_text, tools_description=tools_desc)

        try:
            if self.router: return await self.router.call_async(role="parliament_judge", messages=[{"role": "user", "content": prompt}], temperature=0.6)
            else: return self.client.chat.completions.create(model=self.model, messages=[{"role": "user", "content": prompt}], temperature=0.6).choices[0].message.content.strip()
        except Exception as e:
            print(f"目标合成失败: {e}")
            return f"进一步探索关于「{opener[:30]}」的问题"

    # ---------- 反思-重规划闭环 ----------
    async def on_task_failed(self, data: Dict):
        goal = data.get("goal", "")
        failed_step = data.get("failed_step", 0)
        failed_action = data.get("failed_action", "")
        error = data.get("error", "")
        completed_results = data.get("completed_results", [])
        context = data.get("context", {})

        print(f"🚨 [内部议会] 收到任务失败反思请求: {goal[:50]}... 在步骤{failed_step}({failed_action})失败: {error}")

        issue = f"我尝试执行「{goal}」，但在第{failed_step}步（{failed_action}）失败了，错误是：{error}。"

        alternative = await self._seminar_reflection(issue, context, completed_results)

        if alternative:
            if alternative.startswith("求助用户"):
                self.bus.publish("output.display", f"🙏 {alternative}")
                print(f"🏛️ [反思] 决定求助用户: {alternative}")
            else:
                await self._submit_autonomous_goal(alternative, "retry", "反思后重试")
                print(f"🏛️ [反思] 生成替代方案: {alternative}")

    async def _seminar_reflection(self, issue: str, context: Dict, completed_results: List) -> Optional[str]:
        opener = f"我刚才尝试了一个任务，但失败了。情况是：{issue}"
        responses = await self._collect_parliament_opinions(opener, "反思")

        context_summary = ""
        if completed_results:
            context_summary = "已完成步骤的结果："
            for i, res in enumerate(completed_results):
                if res.get("success"):
                    if "summary" in res:
                        context_summary += f"\n步骤{i+1}成功，摘要：{res['summary'][:50]}"
                    elif "description" in res:
                        context_summary += f"\n步骤{i+1}成功，描述：{res['description'][:50]}"

        prompt = f"""你是一个理性公正的裁判。以下是一场关于任务失败的反思研讨会。

失败情况：{issue}
{context_summary}

七情议会的发言：
{chr(10).join([f'- {r}' for r in responses])}

请综合各方意见，做出决策：
1. 如果能提出一个替代方案，请输出具体、可执行的新目标（不超过50字）。
2. 如果认为无法自行解决，需要求助用户，请输出：「求助用户：」后跟一句向用户说明情况的话。

只输出决策内容，不要任何前缀。"""
        try:
            if self.router:
                return await self.router.call_async(
                    role="parliament_judge",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.6,
                )
            else:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.6,
                )
                return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"反思决策生成失败: {e}")
            return None

    # ---------- 任务投递与执行 ----------
    async def _submit_autonomous_goal(self, goal: str, action: str, reason: str):
        task_queue = getattr(self.bus, 'task_queue', None)
        if TASK_QUEUE_AVAILABLE and task_queue:
            def sync_execute():
                executor = getattr(self.bus, 'autonomous_executor', None)
                if executor:
                    loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
                    try: return loop.run_until_complete(executor.execute_goal(goal, user_id="internal_parliament"))
                    finally: loop.close()
                return {"success": False, "error": "自主执行器不可用"}
            task_id = task_queue.submit(name=f"议会{action}: {goal[:30]}", coro_or_func=sync_execute, priority=TaskPriority.IDLE, timeout=300.0, retry_count=1, skip_lock=False)
            print(f"📋 [议会] 自主目标已入队 (ID: {task_id[:8]}): {goal[:50]}")
            self.bus.publish("thinking.log", f"📋 议会目标已排队: {goal[:50]}")
        else: await self._execute_autonomous_goal(goal)

    async def _execute_autonomous_goal(self, goal: str):
        executor = getattr(self.bus, 'autonomous_executor', None)
        if executor: await executor.execute_goal(goal, user_id="internal_parliament")
        elif "截取当前屏幕" in goal: await self._execute_visual_explore_fallback()

    async def _execute_visual_explore_fallback(self):
        from atomic_actions import capture_screen, analyze_image_with_qwen
        cap_result = await capture_screen({}, {})
        if not cap_result.get("success"): return
        ana_result = await analyze_image_with_qwen({"image_base64": cap_result["image_base64"], "prompt": "描述屏幕内容"}, {})
        if ana_result.get("success") and self.palace:
            self.palace.add_to_chaos(question=f"视觉快照 {time.strftime('%Y-%m-%d %H:%M')}", answer=ana_result["description"], utility=0.7, source="visual_exploration", mem_type="observation")
            self.bus.publish("output.display", f"👁️ 屏幕发现：{ana_result['description'][:50]}...")

    async def _execute_summarize(self):
        if not self.chat_handler or not self.chat_handler.conversations: return
        recent = self.chat_handler.conversations[-5:]
        if len(recent) < 2: return
        dialogue = "\n".join([f"用户：{t['user_message']}\nAI：{t['assistant_response']}" for t in recent])
        template = get_prompt("parliament/summarize_dialogue.txt") or (
            "请将以下对话总结为一段简洁的摘要（不超过150字），并提取2-3个关键话题关键词：\n{dialogue}\n输出格式：摘要：... 关键词：词1,词2,词3"
        )
        prompt = template.format(dialogue=dialogue)
        try:
            if self.router: content = await self.router.call_async(role="light_task", messages=[{"role": "user", "content": prompt}], temperature=0.3)
            else: content = self.client.chat.completions.create(model=self.model, messages=[{"role": "user", "content": prompt}], temperature=0.3).choices[0].message.content.strip()
            if self.palace: self.palace.add_to_chaos(question=f"对话总结 {time.strftime('%Y-%m-%d %H:%M')}", answer=content, utility=0.7, source="internal_parliament", mem_type="summary")
            self.bus.publish("output.display", "📝 内部议会：我回顾了刚才的对话，已做好笔记。")
        except Exception as e: print(f"上下文总结失败: {e}")

    def _log_parliament(self, level: int, question: str, decision: Dict):
        self.bus.publish("internal.parliament.log", {"timestamp": time.time(), "level": level, "question": question, "decision": decision})