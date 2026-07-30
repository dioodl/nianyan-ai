# message_bus.py (修复异步回调调度)
import asyncio
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


class MessageBus:
    def __init__(self, global_loop=None):
        self._subscribers = defaultdict(list)
        self.global_loop = global_loop
        self.lock = None  # 如需线程安全可在此扩展

    def subscribe(self, topic: str, callback):
        """订阅主题，callback 可以是同步或异步函数"""
        if callback not in self._subscribers[topic]:
            self._subscribers[topic].append(callback)
            logger.debug(f"SUBSCRIBE topic={topic}, callback={callback.__name__}")

    def unsubscribe(self, topic: str, callback):
        if callback in self._subscribers[topic]:
            self._subscribers[topic].remove(callback)

    def publish(self, topic: str, data):
        """发布消息，自动适配同步/异步回调"""
        if topic not in self._subscribers:
            return
        logger.debug(f"PUBLISH topic={topic}, data={data}")
        for cb in self._subscribers[topic]:
            if asyncio.iscoroutinefunction(cb):
                # 异步回调：提交到全局事件循环
                if self.global_loop and self.global_loop.is_running():
                    asyncio.run_coroutine_threadsafe(cb(data), self.global_loop)
                else:
                    # 尝试获取当前运行中的事件循环
                    try:
                        loop = asyncio.get_running_loop()
                        asyncio.run_coroutine_threadsafe(cb(data), loop)
                    except RuntimeError:
                        # 没有运行中的循环，创建临时循环执行（不推荐，仅作 fallback）
                        logger.warning(f"No running event loop for async callback {cb.__name__}, using temporary loop")
                        asyncio.run(cb(data))
            else:
                # 同步回调：直接调用
                cb(data)