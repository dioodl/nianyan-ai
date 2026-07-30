# model_router.py (v14.11 - 线程安全并发控制 + VIP通道)
"""
模型路由器 - 统一管理所有模型调用
================================
支持本地 Ollama 和云端 API，提供负载均衡、故障转移和动态配置。
v14.8 - 新增 images 参数支持，支持多模态视觉模型调用。
v14.11 - 新增全局并发控制 (max_concurrent_requests)，支持 VIP 通道 (priority="vip")。
          修复：使用 threading.Semaphore 实现跨事件循环安全。
"""

import json
import os
import time
import asyncio
import threading
from typing import Dict, Any, Optional, List
from openai import OpenAI


class ModelRouter:
    """
    统一模型路由器。
    加载 models_config.json，根据角色名称路由到对应的模型后端。
    """

    def __init__(self, config_path: str = "models_config.json", max_concurrent_requests: int = 1):
        self.config_path = config_path
        self.config = self._load_config()
        self.clients: Dict[str, OpenAI] = {}
        self.model_stats: Dict[str, Dict] = {}
        # 使用线程安全的信号量替代 asyncio.Semaphore，解决跨事件循环引发的冲突
        self._semaphore = threading.Semaphore(max_concurrent_requests)
        print(f"🚦 [ModelRouter] 并发请求上限设置为 {max_concurrent_requests}")

    def _load_config(self) -> dict:
        """加载模型配置文件"""
        if os.path.exists(self.config_path):
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f).get("models", {})
        return {}

    def reload_config(self):
        """重新加载配置（支持热更新）"""
        self.config = self._load_config()
        self.clients.clear()
        print("🔄 [ModelRouter] 配置已重新加载")

    def _get_client(self, backend_type: str, base_url: str, api_key: str = "ollama") -> OpenAI:
        """获取或创建 OpenAI 客户端，设置无限超时"""
        cache_key = f"{backend_type}:{base_url}:{api_key}"
        if cache_key not in self.clients:
            self.clients[cache_key] = OpenAI(
                base_url=base_url,
                api_key=api_key,
                timeout=None   # 永不超时，适应长文本生成
            )
        return self.clients[cache_key]

    def call(self, role: str, messages: List[Dict],
             temperature: Optional[float] = None,
             max_tokens: Optional[int] = None,
             fallback_roles: List[str] = None,
             images: List[str] = None) -> str:
        """
        调用指定角色的模型。
        
        :param role: 角色名称（如 "researcher", "creator", "vision"）
        :param messages: 消息列表
        :param temperature: 温度参数（覆盖配置中的默认值）
        :param max_tokens: 最大 token 数（覆盖配置中的默认值）
        :param fallback_roles: 降级角色列表，主模型失败时依次尝试
        :param images: 图像 Base64 列表，用于多模态视觉模型
        :return: 模型回复的文本内容
        """
        if role not in self.config:
            raise ValueError(f"未知的角色: {role}")

        model_config = self.config[role].copy()
        backend_type = model_config.get("type", "local")
        base_url = model_config.get("base_url", "http://localhost:11434/v1")
        api_key = model_config.get("api_key", "ollama")
        model_name = model_config.get("model")
        temp = temperature if temperature is not None else model_config.get("temperature", 0.7)
        max_tok = max_tokens or model_config.get("max_tokens", 32768)

        # 构建降级链
        roles_to_try = [role]
        if fallback_roles:
            roles_to_try.extend(fallback_roles)

        last_error = None
        for try_role in roles_to_try:
            try:
                cfg = self.config.get(try_role, model_config)
                client = self._get_client(
                    cfg.get("type", backend_type),
                    cfg.get("base_url", base_url),
                    cfg.get("api_key", api_key)
                )

                start_time = time.time()
                request_params = {
                    "model": cfg.get("model", model_name),
                    "messages": messages,
                    "temperature": cfg.get("temperature", temp),
                    "max_tokens": cfg.get("max_tokens", max_tok)
                }
                if images:
                    request_params["extra_body"] = {"images": images}

                response = client.chat.completions.create(**request_params)
                duration = time.time() - start_time

                self._update_stats(try_role, True, duration)

                content = response.choices[0].message.content
                print(f"✅ [ModelRouter] {try_role} ({cfg.get('model')}) 调用成功，耗时 {duration:.2f}s")
                return content

            except Exception as e:
                last_error = e
                self._update_stats(try_role, False, 0, str(e))
                print(f"⚠️ [ModelRouter] {try_role} 调用失败: {e}")

        raise RuntimeError(f"所有模型调用均失败，最后错误: {last_error}")

    async def call_async(self, role: str, messages: List[Dict], priority: str = "normal", **kwargs) -> str:
        """
        异步调用（带线程安全并发控制与VIP通道）
        :param priority: "vip" 时跳过信号量直接执行，用于用户对话请求
        """
        if priority == "vip":
            return await asyncio.to_thread(self.call, role, messages, **kwargs)
        else:
            # 使用线程信号量进行排队，解决 asyncio.Semaphore 跨循环冲突问题
            self._semaphore.acquire(blocking=True)
            try:
                return await asyncio.to_thread(self.call, role, messages, **kwargs)
            finally:
                self._semaphore.release()

    def _update_stats(self, role: str, success: bool, duration: float, error: str = None):
        """更新模型调用统计"""
        if role not in self.model_stats:
            self.model_stats[role] = {
                "total_calls": 0,
                "success_calls": 0,
                "failed_calls": 0,
                "total_duration": 0.0,
                "last_error": None
            }
        stats = self.model_stats[role]
        stats["total_calls"] += 1
        if success:
            stats["success_calls"] += 1
            stats["total_duration"] += duration
        else:
            stats["failed_calls"] += 1
            stats["last_error"] = error

    def get_stats(self) -> dict:
        """获取所有模型的调用统计"""
        return self.model_stats.copy()

    def get_available_roles(self) -> List[str]:
        """获取所有已配置的角色名称"""
        return list(self.config.keys())