# task_planner_agent.py
import json
import datetime
import threading
from apscheduler.schedulers.background import BackgroundScheduler
from openai import OpenAI
from message_bus import MessageBus
from priority_arbiter import Instruction, PriorityArbiter
from config import DEFAULT_BASE_URL, DEFAULT_MODEL, DEFAULT_API_KEY

class TaskPlannerAgent:
    def __init__(self, bus: MessageBus, arbiter: PriorityArbiter):
        self.bus = bus
        self.arbiter = arbiter
        self.client = OpenAI(base_url=DEFAULT_BASE_URL, api_key=DEFAULT_API_KEY)
        self.model = DEFAULT_MODEL
        self.scheduler = BackgroundScheduler()
        self.scheduler.add_job(self.daily_plan, 'cron', hour=6, minute=0)
        self.scheduler.start()
        self.bus.subscribe("task.feedback", self.on_feedback)

    def daily_plan(self):
        try:
            with open("task_log.json", "r") as f:
                logs = json.load(f)
        except:
            logs = []
        cutoff = (datetime.datetime.now() - datetime.timedelta(days=7)).isoformat()
        recent = [log for log in logs if log["timestamp"] > cutoff]

        prompt = f"""你是一个任务规划师。根据以下最近7天的任务执行记录，分析用户的行为模式，生成今天（{datetime.date.today()}）的3-5条建议任务。每条任务应具体、可执行，并给出优先级（高/中/低）。
任务记录：{json.dumps(recent, ensure_ascii=False)}
输出格式为 JSON 列表，每个元素包含 "description" 和 "priority"。"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
            )
            suggestions = json.loads(response.choices[0].message.content)
        except:
            suggestions = []

        for task in suggestions:
            inst = Instruction(
                id=f"plan_{datetime.datetime.now().timestamp()}",
                source="planner",
                user_role="normal",
                type="task",
                content=task["description"],
                timestamp=datetime.datetime.now().timestamp()
            )
            self.arbiter.submit(inst)
            self.bus.publish("output.display", f"📅 任务建议：{task['description']} (优先级: {task.get('priority', '中')})")

    def on_feedback(self, data):
        with open("task_log.json", "a") as f:
            f.write(json.dumps({
                "timestamp": datetime.datetime.now().isoformat(),
                "description": data["description"],
                "status": data["status"],
                "feedback": data.get("feedback", "")
            }) + "\n")