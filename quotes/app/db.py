"""SQLite 访问层：建表、source_files/quote_items 读写、检索。"""
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS source_files(
  id INTEGER PRIMARY KEY,
  path TEXT UNIQUE NOT NULL,
  content_hash TEXT NOT NULL,
  file_type TEXT NOT NULL,
  project_code TEXT NOT NULL,
  email_subject TEXT, email_from TEXT, email_date TEXT, email_body TEXT,
  processed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quote_items(
  id INTEGER PRIMARY KEY,
  source_file_id INTEGER NOT NULL REFERENCES source_files(id) ON DELETE CASCADE,
  project_code TEXT NOT NULL,
  supplier TEXT, category TEXT, product_name TEXT, spec TEXT,
  brand TEXT, model TEXT,
  qty REAL, unit TEXT, unit_price REAL, currency TEXT, tax_included INTEGER,
  price_status TEXT, quote_date TEXT, terms TEXT,
  source_location TEXT,
  confidence REAL NOT NULL DEFAULT 1.0,
  needs_review INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_items_category ON quote_items(category);
CREATE INDEX IF NOT EXISTS idx_items_supplier ON quote_items(supplier);
CREATE TABLE IF NOT EXISTS suppliers(
  name TEXT PRIMARY KEY, aliases TEXT NOT NULL DEFAULT '[]', brands TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS item_vectors(
  item_id INTEGER PRIMARY KEY REFERENCES quote_items(id) ON DELETE CASCADE,
  text TEXT NOT NULL,
  vector TEXT NOT NULL
);
"""

def connect(db_path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn

def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def upsert_source_file(conn, rec: dict) -> int:
    cur = conn.execute(
        """INSERT INTO source_files(path,content_hash,file_type,project_code,
             email_subject,email_from,email_date,email_body,processed_at)
           VALUES(:path,:content_hash,:file_type,:project_code,
             :email_subject,:email_from,:email_date,:email_body,:processed_at)
           ON CONFLICT(path) DO UPDATE SET
             content_hash=excluded.content_hash, file_type=excluded.file_type,
             email_subject=excluded.email_subject, email_from=excluded.email_from,
             email_date=excluded.email_date, email_body=excluded.email_body,
             processed_at=excluded.processed_at
           RETURNING id""", rec)
    row = cur.fetchone()  # RETURNING 需先取回结果；commit 由调用方（事务边界）负责
    return row[0]

def existing_file(conn, path):
    return conn.execute(
        "SELECT id, content_hash FROM source_files WHERE path=?", (path,)).fetchone()

ITEM_COLUMNS = ["supplier", "category", "product_name", "spec", "brand", "model",
                "qty", "unit", "unit_price", "currency", "tax_included",
                "price_status", "quote_date", "terms", "source_location",
                "confidence", "needs_review"]

def insert_quote_items(conn, source_file_id: int, project_code: str, items: list) -> list:
    ids = []
    placeholders = ",".join("?" * (len(ITEM_COLUMNS) + 3))
    with conn:  # 异常自动回滚，避免中途失败留下半量数据或未关闭事务
        for it in items:
            row = [it.get(c) for c in ITEM_COLUMNS]
            row[ITEM_COLUMNS.index("tax_included")] = (
                None if it.get("tax_included") is None else int(bool(it["tax_included"])))
            row[ITEM_COLUMNS.index("confidence")] = it.get("confidence", 1.0)
            row[ITEM_COLUMNS.index("needs_review")] = int(bool(it.get("needs_review")))
            cur = conn.execute(
                f"""INSERT INTO quote_items(source_file_id, project_code, {','.join(ITEM_COLUMNS)}, created_at)
                    VALUES({placeholders})""",
                (source_file_id, project_code, *row, now()))
            ids.append(cur.lastrowid)
    return ids

def delete_items_for_file(conn, source_file_id: int):
    # 不在函数内 commit：与 upsert/insert 由调用方包在同一事务中，保证原子性
    conn.execute("DELETE FROM quote_items WHERE source_file_id=?", (source_file_id,))

def count_items(conn, source_file_id=None) -> int:
    if source_file_id is None:
        return conn.execute("SELECT COUNT(*) FROM quote_items").fetchone()[0]
    return conn.execute("SELECT COUNT(*) FROM quote_items WHERE source_file_id=?",
                        (source_file_id,)).fetchone()[0]

def search_items(conn, categories=None, suppliers=None, projects=None,
                 price_status=None, keyword=None, limit=500):
    q = "SELECT * FROM quote_items WHERE 1=1"
    args = []
    for col, vals in (("LOWER(category)", categories), ("LOWER(supplier)", suppliers),
                      ("LOWER(project_code)", projects)):
        if vals:
            q += f" AND {col} IN ({','.join('?' * len(vals))})"
            args += [str(v).lower() for v in vals]
    if price_status:
        q += " AND price_status=?"
        args.append(price_status)
    if keyword:
        q += " AND (product_name LIKE ? OR spec LIKE ? OR brand LIKE ?)"
        args += [f"%{keyword}%"] * 3
    q += " ORDER BY quote_date DESC LIMIT ?"
    args.append(limit)
    return conn.execute(q, args).fetchall()
