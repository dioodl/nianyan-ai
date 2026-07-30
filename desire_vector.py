# desire_vector.py
"""
欲望向量模块 - 数字生命体的内在驱动力系统
==========================================
维护核心欲望的实时强度，根据系统状态、外部刺激、人格权重进行动态调节。
v14.8 - 新增 'longing' (渴求) 维度，提升主动探索能力。
         longing 会随着空闲时间线性增长，驱动内部议会更频繁地召开。
"""

import time
import json
import os
from typing import Dict, Optional


class DesireVector:
    """
    欲望向量类，维护并动态调节以下欲望强度 (0.0 ~ 1.0)：
    v14.8 新增：
    - longing:      渴求 (填补信息缺口，打破沉寂)
    已有维度：
    - curiosity:    求知欲 (填补信息缺口)
    - organize:     整理欲 (维护内部秩序)
    - explore:      探索欲 (无目的横向联想)
    - create:       创造欲 (产出新内容)
    - resonate:     共鸣欲 (与用户情感同步)
    - achieve:      成就欲 (追求可量化成长)
    """

    def __init__(self, config_path: Optional[str] = None):
        # 已有维度初始值
        self.curiosity = 0.5
        self.organize = 0.3
        self.explore = 0.4
        self.create = 0.3
        self.resonate = 0.5
        self.achieve = 0.4
        # v14.8 新增：渴求维度，初始值较低，随时间上升
        self.longing = 0.1

        # 历史记录
        self.history: list = []
        self.max_history = 100

        # 配置路径
        self.config_path = config_path or "desire_state.json"
        self._load_state()

        print(f"🎯 [欲望向量] 初始化完成: 求知{self.curiosity:.2f} 整理{self.organize:.2f} "
              f"探索{self.explore:.2f} 创造{self.create:.2f} 共鸣{self.resonate:.2f} "
              f"成就{self.achieve:.2f} 渴求{self.longing:.2f}")

    # ---------- 核心更新方法 ----------
    def update(self, cognitive_state: Dict, external_stimuli: Dict = None):
        """
        根据认知引擎状态和外部刺激更新所有欲望强度。
        :param cognitive_state: 来自 CognitiveEngine.get_state() 的字典
        :param external_stimuli: 可选，如 {'user_emotion_intensity': 0.8, 'recent_feedback': 'positive'}
        """
        external_stimuli = external_stimuli or {}

        # 1. 求知欲
        confusion = cognitive_state.get("confusion_level", 0.0)
        knowledge_gap = self._estimate_knowledge_gap(cognitive_state)
        self.curiosity = self._smooth_update(
            self.curiosity,
            min(1.0, confusion * 1.2 + knowledge_gap * 0.8),
            weight=0.3
        )

        # 2. 整理欲
        chaos_count = cognitive_state.get("chaos_count", 0)
        low_utility_count = cognitive_state.get("low_utility_count", 0)
        organize_pressure = min(1.0, chaos_count / 20 + low_utility_count / 10)
        self.organize = self._smooth_update(
            self.organize,
            organize_pressure,
            weight=0.25
        )

        # 3. 探索欲
        energy = cognitive_state.get("curiosity_energy", 0.5)
        is_idle = cognitive_state.get("is_idle", False)
        explore_target = energy * (1.2 if is_idle else 0.6)
        self.explore = self._smooth_update(
            self.explore,
            min(1.0, explore_target),
            weight=0.2
        )

        # 4. 创造欲
        emotion_valence = cognitive_state.get("emotion_valence", 0.0)
        high_crack_count = cognitive_state.get("high_crack_count", 0)
        create_target = ((emotion_valence + 1) / 2) * min(1.0, high_crack_count / 5)
        self.create = self._smooth_update(
            self.create,
            min(1.0, create_target),
            weight=0.2
        )

        # 5. 共鸣欲
        user_emotion_intensity = external_stimuli.get("user_emotion_intensity", 0.0)
        social_tendency = cognitive_state.get("social_tendency", 0.5)
        resonate_target = max(user_emotion_intensity, social_tendency * 0.8)
        self.resonate = self._smooth_update(
            self.resonate,
            min(1.0, resonate_target),
            weight=0.25
        )

        # 6. 成就欲
        recent_positive = external_stimuli.get("recent_feedback") == "positive"
        recent_achievements = cognitive_state.get("recent_achievements", 0)
        achieve_target = 0.8 if recent_positive else 0.4
        achieve_target += min(0.2, recent_achievements * 0.05)
        self.achieve = self._smooth_update(
            self.achieve,
            min(1.0, achieve_target),
            weight=0.3
        )

        # v14.8 新增：7. 渴求维度 — 随空闲时间增长，用户交互后下降
        idle_seconds = cognitive_state.get("idle_seconds", 0)
        if idle_seconds > 300:  # 空闲5分钟后开始累积
            # 对数增长，避免无限膨胀，上限1.0
            longing_target = min(1.0, 0.1 + 0.4 * (idle_seconds / 3600))
        else:
            # 用户刚刚活动过，渴求迅速下降
            longing_target = 0.1
        self.longing = self._smooth_update(self.longing, longing_target, weight=0.15)

        # 记录历史
        self._record_history()
        self._save_state()

    # ---------- 辅助方法 ----------
    def _estimate_knowledge_gap(self, cognitive_state: Dict) -> float:
        confusion = cognitive_state.get("confusion_level", 0.0)
        memory_hit_rate = cognitive_state.get("memory_hit_rate", 1.0)
        gap = confusion * (1 - memory_hit_rate) * 1.5
        return min(1.0, gap)

    def _smooth_update(self, current: float, target: float, weight: float = 0.3) -> float:
        return current * (1 - weight) + target * weight

    def _record_history(self):
        snapshot = {
            "timestamp": time.time(),
            "curiosity": self.curiosity,
            "organize": self.organize,
            "explore": self.explore,
            "create": self.create,
            "resonate": self.resonate,
            "achieve": self.achieve,
            "longing": self.longing
        }
        self.history.append(snapshot)
        if len(self.history) > self.max_history:
            self.history.pop(0)

    # ---------- 决策接口 ----------
    def get_weights(self) -> Dict[str, float]:
        total = (self.curiosity + self.organize + self.explore +
                 self.create + self.resonate + self.achieve + self.longing)
        if total == 0:
            keys = ["curiosity", "organize", "explore", "create", "resonate", "achieve", "longing"]
            return {k: 1/len(keys) for k in keys}
        return {
            "curiosity": self.curiosity / total,
            "organize": self.organize / total,
            "explore": self.explore / total,
            "create": self.create / total,
            "resonate": self.resonate / total,
            "achieve": self.achieve / total,
            "longing": self.longing / total
        }

    def get_dominant_desire(self) -> str:
        desires = {
            "curiosity": self.curiosity,
            "organize": self.organize,
            "explore": self.explore,
            "create": self.create,
            "resonate": self.resonate,
            "achieve": self.achieve,
            "longing": self.longing
        }
        return max(desires, key=desires.get)

    def get_state(self) -> Dict:
        return {
            "desire_vector": {
                "curiosity": self.curiosity,
                "organize": self.organize,
                "explore": self.explore,
                "create": self.create,
                "resonate": self.resonate,
                "achieve": self.achieve,
                "longing": self.longing
            },
            "dominant": self.get_dominant_desire(),
            "normalized_weights": self.get_weights()
        }

    # ---------- 持久化 ----------
    def _save_state(self):
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump({
                    "curiosity": self.curiosity,
                    "organize": self.organize,
                    "explore": self.explore,
                    "create": self.create,
                    "resonate": self.resonate,
                    "achieve": self.achieve,
                    "longing": self.longing,
                    "last_updated": time.time()
                }, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ [欲望向量] 保存状态失败: {e}")

    def _load_state(self):
        if not os.path.exists(self.config_path):
            return
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.curiosity = data.get("curiosity", self.curiosity)
                self.organize = data.get("organize", self.organize)
                self.explore = data.get("explore", self.explore)
                self.create = data.get("create", self.create)
                self.resonate = data.get("resonate", self.resonate)
                self.achieve = data.get("achieve", self.achieve)
                self.longing = data.get("longing", self.longing)
                print(f"📂 [欲望向量] 从 {self.config_path} 加载了上次状态")
        except Exception as e:
            print(f"⚠️ [欲望向量] 加载状态失败: {e}")

    # ---------- 手动调节接口 ----------
    def apply_permanent_modifier(self, desire_name: str, delta: float):
        if hasattr(self, desire_name):
            current = getattr(self, desire_name)
            setattr(self, desire_name, max(0.1, min(1.0, current + delta)))
            self._save_state()
            print(f"🔧 [欲望向量] 永久调整 {desire_name}: {current:.2f} → {getattr(self, desire_name):.2f}")
        else:
            print(f"⚠️ [欲望向量] 未知的欲望名称: {desire_name}")

    # ---------- 微量调节接口（供内部议会反哺欲望孵化） ----------
    def modify(self, dimension: str, delta: float):
        if hasattr(self, dimension):
            current = getattr(self, dimension)
            new_value = max(0.0, min(1.0, current + delta))
            setattr(self, dimension, new_value)
            self._save_state()
            print(f"📊 [欲望向量] {dimension}: {current:.2f} -> {new_value:.2f} (Δ={delta:+.2f})")
        else:
            print(f"⚠️ [欲望向量] modify: 未知维度 '{dimension}'")

    def decay(self, factor: float = 0.995):
        """每日衰减所有欲望强度（向中性回归），渴求维度除外（保持较高基值）"""
        self.curiosity = self._decay_value(self.curiosity, factor)
        self.organize = self._decay_value(self.organize, factor)
        self.explore = self._decay_value(self.explore, factor)
        self.create = self._decay_value(self.create, factor)
        self.resonate = self._decay_value(self.resonate, factor)
        self.achieve = self._decay_value(self.achieve, factor)
        # longing 不衰减，它只被用户交互重置
        self._save_state()
        print(f"📉 [欲望向量] 每日衰减完成，当前主导: {self.get_dominant_desire()}")

    def _decay_value(self, value: float, factor: float) -> float:
        return value * factor + 0.5 * (1 - factor)

    def __repr__(self):
        return (f"DesireVector(curiosity={self.curiosity:.2f}, organize={self.organize:.2f}, "
                f"explore={self.explore:.2f}, create={self.create:.2f}, "
                f"resonate={self.resonate:.2f}, achieve={self.achieve:.2f}, "
                f"longing={self.longing:.2f})")