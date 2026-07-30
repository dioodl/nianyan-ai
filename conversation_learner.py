# conversation_learner.py
import os
import json
import shutil
from typing import List, Dict

class ConversationLearner:
    def __init__(self, archive_dir="conversation_archives", target_question_file="auto_learner_state.json"):
        self.archive_dir = archive_dir
        self.question_file = target_question_file

    def _is_valid_question(self, text: str) -> bool:
        text = text.strip()
        if len(text) < 10:
            return False
        cmd_prefixes = ("python", "pip", "cd", "dir", "ls", "echo", "git", "ollama", "curl", "exit", "quit")
        if text.lower().startswith(cmd_prefixes):
            return False
        if "=" in text or "()" in text or "import" in text:
            if "?" not in text and "？" not in text:
                return False
        if len(text.split()) < 3:
            return False
        return True

    def extract_qa_pairs(self, min_length=10, max_turns=100) -> List[Dict]:
        qa_pairs = []
        for fname in os.listdir(self.archive_dir):
            if not fname.endswith('.json'):
                continue
            with open(os.path.join(self.archive_dir, fname), 'r', encoding='utf-8') as f:
                data = json.load(f)
            for turn in data.get("turns", []):
                q = turn.get("user_message", "").strip()
                a = turn.get("assistant_response", "").strip()
                if len(q) > min_length and self._is_valid_question(q) and len(a) > min_length:
                    qa_pairs.append({"question": q, "answer": a})
                if len(qa_pairs) >= max_turns:
                    break
        return qa_pairs

    def update_auto_learner_questions(self, qa_pairs: List[Dict], max_questions=50):
        if not os.path.exists(self.question_file):
            print("自习状态文件不存在，跳过导入")
            return
        # 先备份原文件
        backup_file = self.question_file + ".bak"
        try:
            shutil.copy2(self.question_file, backup_file)
        except:
            pass
        try:
            with open(self.question_file, 'r', encoding='utf-8') as f:
                state = json.load(f)
        except Exception as e:
            print(f"读取自习状态文件失败: {e}，跳过导入")
            return
        existing = set(state.get("questions", []))
        new_questions = []
        for pair in qa_pairs:
            q = pair["question"]
            if q not in existing and self._is_valid_question(q):
                new_questions.append(q)
            if len(new_questions) >= max_questions:
                break
        if new_questions:
            state["questions"] = list(existing) + new_questions
            # 写入前再次备份
            with open(self.question_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)
            print(f"已添加 {len(new_questions)} 个新问题到自习库")
        else:
            print("没有新问题可添加")