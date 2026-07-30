# tools/tools_catalog.py
"""
工具能力目录 - 念言的自我能力认知
====================================
维护一个动态更新的能力清单，供自主探索时参考。
支持自动注册新工具（如通过 execute_script 创建的脚本）。
"""

import json
import os
from datetime import datetime

CAPABILITIES_FILE = os.path.join(os.path.dirname(__file__), "capabilities.json")

class ToolsCatalog:
    def __init__(self):
        self.catalog = self._load()

    def _load(self) -> dict:
        if os.path.exists(CAPABILITIES_FILE):
            try:
                with open(CAPABILITIES_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {"tools": [], "last_updated": datetime.now().isoformat()}

    def _save(self):
        self.catalog["last_updated"] = datetime.now().isoformat()
        try:
            with open(CAPABILITIES_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.catalog, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ [工具目录] 保存失败: {e}")

    def register_tool(self, name: str, description: str, source: str = "user"):
        """注册一个新工具到目录"""
        for tool in self.catalog["tools"]:
            if tool["name"] == name:
                tool["description"] = description
                tool["source"] = source
                tool["registered_at"] = datetime.now().isoformat()
                self._save()
                print(f"🔧 [工具目录] 更新工具: {name}")
                return
        self.catalog["tools"].append({
            "name": name,
            "description": description,
            "source": source,
            "registered_at": datetime.now().isoformat()
        })
        self._save()
        print(f"🔧 [工具目录] 新工具注册: {name}")

    def remove_tool(self, name: str):
        """移除一个工具"""
        self.catalog["tools"] = [t for t in self.catalog["tools"] if t["name"] != name]
        self._save()
        print(f"🔧 [工具目录] 移除工具: {name}")

    def get_tools_description(self) -> str:
        """返回适合注入到 prompt 中的工具清单描述"""
        if not self.catalog["tools"]:
            return "目前没有可用的工具。"
        lines = ["当前可用的工具列表："]
        for tool in self.catalog["tools"]:
            lines.append(f"- {tool['name']}: {tool['description']}")
        return "\n".join(lines)

    def get_all_tools(self) -> list:
        return self.catalog["tools"]


# 全局实例（由 main.py 初始化）
_catalog_instance = None

def get_catalog() -> ToolsCatalog:
    global _catalog_instance
    if _catalog_instance is None:
        _catalog_instance = ToolsCatalog()
    return _catalog_instance

def init_catalog():
    global _catalog_instance
    _catalog_instance = ToolsCatalog()
    return _catalog_instance