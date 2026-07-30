# intent_colorizer.py (复苏手术版)
"""
问题染色器 - 认知负载的轻量级染色（优化版）
============================================
采用加权评分机制，综合关键词、历史对话、系统能量进行颜色判定。
支持动态策略配置。
"""

from typing import Dict, Any, Optional, List
from message_bus import MessageBus


class IntentColorizer:
    """
    问题染色器。
    根据输入文本、近期对话、系统能量等，输出颜色标签。
    """

    # 颜色常量
    COLOR_WHITE = "white"
    COLOR_GREEN = "green"
    COLOR_YELLOW = "yellow"
    COLOR_RED = "red"

    def __init__(self, bus: Optional[MessageBus] = None):
        self.bus = bus

        # 可动态加载的策略配置（可从 JSON 文件读取）
        self.strategies = {
            self.COLOR_WHITE: {
                "use_multi_agent": True,
                "mode": "light",                # ✅ 轻量议会（3-4名成员）
                "model": "qwen2.5:7b",
                "memory_filter": True,
                "description": "轻量七情议会"
            },
            self.COLOR_GREEN: {
                "use_multi_agent": True,
                "mode": "standard",             # ✅ 标准议会（5-6名成员）
                "model": "qwen2.5:7b",
                "memory_filter": True,
                "description": "标准七情议会"
            },
            self.COLOR_YELLOW: {
                "use_multi_agent": True,
                "mode": "parallel",
                "memory_filter": True,
                "description": "并行多模型协同"
            },
            self.COLOR_RED: {
                "use_multi_agent": True,
                "mode": "full_collaborative",
                "memory_filter": True,
                "description": "完整协同+元认知生成"
            }
        }

    # ---------- 公共接口 ----------
    def colorize(self,
                 user_input: str,
                 conversation_history: Optional[List[Dict]] = None,
                 system_energy: float = 0.5,
                 deep_reasoning_requested: bool = False) -> str:
        """
        对当前输入进行染色（评分制）。
        """
        text = user_input.strip()
        history = conversation_history or []

        scores = {
            self.COLOR_WHITE: self._score_white(text, history, system_energy, deep_reasoning_requested),
            self.COLOR_GREEN: self._score_green(text, history, system_energy, deep_reasoning_requested),
            self.COLOR_YELLOW: self._score_yellow(text, history, system_energy, deep_reasoning_requested),
            self.COLOR_RED: self._score_red(text, history, system_energy, deep_reasoning_requested),
        }

        # 返回最高分颜色
        return max(scores, key=scores.get)

    def get_color_strategy(self, color: str) -> Dict[str, Any]:
        """返回颜色对应的策略配置（深拷贝以防意外修改）"""
        import copy
        return copy.deepcopy(self.strategies.get(color, self.strategies[self.COLOR_GREEN]))

    # ---------- 私有评分函数 ----------
    def _score_white(self, text: str, history: List[Dict], energy: float, deep: bool) -> float:
        score = 0.0
        text_lower = text.lower()
        # 极短输入或纯寒暄
        if len(text) < 8:
            score += 2.0
        white_phrases = ["你好", "嗨", "在吗", "谢谢", "好的", "嗯", "哦", "哈哈", "再见", "拜拜", "ok", "hi", "hello"]
        if any(phrase in text_lower for phrase in white_phrases):
            score += 1.5
        # 如果包含疑问词，降低白色概率
        if any(q in text for q in ["?", "？", "什么", "怎么", "为什么"]):
            score -= 1.0
        return max(0.0, score)

    def _score_green(self, text: str, history: List[Dict], energy: float, deep: bool) -> float:
        score = 0.0
        green_keywords = ["什么是", "定义", "解释", "介绍", "有哪些", "怎么用", "帮我", "创建", "生成", "搜索", "总结"]
        for kw in green_keywords:
            if kw in text:
                score += 1.0
        # 包含明确指令动词
        if any(verb in text for verb in ["帮我", "请", "麻烦"]):
            score += 0.5
        return score

    def _score_yellow(self, text: str, history: List[Dict], energy: float, deep: bool) -> float:
        score = 0.0
        yellow_keywords = ["比较", "区别", "分析", "优化", "架构", "设计", "原理", "最佳实践", "步骤", "如何实现"]
        for kw in yellow_keywords:
            if kw in text:
                score += 1.2
        if len(text) > 60:
            score += 1.0
        # 若最近一次对话也是黄色，则惯性延续
        if history and history[-1].get("color") == self.COLOR_YELLOW:
            score += 0.8
        return score

    def _score_red(self, text: str, history: List[Dict], energy: float, deep: bool) -> float:
        score = 0.0
        if deep:
            score += 3.0
        red_keywords = ["为什么", "如何从哲学上理解", "元认知", "自我意识", "猜想", "规则边界", "我是谁"]
        for kw in red_keywords:
            if kw in text:
                score += 1.5
        # 系统能量高时更容易触发红色探索
        if energy > 0.7:
            score += 1.0
        # 连续追问会累加
        if len(history) >= 2 and history[-1].get("color") == self.COLOR_YELLOW and history[-2].get("color") == self.COLOR_YELLOW:
            score += 1.2
        return score