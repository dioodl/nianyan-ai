# meta_strategy.py
import json
import numpy as np
from config import META_STRATEGY_FILE

class MetaStrategy:
    def __init__(self):
        self.filename = META_STRATEGY_FILE
        self.operators = ["rewrite_prompt", "adjust_temperature", "enable_web_search", "request_clarification"]
        self.weights = {op: 1.0 for op in self.operators}
        self.load()

    def load(self):
        try:
            with open(self.filename, 'r') as f:
                data = json.load(f)
                self.weights = data.get('weights', self.weights)
        except FileNotFoundError:
            self.save()

    def save(self):
        with open(self.filename, 'w') as f:
            json.dump({'weights': self.weights}, f, indent=2)

    def update(self, operator, reward):
        self.weights[operator] += 0.1 * reward
        self.weights[operator] = max(0.1, min(5.0, self.weights[operator]))
        self.save()

    def select(self, failure_mode):
        ops = list(self.weights.keys())
        probs = np.array([self.weights[op] for op in ops])
        probs = probs / probs.sum()
        return np.random.choice(ops, p=probs)