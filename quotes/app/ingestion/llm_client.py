"""OpenAI 兼容 LLM 客户端（文本/视觉/embedding）+ 测试用 Fake。密钥来自环境变量。"""
import base64
import json
import logging
import re
import time
from pathlib import Path

log = logging.getLogger(__name__)

class LLMError(Exception):
    pass

def _image_mime(path) -> str:
    return {".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(
        Path(path).suffix.lower(), "image/png")

def parse_json_loose(text: str) -> dict:
    t = text.strip()
    if t.startswith("```"):
        parts = re.split(r"```", t)
        t = parts[1] if len(parts) > 1 else t
        if t.startswith("json"):
            t = t[4:]
    t = t.strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        start, end = t.find("{"), t.rfind("}")
        if start == -1 or end == -1:
            raise
        return json.loads(t[start:end + 1])

class LLMClient:
    # 单次调用超时（秒）：防止大 payload 下 SDK 默认 10 分钟超时 × 重试导致整夜卡死
    REQUEST_TIMEOUT = 180

    def __init__(self, cfg: dict):
        if not cfg.get("api_key"):
            raise LLMError("缺少环境变量 QUOTES_API_KEY")
        from openai import OpenAI
        self.client = OpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"],
                             timeout=self.REQUEST_TIMEOUT, max_retries=1)
        self.text_model = cfg["text_model"]
        self.vision_model = cfg["vision_model"]
        self.embed_model = cfg["embed_model"]
        log.info("LLM 客户端就绪：text=%s vision=%s embed=%s base_url=%s",
                 self.text_model, self.vision_model, self.embed_model, cfg["base_url"])

    def chat(self, system: str, user: str, images=None) -> str:
        content = [{"type": "text", "text": user}]
        for img in images or []:
            b64 = base64.b64encode(Path(img).read_bytes()).decode()
            content.append({"type": "image_url",
                            "image_url": {"url": f"data:{_image_mime(img)};base64,{b64}"}})
        model = self.vision_model if images else self.text_model
        t0 = time.perf_counter()
        log.debug("LLM 请求 model=%s 输入 %d 字符 图片 %d 张",
                  model, len(user), len(images or []))
        try:
            resp = self.client.chat.completions.create(
                model=model, temperature=0,
                extra_body={"enable_thinking": False},  # 思考模型关闭思考，加快抽取
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": content}])
        except Exception as e:
            log.error("LLM 调用失败 model=%s（耗时 %.1fs）：%s",
                      model, time.perf_counter() - t0, e)
            raise
        out = resp.choices[0].message.content
        log.debug("LLM 响应 model=%s 输出 %d 字符 耗时 %.1fs",
                  model, len(out or ""), time.perf_counter() - t0)
        return out

    def chat_json(self, system: str, user: str, images=None) -> dict:
        try:
            return parse_json_loose(self.chat(system, user, images))
        except (json.JSONDecodeError, ValueError) as e:
            log.warning("LLM 返回内容无法解析为 JSON：%s", e)
            raise LLMError(f"LLM 返回内容无法解析为 JSON: {e}") from e

    def embed(self, texts) -> list:
        items = list(texts)
        log.debug("embedding %d 段文本 model=%s", len(items), self.embed_model)
        resp = self.client.embeddings.create(model=self.embed_model, input=items)
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
