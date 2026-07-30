# inner_world.py
"""
人工里世界 - 数字生命体的统一内部状态日志系统
==============================================
记录感知流、决策轨迹、内部状态，提供自我状态查询。
基于 SQLite 存储，支持时间范围检索与聚合统计。
v13.3 - 集成能量、痛苦、困惑追踪，支持自我反思。
v13.3.1 - 修复多线程写入锁问题，增加线程安全保护。
"""

import sqlite3
import json
import time
import os
import threading
from datetime import datetime
from typing import Optional, Dict, List, Any
from message_bus import MessageBus


class InnerWorld:
    """
    人工里世界核心类。
    订阅消息总线，将关键事件持久化到 SQLite 数据库。
    线程安全：所有写操作受 RLock 保护。
    """

    def __init__(self, bus: MessageBus, db_path: str = "inner_world.db"):
        self.bus = bus
        self.db_path = db_path
        self.db_lock = threading.RLock()  # 保护所有写操作
        self._init_db()
        self._subscribe_events()

    def _init_db(self):
        """初始化数据库表结构"""
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=10)
        with self.db_lock:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    source TEXT,
                    data TEXT,
                    metadata TEXT
                )
            """)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS internal_states (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    state_name TEXT NOT NULL,
                    value REAL,
                    description TEXT
                )
            """)
            # 新增索引加速查询
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_event_type ON events(event_type)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_event_timestamp ON events(timestamp)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_state_name ON internal_states(state_name)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_state_timestamp ON internal_states(timestamp)")
            self.conn.commit()

    def _subscribe_events(self):
        """订阅消息总线中的关键事件"""
        # 感知流
        self.bus.subscribe("user.input.raw", lambda d: self.record_event("perception.raw_input", "user", d))
        self.bus.subscribe("user_input.main", lambda d: self.record_event("perception.chat_input", "user", d))
        self.bus.subscribe("user.goal", lambda d: self.record_event("perception.goal", "user", {"goal": d}))

        # 决策轨迹
        self.bus.subscribe("intent.result", lambda d: self.record_event("decision.intent", "intent_classifier", d))
        self.bus.subscribe("thinking.log", lambda d: self.record_event("decision.thinking", "chat_handler", {"thought": d}))
        self.bus.subscribe("multi_agent.log", lambda d: self.record_event("decision.multi_agent", "chat_handler", {"log": d}))

        # 行动与结果
        self.bus.subscribe("atomic.action.completed", lambda d: self.record_event("action.completed", "atomic", d))
        self.bus.subscribe("task.execute", lambda d: self.record_event("action.task", "task_executor", {"instruction": str(d)}))

        # 内部状态
        self.bus.subscribe("monitor.score", lambda d: self.record_internal_state("performance_score", d.get("score", 0)))
        self.bus.subscribe("system.idle", lambda d: self.record_internal_state("idle_seconds", d.get("idle_seconds", 0)))
        self.bus.subscribe("auto_learn.start", lambda _: self.record_internal_state("auto_learn_active", 1))
        self.bus.subscribe("auto_learn.stop", lambda _: self.record_internal_state("auto_learn_active", 0))

        # 进化事件
        self.bus.subscribe("code.new_version", lambda d: self.record_event("evolution.new_code", "code_generator", d))
        self.bus.subscribe("output.display", lambda d: self.record_event("output.display", "frontend", {"text": d}))

        # 困惑事件（预测-验证环）
        self.bus.subscribe("internal.confusion", lambda d: self.record_confusion_event(d))

        # 认知引擎状态
        self.bus.subscribe("cognitive.state.updated", lambda d: self._on_cognitive_state(d))

    def _on_cognitive_state(self, data: Dict):
        """记录认知引擎状态更新"""
        self.record_internal_state("curiosity_energy", data.get("curiosity_energy", 0.5), "cognitive_engine")
        self.record_internal_state("pain_level", data.get("pain_level", 0.0), "cognitive_engine")
        self.record_internal_state("confusion_level", data.get("confusion_level", 0.0), "cognitive_engine")

    def record_event(self, event_type: str, source: str, data: Any):
        """记录通用事件（线程安全）"""
        try:
            data_str = json.dumps(data, ensure_ascii=False) if isinstance(data, (dict, list)) else str(data)
            with self.db_lock:
                self.conn.execute(
                    "INSERT INTO events (timestamp, event_type, source, data) VALUES (?, ?, ?, ?)",
                    (time.time(), event_type, source, data_str)
                )
                self.conn.commit()
        except Exception as e:
            print(f"记录事件失败: {e}")

    def record_internal_state(self, state_name: str, value: float, description: str = None):
        """记录内部状态变量（线程安全）"""
        try:
            with self.db_lock:
                self.conn.execute(
                    "INSERT INTO internal_states (timestamp, state_name, value, description) VALUES (?, ?, ?, ?)",
                    (time.time(), state_name, value, description)
                )
                self.conn.commit()
        except Exception as e:
            print(f"记录内部状态失败: {e}")

    def record_confusion_event(self, data: Dict):
        """记录困惑事件（预测误差）（线程安全）"""
        try:
            with self.db_lock:
                self.conn.execute(
                    "INSERT INTO events (timestamp, event_type, source, data) VALUES (?, ?, ?, ?)",
                    (time.time(), "internal.confusion", "chat_handler", json.dumps(data, ensure_ascii=False))
                )
                self.conn.execute(
                    "INSERT INTO internal_states (timestamp, state_name, value, description) VALUES (?, ?, ?, ?)",
                    (time.time(), "confusion_error", data.get("error", 0), f"predicted={data.get('predicted')} actual={data.get('actual')}")
                )
                self.conn.commit()
        except Exception as e:
            print(f"记录困惑事件失败: {e}")

    def get_recent_events(self, event_type: Optional[str] = None, limit: int = 20) -> List[Dict]:
        """获取最近事件"""
        query = "SELECT timestamp, event_type, source, data FROM events"
        params = []
        if event_type:
            query += " WHERE event_type = ?"
            params.append(event_type)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        cursor = self.conn.execute(query, params)
        columns = ["timestamp", "event_type", "source", "data"]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_state_summary(self) -> Dict:
        """获取当前内部状态摘要"""
        summary = {}
        cursor = self.conn.execute("""
            SELECT state_name, value FROM internal_states
            WHERE state_name IN ('performance_score', 'auto_learn_active')
            ORDER BY timestamp DESC LIMIT 10
        """)
        for name, val in cursor.fetchall():
            if name not in summary:
                summary[name] = val

        cursor = self.conn.execute("SELECT COUNT(*) FROM events WHERE timestamp > ?", (time.time() - 3600,))
        summary["events_last_hour"] = cursor.fetchone()[0]

        cursor = self.conn.execute("SELECT COUNT(*) FROM events WHERE event_type = 'decision.thinking'")
        summary["total_thoughts"] = cursor.fetchone()[0]

        return summary

    def get_confusion_summary(self, window_hours: int = 24) -> Dict:
        """获取近期困惑统计"""
        since = time.time() - window_hours * 3600
        cursor = self.conn.execute(
            "SELECT COUNT(*), AVG(value) FROM internal_states WHERE state_name='confusion_error' AND timestamp > ?",
            (since,)
        )
        count, avg_error = cursor.fetchone()
        return {
            "confusion_events_24h": count or 0,
            "avg_prediction_error": avg_error or 0
        }

    def get_energy_history(self, hours: int = 24) -> List[Dict]:
        """获取近期的能量变化历史"""
        since = time.time() - hours * 3600
        cursor = self.conn.execute(
            "SELECT timestamp, value, description FROM internal_states WHERE state_name='curiosity_energy' AND timestamp > ? ORDER BY timestamp",
            (since,)
        )
        return [{"timestamp": row[0], "value": row[1], "description": row[2]} for row in cursor.fetchall()]

    def get_current_energy(self) -> float:
        """获取最新的能量值"""
        cursor = self.conn.execute(
            "SELECT value FROM internal_states WHERE state_name='curiosity_energy' ORDER BY timestamp DESC LIMIT 1"
        )
        row = cursor.fetchone()
        return row[0] if row else 0.5

    def get_pain_level(self) -> float:
        """获取当前痛苦指数"""
        cursor = self.conn.execute(
            "SELECT value FROM internal_states WHERE state_name='pain_level' ORDER BY timestamp DESC LIMIT 1"
        )
        row = cursor.fetchone()
        return row[0] if row else 0.0

    def query_self_reflection(self) -> str:
        """
        生成一段简短的“自我反思”文本，基于近期内部状态。
        用于前端 /inner_world 命令展示。
        """
        summary = self.get_state_summary()
        score = summary.get("performance_score", 0.7)
        is_learning = summary.get("auto_learn_active", 0)
        events = summary.get("events_last_hour", 0)
        energy = self.get_current_energy()
        pain = self.get_pain_level()

        if score < 0.6:
            mood = "有些困惑，近期表现不佳"
        elif score > 0.85:
            mood = "思维清晰，状态良好"
        else:
            mood = "运行平稳"

        if is_learning:
            mood += "，正在主动学习中"
        if energy < 0.3:
            mood += "，好奇心能量较低，倾向于保守学习"
        elif energy > 0.7:
            mood += "，好奇心充沛，愿意探索未知"
        if pain > 0.5:
            mood += "，感到一定程度的痛苦，可能触发自我修正"

        return f"当前自我感知：{mood}。过去一小时记录 {events} 个事件，累计思考 {summary.get('total_thoughts', 0)} 次。能量水平 {energy:.0%}，痛苦指数 {pain:.0%}。"

    def close(self):
        """关闭数据库连接"""
        with self.db_lock:
            self.conn.close()