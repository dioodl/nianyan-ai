# emotion_accumulator.py (复苏手术版)
"""
情绪累积器 - 基于“潜在数值”框架的实时情绪状态管理
================================================
维护当前叠加的情绪向量，检测是否突破阈值触发显形，
并在接近阈值时生成预感。
v13.4.6 - 增加语境对比衰减、自适应衰减、中性回归
v13.5.0 - 新增三值情绪状态输出，便于快速决策与监控
v13.5.1 - 新增中性短语防御，防止日常寒暄不合理触发情绪显形
"""

import time
import math
from typing import Optional, List, Dict
from emotion_vector import EmotionVector


class EmotionAccumulator:
    # 中性短语列表（正则匹配或精确包含）
    NEUTRAL_PHRASES = [
        "你是谁", "你叫什么", "介绍一下", "你好", "嗨", "在吗", 
        "谢谢", "好的", "嗯", "哦", "哈哈", "再见", "拜拜", 
        "ok", "hi", "hello", "我叫", "我是", "名字"
    ]
    NEUTRAL_DECAY_FACTOR = 0.2  # 中性情绪权重衰减系数

    def __init__(self, baseline_threshold: float = 0.45, baseline_color: float = 0.3):
        self.current_vector = EmotionVector()
        self.threshold = baseline_threshold
        self.baseline_color = baseline_color
        self.history: List[Dict] = []
        self.is_triggered = False
        self.pending_intuition: Optional[str] = None
        self.distance_to_threshold: float = baseline_threshold
        self.decay_half_life = 86400 * 3

        # 语境衰减参数
        self.context_decay_factor = 0.3      # 语境转变时的衰减系数
        self.context_similarity_threshold = 0.3  # 余弦相似度低于此值视为语境转变
        self.intensity_decay_factor = 0.8    # 新情绪强度远低于累积情绪时的衰减系数
        self.neutral_regression_factor = 0.7 # 长期低情绪时的中性回归系数
        self.low_emotion_threshold = 0.3     # 低情绪判断阈值

        # ---------- 三进制优化配置 ----------
        self.TERNARY_POSITIVE_THRESHOLD = 0.2
        self.TERNARY_NEGATIVE_THRESHOLD = -0.2
        self.record_ternary_history = True
        self.ternary_history: List[int] = []

    def update(self, new_vector: EmotionVector, memory, top_k: int = 5, text: str = None) -> EmotionVector:
        """
        更新累积器：检索历史相似情绪，加权叠加。
        新增：中性短语防御，对日常寒暄降低情绪权重。
        """
        # ========== 中性短语防御 ==========
        if text:
            text_lower = text.lower()
            is_neutral = any(phrase in text_lower for phrase in self.NEUTRAL_PHRASES)
            if is_neutral:
                new_vector = new_vector * self.NEUTRAL_DECAY_FACTOR
                print(f"🛡️ [中性防御] 检测到中性短语，情绪权重降至{self.NEUTRAL_DECAY_FACTOR:.0%}")

        # 检索相似情绪记忆
        similar = []
        if memory:
            try:
                query = f"情绪领域：{new_vector.domain}"
                similar = memory.retrieve_by_semantic(
                    query, top_k=top_k, threshold=0.3, mem_type="emotion"
                )
            except Exception as e:
                print(f"检索情绪记忆失败: {e}")

        now = time.time()

        # ========== 1. 语境对比 ==========
        if self.current_vector.magnitude() > 0.01:
            context_similarity = new_vector.cosine_similarity(self.current_vector)
            if context_similarity < self.context_similarity_threshold:
                self.current_vector = self.current_vector * self.context_decay_factor
                print(f"🔄 [情绪语境转变] 相似度:{context_similarity:.2f} < 阈值{self.context_similarity_threshold}，旧情绪衰减至{self.context_decay_factor:.0%}")

        # ========== 2. 加权叠加新情绪 ==========
        total = new_vector
        for mem in similar:
            utility = mem.get("utility", 0.5)
            timestamp = mem.get("timestamp", now)
            time_decay = math.exp(-(now - timestamp) / self.decay_half_life)
            weight = utility * time_decay
            ev_data = mem.get("emotion_vector", {})
            if ev_data:
                hist_vec = EmotionVector.from_dict(ev_data)
                total += hist_vec * weight

        self.current_vector = total.normalize()

        # ========== 3. 自适应衰减 ==========
        if new_vector.color < self.current_vector.color * 0.5:
            self.current_vector = self.current_vector * self.intensity_decay_factor
            print(f"📉 [情绪强度衰减] 新情绪颜色({new_vector.color:.2f}) < 累积颜色({self.current_vector.color:.2f})的一半，加速衰减")

        # ========== 4. 长期低情绪中性回归 ==========
        if len(self.history) >= 3:
            recent_colors = [h["vector"].color for h in self.history[-3:]]
            if max(recent_colors) < self.low_emotion_threshold:
                self.current_vector.valence *= self.neutral_regression_factor
                self.current_vector.arousal *= self.neutral_regression_factor
                self.current_vector.color *= self.neutral_regression_factor
                print(f"🧘 [中性回归] 连续3轮低情绪，向中性靠拢")

        # ========== 5. 更新阈值与状态检查 ==========
        self._update_threshold()
        self.distance_to_threshold = self.threshold - self.current_vector.color

        print(f"📊 [情绪累积] 领域:{self.current_vector.domain} 颜色:{self.current_vector.color:.3f} "
              f"阈值:{self.threshold:.3f} 距离:{self.distance_to_threshold:.3f} "
              f"支配:{self.current_vector.dominance:.2f} 社交:{self.current_vector.social:.2f}")

        self._check_state()

        # 记录历史（包含三值状态）
        ternary_state = self._compute_ternary_state()
        self.history.append({
            "timestamp": now,
            "vector": self.current_vector,
            "triggered": self.is_triggered,
            "ternary_state": ternary_state
        })
        if len(self.history) > 20:
            self.history.pop(0)

        if self.record_ternary_history:
            self.ternary_history.append(ternary_state)
            if len(self.ternary_history) > 100:
                self.ternary_history.pop(0)

        return self.current_vector

    def _update_threshold(self):
        if not self.history:
            return
        recent = self.history[-5:]
        avg_color = sum(h["vector"].color for h in recent) / len(recent)
        avg_arousal = sum(h["vector"].arousal for h in recent) / len(recent)

        if avg_color < 0.3 and avg_arousal < 0.3:
            self.threshold = self.baseline_color + 0.15
        elif any(h["triggered"] for h in recent):
            self.threshold = self.baseline_color - 0.1
        else:
            self.threshold = self.baseline_color

        self.threshold = max(0.3, min(0.9, self.threshold))

    def _check_state(self):
        if self.distance_to_threshold <= 0:
            self.is_triggered = True
            self.pending_intuition = None
            print(f"💥 [情绪显形] 阈值突破！当前颜色:{self.current_vector.color:.3f}")
        elif self.distance_to_threshold < 0.18:
            self.is_triggered = False
            self._generate_intuition()
            print(f"💭 [情绪预感] 接近阈值，距离:{self.distance_to_threshold:.3f}")
        else:
            self.is_triggered = False
            self.pending_intuition = None

    def _generate_intuition(self):
        domain = self.current_vector.domain
        if domain == "anger" or self.current_vector.valence < -0.3:
            self.pending_intuition = "隐隐感到一丝烦躁……"
        elif domain == "sadness":
            self.pending_intuition = "心里有点闷闷的……"
        elif domain == "fear":
            self.pending_intuition = "总感觉有什么不对劲……"
        elif domain == "joy" or self.current_vector.valence > 0.3:
            self.pending_intuition = "似乎有什么好事要发生……"
        elif self.current_vector.color > 0.5:
            self.pending_intuition = "情绪好像要涌上来了……"
        else:
            self.pending_intuition = "有种说不清的感觉……"

    def get_intuition(self) -> Optional[str]:
        intuition = self.pending_intuition
        self.pending_intuition = None
        return intuition

    def consume_trigger(self) -> Optional[EmotionVector]:
        if self.is_triggered:
            triggered_vec = self.current_vector
            self.current_vector = EmotionVector(
                valence=self.current_vector.valence * 0.3,
                arousal=self.current_vector.arousal * 0.3,
                color=self.current_vector.color * 0.2,
                dominance=self.current_vector.dominance * 0.3,
                social=self.current_vector.social * 0.3,
                domain=self.current_vector.domain
            )
            self.is_triggered = False
            self.distance_to_threshold = self.threshold - self.current_vector.color
            return triggered_vec
        return None

    def get_state(self) -> dict:
        return {
            "current_vector": self.current_vector.to_dict(),
            "threshold": self.threshold,
            "distance": self.distance_to_threshold,
            "is_triggered": self.is_triggered,
            "intuition": self.pending_intuition,
            "color_zone": self.current_vector.get_color_zone(),
            "ternary_state": self.get_ternary_state()
        }

    # ---------- 三进制优化方法 ----------
    def _compute_ternary_state(self) -> int:
        valence = self.current_vector.valence
        if valence >= self.TERNARY_POSITIVE_THRESHOLD:
            return 1
        elif valence <= self.TERNARY_NEGATIVE_THRESHOLD:
            return -1
        else:
            return 0

    def get_ternary_state(self) -> int:
        return self._compute_ternary_state()

    def get_ternary_state_description(self) -> str:
        state = self.get_ternary_state()
        if state == 1:
            return "积极倾向"
        elif state == -1:
            return "消极倾向"
        else:
            return "中性/混沌"

    def get_zero_state_ratio(self, window: int = 20) -> float:
        if not self.record_ternary_history:
            return 0.0
        recent = self.ternary_history[-window:] if len(self.ternary_history) >= window else self.ternary_history
        if not recent:
            return 0.0
        zero_count = sum(1 for s in recent if s == 0)
        return zero_count / len(recent)

    def is_in_chaos_state(self, threshold: float = 0.6) -> bool:
        ratio = self.get_zero_state_ratio()
        return ratio >= threshold