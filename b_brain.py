# b_brain.py
import subprocess
import os
import json
import time
import shutil
import sys
import importlib
import importlib.util
import glob
from datetime import datetime
from message_bus import MessageBus
from version_manager import VersionManager

class BBrain:
    def __init__(self, bus: MessageBus, vm: VersionManager, code_gen):
        self.bus = bus
        self.vm = vm
        self.code_gen = code_gen
        bus.subscribe("code.new_version", self.on_new_version)
        bus.subscribe("code.verify", self.on_verify)

    def _backup_file(self, filepath):
        if not os.path.exists(filepath):
            return None
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{filepath}.backup_{timestamp}"
        shutil.copy2(filepath, backup_name)
        return backup_name

    def on_new_version(self, data):
        temp_file = data["temp_file"]
        target_file = data["target_file"]
        version_name = data["version_name"]
        test_temp_file = data.get("test_temp_file")

        backup_file = self._backup_file(target_file)
        if not backup_file:
            print("⚠️ 无法备份原文件，取消升级")
            return

        # 备份测试文件（如果存在）
        test_target_file = f"test_{target_file}"
        test_backup = None
        if test_temp_file and os.path.exists(test_target_file):
            test_backup = self._backup_file(test_target_file)

        try:
            os.replace(temp_file, target_file)
            if test_temp_file and os.path.exists(test_temp_file):
                os.replace(test_temp_file, test_target_file)
        except Exception as e:
            print(f"替换文件失败: {e}")
            if backup_file and os.path.exists(backup_file):
                shutil.copy2(backup_file, target_file)
            if test_backup and os.path.exists(test_backup):
                shutil.copy2(test_backup, test_target_file)
            return

        # 运行针对性测试
        success = self.run_self_test(target_file, test_target_file if test_temp_file else None)

        if success:
            self.vm.save_version(version_name, f"自动升级 {target_file}")
            self.bus.publish("output.display", f"✅ 升级成功，版本 {version_name} 已保存")
            self.code_gen.receive_upgrade_result(True)
            self._clean_old_backups(target_file)
        else:
            # 回滚
            if backup_file and os.path.exists(backup_file):
                shutil.copy2(backup_file, target_file)
            if test_backup and os.path.exists(test_backup):
                shutil.copy2(test_backup, test_target_file)
            self.bus.publish("output.display", f"❌ 升级失败，已回滚到 {backup_file}")
            self.code_gen.receive_upgrade_result(False)

    def run_self_test(self, changed_module, test_module=None):
        """
        运行测试：优先运行模块对应的单元测试文件，否则运行基础导入测试。
        对核心模块增加功能探针验证。
        """
        module_name = changed_module.replace(".py", "")
        # 1. 尝试运行单元测试
        if test_module and os.path.exists(test_module):
            print(f"运行单元测试: {test_module}")
            try:
                result = subprocess.run(
                    ["python", test_module],
                    capture_output=True, text=True, timeout=30
                )
                if result.returncode == 0:
                    print("✅ 单元测试通过")
                    return True
                else:
                    print(f"❌ 单元测试失败:\n{result.stdout}\n{result.stderr}")
                    return False
            except Exception as e:
                print(f"运行单元测试异常: {e}")
                return False

        # 2. 基础导入测试
        print("未找到单元测试，执行基础导入测试")
        try:
            result = subprocess.run(
                ["python", "-c", f"import {module_name}; print('OK')"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0 or "OK" not in result.stdout:
                print(f"❌ 基础导入测试失败: {result.stderr}")
                return False
        except Exception as e:
            print(f"❌ 基础导入测试异常: {e}")
            return False

        # 3. 功能探针：对核心模块进行关键方法检查
        if not self._probe_core_functions(changed_module):
            return False

        return True

    def _probe_core_functions(self, changed_module: str) -> bool:
        """
        功能探针：验证核心模块的关键类和方法是否存在。
        """
        # 定义各模块需要检查的关键类和方法
        PROBE_RULES = {
            "chat_handler.py": {
                "class": "ChatHandlerModule",
                "methods": [
                    "handle_user_input",
                    "multi_agent_answer_async",
                    "_simple_answer_with_context",
                    "_multi_agent_with_context",
                    "_select_parliament_members",
                ]
            },
            "palace_memory_v3.py": {
                "class": "PalaceMemoryV3",
                "methods": [
                    "retrieve_by_semantic",
                    "add_to_chaos",
                    "record_crack",
                    "decay_utility",
                ]
            },
            "auto_learner.py": {
                "class": "AutoLearner",
                "methods": [
                    "_learn_loop",
                    "_learn_from_bookshelf",
                    "_deep_study_bookshelf_loop",
                    "_review_and_reclassify_memories",
                ]
            },
            "supervisor.py": {
                "class": "Supervisor",
                "methods": [
                    "decompose_goal",
                    "assign_roles",
                    "execute_subtasks_concurrently",
                ]
            },
        }

        if changed_module not in PROBE_RULES:
            return True  # 非核心模块，跳过探针

        rule = PROBE_RULES[changed_module]
        class_name = rule["class"]
        required_methods = rule["methods"]

        print(f"🔍 执行功能探针：检查 {changed_module} 的核心完整性...")
        try:
            # 动态加载模块
            module_name = changed_module.replace(".py", "")
            spec = importlib.util.spec_from_file_location(f"{module_name}_temp", changed_module)
            if spec is None:
                print(f"❌ 功能探针失败：无法加载模块 {changed_module}")
                return False
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # 检查核心类是否存在
            if not hasattr(module, class_name):
                print(f"❌ 功能探针失败：缺少核心类 {class_name}")
                return False

            cls = getattr(module, class_name)
            # 检查关键方法是否存在
            missing_methods = []
            for method in required_methods:
                if not hasattr(cls, method):
                    missing_methods.append(method)

            if missing_methods:
                print(f"❌ 功能探针失败：缺少关键方法 {', '.join(missing_methods)}")
                return False

            print(f"✅ 功能探针通过：{class_name} 的核心方法完整")
            return True

        except Exception as e:
            print(f"❌ 功能探针失败：{e}")
            return False

    def _clean_old_backups(self, target_file):
        backup_pattern = f"{target_file}.backup_*"
        backups = glob.glob(backup_pattern)
        backups.sort(key=os.path.getmtime, reverse=True)
        for old in backups[3:]:
            os.remove(old)

    def on_verify(self, data):
        pass