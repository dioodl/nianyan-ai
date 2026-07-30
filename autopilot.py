# autopilot.py
import threading
import time
import asyncio
from message_bus import MessageBus
from config import IDLE_THRESHOLD_SECONDS, AUTO_PILOT_MODE, DEEP_STUDY_INTERVAL_SECONDS


class AutoPilot:
    """无人值守模式：空闲检测，触发智能学习"""
    def __init__(self, bus: MessageBus, smart_learner, global_loop: asyncio.AbstractEventLoop):
        self.bus = bus
        self.smart_learner = smart_learner
        self.global_loop = global_loop
        self.last_activity = time.time()
        self.last_learn_time = 0
        self.running = True
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()
        bus.subscribe("user.input.raw", self._on_activity)
        bus.subscribe("user_input.main", self._on_activity)

    def _on_activity(self, _):
        self.last_activity = time.time()

    def _monitor_loop(self):
        while self.running:
            time.sleep(60)
            if not AUTO_PILOT_MODE:
                continue
            idle_time = time.time() - self.last_activity
            now = time.time()
            if idle_time > IDLE_THRESHOLD_SECONDS and (now - self.last_learn_time) > DEEP_STUDY_INTERVAL_SECONDS:
                self.last_learn_time = now
                print("🤖 无人值守：系统空闲，触发智能学习")
                if self.global_loop and self.global_loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        self.smart_learner.decide_and_learn(),
                        self.global_loop
                    )
                else:
                    print("⚠️ 全局事件循环未运行，无法触发学习")

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)