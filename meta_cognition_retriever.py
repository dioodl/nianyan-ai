# meta_cognition_retriever.py
"""
元认知检索器
============
加载猜想图书馆注脚，使用向量检索为系统提供元规则指导。
"""

import os
import json
import numpy as np
from typing import List, Dict, Optional
from sentence_transformers import SentenceTransformer


class MetaCognitionRetriever:
    """
    元认知知识库检索器。
    将注脚文本向量化，提供语义检索接口。
    """

    def __init__(self, footnotes_file: str = "footnotes.jsonl", model_name: str = 'all-MiniLM-L6-v2'):
        self.footnotes_file = footnotes_file
        self.encoder = SentenceTransformer(model_name)
        self.footnotes: List[Dict] = []
        self.vectors: List[np.ndarray] = []
        self._load_and_encode()

    def _load_and_encode(self):
        """加载注脚文件并编码为向量"""
        if not os.path.exists(self.footnotes_file):
            print(f"⚠️ 注脚文件 {self.footnotes_file} 不存在，元认知库为空。")
            return

        with open(self.footnotes_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                    self.footnotes.append(item)
                except json.JSONDecodeError:
                    continue

        if self.footnotes:
            contents = [item['content'] for item in self.footnotes]
            embeddings = self.encoder.encode(contents)
            self.vectors = [embeddings[i] for i in range(len(contents))]
            print(f"📚 元认知库加载完成，共 {len(self.footnotes)} 条注脚。")
        else:
            print("⚠️ 元认知库为空。")

    def retrieve(self, query: str, top_k: int = 3) -> List[Dict]:
        """
        根据查询文本检索最相关的注脚。
        返回包含 content、tags、相似度的字典列表。
        """
        if not self.vectors:
            return []

        query_vec = self.encoder.encode([query])[0]
        scores = []
        for i, vec in enumerate(self.vectors):
            sim = np.dot(query_vec, vec) / (np.linalg.norm(query_vec) * np.linalg.norm(vec) + 1e-8)
            scores.append((sim, i))

        scores.sort(key=lambda x: x[0], reverse=True)
        results = []
        for sim, idx in scores[:top_k]:
            footnote = self.footnotes[idx].copy()
            footnote['similarity'] = float(sim)
            results.append(footnote)

        return results

    def retrieve_as_context(self, query: str, top_k: int = 3) -> str:
        """
        将检索到的注脚格式化为一段上下文字符串，便于注入提示词。
        """
        results = self.retrieve(query, top_k)
        if not results:
            return ""

        lines = ["【元认知参考·猜想图书馆注脚】"]
        for r in results:
            lines.append(f"· {r['content']}")
        return "\n".join(lines)


# 全局单例（供各模块复用）
_retriever_instance: Optional[MetaCognitionRetriever] = None


def get_meta_retriever() -> MetaCognitionRetriever:
    """获取元认知检索器单例"""
    global _retriever_instance
    if _retriever_instance is None:
        _retriever_instance = MetaCognitionRetriever()
    return _retriever_instance