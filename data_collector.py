# data_collector.py
import json
import os
import time
from typing import Optional, List, Dict
from dimension_tracker import track  # 新增导入


class DataCollector:
    """
    数据收集器：收集用户与AI的对话交互，用于后续微调或分析。
    支持存储到内存缓冲区，并导出为 JSONL 格式（每行一个 JSON 对象）。
    """
    def __init__(self, buffer_size: int = 100, save_file: str = "collected_data.jsonl"):
        """
        :param buffer_size: 内存中保留的最大交互数，超过后自动写入文件
        :param save_file: 持久化文件路径（JSONL 格式）
        """
        self.buffer: List[Dict] = []
        self.buffer_size = buffer_size
        self.save_file = save_file
        if not os.path.exists(save_file):
            with open(save_file, 'w', encoding='utf-8') as f:
                pass

    @track(dimension=0)  # 新增装饰器
    def add_interaction(self,
                        user_input: str,
                        assistant_output: str,
                        user_rating: Optional[int] = None,
                        emotion: Optional[str] = None,
                        strategy: Optional[str] = None,
                        metadata: Optional[Dict] = None) -> None:
        """
        添加一次交互记录。
        """
        record = {
            "timestamp": time.time(),
            "user_input": user_input,
            "assistant_output": assistant_output,
            "user_rating": user_rating,
            "emotion": emotion,
            "strategy": strategy,
            "metadata": metadata or {}
        }
        self.buffer.append(record)

        if len(self.buffer) >= self.buffer_size:
            self.flush()

    def flush(self) -> None:
        """将缓冲区中的所有数据追加到文件，并清空缓冲区"""
        if not self.buffer:
            return
        with open(self.save_file, 'a', encoding='utf-8') as f:
            for record in self.buffer:
                f.write(json.dumps(record, ensure_ascii=False) + '\n')
        self.buffer.clear()

    def export_for_finetune(self,
                            output_file: str = "finetune_data.jsonl",
                            min_rating: Optional[int] = None,
                            max_samples: Optional[int] = None) -> int:
        """从持久化文件中筛选高质量数据，导出为微调格式"""
        if not os.path.exists(self.save_file):
            print(f"数据文件 {self.save_file} 不存在，无法导出")
            return 0

        count = 0
        with open(self.save_file, 'r', encoding='utf-8') as infile, \
             open(output_file, 'w', encoding='utf-8') as outfile:

            for line in infile:
                if max_samples is not None and count >= max_samples:
                    break
                try:
                    record = json.loads(line.strip())
                    rating = record.get("user_rating")
                    if min_rating is not None and (rating is None or rating < min_rating):
                        continue
                    prompt = record.get("user_input", "").strip()
                    completion = record.get("assistant_output", "").strip()
                    if not prompt or not completion:
                        continue
                    outfile.write(json.dumps({
                        "prompt": prompt,
                        "completion": completion
                    }, ensure_ascii=False) + '\n')
                    count += 1
                except Exception as e:
                    print(f"跳过无效记录: {e}")
        print(f"已导出 {count} 条微调数据到 {output_file}")
        return count

    def clear_all(self) -> None:
        """清空所有收集的数据"""
        self.flush()
        if os.path.exists(self.save_file):
            os.remove(self.save_file)
        with open(self.save_file, 'w', encoding='utf-8') as f:
            pass
        print("所有数据已清空")

    def get_stats(self) -> Dict:
        """返回数据统计信息"""
        if not os.path.exists(self.save_file):
            return {"total": 0, "rated": 0}
        total = 0
        rated = 0
        with open(self.save_file, 'r', encoding='utf-8') as f:
            for line in f:
                total += 1
                try:
                    record = json.loads(line)
                    if record.get("user_rating") is not None:
                        rated += 1
                except:
                    pass
        return {"total": total, "rated": rated, "buffer_size": len(self.buffer)}