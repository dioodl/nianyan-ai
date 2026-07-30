# optimizer.py
import json
import time
from collections import defaultdict
from message_bus import MessageBus
from model_client import ModelRouter

class Optimizer:
    """性能优化器：分析原子操作统计数据，生成优化建议，可触发代码改进"""
    def __init__(self, bus: MessageBus, code_generator=None):
        self.bus = bus
        self.code_gen = code_generator
        self.router = getattr(bus, 'model_router', None) or ModelRouter(max_concurrent_requests=1)
        self.stats = defaultdict(list)
        bus.subscribe("atomic.action.completed", self.on_action_completed)

    def on_action_completed(self, data):
        action = data.get("action")
        duration = data.get("duration")
        success = data.get("success")
        if action:
            self.stats[action].append({
                "duration": duration,
                "success": success,
                "timestamp": time.time()
            })
            # 保留最近200条
            if len(self.stats[action]) > 200:
                self.stats[action] = self.stats[action][-200:]

    def get_performance_report(self, min_samples=3):
        """生成性能报告，需要至少 min_samples 条记录"""
        report = {}
        for action, records in self.stats.items():
            if len(records) < min_samples:
                continue
            durations = [r["duration"] for r in records if r["success"]]
            success_count = sum(1 for r in records if r["success"])
            total_count = len(records)
            avg_duration = sum(durations) / len(durations) if durations else 0
            success_rate = success_count / total_count if total_count > 0 else 0
            report[action] = {
                "avg_duration": avg_duration,
                "success_rate": success_rate,
                "sample_count": total_count
            }
        return report

    def auto_optimize(self, threshold_duration=2.0, threshold_failure_rate=0.1):
        """自动触发优化：阈值使用生产值"""
        report = self.get_performance_report(min_samples=3)
        if not report:
            return
        for action, metrics in report.items():
            if metrics["avg_duration"] > threshold_duration:
                print(f"⚠️ 优化触发：{action} 平均耗时 {metrics['avg_duration']:.3f}s > {threshold_duration}s")
                if self.code_gen:
                    self.code_gen.attempt_upgrade(
                        specific_module="atomic_actions.py",
                        failure_context=f"原子操作 {action} 执行缓慢，平均耗时 {metrics['avg_duration']:.3f}s，需要优化性能。"
                    )
            elif (1 - metrics["success_rate"]) > threshold_failure_rate:
                print(f"⚠️ 优化触发：{action} 失败率 {1 - metrics['success_rate']:.1%} > {threshold_failure_rate:.0%}")
                if self.code_gen:
                    self.code_gen.attempt_upgrade(
                        specific_module="atomic_actions.py",
                        failure_context=f"原子操作 {action} 失败率过高，成功率为 {metrics['success_rate']:.1%}，需要提高稳定性。"
                    )