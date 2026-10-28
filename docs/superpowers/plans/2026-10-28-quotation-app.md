# AI 报价查询系统 · 计划 B：对话查询/清单匹配/Web 应用 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在计划 A 建成的 SQLite 报价知识库之上，实现对话式查询、新询价清单四档匹配、报价草稿 Excel 导出与本地 Web 界面。

**Architecture:** 两段式检索（LLM 意图解析 → SQL 精确检索 → embedding 语义兜底 → LLM 带溯源汇总）；清单匹配为规则优先（品类/品牌/相似度阈值）+ LLM 兜底分类；FastAPI 单文件路由 + 原生 HTML/JS 单页。前置依赖：计划 A 已完成（`quotes/data/quotes.db` 可用、`app/db.py`、`app/ingestion/llm_client.py` 存在）。

**Tech Stack:** FastAPI、uvicorn、openpyxl、SQLite、原生 HTML/JS、pytest + fastapi TestClient。

**与设计文档的偏差（有意简化，YAGNI）：**
- 匹配结果与对话历史**不持久化**到库（设计 §4.2 的 inquiry_matches/conversations 表暂缓）：单用户场景下，匹配结果当次会话内存持有、草稿即时下载即够用
- 数据管理页的"人工修正回写"v1 不做 UI 编辑，直接用 DB Browser 改库（设计 §8）

**约定：** 命令在 `d:\Projects\COMAU\quotes` 执行；密钥仍走环境变量；LLM 调用在测试中全部用 `FakeLLMClient` 替身。

---

### Task 1: 检索层 retriever.py

**Files:**
- Create: `quotes/app/query/__init__.py`（空文件）
- Create: `quotes/app/query/retriever.py`
- Test: `quotes/tests/test_retriever.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_retriever.py
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
```

- [ ] **Step 2: 运行验证失败**

Run: `python -m pytest tests/test_retriever.py -v`
Expected: FAIL，ModuleNotFoundError

- [ ] **Step 3: 实现**

```python
# app/query/retriever.py
"""结构化检索：QueryFilter 构造 SQL，大小写不敏感，支持日期区间与统计。"""
from dataclasses import dataclass, field
from statistics import median

@dataclass
class QueryFilter:
    categories: list = None
    suppliers: list = None
    projects: list = None
    date_from: str = None
    date_to: str = None
    price_status: str = None
    keyword: str = None

def filter_from_dict(d: dict) -> QueryFilter:
    def lst(k):
        v = d.get(k)
        return [str(x) for x in v] if isinstance(v, list) and v else None
    return QueryFilter(
        categories=lst("categories"), suppliers=lst("suppliers"),
        projects=lst("projects"), date_from=d.get("date_from") or None,
        date_to=d.get("date_to") or None,
        price_status=d.get("price_status") or None,
        keyword=d.get("keyword") or None)

def _where(f: QueryFilter):
    q, args = " WHERE 1=1", []
    for col, vals in (("LOWER(category)", f.categories),
                      ("LOWER(supplier)", f.suppliers),
                      ("LOWER(project_code)", f.projects)):
        if vals:
            q += f" AND {col} IN ({','.join('?' * len(vals))})"
            args += [v.lower() for v in vals]
    if f.price_status:
        q += " AND price_status=?"; args.append(f.price_status)
    if f.date_from:
        q += " AND quote_date>=?"; args.append(f.date_from)
    if f.date_to:
        q += " AND quote_date<=?"; args.append(f.date_to)
    if f.keyword:
        q += " AND (product_name LIKE ? OR spec LIKE ? OR brand LIKE ?)"
        args += [f"%{f.keyword}%"] * 3
    return q, args

def search(conn, f: QueryFilter, limit=200):
    q, args = _where(f)
    return conn.execute(
        "SELECT quote_items.*, source_files.path AS source_path FROM quote_items "
        "LEFT JOIN source_files ON source_files.id=source_file_id"
        + q + " ORDER BY quote_date DESC LIMIT ?", (*args, limit)).fetchall()

def stats(conn, f: QueryFilter):
    rows = search(conn, f, limit=100000)
    prices = [r["unit_price"] for r in rows if r["unit_price"] is not None]
    return {"count": len(rows),
            "min": min(prices) if prices else None,
            "max": max(prices) if prices else None,
            "median": median(prices) if prices else None}
```

- [ ] **Step 4: 运行验证通过**

Run: `python -m pytest tests/test_retriever.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add quotes/app/query quotes/tests/test_retriever.py
git commit -m "feat: 结构化检索层（过滤/日期/统计）"
```

---

### Task 2: 向量索引 embeddings.py（语义兜底）

**Files:**
- Create: `quotes/app/query/embeddings.py`
- Modify: `quotes/app/db.py`（SCHEMA 增加 item_vectors 表）

- [ ] **Step 1: 在 db.py 的 SCHEMA 字符串末尾追加表定义**

```sql
CREATE TABLE IF NOT EXISTS item_vectors(
  item_id INTEGER PRIMARY KEY REFERENCES quote_items(id) ON DELETE CASCADE,
  text TEXT NOT NULL,
  vector TEXT NOT NULL
);
```

（`CREATE TABLE IF NOT EXISTS` 对已存在的库安全，无需迁移脚本。）

- [ ] **Step 2: 写失败测试**

```python
# tests/test_embeddings.py
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
```

- [ ] **Step 3: 运行验证失败**

Run: `python -m pytest tests/test_embeddings.py -v`
Expected: FAIL，ModuleNotFoundError

- [ ] **Step 4: 实现**

```python
# app/query/embeddings.py
"""embedding 索引与余弦语义检索（数据量小，直接存 SQLite + Python 计算）。"""
import json
import math

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
    vectors = client.embed([_item_text(r) for r in rows])
    conn.executemany(
        "INSERT OR REPLACE INTO item_vectors(item_id, text, vector) VALUES(?,?,?)",
        [(r["id"], _item_text(r), json.dumps(v)) for r, v in zip(rows, vectors)])
    conn.commit()

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
    return [dict(s["row"]) for s in scored[:k]]
```

- [ ] **Step 5: 运行验证通过**

Run: `python -m pytest tests/test_embeddings.py tests/test_db.py -v`
Expected: 全部 PASS（db 旧测试不回归）

- [ ] **Step 6: Commit**

```bash
git add quotes/app/db.py quotes/app/query/embeddings.py quotes/tests/test_embeddings.py
git commit -m "feat: embedding 语义检索兜底"
```

---

### Task 3: 对话编排 chat.py

**Files:**
- Create: `quotes/app/query/chat.py`
- Test: `quotes/tests/test_chat.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_chat.py
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
```

- [ ] **Step 2: 运行验证失败**

Run: `python -m pytest tests/test_chat.py -v`
Expected: FAIL，ModuleNotFoundError

- [ ] **Step 3: 实现**

```python
# app/query/chat.py
"""对话编排：意图解析 → SQL 检索 → 语义兜底 → 带溯源汇总。"""
from datetime import date
from . import retriever
from .embeddings import semantic_search

SYSTEM_INTENT = """把用户关于历史采购/报价的问题转成 JSON 查询条件。字段：
categories(品类列表), suppliers(供应商列表), projects(项目代号列表,如BAIC/Tesla),
date_from, date_to("YYYY-MM-DD"或null), price_status("成交价/本次报价/历史报价/预估价"或null),
keyword(自由文本关键词或null), metrics(["count","min","max","median","table"]中若干)。
今天是{today}。只输出 JSON。"""

SYSTEM_ANSWER = """你是采购报价分析助手。仅基于"检索结果"回答用户问题，禁止编造数据。
每个价格后必须以[来源:文件名 位置]形式标注溯源；数据不足时明确说明库中无对应数据；
适当给出数量、最低/中位/最高价等统计；回答末尾提示"建议价为参考，需人工确认"。"""

def _fmt_row(r) -> str:
    name = (r.get("source_path") or "").replace("\\", "/").split("/")[-1]
    tax = "含税" if r["tax_included"] else ("未税" if r["tax_included"] is not None else "税率不明")
    return (f"{r['project_code']} | {r['supplier']} | {r['category']} | "
            f"{r['product_name']} {r['spec'] or ''} | qty={r['qty']} | "
            f"{r['unit_price']} {r['currency'] or ''} {tax} | "
            f"{r['price_status']} | {r['quote_date'] or ''} | "
            f"[来源:{name} {r['source_location'] or ''}]")

def answer_question(conn, client, question: str) -> dict:
    intent = client.chat_json(
        SYSTEM_INTENT.format(today=date.today().isoformat()), question)
    f = retriever.filter_from_dict(intent)
    rows = [dict(r) for r in retriever.search(conn, f)]
    if not rows:  # 语义兜底
        try:
            rows = semantic_search(conn, client, question)
        except Exception:
            rows = []
    prices = [r["unit_price"] for r in rows if r.get("unit_price") is not None]
    from statistics import median
    stats_txt = (f"命中{len(rows)}条；价格 min={min(prices)} 中位={median(prices)} "
                 f"max={max(prices)}（币种以各条目为准）") if prices else f"命中{len(rows)}条"
    table = "\n".join(_fmt_row(r) for r in rows[:60])
    answer = client.chat(
        SYSTEM_ANSWER,
        f"用户问题：{question}\n统计：{stats_txt}\n检索结果：\n{table or '（无）'}")
    return {"answer": answer,
            "matched_count": len(rows),
            "citations": [{"item_id": r["id"],
                           "source_path": r.get("source_path"),
                           "source_location": r.get("source_location")}
                          for r in rows[:20]]}
```

- [ ] **Step 4: 运行验证通过**

Run: `python -m pytest tests/test_chat.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add quotes/app/query/chat.py quotes/tests/test_chat.py
git commit -m "feat: 对话编排（意图→检索→兜底→溯源汇总）"
```

---

### Task 4: 询价清单解析 inquiry.py

**Files:**
- Create: `quotes/app/matching/__init__.py`（空文件）
- Create: `quotes/app/matching/inquiry.py`
- Test: `quotes/tests/test_inquiry.py`

- [ ] **Step 1: 写失败测试（fixture 复刻真实 Inquiry table 表头结构）**

```python
# tests/test_inquiry.py
import openpyxl
from app.matching.inquiry import parse_inquiry_xlsx, InquiryLine

def _make_inquiry(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Inquiry table"
    ws.append(["Remark", "Product", "Commodity", "Category", "Commodity\nManager",
               "Buyer", "Vendor list", "Descripton", "Qty1", "Qty.", "Unit\nPrice"])
    ws.append(["本次报价", "7-Axis七轴", "Equipment", "7-Axis", "Li", "Li",
               "推荐", "机器人七轴 含底座 11.5m", 2, 2, 47900])
    ws.append(["历史报价", "Robot 机器人", "Equipment", "Robot", "Li", "Li",
               "FANUC", "R-2000iC", 8, 8, 300000])
    f = tmp_path / "inquiry.xlsx"
    wb.save(f)
    return f

def test_parse_maps_headers_tolerantly(tmp_path):
    lines = parse_inquiry_xlsx(_make_inquiry(tmp_path))
    assert len(lines) == 2
    l0 = lines[0]
    assert isinstance(l0, InquiryLine)
    assert l0.row_index == 2
    assert "七轴" in l0.product and "11.5m" in l0.spec
    assert l0.qty == 2 and l0.brand is None
    assert lines[1].brand == "FANUC" and lines[1].category == "Robot"

def test_prefers_sheet_named_inquiry(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active; ws.title = "汇总"
    ws.append(["杂项", "表头"]); ws.append([1, 2])
    ws2 = wb.create_sheet("Inquiry table")
    ws2.append(["Product", "Qty"]); ws2.append(["七轴", 1])
    f = tmp_path / "multi.xlsx"; wb.save(f)
    lines = parse_inquiry_xlsx(f)
    assert len(lines) == 1 and lines[0].product == "七轴"
```

- [ ] **Step 2: 运行验证失败**

Run: `python -m pytest tests/test_inquiry.py -v`
Expected: FAIL，ModuleNotFoundError

- [ ] **Step 3: 实现**

```python
# app/matching/inquiry.py
"""解析新项目询价清单 xlsx：定位 Inquiry 表、容错映射表头、产出清单行。"""
from dataclasses import dataclass
import openpyxl

@dataclass
class InquiryLine:
    row_index: int
    product: str
    spec: str = None
    brand: str = None
    qty: float = None
    unit: str = None
    category: str = None

# 表头别名：列表顺序 = 优先级（category 优先于 commodity 列；含真实清单的 Descripton 拼写）
ALIASES = {
    "product": ["product", "product name", "名称"],
    "spec": ["descripton", "description", "规格", "描述", "说明"],
    "qty": ["qty.", "qty", "数量"],
    "category": ["category", "品类", "commodity"],
    "brand": ["brand", "品牌", "vendor list"],
}
HEADER_KEYS = ["product", "spec", "qty", "category", "brand"]
NUM = "0123456789."
NOT_BRAND = {"推荐", "tbd", "无", "/"}

def _norm(s) -> str:
    return "".join(str(s).lower().split()) if s is not None else ""

def _map_header(row) -> dict:
    """按字段优先级映射列号：先精确匹配首选别名，再退而求其次。"""
    m = {}
    for field, names in ALIASES.items():
        for name in names:
            for j, cell in enumerate(row):
                if _norm(cell) == _norm(name) and j not in m.values():
                    m[field] = j
                    break
            if field in m:
                break
    return m

def _to_num(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = "".join(ch for ch in str(v) if ch in NUM)
    return float(s) if s else None

def parse_inquiry_xlsx(path) -> list:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheets = sorted(wb.worksheets,
                    key=lambda ws: 0 if "inquiry" in _norm(ws.title) else 1)
    for ws in sheets:
        grid = [list(r) for r in ws.iter_rows(values_only=True)]
        # 名字含 inquiry 的 sheet 放宽表头判定（Product+Qty 即可），其他 sheet 需 3 个字段
        need = 2 if "inquiry" in _norm(ws.title) else 3
        header_row, mapping = None, None
        for i, row in enumerate(grid[:10]):
            m = _map_header(row)
            if sum(1 for k in HEADER_KEYS if k in m) >= need:
                header_row, mapping = i, m
                break
        if header_row is None:
            continue
        lines = []
        for i, row in enumerate(grid[header_row + 1:], start=header_row + 2):
            def get(field):
                j = mapping.get(field)
                return row[j] if j is not None and j < len(row) else None
            product, spec = get("product"), get("spec")
            if not (product or spec):
                continue
            if product and _norm(product) in ("(blank)", "总计", "x"):
                continue
            if not any(v not in (None, "") for v in row):
                continue
            brand_raw = get("brand")
            brand = str(brand_raw).strip() if brand_raw else None
            if brand and _norm(brand) in NOT_BRAND:
                brand = None  # "推荐"等占位值不是品牌
            lines.append(InquiryLine(
                row_index=i, product=str(product).strip() if product else None,
                spec=str(spec).strip() if spec else None,
                brand=brand, qty=_to_num(get("qty")),
                unit=None, category=str(get("category")).strip() if get("category") else None))
        if lines:
            wb.close()
            return lines
    wb.close()
    return []
```

- [ ] **Step 4: 运行验证通过**

Run: `python -m pytest tests/test_inquiry.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add quotes/app/matching quotes/tests/test_inquiry.py
git commit -m "feat: 询价清单解析（容错表头映射）"
```

---

### Task 5: 四档匹配 matcher.py

**Files:**
- Create: `quotes/app/matching/matcher.py`
- Test: `quotes/tests/test_matcher.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_matcher.py
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
```

- [ ] **Step 2: 运行验证失败**

Run: `python -m pytest tests/test_matcher.py -v`
Expected: FAIL，ModuleNotFoundError

- [ ] **Step 3: 实现**

```python
# app/matching/matcher.py
"""四档匹配：规则优先（品类/品牌/文本相似度），LLM 仅兜底品类分类。建议价仅供参考。"""
import re
from dataclasses import dataclass, field
from statistics import median

from .. import db

@dataclass
class MatchResult:
    line_id: int
    tier: str                 # 精确匹配/相似匹配/弱匹配/无匹配
    suggested_price: float = None
    price_range: tuple = None
    quote_item_ids: list = field(default_factory=list)
    basis: str = None         # 参考依据：项目/供应商/日期/状态
    explanation: str = None   # 差异说明

def _tokens(s) -> set:
    if not s:
        return set()
    s = str(s).lower()
    words = set(re.findall(r"[a-z0-9]+", s))
    cjk = {s[i] for i in range(len(s)) if "\u4e00" <= s[i] <= "\u9fff"}
    return words | cjk

def similarity(a, b) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), len(tb))

def _brand_equal(a, b) -> bool:
    if not a or not b:
        return False
    return _norm_brand(a) == _norm_brand(b) or _norm_brand(a) in _norm_brand(b) \
        or _norm_brand(b) in _norm_brand(a)

def _norm_brand(s):
    return re.sub(r"\s+", "", str(s)).lower()

def guess_category(conn, line, client=None):
    """品类猜测：品类词在清单行文本中的覆盖率 ≥0.5 即命中，取覆盖最全者；LLM 兜底。"""
    cats = [r[0] for r in conn.execute(
        "SELECT DISTINCT category FROM quote_items WHERE category IS NOT NULL")]
    text = _tokens(" ".join(
        str(x) for x in (line.category, line.product, line.spec) if x))
    if not text:
        return None

    def cover(c):
        ct = _tokens(c)
        return len(ct & text) / len(ct) if ct else 0.0

    best = max(cats, key=cover, default=None)
    if best and cover(best) >= 0.5:
        return best
    if client is not None:  # LLM 兜底分类
        try:
            out = client.chat_json(
                "从给定品类列表中为设备选择最接近的品类，只输出JSON:{\"category\":\"...\"}；都不合适输出null。",
                f"品类列表：{','.join(cats)}\n设备：{line.product} {line.spec or ''}")
            c = out.get("category")
            if c in cats:
                return c
        except Exception:
            pass
    return None

def _line_text(line) -> str:
    return " ".join(str(x) for x in (line.product, line.spec, line.category) if x)

def match_line(conn, line, client=None) -> MatchResult:
    cat = guess_category(conn, line, client)
    cands = [dict(r) for r in db.search_items(conn, categories=[cat])] if cat else []
    if not cands:
        return MatchResult(line_id=line.row_index, tier="无匹配",
                           explanation="库中无该品类历史报价，需发起新询价")
    lt = _line_text(line)
    scored = []
    for c in cands:
        s = max(similarity(lt, f"{c['product_name']} {c['spec'] or ''}"),
                similarity(lt, f"{c['category']} {c['product_name']}"))
        scored.append((c, s))
    exact = [c for c, s in scored if s >= 0.5 and _brand_equal(line.brand, c["brand"])]
    exact_same_brand = [c for c, s in scored if s >= 0.5]
    similar = [c for c, s in scored if 0.25 <= s < 0.5] or exact_same_brand
    prefer = lambda lst: sorted(
        lst, key=lambda c: (c["price_status"] != "成交价", -(c["quote_date"] or "")))[0]

    def basis_of(lst):
        seen, parts = set(), []
        for c in sorted(lst, key=lambda x: (x["price_status"] != "成交价", -(x["quote_date"] or ""))):
            key = (c["project_code"], c["supplier"], c["price_status"])
            if key not in seen:
                seen.add(key)
                parts.append(f"{c['project_code']}/{c['supplier']}/{c['quote_date'] or '?'}/{c['price_status']}")
            if len(parts) >= 3:
                break
        return "；".join(parts)

    if exact:
        best = prefer(exact)
        return MatchResult(line.row_index, "精确匹配", suggested_price=best["unit_price"],
                           quote_item_ids=[c["id"] for c in exact],
                           basis=basis_of(exact),
                           explanation=f"同品类同品牌规格相近，参考成交价优先")
    if similar:
        prices = [c["unit_price"] for c in similar if c["unit_price"] is not None]
        brands = {c["brand"] for c in similar if c["brand"]}
        diffs = []
        if line.brand and brands and not any(_brand_equal(line.brand, b) for b in brands):
            diffs.append(f"品牌差异：清单 {line.brand} vs 历史 {'/'.join(list(brands)[:3])}")
        return MatchResult(line.row_index, "相似匹配",
                           suggested_price=median(prices) if prices else None,
                           price_range=(min(prices), max(prices)) if prices else None,
                           quote_item_ids=[c["id"] for c in similar],
                           basis=basis_of(similar),
                           explanation="；".join(filter(None, diffs + ["同品类，品牌/规格存在差异"])))
    prices = [c["unit_price"] for c in cands if c["unit_price"] is not None]
    return MatchResult(line.row_index, "弱匹配",
                       suggested_price=median(prices) if prices else None,
                       price_range=(min(prices), max(prices)) if prices else None,
                       quote_item_ids=[c["id"] for c in cands],
                       basis=basis_of(cands),
                       explanation="仅品类相同，价格区间跨度大，务必人工判断")

def match_batch(conn, client, lines) -> list:
    return [match_line(conn, ln, client) for ln in lines]
```

说明：匹配规则与测试断言的对应——第 1 行品牌"盛允"+高相似度 → 精确匹配；第 2 行品牌不匹配但相似度高 → 相似匹配；第 3 行无品牌信息降为相似匹配；第 4 行"涂胶"覆盖"Sealing 涂胶"品类词 2/3 且产品名完全一致 → 相似匹配（品牌缺失不能算精确）；第 5 行"吊具"品类覆盖率为 0 且无 LLM 兜底 → 无匹配。

- [ ] **Step 4: 运行验证通过**

Run: `python -m pytest tests/test_matcher.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add quotes/app/matching/matcher.py quotes/tests/test_matcher.py
git commit -m "feat: 四档匹配引擎（规则优先+LLM品类兜底）"
```

---

### Task 6: 报价草稿导出 draft.py

**Files:**
- Create: `quotes/app/export/__init__.py`（空文件）
- Create: `quotes/app/export/draft.py`
- Test: `quotes/tests/test_draft.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_draft.py
import openpyxl
from app import db
from app.export.draft import export_draft
from app.matching.inquiry import InquiryLine
from app.matching.matcher import MatchResult

def test_export_draft_columns_and_rows(tmp_path):
    conn = db.connect(":memory:")
    fid = db.upsert_source_file(conn, {
        "path": "D:/BAIC/盛允.xlsx", "content_hash": "h", "file_type": ".xlsx",
        "project_code": "BAIC", "email_subject": None, "email_from": None,
        "email_date": None, "email_body": None, "processed_at": db.now()})
    ids = db.insert_quote_items(conn, fid, "BAIC", [
        {"supplier": "盛允", "category": "7-Axis", "product_name": "机器人七轴",
         "spec": "11.5m", "brand": "盛允", "model": None, "qty": 1, "unit": "套",
         "unit_price": 100.0, "currency": "CNY", "tax_included": True,
         "price_status": "成交价", "quote_date": "2026-09-01", "terms": None,
         "source_location": "R2", "confidence": 0.9, "needs_review": 0}])
    lines = [InquiryLine(2, "7-Axis七轴", "机器人七轴 11.5m", "盛允", 2)]
    matches = [MatchResult(2, "精确匹配", suggested_price=100.0,
                           quote_item_ids=ids, basis="BAIC/盛允/2026-09-01/成交价",
                           explanation="参考成交价")]
    out = tmp_path / "draft.xlsx"
    export_draft(conn, lines, matches, out)
    ws = openpyxl.load_workbook(out).active
    header = [c.value for c in ws[1]]
    assert header[:3] == ["行号", "产品", "规格"]
    assert "建议价" in header and "溯源" in header and "需人工确认" in header
    row2 = [c.value for c in ws[2]]
    assert row2[0] == 2 and row2[header.index("建议价")] == 100.0
    assert "盛允.xlsx" in row2[header.index("溯源")]
```

- [ ] **Step 2: 运行验证失败**

Run: `python -m pytest tests/test_draft.py -v`
Expected: FAIL，ModuleNotFoundError

- [ ] **Step 3: 实现**

```python
# app/export/draft.py
"""报价建议草稿导出：原清单行 + 建议价 + 档位 + 依据 + 溯源 + 人工确认标记。"""
from pathlib import Path
import openpyxl
from openpyxl.styles import Font, PatternFill

COLUMNS = ["行号", "产品", "规格", "品牌", "数量", "建议价", "价格区间",
           "匹配档位", "参考依据", "差异说明", "溯源", "需人工确认"]

NEED_CONFIRM = {"弱匹配", "无匹配"}

def export_draft(conn, lines, matches, out_path):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "报价建议草稿"
    ws.append(COLUMNS)
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="EFEFF2")
    for ln, m in zip(lines, matches):
        trace = ""
        if m.quote_item_ids:
            rows = conn.execute(
                """SELECT sf.path, qi.source_location FROM quote_items qi
                   JOIN source_files sf ON sf.id=qi.source_file_id WHERE qi.id=?""",
                (m.quote_item_ids[0],)).fetchall()
            if rows:
                p = Path(rows[0]["path"])
                trace = f"{p.name} {rows[0]['source_location'] or ''}".strip()
        ws.append([
            ln.row_index, ln.product, ln.spec, ln.brand, ln.qty,
            m.suggested_price,
            f"{m.price_range[0]:.0f}~{m.price_range[1]:.0f}" if m.price_range else None,
            m.tier, m.basis, m.explanation, trace,
            "是" if m.tier in NEED_CONFIRM else ""])
    for col, width in zip("ABCDEFGHIJKL", [6, 22, 28, 12, 8, 12, 16, 10, 40, 36, 30, 10]):
        ws.column_dimensions[col].width = width
    wb.save(out_path)
    return out_path
```

- [ ] **Step 4: 运行验证通过**

Run: `python -m pytest tests/test_draft.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quotes/app/export quotes/tests/test_draft.py
git commit -m "feat: 报价建议草稿 Excel 导出"
```

---

### Task 7: Web 服务 server.py

**Files:**
- Create: `quotes/app/web/__init__.py`（空文件）
- Create: `quotes/app/web/server.py`
- Create: `quotes/app/web/static/index.html`（Task 8 实现内容，此任务先建占位以便路由测试）
- Test: `quotes/tests/test_server.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_server.py
import io
import openpyxl
from fastapi.testclient import TestClient
from app import db
from app.web import server

def _client(monkeypatch, tmp_path):
    # 每个测试独立数据库连接，避免模块级缓存串库
    conn = db.connect(tmp_path / "test.db")
    server._CONN = conn
    monkeypatch.setattr(server, "get_conn", lambda: conn)
    return TestClient(server.app), conn

def _seed(conn):
    fid = conn.execute("""INSERT INTO source_files(path,content_hash,file_type,
        project_code,processed_at) VALUES('D:/a.xlsx','h','.xlsx','BAIC',?)
        RETURNING id""", (server.db.now(),)).fetchone()[0]
    conn.execute("""INSERT INTO quote_items(source_file_id,project_code,supplier,
        category,product_name,spec,brand,model,qty,unit,unit_price,currency,
        tax_included,price_status,quote_date,terms,source_location,confidence,
        needs_review,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (fid, "BAIC", "盛允", "7-Axis", "机器人七轴", "11.5m", "盛允", None, 1, "套",
         100.0, "CNY", 1, "成交价", "2026-09-01", None, "R2", 0.9, 0, server.db.now()))
    conn.commit()
    return fid

def test_chat_endpoint(monkeypatch, tmp_path):
    from app.ingestion.llm_client import FakeLLMClient
    tc, conn = _client(monkeypatch, tmp_path)
    _seed(conn)
    fake = FakeLLMClient(chat_responses=[
        {"categories": ["7-Axis"]}, "七轴成交价100元 [来源:a.xlsx R2]"])
    monkeypatch.setattr(server, "get_llm", lambda: fake)
    r = tc.post("/api/chat", json={"question": "七轴价格"})
    assert r.status_code == 200
    body = r.json()
    assert "100" in body["answer"] and body["matched_count"] == 1

def test_inquiry_upload_and_draft(monkeypatch, tmp_path):
    tc, conn = _client(monkeypatch, tmp_path)
    _seed(conn)
    from app.ingestion.llm_client import FakeLLMClient
    monkeypatch.setattr(server, "get_llm", lambda: FakeLLMClient())
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Inquiry table"
    ws.append(["Product", "Brand", "Qty"])
    ws.append(["7-Axis七轴 机器人七轴 11.5m", "盛允", 2])
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    r = tc.post("/api/inquiry/upload", files={"file": ("inq.xlsx", buf,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200
    data = r.json()
    assert data["results"][0]["tier"] == "精确匹配"
    r2 = tc.get(f"/api/inquiry/{data['batch_id']}/draft.xlsx")
    assert r2.status_code == 200 and len(r2.content) > 1000

def test_files_and_review_endpoints(monkeypatch, tmp_path):
    tc, conn = _client(monkeypatch, tmp_path)
    _seed(conn)
    assert tc.get("/api/files").status_code == 200
    assert tc.get("/api/review").status_code == 200
    meta = tc.get("/api/meta").json()
    assert "7-Axis" in meta["categories"] and "盛允" in meta["suppliers"]
```

- [ ] **Step 2: 运行验证失败**

Run: `python -m pytest tests/test_server.py -v`
Expected: FAIL，ModuleNotFoundError

- [ ] **Step 3: 实现**

```python
# app/web/server.py
"""本地 Web 服务：对话、清单上传匹配、草稿下载、数据管理。"""
import tempfile
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import db
from ..config import load_config
from ..ingestion.llm_client import LLMClient
from ..query import chat as chat_mod
from ..matching import inquiry as inquiry_mod, matcher as matcher_mod
from ..export import draft as draft_mod

app = FastAPI(title="AI 报价查询系统")
CFG = load_config()

# 内存态：batch_id -> (lines, matches)
BATCHES = {}
_CONN = None

def get_conn():
    """懒加载正式库连接；测试通过 monkeypatch 替换并直接设置 _CONN。"""
    global _CONN
    if _CONN is None:
        Path(CFG["db_path_abs"]).parent.mkdir(parents=True, exist_ok=True)
        _CONN = db.connect(CFG["db_path_abs"])
    return _CONN

_LLM = None

def get_llm():
    global _LLM
    if _LLM is None:
        _LLM = LLMClient(CFG)
    return _LLM

class ChatIn(BaseModel):
    question: str

@app.post("/api/chat")
def api_chat(body: ChatIn):
    if not body.question.strip():
        raise HTTPException(400, "问题不能为空")
    out = chat_mod.answer_question(get_conn(), get_llm(), body.question)
    return out

@app.post("/api/inquiry/upload")
async def api_inquiry_upload(file: UploadFile = File(...)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix != ".xlsx":
        raise HTTPException(400, "只支持 .xlsx 询价清单")
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        f.write(await file.read())
        tmp = f.name
    lines = inquiry_mod.parse_inquiry_xlsx(tmp)
    if not lines:
        raise HTTPException(422, "未识别到询价清单表头（需含 Product/Qty 等列）")
    matches = matcher_mod.match_batch(get_conn(), get_llm(), lines)
    batch_id = uuid4().hex
    BATCHES[batch_id] = (lines, matches)
    return {"batch_id": batch_id,
            "count": len(lines),
            "results": [{"row_index": ln.row_index, "product": ln.product,
                         "tier": m.tier, "suggested_price": m.suggested_price,
                         "price_range": m.price_range, "basis": m.basis,
                         "explanation": m.explanation}
                        for ln, m in zip(lines, matches)]}

@app.get("/api/inquiry/{batch_id}/draft.xlsx")
def api_inquiry_draft(batch_id: str):
    if batch_id not in BATCHES:
        raise HTTPException(404, "批次不存在或已过期，请重新上传")
    lines, matches = BATCHES[batch_id]
    out = Path(tempfile.gettempdir()) / f"draft_{batch_id}.xlsx"
    draft_mod.export_draft(get_conn(), lines, matches, out)
    return FileResponse(out, filename="报价建议草稿.xlsx")

@app.get("/api/files")
def api_files():
    rows = get_conn().execute(
        """SELECT sf.path, sf.project_code, sf.file_type, sf.email_subject,
                  sf.email_date, COUNT(qi.id) AS item_count
           FROM source_files sf LEFT JOIN quote_items qi ON qi.source_file_id=sf.id
           GROUP BY sf.id ORDER BY sf.project_code, sf.path""").fetchall()
    return {"files": [dict(r) for r in rows]}

@app.get("/api/review")
def api_review():
    rows = get_conn().execute(
        """SELECT qi.id, qi.product_name, qi.unit_price, qi.supplier,
                  qi.source_location, sf.path
           FROM quote_items qi JOIN source_files sf ON sf.id=qi.source_file_id
           WHERE qi.needs_review=1 LIMIT 500""").fetchall()
    return {"review": [dict(r) for r in rows]}

@app.get("/api/meta")
def api_meta():
    conn = get_conn()
    cats = [r[0] for r in conn.execute(
        "SELECT DISTINCT category FROM quote_items WHERE category IS NOT NULL")]
    sups = [r[0] for r in conn.execute(
        "SELECT DISTINCT supplier FROM quote_items WHERE supplier IS NOT NULL")]
    projs = [r[0] for r in conn.execute(
        "SELECT DISTINCT project_code FROM quote_items")]
    return {"categories": cats, "suppliers": sups, "projects": projs}

@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")
```

说明：测试通过 `server._CONN = conn` + monkeypatch `get_conn` 实现每测试独立数据库；上传接口对 .msg/.pdf 等非 .xlsx 直接 400。

- [ ] **Step 4: 建 static 占位（Task 8 填充）**

```html
<!-- quotes/app/web/static/index.html -->
<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>AI 报价查询</title></head><body>placeholder</body></html>
```

- [ ] **Step 5: 运行验证通过**

Run: `python -m pytest tests/test_server.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add quotes/app/web quotes/tests/test_server.py
git commit -m "feat: FastAPI 服务（对话/清单/草稿/数据管理接口）"
```

---

### Task 8: 前端单页 index.html

**Files:**
- Modify: `quotes/app/web/static/index.html`（替换占位为完整实现）

- [ ] **Step 1: 写完整前端（原生 HTML/JS，无构建工具）**

```html
<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI 报价查询系统</title>
<style>
  :root { --bg:#f6f7f9; --card:#fff; --text:#1a1a1a; --muted:#667; --line:#e3e5e8; --brand:#0a7d43; }
  * { box-sizing:border-box; }
  body { margin:0; font:14px/1.6 "Segoe UI","PingFang SC",sans-serif; background:var(--bg); color:var(--text); }
  header { background:var(--card); border-bottom:1px solid var(--line); padding:12px 24px; display:flex; gap:16px; align-items:center; }
  header h1 { font-size:16px; margin:0; }
  nav button { border:1px solid var(--line); background:var(--bg); padding:6px 14px; border-radius:8px; cursor:pointer; }
  nav button.on { background:var(--brand); color:#fff; border-color:var(--brand); }
  main { max-width:1100px; margin:20px auto; padding:0 16px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px; margin-bottom:16px; }
  .msg { padding:10px 14px; border-radius:10px; margin:8px 0; white-space:pre-wrap; }
  .msg.user { background:#e8f0ea; margin-left:30%; }
  .msg.bot { background:var(--bg); margin-right:10%; }
  .cite { display:inline-block; font-size:12px; color:var(--muted); border:1px dashed var(--line); border-radius:6px; padding:1px 6px; margin:2px; }
  input[type=text] { flex:1; padding:10px; border:1px solid var(--line); border-radius:8px; }
  button.pri { background:var(--brand); color:#fff; border:0; border-radius:8px; padding:10px 18px; cursor:pointer; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th,td { border:1px solid var(--line); padding:6px 8px; text-align:left; vertical-align:top; }
  th { background:var(--bg); }
  .tier-精确匹配 { color:var(--brand); font-weight:600; }
  .tier-无匹配 { color:#c0392b; }
  .muted { color:var(--muted); font-size:12px; }
  .row { display:flex; gap:8px; }
</style>
</head>
<body>
<header>
  <h1>AI 报价查询系统</h1>
  <nav>
    <button data-tab="chat" class="on">对话查询</button>
    <button data-tab="inquiry">清单匹配</button>
    <button data-tab="data">数据管理</button>
  </nav>
</header>
<main>
  <section id="tab-chat" class="card">
    <div id="chatlog"><p class="muted">例：BE22 七轴各家报价对比？滚床最低价是多少？Fronius CMT 报过几次？</p></div>
    <div class="row"><input id="q" type="text" placeholder="输入问题，回车发送"><button class="pri" id="send">提问</button></div>
  </section>

  <section id="tab-inquiry" class="card" hidden>
    <p>上传新项目询价清单（.xlsx，需含 Product/Qty 表头），逐行匹配历史报价：</p>
    <div class="row"><input id="file" type="file" accept=".xlsx"><button class="pri" id="upload">上传匹配</button></div>
    <div id="inqresult"></div>
  </section>

  <section id="tab-data" class="card" hidden>
    <h3>已入库文件</h3><div id="filetable" class="muted">加载中…</div>
    <h3>待人工复核（低置信度/校验警告）</h3><div id="reviewtable" class="muted">加载中…</div>
  </section>
</main>
<script>
const $ = s => document.querySelector(s);
document.querySelectorAll("nav button").forEach(b => b.onclick = () => {
  document.querySelectorAll("nav button").forEach(x => x.classList.remove("on"));
  b.classList.add("on");
  ["chat","inquiry","data"].forEach(t => $("#tab-"+t).hidden = t !== b.dataset.tab);
});

async function ask() {
  const q = $("#q").value.trim(); if (!q) return;
  $("#q").value = "";
  const log = $("#chatlog");
  log.insertAdjacentHTML("beforeend", `<div class="msg user">${q}</div>`);
  const div = document.createElement("div"); div.className = "msg bot"; div.textContent = "思考中…";
  log.appendChild(div); log.parentElement.scrollTop = 1e9;
  try {
    const r = await fetch("/api/chat", {method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({question:q})});
    const d = await r.json();
    div.textContent = d.answer;
    if (d.citations && d.citations.length)
      div.insertAdjacentHTML("beforeend", "<div>" + d.citations.slice(0,8).map(c =>
        `<span class="cite" title="${c.source_path||""} ${c.source_location||""}">来源#${c.item_id}</span>`).join("") + "</div>");
  } catch (e) { div.textContent = "请求失败：" + e; }
}
$("#send").onclick = ask;
$("#q").onkeydown = e => { if (e.key === "Enter") ask(); };

$("#upload").onclick = async () => {
  const f = $("#file").files[0]; if (!f) return alert("请选择文件");
  $("#inqresult").textContent = "匹配中…";
  const fd = new FormData(); fd.append("file", f);
  const r = await fetch("/api/inquiry/upload", {method:"POST", body:fd});
  if (!r.ok) { $("#inqresult").textContent = "上传失败：" + (await r.text()); return; }
  const d = await r.json();
  let html = `<p>共 ${d.count} 行。 <a href="/api/inquiry/${d.batch_id}/draft.xlsx">下载报价建议草稿.xlsx</a></p>
    <table><tr><th>行</th><th>产品</th><th>档位</th><th>建议价</th><th>区间</th><th>依据</th><th>说明</th></tr>`;
  for (const x of d.results)
    html += `<tr><td>${x.row_index}</td><td>${x.product||""}</td>
      <td class="tier-${x.tier}">${x.tier}</td><td>${x.suggested_price ?? ""}</td>
      <td>${x.price_range ? x.price_range[0]+"~"+x.price_range[1] : ""}</td>
      <td class="muted">${x.basis||""}</td><td class="muted">${x.explanation||""}</td></tr>`;
  $("#inqresult").innerHTML = html + "</table>";
};

async function loadData() {
  const f = await (await fetch("/api/files")).json();
  $("#filetable").innerHTML = "<table><tr><th>项目</th><th>文件</th><th>类型</th><th>明细数</th><th>邮件主题</th></tr>" +
    f.files.map(x => `<tr><td>${x.project_code}</td><td>${x.path}</td><td>${x.file_type}</td>
      <td>${x.item_count}</td><td class="muted">${x.email_subject||""}</td></tr>`).join("") + "</table>";
  const rv = await (await fetch("/api/review")).json();
  $("#reviewtable").innerHTML = rv.review.length
    ? "<table><tr><th>ID</th><th>产品</th><th>价格</th><th>供应商</th><th>位置</th><th>文件</th></tr>" +
      rv.review.map(x => `<tr><td>${x.id}</td><td>${x.product_name||""}</td><td>${x.unit_price??""}</td>
        <td>${x.supplier||""}</td><td>${x.source_location||""}</td><td class="muted">${x.path}</td></tr>`).join("") + "</table>"
    : "无待复核项";
}
loadData();
</script>
</body>
</html>
```

- [ ] **Step 2: 静态页与回归测试**

Run: `python -m pytest -v` 然后：

```powershell
python -c "from fastapi.testclient import TestClient; from app.web import server; c=TestClient(server.app); r=c.get('/'); print(r.status_code, len(r.text))"
```

Expected: 全部测试 PASS；`/` 返回 200 且内容 > 2000 字符（非占位页）

- [ ] **Step 3: Commit**

```bash
git add quotes/app/web/static/index.html
git commit -m "feat: 本地 Web 单页界面（对话/清单/数据管理）"
```

---

### Task 9: 端到端验收（人工检查点）

**Files:** 无新代码。

- [ ] **Step 1: 启动服务**

```powershell
$env:QUOTES_API_KEY="<你的key>"
$env:QUOTES_BASE_URL="<你的endpoint>"
python -m uvicorn app.web.server:app --port 8000
```

浏览器打开 `http://127.0.0.1:8000`。

- [ ] **Step 2: 验收 10 个典型问题（设计文档第 10 节）**

逐条提问并人工核对答案与库内数据一致、每个价格带溯源：
1. BE22 项目七轴有几家报价？分别是多少？
2. 7 轴历史最低成交价是多少？哪家供应商？
3. 滚床（Roller bed）按供应商对比单价。
4. Fronius CMT 焊机报过几次？含税吗？
5. 涂胶设备的价格区间？
6. 视觉（Vision）在 BAIC 和 Tesla 两项目的报价差异。
7. 哪些品类有"成交价"记录？
8. 除尘系统哪家报价最便宜？
9. 吊具（Hoist）在 Tesla R05 的报价明细。
10. 激光打码的历史报价趋势（按日期）。

- [ ] **Step 3: 清单匹配回测**

用 BAIC 项目自身的 `BAIC BE22 Inquiry list 20260910.xlsx` 上传到"清单匹配"页：
- 预期：七轴/滚床/弧焊等品类行命中"精确/相似匹配"；建议价与库内一致
- 下载草稿 xlsx，抽查 10 行的溯源能打开到正确文件

- [ ] **Step 4: 数据管理页检查**

- 文件列表覆盖 BAIC + Tesla 全部已入库文件
- 复核清单与 `data/review.csv` 一致

- [ ] **Step 5: 覆盖率与最终提交**

```powershell
pip install pytest-cov --disable-pip-version-check
python -m pytest --cov=app --cov-report=term
git add -A
git commit -m "chore: 计划B端到端验收通过"
```

Expected: 覆盖率 ≥ 80%

---

## 验收标准（计划 B 完成 = 以下全部满足）

1. `python -m pytest` 全绿，覆盖率 ≥ 80%
2. 10 个验收问题答案与库内数据一致且带溯源
3. BE22 自身清单回测：主要品类行命中精确/相似匹配，建议价可追溯
4. Web 界面三页（对话/清单/数据）全部可用，草稿 xlsx 可下载
