import pytest
from app.ingestion.extractor import extract_from_payload
from app.ingestion.llm_client import FakeLLMClient, LLMError

GOOD = {"items": [{"supplier": "冠宇", "category": "Roller bed 滚床",
                   "product_name": "高速固定滚床", "spec": None, "qty": "9",
                   "unit_price": "30,375", "currency": "CNY",
                   "tax_included": "未税", "price_status": "成交价"}],
        "email_terms": None, "supplier_name": "江苏冠宇"}

def test_extract_cleans_items():
    fake = FakeLLMClient(chat_responses=[GOOD])
    out = extract_from_payload(fake, "a.xlsx", "表格内容")
    assert out["supplier_name"] == "江苏冠宇"
    it = out["items"][0]
    assert it["unit_price"] == 30375.0 and it["qty"] == 9.0
    assert it["tax_included"] is False and it["price_status"] == "成交价"

def test_retry_on_bad_json_then_success():
    fake = FakeLLMClient(chat_responses=["不是json", GOOD])
    out = extract_from_payload(fake, "a.xlsx", "x")
    assert len(out["items"]) == 1

def test_fail_after_retries():
    fake = FakeLLMClient(chat_responses=["bad", "bad", "bad"])
    with pytest.raises(LLMError):
        extract_from_payload(fake, "a.xlsx", "x")

def test_retry_on_non_dict_response():
    # items 内含非 dict 元素：validate_item 里 it.get 抛 AttributeError，应被重试捕获
    fake = FakeLLMClient(chat_responses=[{"items": ["不是dict"]}, GOOD])
    out = extract_from_payload(fake, "a.xlsx", "x")
    assert len(out["items"]) == 1

def test_non_dict_top_level_response_retries():
    # 顶层是裸数组：data.get 抛 AttributeError，应被重试捕获。
    # FakeLLMClient.chat_json 对非 dict 强制抛 LLMError 无法模拟裸数组，
    # 故用 StubClient 模拟真实 LLMClient（parse_json_loose 原样返回数组）。
    class StubClient:
        def __init__(self, responses):
            self.responses = list(responses)
        def chat_json(self, system, user, images=None):
            r = self.responses.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
    stub = StubClient([[1, 2], GOOD])  # 顶层是数组
    out = extract_from_payload(stub, "a.xlsx", "x")
    assert len(out["items"]) == 1
