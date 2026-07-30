# permission_manager.py
"""
动态权限管理器 - 数字生命体的“免疫系统”与“协商皮层”
==================================================
管理所有敏感操作的权限申请、审批、记忆与过期。
与消息总线集成，支持Tkinter和Web双前端审批。
"""

import json
import os
import time
import uuid
import threading
from typing import Dict, List, Optional, Callable
from enum import Enum
from message_bus import MessageBus


class RiskLevel(Enum):
    L1 = "low"      # 自动授权
    L2 = "medium"   # 用户确认，可记住
    L3 = "high"     # 强制确认，不可记住


class PermissionRequest:
    def __init__(self, action: str, target: str, risk_level: RiskLevel, 
                 reason: str, source_module: str, remember: bool = False):
        self.request_id = str(uuid.uuid4())[:8]
        self.action = action
        self.target = target
        self.risk_level = risk_level
        self.reason = reason
        self.source_module = source_module
        self.timestamp = time.time()
        self.status = "pending"
        self.granted_by = None
        self.expires_at = None
        self.remember = remember

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "action": self.action,
            "target": self.target,
            "risk_level": self.risk_level.value,
            "reason": self.reason,
            "source_module": self.source_module,
            "timestamp": self.timestamp,
            "status": self.status,
            "granted_by": self.granted_by,
            "expires_at": self.expires_at,
            "remember": self.remember
        }


class PermissionManager:
    def __init__(self, bus: MessageBus, state_file: str = "permission_state.json"):
        self.bus = bus
        self.state_file = state_file
        self.pending_requests: Dict[str, PermissionRequest] = {}
        self.granted_rules: List[dict] = []  # 记住的授权规则
        self.lock = threading.Lock()
        self._load_state()

        # 风险等级 → 基础操作映射
        self.risk_mapping = {
            "execute_command": RiskLevel.L3,
            "delete_file": RiskLevel.L3,
            "copy_file": RiskLevel.L2,
            "web_browser_search": RiskLevel.L1,
            "save_file": RiskLevel.L1,
            "create_folder": RiskLevel.L1,
        }

        # 订阅审批响应
        bus.subscribe("permission.response", self.on_user_response)

    def _load_state(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.granted_rules = data.get("granted_rules", [])
            except:
                pass

    def _save_state(self):
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump({"granted_rules": self.granted_rules}, f, indent=2)

    def get_risk_level(self, action: str, target: str) -> RiskLevel:
        """根据动作和目标推断风险等级"""
        base_level = self.risk_mapping.get(action, RiskLevel.L2)
        # 可根据 target 进一步调整（如路径敏感度）
        return base_level

    def check_cached_permission(self, action: str, target: str) -> Optional[bool]:
        """检查是否有已记住的授权规则"""
        for rule in self.granted_rules:
            if rule["action"] == action:
                # 简单前缀匹配，可扩展为正则
                if target.startswith(rule.get("target_prefix", "")):
                    if rule.get("expires_at", float('inf')) > time.time():
                        return True
        return None

    def request_permission(self, action: str, target: str, reason: str, 
                           source_module: str = "unknown") -> PermissionRequest:
        """
        发起权限申请。
        返回 PermissionRequest 对象，调用方可等待其状态变化。
        """
        # 检查缓存
        cached = self.check_cached_permission(action, target)
        if cached is True:
            req = PermissionRequest(action, target, RiskLevel.L1, reason, source_module)
            req.status = "granted"
            req.granted_by = "cache"
            return req

        risk_level = self.get_risk_level(action, target)
        req = PermissionRequest(action, target, risk_level, reason, source_module)

        # L1 自动授权
        if risk_level == RiskLevel.L1:
            req.status = "granted"
            req.granted_by = "auto"
            return req

        # L2/L3 需要用户审批
        with self.lock:
            self.pending_requests[req.request_id] = req

        # 发布审批请求到前端
        self.bus.publish("permission.request", req.to_dict())
        print(f"🔐 [权限申请] {req.request_id}: {action} {target[:50]} (等级:{risk_level.value})")

        return req

    def on_user_response(self, data: dict):
        """处理用户的审批响应"""
        request_id = data.get("request_id")
        granted = data.get("granted", False)
        remember = data.get("remember", False)
        user_id = data.get("user_id", "user")

        with self.lock:
            req = self.pending_requests.get(request_id)
            if not req:
                return

            req.status = "granted" if granted else "denied"
            req.granted_by = user_id

            if granted and remember and req.risk_level == RiskLevel.L2:
                # L2 可记住，L3 不可
                rule = {
                    "action": req.action,
                    "target_prefix": req.target[:50],  # 简化记忆
                    "granted_at": time.time(),
                    "expires_at": time.time() + 86400 * 30,  # 30天有效期
                }
                self.granted_rules.append(rule)
                self._save_state()

            # 通知等待者
            self.bus.publish("permission.resolved", req.to_dict())

    def wait_for_approval(self, request: PermissionRequest, timeout: float = 60.0) -> bool:
        """
        同步等待审批结果（供自主执行器调用）。
        返回 True 表示授权，False 表示拒绝或超时。
        """
        if request.status == "granted":
            return True
        if request.status == "denied":
            return False

        start = time.time()
        while time.time() - start < timeout:
            with self.lock:
                if request.request_id in self.pending_requests:
                    req = self.pending_requests[request.request_id]
                    if req.status == "granted":
                        return True
                    if req.status == "denied":
                        return False
            time.sleep(0.5)
        return False  # 超时视为拒绝