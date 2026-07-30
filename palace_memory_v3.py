# palace_memory_v3.py (v14.11 - 关键词精确索引 + 核心记忆锚点 + 提示词文件化)
import os
import json
import time
import uuid
import shutil
import jieba
import numpy as np
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Set
from rank_bm25 import BM25Okapi
import ollama
from sentence_transformers import SentenceTransformer
from prompts.registry import get_prompt


class PalaceMemoryV3:
    def __init__(self, robot_id: str = "default", base_dir: str = "memory_palace"):
        self.robot_id = robot_id
        self.base_dir = os.path.join(base_dir, robot_id)
        self.entries_dir = os.path.join(self.base_dir, "entries")
        self.chaos_dir = os.path.join(self.base_dir, "chaos")
        self.index_file = os.path.join(self.base_dir, "index.json")
        self.encoder = SentenceTransformer('all-MiniLM-L6-v2')
        os.makedirs(self.entries_dir, exist_ok=True)
        os.makedirs(self.chaos_dir, exist_ok=True)
        self._load_index()
        self._migrate_old_entries()

        # 三进制优化配置
        self.TERNARY_ATTENTION_HIGH_THRESHOLD = 1.5
        self.TERNARY_ATTENTION_LOW_THRESHOLD = 0.3
        self.use_ternary_filter = True

        # BM25 混合检索索引
        self.bm25_index = None
        self.bm25_corpus = []
        self.bm25_doc_ids = []
        self._build_bm25_index()

        # v14.11 新增：关键词精确索引
        self.keyword_index: Dict[str, Set[str]] = {}  # 关键词 -> 记忆ID集合
        self._build_keyword_index()

    # ---------- 关键词索引管理 ----------
    def _build_keyword_index(self):
        """构建倒排索引，将记忆的关键词映射到记忆ID"""
        self.keyword_index.clear()
        for info in self._index["entries"]:
            if info.get("is_chaos", False):
                continue
            tags = info.get("tags", [])
            for tag in tags:
                tag_lower = tag.lower()
                if tag_lower not in self.keyword_index:
                    self.keyword_index[tag_lower] = set()
                self.keyword_index[tag_lower].add(info["id"])
        print(f"🔤 关键词索引已构建，共 {len(self.keyword_index)} 个唯一关键词")

    def _add_to_keyword_index(self, entry_id: str, tags: List[str]):
        for tag in tags:
            tag_lower = tag.lower()
            if tag_lower not in self.keyword_index:
                self.keyword_index[tag_lower] = set()
            self.keyword_index[tag_lower].add(entry_id)

    def _remove_from_keyword_index(self, entry_id: str):
        for tag, ids in list(self.keyword_index.items()):
            if entry_id in ids:
                ids.discard(entry_id)
                if not ids:
                    del self.keyword_index[tag]

    # ---------- 核心记忆管理 v14.11 ----------
    def mark_as_core(self, entry_id: str, core: bool = True):
        """将记忆标记为核心记忆（锚点），效用永不衰减，归档跳过，检索最高优先级"""
        entry = self._load_entry(entry_id)
        if not entry:
            return False
        entry["is_core"] = core
        self._save_entry(entry)
        for info in self._index["entries"]:
            if info["id"] == entry_id:
                info["is_core"] = core
                self._save_index()
                return True
        return False

    def is_core(self, entry_id: str) -> bool:
        for info in self._index["entries"]:
            if info["id"] == entry_id:
                return info.get("is_core", False)
        return False

    # ---------- BM25 索引管理 ----------
    def _build_bm25_index(self):
        corpus = []
        doc_ids = []
        for info in self._index["entries"]:
            if info.get("is_chaos", False):
                continue
            entry = self._load_entry(info["id"])
            if entry:
                text = entry.get("question", "") + " " + entry.get("answer", "")
                tokens = jieba.lcut(text)
                corpus.append(tokens)
                doc_ids.append(info["id"])
        self.bm25_corpus = corpus
        self.bm25_doc_ids = doc_ids
        if corpus:
            self.bm25_index = BM25Okapi(corpus)
        print(f"🔍 BM25 索引已构建，共 {len(corpus)} 篇文档")

    def _add_to_bm25(self, entry_id: str, question: str, answer: str):
        text = question + " " + answer
        tokens = jieba.lcut(text)
        self.bm25_corpus.append(tokens)
        self.bm25_doc_ids.append(entry_id)
        if self.bm25_index is None:
            if self.bm25_corpus:
                self.bm25_index = BM25Okapi(self.bm25_corpus)
        else:
            self.bm25_index = BM25Okapi(self.bm25_corpus)

    # ---------- 索引管理 ----------
    def _load_index(self):
        if os.path.exists(self.index_file):
            with open(self.index_file, 'r', encoding='utf-8') as f:
                self._index = json.load(f)
        else:
            self._index = {"entries": []}

    def _save_index(self):
        with open(self.index_file, 'w', encoding='utf-8') as f:
            json.dump(self._index, f, indent=2, ensure_ascii=False)

    @property
    def index(self):
        return self._index

    # ---------- 旧记忆字段迁移 ----------
    def _migrate_old_entries(self):
        migrated = False
        for info in self._index["entries"]:
            entry = self._load_entry(info["id"])
            if entry:
                updated = False
                if "crack_depth" not in entry:
                    entry["crack_depth"] = 0
                    updated = True
                if "crack_history" not in entry:
                    entry["crack_history"] = []
                    updated = True
                if "relations" not in entry:
                    entry["relations"] = []
                    updated = True
                if "emotion_vector" not in entry:
                    entry["emotion_vector"] = None
                    updated = True
                if "image_description" not in entry:
                    entry["image_description"] = None
                    entry["image_path"] = None
                    updated = True
                if "is_core" not in entry:
                    entry["is_core"] = False
                    updated = True
                if updated:
                    self._save_entry(entry)
                    info["crack_depth"] = entry["crack_depth"]
                if "ternary_attention" not in info:
                    info["ternary_attention"] = self._compute_ternary_attention_tag(info)
                    migrated = True
        if migrated:
            self._save_index()
            print("✅ 旧记忆字段迁移完成（裂纹、关系、情绪、三值注意力、多模态、核心标记）")

    # ---------- 注脚生成 (提示词文件化) ----------
    def _generate_footnote(self, question: str, answer: str, source: str = "dialogue") -> Dict:
        template = get_prompt("palace_memory/footnote_generation.txt") or (
            "请为以下对话生成一句话摘要（不超过30字），并提取2-4个关键词（用逗号分隔）。\n"
            "用户问题：{question}\nAI回答：{answer}\n输出格式：摘要：... 关键词：词1,词2,词3"
        )
        prompt = template.format(question=question, answer=answer)
        try:
            response = ollama.chat(
                model="qwen3.5:4b",
                messages=[{"role": "user", "content": prompt}]
            )
            text = response['message']['content']
            summary = ""
            tags = []
            if "摘要：" in text:
                parts = text.split("关键词：")
                summary = parts[0].replace("摘要：", "").strip()
                if len(parts) > 1:
                    tags = [t.strip() for t in parts[1].split(",") if t.strip()]
            else:
                summary = question[:50]
        except Exception as e:
            print(f"生成注脚失败: {e}")
            summary = question[:50]
            tags = []
        return {
            "source": source,
            "summary": summary,
            "tags": tags,
            "created_at": time.time()
        }

    # ---------- 核心添加方法 ----------
    def add(self, question: str, answer: str, utility: float = 0.5,
            source: str = "dialogue", category_path: str = None,
            mem_type: str = "fact", custom_footnote: Dict = None,
            emotion_vector: Dict = None,
            image_description: str = None, image_path: str = None,
            is_core: bool = False) -> str:
        return self._add_entry(question, answer, utility, source, category_path,
                               mem_type, custom_footnote, is_chaos=False,
                               emotion_vector=emotion_vector,
                               image_description=image_description,
                               image_path=image_path,
                               is_core=is_core)

    def add_to_chaos(self, question: str, answer: str, utility: float = 0.5,
                     source: str = "dialogue", mem_type: str = "fact",
                     custom_footnote: Dict = None, emotion_vector: Dict = None,
                     image_description: str = None, image_path: str = None) -> str:
        return self._add_entry(question, answer, utility, source, None,
                               mem_type, custom_footnote, is_chaos=True,
                               emotion_vector=emotion_vector,
                               image_description=image_description,
                               image_path=image_path,
                               is_core=False)

    def _add_entry(self, question: str, answer: str, utility: float,
                   source: str, category_path: Optional[str], mem_type: str,
                   custom_footnote: Optional[Dict], is_chaos: bool,
                   emotion_vector: Optional[Dict] = None,
                   image_description: str = None, image_path: str = None,
                   is_core: bool = False) -> str:
        if not is_chaos:
            existing = self._find_similar_question(question, threshold=0.9)
            if existing:
                self._supersede_entry(existing['id'], new_utility=utility)
                supersedes_id = existing['id']
            else:
                supersedes_id = None
        else:
            supersedes_id = None

        entry_id = str(uuid.uuid4())
        timestamp = time.time()
        if custom_footnote:
            footnote = custom_footnote
        else:
            footnote = self._generate_footnote(question, answer, source)
        footnote["id"] = entry_id
        footnote["timestamp"] = timestamp
        if category_path:
            footnote["category_path"] = category_path
            footnote["category_levels"] = category_path.split('/')
        if supersedes_id:
            footnote["supersedes"] = supersedes_id

        # 向量编码（融合图像描述）
        text_to_encode = question
        if image_description:
            text_to_encode = f"{question} [图像描述: {image_description}]"
        vector = self.encoder.encode([text_to_encode])[0].tolist()

        entry = {
            "id": entry_id,
            "question": question,
            "answer": answer,
            "utility": max(0.1, min(5.0, utility)),
            "mem_type": mem_type,
            "vector": vector,
            "footnote": footnote,
            "crack_depth": 0,
            "crack_history": [],
            "relations": [],
            "emotion_vector": emotion_vector,
            "image_description": image_description,
            "image_path": image_path,
            "is_core": is_core and not is_chaos
        }
        target_dir = self.chaos_dir if is_chaos else self.entries_dir
        entry_file = os.path.join(target_dir, f"{entry_id}.json")
        with open(entry_file, 'w', encoding='utf-8') as f:
            json.dump(entry, f, indent=2, ensure_ascii=False)

        index_entry = {
            "id": entry_id,
            "timestamp": timestamp,
            "summary": footnote["summary"],
            "tags": footnote["tags"],
            "source": source,
            "path": entry_file,
            "utility": entry["utility"],
            "mem_type": mem_type,
            "category_path": category_path,
            "crack_depth": 0,
            "is_chaos": is_chaos,
            "is_core": is_core and not is_chaos
        }
        index_entry["ternary_attention"] = self._compute_ternary_attention_tag(index_entry)
        self._index["entries"].append(index_entry)
        self._save_index()

        # 增量更新 BM25 索引
        if not is_chaos:
            self._add_to_bm25(entry_id, question, answer)

        # 增量更新关键词索引
        if footnote["tags"]:
            self._add_to_keyword_index(entry_id, footnote["tags"])

        # 自动建立时序边
        if not is_chaos:
            self._link_timeline_edges(entry_id, mem_type, timestamp)

        return entry_id

    def promote_from_chaos(self, entry_id: str, suggested_category: str) -> bool:
        chaos_file = os.path.join(self.chaos_dir, f"{entry_id}.json")
        if not os.path.exists(chaos_file):
            return False
        with open(chaos_file, 'r', encoding='utf-8') as f:
            entry = json.load(f)
        entry["footnote"]["category_path"] = suggested_category
        entry["footnote"]["category_levels"] = suggested_category.split('/')
        target_file = os.path.join(self.entries_dir, f"{entry_id}.json")
        os.replace(chaos_file, target_file)
        for info in self._index["entries"]:
            if info["id"] == entry_id:
                info["category_path"] = suggested_category
                info["is_chaos"] = False
                info["path"] = target_file
                info["ternary_attention"] = self._compute_ternary_attention_tag(info)
                break
        self._save_index()
        self._add_to_bm25(entry_id, entry["question"], entry["answer"])
        if entry.get("footnote", {}).get("tags"):
            self._add_to_keyword_index(entry_id, entry["footnote"]["tags"])
        return True

    # ---------- 裂纹记录 ----------
    def record_crack(self, entry_id: str) -> bool:
        entry = self._load_entry(entry_id)
        if not entry:
            return False
        if "crack_depth" not in entry:
            entry["crack_depth"] = 0
        if "crack_history" not in entry:
            entry["crack_history"] = []
        entry["crack_depth"] += 1
        entry["crack_history"].append(time.time())
        self._save_entry(entry)
        for info in self._index["entries"]:
            if info["id"] == entry_id:
                info["crack_depth"] = entry["crack_depth"]
                info["ternary_attention"] = self._compute_ternary_attention_tag(info)
                break
        self._save_index()
        return True

    # ---------- 知识图谱关系 ----------
    def add_relation(self, source_id: str, target_id: str, relation_type: str) -> bool:
        source = self._load_entry(source_id)
        target = self._load_entry(target_id)
        if not source or not target:
            return False
        if "relations" not in source:
            source["relations"] = []
        for rel in source["relations"]:
            if rel.get("target_id") == target_id and rel.get("type") == relation_type:
                return True
        source["relations"].append({
            "target_id": target_id,
            "type": relation_type,
            "timestamp": time.time()
        })
        self._save_entry(source)
        return True

    def get_related_entries(self, entry_id: str, relation_type: Optional[str] = None, max_depth: int = 1) -> List[Dict]:
        visited = set()
        result = []
        queue = [(entry_id, 0)]
        while queue:
            current_id, depth = queue.pop(0)
            if current_id in visited or depth > max_depth:
                continue
            visited.add(current_id)
            current = self._load_entry(current_id)
            if not current:
                continue
            if current_id != entry_id:
                result.append(current)
            for rel in current.get("relations", []):
                if relation_type and rel.get("type") != relation_type:
                    continue
                target = rel.get("target_id")
                if target and target not in visited:
                    queue.append((target, depth + 1))
        return result

    def _ternary_relation_hint(self, entry_a: Dict, entry_b: Dict) -> int:
        vec_a = np.array(entry_a["vector"])
        vec_b = np.array(entry_b["vector"])
        sim = np.dot(vec_a, vec_b) / (np.linalg.norm(vec_a) * np.linalg.norm(vec_b) + 1e-8)
        time_a = entry_a.get("footnote", {}).get("timestamp", 0)
        time_b = entry_b.get("footnote", {}).get("timestamp", 0)
        time_diff = abs(time_a - time_b) / 86400 if time_a and time_b else 999
        if sim > 0.8 and time_diff < 7:
            return 1
        elif sim < 0.3 or time_diff > 90:
            return -1
        else:
            return 0

    def _suggest_relations(self, entry_id: str):
        entry = self._load_entry(entry_id)
        if not entry:
            return
        similar = self.retrieve_by_semantic(entry["question"], top_k=4, threshold=0.5, mem_type=entry.get("mem_type", "fact"))
        similar = [s for s in similar if s["id"] != entry_id][:3]
        if not similar:
            return
        for sim_entry in similar:
            hint = self._ternary_relation_hint(entry, sim_entry)
            if hint == -1:
                continue
            elif hint == 1:
                self.add_relation(entry_id, sim_entry["id"], "related_to")
                continue

            # 提示词文件化
            template = get_prompt("palace_memory/relation_suggestion.txt") or (
                "分析以下两段问答之间的关系，从以下选项中选择最合适的一个：\n"
                "- related_to：一般相关\n- contradicts：观点矛盾或相反\n- extends：进一步解释或扩展\n"
                "- exemplifies：举例说明\n- causes：因果关系\n如果无明显关系，输出 none。\n\n"
                "问答1：\n问题：{question1}\n回答：{answer1}\n\n问答2：\n问题：{question2}\n回答：{answer2}\n\n关系类型："
            )
            prompt = template.format(
                question1=entry['question'], answer1=entry['answer'][:300],
                question2=sim_entry['question'], answer2=sim_entry['answer'][:300]
            )
            try:
                response = ollama.chat(
                    model="qwen3.5:4b",
                    messages=[{"role": "user", "content": prompt}]
                )
                rel_type = response['message']['content'].strip().lower()
                if rel_type in ["related_to", "contradicts", "extends", "exemplifies", "causes"]:
                    self.add_relation(entry_id, sim_entry["id"], rel_type)
            except Exception as e:
                print(f"关系建议失败: {e}")

    # ---------- 时序图谱 ----------
    def _link_timeline_edges(self, entry_id: str, mem_type: str, timestamp: float):
        candidates = []
        for info in self._index["entries"]:
            if info.get("mem_type") != mem_type:
                continue
            if info.get("is_chaos", False):
                continue
            if info["id"] == entry_id:
                continue
            ts = info.get("timestamp", 0)
            if ts < timestamp:
                candidates.append((ts, info["id"]))
        if not candidates:
            return
        candidates.sort(key=lambda x: x[0], reverse=True)
        prev_id = candidates[0][1]
        self.add_relation(prev_id, entry_id, "before")
        self.add_relation(entry_id, prev_id, "after")
        print(f"🔗 时序边建立: {prev_id[:8]} --before--> {entry_id[:8]}")

    def retrieve_timeline(self, entry_id: str, direction: str = "both",
                          max_steps: int = 5, mem_type: str = None) -> List[Dict]:
        start_entry = self._load_entry(entry_id)
        if not start_entry:
            return []
        result = [start_entry]
        visited = {entry_id}
        if direction in ("backward", "both"):
            current_id = entry_id
            steps = 0
            while steps < max_steps:
                current = self._load_entry(current_id)
                if not current:
                    break
                found = False
                for rel in current.get("relations", []):
                    if rel.get("type") == "after":
                        target = rel.get("target_id")
                        if target and target not in visited:
                            target_entry = self._load_entry(target)
                            if target_entry:
                                if mem_type and target_entry.get("mem_type") != mem_type:
                                    continue
                                result.insert(0, target_entry)
                                visited.add(target)
                                current_id = target
                                steps += 1
                                found = True
                                break
                if not found:
                    break
        if direction in ("forward", "both"):
            current_id = entry_id
            steps = 0
            while steps < max_steps:
                current = self._load_entry(current_id)
                if not current:
                    break
                found = False
                for rel in current.get("relations", []):
                    if rel.get("type") == "before":
                        target = rel.get("target_id")
                        if target and target not in visited:
                            target_entry = self._load_entry(target)
                            if target_entry:
                                if mem_type and target_entry.get("mem_type") != mem_type:
                                    continue
                                result.append(target_entry)
                                visited.add(target)
                                current_id = target
                                steps += 1
                                found = True
                                break
                if not found:
                    break
        return result

    def build_timeline_edges_for_existing(self, mem_type: str = None):
        entries = []
        for info in self._index["entries"]:
            if info.get("is_chaos", False):
                continue
            if mem_type and info.get("mem_type") != mem_type:
                continue
            entries.append((info["timestamp"], info["id"], info.get("mem_type")))
        entries.sort(key=lambda x: x[0])
        count = 0
        for i in range(len(entries) - 1):
            ts1, id1, type1 = entries[i]
            ts2, id2, type2 = entries[i+1]
            if type1 == type2:
                self.add_relation(id1, id2, "before")
                self.add_relation(id2, id1, "after")
                count += 1
        print(f"🔗 批量建立时序边完成，共 {count} 对")
        self._save_index()

    # ---------- 检索方法 ----------
    def _keyword_match(self, query: str, mem_type: str = None) -> List[str]:
        """使用关键词索引进行精确匹配，返回匹配的记忆ID列表（按匹配度排序）"""
        query_tags = set(jieba.lcut(query))
        matched_scores = {}  # entry_id -> match_count
        for tag in query_tags:
            tag_lower = tag.lower()
            for entry_id in self.keyword_index.get(tag_lower, set()):
                # 检查是否符合类型过滤
                if mem_type:
                    # 简单从索引查找类型
                    for info in self._index["entries"]:
                        if info["id"] == entry_id:
                            if info.get("mem_type") != mem_type or info.get("is_chaos", False):
                                continue
                            break
                matched_scores[entry_id] = matched_scores.get(entry_id, 0) + 1
        # 按匹配次数降序排列
        sorted_ids = sorted(matched_scores.keys(), key=lambda eid: matched_scores[eid], reverse=True)
        return sorted_ids

    def retrieve_by_semantic(self, query: str, top_k: int = 3, threshold: float = 0.5,
                             mem_type: str = None, category_prefix: str = None,
                             include_chaos: bool = False, use_ternary_filter: bool = None,
                             time_bias: str = None, time_range_start: float = None,
                             time_range_end: float = None, time_reference: float = None,
                             time_decay_factor: float = 0.95) -> List[Dict]:
        if mem_type is None:
            print("⚠️ 警告：retrieve_by_semantic 必须指定 mem_type 参数，本次检索返回空。")
            return []
        if use_ternary_filter is None:
            use_ternary_filter = self.use_ternary_filter

        now = time.time()

        # 关键词精确匹配优先 (v14.11)
        keyword_matched_ids = self._keyword_match(query, mem_type)
        keyword_results = []
        remaining_ids = set(info["id"] for info in self._index["entries"] if info.get("mem_type") == mem_type)

        for eid in keyword_matched_ids:
            entry = self._load_entry(eid)
            if entry and eid in remaining_ids:
                keyword_results.append(entry)
                remaining_ids.discard(eid)

        # 语义检索 (剩余候选)
        q_vec = self.encoder.encode([query])[0]
        candidates = []
        for info in self._index["entries"]:
            if info["id"] not in remaining_ids:
                continue
            if info.get("mem_type") != mem_type:
                continue
            if category_prefix and not (info.get("category_path") or "").startswith(category_prefix):
                continue
            if not include_chaos and info.get("is_chaos", False):
                continue

            ts = info.get("timestamp", now)
            if time_bias == "range":
                if time_range_start is not None and ts < time_range_start:
                    continue
                if time_range_end is not None and ts > time_range_end:
                    continue
            elif time_bias == "before" and time_reference is not None:
                if ts > time_reference:
                    continue
            elif time_bias == "after" and time_reference is not None:
                if ts < time_reference:
                    continue

            if use_ternary_filter:
                tag = info.get("ternary_attention", 0)
                if tag == -1:
                    continue

            entry = self._load_entry(info["id"])
            if not entry:
                continue
            vec = np.array(entry["vector"])
            sim = np.dot(q_vec, vec) / (np.linalg.norm(q_vec) * np.linalg.norm(vec) + 1e-8)
            utility = entry.get("utility", 0.5)
            crack_depth = entry.get("crack_depth", 0)
            crack_factor = min(3.0, 1 + 0.1 * crack_depth)
            if info.get("is_chaos", False):
                crack_factor *= 0.5

            time_weight = 1.0
            if time_bias == "recent":
                age_days = (now - ts) / 86400
                time_weight = time_decay_factor ** age_days
            elif time_bias in ("before", "after") and time_reference is not None:
                distance_days = abs(ts - time_reference) / 86400
                time_weight = np.exp(-distance_days / 30)

            final_score = sim * utility * crack_factor * time_weight
            if final_score >= threshold:
                candidates.append((final_score, entry, sim))

        candidates.sort(key=lambda x: x[0], reverse=True)
        semantic_results = []
        for score, entry, sim in candidates[:top_k]:
            entry_copy = entry.copy()
            entry_copy["retrieval_score"] = score
            entry_copy["similarity"] = sim
            semantic_results.append(entry_copy)

        # 合并：关键词优先，然后语义
        final = keyword_results[:top_k]
        added_ids = {e["id"] for e in final}
        for res in semantic_results:
            if res["id"] not in added_ids and len(final) < top_k:
                final.append(res)
                added_ids.add(res["id"])
        return final

    def retrieve_hybrid(self, query: str, top_k: int = 5, threshold: float = 0.4,
                        mem_type: str = None, category_prefix: str = None,
                        include_chaos: bool = False, vector_weight: float = 0.6,
                        time_bias: str = None, time_range_start: float = None,
                        time_range_end: float = None, time_reference: float = None,
                        time_decay_factor: float = 0.95) -> List[Dict]:
        if mem_type is None:
            print("⚠️ 警告：retrieve_hybrid 必须指定 mem_type 参数")
            return []

        now = time.time()

        # 关键词匹配优先
        keyword_matched_ids = self._keyword_match(query, mem_type)
        keyword_results = []
        remaining_ids = set(info["id"] for info in self._index["entries"] if info.get("mem_type") == mem_type)

        for eid in keyword_matched_ids:
            entry = self._load_entry(eid)
            if entry and eid in remaining_ids:
                keyword_results.append(entry)
                remaining_ids.discard(eid)

        # 语义+BM25 混合检索
        q_vec = self.encoder.encode([query])[0]
        vector_candidates = {}
        for info in self._index["entries"]:
            if info["id"] not in remaining_ids:
                continue
            if info.get("mem_type") != mem_type:
                continue
            if category_prefix and not (info.get("category_path") or "").startswith(category_prefix):
                continue
            if not include_chaos and info.get("is_chaos", False):
                continue

            ts = info.get("timestamp", now)
            if time_bias == "range":
                if time_range_start is not None and ts < time_range_start:
                    continue
                if time_range_end is not None and ts > time_range_end:
                    continue
            elif time_bias == "before" and time_reference is not None:
                if ts > time_reference:
                    continue
            elif time_bias == "after" and time_reference is not None:
                if ts < time_reference:
                    continue

            entry = self._load_entry(info["id"])
            if not entry:
                continue
            vec = np.array(entry["vector"])
            sim = np.dot(q_vec, vec) / (np.linalg.norm(q_vec) * np.linalg.norm(vec) + 1e-8)
            if sim >= threshold * 0.7:
                vector_candidates[info["id"]] = (sim, ts)

        bm25_scores = {}
        if self.bm25_index and vector_candidates:
            query_tokens = jieba.lcut(query)
            id_to_idx = {doc_id: idx for idx, doc_id in enumerate(self.bm25_doc_ids)}
            doc_scores = self.bm25_index.get_scores(query_tokens)
            max_score = max(doc_scores) if max(doc_scores) > 0 else 1
            for entry_id in vector_candidates:
                idx = id_to_idx.get(entry_id)
                if idx is not None:
                    bm25_scores[entry_id] = doc_scores[idx] / max_score
                else:
                    bm25_scores[entry_id] = 0.0

        final_scores = []
        for entry_id, (vec_sim, ts) in vector_candidates.items():
            bm25 = bm25_scores.get(entry_id, 0.0)
            hybrid_score = vector_weight * vec_sim + (1 - vector_weight) * bm25
            entry = self._load_entry(entry_id)
            utility = entry.get("utility", 0.5)
            crack_depth = entry.get("crack_depth", 0)
            crack_factor = min(3.0, 1 + 0.1 * crack_depth)

            time_weight = 1.0
            if time_bias == "recent":
                age_days = (now - ts) / 86400
                time_weight = time_decay_factor ** age_days
            elif time_bias in ("before", "after") and time_reference is not None:
                distance_days = abs(ts - time_reference) / 86400
                time_weight = np.exp(-distance_days / 30)

            final = hybrid_score * utility * crack_factor * time_weight
            if final >= threshold:
                final_scores.append((final, entry, vec_sim))

        final_scores.sort(key=lambda x: x[0], reverse=True)
        semantic_results = []
        for score, entry, sim in final_scores[:top_k]:
            entry_copy = entry.copy()
            entry_copy["retrieval_score"] = score
            entry_copy["similarity"] = sim
            semantic_results.append(entry_copy)

        # 合并
        final = keyword_results[:top_k]
        added_ids = {e["id"] for e in final}
        for res in semantic_results:
            if res["id"] not in added_ids and len(final) < top_k:
                final.append(res)
                added_ids.add(res["id"])
        return final

    def retrieve_by_path(self, path_prefix: str, top_k: int = 10) -> List[Dict]:
        results = []
        for info in self._index["entries"]:
            if info.get("category_path", "").startswith(path_prefix) and not info.get("is_chaos", False):
                results.append(self._load_entry(info["id"]))
        return results[:top_k]

    def retrieve_by_tags(self, tags: List[str], top_k: int = 5) -> List[Dict]:
        results = []
        for info in self._index["entries"]:
            if info.get("is_chaos", False):
                continue
            score = sum(1 for t in tags if t in info.get("tags", []))
            if score > 0:
                results.append((score, info))
        results.sort(key=lambda x: x[0], reverse=True)
        return [self._load_entry(r[1]["id"]) for r in results[:top_k]]

    def retrieve_by_time_range(self, start_time: float, end_time: float) -> List[Dict]:
        entries = []
        for info in self._index["entries"]:
            if info.get("is_chaos", False):
                continue
            if start_time <= info["timestamp"] <= end_time:
                entries.append(self._load_entry(info["id"]))
        return entries

    # ---------- 记忆更新 ----------
    def update_utility(self, entry_id: str, delta: float):
        entry = self._load_entry(entry_id)
        if entry:
            entry["utility"] += delta
            entry["utility"] = max(0.1, min(5.0, entry["utility"]))
            self._save_entry(entry)
            for info in self._index["entries"]:
                if info["id"] == entry_id:
                    info["utility"] = entry["utility"]
                    info["ternary_attention"] = self._compute_ternary_attention_tag(info)
                    break
            self._save_index()

    def update_category(self, entry_id: str, new_category_path: str):
        entry = self._load_entry(entry_id)
        if not entry:
            return
        entry["footnote"]["category_path"] = new_category_path
        entry["footnote"]["category_levels"] = new_category_path.split('/')
        self._save_entry(entry)
        for info in self._index["entries"]:
            if info["id"] == entry_id:
                info["category_path"] = new_category_path
                break
        self._save_index()

    # ---------- 记忆重力/依赖度 ----------
    def get_memory_gravity(self, entry_id: str) -> Dict:
        entry = self._load_entry(entry_id)
        if not entry:
            return {"incoming_count": 0, "outgoing_count": 0, "incoming_importance": 0.0,
                    "gravity_score": 0.0, "is_protected": False}
        incoming = 0
        incoming_util_sum = 0.0
        outgoing = len(entry.get("relations", []))
        for info in self._index["entries"]:
            if info.get("is_chaos", False):
                continue
            if info["id"] == entry_id:
                continue
            other = self._load_entry(info["id"])
            if not other:
                continue
            for rel in other.get("relations", []):
                if rel.get("target_id") == entry_id:
                    incoming += 1
                    incoming_util_sum += other.get("utility", 0.5)
                    break
        incoming_importance = incoming_util_sum / incoming if incoming > 0 else 0.0
        gravity_score = min(1.0, (incoming * 0.3) + (incoming_importance * 0.5) + (outgoing * 0.1))
        is_protected = incoming >= 2 or entry.get("is_core", False)
        return {
            "incoming_count": incoming,
            "outgoing_count": outgoing,
            "incoming_importance": incoming_importance,
            "gravity_score": gravity_score,
            "is_protected": is_protected
        }

    def decay_utility(self, factor: float = 0.995):
        for info in self._index["entries"]:
            entry = self._load_entry(info["id"])
            if not entry:
                continue
            # 核心记忆不衰减
            if entry.get("is_core", False):
                continue
            gravity = self.get_memory_gravity(info["id"])
            if gravity["is_protected"]:
                protected_factor = 1.0 - (1.0 - factor) * 0.1
                entry["utility"] = max(0.1, entry["utility"] * protected_factor)
            else:
                entry["utility"] = max(0.1, entry["utility"] * factor)
            self._save_entry(entry)
            info["utility"] = entry["utility"]
            info["ternary_attention"] = self._compute_ternary_attention_tag(info)
        self._save_index()
        print(f"✅ 记忆效用已衰减（因子={factor}），核心记忆与高重力记忆受保护")

    def archive_low_utility_memories(self, utility_threshold: float = 0.15,
                                      days_old: int = 90) -> int:
        archive_dir = os.path.join(self.base_dir, "archived")
        os.makedirs(archive_dir, exist_ok=True)
        cutoff_time = time.time() - days_old * 86400
        archived_count = 0
        entries_to_remove = []
        for info in self._index["entries"]:
            if info.get("is_chaos", False):
                continue
            # 核心记忆不归档
            if info.get("is_core", False):
                continue
            if info.get("utility", 0.5) >= utility_threshold:
                continue
            if info.get("timestamp", 0) > cutoff_time:
                continue
            gravity = self.get_memory_gravity(info["id"])
            if gravity["is_protected"]:
                print(f"🛡️ 记忆 {info['id'][:8]} 受重力或核心保护，跳过归档")
                continue
            entry_id = info["id"]
            entry_file = os.path.join(self.entries_dir, f"{entry_id}.json")
            if os.path.exists(entry_file):
                archive_file = os.path.join(archive_dir, f"{entry_id}.json")
                shutil.move(entry_file, archive_file)
                entries_to_remove.append(info)
                archived_count += 1
                self._remove_from_keyword_index(entry_id)
        self._index["entries"] = [info for info in self._index["entries"] 
                                  if info not in entries_to_remove]
        self._save_index()
        self._build_bm25_index()
        print(f"📦 记忆归档完成，共归档 {archived_count} 条低效用记忆（核心与受保护记忆已跳过）")
        return archived_count

    # ---------- 情绪事件存储 ----------
    def store_emotion_event(self, emotion_vector, context: str = ""):
        if hasattr(emotion_vector, 'to_dict'):
            ev_dict = emotion_vector.to_dict()
        else:
            ev_dict = emotion_vector
        if ev_dict:
            self.add_to_chaos(
                question=f"情绪事件 {time.strftime('%Y-%m-%d %H:%M')}",
                answer=f"领域：{ev_dict.get('domain', 'unknown')}，强度：{ev_dict.get('color', 0):.2f}。上下文：{context}",
                utility=0.6,
                source="emotion_module",
                mem_type="emotion",
                emotion_vector=ev_dict
            )

    # ---------- 相似检测与冲突处理 ----------
    def _find_similar_question(self, question: str, threshold: float = 0.9) -> Optional[Dict]:
        q_vec = self.encoder.encode([question])[0]
        best = None
        best_score = 0
        for info in self._index["entries"]:
            if info.get("mem_type") != "fact" or info.get("is_chaos", False):
                continue
            entry = self._load_entry(info["id"])
            if not entry:
                continue
            vec = np.array(entry["vector"])
            sim = np.dot(q_vec, vec) / (np.linalg.norm(q_vec) * np.linalg.norm(vec) + 1e-8)
            if sim > threshold and sim > best_score:
                best_score = sim
                best = entry
        return best

    def _supersede_entry(self, entry_id: str, new_utility: float):
        entry = self._load_entry(entry_id)
        if entry:
            entry["utility"] = min(entry["utility"], 0.2)
            if "superseded_by" not in entry["footnote"]:
                entry["footnote"]["superseded_by"] = []
            entry["footnote"]["superseded_by"].append({"time": time.time(), "new_utility": new_utility})
            self._save_entry(entry)
            for info in self._index["entries"]:
                if info["id"] == entry_id:
                    info["utility"] = entry["utility"]
                    info["ternary_attention"] = self._compute_ternary_attention_tag(info)
                    break
            self._save_index()

    # ---------- 三进制注意力 ----------
    def _compute_ternary_attention_tag(self, index_info: Dict) -> int:
        utility = index_info.get("utility", 0.5)
        crack_depth = index_info.get("crack_depth", 0)
        timestamp = index_info.get("timestamp", time.time())
        age_days = (time.time() - timestamp) / 86400
        crack_factor = min(3.0, 1 + 0.1 * crack_depth)
        time_decay = 0.995 ** age_days
        score = utility * crack_factor * time_decay
        if score >= self.TERNARY_ATTENTION_HIGH_THRESHOLD:
            return 1
        elif score <= self.TERNARY_ATTENTION_LOW_THRESHOLD:
            return -1
        else:
            return 0

    def update_ternary_attention_tag(self, entry_id: str):
        for info in self._index["entries"]:
            if info["id"] == entry_id:
                info["ternary_attention"] = self._compute_ternary_attention_tag(info)
                self._save_index()
                return

    # ---------- 辅助方法 ----------
    def _load_entry(self, entry_id: str) -> Optional[Dict]:
        entry_file = os.path.join(self.entries_dir, f"{entry_id}.json")
        if not os.path.exists(entry_file):
            entry_file = os.path.join(self.chaos_dir, f"{entry_id}.json")
        if os.path.exists(entry_file):
            with open(entry_file, 'r', encoding='utf-8') as f:
                entry = json.load(f)
            if "crack_depth" not in entry:
                entry["crack_depth"] = 0
            if "crack_history" not in entry:
                entry["crack_history"] = []
            if "relations" not in entry:
                entry["relations"] = []
            if "emotion_vector" not in entry:
                entry["emotion_vector"] = None
            if "image_description" not in entry:
                entry["image_description"] = None
                entry["image_path"] = None
            if "is_core" not in entry:
                entry["is_core"] = False
            return entry
        return None

    def _save_entry(self, entry: Dict):
        is_chaos = False
        for info in self._index["entries"]:
            if info["id"] == entry["id"]:
                is_chaos = info.get("is_chaos", False)
                break
        target_dir = self.chaos_dir if is_chaos else self.entries_dir
        entry_file = os.path.join(target_dir, f"{entry['id']}.json")
        with open(entry_file, 'w', encoding='utf-8') as f:
            json.dump(entry, f, indent=2, ensure_ascii=False)

    def export_footnotes(self, output_file="footnotes.md"):
        from collections import defaultdict
        by_date = defaultdict(list)
        for info in self._index["entries"]:
            if info.get("is_chaos", False):
                continue
            date = datetime.fromtimestamp(info["timestamp"]).strftime("%Y-%m-%d")
            by_date[date].append(info)
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write("# 记忆宫殿注脚索引\n\n")
            for date in sorted(by_date.keys(), reverse=True):
                f.write(f"## {date}\n")
                for info in by_date[date]:
                    crack_str = f" [刻录:{info.get('crack_depth', 0)}]" if info.get('crack_depth', 0) > 0 else ""
                    tag_str = f" [三值:{info.get('ternary_attention', 0)}]" if 'ternary_attention' in info else ""
                    core_str = " [核心]" if info.get("is_core", False) else ""
                    f.write(f"- **摘要**：{info['summary']}{crack_str}{tag_str}{core_str}  [标签：{', '.join(info['tags'])}]  [来源：{info['source']}]  [类型：{info.get('mem_type','fact')}]\n")
                f.write("\n")
        print(f"注脚索引已导出到 {output_file}")

    def clear_all(self):
        shutil.rmtree(self.entries_dir)
        shutil.rmtree(self.chaos_dir)
        os.makedirs(self.entries_dir, exist_ok=True)
        os.makedirs(self.chaos_dir, exist_ok=True)
        self._index = {"entries": []}
        self._save_index()
        self._build_bm25_index()
        self._build_keyword_index()