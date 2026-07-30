# conversation_archiver.py
import os
import json
import time
from datetime import datetime
from typing import List, Dict, Optional

class ConversationArchiver:
    def __init__(self, archive_dir="conversation_archives"):
        self.archive_dir = archive_dir
        os.makedirs(archive_dir, exist_ok=True)

    def _get_session_filename(self, session_id: str) -> str:
        return os.path.join(self.archive_dir, f"session_{session_id}.json")

    def start_new_session(self, session_id: str, metadata: Optional[Dict] = None):
        filename = self._get_session_filename(session_id)
        if not os.path.exists(filename):
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump({
                    "session_id": session_id,
                    "start_time": time.time(),
                    "metadata": metadata or {},
                    "turns": []
                }, f, indent=2)

    def add_turn(self, session_id: str, user_message: str, assistant_response: str,
                 emotion: str = None, strategy: str = None, metadata: Optional[Dict] = None):
        filename = self._get_session_filename(session_id)
        if not os.path.exists(filename):
            self.start_new_session(session_id)
        with open(filename, 'r', encoding='utf-8') as f:
            data = json.load(f)
        data["turns"].append({
            "timestamp": time.time(),
            "user_message": user_message,
            "assistant_response": assistant_response,
            "emotion": emotion,
            "strategy": strategy,
            "metadata": metadata or {}
        })
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

    def get_full_conversation(self, session_id: str) -> Optional[List[Dict]]:
        filename = self._get_session_filename(session_id)
        if not os.path.exists(filename):
            return None
        with open(filename, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get("turns", [])

    def search_conversations(self, keyword: str, start_time: float = None, end_time: float = None) -> List[Dict]:
        results = []
        for fname in os.listdir(self.archive_dir):
            if not fname.endswith('.json'):
                continue
            with open(os.path.join(self.archive_dir, fname), 'r', encoding='utf-8') as f:
                data = json.load(f)
            session_id = data["session_id"]
            for turn in data["turns"]:
                if start_time and turn["timestamp"] < start_time:
                    continue
                if end_time and turn["timestamp"] > end_time:
                    continue
                if keyword.lower() in turn["user_message"].lower() or keyword.lower() in turn["assistant_response"].lower():
                    results.append({
                        "session_id": session_id,
                        "timestamp": turn["timestamp"],
                        "user_message": turn["user_message"],
                        "assistant_response": turn["assistant_response"]
                    })
        return results

    def list_sessions(self) -> List[Dict]:
        sessions = []
        for fname in os.listdir(self.archive_dir):
            if not fname.endswith('.json'):
                continue
            with open(os.path.join(self.archive_dir, fname), 'r', encoding='utf-8') as f:
                data = json.load(f)
            turns = data.get("turns", [])
            if turns:
                sessions.append({
                    "session_id": data["session_id"],
                    "start_time": turns[0]["timestamp"],
                    "end_time": turns[-1]["timestamp"],
                    "turn_count": len(turns)
                })
        return sessions