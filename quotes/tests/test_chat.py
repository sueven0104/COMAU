from app import db
from app.query import chat
from app.ingestion.llm_client import FakeLLMClient

def _seed():
    conn = db.connect(":memory:")
    fid = db.upsert_source_file(conn, {
        "path": "D:/BAIC/七轴/盛允.xlsx", "content_hash": "h", "file_type": ".xlsx",
        "project_code": "BAIC", "email_subject": None, "email_from": None,
        "email_date": None, "email_body": None, "processed_at": db.now()})
    db.insert_quote_items(conn, fid, "BAIC", [
        {"supplier": "盛允", "category": "7-Axis", "product_name": "机器人七轴",
         "spec": "11.5m", "brand": None, "model": None, "qty": 1, "unit": "套",
         "unit_price": 100.0, "currency": "CNY", "tax_included": True,
         "price_status": "成交价", "quote_date": "2026-09-01", "terms": "电汇价",
         "source_location": "Tabelle1!R2", "confidence": 0.9, "needs_review": 0}])
    return conn

INTENT = {"categories": ["7-Axis"], "suppliers": None, "projects": None,
          "date_from": None, "date_to": None, "price_status": None,
          "keyword": None, "metrics": ["table"]}

def test_answer_with_citation():
    conn = _seed()
    fake = FakeLLMClient(chat_responses=[INTENT, "七轴成交价 100 元/套 [来源:盛允.xlsx Tabelle1!R2]"])
    out = chat.answer_question(conn, fake, "七轴历史价格多少")
    assert "100" in out["answer"]
    assert out["matched_count"] == 1
    assert out["citations"][0]["source_path"].endswith("盛允.xlsx")

def test_no_result_falls_back_to_semantic():
    conn = _seed()
    # 意图过滤无命中 -> 走语义兜底（向量：item0 与查询同向、item1 正交）；再由 LLM 汇总
    fake = FakeLLMClient(
        chat_responses=[{"categories": ["不存在的品类"]}, "语义兜底找到相关记录 100 元"],
        embed_responses=[[[1.0, 0.0], [0.0, 1.0]], [[1.0, 0.0]]])
    out = chat.answer_question(conn, fake, "机器人第七轴多少钱")
    assert out["matched_count"] >= 1
