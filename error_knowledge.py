# error_knowledge.py
"""
错误知识库 - 数字生命体的错误自省中枢
====================================
从 inner_world.db 和 evolution_log.json 中提取错误事件，
分类、去重后存入记忆宫殿的专用频段 (mem_type="error_log")。
提供按优先级检索未解决错误的接口，供自习模块调用。
"""

import json
import os
import sqlite3
import time
from datetime import datetime
from typing import List, Dict, Optional


class ErrorKnowledge:
    """
    错误知识库管理器。
    """

    def __init__(self, palace_memory, inner_world_db: str = "inner_world.db",
                 evolution_log: str = "evolution_log.json"):
        self.palace = palace_memory
        self.inner_world_db = inner_world_db
        self.evolution_log = evolution_log

        # 错误类型定义
        self.ERROR_TYPES = {
            "confusion": "预测误差",
            "low_score": "性能下降",
            "evolution_failure": "进化失败",
            "atomic_slow": "原子操作缓慢",
            "atomic_failure": "原子操作失败"
        }

    def scan_and_store_errors(self, lookback_hours: int = 24) -> int:
        """
        扫描近期错误，分类后存入记忆宫殿。
        返回新增的错误条目数量。
        """
        errors = []
        cutoff = time.time() - lookback_hours * 3600

        # 1. 从 inner_world 提取困惑事件
        confusion_errors = self._extract_confusion_events(cutoff)
        errors.extend(confusion_errors)

        # 2. 从 inner_world 提取低性能得分事件
        low_score_errors = self._extract_low_score_events(cutoff)
        errors.extend(low_score_errors)

        # 3. 从 evolution_log 提取失败的进化记录
        evolution_errors = self._extract_evolution_failures(cutoff)
        errors.extend(evolution_errors)

        # 4. 从 inner_world 提取原子操作异常
        atomic_errors = self._extract_atomic_errors(cutoff)
        errors.extend(atomic_errors)

        if not errors:
            print("📋 [错误知识库] 未发现新的错误事件")
            return 0

        # 去重（基于错误指纹）
        unique_errors = self._deduplicate_errors(errors)

        # 存入记忆宫殿
        stored_count = 0
        for err in unique_errors:
            question = f"[错误报告] {err['error_type']}: {err['summary'][:50]}"
            answer = self._format_error_answer(err)
            self.palace.add_to_chaos(
                question=question,
                answer=answer,
                utility=0.7,
                source="error_knowledge",
                mem_type="error_log",
                category_path=f"系统/错误/{err['error_type']}"
            )
            stored_count += 1

        print(f"📋 [错误知识库] 已存储 {stored_count} 条错误记录")
        return stored_count

    def _extract_confusion_events(self, cutoff: float) -> List[Dict]:
        """提取预测误差事件"""
        errors = []
        if not os.path.exists(self.inner_world_db):
            return errors

        try:
            conn = sqlite3.connect(self.inner_world_db)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT timestamp, data FROM events 
                WHERE event_type = 'internal.confusion' AND timestamp > ?
                ORDER BY timestamp DESC
            """, (cutoff,))
            for row in cursor.fetchall():
                ts, data_str = row
                try:
                    data = json.loads(data_str)
                    error_val = data.get("error", 0)
                    if error_val > 0.3:  # 只记录显著误差
                        errors.append({
                            "timestamp": ts,
                            "error_type": "confusion",
                            "severity": error_val,
                            "summary": f"预测误差 {error_val:.2f}",
                            "context": data.get("last_response", "")[:200],
                            "metadata": data
                        })
                except:
                    pass
            conn.close()
        except Exception as e:
            print(f"⚠️ 提取困惑事件失败: {e}")

        return errors

    def _extract_low_score_events(self, cutoff: float) -> List[Dict]:
        """提取低性能得分事件"""
        errors = []
        if not os.path.exists(self.inner_world_db):
            return errors

        try:
            conn = sqlite3.connect(self.inner_world_db)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT timestamp, value FROM internal_states 
                WHERE state_name = 'performance_score' AND timestamp > ?
                ORDER BY timestamp DESC
            """, (cutoff,))
            for row in cursor.fetchall():
                ts, score = row
                if score < 0.7:  # 低于阈值
                    severity = 1.0 - score
                    errors.append({
                        "timestamp": ts,
                        "error_type": "low_score",
                        "severity": severity,
                        "summary": f"性能得分 {score:.2f}",
                        "context": f"测试集评估得分低于阈值 ({score:.2f} < 0.7)",
                        "metadata": {"score": score}
                    })
            conn.close()
        except Exception as e:
            print(f"⚠️ 提取低分事件失败: {e}")

        return errors

    def _extract_evolution_failures(self, cutoff: float) -> List[Dict]:
        """提取失败的进化记录"""
        errors = []
        if not os.path.exists(self.evolution_log):
            return errors

        try:
            with open(self.evolution_log, 'r', encoding='utf-8') as f:
                log = json.load(f)
            for entry in log:
                if entry.get("time", 0) < cutoff:
                    continue
                if not entry.get("improved", True):
                    delta = entry.get("delta", 0)
                    errors.append({
                        "timestamp": entry.get("time", 0),
                        "error_type": "evolution_failure",
                        "severity": abs(delta) if delta < 0 else 0.3,
                        "summary": f"变异失败: {entry.get('operator', 'unknown')}",
                        "context": f"算子 {entry.get('operator')} 导致性能下降 {delta:.2f}",
                        "metadata": entry
                    })
        except Exception as e:
            print(f"⚠️ 提取进化失败记录失败: {e}")

        return errors

    def _extract_atomic_errors(self, cutoff: float) -> List[Dict]:
        """提取原子操作异常"""
        errors = []
        if not os.path.exists(self.inner_world_db):
            return errors

        try:
            conn = sqlite3.connect(self.inner_world_db)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT timestamp, data FROM events 
                WHERE event_type = 'atomic.action.completed' AND timestamp > ?
            """, (cutoff,))
            for row in cursor.fetchall():
                ts, data_str = row
                try:
                    data = json.loads(data_str)
                    if not data.get("success", True):
                        errors.append({
                            "timestamp": ts,
                            "error_type": "atomic_failure",
                            "severity": 0.8,
                            "summary": f"原子操作失败: {data.get('action', 'unknown')}",
                            "context": data.get("error", "未知错误"),
                            "metadata": data
                        })
                    elif data.get("duration", 0) > 5.0:
                        errors.append({
                            "timestamp": ts,
                            "error_type": "atomic_slow",
                            "severity": min(1.0, data.get("duration", 0) / 10.0),
                            "summary": f"原子操作缓慢: {data.get('action', 'unknown')} ({data.get('duration', 0):.2f}s)",
                            "context": f"耗时 {data.get('duration', 0):.2f}s 超过阈值",
                            "metadata": data
                        })
                except:
                    pass
            conn.close()
        except Exception as e:
            print(f"⚠️ 提取原子操作异常失败: {e}")

        return errors

    def _deduplicate_errors(self, errors: List[Dict]) -> List[Dict]:
        """基于错误类型和上下文的指纹去重"""
        seen = set()
        unique = []
        for err in errors:
            fingerprint = f"{err['error_type']}:{err['summary']}"
            if fingerprint not in seen:
                seen.add(fingerprint)
                unique.append(err)
        return unique

    def _format_error_answer(self, err: Dict) -> str:
        """格式化错误条目为可读的答案文本"""
        ts = datetime.fromtimestamp(err['timestamp']).strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            f"【错误类型】{self.ERROR_TYPES.get(err['error_type'], err['error_type'])}",
            f"【发生时间】{ts}",
            f"【严重程度】{err['severity']:.2f}",
            f"【摘要】{err['summary']}",
            f"【上下文】{err['context']}",
        ]
        return "\n".join(lines)

    def get_unsolved_errors(self, limit: int = 5) -> List[Dict]:
        """
        检索未解决的错误（从记忆宫殿中读取）。
        返回按严重程度排序的错误列表。
        """
        try:
            results = self.palace.retrieve_by_semantic(
                query="错误 失败 异常",
                top_k=limit,
                threshold=0.3,
                mem_type="error_log",
                include_chaos=True
            )
            # 过滤出未解决的（可根据是否有 solution 字段判断，暂无则全部返回）
            errors = []
            for r in results:
                errors.append({
                    "id": r.get("id"),
                    "question": r.get("question", ""),
                    "answer": r.get("answer", ""),
                    "utility": r.get("utility", 0.5),
                    "timestamp": r.get("footnote", {}).get("timestamp", 0)
                })
            # 按效用排序（高效用 = 更严重/更需关注）
            errors.sort(key=lambda x: x.get("utility", 0.5), reverse=True)
            return errors
        except Exception as e:
            print(f"⚠️ 检索未解决错误失败: {e}")
            return []

    def mark_error_solved(self, error_id: str, solution: str = ""):
        """
        将错误标记为已解决。
        可以通过更新记忆的 category_path 或增加 solution 字段实现。
        """
        try:
            # 更新分类路径为“已解决”
            self.palace.update_category(error_id, f"系统/错误/已解决/{int(time.time())}")
            if solution:
                # 追加解决方案到答案
                entry = self.palace._load_entry(error_id)
                if entry:
                    entry["answer"] += f"\n\n【解决方案】{solution}"
                    self.palace._save_entry(entry)
            print(f"✅ 错误 {error_id} 已标记为已解决")
        except Exception as e:
            print(f"⚠️ 标记错误已解决失败: {e}")


# 全局调度函数，供 internal_monitor 或 auto_learner 调用
def run_error_scan(palace_memory, lookback_hours: int = 24) -> int:
    """便捷函数：执行一次错误扫描并存储"""
    ek = ErrorKnowledge(palace_memory)
    return ek.scan_and_store_errors(lookback_hours=lookback_hours)