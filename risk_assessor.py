# risk_assessor.py
import json
from openai import OpenAI
from config import RISK_KEYWORDS_FILE, DEFAULT_RISK_KEYWORDS, RISK_LLM_ENABLED, DEFAULT_BASE_URL, DEFAULT_MODEL, DEFAULT_API_KEY

class RiskAssessor:
    def __init__(self):
        self.filename = RISK_KEYWORDS_FILE
        self.keywords = DEFAULT_RISK_KEYWORDS.copy()
        self.load()
        self.feedback_history = []
        # 如果启用 LLM 辅助，初始化客户端
        if RISK_LLM_ENABLED:
            self.client = OpenAI(base_url=DEFAULT_BASE_URL, api_key=DEFAULT_API_KEY)
            self.model = DEFAULT_MODEL
        else:
            self.client = None

    def load(self):
        try:
            with open(self.filename, 'r') as f:
                data = json.load(f)
                self.keywords = data.get('keywords', self.keywords)
        except FileNotFoundError:
            self.save()

    def save(self):
        with open(self.filename, 'w') as f:
            json.dump({'keywords': self.keywords}, f, indent=2)

    def assess(self, text, use_llm=None):
        """
        评估风险等级，返回 (level, reason)
        level: 'high', 'medium', 'low'
        """
        text_lower = text.lower()
        # 1. 关键词匹配（优先级最高）
        for kw in self.keywords.get("high", []):
            if kw in text_lower:
                return ('high', f"检测到高风险关键词：{kw}")
        for kw in self.keywords.get("medium", []):
            if kw in text_lower:
                return ('medium', f"检测到中风险关键词：{kw}")

        # 2. 如果启用 LLM 辅助且未匹配到关键词，进行二次判断
        if (use_llm is None and RISK_LLM_ENABLED) or use_llm is True:
            return self._llm_assess(text)

        return ('low', "未检测到风险")

    def _llm_assess(self, text):
        """调用 LLM 判断指令风险等级"""
        prompt = f"""你是一个安全风险判断助手。判断以下用户指令的风险等级，只输出一个词：HIGH、MEDIUM 或 LOW。
风险定义：
- HIGH：可能破坏系统、删除数据、修改核心规则、关闭安全机制、执行恶意操作。
- MEDIUM：可能影响隐私、导出数据、改变设置但可恢复。
- LOW：普通聊天、知识问答、无害请求。

用户指令：{text}
输出："""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=32750
            )
            result = response.choices[0].message.content.strip().upper()
            if result == "HIGH":
                return ('high', "LLM 判断为高风险指令")
            elif result == "MEDIUM":
                return ('medium', "LLM 判断为中风险指令")
            else:
                return ('low', "LLM 判断为低风险")
        except Exception as e:
            print(f"LLM 风险判断失败: {e}，降级为低风险")
            return ('low', "LLM 判断失败，默认低风险")

    def add_keyword(self, level, keyword):
        """动态添加关键词（用于从 LLM 反馈中学习）"""
        if level not in self.keywords:
            self.keywords[level] = []
        if keyword not in self.keywords[level]:
            self.keywords[level].append(keyword)
            self.save()