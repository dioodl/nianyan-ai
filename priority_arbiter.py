# priority_arbiter.py
import heapq
import threading
import time
from dataclasses import dataclass
from typing import Any
from message_bus import MessageBus
from risk_assessor import RiskAssessor   # 新增

@dataclass
class Instruction:
    id: str
    source: str
    user_role: str
    type: str
    content: Any
    timestamp: float
    priority: int = None

class PriorityCalculator:
    ROLE_WEIGHTS = {"admin": 100, "normal": 50, "guest": 10}
    SOURCE_WEIGHTS = {"user": 80, "planner": 40, "monitor": 20}
    TYPE_WEIGHTS = {"urgent": 90, "task": 60, "query": 30, "chat": 10}

    @staticmethod
    def compute(inst: Instruction) -> int:
        role = PriorityCalculator.ROLE_WEIGHTS.get(inst.user_role, 0)
        src = PriorityCalculator.SOURCE_WEIGHTS.get(inst.source, 0)
        typ = PriorityCalculator.TYPE_WEIGHTS.get(inst.type, 0)
        age = max(0, (time.time() - inst.timestamp) / 3600) * 0.1
        return role + src + typ + int(age)

class PriorityArbiter:
    def __init__(self, bus: MessageBus):
        self.bus = bus
        self.queue = []
        self.lock = threading.Lock()
        self.running = True
        self.worker = threading.Thread(target=self._dispatch_loop, daemon=True)
        self.worker.start()
        self.risk_assessor = RiskAssessor()   # 初始化风险判断

    def submit(self, instruction: Instruction):
        # 风险判断：高风险直接拒绝
        risk_level, reason = self.risk_assessor.assess(instruction.content)
        if risk_level == "high":
            self.bus.publish("output.display", f"⚠️ 高风险指令被拦截：{reason}")
            return
        elif risk_level == "medium":
            # 可增加确认机制，这里简化，仅警告并继续
            self.bus.publish("output.display", f"⚠️ 中风险指令：{reason}，已执行但请注意。")
        # 正常排队
        instruction.priority = PriorityCalculator.compute(instruction)
        with self.lock:
            heapq.heappush(self.queue, (-instruction.priority, instruction.timestamp, instruction))

    def _dispatch_loop(self):
        while self.running:
            with self.lock:
                if self.queue:
                    _, _, inst = heapq.heappop(self.queue)
                else:
                    time.sleep(0.1)
                    continue
            if inst.type == "urgent":
                self.bus.publish("control.urgent", inst.content)
            elif inst.type == "task":
                self.bus.publish("task.execute", inst)
            else:
                self.bus.publish("user.input.raw", inst.content)

    def stop(self):
        self.running = False