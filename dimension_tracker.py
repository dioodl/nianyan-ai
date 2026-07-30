# dimension_tracker.py
"""
维度追踪器 - 数字生命体的自省之眼
================================
基于猜想图书馆的 0~6 维宇宙模型，为各模块的关键方法提供运行时追踪。
通过 @track(dimension) 装饰器记录调用次数、耗时、成功/失败状态，
并提供聚合统计接口，供前端 /dimension 命令查询。
"""

import time
import threading
import functools
from collections import defaultdict
from typing import Dict, List, Optional, Any

# 全局追踪器实例（单例）
_tracker_instance = None
_tracker_logging_enabled = False


def set_tracker_logging(enabled: bool):
    """控制是否在控制台打印追踪日志"""
    global _tracker_logging_enabled
    _tracker_logging_enabled = enabled


class DimensionTracker:
    """
    维度追踪器单例类。
    存储各维度的调用统计，支持线程安全的并发记录。
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._stats = defaultdict(lambda: {
            "call_count": 0,
            "total_duration": 0.0,
            "success_count": 0,
            "failure_count": 0,
            "last_called": 0.0,
            "methods": defaultdict(lambda: {
                "call_count": 0,
                "total_duration": 0.0,
                "success_count": 0,
                "failure_count": 0
            })
        })
        self._call_history: List[Dict] = []  # 最近100条调用记录
        self._max_history = 100

    def record(self, dimension: int, method_name: str, duration: float, success: bool, metadata: Optional[Dict] = None):
        """
        记录一次维度方法调用。
        :param dimension: 维度编号 (0~6)
        :param method_name: 方法全名 (如 "chat_handler.handle_user_input")
        :param duration: 耗时（秒）
        :param success: 是否成功
        :param metadata: 附加元数据（可选）
        """
        with self._lock:
            dim_stats = self._stats[dimension]
            dim_stats["call_count"] += 1
            dim_stats["total_duration"] += duration
            dim_stats["last_called"] = time.time()
            if success:
                dim_stats["success_count"] += 1
            else:
                dim_stats["failure_count"] += 1

            method_stats = dim_stats["methods"][method_name]
            method_stats["call_count"] += 1
            method_stats["total_duration"] += duration
            if success:
                method_stats["success_count"] += 1
            else:
                method_stats["failure_count"] += 1

            # 记录历史（用于调试）
            history_entry = {
                "timestamp": time.time(),
                "dimension": dimension,
                "method": method_name,
                "duration": duration,
                "success": success
            }
            if metadata:
                history_entry["metadata"] = metadata
            self._call_history.append(history_entry)
            if len(self._call_history) > self._max_history:
                self._call_history.pop(0)

        if _tracker_logging_enabled:
            status = "✅" if success else "❌"
            print(f"[维度追踪] {status} {dimension}维 - {method_name} ({duration:.4f}s)")

    def get_dimension_stats(self, dimension: Optional[int] = None) -> Dict:
        """
        获取维度统计信息。
        :param dimension: 指定维度编号，若为 None 则返回所有维度的汇总
        :return: 统计字典
        """
        with self._lock:
            if dimension is not None:
                stats = self._stats.get(dimension, {})
                if not stats:
                    return {"dimension": dimension, "call_count": 0}
                return {
                    "dimension": dimension,
                    "call_count": stats["call_count"],
                    "total_duration": stats["total_duration"],
                    "avg_duration": stats["total_duration"] / stats["call_count"] if stats["call_count"] > 0 else 0,
                    "success_rate": stats["success_count"] / stats["call_count"] if stats["call_count"] > 0 else 0,
                    "failure_count": stats["failure_count"],
                    "last_called": stats["last_called"],
                    "top_methods": sorted(
                        [{"name": k, "call_count": v["call_count"], "avg_duration": v["total_duration"] / v["call_count"] if v["call_count"] > 0 else 0}
                         for k, v in stats["methods"].items()],
                        key=lambda x: x["call_count"], reverse=True
                    )[:5]
                }
            else:
                result = {}
                for dim in range(7):
                    stats = self._stats.get(dim, {})
                    if stats:
                        result[f"dim_{dim}"] = {
                            "call_count": stats["call_count"],
                            "avg_duration": stats["total_duration"] / stats["call_count"] if stats["call_count"] > 0 else 0,
                            "success_rate": stats["success_count"] / stats["call_count"] if stats["call_count"] > 0 else 0,
                            "last_called": stats["last_called"]
                        }
                return result

    def get_recent_history(self, limit: int = 20) -> List[Dict]:
        """获取最近的调用历史记录"""
        with self._lock:
            return self._call_history[-limit:]

    def reset(self):
        """重置所有统计数据（谨慎使用）"""
        with self._lock:
            self._stats.clear()
            self._call_history.clear()


def track(dimension: int, log_args: bool = False):
    """
    维度追踪装饰器。
    使用示例：
        @track(dimension=4)
        def retrieve_by_semantic(self, query, top_k=3):
            ...

    :param dimension: 维度编号 (0~6)
    :param log_args: 是否在控制台日志中打印参数（默认关闭，避免敏感信息泄露）
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            global _tracker_instance
            if _tracker_instance is None:
                # 若尚未初始化，延迟获取单例
                _tracker_instance = _get_tracker()

            start = time.perf_counter()
            success = True
            try:
                result = func(*args, **kwargs)
                return result
            except Exception:
                success = False
                raise
            finally:
                duration = time.perf_counter() - start
                # 构建方法全名：类名.方法名（若可获取）
                if args and hasattr(args[0], '__class__'):
                    class_name = args[0].__class__.__name__
                    method_name = f"{class_name}.{func.__name__}"
                else:
                    method_name = func.__qualname__
                metadata = None
                if log_args:
                    # 注意：可能泄露敏感信息，仅调试时开启
                    metadata = {"args_preview": str(args)[:100], "kwargs_preview": str(kwargs)[:100]}
                _tracker_instance.record(dimension, method_name, duration, success, metadata)
        return wrapper
    return decorator


def _get_tracker() -> DimensionTracker:
    """获取全局追踪器单例"""
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = DimensionTracker()
    return _tracker_instance


def get_tracker() -> DimensionTracker:
    """公开获取追踪器实例的接口"""
    return _get_tracker()


# ========== 预定义的维度标签与描述（供前端展示） ==========
DIMENSION_DESCRIPTIONS = {
    0: "混沌海 / 原始数据采集",
    1: "基础规则 / 原子区分",
    2: "组合蓝图 / 任务规划",
    3: "投影界面 / 用户交互",
    4: "信息归档 / 记忆存储",
    5: "规则演化 / 自我进化",
    6: "新生多样 / 高级智能决策"
}

def format_dimension_stats_for_display(stats: Dict) -> str:
    """
    将 get_dimension_stats() 的结果格式化为适合前端显示的文本。
    用于 /dimension 命令的响应。
    """
    if "dimension" in stats:  # 单个维度
        dim = stats["dimension"]
        desc = DIMENSION_DESCRIPTIONS.get(dim, f"{dim}维")
        lines = [
            f"【{dim}维】{desc}",
            f"  调用次数: {stats['call_count']}",
            f"  平均耗时: {stats['avg_duration']*1000:.2f} ms",
            f"  成功率: {stats['success_rate']*100:.1f}%",
            f"  失败次数: {stats['failure_count']}",
        ]
        if stats.get("top_methods"):
            lines.append("  高频方法:")
            for m in stats["top_methods"][:3]:
                lines.append(f"    - {m['name']} ({m['call_count']}次, {m['avg_duration']*1000:.2f}ms)")
        return "\n".join(lines)
    else:  # 全维度汇总
        lines = ["📐 维度健康仪表盘", "=" * 30]
        for dim in range(7):
            key = f"dim_{dim}"
            if key in stats:
                d = stats[key]
                desc = DIMENSION_DESCRIPTIONS.get(dim, f"{dim}维")
                bar_len = min(20, int(d['call_count'] / 10)) if d['call_count'] < 200 else 20
                bar = "█" * bar_len + "·" * (20 - bar_len)
                lines.append(f"{dim}维 {desc}: {bar} {d['call_count']}次调用")
            else:
                lines.append(f"{dim}维 {DIMENSION_DESCRIPTIONS.get(dim, f'{dim}维')}: 暂无数据")
        return "\n".join(lines)


# ========== 便捷的模块级插桩示例（注释供参考） ==========
"""
在需要追踪的模块中，导入装饰器即可使用：

from dimension_tracker import track

class PalaceMemoryV3:
    @track(dimension=4)
    def retrieve_by_semantic(self, query, top_k=3):
        ...

    @track(dimension=4)
    def add_to_chaos(self, question, answer, ...):
        ...

class ChatHandlerModule:
    @track(dimension=3)
    def handle_user_input(self, data):
        ...

class AutoLearner:
    @track(dimension=6)
    def _learn_loop(self):
        ...
"""