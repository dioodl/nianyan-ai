# model_client.py
import json
from openai import OpenAI

class ModelRouter:
    def __init__(self, config_file="models_config.json"):
        with open(config_file, 'r', encoding='utf-8') as f:   # 指定 utf-8 编码
            self.config = json.load(f)
        self.clients = {}
        for name, cfg in self.config["models"].items():
            if cfg["type"] == "local":
                self.clients[name] = OpenAI(base_url=cfg["base_url"], api_key="ollama")
            else:
                api_key = cfg.get("api_key", "")
                # 支持环境变量替换
                if api_key.startswith("${") and api_key.endswith("}"):
                    import os
                    env_var = api_key[2:-1]
                    api_key = os.environ.get(env_var, "")
                self.clients[name] = OpenAI(base_url=cfg["base_url"], api_key=api_key)

    def call(self, role, messages, **kwargs):
        cfg = self.config["models"][role]
        client = self.clients[role]
        response = client.chat.completions.create(
            model=cfg["model"],
            messages=messages,
            temperature=kwargs.get("temperature", cfg.get("temperature", 0.7)),
            max_tokens=kwargs.get("max_tokens", 32750)
        )
        return response.choices[0].message.content