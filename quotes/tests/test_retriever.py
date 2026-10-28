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

def test_projects_filter_no_ambiguous_column():
    # JOIN source_files 后两表均有 project_code，裸列名会报 ambiguous column
    conn = _seed()
    rows = retriever.search(conn, retriever.QueryFilter(projects=["baic"]))
    assert len(rows) == 2
    assert all(r["source_path"] == "D:/a.xlsx" for r in rows)

def test_keyword_terms_or_match():
    # 多词 keyword 按空格分词后 OR 匹配：词分布在不同列也能召回
    conn = db.connect(":memory:")
    fid = db.upsert_source_file(conn, {
        "path": "D:/a.xlsx", "content_hash": "h", "file_type": ".xlsx",
        "project_code": "BAIC", "email_subject": None, "email_from": None,
        "email_date": None, "email_body": None, "processed_at": db.now()})
    db.insert_quote_items(conn, fid, "BAIC", [
        {"supplier": "伏能士", "category": "Arc Welding", "product_name": "Welding Package CMT",
         "spec": "焊机", "brand": "Fronius", "model": None, "qty": 1, "unit": "套",
         "unit_price": 1.0, "currency": "CNY", "tax_included": True,
         "price_status": "本次报价", "quote_date": None, "terms": None,
         "source_location": None, "confidence": 0.9, "needs_review": 0}])
    rows = retriever.search(conn, retriever.QueryFilter(keyword="Fronius CMT"))
    assert len(rows) == 1   # 两词分列存放，OR 匹配召回
