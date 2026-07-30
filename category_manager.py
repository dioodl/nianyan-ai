# category_manager.py
import json
import numpy as np
from sentence_transformers import SentenceTransformer
from config import CATEGORY_FILE, DOMAIN_KEYWORDS

class CategoryManager:
    def __init__(self):
        self.filename = CATEGORY_FILE
        self.categories = []
        self.threshold = 0.8
        self.encoder = SentenceTransformer('all-MiniLM-L6-v2')
        self.load()

    def load(self):
        try:
            with open(self.filename, 'r') as f:
                data = json.load(f)
                self.categories = data.get('categories', [])
                for cat in self.categories:
                    cat['prototype'] = np.array(cat['prototype'])
        except FileNotFoundError:
            self.categories = []

    def save(self):
        to_save = []
        for cat in self.categories:
            to_save.append({
                'name': cat['name'],
                'prototype': cat['prototype'].tolist(),
                'count': cat['count']
            })
        with open(self.filename, 'w') as f:
            json.dump({'categories': to_save}, f, indent=2)

    def get_vector(self, text):
        return self.encoder.encode([text])[0]

    def find_best_category(self, vector):
        if not self.categories:
            return None, 0.0
        best_idx = -1
        best_sim = -1
        for i, cat in enumerate(self.categories):
            sim = np.dot(vector, cat['prototype']) / (np.linalg.norm(vector) * np.linalg.norm(cat['prototype']) + 1e-8)
            if sim > best_sim:
                best_sim = sim
                best_idx = i
        if best_sim >= self.threshold:
            return best_idx, best_sim
        return None, best_sim

    def add_or_update(self, text, vector):
        idx, sim = self.find_best_category(vector)
        if idx is not None:
            cat = self.categories[idx]
            n = cat['count']
            new_proto = (cat['prototype'] * n + vector) / (n + 1)
            cat['prototype'] = new_proto
            cat['count'] += 1
            return idx, cat['name']
        else:
            name = text[:20] + "..." if len(text) > 20 else text
            self.categories.append({
                'name': name,
                'prototype': vector,
                'count': 1
            })
            self.save()
            return len(self.categories) - 1, name

    def merge_similar(self):
        merged = False
        i = 0
        while i < len(self.categories):
            j = i + 1
            while j < len(self.categories):
                v1 = self.categories[i]['prototype']
                v2 = self.categories[j]['prototype']
                sim = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-8)
                if sim > 0.9:
                    n1 = self.categories[i]['count']
                    n2 = self.categories[j]['count']
                    new_proto = (v1 * n1 + v2 * n2) / (n1 + n2)
                    self.categories[i]['prototype'] = new_proto
                    self.categories[i]['count'] = n1 + n2
                    self.categories[i]['name'] = f"{self.categories[i]['name']} / {self.categories[j]['name']}"
                    del self.categories[j]
                    merged = True
                else:
                    j += 1
            i += 1
        if merged:
            self.save()
        return merged

    def detect_domain(self, text):
        text_lower = text.lower()
        for domain, keywords in DOMAIN_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                return domain
        vec = self.get_vector(text)
        idx, sim = self.find_best_category(vec)
        if idx is not None:
            return self.categories[idx]['name']
        idx, new_name = self.add_or_update(text, vec)
        return new_name