"""配置加载：默认值 < config.json < 环境变量；密钥只从环境变量读取。"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # quotes/

DEFAULTS = {
    "text_model": "qwen-plus",
    "vision_model": "qwen-vl-max",
    "embed_model": "text-embedding-v3",
    "data_root": "../raw_data/",
    "db_path": "data/quotes.db",
    "confidence_threshold": 0.7,
}

def load_config(path=None) -> dict:
    cfg = dict(DEFAULTS)
    p = Path(path) if path else ROOT / "config.json"
    if p.exists():
        cfg.update(json.loads(p.read_text(encoding="utf-8")))
    for k in ("text_model", "vision_model", "embed_model"):
        env = os.environ.get(f"QUOTES_{k.upper()}")
        if env:
            cfg[k] = env
    cfg["api_key"] = os.environ.get("QUOTES_API_KEY", "")
    cfg["base_url"] = os.environ.get(
        "QUOTES_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    cfg["data_root_abs"] = (ROOT / cfg["data_root"]).resolve()
    cfg["db_path_abs"] = (ROOT / cfg["db_path"]).resolve()
    return cfg
