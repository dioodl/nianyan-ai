# prompts/registry.py
"""
提示词注册中心 - 统一加载与管理所有系统提示词
============================================
支持热重载、版本记录、降级回退。
"""

import os
import json
import time
from typing import Dict, Optional

# 提示词缓存
_PROMPT_CACHE: Dict[str, str] = {}
# 加载时间记录
_LOAD_TIMESTAMPS: Dict[str, float] = {}
# 默认编码
ENCODING = "utf-8"


def load_prompt(relative_path: str) -> str:
    """
    从 prompts/ 目录加载指定路径的提示词文件。
    例如: load_prompt("chat/daily_chat.txt")
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    full_path = os.path.join(base_dir, relative_path)
    
    if not os.path.exists(full_path):
        print(f"⚠️ [提示词注册中心] 文件不存在: {relative_path}")
        return ""
    
    try:
        with open(full_path, "r", encoding=ENCODING) as f:
            content = f.read().strip()
        
        _PROMPT_CACHE[relative_path] = content
        _LOAD_TIMESTAMPS[relative_path] = time.time()
        return content
    except Exception as e:
        print(f"❌ [提示词注册中心] 加载失败 {relative_path}: {e}")
        return ""


def get_prompt(relative_path: str, use_cache: bool = True) -> str:
    """获取已加载的提示词内容，优先从缓存读取"""
    if use_cache and relative_path in _PROMPT_CACHE:
        return _PROMPT_CACHE[relative_path]
    return load_prompt(relative_path)


def reload_all():
    """重新加载所有已缓存的提示词（支持热重载）"""
    paths = list(_PROMPT_CACHE.keys())
    _PROMPT_CACHE.clear()
    for path in paths:
        load_prompt(path)
    print(f"🔄 [提示词注册中心] 已重新加载 {len(paths)} 个提示词文件")


def list_loaded_prompts() -> Dict[str, str]:
    """返回所有已加载的提示词路径与内容映射"""
    return _PROMPT_CACHE.copy()


def get_load_timestamps() -> Dict[str, float]:
    """返回各提示词的加载时间"""
    return _LOAD_TIMESTAMPS.copy()