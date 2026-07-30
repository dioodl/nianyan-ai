# info_store.py
import json
import os

class InfoStore:
    """
    专用键值存储，用于长期记忆个人信息（如姓名、生日、偏好等）。
    支持持久化到 JSON 文件，提供简单的 get/set/delete 接口。
    """
    def __init__(self, filepath: str = "personal_info.json"):
        """
        初始化存储。
        :param filepath: 存储文件的路径（默认项目根目录下的 personal_info.json）
        """
        self.filepath = filepath
        self.data = {}
        self.load()

    def load(self):
        """从文件加载数据（如果存在）"""
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    self.data = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"加载个人信息文件失败: {e}，将使用空存储")
                self.data = {}

    def save(self):
        """将数据保存到文件"""
        try:
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except IOError as e:
            print(f"保存个人信息失败: {e}")

    def set(self, key: str, value):
        """
        设置键值对。
        :param key: 键名（如 "user_name"）
        :param value: 值（可以是字符串、数字、列表等可序列化对象）
        """
        self.data[key] = value
        self.save()

    def get(self, key: str, default=None):
        """
        获取键对应的值。
        :param key: 键名
        :param default: 键不存在时返回的默认值
        :return: 存储的值或默认值
        """
        return self.data.get(key, default)

    def delete(self, key: str):
        """
        删除键值对。
        :param key: 键名
        """
        if key in self.data:
            del self.data[key]
            self.save()

    def contains(self, key: str) -> bool:
        """检查键是否存在"""
        return key in self.data

    def clear(self):
        """清空所有存储"""
        self.data = {}
        self.save()

    def get_all(self) -> dict:
        """返回所有存储的数据（副本）"""
        return self.data.copy()