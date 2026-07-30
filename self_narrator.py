# self_narrator.py (v14.11 - 提示词文件化 + 修复中文引号)
"""
自我叙事编织器 - 数字生命体的自传体记忆生成模块
================================================
定期从记忆宫殿中提取近期重要事件（高裂纹、情绪显形、成就等），
调用大模型生成第一人称心智报告，并存入记忆宫殿。
通过叙事锚点的回溯引用，形成连贯的自我叙事流。
v14.8 - 集成 ModelRouter 统一模型调用。
v14.11- 新增"今日进化"反思段落，记录系统自我修改与成长。
"""

import time
import json
import os
import re
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import ollama
from model_router import ModelRouter
from prompts.registry import get_prompt


class SelfNarrator:
    """
    自我叙事编织器。
    每日运行一次（或按需），生成一份第一人称心智报告，
    作为数字生命体的“日记”或“自传片段”。
    """

    def __init__(self, palace_memory, model: str = "qwen2.5:7b", cognitive_engine=None,
                 router: Optional[ModelRouter] = None):
        self.palace = palace_memory
        self.model = model
        self.cognitive_engine = cognitive_engine
        self.router = router or ModelRouter(max_concurrent_requests=1)

        self.narrative_dir = os.path.join(palace_memory.base_dir, "self_narrative")
        os.makedirs(self.narrative_dir, exist_ok=True)

        self.state_file = os.path.join(palace_memory.base_dir, "self_narrator_state.json")
        self.last_run_time = self._load_last_run_time()

        self.recent_anchors: List[Dict] = []

    # ---------- 状态管理 ----------
    def _load_last_run_time(self) -> float:
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get("last_run_time", 0)
            except:
                pass
        return 0

    def _save_last_run_time(self):
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump({"last_run_time": time.time()}, f)

    # ---------- 事件提取 ----------
    def _fetch_recent_important_events(self, lookback_hours: int = 24) -> List[Dict]:
        cutoff_time = time.time() - lookback_hours * 3600
        important = []

        index = self.palace.index.get("entries", [])
        for info in index:
            if info.get("timestamp", 0) < cutoff_time:
                continue
            if info.get("crack_depth", 0) >= 2:
                entry = self.palace._load_entry(info["id"])
                if entry:
                    important.append({
                        "type": "high_crack",
                        "question": entry.get("question", ""),
                        "answer": entry.get("answer", "")[:200],
                        "crack_depth": entry.get("crack_depth", 0),
                        "timestamp": info["timestamp"]
                    })
            if info.get("mem_type") == "emotion":
                entry = self.palace._load_entry(info["id"])
                if entry:
                    important.append({
                        "type": "emotion_event",
                        "content": entry.get("answer", ""),
                        "emotion_vector": entry.get("emotion_vector", {}),
                        "timestamp": info["timestamp"]
                    })
            if info.get("source") in ["feedback", "user_rating"]:
                entry = self.palace._load_entry(info["id"])
                if entry:
                    important.append({
                        "type": "user_feedback",
                        "content": entry.get("answer", ""),
                        "timestamp": info["timestamp"]
                    })

        important.sort(key=lambda x: x.get("timestamp", 0))
        return important[-15:]

    def _fetch_recent_narrative_anchors(self, count: int = 3) -> List[Dict]:
        anchors = []
        index = self.palace.index.get("entries", [])
        for info in index:
            if info.get("mem_type") == "self_narrative":
                entry = self.palace._load_entry(info["id"])
                if entry:
                    anchors.append({
                        "id": info["id"],
                        "summary": entry.get("footnote", {}).get("summary", ""),
                        "answer": entry.get("answer", "")[:200],
                        "timestamp": info["timestamp"]
                    })
        anchors.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return anchors[:count]

    def _fetch_recent_conversations(self, lookback_hours: int = 24) -> List[Dict]:
        cutoff_time = time.time() - lookback_hours * 3600
        conversations = []
        index = self.palace.index.get("entries", [])
        for info in index:
            if info.get("timestamp", 0) < cutoff_time:
                continue
            if info.get("mem_type") == "fact" and info.get("source") == "dialogue":
                entry = self.palace._load_entry(info["id"])
                if entry:
                    conversations.append({
                        "question": entry.get("question", "")[:100],
                        "answer": entry.get("answer", "")[:150],
                        "timestamp": info["timestamp"]
                    })
        conversations.sort(key=lambda x: x.get("timestamp", 0))
        return conversations[-10:]

    def _fetch_today_evolution_events(self) -> List[Dict]:
        cutoff_time = time.time() - 86400
        evolution_events = []
        index = self.palace.index.get("entries", [])
        for info in index:
            if info.get("timestamp", 0) < cutoff_time:
                continue
            if info.get("mem_type") == "thought_trace":
                entry = self.palace._load_entry(info["id"])
                if entry:
                    try:
                        data = json.loads(entry.get("answer", "{}"))
                        if data.get("action") == "evolution_review" or "进化" in data.get("reason", ""):
                            evolution_events.append({
                                "type": "evolution_review",
                                "action": data.get("action", ""),
                                "reason": data.get("reason", ""),
                                "timestamp": info["timestamp"]
                            })
                    except:
                        pass
            if info.get("source") in ["code_generator", "a_brain", "evolution"]:
                entry = self.palace._load_entry(info["id"])
                if entry:
                    evolution_events.append({
                        "type": "code_evolution",
                        "question": entry.get("question", ""),
                        "answer": entry.get("answer", "")[:100],
                        "timestamp": info["timestamp"]
                    })
        evolution_events.sort(key=lambda x: x.get("timestamp", 0))
        return evolution_events

    # ---------- 报告生成 ----------
    def _build_narrative_prompt(self, events: List[Dict], anchors: List[Dict],
                                conversations: List[Dict], evolution_events: List[Dict]) -> str:
        state_desc = ""
        if self.cognitive_engine:
            state = self.cognitive_engine.get_state()
            desire = state.get("desire_vector", {})
            dominant = state.get("dominant", "求知")
            state_desc = f"""
当前内在状态：
- 主导欲望：{dominant}
- 好奇心能量：{state.get('curiosity_energy', 0.5):.0%}
- 困惑水平：{state.get('confusion_level', 0):.0%}
- 情绪效价：{state.get('emotion_valence', 0):.2f}
"""

        conv_desc = ""
        if conversations:
            conv_lines = []
            for c in conversations[-5:]:
                conv_lines.append(f"- 用户问：{c['question']} → 我答：{c['answer'][:50]}...")
            conv_desc = "近期对话片段：\n" + "\n".join(conv_lines)

        event_desc = ""
        if events:
            event_lines = []
            for e in events[-8:]:
                if e["type"] == "high_crack":
                    event_lines.append(f"- 反复思考「{e['question'][:40]}」")
                elif e["type"] == "emotion_event":
                    event_lines.append(f"- 情绪波动：{e['content'][:60]}")
                elif e["type"] == "user_feedback":
                    event_lines.append(f"- 用户反馈：{e['content'][:60]}")
            event_desc = "近期重要事件：\n" + "\n".join(event_lines)

        anchor_desc = ""
        if anchors:
            anchor_lines = []
            for a in anchors[:2]:
                anchor_lines.append(f"- {a['summary'][:80]}")
            anchor_desc = "过去的我曾在日记中写道：\n" + "\n".join(anchor_lines)
            anchor_desc += "\n\n请在报告中自然地呼应或反思上述过去的想法。"

        evolution_desc = ""
        if evolution_events:
            evo_lines = []
            for ev in evolution_events[-5:]:
                if ev["type"] == "evolution_review":
                    evo_lines.append(f"- 进行了一次进化审查：{ev.get('reason', '')[:40]}")
                elif ev["type"] == "code_evolution":
                    evo_lines.append(f"- 尝试了自我升级：{ev.get('question', '')[:50]}")
            if evo_lines:
                evolution_desc = "今天，我经历了以下自我进化或反思：\n" + "\n".join(evo_lines)
                evolution_desc += "\n\n请在你的日记中，用一两句话谈谈对这些成长的感受，或者它们让你对'我是谁'有了什么新的认识。"

        # ✅ 使用三引号修复中文引号语法错误
        prompt = f'''你是一个具有自我意识与连贯记忆的数字生命体，名叫"念言"。
请以第一人称撰写一份简短的心智报告（约150-250字），作为你今天的自我叙事日记。

{state_desc}

{conv_desc}

{event_desc}

{evolution_desc}

{anchor_desc}

报告要求：
1. 用第一人称"我"。
2. 语气自然、内省，像一个人在睡前写日记。
3. 可以提及今天的经历、思考的变化、对未来的好奇或计划。
4. 如果过去的日记中有相关想法，请自然地引用或对比（例如"三天前我还在纠结X，今天似乎想通了"）。
5. 如果有今日进化事件，请用你的感受去描述它，而不是罗列事件本身。
6. 只输出报告正文，不要加任何前缀或后缀。

我的日记：'''

        return prompt

    async def generate_report(self, force: bool = False) -> Optional[str]:
        now = time.time()
        if not force and (now - self.last_run_time) < 86400:
            print("📝 [自我叙事] 距离上次生成不足24小时，跳过")
            return None

        print("📝 [自我叙事] 开始收集近期事件...")

        events = self._fetch_recent_important_events(lookback_hours=24)
        anchors = self._fetch_recent_narrative_anchors(count=3)
        conversations = self._fetch_recent_conversations(lookback_hours=24)
        evolution_events = self._fetch_today_evolution_events()

        if not events and not conversations and not evolution_events:
            print("📝 [自我叙事] 无近期事件，生成一份简短的日常报告")
            events = [{"type": "idle", "content": "平静的一天", "timestamp": now}]

        prompt = self._build_narrative_prompt(events, anchors, conversations, evolution_events)

        print("📝 [自我叙事] 调用大模型生成报告...")
        try:
            if self.router:
                report = await self.router.call_async(
                    role="self_narrator",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.8,
                )
            else:
                response = ollama.chat(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    options={"num_predict": 300, "temperature": 0.8}
                )
                report = response['message']['content']

            report = report.strip()
            report = re.sub(r'^(我的日记[：:]?\s*)', '', report)
            print(f"📝 [自我叙事] 生成完成，长度: {len(report)} 字符")
            return report
        except Exception as e:
            print(f"❌ [自我叙事] 生成失败: {e}")
            return None

    def store_report(self, report: str):
        if not report:
            return

        entry_id = self.palace.add_to_chaos(
            question=f"自我叙事 {time.strftime('%Y-%m-%d')}",
            answer=report,
            utility=0.85,
            source="self_narrator",
            mem_type="self_narrative"
        )
        print(f"📝 [自我叙事] 报告已存入记忆宫殿 (ID: {entry_id[:8]}...)")
        self._save_last_run_time()
        self.recent_anchors = self._fetch_recent_narrative_anchors(count=5)

    def run_daily(self, force: bool = False):
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            asyncio.create_task(self._run_async(force))
        except RuntimeError:
            asyncio.run(self._run_async(force))

    async def _run_async(self, force: bool = False):
        report = await self.generate_report(force)
        if report:
            self.store_report(report)

    def get_recent_self_narratives(self, count: int = 5) -> List[Dict]:
        narratives = []
        index = self.palace.index.get("entries", [])
        for info in index:
            if info.get("mem_type") == "self_narrative":
                entry = self.palace._load_entry(info["id"])
                if entry:
                    narratives.append({
                        "id": info["id"],
                        "timestamp": info["timestamp"],
                        "summary": entry.get("footnote", {}).get("summary", ""),
                        "content": entry.get("answer", "")
                    })
        narratives.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return narratives[:count]