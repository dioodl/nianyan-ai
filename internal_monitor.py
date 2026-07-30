# internal_monitor.py (v14.11 - 集成七情议会情绪评估，优化进化方向校正)
import json
import time
import threading
import numpy as np
from collections import defaultdict
from scipy.stats import binomtest
from openai import OpenAI
import ollama
from config import EVOLUTION_LOG, TEST_SET, PERFORMANCE_THRESHOLD, DEFAULT_BASE_URL, DEFAULT_MODEL, DEFAULT_API_KEY
from message_bus import MessageBus

# 尝试导入可选模块
try:
    from meta_strategy import MetaStrategy
    META_STRATEGY_AVAILABLE = True
except ImportError:
    META_STRATEGY_AVAILABLE = False
    print("⚠️ meta_strategy 模块未找到，进化算子选择将使用默认策略")

try:
    from strategy_optimizer import StrategyOptimizer
    STRATEGY_OPT_AVAILABLE = True
except ImportError:
    STRATEGY_OPT_AVAILABLE = False

try:
    from dimension_tracker import track
    TRACK_AVAILABLE = True
except ImportError:
    TRACK_AVAILABLE = False
    def track(dimension=0):
        return lambda func: func

try:
    from config import IDLE_THRESHOLD_SECONDS
except ImportError:
    IDLE_THRESHOLD_SECONDS = 600


class InternalMonitor:
    def __init__(self, bus: MessageBus, code_generator=None, memory=None, cognitive_engine=None):
        self.bus = bus
        self.code_gen = code_generator
        self.memory = memory
        self.cognitive_engine = cognitive_engine
        self.score_history = []
        self.evolution_log = []
        self.current_experiment = None
        self.running = False
        self.thread = None
        self.client = OpenAI(base_url=DEFAULT_BASE_URL, api_key=DEFAULT_API_KEY)
        self.model = DEFAULT_MODEL
        self.load_log()

        self.action_stats = defaultdict(list)
        self.action_thresholds = {
            "open_browser": 2.0,
            "send_email": 3.0,
            "execute_command": 1.0,
            "generate_text": 5.0,
            "save_file": 0.5,
        }

        bus.subscribe("monitor.evaluate", self.on_evaluate_request)
        bus.subscribe("atomic.action.completed", self.on_action_completed)

        self.last_activity = time.time()
        self.idle_threshold = IDLE_THRESHOLD_SECONDS
        self.idle_monitor_thread = threading.Thread(target=self._idle_monitor_loop, daemon=True)
        self.idle_monitor_thread.start()
        bus.subscribe("user.input.raw", self._on_activity)
        bus.subscribe("user_input.main", self._on_activity)

        self.confusion_window = []
        self.pain_history = []
        bus.subscribe("internal.confusion", self.on_confusion)
        bus.subscribe("cognitive.state.updated", self.on_cognitive_state)

        self.feedback_window = []
        self.response_times = []
        self.memory_hits = []
        self.red_zone_counters = {"negative_feedback": 0, "slow_response": 0, "low_memory_hit": 0}
        self.RED_ZONE_THRESHOLD = 3
        bus.subscribe("chat.response.sent", self.on_response_sent)

        self.last_daily_check = time.time()
        self.last_dream_time = time.time()
        self.last_narrative_time = time.time()
        self.last_weekly_cleanup = time.time()
        self.last_maintenance = time.time()

        self.chaos_alert_counter = 0
        self.CHAOS_ALERT_THRESHOLD = 3
        self.ZERO_STATE_RATIO_THRESHOLD = 0.6
        self.chaos_triggered = False

        print("🩺 内部监控模块初始化完成（集成七情议会情绪评估）")

    # ---------- 辅助方法 ----------
    def _on_activity(self, _):
        self.last_activity = time.time()

    def _idle_monitor_loop(self):
        while not self.running:
            time.sleep(1)
        while self.running:
            time.sleep(60)
            idle_time = time.time() - self.last_activity
            if idle_time > self.idle_threshold:
                self.bus.publish("system.idle", {"idle_seconds": idle_time})

    def load_log(self):
        try:
            with open(EVOLUTION_LOG, 'r') as f:
                self.evolution_log = json.load(f)
        except FileNotFoundError:
            self.evolution_log = []

    def save_log(self):
        with open(EVOLUTION_LOG, 'w') as f:
            json.dump(self.evolution_log, f, indent=2)

    def on_response_sent(self, data):
        duration = data.get("duration", 0)
        memory_hit = data.get("memory_hit", False)
        self.response_times.append(duration)
        self.memory_hits.append(1 if memory_hit else 0)
        if len(self.response_times) > 20:
            self.response_times.pop(0)
        if len(self.memory_hits) > 20:
            self.memory_hits.pop(0)

    def record_feedback_for_redzone(self, is_positive: bool):
        self.feedback_window.append(1 if is_positive else 0)
        if len(self.feedback_window) > 20:
            self.feedback_window.pop(0)

    @track(dimension=5) if TRACK_AVAILABLE else (lambda func: func)
    def evaluate(self, collect_failures=False):
        correct = 0
        failures = []
        total = len(TEST_SET)
        for item in TEST_SET:
            q = item['q']
            expected = item['a'].strip().lower()
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": q}],
                    temperature=0.3,
                )
                answer = response.choices[0].message.content.strip().lower()
                if expected in answer:
                    correct += 1
                elif collect_failures:
                    failures.append({"question": q, "expected": expected, "actual": answer})
            except Exception as e:
                print(f"评估出错: {e}")
                if collect_failures:
                    failures.append({"question": q, "expected": expected, "actual": f"评估异常: {e}"})
        score = correct / total if total > 0 else 0
        self.score_history.append(score)
        if len(self.score_history) > 20:
            self.score_history.pop(0)
        if collect_failures:
            return score, failures
        return score

    def get_failure_mode(self):
        if len(self.score_history) < 5:
            return "unknown"
        recent = self.score_history[-5:]
        avg = np.mean(recent)
        if avg < 0.5:
            return "severe"
        elif avg < 0.7:
            return "mild"
        else:
            return "stable"

    def on_action_completed(self, data):
        action = data.get("action")
        duration = data.get("duration", 0)
        success = data.get("success", False)
        self.action_stats[action].append({"duration": duration, "success": success, "timestamp": time.time()})
        if len(self.action_stats[action]) > 100:
            self.action_stats[action] = self.action_stats[action][-100:]
        threshold = self.action_thresholds.get(action, 1.0)
        if duration > threshold and success:
            print(f"⚠️ 性能警告：{action} 耗时 {duration:.2f}s > {threshold}s")

    @track(dimension=5) if TRACK_AVAILABLE else (lambda func: func)
    def analyze_performance(self):
        issues = []
        for action, records in self.action_stats.items():
            if len(records) < 3:
                continue
            durations = [r["duration"] for r in records if r["success"]]
            if not durations:
                continue
            avg_duration = np.mean(durations)
            threshold = self.action_thresholds.get(action, 1.0)
            if avg_duration > threshold * 1.2:
                issues.append({
                    "action": action,
                    "avg_duration": avg_duration,
                    "threshold": threshold,
                    "sample_count": len(durations)
                })
        return issues

    def _check_red_zones(self):
        red_zones = []
        if len(self.feedback_window) >= 5:
            negative_rate = 1 - sum(self.feedback_window) / len(self.feedback_window)
            if negative_rate > 0.3:
                red_zones.append("negative_feedback")
        if len(self.response_times) >= 5:
            avg_time = sum(self.response_times) / len(self.response_times)
            if avg_time > 5.0:
                red_zones.append("slow_response")
        if len(self.memory_hits) >= 5:
            hit_rate = sum(self.memory_hits) / len(self.memory_hits)
            if hit_rate < 0.2:
                red_zones.append("low_memory_hit")
        return red_zones

    def _update_red_zone_counters(self, red_zones):
        for zone in ["negative_feedback", "slow_response", "low_memory_hit"]:
            if zone in red_zones:
                self.red_zone_counters[zone] += 1
            else:
                self.red_zone_counters[zone] = 0
        for zone, count in self.red_zone_counters.items():
            if count >= self.RED_ZONE_THRESHOLD:
                print(f"🚨 红区连续触发：{zone}，启动针对性进化！")
                self.trigger_evolution(reason=f"red_zone_{zone}")
                self.red_zone_counters[zone] = 0

    def on_confusion(self, data):
        error = data.get("error", 0)
        self.confusion_window.append(error)
        if len(self.confusion_window) > 10:
            self.confusion_window.pop(0)
        if len(self.confusion_window) >= 5 and sum(self.confusion_window) / len(self.confusion_window) > 0.6:
            print("🚨 连续高困惑检测，触发紧急修正！")
            self.trigger_evolution(reason="acute_confusion")
            self.confusion_window.clear()
        red_zones = self._check_red_zones()
        self._update_red_zone_counters(red_zones)
        self._check_chaos_state()

    def on_cognitive_state(self, data):
        pain = data.get("pain_level", 0.0)
        self.pain_history.append(pain)
        if len(self.pain_history) > 10:
            self.pain_history.pop(0)
        if len(self.pain_history) >= 5 and sum(self.pain_history[-5:]) / 5 > 0.6:
            print("🚨 连续高痛苦状态检测，触发紧急深度修正！")
            self.trigger_evolution(reason="acute_pain")
            self.pain_history.clear()
        self._check_chaos_state()

    def _check_chaos_state(self):
        if not hasattr(self, 'bus') or not self.bus:
            return
        try:
            accumulator = None
            if hasattr(self, 'cognitive_engine') and self.cognitive_engine:
                if hasattr(self.cognitive_engine, 'emotion_manager'):
                    accumulator = self.cognitive_engine.emotion_manager.accumulator
                elif hasattr(self.cognitive_engine, 'accumulator'):
                    accumulator = self.cognitive_engine.accumulator
            if accumulator is None:
                if hasattr(self.bus, 'emotion_manager'):
                    accumulator = self.bus.emotion_manager.accumulator
                elif hasattr(self.bus, 'accumulator'):
                    accumulator = self.bus.accumulator

            if accumulator and hasattr(accumulator, 'is_in_chaos_state'):
                is_chaos = accumulator.is_in_chaos_state(self.ZERO_STATE_RATIO_THRESHOLD)
                zero_ratio = accumulator.get_zero_state_ratio()
                if is_chaos:
                    self.chaos_alert_counter += 1
                    print(f"⚠️ 混沌状态检测：0态占比 {zero_ratio:.2%} > 阈值，警报计数 {self.chaos_alert_counter}/{self.CHAOS_ALERT_THRESHOLD}")
                    if self.chaos_alert_counter >= self.CHAOS_ALERT_THRESHOLD and not self.chaos_triggered:
                        self._enter_chaos_conservative_mode()
                else:
                    self.chaos_alert_counter = max(0, self.chaos_alert_counter - 0.5)
                    if self.chaos_triggered:
                        if zero_ratio < self.ZERO_STATE_RATIO_THRESHOLD * 0.7:
                            self._exit_chaos_conservative_mode()
        except Exception as e:
            print(f"混沌状态检查失败: {e}")

    def _enter_chaos_conservative_mode(self):
        self.chaos_triggered = True
        print("🛡️ 进入混沌保守模式：暂停自动进化、锁定高风险操作")
        if self.current_experiment and self.current_experiment.get("active", False):
            self.current_experiment["active"] = False
        if STRATEGY_OPT_AVAILABLE:
            try:
                strategy_opt = StrategyOptimizer()
                strategy_opt.temperature = max(0.5, strategy_opt.temperature * 0.7)
            except:
                pass
        self.bus.publish("system.chaos_mode", {"active": True, "reason": "high_zero_state_ratio"})

    def _exit_chaos_conservative_mode(self):
        self.chaos_triggered = False
        self.chaos_alert_counter = 0
        print("✅ 退出混沌保守模式，恢复正常运行")
        self.bus.publish("system.chaos_mode", {"active": False})

    def is_in_chaos_mode(self) -> bool:
        return self.chaos_triggered

    # ========== v14.11 新增：七情议会情绪评估 ==========
    def _emotional_evolution_check(self, reason: str) -> bool:
        """
        调用七情议会评估当前是否适合进行进化。
        如果多数成员表达负面情绪（反对、担忧），则返回 False，暂缓进化。
        """
        internal_parliament = getattr(self.bus, 'internal_parliament', None)
        if not internal_parliament or not hasattr(internal_parliament, '_collect_parliament_opinions'):
            print("⚠️ 七情议会不可用，跳过情绪评估，默认允许进化")
            return True

        import asyncio
        try:
            opener = f"系统因「{reason}」正在考虑触发自我进化。请从你的性格出发，用一句话表达你是否支持这次进化，以及原因（不超过25字）。"
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            opinions = loop.run_until_complete(
                internal_parliament._collect_parliament_opinions(opener, "进化评估")
            )
            loop.close()

            if not opinions or len(opinions) < 3:
                print("⚠️ 有效发言不足，默认允许进化")
                return True

            negative_signals = ["反对", "危险", "担心", "不稳定", "不可", "不行", "拒绝", "暂缓"]
            veto_count = 0
            for op in opinions:
                if any(kw in op for kw in negative_signals):
                    veto_count += 1

            if veto_count >= 3:
                print(f"🚫 [七情评估] 进化暂缓！反对票 {veto_count}/7")
                print(f"   反对意见: {[op for op in opinions if any(kw in op for kw in negative_signals)]}")
                return False
            else:
                print(f"✅ [七情评估] 进化通过，反对票 {veto_count}/7")
                return True
        except Exception as e:
            print(f"⚠️ 七情评估异常: {e}，默认允许进化")
            return True

    @track(dimension=5) if TRACK_AVAILABLE else (lambda func: func)
    def trigger_evolution(self, reason="score"):
        if self.chaos_triggered:
            print(f"⏸️ 混沌保守模式下抑制进化触发 (原因: {reason})")
            return

        # 七情议会情绪评估
        if not self._emotional_evolution_check(reason):
            print(f"🚫 [InternalMonitor] 七情议会认为当前不适合进化，取消")
            return

        print(f"🔧 触发自动变异，原因：{reason}")
        failure = self.get_failure_mode()
        operator = "rewrite_prompt"  # 默认
        if META_STRATEGY_AVAILABLE:
            meta = MetaStrategy()
            operator = meta.select(failure)

        if reason.startswith("red_zone_"):
            zone = reason.replace("red_zone_", "")
            if zone == "slow_response":
                self.mutate_prompt(target_action="atomic_actions")
            elif zone == "negative_feedback":
                self.mutate_prompt(target_action="chat_handler")
            elif zone == "low_memory_hit":
                self.mutate_prompt(target_action="palace_memory")
        elif reason in ("acute_confusion", "acute_pain"):
            self.mutate_prompt(target_action="chat_handler")

        if operator == "rewrite_prompt":
            self.mutate_prompt()
        elif operator == "adjust_temperature":
            self.adjust_temperature()
        elif operator == "enable_web_search":
            self.enable_web_search()
        elif operator == "request_clarification":
            self.request_clarification()

        current_score = self.evaluate()
        self.start_experiment(operator, current_score)

    def mutate_prompt(self, target_action=None):
        if target_action:
            print(f"变异提示词：针对模块 {target_action} 请求改进")
            if self.code_gen:
                self.code_gen.attempt_upgrade(
                    specific_module=f"{target_action}.py",
                    failure_context=f"模块 {target_action} 性能指标持续红区，需要优化"
                )
        else:
            print("变异提示词：请求 A 智脑改进 chat_handler.py")
            if self.code_gen:
                self.code_gen.attempt_upgrade(specific_module="chat_handler.py")

    def adjust_temperature(self):
        if STRATEGY_OPT_AVAILABLE:
            strategy_opt = StrategyOptimizer()
            old = strategy_opt.temperature
            new = min(2.0, old * 1.2)
            strategy_opt.temperature = new
            print(f"调整温度：{old} -> {new}")

    def enable_web_search(self):
        print("已启用联网搜索")

    def request_clarification(self):
        print("将尝试在对话中增加主动澄清")

    def start_experiment(self, operator, current_score):
        self.current_experiment = {
            "operator": operator,
            "start_score": current_score,
            "sample_count": 0,
            "success_count": 0,
            "active": True
        }

    def record_feedback(self, user_score):
        if self.current_experiment and self.current_experiment["active"]:
            self.current_experiment["sample_count"] += 1
            if user_score >= 4:
                self.current_experiment["success_count"] += 1
            if self.current_experiment["sample_count"] >= 10:
                self.end_experiment()

    @track(dimension=5) if TRACK_AVAILABLE else (lambda func: func)
    def end_experiment(self):
        if not self.current_experiment:
            return
        exp = self.current_experiment
        result = binomtest(exp["success_count"], exp["sample_count"], p=0.5)
        p_value = result.pvalue
        improved = p_value < 0.05 and (exp["success_count"] / exp["sample_count"]) > 0.5
        end_score = self.evaluate()
        delta = end_score - exp["start_score"]
        if META_STRATEGY_AVAILABLE:
            meta = MetaStrategy()
            meta.update(exp["operator"], delta if improved else -abs(delta))
        self.evolution_log.append({
            "time": time.time(),
            "operator": exp["operator"],
            "start_score": exp["start_score"],
            "end_score": end_score,
            "sample_count": exp["sample_count"],
            "success_rate": exp["success_count"] / exp["sample_count"],
            "improved": improved,
            "delta": delta
        })
        self.save_log()
        if improved:
            print(f"✅ 变异成功，算子 {exp['operator']} 永久生效")
        else:
            self.rollback()
        self.current_experiment = None

    def rollback(self):
        if STRATEGY_OPT_AVAILABLE:
            strategy_opt = StrategyOptimizer()
            strategy_opt.temperature = 1.0
        print("🔄 回滚到上次稳定配置")

    def start_monitoring(self, interval_seconds=300):
        self.running = True
        print("🔍 启动自检：执行测试集评估...")
        score = self.evaluate()
        print(f"✅ 性能正常（本地）：得分 {score:.2f}")

        print("🔍 启动自检：分析原子操作性能...")
        issues = self.analyze_performance()
        if issues:
            print(f"⚠️ 发现 {len(issues)} 个原子操作性能问题")
            for issue in issues:
                print(f"  - {issue['action']}: 平均耗时 {issue['avg_duration']:.2f}s > 阈值 {issue['threshold']}s")
                self.mutate_prompt(target_action=issue['action'])
        else:
            print("✅ 原子操作性能正常")

        self.last_daily_check = time.time()
        self.last_narrative_time = time.time()
        self.last_weekly_cleanup = time.time()
        self.last_maintenance = time.time()
        self.thread = threading.Thread(target=self._monitor_loop, args=(interval_seconds,), daemon=True)
        self.thread.start()
        print(f"🩺 内部监控已启动，检查间隔: {interval_seconds} 秒")

    def _monitor_loop(self, interval):
        while self.running:
            time.sleep(interval)
            now = time.time()

            self._check_chaos_state()

            # 每日自检
            if now - self.last_daily_check > 86400:
                print("🔍 每日自检：执行测试集评估...")
                score = self.evaluate()
                if score < PERFORMANCE_THRESHOLD:
                    print(f"⚠️ 性能下降：得分 {score:.2f} < 阈值 {PERFORMANCE_THRESHOLD}，触发变异")
                    self.trigger_evolution(reason="score")
                else:
                    print(f"✅ 性能正常（本地）：得分 {score:.2f}")

                self.last_daily_check = now

                # 错误知识库扫描
                try:
                    from error_knowledge import run_error_scan
                    count = run_error_scan(self.memory, lookback_hours=24)
                    if count > 0:
                        print(f"📋 错误知识库已更新，新增 {count} 条记录")
                except Exception as e:
                    print(f"⚠️ 错误扫描失败: {e}")

                # 一致性审计
                try:
                    from consistency_auditor import run_consistency_audit
                    print("🔍 启动一致性审计（扫描小说项目）...")
                    run_consistency_audit()
                except Exception as e:
                    print(f"⚠️ 一致性审计失败: {e}")

            # 记忆库维护（每日，包括欲望衰减）
            if now - self.last_maintenance > 86400:
                print("执行每日记忆库维护...")
                if self.memory:
                    try:
                        if hasattr(self.memory, 'decay_utility'):
                            self.memory.decay_utility()
                        print("   📉 记忆效用已衰减")
                    except Exception as e:
                        print(f"   ⚠️ 记忆效用衰减失败: {e}")

                if self.cognitive_engine and hasattr(self.cognitive_engine, 'desire_vector'):
                    try:
                        self.cognitive_engine.desire_vector.decay(factor=0.995)
                        print("   📉 欲望向量已衰减")
                    except Exception as e:
                        print(f"   ⚠️ 欲望衰减失败: {e}")

                self.last_maintenance = now

            # 每周记忆归档清理
            if now - self.last_weekly_cleanup > 604800:
                if self.memory and hasattr(self.memory, 'archive_low_utility_memories'):
                    print("📦 执行每周记忆归档...")
                    try:
                        archived = self.memory.archive_low_utility_memories(utility_threshold=0.15, days_old=90)
                        print(f"📦 每周归档完成，共归档 {archived} 条记忆")
                    except Exception as e:
                        print(f"⚠️ 每周记忆归档失败: {e}")
                self.last_weekly_cleanup = now

            # 自我叙事编织器（每日凌晨3-5点）
            if hasattr(self.bus, 'self_narrator') and self.bus.self_narrator:
                if now - self.last_narrative_time > 86400:
                    current_hour = time.localtime(now).tm_hour
                    if 3 <= current_hour <= 5:
                        print("📝 触发自我叙事编织器...")
                        self.bus.self_narrator.run_daily(force=False)
                        self.last_narrative_time = now

            # 深度梦境
            if hasattr(self, 'bus') and hasattr(self.bus, 'deep_dream'):
                if now - self.last_dream_time > 86400:
                    current_hour = time.localtime(now).tm_hour
                    if 2 <= current_hour <= 4:
                        print("🌙 触发深度梦境...")
                        self.bus.deep_dream.start()
                        self.last_dream_time = now

    def on_evaluate_request(self, data):
        score = self.evaluate()
        self.bus.publish("monitor.score", {"score": score, "timestamp": time.time()})