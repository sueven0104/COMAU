from app import db
from app.query import embeddings

def _seed_conn():
    conn = db.connect(":memory:")
    fid = db.upsert_source_file(conn, {
        "path": "D:/a.xlsx", "content_hash": "h", "file_type": ".xlsx",
        "project_code": "BAIC", "email_subject": None, "email_from": None,
        "email_date": None, "email_body": None, "processed_at": db.now()})
    ids = db.insert_quote_items(conn, fid, "BAIC", [
        {"supplier": "s", "category": "7-Axis", "product_name": "机器人七轴",
         "spec": "导轨", "brand": None, "model": None, "qty": 1, "unit": "套",
         "unit_price": 1.0, "currency": "CNY", "tax_included": True,
         "price_status": "成交价", "quote_date": None, "terms": None,
         "source_location": None, "confidence": 0.9, "needs_review": 0},
        {"supplier": "s", "category": "Vision", "product_name": "涂胶视觉",
         "spec": "2D", "brand": None, "model": None, "qty": 1, "unit": "套",
         "unit_price": 2.0, "currency": "CNY", "tax_included": True,
         "price_status": "成交价", "quote_date": None, "terms": None,
         "source_location": None, "confidence": 0.9, "needs_review": 0}])
    return conn, ids

def test_ensure_and_semantic_search():
    conn, ids = _seed_conn()
    # 向量：item0 与查询同向，item0 与 item1 正交
    v_q, v0, v1 = [1.0, 0.0], [1.0, 0.0], [0.0, 1.0]
    class FakeEmb:
        def embed(self, texts):
            if len(texts) == 1:
                return [v_q]
            return [v0, v1]
    embeddings.ensure_vectors(conn, FakeEmb())
    hits = embeddings.semantic_search(conn, FakeEmb(), "机器人第七轴导轨", k=2)
    assert hits[0]["id"] == ids[0]      # 语义最近的排第一
    assert len(hits) == 2

def test_ensure_vectors_idempotent():
    conn, ids = _seed_conn()
    calls = []
    class FakeEmb:
        def embed(self, texts):
            calls.append(len(texts)); return [[1.0, 0.0]] * len(texts)
    embeddings.ensure_vectors(conn, FakeEmb())
    embeddings.ensure_vectors(conn, FakeEmb())   # 第二次应无新增
    assert calls == [2]                          # 只在首次 embed 了 2 条
