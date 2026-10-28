"""OpenAI 兼容 LLM 客户端（文本/视觉/embedding）+ 测试用 Fake。密钥来自环境变量。"""
import base64
import json
import re
from pathlib import Path

class LLMError(Exception):
    pass

def parse_json_loose(text: str) -> dict:
    t = text.strip()
    if t.startswith("```"):
        parts = re.split(r"```", t)
        t = parts[1] if len(parts) > 1 else t
        if t.startswith("json"):
            t = t[4:]
    return json.loads(t.strip())

class LLMClient:
    def __init__(self, cfg: dict):
        if not cfg.get("api_key"):
            raise LLMError("缺少环境变量 QUOTES_API_KEY")
        from openai import OpenAI
        self.client = OpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"])
        self.text_model = cfg["text_model"]
        self.vision_model = cfg["vision_model"]
        self.embed_model = cfg["embed_model"]

    def chat(self, system: str, user: str, images=None) -> str:
        content = [{"type": "text", "text": user}]
        for img in images or []:
            b64 = base64.b64encode(Path(img).read_bytes()).decode()
            content.append({"type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64}"}})
        model = self.vision_model if images else self.text_model
        resp = self.client.chat.completions.create(
            model=model, temperature=0,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": content}])
        return resp.choices[0].message.content

    def chat_json(self, system: str, user: str, images=None) -> dict:
        return parse_json_loose(self.chat(system, user, images))

    def embed(self, texts) -> list:
        resp = self.client.embeddings.create(model=self.embed_model, input=list(texts))
        return [d.embedding for d in resp.data]

class FakeLLMClient:
    """测试替身：按顺序弹出预设响应；Exception 实例则抛出。"""
    def __init__(self, chat_responses=(), embed_responses=()):
        self.chat_responses = list(chat_responses)
        self.embed_responses = list(embed_responses)

    def _pop(self):
        if not self.chat_responses:
            raise LLMError("FakeLLM: 预设响应已耗尽")
        r = self.chat_responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    def chat(self, system, user, images=None):
        return str(self._pop())

    def chat_json(self, system, user, images=None):
        r = self._pop()
        if not isinstance(r, dict):
            raise LLMError("FakeLLM: 该响应不是 dict")
        return r

    def embed(self, texts):
        if not self.embed_responses:
            raise LLMError("FakeLLM: 预设向量已耗尽")
        vs = self.embed_responses.pop(0)
        return [vs[i % len(vs)] for i in range(len(texts))]
