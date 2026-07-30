# emotion_manager.py (调试增强版)
import sys
import json
import os

site_packages = r"C:\Users\diood\AppData\Local\Programs\Python\Python310\Lib\site-packages"
if site_packages not in sys.path:
    sys.path.insert(0, site_packages)

from config import EMOTION_EXTEND_FILE, EMOTION_KEYWORDS
from emotion_vector import EmotionVector
from emotion_accumulator import EmotionAccumulator


class EmotionManager:
    def __init__(self):
        self.filename = EMOTION_EXTEND_FILE
        self.keywords = EMOTION_KEYWORDS.copy()
        self.load()

        extra_keywords = {
            "开心": ["开心", "高兴", "快乐", "愉快", "喜悦", "乐", "嘻嘻", "哈哈", "期待", "盼望", "向往"],
            "难过": ["难过", "伤心", "悲伤", "痛苦", "难受", "想哭", "忧郁"],
            "愤怒": ["生气", "愤怒", "恼火", "发火", "气愤", "暴怒", "气死", "火大"],
            "恐惧": ["害怕", "恐惧", "担心", "焦虑", "不安", "恐慌", "紧张"],
            "惊讶": ["惊讶", "惊奇", "吃惊", "意外", "没想到", "天哪"],
            "好奇": ["好奇", "想知道", "探究", "为什么", "怎么回事"],
            "平静": ["平静", "冷静", "平和", "安静", "淡定"],
            "厌恶": ["讨厌", "厌恶", "反感", "恶心", "烦", "嫌弃"],
        }
        for emotion, words in extra_keywords.items():
            if emotion not in self.keywords:
                self.keywords[emotion] = []
            for w in words:
                if w not in self.keywords[emotion]:
                    self.keywords[emotion].append(w)

        self.accumulator = EmotionAccumulator(baseline_threshold=0.45, baseline_color=0.3)

        self.label_map = {
            "开心": "joy", "喜悦": "joy", "高兴": "joy", "快乐": "joy", "愉快": "joy",
            "难过": "sadness", "伤心": "sadness", "悲伤": "sadness", "痛苦": "sadness",
            "愤怒": "anger", "生气": "anger", "恼火": "anger", "气愤": "anger", "暴怒": "anger",
            "恐惧": "fear", "害怕": "fear", "担心": "fear", "焦虑": "fear", "恐慌": "fear",
            "惊讶": "surprise", "惊奇": "surprise", "吃惊": "surprise", "意外": "surprise",
            "好奇": "curious", "想知道": "curious", "探究": "curious",
            "平静": "calm", "冷静": "calm", "平和": "calm", "安静": "calm",
            "厌恶": "disgust", "讨厌": "disgust", "反感": "disgust", "恶心": "disgust",
            "中性": "neutral", "neutral": "neutral"
        }

        self.sentiment_model = None
        self._init_sentiment_model()

        self.TERNARY_POSITIVE_THRESHOLD = 0.2
        self.TERNARY_NEGATIVE_THRESHOLD = -0.2

        # 消息总线引用（由 main.py 注入）
        self.bus = None

    def _init_sentiment_model(self):
        try:
            from snownlp import SnowNLP
            self.sentiment_model = SnowNLP
            print("✅ SnowNLP 情感分析模型加载成功")
        except ImportError:
            print("⚠️ SnowNLP 未安装，将使用规则映射。安装命令: pip install snownlp")
            self.sentiment_model = None
        except Exception as e:
            print(f"⚠️ SnowNLP 加载失败: {e}，将使用规则映射")
            self.sentiment_model = None

    def load(self):
        try:
            with open(self.filename, 'r', encoding='utf-8') as f:
                ext = json.load(f)
                for emotion, words in ext.items():
                    if emotion in self.keywords:
                        self.keywords[emotion].extend([w for w in words if w not in self.keywords[emotion]])
                    else:
                        self.keywords[emotion] = words
        except FileNotFoundError:
            pass

    def save(self):
        with open(self.filename, 'w', encoding='utf-8') as f:
            json.dump(self.keywords, f, indent=2)

    def add_keywords(self, emotion, words):
        if emotion not in self.keywords:
            self.keywords[emotion] = []
        for w in words:
            if w not in self.keywords[emotion]:
                self.keywords[emotion].append(w)
        self.save()

    def get_emotion_vector(self, text: str) -> EmotionVector:
        if self.sentiment_model is not None:
            try:
                return self._model_based_mapping(text)
            except Exception as e:
                print(f"⚠️ 模型推理失败，降级使用规则映射: {e}")
        return self._rule_based_mapping(text)

    def _model_based_mapping(self, text: str) -> EmotionVector:
        s = self.sentiment_model(text)
        score = s.sentiments

        if score > 0.45:
            v, a, c, d, s_val, domain, secondary = 0.7, 0.5, score * 0.8, 0.4, 0.8, "joy", {"surprise": 0.1}
        elif score < 0.45:
            text_lower = text.lower()
            if any(kw in text_lower for kw in self.keywords.get('愤怒', [])):
                v, a, c, d, s_val, domain, secondary = -0.5, 0.7, (1 - score) * 0.8, 0.8, -0.5, "anger", {"disgust": 0.2}
            else:
                v, a, c, d, s_val, domain, secondary = -0.6, -0.3, (1 - score) * 0.7, -0.5, -0.3, "sadness", {}
        else:
            v, a, c, d, s_val, domain, secondary = 0.0, 0.0, score * 0.3, 0.0, 0.0, "neutral", {}

        vec = EmotionVector(valence=v, arousal=a, color=c, dominance=d, social=s_val, domain=domain, secondary=secondary)
        return vec

    def _rule_based_mapping(self, text: str) -> EmotionVector:
        text_lower = text.lower()
        chinese_label = self.get_emotion_label(text_lower)
        english_label = self.label_map.get(chinese_label, "neutral")

        mapping = {
            "joy": (0.7, 0.5, 0.55, 0.4, 0.8, "joy", {"surprise": 0.1}),
            "sadness": (-0.6, -0.3, 0.45, -0.5, -0.3, "sadness", {}),
            "anger": (-0.5, 0.7, 0.60, 0.8, -0.5, "anger", {"disgust": 0.2}),
            "fear": (-0.6, 0.6, 0.55, -0.7, -0.8, "fear", {"surprise": 0.2}),
            "surprise": (0.2, 0.8, 0.50, -0.2, 0.0, "surprise", {}),
            "disgust": (-0.5, 0.3, 0.45, 0.2, -0.6, "disgust", {"anger": 0.1}),
            "curious": (0.3, 0.4, 0.35, 0.1, 0.5, "curious", {"joy": 0.1}),
            "calm": (0.1, -0.5, 0.15, 0.3, 0.2, "calm", {}),
            "neutral": (0.0, 0.0, 0.0, 0.0, 0.0, "neutral", {}),
        }

        if english_label in mapping:
            v, a, c, d, s_val, domain, secondary = mapping[english_label]
        else:
            v, a, c, d, s_val, domain, secondary = 0.0, 0.0, 0.0, 0.0, 0.0, "neutral", {}

        vec = EmotionVector(valence=v, arousal=a, color=c, dominance=d, social=s_val, domain=domain, secondary=secondary)
        return vec

    def get_emotion_label(self, text_lower: str) -> str:
        for emotion, keywords in self.keywords.items():
            if any(kw in text_lower for kw in keywords):
                return emotion
        return "中性"

    def get_emotion(self, text: str) -> str:
        return self.get_emotion_label(text.lower())

    def update_accumulator(self, text: str, memory) -> EmotionVector:
        vec = self.get_emotion_vector(text)
        result = self.accumulator.update(vec, memory, text=text)

        # 推送状态更新到 Web 仪表盘（调试增强）
        if self.bus:
            state = self.accumulator.get_state()
            print(f"📢 [EmotionManager] 发布情绪状态: 效价={state['current_vector']['valence']:.2f}, 唤醒={state['current_vector']['arousal']:.2f}")
            self.bus.publish("emotion.state_changed", state)
        else:
            print("⚠️ [EmotionManager] self.bus 为 None，无法发布情绪状态")

        return result

    def get_current_emotion_state(self) -> dict:
        return self.accumulator.get_state()

    def check_emotion_trigger(self) -> dict:
        state = self.accumulator.get_state()
        intuition = self.accumulator.get_intuition()
        triggered = self.accumulator.consume_trigger()
        return {
            "triggered": triggered is not None,
            "trigger_vector": triggered.to_dict() if triggered else None,
            "intuition": intuition,
            "current_state": state
        }

    def get_ternary_emotion_state(self) -> int:
        state = self.accumulator.get_state()
        current_vec = state.get("current_vector", {})
        valence = current_vec.get("valence", 0.0)
        if valence >= self.TERNARY_POSITIVE_THRESHOLD:
            return 1
        elif valence <= self.TERNARY_NEGATIVE_THRESHOLD:
            return -1
        else:
            return 0

    def get_ternary_state_description(self) -> str:
        state = self.get_ternary_emotion_state()
        if state == 1:
            return "积极倾向"
        elif state == -1:
            return "消极倾向"
        else:
            return "中性/混沌"