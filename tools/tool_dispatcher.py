# tools/tool_dispatcher.py
"""
工具调度器 - 统一管理外部工具插件
================================
提供工具注册、调用和降级处理，让核心意识与具体实现解耦。
"""

from typing import Dict, Any, Optional, Callable, Awaitable

# 工具注册表
_TOOLS: Dict[str, Callable[..., Awaitable[Dict[str, Any]]]] = {}


def register_tool(name: str, func: Callable[..., Awaitable[Dict[str, Any]]]):
    """注册一个工具函数"""
    _TOOLS[name] = func
    print(f"🔧 [工具调度器] 已注册工具: {name}")


def unregister_tool(name: str):
    """注销工具"""
    if name in _TOOLS:
        del _TOOLS[name]
        print(f"🔧 [工具调度器] 已注销工具: {name}")


async def dispatch(name: str, params: dict, context: dict = None) -> Dict[str, Any]:
    """
    调度工具执行。
    :param name: 工具名称
    :param params: 参数
    :param context: 上下文
    :return: 执行结果字典，至少包含 success 字段
    """
    if name not in _TOOLS:
        return {
            "success": False,
            "error": f"工具 '{name}' 未注册或不可用",
            "available_tools": list(_TOOLS.keys())
        }
    try:
        return await _TOOLS[name](params, context or {})
    except Exception as e:
        return {"success": False, "error": f"工具执行异常: {e}"}


def is_tool_available(name: str) -> bool:
    """检查工具是否可用"""
    return name in _TOOLS


def get_available_tools() -> list:
    """获取所有已注册的工具名称"""
    return list(_TOOLS.keys())