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
