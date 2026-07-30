# intent_router.py
import time
import uuid
from message_bus import MessageBus
from priority_arbiter import Instruction

class IntentRouter:
    def __init__(self, bus: MessageBus):
        self.bus = bus
        bus.subscribe("intent.result", self.on_intent)

    def on_intent(self, data):
        user_input = data["input"]
        intent = data["intent"]
        deep_reasoning = data.get("deep_reasoning", False)

        if intent == "CHAT":
            # 发布到聊天处理器，携带深度推理标志
            self.bus.publish(f"user_input.main", {
                "message": user_input,
                "user_id": "user",
                "deep_reasoning": deep_reasoning
            })
        else:  # EXEC
            # 创建指令并发布到任务执行器
            self.bus.publish("task.execute", Instruction(
                id=str(uuid.uuid4()),
                source="user",
                user_role="normal",
                type="task",
                content=user_input,
                timestamp=time.time()
            ))