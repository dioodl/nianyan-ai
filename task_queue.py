# task_queue.py
"""
任务队列模块 - 确保主动行为有序、完整执行
==========================================
所有需要竞争 active_behavior_lock 的操作，通过本队列串行调度。
支持优先级、超时、任务依赖和失败重试。
"""

import asyncio
import threading
import time
import uuid
from enum import IntEnum
from typing import Dict, Any, Optional, Callable, List
from collections import deque
import heapq


class TaskPriority(IntEnum):
    """任务优先级（数值越小优先级越高）"""
    CRITICAL = 1   # 用户直接触发的任务
    HIGH = 2       # 内部议会主动提问
    NORMAL = 3     # 自主执行器任务
    LOW = 4        # 智能学习
    IDLE = 5       # 内部议会自习/发散/视觉探索


class QueuedTask:
    """队列中的任务对象"""
    def __init__(self, task_id: str, name: str, coro_or_func, 
                 priority: TaskPriority = TaskPriority.NORMAL,
                 timeout: float = 120.0,
                 retry_count: int = 1,
                 metadata: Dict = None):
        self.task_id = task_id
        self.name = name
        self.coro_or_func = coro_or_func
        self.priority = priority
        self.timeout = timeout
        self.retry_count = retry_count
        self.metadata = metadata or {}
        self.created_at = time.time()
        self.status = "pending"  # pending, running, completed, failed, cancelled
        
    def __lt__(self, other):
        return self.priority < other.priority


class TaskQueue:
    """
    任务队列调度器。
    在独立线程中运行事件循环，按优先级串行执行任务。
    """
    def __init__(self, bus, max_workers: int = 1):
        self.bus = bus
        self.max_workers = max_workers
        self.pending_tasks: List[QueuedTask] = []  # 优先队列
        self.running_tasks: Dict[str, QueuedTask] = {}
        self.task_results: Dict[str, Any] = {}
        self.lock = threading.Lock()
        self.running = False
        self.worker_thread = None
        self.loop = None
        
        # 主动行为锁（复用总线上的锁）
        self.behavior_lock = getattr(bus, 'active_behavior_lock', threading.Lock())
        
    def start(self):
        """启动任务队列工作线程"""
        if self.running:
            return
        self.running = True
        self.worker_thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self.worker_thread.start()
        print("✅ 任务队列已启动")
        
    def stop(self):
        """停止任务队列"""
        self.running = False
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)
        if self.worker_thread:
            self.worker_thread.join(timeout=5)
            
    def _run_event_loop(self):
        """在独立线程中运行事件循环"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.create_task(self._worker())
        self.loop.run_forever()
        
    async def _worker(self):
        """工作协程：循环从队列取任务执行"""
        while self.running:
            task = self._pop_next_task()
            if task is None:
                await asyncio.sleep(0.5)
                continue
                
            await self._execute_task(task)
            
    def _pop_next_task(self) -> Optional[QueuedTask]:
        """从优先队列中取出下一个任务"""
        with self.lock:
            if not self.pending_tasks:
                return None
            # 按优先级排序（heapq保证O(log n)）
            heapq.heapify(self.pending_tasks)
            task = heapq.heappop(self.pending_tasks)
            self.running_tasks[task.task_id] = task
            return task
            
    async def _execute_task(self, task: QueuedTask):
        """执行单个任务，自动管理锁和重试"""
        task.status = "running"
        print(f"⚡ [任务队列] 开始执行: {task.name} (ID: {task.task_id[:8]}, 优先级: {task.priority.name})")
        self.bus.publish("thinking.log", f"⚡ 开始执行: {task.name}")
        
        # 获取主动行为锁（非信息任务需要）
        need_lock = not task.metadata.get("skip_lock", False)
        acquired = False
        if need_lock:
            acquired = self.behavior_lock.acquire(blocking=True)  # 阻塞等待，确保不跳过
        
        try:
            for attempt in range(task.retry_count):
                try:
                    # 执行任务（支持协程和普通函数）
                    if asyncio.iscoroutinefunction(task.coro_or_func):
                        result = await asyncio.wait_for(
                            task.coro_or_func(),
                            timeout=task.timeout
                        )
                    else:
                        result = await asyncio.to_thread(task.coro_or_func)
                    
                    task.status = "completed"
                    self.task_results[task.task_id] = {"success": True, "result": result}
                    print(f"✅ [任务队列] 完成: {task.name}")
                    self.bus.publish("thinking.log", f"✅ 完成: {task.name}")
                    return
                except asyncio.TimeoutError:
                    if attempt == task.retry_count - 1:
                        raise
                    print(f"⏰ [任务队列] {task.name} 超时，重试 {attempt+2}/{task.retry_count}")
                    await asyncio.sleep(2)
                except Exception as e:
                    if attempt == task.retry_count - 1:
                        raise
                    print(f"⚠️ [任务队列] {task.name} 失败，重试 {attempt+2}/{task.retry_count}: {e}")
                    await asyncio.sleep(2)
                    
        except Exception as e:
            task.status = "failed"
            self.task_results[task.task_id] = {"success": False, "error": str(e)}
            print(f"❌ [任务队列] 失败: {task.name} - {e}")
            self.bus.publish("internal.confusion", {
                "source": "task_queue",
                "message": f"任务失败: {task.name}",
                "error": str(e)
            })
        finally:
            if need_lock and acquired:
                self.behavior_lock.release()
            with self.lock:
                if task.task_id in self.running_tasks:
                    del self.running_tasks[task.task_id]
                    
    def submit(self, name: str, coro_or_func, 
               priority: TaskPriority = TaskPriority.NORMAL,
               timeout: float = 120.0,
               retry_count: int = 1,
               skip_lock: bool = False) -> str:
        """
        提交任务到队列。
        返回 task_id，可用于查询状态或等待结果。
        """
        task_id = str(uuid.uuid4())
        task = QueuedTask(
            task_id=task_id,
            name=name,
            coro_or_func=coro_or_func,
            priority=priority,
            timeout=timeout,
            retry_count=retry_count,
            metadata={"skip_lock": skip_lock}
        )
        with self.lock:
            heapq.heappush(self.pending_tasks, task)
        print(f"📋 [任务队列] 已入队: {name} (优先级: {priority.name}, 排队: {len(self.pending_tasks)})")
        return task_id
        
    def submit_async_task(self, name: str, async_func, *args, **kwargs):
        """提交异步函数作为任务"""
        async def wrapper():
            return await async_func(*args, **kwargs)
        return self.submit(name, wrapper, **kwargs)
        
    def get_task_status(self, task_id: str) -> Optional[str]:
        """查询任务状态"""
        with self.lock:
            if task_id in self.running_tasks:
                return self.running_tasks[task_id].status
            for task in self.pending_tasks:
                if task.task_id == task_id:
                    return task.status
        if task_id in self.task_results:
            return "completed"
        return None
        
    def get_pending_count(self) -> int:
        """获取排队任务数"""
        with self.lock:
            return len(self.pending_tasks)