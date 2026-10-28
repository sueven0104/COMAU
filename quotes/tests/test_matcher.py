from app import db
from app.matching.inquiry import InquiryLine
from app.matching.matcher import similarity, match_batch

def _seed():
    conn = db.connect(":memory:")
    fid = db.upsert_source_file(conn, {
        "path": "D:/BAIC/七轴/盛允.xlsx", "content_hash": "h", "file_type": ".xlsx",
        "project_code": "BAIC", "email_subject": None, "email_from": None,
        "email_date": None, "email_body": None, "processed_at": db.now()})
    db.insert_quote_items(conn, fid, "BAIC", [
        {"supplier": "盛允", "category": "7-Axis", "product_name": "机器人七轴",
         "spec": "11.5m 含底座", "brand": "盛允", "model": None, "qty": 1, "unit": "套",
         "unit_price": 100.0, "currency": "CNY", "tax_included": True,
         "price_status": "成交价", "quote_date": "2026-09-01", "terms": None,
         "source_location": "R2", "confidence": 0.9, "needs_review": 0},
        {"supplier": "KUKA", "category": "7-Axis", "product_name": "机器人七轴",
         "spec": "5m", "brand": "KUKA", "model": None, "qty": 1, "unit": "套",
         "unit_price": 200.0, "currency": "CNY", "tax_included": True,
         "price_status": "本次报价", "quote_date": "2026-09-02", "terms": None,
         "source_location": "R3", "confidence": 0.9, "needs_review": 0},
        {"supplier": "大铭", "category": "Sealing 涂胶", "product_name": "自动涂胶设备",
         "spec": None, "brand": None, "model": None, "qty": 1, "unit": "套",
         "unit_price": 500.0, "currency": "CNY", "tax_included": True,
         "price_status": "成交价", "quote_date": None, "terms": None,
         "source_location": "R4", "confidence": 0.9, "needs_review": 0}])
    return conn

def test_similarity():
    assert similarity("机器人七轴 11.5m 含底座", "机器人七轴 含底座 11.5m") > 0.8
    assert similarity("机器人七轴", "除尘系统") < 0.2

def test_match_batch_tiers():
    conn = _seed()
    lines = [
        InquiryLine(2, "7-Axis七轴", "机器人七轴 含底座 11.5m", "盛允", 2),
        InquiryLine(3, "7-Axis七轴", "机器人七轴", "其他品牌", 1),
        InquiryLine(4, "7-Axis七轴", "机器人七轴", None, 1),
        InquiryLine(5, "涂胶", "自动涂胶设备", None, 1),
        InquiryLine(6, "吊具 Hoist", "升降吊具", None, 1),   # 库中无品类
    ]
    results = match_batch(conn, None, lines)   # client=None：品类规则命中，不触发LLM
    tiers = [r.tier for r in results]
    assert tiers[0] == "精确匹配" and results[0].suggested_price == 100.0
    assert tiers[1] == "相似匹配"
    assert tiers[2] == "相似匹配"          # 无品牌信息降档
    assert tiers[3] == "相似匹配"          # 品类+产品名命中
    assert tiers[4] == "无匹配" and results[4].suggested_price is None
