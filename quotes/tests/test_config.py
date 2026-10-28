import json
from pathlib import Path
from app import config

def test_defaults_and_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("QUOTES_API_KEY", "sk-test")
    monkeypatch.setenv("QUOTES_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("QUOTES_TEXT_MODEL", "my-model")
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"db_path": "data/x.db"}), encoding="utf-8")
    cfg = config.load_config(p)
    assert cfg["api_key"] == "sk-test"
    assert cfg["base_url"] == "https://example.com/v1"
    assert cfg["text_model"] == "my-model"      # 环境变量覆盖默认
    assert cfg["db_path_abs"].name == "x.db"     # 相对 quotes 根解析
    assert cfg["data_root_abs"].exists()
