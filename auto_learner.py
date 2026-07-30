# auto_learner.py (适配工具调度器 + 移除 max_tokens 硬编码)
import threading
import time
import json
import os
import random
import asyncio
from openai import OpenAI
from message_bus import MessageBus
from config import (
    DEFAULT_BASE_URL, DEFAULT_MODEL, DEFAULT_API_KEY, STUDY_GOALS, DEFAULT_STUDY_GOAL,
    BOOKSHELF_DIR, BOOKSHELF_READ_HISTORY, BOOKSHELF_PROGRESS_FILE
)
from palace_memory_v3 import PalaceMemoryV3
from conversation_learner import ConversationLearner
from apscheduler.schedulers.background import BackgroundScheduler

# 使用工具调度器调用搜索
from tools.tool_dispatcher import dispatch, is_tool_available


class AutoLearner:
    def __init__(self, bus: MessageBus, memory=None):
        self.bus = bus
        if memory is None:
            self.memory = PalaceMemoryV3(robot_id="auto_learner")
        else:
            self.memory = memory
        self.running = False
        self.thread = None
        self.client = OpenAI(base_url=DEFAULT_BASE_URL, api_key=DEFAULT_API_KEY)
        self.model = DEFAULT_MODEL

        self.ollama_options = {
            "num_ctx": 32768,
            "num_predict": 3275
        }

        self.active_goal_name = DEFAULT_STUDY_GOAL
        self.active_goal = STUDY_GOALS.get(self.active_goal_name, STUDY_GOALS["通用"])
        self.questions = self.active_goal["questions"].copy()
        self.learned_index = 0
        self.generation_count = 0
        self.state_file = "auto_learner_state.json"
        self.load_state()

        self._import_from_conversation_archives()
        self.bookshelf_counter = 0

        self.pause_deep_study = False
        self.paused_by_user = False
        self.deep_study_condition = threading.Condition()
        self.deep_study_thread = None

        bus.subscribe("auto_learn.start", self.start)
        bus.subscribe("auto_learn.stop", self.stop)
        bus.subscribe("auto_learn.set_goal", self.set_goal)
        bus.subscribe("auto_learn.deep_study", self.manual_deep_study)
        bus.subscribe("user.input.raw", self.on_user_activity)
        bus.subscribe("user_input.main", self.on_user_activity)
        bus.subscribe("system.idle", self.on_system_idle)
        bus.subscribe("control.user_activity", self.on_user_activity_pause)

        self.scheduler = BackgroundScheduler()
        self.scheduler.add_job(self._review_and_reclassify_memories, 'cron', hour=2, minute=0)
        self.scheduler.start()
        self.last_review_time = self._load_last_review_time()
        self._check_initial_review()

    def on_user_activity_pause(self, data):
        self.paused_by_user = True
        self.pause_deep_study = True
        print("⏸️ 收到用户活动信号，暂停所有自习任务")

    def _import_from_conversation_archives(self, max_questions=20):
        try:
            learner = ConversationLearner()
            qa_pairs = learner.extract_qa_pairs(min_length=10, max_turns=100)
            new_questions = []
            existing = set(self.questions)
            for pair in qa_pairs:
                q = pair["question"]
                if q not in existing and len(q) < 200:
                    new_questions.append(q)
                if len(new_questions) >= max_questions:
                    break
            if new_questions:
                self.questions.extend(new_questions)
                self.save_state()
                print(f"📚 从对话归档中导入了 {len(new_questions)} 个新问题到自习库")
        except Exception as e:
            print(f"从对话归档导入失败: {e}")

    def load_state(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.active_goal_name = data.get("active_goal", DEFAULT_STUDY_GOAL)
                    self.questions = data.get("questions", self.active_goal["questions"].copy())
                    self.learned_index = data.get("learned_index", 0)
                    self.generation_count = data.get("generation_count", 0)
                    self.active_goal = STUDY_GOALS.get(self.active_goal_name, STUDY_GOALS["通用"])
            except:
                pass

    def save_state(self):
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump({
                "active_goal": self.active_goal_name,
                "questions": self.questions,
                "learned_index": self.learned_index,
                "generation_count": self.generation_count
            }, f, indent=2, ensure_ascii=False)

    def set_goal(self, goal_name: str):
        if goal_name in STUDY_GOALS:
            self.active_goal_name = goal_name
            self.active_goal = STUDY_GOALS[goal_name]
            self.questions = self.active_goal["questions"].copy()
            self.learned_index = 0
            self.generation_count = 0
            self.save_state()
            self.bus.publish("output.display", f"📚 自习目标已切换为：{goal_name}")
        else:
            self.bus.publish("output.display", f"⚠️ 未知的自习目标：{goal_name}")

    def start(self, data=None):
        if self.running:
            return
        self.running = True
        self.pause_deep_study = False
        self.paused_by_user = False
        self.thread = threading.Thread(target=self._learn_loop, daemon=True)
        self.thread.start()
        self.bus.publish("output.display", f"📚 自习开始，当前目标：{self.active_goal_name}")

    def stop(self, data=None):
        self.running = False
        self.pause_deep_study = False
        self.paused_by_user = False
        with self.deep_study_condition:
            self.deep_study_condition.notify_all()
        if self.thread:
            self.thread.join(timeout=2)
        if self.deep_study_thread and self.deep_study_thread.is_alive():
            self.deep_study_thread.join(timeout=2)
        self.save_state()
        self.bus.publish("output.display", "📚 自习结束。")

    def _generate_new_questions(self):
        self.bus.publish("output.display", f"🔍 正在为自习目标「{self.active_goal_name}」生成新的学习问题...")
        keywords = self.active_goal.get("keywords", [])
        if not keywords:
            prompt = f"请根据以下领域生成5个新的学习问题：{self.active_goal_name}。每行一个问题。"
        else:
            prompt = f"""你是一个学习规划师。当前学习领域：{self.active_goal_name}，关键词：{', '.join(keywords)}。
请生成5个新的、更深层次或相关领域的延伸问题，每个问题应具体、有研究价值。
输出格式：每行一个问题，不要有序号或其他文字。"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                extra_body={"options": self.ollama_options}
            )
            new_questions = response.choices[0].message.content.strip().split("\n")
            new_questions = [q.strip() for q in new_questions if q.strip() and not q.strip().startswith('-')]
            filtered = []
            for q in new_questions:
                if any(kw.lower() in q.lower() for kw in keywords):
                    filtered.append(q)
                else:
                    print(f"丢弃不相关问题: {q}")
            if filtered:
                self.questions.extend(filtered)
                self.generation_count += 1
                self.save_state()
                self.bus.publish("output.display", f"✨ 已生成 {len(filtered)} 个新问题，当前问题库共 {len(self.questions)} 个。")
            else:
                self.bus.publish("output.display", "⚠️ 生成的问题均与目标无关，稍后重试。")
        except Exception as e:
            self.bus.publish("output.display", f"⚠️ 生成新问题失败：{e}")

    def _load_json_or_jsonl(self, filepath: str):
        with open(filepath, 'r', encoding='utf-8') as f:
            first_char = f.read(1)
            f.seek(0)
            if first_char == '[':
                return json.load(f)
            else:
                lines = []
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            lines.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
                if lines:
                    return lines
                else:
                    f.seek(0)
                    return json.load(f)

    def _learn_from_bookshelf(self):
        if not self.running or self.paused_by_user:
            return False
        if not os.path.exists(BOOKSHELF_DIR):
            os.makedirs(BOOKSHELF_DIR, exist_ok=True)
            return False

        history_file = BOOKSHELF_READ_HISTORY
        read = set()
        if os.path.exists(history_file):
            try:
                with open(history_file, 'r', encoding='utf-8') as f:
                    read = set(json.load(f))
            except:
                pass

        progress_file = BOOKSHELF_PROGRESS_FILE
        progress = {}
        if os.path.exists(progress_file):
            try:
                with open(progress_file, 'r', encoding='utf-8') as f:
                    progress = json.load(f)
            except:
                pass

        all_files = [f for f in os.listdir(BOOKSHELF_DIR) if f.endswith(('.txt', '.json', '.jsonl')) and f not in read]
        if not all_files:
            return False

        candidates = [f for f in all_files if f in progress and progress[f].get('chunk_index', 0) < progress[f].get('total_chunks', 1)]
        chosen = random.choice(candidates) if candidates else random.choice(all_files)
        filepath = os.path.join(BOOKSHELF_DIR, chosen)

        if chosen.endswith('.txt'):
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            chunk_size = 2000
            total_chunks = (len(content) + chunk_size - 1) // chunk_size
            current = progress.get(chosen, {}).get('chunk_index', 0)
            for idx in range(current, total_chunks):
                if not self.running or self.paused_by_user:
                    return False
                chunk = content[idx*chunk_size : (idx+1)*chunk_size]
                prompt = f"请从以下文本中提取出3-5个关键知识点，每个知识点用一句完整的话表述。如果文本很短，至少提取1个。\n文本：\n{chunk}\n输出格式：每行一个知识点。"
                try:
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.3,
                        extra_body={"options": self.ollama_options}
                    )
                    lines = response.choices[0].message.content.strip().split('\n')
                    for line in lines:
                        if line.strip():
                            self.memory.add_to_chaos(
                                question=f"书架《{chosen}》知识点（第{idx+1}段）",
                                answer=line.strip(),
                                utility=0.8,
                                source="bookshelf",
                                mem_type="fact"
                            )
                    progress[chosen] = {"chunk_index": idx+1, "total_chunks": total_chunks, "last_time": time.time()}
                    with open(progress_file, 'w', encoding='utf-8') as pf:
                        json.dump(progress, pf, indent=2)
                except Exception as e:
                    print(f"处理文本块失败: {e}")
                    break
            if progress.get(chosen, {}).get('chunk_index', 0) >= total_chunks:
                read.add(chosen)
                with open(history_file, 'w', encoding='utf-8') as hf:
                    json.dump(list(read), hf, indent=2)
                if chosen in progress:
                    del progress[chosen]
                    with open(progress_file, 'w', encoding='utf-8') as pf:
                        json.dump(progress, pf, indent=2)
                self.bus.publish("output.display", f"📚 从书架完整学习了《{chosen}》")
            else:
                self.bus.publish("output.display", f"📚 从书架学习了《{chosen}》第 {progress[chosen]['chunk_index']}/{total_chunks} 段")

        elif chosen.endswith(('.json', '.jsonl')):
            try:
                data = self._load_json_or_jsonl(filepath)
            except Exception as e:
                print(f"读取JSON/JSONL文件失败: {filepath}, 错误: {e}")
                return False

            if isinstance(data, dict):
                items = [data]
            elif isinstance(data, list):
                items = data
            else:
                items = []

            total_items = len(items)
            current = progress.get(chosen, {}).get('item_index', 0)
            for idx in range(current, total_items):
                if not self.running or self.paused_by_user:
                    return False
                obj = items[idx]
                if not isinstance(obj, dict):
                    continue
                user = obj.get("user_input") or obj.get("user_message") or obj.get("question") or ""
                assistant = obj.get("assistant_output") or obj.get("assistant_response") or obj.get("answer") or ""
                if user and assistant:
                    knowledge = f"问题：{user}\n答案：{assistant}"
                else:
                    knowledge = json.dumps(obj, ensure_ascii=False)
                self.memory.add_to_chaos(
                    question=f"书架《{chosen}》条目{idx+1}",
                    answer=knowledge,
                    utility=0.8,
                    source="bookshelf",
                    mem_type="fact"
                )
                progress[chosen] = {"item_index": idx+1, "total_items": total_items, "last_time": time.time()}
                with open(progress_file, 'w', encoding='utf-8') as pf:
                    json.dump(progress, pf, indent=2)
            if progress.get(chosen, {}).get('item_index', 0) >= total_items:
                read.add(chosen)
                with open(history_file, 'w', encoding='utf-8') as hf:
                    json.dump(list(read), hf, indent=2)
                if chosen in progress:
                    del progress[chosen]
                    with open(progress_file, 'w', encoding='utf-8') as pf:
                        json.dump(progress, pf, indent=2)
                self.bus.publish("output.display", f"📚 从书架完整学习了《{chosen}》")
            else:
                self.bus.publish("output.display", f"📚 从书架学习了《{chosen}》第 {progress[chosen]['item_index']}/{total_items} 条")
        return True

    def _deep_study_single_text(self, text: str, title: str):
        self.bus.publish("multi_agent.log", f"📖 深度自习开始：{title}")
        student_prompt = f"""请仔细阅读以下文本，然后提出3个最核心的问题，这些问题应能引导对文本的深入理解。每个问题用一句话表述。
文本：
{text}
输出格式：每行一个问题。"""
        student_resp = self.client.chat.completions.create(
            model="qwen3.5:4b",
            messages=[{"role": "user", "content": student_prompt}],
            temperature=0.7,
            extra_body={"options": self.ollama_options}
        )
        questions = student_resp.choices[0].message.content.strip().split('\n')
        questions = [q.strip() for q in questions if q.strip() and '?' in q]
        if not questions:
            questions = ["文本的核心观点是什么？", "有哪些关键证据或例子？", "是否存在争议或局限性？"]
        self.bus.publish("multi_agent.log", f"🎓 学生提出 {len(questions)} 个核心问题")

        teacher_answers = []
        for q in questions:
            teacher_prompt = f"""请作为专家，针对以下问题给出深入、全面的回答。可以引用文本内容，也可以补充背景知识。
问题：{q}
文本：{text}
回答："""
            teacher_resp = self.client.chat.completions.create(
                model="deepseek-r1:7b",
                messages=[{"role": "user", "content": teacher_prompt}],
                temperature=0.5,
                extra_body={"options": self.ollama_options}
            )
            teacher_answers.append(teacher_resp.choices[0].message.content.strip())
        self.bus.publish("multi_agent.log", f"👨‍🏫 教师完成了 {len(teacher_answers)} 个问题的解答")

        judge_prompt = f"""综合以下讨论，生成一份结构化总结，格式如下：
### 核心观点
（列出2-3个最核心的观点）

### 证据与例子
（列出文本中的关键证据或例子）

### 深度思考
（指出文本的潜在假设、争议点或未解决的问题）

### 延伸建议
（建议进一步阅读或思考的方向）

讨论内容：
学生提出的问题：{chr(10).join(questions)}
教师的回答：{chr(10).join(teacher_answers)}
输出总结："""
        judge_resp = self.client.chat.completions.create(
            model="qwen2.5:7b",
            messages=[{"role": "user", "content": judge_prompt}],
            temperature=0.4,
            extra_body={"options": self.ollama_options}
        )
        summary = judge_resp.choices[0].message.content.strip()
        self.bus.publish("multi_agent.log", f"⚖️ 裁判生成总结（{len(summary)} 字符）")
        return summary

    def manual_deep_study(self, data=None):
        if not self.running:
            print("🔄 深度自习触发，自动启动普通自习...")
            self.start()
            time.sleep(1)
        if self.deep_study_thread is None or not self.deep_study_thread.is_alive():
            self.deep_study_thread = threading.Thread(target=self._deep_study_bookshelf_loop, daemon=True)
            self.deep_study_thread.start()

    def _deep_study_bookshelf_loop(self):
        if not os.path.exists(BOOKSHELF_DIR):
            os.makedirs(BOOKSHELF_DIR, exist_ok=True)
            self.bus.publish("output.display", "📂 书架目录不存在，已自动创建")
            return

        history_file = BOOKSHELF_READ_HISTORY
        read = set()
        if os.path.exists(history_file):
            try:
                with open(history_file, 'r', encoding='utf-8') as f:
                    read = set(json.load(f))
            except:
                pass

        progress_file = BOOKSHELF_PROGRESS_FILE
        progress = {}
        if os.path.exists(progress_file):
            try:
                with open(progress_file, 'r', encoding='utf-8') as f:
                    progress = json.load(f)
            except:
                pass

        all_files = [f for f in os.listdir(BOOKSHELF_DIR) if f.endswith(('.txt', '.json', '.jsonl')) and f not in read]
        if not all_files:
            self.bus.publish("output.display", "📭 没有未读的书架文件，请添加 .txt 或 .json 或 .jsonl 文件到 bookshelf/ 目录")
            return

        candidates = [f for f in all_files if f in progress and progress[f].get('chunk_index', 0) < progress[f].get('total_chunks', 1)]
        chosen = random.choice(candidates) if candidates else random.choice(all_files)
        filepath = os.path.join(BOOKSHELF_DIR, chosen)
        self.bus.publish("output.display", f"🧠 深度自习开始：{chosen}")

        if chosen.endswith('.txt'):
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            chunk_size = 3000
            total_chunks = (len(content) + chunk_size - 1) // chunk_size
            current = progress.get(chosen, {}).get('chunk_index', 0)
            all_summaries = []
            for idx in range(current, total_chunks):
                while self.paused_by_user or self.pause_deep_study:
                    if not self.running:
                        return
                    time.sleep(0.5)
                self.bus.publish("output.display", f"📖 正在分析第 {idx+1}/{total_chunks} 段...")
                chunk = content[idx*chunk_size : (idx+1)*chunk_size]
                summary = self._deep_study_single_text(chunk, f"{chosen} (第{idx+1}段)")
                all_summaries.append(summary)
                progress[chosen] = {"chunk_index": idx+1, "total_chunks": total_chunks, "last_time": time.time()}
                with open(progress_file, 'w', encoding='utf-8') as pf:
                    json.dump(progress, pf, indent=2)
            final_summary = "\n\n".join(all_summaries)

        elif chosen.endswith(('.json', '.jsonl')):
            try:
                data = self._load_json_or_jsonl(filepath)
            except Exception as e:
                print(f"深度自习读取JSON/JSONL失败: {e}")
                return

            if isinstance(data, dict):
                items = [data]
            elif isinstance(data, list):
                items = data
            else:
                items = []

            total = len(items)
            current = progress.get(chosen, {}).get('item_index', 0)
            all_summaries = []
            for idx in range(current, total):
                while self.paused_by_user or self.pause_deep_study:
                    if not self.running:
                        return
                    time.sleep(0.5)
                self.bus.publish("output.display", f"📖 正在分析第 {idx+1}/{total} 个知识点...")
                obj = items[idx]
                if not isinstance(obj, dict):
                    continue
                user = obj.get("user_input") or obj.get("user_message") or obj.get("question") or ""
                assistant = obj.get("assistant_output") or obj.get("assistant_response") or obj.get("answer") or ""
                if user and assistant:
                    text = f"问题：{user}\n答案：{assistant}"
                else:
                    text = json.dumps(obj, ensure_ascii=False)
                title = user[:50] if user else f"{chosen} 条目{idx+1}"
                summary = self._deep_study_single_text(text, title)
                all_summaries.append(summary)
                progress[chosen] = {"item_index": idx+1, "total_items": total, "last_time": time.time()}
                with open(progress_file, 'w', encoding='utf-8') as pf:
                    json.dump(progress, pf, indent=2)
            final_summary = "\n\n".join(all_summaries)
        else:
            self.bus.publish("output.display", f"⚠️ 不支持的文件类型：{chosen}")
            return

        if not self.running:
            return

        self.memory.add_to_chaos(
            question=f"深度自习：{chosen}",
            answer=final_summary,
            utility=0.9,
            source="deep_study",
            mem_type="deep_study"
        )
        read.add(chosen)
        with open(history_file, 'w', encoding='utf-8') as hf:
            json.dump(list(read), hf, indent=2)
        if chosen in progress:
            del progress[chosen]
            with open(progress_file, 'w', encoding='utf-8') as pf:
                json.dump(progress, pf, indent=2)

        lines = final_summary.split('\n')
        new_questions = []
        for line in lines:
            line = line.strip()
            if line.startswith('###') or len(line) < 15:
                continue
            if '？' in line or '?' in line:
                new_questions.append(line)
            elif len(line) > 20 and ('核心' in line or '观点' in line or '建议' in line):
                new_questions.append(f"请解释：{line}")
        existing = set(self.questions)
        added = 0
        for q in new_questions[:5]:
            if q not in existing and len(q) < 200:
                self.questions.append(q)
                existing.add(q)
                added += 1
        if added:
            self.save_state()
            self.bus.publish("output.display", f"✨ 从深度自习中提取了 {added} 个新问题到自习库")

        self.bus.publish("output.display", f"✅ 深度自习完成！《{chosen}》已存入记忆库。")
        self.bus.publish("output.display", f"📝 深度自习总结预览：\n{final_summary[:500]}...")

    def on_user_activity(self, _):
        if not self.pause_deep_study:
            print("👤 用户活动，深度自习暂停")
            self.pause_deep_study = True

    def on_system_idle(self, data):
        self.paused_by_user = False
        if self.pause_deep_study:
            print("🤖 系统空闲，恢复深度自习")
            self.pause_deep_study = False
            with self.deep_study_condition:
                self.deep_study_condition.notify()

    def _learn_loop(self):
        print("📌 自习循环已启动")
        while self.running:
            while self.paused_by_user and self.running:
                time.sleep(0.5)
            if not self.running:
                break

            self.bookshelf_counter += 1
            if self.bookshelf_counter % 3 == 0:
                shelf_learned = self._learn_from_bookshelf()
                if shelf_learned:
                    print("📚 书架学习完成一轮")

            if self.learned_index >= len(self.questions):
                print(f"📌 问题库已空 (index={self.learned_index}, total={len(self.questions)})，尝试生成新问题...")
                self.learned_index = 0
                self._generate_new_questions()
                if len(self.questions) == 0:
                    print("⚠️ 问题库仍为空，暂停 60 秒")
                    for _ in range(120):
                        if self.paused_by_user or not self.running:
                            break
                        time.sleep(0.5)
                    continue

            q = self.questions[self.learned_index]
            keywords = self.active_goal.get("keywords", [])
            if keywords and not any(kw.lower() in q.lower() for kw in keywords):
                print(f"跳过不相关问题: {q}")
                self.learned_index += 1
                self.save_state()
                continue

            print(f"📖 正在学习: {q[:50]}...")
            answer = self._search_and_summarize_sync(q)
            if answer:
                self.memory.add_to_chaos(
                    question=q,
                    answer=answer,
                    utility=0.8,
                    source="auto_learner",
                    mem_type="fact"
                )
                self.bus.publish("output.display", f"📖 自习学到了：{q[:40]}...")
                self.learned_index += 1
                self.save_state()
            else:
                self.bus.publish("output.display", f"⚠️ 自习未能学到：{q[:40]}...")
                self.learned_index += 1
                self.save_state()

            sleep_seconds = random.uniform(30, 90)
            for _ in range(int(sleep_seconds * 2)):
                if self.paused_by_user or not self.running:
                    break
                time.sleep(0.5)
        print("📌 自习循环已退出")

    def _search_and_summarize_sync(self, query):
        try:
            return asyncio.run(self._search_and_summarize_async(query))
        except Exception as e:
            print(f"搜索失败: {e}")
            return None

    async def _search_and_summarize_async(self, query):
        # 检查工具是否可用
        if not is_tool_available("web_browser_search"):
            print("⚠️ 浏览器搜索工具不可用")
            return None

        result = await dispatch("web_browser_search", {"query": query}, {})
        if not result.get("success"):
            return None
        combined = result.get("results", "")
        if not combined.strip():
            return None
        prompt = f"请根据以下搜索结果，用中文总结出一段简洁的知识点（100字以内）：\n{combined}"
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                extra_body={"options": self.ollama_options}
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"LLM 总结失败: {e}")
            return None

    def _load_last_review_time(self):
        file = "last_review_time.json"
        if os.path.exists(file):
            with open(file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get("last_review", 0)
        return 0

    def _save_last_review_time(self, timestamp):
        with open("last_review_time.json", 'w', encoding='utf-8') as f:
            json.dump({"last_review": timestamp}, f)

    def _check_initial_review(self):
        now = time.time()
        if now - self.last_review_time > 86400:
            print("⏰ 启动检测：距离上次复盘超过24小时，立即执行每日记忆复盘...")
            self._review_and_reclassify_memories()

    def _review_and_reclassify_memories(self):
        print("🧠 开始每日记忆复盘，分析新增记忆并优化分类...")
        now = time.time()
        since = self.last_review_time

        self.memory.decay_utility(factor=0.995)

        index = self.memory.index
        new_entries = [e for e in index["entries"] if e["timestamp"] > since and not e.get("is_chaos", False)]
        for entry_info in new_entries:
            entry = self.memory._load_entry(entry_info["id"])
            if entry and entry["footnote"].get("source") != "auto_reclassify":
                new_category = self._suggest_category(entry["question"], entry["answer"])
                if new_category and new_category != entry["footnote"].get("category_path", ""):
                    self.memory.update_category(entry["id"], new_category)
                    print(f"  更新记忆分类: {entry['question'][:30]}... -> {new_category}")

        self._process_chaos_entries()

        self._save_last_review_time(now)
        print("✅ 记忆复盘完成")

    def _process_chaos_entries(self):
        chaos_dir = self.memory.chaos_dir
        if not os.path.exists(chaos_dir):
            return
        files = [f for f in os.listdir(chaos_dir) if f.endswith('.json')]
        if not files:
            print("混沌海中无待处理记忆")
            return
        print(f"发现 {len(files)} 条混沌记忆，正在分析分类...")
        count_promoted = 0
        for fname in files:
            entry_id = fname.replace('.json', '')
            entry = self.memory._load_entry(entry_id)
            if not entry:
                continue
            question = entry.get("question", "")
            answer = entry.get("answer", "")
            suggested = self._suggest_category(question, answer)
            if suggested:
                if self.memory.promote_from_chaos(entry_id, suggested):
                    count_promoted += 1
                    print(f"  提升混沌记忆: {question[:30]}... -> {suggested}")
                    if hasattr(self.memory, '_suggest_relations'):
                        self.memory._suggest_relations(entry_id)
            else:
                default_cat = "未分类/混沌"
                self.memory.promote_from_chaos(entry_id, default_cat)
                count_promoted += 1
                print(f"  默认分类混沌记忆: {question[:30]}... -> {default_cat}")
        self.bus.publish("output.display", f"📦 混沌海处理完成，{count_promoted} 条记忆已归档。")

    def _suggest_category(self, question: str, answer: str) -> str:
        prompt = f"""请根据以下问答内容，给出一个最合适的分类路径（使用斜杠分隔，例如"编程/Python/装饰器"或"医学/症状"）。只输出分类路径，不要有其他解释。
问题：{question}
回答：{answer}
分类："""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                extra_body={"options": self.ollama_options}
            )
            category = response.choices[0].message.content.strip()
            if len(category) < 2 or '/' not in category:
                return None
            return category
        except Exception as e:
            print(f"分类建议失败: {e}")
            return None