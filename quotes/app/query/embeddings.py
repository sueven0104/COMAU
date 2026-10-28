"""embedding 索引与余弦语义检索（数据量小，直接存 SQLite + Python 计算）。"""
import json
import logging
import math

log = logging.getLogger(__name__)

def _item_text(r) -> str:
    return " | ".join(str(x) for x in
                      (r["category"], r["product_name"], r["spec"], r["brand"]) if x)

def ensure_vectors(conn, client):
    rows = conn.execute(
        """SELECT quote_items.* FROM quote_items
           LEFT JOIN item_vectors ON item_vectors.item_id = quote_items.id
           WHERE item_vectors.item_id IS NULL""").fetchall()
    if not rows:
        return
    log.info("构建向量索引：%d 条条目待向量化", len(rows))
    vectors = client.embed([_item_text(r) for r in rows])
    conn.executemany(
        "INSERT OR REPLACE INTO item_vectors(item_id, text, vector) VALUES(?,?,?)",
        [(r["id"], _item_text(r), json.dumps(v)) for r, v in zip(rows, vectors)])
    conn.commit()
    log.info("向量索引构建完成：新增 %d 条", len(vectors))

def _cosine(a, b) -> float:
    num = sum(x * y for x, y in zip(a, b))
    da = math.sqrt(sum(x * x for x in a)) or 1.0
    db_ = math.sqrt(sum(y * y for y in b)) or 1.0
    return num / (da * db_)

def semantic_search(conn, client, query: str, k=10):
    ensure_vectors(conn, client)
    qv = client.embed([query])[0]
    rows = conn.execute(
        """SELECT quote_items.*, source_files.path AS source_path,
                  item_vectors.vector
           FROM item_vectors
           JOIN quote_items ON quote_items.id = item_vectors.item_id
           LEFT JOIN source_files ON source_files.id = quote_items.source_file_id""").fetchall()
    scored = sorted(
        ({"row": r, "score": _cosine(qv, json.loads(r["vector"]))} for r in rows),
        key=lambda x: -x["score"])
    top = scored[:k]
    if top:
        log.debug("语义检索 %r：候选 %d 条，top1 相似度 %.3f",
                  query, len(rows), top[0]["score"])
    log.info("语义检索命中 %d 条（候选 %d）", len(top), len(rows))
    return [dict(s["row"]) for s in top]
