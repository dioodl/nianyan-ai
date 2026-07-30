# memory.py (适配模型路由器)
import os
import json
import time
import numpy as np
from sentence_transformers import SentenceTransformer
from config import MEMORY_DIR, MEMORY_DECAY_FACTOR, MEMORY_ARCHIVE_THRESHOLD, MEMORY_ARCHIVE_FILE, RULE_FILE
from model_router import ModelRouter


class WindowMemory:
    def __init__(self, window_id: str, router: ModelRouter = None):
        self.window_id = window_id
        self.filename = os.path.join(MEMORY_DIR, f"memory_{window_id}.json")
        self.data = []
        self.encoder = SentenceTransformer('all-MiniLM-L6-v2')
        self.load()
        self.compression_threshold = 100
        self.similarity_threshold = 0.85

        self.archive_file = MEMORY_ARCHIVE_FILE
        self.rule_file = RULE_FILE
        self.load_archive()
        self.load_rules()

        self.router = router or ModelRouter(max_concurrent_requests=1)

    # ---------- 原有加载保存方法 ----------
    def load(self):
        os.makedirs(MEMORY_DIR, exist_ok=True)
        try:
            with open(self.filename, 'r') as f:
                self.data = json.load(f)
            for item in self.data:
                if 'vector' not in item:
                    item['vector'] = self._get_vector(item['question']).tolist()
                else:
                    if isinstance(item['vector'], np.ndarray):
                        item['vector'] = item['vector'].tolist()
                if 'domain' not in item:
                    item['domain'] = "通用"
                if 'knowledge_type' not in item:
                    item['knowledge_type'] = "general"
                if 'metadata' not in item:
                    item['metadata'] = {}
        except FileNotFoundError:
            self.data = []

    def save(self):
        to_save = []
        for item in self.data:
            vec = item['vector'].tolist() if hasattr(item['vector'], 'tolist') else item['vector']
            to_save.append({
                'question': item['question'],
                'answer': item['answer'],
                'utility': item['utility'],
                'timestamp': item['timestamp'],
                'vector': vec,
                'domain': item.get('domain', '通用'),
                'knowledge_type': item.get('knowledge_type', 'general'),
                'metadata': item.get('metadata', {})
            })
        with open(self.filename, 'w') as f:
            json.dump(to_save, f, indent=2)

    def _get_vector(self, text):
        return self.encoder.encode([text])[0]

    def add(self, question, answer, utility=1.0, domain=None, knowledge_type=None, metadata=None):
        for item in self.data:
            if item['question'] == question:
                if utility > item['utility']:
                    item['answer'] = answer
                    item['utility'] = utility
                    item['timestamp'] = time.time()
                    item['vector'] = self._get_vector(question).tolist()
                    if domain:
                        item['domain'] = domain
                    if knowledge_type:
                        item['knowledge_type'] = knowledge_type
                    if metadata:
                        item['metadata'].update(metadata)
                    self.save()
                return
        vec = self._get_vector(question)
        self.data.append({
            'question': question,
            'answer': answer,
            'utility': utility,
            'timestamp': time.time(),
            'vector': vec.tolist(),
            'domain': domain or "通用",
            'knowledge_type': knowledge_type or "general",
            'metadata': metadata or {}
        })
        self.save()
        if len(self.data) > self.compression_threshold:
            self.compress()

    def retrieve(self, query, top_k=1, domain=None, knowledge_type=None, threshold=0.6):
        if not self.data:
            return []
        q_vec = self._get_vector(query)
        results = []
        for item in self.data:
            if domain and item.get('domain') != domain:
                continue
            if knowledge_type and item.get('knowledge_type') != knowledge_type:
                continue
            vec = np.array(item['vector'])
            sim = np.dot(q_vec, vec) / (np.linalg.norm(q_vec) * np.linalg.norm(vec) + 1e-8)
            final_score = sim * item['utility']
            if final_score >= threshold:
                results.append((final_score, item))
        results.sort(key=lambda x: x[0], reverse=True)
        return [(item, score) for score, item in results[:top_k]]

    def update_utility(self, question, delta):
        for item in self.data:
            if item['question'] == question:
                item['utility'] += delta
                item['utility'] = max(0.1, min(5.0, item['utility']))
                self.save()
                return

    # ---------- 新增治理方法 ----------
    def decay_utility(self, factor=MEMORY_DECAY_FACTOR):
        for item in self.data:
            item['utility'] *= factor
            item['utility'] = max(0.1, item['utility'])
        self.save()
        print(f"记忆效用衰减完成，因子={factor}")

    def archive_low_utility(self, threshold=MEMORY_ARCHIVE_THRESHOLD):
        archived = []
        remaining = []
        for item in self.data:
            if item['utility'] < threshold:
                archived.append(item)
            else:
                remaining.append(item)
        if archived:
            existing = []
            if os.path.exists(self.archive_file):
                with open(self.archive_file, 'r') as f:
                    existing = json.load(f)
            existing.extend(archived)
            with open(self.archive_file, 'w') as f:
                json.dump(existing, f, indent=2)
            self.data = remaining
            self.save()
            print(f"已归档 {len(archived)} 条低效用记忆，当前主库 {len(self.data)} 条")
        else:
            print("没有需要归档的记忆")

    def load_archive(self):
        if os.path.exists(self.archive_file):
            with open(self.archive_file, 'r') as f:
                self.archived_data = json.load(f)
        else:
            self.archived_data = []

    def load_rules(self):
        if os.path.exists(self.rule_file):
            with open(self.rule_file, 'r') as f:
                self.rules = json.load(f)
        else:
            self.rules = []

    def save_rules(self):
        with open(self.rule_file, 'w') as f:
            json.dump(self.rules, f, indent=2)

    def extract_rules(self, llm_client=None, model="qwen2.5:3b"):
        """从高效用记忆中提炼通用规则（调用 LLM）"""
        high_utility = [item for item in self.data if item['utility'] >= 1.5]
        if len(high_utility) < 5:
            print("高质量记忆不足，跳过规则提炼")
            return
        examples = "\n".join([f"问题：{item['question']}\n答案：{item['answer']}" for item in high_utility[:10]])
        prompt = f"""从以下问答对中提炼出通用的规则或模式，每条规则用一句话概括。输出JSON数组，例如：["规则1", "规则2"]。
问答对：
{examples}
规则："""
        try:
            # 优先使用路由器
            if self.router:
                response_text = self.router.call(
                    role="light_task",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3
                )
                rules = json.loads(response_text)
            elif llm_client:
                # 使用传入的客户端（如 ollama）
                response = llm_client.chat(model=model, messages=[{"role": "user", "content": prompt}])
                rules = json.loads(response['message']['content'])
            else:
                # 降级：默认使用 ollama
                import ollama
                response = ollama.chat(model=model, messages=[{"role": "user", "content": prompt}])
                rules = json.loads(response['message']['content'])
            if isinstance(rules, list):
                self.rules = rules
                self.save_rules()
                print(f"提炼出 {len(rules)} 条规则")
        except Exception as e:
            print(f"规则提炼失败: {e}")

    def compress(self):
        print(f"🔄 开始压缩记忆库（当前条目数：{len(self.data)}）")
        merged = []
        used = [False] * len(self.data)
        for i in range(len(self.data)):
            if used[i]:
                continue
            group = [self.data[i]]
            used[i] = True
            vec_i = np.array(self.data[i]['vector'])
            for j in range(i+1, len(self.data)):
                if used[j]:
                    continue
                vec_j = np.array(self.data[j]['vector'])
                sim = np.dot(vec_i, vec_j) / (np.linalg.norm(vec_i) * np.linalg.norm(vec_j) + 1e-8)
                if sim > self.similarity_threshold:
                    group.append(self.data[j])
                    used[j] = True
            if len(group) == 1:
                merged.append(group[0])
            else:
                best = max(group, key=lambda x: x['utility'])
                combined_question = " / ".join(set([g['question'] for g in group]))
                domain_counter = {}
                ktype_counter = {}
                for g in group:
                    d = g.get('domain', '通用')
                    domain_counter[d] = domain_counter.get(d, 0) + 1
                    kt = g.get('knowledge_type', 'general')
                    ktype_counter[kt] = ktype_counter.get(kt, 0) + 1
                merged_domain = max(domain_counter, key=domain_counter.get)
                merged_ktype = max(ktype_counter, key=ktype_counter.get)
                merged.append({
                    'question': combined_question,
                    'answer': best['answer'],
                    'utility': max(g['utility'] for g in group),
                    'timestamp': best['timestamp'],
                    'vector': best['vector'],
                    'domain': merged_domain,
                    'knowledge_type': merged_ktype,
                    'metadata': {}
                })
        self.data = merged
        self.save()
        print(f"✅ 压缩完成，当前条目数：{len(self.data)}")

    def clear(self):
        self.data = []
        self.save()