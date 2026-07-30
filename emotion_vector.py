# emotion_vector.py
"""
情绪向量 - 基于“潜在数值”框架的情绪表示
========================================
效价(valence)：-1(极度负面) ~ +1(极度正面)
唤醒度(arousal)：-1(极度平静) ~ +1(极度激动)
颜色条(color)：0(白/平静) ~ 1(黑/强烈)
支配度(dominance)：-1(被支配/无力) ~ +1(支配/掌控)
社交倾向(social)：-1(回避/疏离) ~ +1(趋近/亲和)
领域(domain)：主导情绪标签
次要情绪(secondary)：其他情绪成分的字典
"""

from dataclasses import dataclass, field
from typing import Optional, Dict


@dataclass
class EmotionVector:
    valence: float = 0.0      # -1 ~ +1
    arousal: float = 0.0      # -1 ~ +1
    color: float = 0.0        # 0 ~ 1
    dominance: float = 0.0    # -1 ~ +1
    social: float = 0.0       # -1 ~ +1
    domain: str = "neutral"
    secondary: Dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        # 确保数值在有效范围内
        self.valence = max(-1.0, min(1.0, self.valence))
        self.arousal = max(-1.0, min(1.0, self.arousal))
        self.color = max(0.0, min(1.0, self.color))
        self.dominance = max(-1.0, min(1.0, self.dominance))
        self.social = max(-1.0, min(1.0, self.social))

    def to_dict(self) -> dict:
        return {
            "valence": self.valence,
            "arousal": self.arousal,
            "color": self.color,
            "dominance": self.dominance,
            "social": self.social,
            "domain": self.domain,
            "secondary": self.secondary
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EmotionVector":
        return cls(
            valence=data.get("valence", 0.0),
            arousal=data.get("arousal", 0.0),
            color=data.get("color", 0.0),
            dominance=data.get("dominance", 0.0),
            social=data.get("social", 0.0),
            domain=data.get("domain", "neutral"),
            secondary=data.get("secondary", {})
        )

    def __add__(self, other: "EmotionVector") -> "EmotionVector":
        """向量加法（用于叠加）"""
        # 合并次要情绪
        new_secondary = self.secondary.copy()
        for k, v in other.secondary.items():
            new_secondary[k] = new_secondary.get(k, 0.0) + v
        return EmotionVector(
            valence=self.valence + other.valence,
            arousal=self.arousal + other.arousal,
            color=self.color + other.color,
            dominance=self.dominance + other.dominance,
            social=self.social + other.social,
            domain=self.domain if self.domain != "neutral" else other.domain,
            secondary=new_secondary
        )

    def __mul__(self, weight: float) -> "EmotionVector":
        """标量乘法（用于加权）"""
        new_secondary = {k: v * weight for k, v in self.secondary.items()}
        return EmotionVector(
            valence=self.valence * weight,
            arousal=self.arousal * weight,
            color=self.color * weight,
            dominance=self.dominance * weight,
            social=self.social * weight,
            domain=self.domain,
            secondary=new_secondary
        )

    def normalize(self) -> "EmotionVector":
        """归一化到有效范围"""
        new_secondary = {k: max(0.0, min(1.0, v)) for k, v in self.secondary.items()}
        return EmotionVector(
            valence=max(-1.0, min(1.0, self.valence)),
            arousal=max(-1.0, min(1.0, self.arousal)),
            color=max(0.0, min(1.0, self.color)),
            dominance=max(-1.0, min(1.0, self.dominance)),
            social=max(-1.0, min(1.0, self.social)),
            domain=self.domain,
            secondary=new_secondary
        )

    def magnitude(self) -> float:
        """向量模长（用于计算强度）"""
        return (self.valence**2 + self.arousal**2 + self.color**2 + 
                self.dominance**2 + self.social**2) ** 0.5

    def cosine_similarity(self, other: "EmotionVector") -> float:
        """计算与另一个情绪向量的余弦相似度"""
        dot = (self.valence * other.valence + self.arousal * other.arousal + 
               self.color * other.color + self.dominance * other.dominance + 
               self.social * other.social)
        mag_self = self.magnitude()
        mag_other = other.magnitude()
        if mag_self == 0 or mag_other == 0:
            return 0.0
        return dot / (mag_self * mag_other)

    def get_color_zone(self) -> str:
        """根据颜色条返回情绪区域"""
        if self.color < 0.2:
            return "white"
        elif self.color < 0.4:
            return "green"
        elif self.color < 0.6:
            return "yellow"
        elif self.color < 0.8:
            return "red"
        else:
            return "black"