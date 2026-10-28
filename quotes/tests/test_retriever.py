from app import db
from app.query import retriever

def _seed():
    conn = db.connect(":memory:")
    fid = db.upsert_source_file(conn, {
        "path": "D:/a.xlsx", "content_hash": "h", "file_type": ".xlsx",
        "project_code": "BAIC", "email_subject": None, "email_from": None,
        "email_date": None, "email_body": None, "processed_at": db.now()})
    db.insert_quote_items(conn, fid, "BAIC", [
        {"supplier": "盛允", "category": "7-Axis", "product_name": "机器人七轴",
         "spec": "11.5m", "brand": None, "model": None, "qty": 1, "unit": "套",
         "unit_price": 100.0, "currency": "CNY", "tax_included": True,
         "price_status": "成交价", "quote_date": "2026-09-01", "terms": None,
         "source_location": "R2", "confidence": 0.9, "needs_review": 0},
        {"supplier": "KUKA", "category": "7-Axis", "product_name": "机器人七轴",
         "spec": "5m", "brand": None, "model": None, "qty": 1, "unit": "套",
         "unit_price": 200.0, "currency": "CNY", "tax_included": True,
         "price_status": "本次报价", "quote_date": "2026-09-02", "terms": None,
         "source_location": "R3", "confidence": 0.9, "needs_review": 0}])
    return conn

def test_filter_from_dict_ignores_garbage():
    f = retriever.filter_from_dict({"categories": ["7-axis"], "suppliers": None,
                                    "foo": 1, "date_from": "2026-01-01"})
    assert f.categories == ["7-axis"] and f.date_from == "2026-01-01"
    assert f.suppliers is None

def test_search_case_insensitive_and_dates():
    conn = _seed()
    f = retriever.QueryFilter(categories=["7-AXIS"])
    rows = retriever.search(conn, f)
    assert len(rows) == 2
    f2 = retriever.QueryFilter(date_from="2026-09-02")
    assert [r["supplier"] for r in retriever.search(conn, f2)] == ["KUKA"]

def test_stats():
    conn = _seed()
    s = retriever.stats(conn, retriever.QueryFilter(categories=["7-axis"]))
    assert s["count"] == 2 and s["min"] == 100.0 and s["max"] == 200.0
