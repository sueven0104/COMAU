import pytest
from app.ingestion.llm_client import FakeLLMClient, LLMError, parse_json_loose

def test_parse_json_loose_strips_fences():
    assert parse_json_loose('```json\n{"a":1}\n```') == {"a": 1}
    assert parse_json_loose('{"b": 2}') == {"b": 2}

def test_fake_chat_json_and_chat():
    fake = FakeLLMClient(chat_responses=[{"items": []}, "纯文本回答"])
    assert fake.chat_json("s", "u") == {"items": []}
    assert fake.chat("s", "u") == "纯文本回答"

def test_fake_raises_when_exhausted():
    fake = FakeLLMClient(chat_responses=[])
    with pytest.raises(LLMError):
        fake.chat_json("s", "u")
