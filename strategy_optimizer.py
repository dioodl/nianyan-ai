# strategy_optimizer.py
import json
import numpy as np
from config import STRATEGY_OPTIMIZER_FILE, EMOTION_KEYWORDS, STRATEGIES
from emotion_vector import EmotionVector


class StrategyOptimizer:
    """
    情绪-策略优化器，支持探索-利用平衡与情绪向量驱动的策略选择。
    """
    def __init__(self):
        self.filename = STRATEGY_OPTIMIZER_FILE
        self.weights = {}
        self.temperature = 1.0
        self.temperature_min = 0.1
        self.temperature_decay = 0.999
        self.load()

        # 策略的情绪原型向量（预设，后续可通过学习调整）
        self.strategy_prototypes = {
            "silence": EmotionVector(valence=0.0, arousal=-0.5, color=0.1, dominance=0.0, social=-0.5, domain="calm"),
            "listen": EmotionVector(valence=0.2, arousal=-0.3, color=0.15, dominance=-0.3, social=0.6, domain="calm"),
            "empathize": EmotionVector(valence=0.6, arousal=0.2, color=0.4, dominance=-0.2, social=0.8, domain="joy"),
            "analyze": EmotionVector(valence=0.1, arousal=-0.2, color=0.2, dominance=0.4, social=0.0, domain="calm"),
            "distract": EmotionVector(valence=0.4, arousal=0.5, color=0.5, dominance=0.2, social=0.5, domain="curious"),
        }

    def load(self):
        try:
            with open(self.filename, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.weights = data.get('weights', {})
                self.temperature = data.get('temperature', 1.0)
        except FileNotFoundError:
            for emotion in EMOTION_KEYWORDS.keys():
                self.weights[emotion] = {s: 1.0 for s in STRATEGIES}
            self.weights['neutral'] = {s: 1.0 for s in STRATEGIES}
            self.save()

    def save(self):
        with open(self.filename, 'w', encoding='utf-8') as f:
            json.dump({'weights': self.weights, 'temperature': self.temperature}, f, indent=2)

    def update(self, emotion, strategy, reward):
        reward_scaled = reward * 0.1
        if emotion not in self.weights:
            self.weights[emotion] = {s: 1.0 for s in STRATEGIES}
        self.weights[emotion][strategy] += reward_scaled
        self.weights[emotion][strategy] = max(0.1, min(5.0, self.weights[emotion][strategy]))
        self.save()

    def get_probs(self, emotion):
        if emotion not in self.weights:
            emotion = 'neutral'
        weights = self.weights[emotion]
        w = np.array(list(weights.values()))
        w = w - np.max(w)
        exp_w = np.exp(w / max(self.temperature, 0.01))
        probs = exp_w / exp_w.sum()
        return {s: probs[i] for i, s in enumerate(weights.keys())}

    def select(self, emotion):
        probs = self.get_probs(emotion)
        strategies = list(probs.keys())
        probs_list = list(probs.values())
        chosen = np.random.choice(strategies, p=probs_list)
        self.temperature = max(self.temperature_min, self.temperature * self.temperature_decay)
        self.save()
        return chosen

    def select_by_emotion_vector(self, emotion_vec: EmotionVector) -> str:
        """基于情绪向量的余弦相似度选择策略（融合权重）"""
        best_strategy = None
        best_score = -1.0
        for strategy, prototype in self.strategy_prototypes.items():
            sim = emotion_vec.cosine_similarity(prototype)
            # 结合学习到的权重（如果有）
            weight = 1.0
            if 'neutral' in self.weights and strategy in self.weights['neutral']:
                weight = self.weights['neutral'][strategy]
            score = sim * weight
            if score > best_score:
                best_score = score
                best_strategy = strategy
        # 探索-利用：以一定概率随机探索
        if np.random.random() < 0.1:  # 10%探索率
            best_strategy = np.random.choice(STRATEGIES)
        return best_strategy or "analyze"

    def set_temperature(self, value: float):
        self.temperature = max(self.temperature_min, min(5.0, value))
        self.save()
        print(f"🌡️ 策略温度已调整为: {self.temperature:.3f}")

    def get_temperature(self) -> float:
        return self.temperature

    def reset_temperature(self):
        self.temperature = 1.0
        self.save()