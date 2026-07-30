# frontend.py (集成动态权限审批弹窗)
import tkinter as tk
from tkinter import scrolledtext, ttk, messagebox
import time
import uuid
import json
import os
from message_bus import MessageBus
from priority_arbiter import Instruction, PriorityArbiter
from conversation_archiver import ConversationArchiver

# ========== 颜色主题配置 ==========
COLORS = {
    "bg": "#ffffff",
    "chat_bg": "#ffffff",
    "user_bg": "#ffffff",
    "user_fg": "#111111",
    "assistant_bg": "#ffffff",
    "assistant_fg": "#ff8fab",
    "study_fg": "#4ade80",
    "system_fg": "#ff9f1c",
    "entry_bg": "#ffffff",
    "entry_fg": "#111111",
    "button_bg": "#ffffff",
    "button_fg": "#222222",
    "log_fg": "#333333",
    "log_bg": "#fafafa",
}

class ChatFrontend:
    def __init__(self, bus: MessageBus, arbiter: PriorityArbiter, archiver: ConversationArchiver = None):
        self.bus = bus
        self.arbiter = arbiter
        self.archiver = archiver or ConversationArchiver()
        self.root = tk.Tk()
        self.root.title("念言")
        self.root.geometry("900x700")
        self.root.configure(bg=COLORS["bg"])

        self.style = ttk.Style()
        self.style.theme_use('clam')
        self.style.configure('TFrame', background=COLORS["bg"])
        self.style.configure('TLabel', background=COLORS["bg"], foreground=COLORS["assistant_fg"])
        self.style.configure('TButton', background=COLORS["button_bg"], foreground=COLORS["button_fg"], borderwidth=1)
        self.style.map('TButton', background=[('active', '#e8e8e8')])
        self.style.configure('TRadiobutton', background=COLORS["bg"], foreground=COLORS["assistant_fg"])
        self.style.configure('TCheckbutton', background=COLORS["bg"], foreground=COLORS["assistant_fg"])
        self.style.configure('TEntry', fieldbackground=COLORS["entry_bg"], foreground=COLORS["entry_fg"])

        self.history_offset = 0
        self.history_file = "conversation_history_main.jsonl"

        self.create_widgets()
        self.bus.subscribe("output.display", self.display_message)
        self.bus.subscribe("output.stream", self.stream_message)
        self.bus.subscribe("thinking.log", self.add_thinking_log)
        self.bus.subscribe("permission.request", self.on_permission_request)  # 新增：权限申请
        self.current_stream_id = None
        self.stream_buffer = ""

        self.load_conversation_history()

    def create_widgets(self):
        self.chat_frame = ttk.Frame(self.root)
        self.chat_frame.pack(fill='both', expand=True, padx=10, pady=10)
        self.chat_text = tk.Text(self.chat_frame, wrap=tk.WORD, state='disabled',
                                 bg=COLORS["chat_bg"], fg=COLORS["assistant_fg"],
                                 font=('Segoe UI', 10), relief='flat', bd=0)
        self.chat_text.pack(fill='both', expand=True)

        self.chat_text.tag_config('user_msg', background=COLORS["user_bg"], foreground=COLORS["user_fg"],
                                  font=('Segoe UI', 10), lmargin1=20, lmargin2=20, rmargin=20, spacing1=5, spacing3=5)
        self.chat_text.tag_config('assistant_msg', background=COLORS["assistant_bg"], foreground=COLORS["assistant_fg"],
                                  font=('Segoe UI', 10), lmargin1=20, lmargin2=20, rmargin=20, spacing1=5, spacing3=5)
        self.chat_text.tag_config('study_msg', foreground=COLORS["study_fg"], font=('Segoe UI', 10, 'bold'),
                                  lmargin1=20, lmargin2=20, rmargin=20, spacing1=5, spacing3=5)
        self.chat_text.tag_config('system_msg', foreground=COLORS["system_fg"], font=('Segoe UI', 9, 'italic'),
                                  lmargin1=20, lmargin2=20, rmargin=20)
        self.chat_text.tag_config('thinking_msg', foreground='#888888', font=('Segoe UI', 9, 'italic'),
                                  lmargin1=40, lmargin2=20, rmargin=20, spacing1=2, spacing3=2)

        bottom_frame = ttk.Frame(self.root)
        bottom_frame.pack(fill='x', padx=10, pady=(0,10))
        self.input_entry = ttk.Entry(bottom_frame, font=('Segoe UI', 10))
        self.input_entry.pack(side='left', fill='x', expand=True, padx=(0,10), ipady=5)
        self.input_entry.bind('<Return>', self.send_message)
        send_btn = ttk.Button(bottom_frame, text="发送", command=self.send_message)
        send_btn.pack(side='right')

        mode_frame = ttk.Frame(self.root)
        mode_frame.pack(pady=(0,5))
        self.mode_var = tk.StringVar(value="auto")
        ttk.Radiobutton(mode_frame, text="自动模式", variable=self.mode_var, value="auto").pack(side='left', padx=5)
        ttk.Radiobutton(mode_frame, text="聊天模式", variable=self.mode_var, value="chat").pack(side='left', padx=5)
        ttk.Radiobutton(mode_frame, text="执行模式", variable=self.mode_var, value="exec").pack(side='left', padx=5)

        self.deep_reasoning_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(mode_frame, text="深度推理模式", variable=self.deep_reasoning_var).pack(side='left', padx=10)

        study_frame = ttk.Frame(self.root)
        study_frame.pack(pady=5)
        ttk.Button(study_frame, text="📚 开始自习", command=self.start_study).pack(side='left', padx=5)
        ttk.Button(study_frame, text="⏹️ 停止自习", command=self.stop_study).pack(side='left', padx=5)
        ttk.Button(study_frame, text="🧠 深度自习", command=self.start_deep_study).pack(side='left', padx=5)
        ttk.Button(study_frame, text="📜 加载历史", command=self.load_more_history).pack(side='left', padx=5)

        self.log_frame = ttk.Frame(self.root)
        self.log_frame.pack(fill='x', padx=10, pady=5)
        self.log_btn = ttk.Button(self.log_frame, text="📋 多模型协作日志 (展开)", command=self.toggle_log)
        self.log_btn.pack(anchor='w')
        self.log_text = scrolledtext.ScrolledText(self.root, wrap=tk.WORD, height=10, state='disabled',
                                                   font=('Consolas', 9), bg=COLORS["log_bg"], fg=COLORS["log_fg"])
        self.log_visible = False
        self.bus.subscribe("multi_agent.log", self.add_log)

    def toggle_log(self):
        if self.log_visible:
            self.log_text.pack_forget()
            self.log_btn.config(text="📋 多模型协作日志 (展开)")
            self.log_visible = False
        else:
            self.log_text.pack(fill='both', padx=10, pady=5)
            self.log_btn.config(text="📋 多模型协作日志 (折叠)")
            self.log_visible = True

    def add_log(self, data):
        self.log_text.config(state='normal')
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {data}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state='disabled')

    def add_thinking_log(self, data):
        self.chat_text.config(state='normal')
        self.chat_text.insert(tk.END, f"💭 {data}\n\n", 'thinking_msg')
        self.chat_text.see(tk.END)
        self.chat_text.config(state='disabled')

    def stream_message(self, data):
        chunk = data.get("chunk", "")
        stream_id = data.get("stream_id")
        if stream_id != self.current_stream_id:
            self.current_stream_id = stream_id
            self.stream_buffer = ""
            self.insert_message("", tag='assistant_msg')
        self.stream_buffer += chunk
        self.chat_text.config(state='normal')
        self.chat_text.mark_set("insert", "end-1c")
        self.chat_text.delete("end-1c linestart", "end-1c")
        self.chat_text.insert(tk.END, f"🤖 {self.stream_buffer}\n\n", 'assistant_msg')
        self.chat_text.see(tk.END)
        self.chat_text.config(state='disabled')

    # ========== 动态权限审批 ==========
    def on_permission_request(self, data):
        """收到权限申请，弹出对话框让用户确认"""
        request_id = data.get("request_id")
        action = data.get("action")
        target = data.get("target")
        reason = data.get("reason")
        risk_level = data.get("risk_level")

        # 构建提示文本
        msg = f"念言请求执行操作：\n\n动作：{action}\n目标：{target[:100]}\n原因：{reason}\n风险等级：{risk_level}\n\n是否允许？"
        if risk_level == "medium":
            msg += "\n（可勾选“记住选择”，后续类似操作不再询问）"

        # 创建自定义对话框
        dialog = tk.Toplevel(self.root)
        dialog.title("权限申请")
        dialog.geometry("450x250")
        dialog.configure(bg=COLORS["bg"])
        dialog.transient(self.root)
        dialog.grab_set()

        # 提示标签
        label = ttk.Label(dialog, text=msg, wraplength=400, justify='left')
        label.pack(pady=15, padx=20)

        # 记住选择复选框（仅L2显示）
        remember_var = tk.BooleanVar(value=False)
        if risk_level == "medium":
            cb = ttk.Checkbutton(dialog, text="记住我的选择（30天内有效）", variable=remember_var)
            cb.pack(pady=5)

        # 按钮框架
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=15)

        def on_allow():
            self.bus.publish("permission.response", {
                "request_id": request_id,
                "granted": True,
                "remember": remember_var.get()
            })
            self.insert_message(f"🔓 已授权：{action} {target[:30]}...", tag='system_msg')
            dialog.destroy()

        def on_deny():
            self.bus.publish("permission.response", {
                "request_id": request_id,
                "granted": False,
                "remember": False
            })
            self.insert_message(f"🔒 已拒绝：{action} {target[:30]}...", tag='system_msg')
            dialog.destroy()

        ttk.Button(btn_frame, text="允许", command=on_allow).pack(side='left', padx=10)
        ttk.Button(btn_frame, text="拒绝", command=on_deny).pack(side='left', padx=10)

        # 在聊天窗口显示提示
        self.insert_message(f"🔐 权限申请：{action} {target[:40]}...\n原因：{reason}\n请在弹窗中确认。", tag='system_msg')

    def send_message(self, event=None):
        user_input = self.input_entry.get().strip()
        if not user_input:
            return
        self.input_entry.delete(0, tk.END)
        self.insert_message(f"👤 {user_input}", tag='user_msg')

        # ========== 通知所有模块用户活动，立即暂停后台任务 ==========
        self.bus.publish("control.user_activity", {"timestamp": time.time()})
        # =================================================================

        # ---------- 自主执行指令 ----------
        if user_input.startswith("执行："):
            goal = user_input[3:].strip()
            self.bus.publish("user.goal.autonomous", {"goal": goal, "user_id": "user"})
            self.insert_message(f"🎯 已发送自主执行目标：{goal}", tag='system_msg')
            return

        if user_input.startswith("/dimension"):
            self.show_dimension_stats()
            return

        if user_input.startswith("/inner_world"):
            self.show_inner_world()
            return

        if user_input.startswith("/recall"):
            parts = user_input.split(maxsplit=1)
            if len(parts) == 1:
                self.insert_message("ℹ️ 用法：/recall 关键词", tag='system_msg')
                return
            keyword = parts[1].strip()
            if self.archiver:
                results = self.archiver.search_conversations(keyword)
                self.insert_message(f"🔍 搜索到 {len(results)} 条包含「{keyword}」的记录：", tag='system_msg')
                for r in results[:5]:
                    time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r['timestamp']))
                    self.insert_message(f"[{time_str}] 念君：{r['user_message'][:80]}...", tag='system_msg')
                    self.insert_message(f"    念言：{r['assistant_response'][:80]}...", tag='system_msg')
            else:
                self.insert_message("⚠️ 归档器未初始化", tag='system_msg')
            return

        if user_input.startswith("目标："):
            self.bus.publish("user.goal", user_input[3:].strip())
            return

        mode = self.mode_var.get()
        deep = self.deep_reasoning_var.get()
        if mode == "exec":
            inst = Instruction(
                id=str(uuid.uuid4()),
                source="user",
                user_role="normal",
                type="task",
                content=user_input,
                timestamp=time.time()
            )
            self.arbiter.submit(inst)
        elif mode == "chat":
            self.bus.publish("user_input.main", {"message": user_input, "user_id": "user", "deep_reasoning": deep})
        else:
            self.bus.publish("user.input.raw", {"text": user_input, "deep_reasoning": deep})

    def show_dimension_stats(self):
        try:
            from dimension_tracker import get_tracker, format_dimension_stats_for_display
            tracker = get_tracker()
            stats = tracker.get_dimension_stats()
            display_text = format_dimension_stats_for_display(stats)
            self.insert_message(display_text, tag='system_msg')
        except ImportError:
            self.insert_message("⚠️ 维度追踪模块未加载", tag='system_msg')
        except Exception as e:
            self.insert_message(f"⚠️ 获取维度统计失败: {e}", tag='system_msg')

    def show_inner_world(self):
        """显示人工里世界状态，包括自我反思、能量条、痛苦指数"""
        try:
            from inner_world import InnerWorld
            if hasattr(self.bus, 'inner_world'):
                iw = self.bus.inner_world
                reflection = iw.query_self_reflection()
                self.insert_message(f"🧠 {reflection}", tag='system_msg')
                energy = iw.get_current_energy()
                pain = iw.get_pain_level()
                bar_len = int(energy * 10)
                energy_bar = "█" * bar_len + "·" * (10 - bar_len)
                self.insert_message(f"📊 好奇心能量：[{energy_bar}] {energy:.0%}  痛苦指数：{pain:.0%}", tag='system_msg')
            else:
                self.insert_message("⚠️ 里世界模块未初始化", tag='system_msg')
        except ImportError:
            self.insert_message("⚠️ 里世界模块未加载", tag='system_msg')
        except Exception as e:
            self.insert_message(f"⚠️ 获取里世界状态失败: {e}", tag='system_msg')

    def start_study(self):
        self.bus.publish("smart_learner.manual", {})

    def stop_study(self):
        self.bus.publish("smart_learner.stop", {})

    def start_deep_study(self):
        self.bus.publish("smart_learner.deep_study", {})

    def insert_message(self, text, tag='assistant_msg'):
        self.chat_text.config(state='normal')
        self.chat_text.insert(tk.END, text + "\n\n", tag)
        self.chat_text.see(tk.END)
        self.chat_text.config(state='disabled')

    def display_message(self, text, tag=None):
        if tag is None:
            if any(emoji in text for emoji in ['📖', '📚', '🧠', '🤖', '📭', '🔍', '✨', '✅', '⚠️', '💡', '🔧', '💭', '🔐', '🔓', '🔒']):
                tag = 'study_msg'
            else:
                tag = 'assistant_msg'
        if tag == 'user':
            tag = 'user_msg'
        elif tag == 'assistant':
            tag = 'assistant_msg'
        elif tag == 'system':
            tag = 'system_msg'
        self.insert_message(text, tag=tag)

    def load_conversation_history(self, max_records=50, offset=0):
        if not os.path.exists(self.history_file):
            print("历史文件不存在，跳过加载")
            return
        try:
            with open(self.history_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            total = len(lines)
            start = max(0, total - (offset+1)*max_records)
            end = total - offset*max_records
            records = []
            for i in range(start, end):
                if i < 0 or i >= total:
                    continue
                record = json.loads(lines[i].strip())
                records.append(record)
            for record in records:
                self.display_message(f"念君：{record['user_message']}", tag='user')
                self.display_message(f"念言：{record['assistant_response']}", tag='assistant')
            print(f"已加载 {len(records)} 条历史对话")
        except Exception as e:
            print(f"加载历史失败: {e}")

    def load_more_history(self):
        self.history_offset += 1
        self.load_conversation_history(max_records=50, offset=self.history_offset)

    def run(self):
        self.root.mainloop()