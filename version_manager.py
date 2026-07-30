# version_manager.py
import os
import shutil
import json
import time
from datetime import datetime

class VersionManager:
    def __init__(self, repo_dir="version_repo"):
        self.repo_dir = repo_dir
        self.versions_dir = os.path.join(repo_dir, "versions")
        self.current_version_file = os.path.join(repo_dir, "current_version.json")
        os.makedirs(self.versions_dir, exist_ok=True)
        self._init_current_version()

    def _init_current_version(self):
        if not os.path.exists(self.current_version_file):
            self.save_version("initial", "初始版本")
            self.set_current("initial")

    def save_version(self, name, description=""):
        """保存当前所有核心模块的代码快照"""
        version_path = os.path.join(self.versions_dir, name)
        os.makedirs(version_path, exist_ok=True)
        # 需要备份的核心模块列表
        core_modules = [
            "chat_handler.py", "task_executor.py", "supervisor.py",
            "intent_classifier.py", "priority_arbiter.py", "auto_learner.py"
        ]
        for mod in core_modules:
            if os.path.exists(mod):
                shutil.copy2(mod, os.path.join(version_path, mod))  # copy2 保留元数据
        # 记录元数据
        meta = {
            "name": name,
            "description": description,
            "timestamp": datetime.now().isoformat(),
            "modules": core_modules
        }
        with open(os.path.join(version_path, "meta.json"), "w") as f:
            json.dump(meta, f, indent=2)
        # 更新 current_version 为当前（如果保存的是当前版本）
        self.set_current(name)
        return True

    def load_version(self, name):
        """加载指定版本的代码到工作目录（会覆盖当前文件）"""
        version_path = os.path.join(self.versions_dir, name)
        if not os.path.exists(version_path):
            print(f"版本 {name} 不存在")
            return False
        meta_path = os.path.join(version_path, "meta.json")
        if not os.path.exists(meta_path):
            print(f"版本 {name} 元数据缺失")
            return False
        with open(meta_path, "r") as f:
            meta = json.load(f)
        for mod in meta["modules"]:
            src = os.path.join(version_path, mod)
            if os.path.exists(src):
                try:
                    # 使用 os.replace 覆盖目标文件（支持跨平台，直接替换）
                    os.replace(src, mod)
                    print(f"已恢复 {mod}")
                except Exception as e:
                    print(f"恢复 {mod} 失败: {e}")
                    return False
        self.set_current(name)
        return True

    def set_current(self, name):
        with open(self.current_version_file, "w") as f:
            json.dump({"current": name, "timestamp": datetime.now().isoformat()}, f)

    def get_current(self):
        if os.path.exists(self.current_version_file):
            with open(self.current_version_file, "r") as f:
                return json.load(f).get("current", "initial")
        return "initial"

    def rollback(self):
        """回滚到上一个稳定版本（根据历史记录）"""
        versions = [d for d in os.listdir(self.versions_dir) if os.path.isdir(os.path.join(self.versions_dir, d))]
        if len(versions) < 2:
            print("没有足够的历史版本可回滚")
            return False
        # 按修改时间排序（最新的最后）
        versions.sort(key=lambda x: os.path.getmtime(os.path.join(self.versions_dir, x)))
        last_stable = versions[-2]  # 倒数第二个
        print(f"回滚到版本: {last_stable}")
        return self.load_version(last_stable)

    def list_versions(self):
        versions = []
        for d in os.listdir(self.versions_dir):
            meta_path = os.path.join(self.versions_dir, d, "meta.json")
            if os.path.exists(meta_path):
                with open(meta_path, "r") as f:
                    meta = json.load(f)
                versions.append(meta)
        return versions