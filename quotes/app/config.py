"""配置加载：默认值 < config.json < .env / 环境变量；密钥只从环境变量或 quotes/.env 读取。"""
import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]  # quotes/

DEFAULTS = {
    "text_model": "qwen-plus",
    "vision_model": "qwen-vl-max",
    "embed_model": "text-embedding-v3",
    "data_root": "../raw_data/",
    "db_path": "data/quotes.db",
    "confidence_threshold": 0.7,
}

def load_dotenv(path=None) -> None:
    """读取 quotes/.env，仅补充未设置的环境变量（已存在的值优先，不会被覆盖）。"""
    p = Path(path) if path else ROOT / ".env"
    if not p.exists():
        return
    # utf-8-sig：兼容用户编辑器保存 .env 时带上 BOM 的情况
    for raw in p.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
    log.debug("已载入环境变量文件 %s", p)

def load_config(path=None) -> dict:
    load_dotenv()
    cfg = dict(DEFAULTS)
    p = Path(path) if path else ROOT / "config.json"
    if p.exists():
        cfg.update(json.loads(p.read_text(encoding="utf-8")))
        log.debug("已加载配置文件 %s", p)
    else:
        log.debug("未找到配置文件 %s，使用默认值", p)
    for k in ("text_model", "vision_model", "embed_model"):
        env = os.environ.get(f"QUOTES_{k.upper()}")
        if env:
            cfg[k] = env
    cfg["api_key"] = os.environ.get("QUOTES_API_KEY", "")
    log.debug("API 密钥%s", "已从环境变量读取" if cfg["api_key"] else "未设置（QUOTES_API_KEY）")
    cfg["base_url"] = os.environ.get(
        "QUOTES_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    cfg["data_root_abs"] = (ROOT / cfg["data_root"]).resolve()
    cfg["db_path_abs"] = (ROOT / cfg["db_path"]).resolve()
    return cfg
