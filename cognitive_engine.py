# cognitive_engine.py (修复版：新增能量管理方法)
"""
认知引擎模块 - 数字生命体的核心状态管理中心
============================================
维护好奇心能量、困惑水平、痛苦指数、情感倾向等核心认知状态，
并集成了欲望向量（DesireVector），为内部议会和规划裁决器提供统一的决策依据。
"""

import time
import threading
import random
from typing import Dict, Optional, Any
from message_bus import MessageBus
from desire_vector import DesireVector


class CognitiveEngine:
    def __init__(self, bus: MessageBus,
                 intent_classifier=None,
                 chat_handler=None,
                 palace_memory=None,
                 auto_learner=None,
                 internal_monitor=None,
                 smart_learner=None,
                 inner_world=None):
        self.bus = bus
        self.intent_classifier = intent_classifier
        self.chat_handler = chat_handler
        self.palace = palace_memory
        self.auto_learner = auto_learner
        self.internal_monitor = internal_monitor
        self.smart_learner = smart_learner
        self.inner_world = inner_world

        # 核心状态变量
        self.curiosity_energy = 0.5        # 好奇心能量 (0~1)
        self.confusion_level = 0.0          # 困惑水平 (0~1)
        self.pain_level = 0.0              # 痛苦指数 (0~1)
        self.social_tendency = 0.5         # 社交倾向 (0~1)
        self.emotion_valence = 0.0         # 当前情绪效价 (-1~1)
        self.emotion_arousal = 0.0         # 当前情绪唤醒度 (-1~1)

        # 记忆相关统计
        self.memory_hit_rate = 1.0         # 近期记忆命中率
        self.chaos_count = 0               # 混沌海条目数
        self.low_utility_count = 0         # 低效用记忆数
        self.high_crack_count = 0          # 高裂纹记忆数
        self.recent_achievements = 0       # 近期成就计数

        # 空闲状态
        self.is_idle = False
        self.last_activity_time = time.time()
        self.idle_threshold = 600  # 10分钟

        # 外部刺激缓存
        self.external_stimuli: Dict[str, Any] = {}

        # 初始化欲望向量
        self.desire_vector = DesireVector()

        # 运行状态
        self.running = False
        self.update_thread = None
        self.update_interval = 30  # 每30秒更新一次状态

        # 订阅消息总线事件
        bus.subscribe("internal.confusion", self.on_confusion)
        bus.subscribe("chat.response.sent", self.on_response_sent)
        bus.subscribe("emotion.state_changed", self.on_emotion_changed)
        bus.subscribe("user.input.raw", self.on_user_activity)
        bus.subscribe("user_input.main", self.on_user_activity)
        bus.subscribe("system.idle", self.on_system_idle)

        print("🧠 [认知引擎] 初始化完成，欲望向量已集成")

    # ---------- 事件回调 ----------
    def on_confusion(self, data):
        """接收到困惑事件，提升困惑水平"""
        error = data.get("error", 0.0)
        # 确保 error 是浮点数
        try:
            error = float(error)
        except (ValueError, TypeError):
            error = 0.0
        self.confusion_level = min(1.0, self.confusion_level + error * 0.3)
        # 困惑时略微降低能量
        self.curiosity_energy = max(0.1, self.curiosity_energy - 0.02)

    def on_response_sent(self, data):
        """回答发送后，记录记忆命中情况，调整能量"""
        memory_hit = data.get("memory_hit", False)
        # 更新记忆命中率（简单移动平均）
        alpha = 0.3
        self.memory_hit_rate = self.memory_hit_rate * (1 - alpha) + (1.0 if memory_hit else 0.0) * alpha

        # 回答完成，消耗一点能量，但如果是深度推理则消耗更多
        deep = data.get("deep_reasoning", False)
        energy_cost = 0.03 if deep else 0.01
        self.curiosity_energy = max(0.1, self.curiosity_energy - energy_cost)

    def on_emotion_changed(self, data):
        """情绪状态更新"""
        current = data.get("current_vector", {})
        self.emotion_valence = current.get("valence", 0.0)
        self.emotion_arousal = current.get("arousal", 0.0)
        # 高效价时略微增加能量
        if self.emotion_valence > 0.3:
            self.curiosity_energy = min(1.0, self.curiosity_energy + 0.02)

    def on_user_activity(self, _):
        """用户活动，重置空闲状态，恢复能量"""
        self.last_activity_time = time.time()
        self.is_idle = False
        # 用户互动是最佳的能量来源
        self.curiosity_energy = min(1.0, self.curiosity_energy + 0.05)
        # 社交倾向根据互动频率提升
        self.social_tendency = min(1.0, self.social_tendency + 0.05)

    def on_system_idle(self, data):
        """系统空闲事件"""
        idle_seconds = data.get("idle_seconds", 0)
        if idle_seconds > self.idle_threshold:
            self.is_idle = True
            # 空闲时社交倾向逐渐衰减
            self.social_tendency = max(0.1, self.social_tendency - 0.02)

    # ---------- 状态更新循环 ----------
    def start(self):
        """启动认知引擎的后台更新线程"""
        if self.running:
            return
        self.running = True
        self.update_thread = threading.Thread(target=self._update_loop, daemon=True)
        self.update_thread.start()
        print("🧠 [认知引擎] 后台更新线程已启动")

    def stop(self):
        self.running = False
        if self.update_thread:
            self.update_thread.join(timeout=2)

    def _update_loop(self):
        """定期更新内部状态和欲望向量"""
        while self.running:
            time.sleep(self.update_interval)

            # 1. 自然衰减
            self._apply_natural_decay()

            # 2. 从记忆宫殿同步统计信息
            self._sync_memory_stats()

            # 3. 从里世界同步痛苦指数
            self._sync_inner_world()

            # 4. 更新欲望向量
            cognitive_state = self.get_state()
            self.desire_vector.update(cognitive_state, self.external_stimuli)

            # 5. 发布状态更新事件
            self.bus.publish("cognitive.state.updated", self.get_state())

            # 6. 清理过期的外部刺激
            self.external_stimuli.clear()

    def _apply_natural_decay(self):
        """自然衰减：能量、困惑、社交倾向随时间缓慢回归"""
        # 能量衰减（空闲时更快）
        decay_rate = 0.005 if self.is_idle else 0.002
        self.curiosity_energy = max(0.1, self.curiosity_energy - decay_rate)

        # 困惑自然消退
        self.confusion_level = max(0.0, self.confusion_level - 0.01)

        # 社交倾向衰减
        self.social_tendency = max(0.1, self.social_tendency - 0.005)

    def _sync_memory_stats(self):
        """从记忆宫殿同步统计信息"""
        if not self.palace:
            return
        try:
            index = self.palace.index
            entries = index.get("entries", [])
            self.chaos_count = sum(1 for e in entries if e.get("is_chaos", False))
            self.low_utility_count = sum(1 for e in entries if e.get("utility", 0.5) < 0.3 and not e.get("is_chaos", False))
            self.high_crack_count = sum(1 for e in entries if e.get("crack_depth", 0) >= 2)
        except Exception as e:
            print(f"⚠️ [认知引擎] 同步记忆统计失败: {e}")

    def _sync_inner_world(self):
        """从里世界同步痛苦指数"""
        if self.inner_world:
            try:
                self.pain_level = self.inner_world.get_pain_level()
            except:
                pass

    # ---------- 公共接口 ----------
    def get_state(self) -> Dict[str, Any]:
        """返回完整的认知状态，包含欲望向量"""
        state = {
            "curiosity_energy": self.curiosity_energy,
            "confusion_level": self.confusion_level,
            "pain_level": self.pain_level,
            "social_tendency": self.social_tendency,
            "emotion_valence": self.emotion_valence,
            "emotion_arousal": self.emotion_arousal,
            "memory_hit_rate": self.memory_hit_rate,
            "chaos_count": self.chaos_count,
            "low_utility_count": self.low_utility_count,
            "high_crack_count": self.high_crack_count,
            "recent_achievements": self.recent_achievements,
            "is_idle": self.is_idle,
            "last_activity": self.last_activity_time
        }
        # 合并欲望向量状态
        state.update(self.desire_vector.get_state())
        return state

    def set_external_stimuli(self, stimuli: Dict[str, Any]):
        """设置外部刺激，供下一轮欲望更新使用"""
        self.external_stimuli.update(stimuli)

    def add_achievement(self, count: int = 1):
        """记录成就（如完成一次深度自习）"""
        self.recent_achievements += count
        # 成就带来能量奖励
        self.curiosity_energy = min(1.0, self.curiosity_energy + 0.1 * count)
        # 设置外部刺激
        self.external_stimuli["recent_feedback"] = "positive"

    def record_user_feedback(self, is_positive: bool):
        """记录用户反馈"""
        self.external_stimuli["recent_feedback"] = "positive" if is_positive else "negative"
        if is_positive:
            self.curiosity_energy = min(1.0, self.curiosity_energy + 0.08)
            self.social_tendency = min(1.0, self.social_tendency + 0.1)
        else:
            self.confusion_level = min(1.0, self.confusion_level + 0.1)
            self.curiosity_energy = max(0.1, self.curiosity_energy - 0.05)

    def record_user_emotion_intensity(self, intensity: float):
        """记录用户情绪强度，供共鸣欲使用"""
        self.external_stimuli["user_emotion_intensity"] = intensity

    # ---------- 新增：能量管理方法 ----------
    def consume_energy(self, amount: float, source: str = "unknown"):
        """消耗好奇心能量"""
        self.curiosity_energy = max(0.1, self.curiosity_energy - amount)

    def add_energy(self, amount: float, source: str = "unknown"):
        """增加好奇心能量"""
        self.curiosity_energy = min(1.0, self.curiosity_energy + amount)