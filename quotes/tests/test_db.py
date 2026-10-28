from app import db

ITEM = {
    "supplier": "盛允", "category": "7-Axis", "product_name": "机器人七轴（含底座）",
    "spec": "11.5m", "brand": None, "model": None, "qty": 1.0, "unit": "套",
    "unit_price": 47900.0, "currency": "CNY", "tax_included": 1,
    "price_status": "成交价", "quote_date": "2026-09-09", "terms": "电汇价",
    "source_location": "Tabelle1!R2", "confidence": 0.95, "needs_review": 0,
}

def _conn():
    return db.connect(":memory:")

def test_schema_and_insert_search():
    conn = _conn()
    fid = db.upsert_source_file(conn, {
        "path": "D:/x/a.xlsx", "content_hash": "h1", "file_type": ".xlsx",
        "project_code": "BAIC", "email_subject": None, "email_from": None,
        "email_date": None, "email_body": None, "processed_at": db.now()})
    ids = db.insert_quote_items(conn, fid, "BAIC", [ITEM])
    assert len(ids) == 1
    rows = db.search_items(conn, categories=["7-axis"])  # 品类大小写不敏感
    assert len(rows) == 1 and rows[0]["unit_price"] == 47900.0
    rows = db.search_items(conn, suppliers=["不存在"])
    assert rows == []

def test_upsert_idempotent_and_reingest():
    conn = _conn()
    rec = {"path": "D:/x/a.xlsx", "content_hash": "h1", "file_type": ".xlsx",
           "project_code": "BAIC", "email_subject": None, "email_from": None,
           "email_date": None, "email_body": None, "processed_at": db.now()}
    fid = db.upsert_source_file(conn, rec)
    rec2 = {**rec, "content_hash": "h2"}
    fid2 = db.upsert_source_file(conn, rec2)
    assert fid == fid2  # 同路径覆盖更新，不产生新行
    db.insert_quote_items(conn, fid, "BAIC", [ITEM])
    db.delete_items_for_file(conn, fid)
    assert db.count_items(conn, source_file_id=fid) == 0
