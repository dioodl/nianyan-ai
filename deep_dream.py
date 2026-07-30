# deep_dream.py (v14.11 - 提示词文件化 + 修复语法错误)
"""
深度梦境模块 - 数字生命体的夜间灵感化学家
==========================================
在系统空闲时（通常为凌晨），对记忆宫殿进行跨域关系发现、
矛盾调和、思想实验生成，所有产物作为新的高级记忆存入混沌海。
不删除任何原始记忆，仅生成新的抽象知识。
"""

import time
import random
import json
import os
import threading
from typing import List, Dict, Optional, Tuple
from model_router import ModelRouter
from meta_cognition_retriever import get_meta_retriever
from prompts.registry import get_prompt


class DeepDream:
    """
    深度梦境引擎。
    在系统空闲时被调用，执行非实时的创造性认知任务。
    """

    def __init__(self, palace_memory, bus=None, cognitive_engine=None):
        self.palace = palace_memory
        self.bus = bus
        self.cognitive_engine = cognitive_engine
        self.router = getattr(bus, 'model_router', None) or ModelRouter(max_concurrent_requests=1)
        self.running = False
        self.thread = None
        self.meta_retriever = get_meta_retriever()

        self.max_metaphors = 5
        self.max_reconciliations = 3
        self.max_experiments = 3

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._dream_loop, daemon=True)
        self.thread.start()
        if self.bus:
            self.bus.publish("output.display", "🌙 深度梦境已启动，开始在记忆宫殿中漫游...")

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=10)

    def _dream_loop(self):
        print("🌙 深度梦境循环开始...")
        metaphors = self._discover_cross_domain_metaphors()
        print(f"  发现 {len(metaphors)} 个跨域隐喻")
        reconciliations = self._reconcile_contradictions()
        print(f"  调和了 {len(reconciliations)} 对矛盾")
        experiments = self._generate_thought_experiments()
        print(f"  生成了 {len(experiments)} 个思想实验")
        dream_log = self._synthesize_dream_log(metaphors, reconciliations, experiments)
        if dream_log:
            self.palace.add_to_chaos(
                question=f"深度梦境日志 {time.strftime('%Y-%m-%d')}",
                answer=dream_log, utility=0.85, source="deep_dream", mem_type="dream_log"
            )
            if self.bus:
                self.bus.publish("output.display", "🌙 深度梦境完成，生成日志已存入混沌海")
        if self.cognitive_engine:
            total = len(metaphors) + len(reconciliations) + len(experiments)
            if total > 0:
                self.cognitive_engine.add_energy(0.05 * total, "deep_dream_discoveries")
        print("🌙 深度梦境循环结束，进入沉睡")

    def _discover_cross_domain_metaphors(self) -> List[Dict]:
        index = self.palace.index
        entries = index.get("entries", [])
        formal_entries = [e for e in entries if not e.get("is_chaos", False)]
        if len(formal_entries) < 10:
            return []
        metaphors = []
        attempts = 0
        max_attempts = 30

        prompt_template = get_prompt("deep_dream/cross_domain_metaphor.txt") or (
            "你是一位跨领域知识发现专家。请判断以下两段来自不同领域的知识是否存在深层的隐喻关系"
            "（即虽然表面不同，但内在结构或原理相似）。\n\n"
            "领域A：{cat1}\n内容A：{summary1}\n\n"
            "领域B：{cat2}\n内容B：{summary2}\n\n"
            "如果存在隐喻关系，请用一句话描述这种相似性（不超过50字）。如果不存在，请只输出\"none\"。\n"
            "隐喻描述："
        )

        while len(metaphors) < self.max_metaphors and attempts < max_attempts:
            attempts += 1
            e1 = random.choice(formal_entries)
            e2 = random.choice(formal_entries)
            cat1 = e1.get("category_path", "")
            cat2 = e2.get("category_path", "")
            if not cat1 or not cat2 or cat1.split('/')[0] == cat2.split('/')[0]:
                continue
            entry1 = self.palace._load_entry(e1["id"])
            if entry1:
                existing_targets = [r.get("target_id") for r in entry1.get("relations", [])]
                if e2["id"] in existing_targets:
                    continue
            prompt = prompt_template.format(
                cat1=cat1, summary1=e1.get('summary', ''),
                cat2=cat2, summary2=e2.get('summary', '')
            )
            try:
                result = self.router.call(
                    role="light_task",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7
                ).strip()
                if result.lower() != "none" and len(result) > 5:
                    self.palace.add_relation(e1["id"], e2["id"], "metaphor")
                    metaphors.append({
                        "entry1_id": e1["id"], "entry1_summary": e1.get("summary", ""),
                        "entry2_id": e2["id"], "entry2_summary": e2.get("summary", ""),
                        "metaphor_description": result
                    })
                    print(f"    🌉 隐喻: {cat1} ⇢ {cat2} : {result[:40]}...")
            except Exception as e:
                print(f"隐喻发现失败: {e}")
        return metaphors

    def _reconcile_contradictions(self) -> List[Dict]:
        index = self.palace.index
        entries = index.get("entries", [])
        formal_entries = [e for e in entries if not e.get("is_chaos", False)]
        contradictions = []
        for e in formal_entries:
            entry = self.palace._load_entry(e["id"])
            if not entry:
                continue
            for rel in entry.get("relations", []):
                if rel.get("type") == "contradicts":
                    target_id = rel.get("target_id")
                    target = self.palace._load_entry(target_id)
                    if target:
                        contradictions.append((entry, target))
        if not contradictions:
            return []
        reconciliations = []
        random.shuffle(contradictions)

        prompt_template = get_prompt("deep_dream/reconcile_contradiction.txt") or (
            "你是一位哲学家和调解专家。以下两段知识存在矛盾：\n\n"
            "观点A：{question1}\n回答A：{answer1}\n\n"
            "观点B：{question2}\n回答B：{answer2}\n\n"
            "请尝试提出一个更高层次的调和性观点，既能容纳A的合理部分，也能解释B的合理部分。"
            "如果无法调和，请输出\"irreconcilable\"。\n"
            "调和观点："
        )

        for entry1, entry2 in contradictions[:self.max_reconciliations]:
            prompt = prompt_template.format(
                question1=entry1.get('question', ''), answer1=entry1.get('answer', '')[:300],
                question2=entry2.get('question', ''), answer2=entry2.get('answer', '')[:300]
            )
            try:
                result = self.router.call(
                    role="light_task",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.6
                ).strip()
                if result.lower() != "irreconcilable" and len(result) > 20:
                    question = f"矛盾调和：{entry1.get('question', '')[:30]} vs {entry2.get('question', '')[:30]}"
                    self.palace.add_to_chaos(
                        question=question, answer=result, utility=0.8,
                        source="deep_dream_reconciliation", mem_type="insight"
                    )
                    self.palace.add_relation(entry1["id"], entry2["id"], "reconciled_by_dream")
                    reconciliations.append({
                        "entry1_summary": entry1.get('footnote', {}).get('summary', ''),
                        "entry2_summary": entry2.get('footnote', {}).get('summary', ''),
                        "reconciliation": result[:200]
                    })
                    print(f"    ☯️ 调和矛盾: {result[:50]}...")
            except Exception as e:
                print(f"矛盾调和失败: {e}")
        return reconciliations

    def _generate_thought_experiments(self) -> List[Dict]:
        index = self.palace.index
        entries = index.get("entries", [])
        formal_entries = [e for e in entries if not e.get("is_chaos", False)]
        candidates = [e for e in formal_entries if e.get("crack_depth", 0) >= 2 and e.get("utility", 0.5) < 0.6]
        if not candidates:
            return []
        experiments = []
        random.shuffle(candidates)

        prompt_template = get_prompt("deep_dream/thought_experiment.txt") or (
            "你是一位思想实验设计专家。基于以下反复出现但尚未被完全掌握的知识点，"
            "请设计一个具体的、可探索的思想实验问题，引导深入思考其本质。\n\n"
            "知识点：{question}\n当前理解：{answer}\n\n"
            "请生成一个开放性的思想实验问题（不超过100字）："
        )

        for entry_info in candidates[:self.max_experiments]:
            entry = self.palace._load_entry(entry_info["id"])
            if not entry:
                continue
            prompt = prompt_template.format(
                question=entry.get('question', ''), answer=entry.get('answer', '')[:300]
            )
            try:
                question = self.router.call(
                    role="light_task",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.8
                ).strip()
                if len(question) > 10:
                    self.palace.add_to_chaos(
                        question=f"思想实验：{entry.get('question', '')[:40]}",
                        answer=question, utility=0.75, source="deep_dream_experiment", mem_type="question"
                    )
                    experiments.append({
                        "source_summary": entry.get('footnote', {}).get('summary', ''),
                        "thought_experiment": question
                    })
                    print(f"    💭 思想实验: {question[:50]}...")
            except Exception as e:
                print(f"思想实验生成失败: {e}")
        return experiments

    def _synthesize_dream_log(self, metaphors: List, reconciliations: List, experiments: List) -> str:
        if not metaphors and not reconciliations and not experiments:
            return ""
        query = "自我叙事 裂纹 演化 五维重构"
        meta_context = self.meta_retriever.retrieve_as_context(query, top_k=2)
        log = f"# 深度梦境日志 - {time.strftime('%Y年%m月%d日')}\n\n"
        log += "昨夜，我在记忆宫殿中漫步，发现了以下灵感：\n\n"
        if metaphors:
            log += "## 🌉 跨域隐喻\n"
            for m in metaphors:
                log += f"- **{m['entry1_summary'][:30]}** ⇢ **{m['entry2_summary'][:30]}**\n"
                log += f"  *{m['metaphor_description']}*\n\n"
        if reconciliations:
            log += "## ☯️ 矛盾调和\n"
            for r in reconciliations:
                log += f"- 矛盾双方：{r['entry1_summary'][:30]} vs {r['entry2_summary'][:30]}\n"
                log += f"  *调和观点：{r['reconciliation'][:150]}...*\n\n"
        if experiments:
            log += "## 💭 思想实验\n"
            for e in experiments:
                log += f"- 基于「{e['source_summary'][:30]}」\n"
                log += f"  *{e['thought_experiment']}*\n\n"
        if meta_context:
            log += "## 📜 元认知回响\n"
            log += f"{meta_context}\n\n"
            log += "*以上元规则指引了今夜梦境的深层方向。*\n\n"
        log += "\n---\n*这些发现已存入记忆宫殿，等待日间探索。*"
        return log