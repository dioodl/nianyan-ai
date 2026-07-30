# intent_classifier.py
import threading
import re
from openai import OpenAI
from message_bus import MessageBus
from config import DEFAULT_BASE_URL, DEFAULT_MODEL, DEFAULT_API_KEY

try:
    from config import INTENT_CLASSIFIER_MODEL
except ImportError:
    INTENT_CLASSIFIER_MODEL = DEFAULT_MODEL

class IntentClassifierModule:
    def __init__(self, bus: MessageBus):
        self.bus = bus
        self.client = OpenAI(base_url=DEFAULT_BASE_URL, api_key=DEFAULT_API_KEY)
        self.model = INTENT_CLASSIFIER_MODEL
        bus.subscribe("user.input.raw", self.on_user_input)

    def on_user_input(self, data):
        if isinstance(data, dict):
            user_input = data.get("text", "")
            deep_reasoning = data.get("deep_reasoning", False)
        else:
            user_input = data
            deep_reasoning = False
        print(f"意图分类器收到输入: {user_input}")
        threading.Thread(target=self.classify, args=(user_input, "auto", deep_reasoning), daemon=True).start()

    def classify(self, user_input: str, mode: str, deep_reasoning: bool = False):
        try:
            if mode == "chat":
                intent = "CHAT"
            elif mode == "exec":
                intent = "EXEC"
            else:
                intent = self.fast_match(user_input)
                if intent is None:
                    intent = self.llm_classify(user_input)
            self.bus.publish("intent.result", {
                "input": user_input,
                "intent": intent,
                "deep_reasoning": deep_reasoning
            })
        except Exception as e:
            print(f"意图分类异常: {e}")

    def fast_match(self, text: str):
        text_lower = text.lower()
        
        # 数学计算优先 → 聊天
        if re.search(r'\d+\s*[\+\-\*/]\s*\d+\s*[=＝？]?', text):
            return "CHAT"

        # ========== 强制 EXEC：文件创建相关指令 ==========
        file_creation_patterns = [
            r'(创建|新建|生成|写|保存).*(文件|文档|代码|脚本)',      # 创建文件/写代码等
            r'(桌面|下载|文档).*(创建|生成|保存).*\.(txt|py|md|json)', # 桌面创建 .py
            r'内容为.*print',                                       # 内容为 print...
            r'内容.*print\(.*\)',                                   # 内容包含 print(...)
            r"内容为\s*print\s*\(",                                 # 内容为 print(
            r"内容为\s*['\"]?print",                                # 内容为 'print 或 "print
            r'hello\.py',                                           # hello.py
            r'\.py.*内容',                                          # .py 后跟内容
            r'print\([\'"]Hello',                                   # print('Hello 或 print("Hello
        ]
        for pattern in file_creation_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return "EXEC"

        # 原有的执行关键词
        exec_keywords = [
            "帮我", "生成", "创建", "写一篇", "搜索", "总结", "发送", "下载", 
            "保存", "打开", "删除", "修改", "复制", "移动", "重命名", "运行", 
            "执行", "安装", "卸载", "清空", "备份", "恢复", "压缩", "解压",
            "新建", "写入", "输出到", "保存为", "存为"
        ]
        chat_keywords = [
            "觉得", "认为", "感觉", "聊聊", "说说", "什么是", "为什么", "如何", 
            "怎样", "哪些", "哪个", "哪里", "何时", "可否", "能否", "请解释", 
            "请介绍", "有哪些", "是什么", "有什么区别", "举例说明", "定义", 
            "概念", "原理", "功能", "应用案例", "作用", "好处", "坏处", "等于", 
            "计算", "结果", "多少"
        ]
        
        if any(kw in text_lower for kw in exec_keywords):
            return "EXEC"
        if any(kw in text_lower for kw in chat_keywords):
            return "CHAT"
        return None

    def llm_classify(self, text: str) -> str:
        prompt = f"""判断以下用户输入是“执行指令”（需要AI动手操作电脑或完成具体任务）还是“交流对话”（只需AI回答问题，无需操作）。只输出一个词：EXEC 或 CHAT。

示例：
输入：帮我写一篇800字仙侠小说
输出：EXEC
输入：你觉得今天天气怎么样？
输出：CHAT
输入：在桌面创建文件 test.txt，内容为 hello
输出：EXEC
输入：什么是量子计算？
输出：CHAT
输入：1+1=？
输出：CHAT

输入：{text}
输出："""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=32750
            )
            result = response.choices[0].message.content.strip().upper()
            return result if result in ("EXEC", "CHAT") else "CHAT"
        except Exception as e:
            print(f"LLM分类失败: {e}")
            return "CHAT"