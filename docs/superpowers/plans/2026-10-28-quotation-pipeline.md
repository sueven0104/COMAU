# AI 报价查询系统 · 计划 A：数据建库管道 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `d:\Projects\COMAU` 下 2 个项目约 105 个文件（.msg/.xlsx/.pdf/.png）的历史报价抽取为带溯源的 SQLite 标准化知识库。

**Architecture:** 扫描目录 → 按类型解析（extract-msg/openpyxl/pymupdf/视觉模型）→ LLM 结构化抽取（JSON + 校验 + 置信度）→ SQLite 入库（幂等、断点续跑）→ 人工复核 CSV 报告。设计文档：`docs/superpowers/specs/2026-10-28-ai-quotation-query-system-design.md`。

**Tech Stack:** Python 3.14、SQLite(stdlib)、openai SDK（OpenAI 兼容云端 API，视觉模型）、extract-msg、openpyxl、pymupdf、pytest。

**约定：**
- 代码根目录：`d:\Projects\COMAU\quotes\`（包名 `app`），原始数据在仓库根目录，不入库不提交。
- 所有命令在 `d:\Projects\COMAU\quotes` 目录下执行；PowerShell 语法。
- API Key 只从环境变量 `QUOTES_API_KEY`、`QUOTES_BASE_URL` 读取，绝不写入文件（安全规则）。

---

### Task 0: 项目脚手架与 git 初始化

**Files:**
- Create: `d:\Projects\COMAU\.gitignore`
- Create: `d:\Projects\COMAU\quotes\pyproject.toml`
- Create: `d:\Projects\COMAU\quotes\config.json`
- Create: `d:\Projects\COMAU\quotes\app\__init__.py`（空文件）
- Create: `d:\Projects\COMAU\quotes\app\ingestion\__init__.py`（空文件）
- Create: `d:\Projects\COMAU\quotes\tests\__init__.py`（空文件）

- [ ] **Step 1: git init 与 .gitignore（白名单方式，机密价格数据绝不入库）**

在 `d:\Projects\COMAU` 执行 `git init`，然后写 `.gitignore`：

```gitignore
# 白名单：只跟踪代码与文档，机密商务数据(价格)不入库
/*
!/quotes/
!/docs/
quotes/data/
quotes/__pycache__/
**/__pycache__/
*.pyc
.env
```

- [ ] **Step 2: 写 pyproject.toml**

```toml
[project]
name = "quotes"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "fastapi",
  "uvicorn",
  "openai",
  "openpyxl",
  "extract-msg",
  "pymupdf",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 3: 写 config.json（不含任何密钥）**

```json
{
  "text_model": "qwen-plus",
  "vision_model": "qwen-vl-max",
  "embed_model": "text-embedding-v3",
  "data_root": "../",
  "db_path": "data/quotes.db",
  "confidence_threshold": 0.7
}
```

模型名按手头 API 供应商调整；密钥一律走环境变量。

- [ ] **Step 4: 安装依赖并验证**

Run: `pip install -e . pytest --disable-pip-version-check`
Expected: 成功安装，无报错

- [ ] **Step 5: 初始提交**

```bash
git add .gitignore docs quotes/pyproject.toml quotes/config.json quotes/app quotes/tests
git commit -m "chore: 初始化报价系统项目脚手架"
```

---

### Task 1: 配置加载 config.py

**Files:**
- Create: `quotes/app/config.py`
- Test: `quotes/tests/test_config.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_config.py
import json
from pathlib import Path
from app import config

def test_defaults_and_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("QUOTES_API_KEY", "sk-test")
    monkeypatch.setenv("QUOTES_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("QUOTES_TEXT_MODEL", "my-model")
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"db_path": "data/x.db"}), encoding="utf-8")
    cfg = config.load_config(p)
    assert cfg["api_key"] == "sk-test"
    assert cfg["base_url"] == "https://example.com/v1"
    assert cfg["text_model"] == "my-model"      # 环境变量覆盖默认
    assert cfg["db_path_abs"].name == "x.db"     # 相对 quotes 根解析
    assert cfg["data_root_abs"].exists()
```

- [ ] **Step 2: 运行验证失败**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL，`AttributeError: module 'app.config' has no attribute 'load_config'`

- [ ] **Step 3: 实现**

```python
# app/config.py
"""配置加载：默认值 < config.json < 环境变量；密钥只从环境变量读取。"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # quotes/

DEFAULTS = {
    "text_model": "qwen-plus",
    "vision_model": "qwen-vl-max",
    "embed_model": "text-embedding-v3",
    "data_root": "../",
    "db_path": "data/quotes.db",
    "confidence_threshold": 0.7,
}

def load_config(path=None) -> dict:
    cfg = dict(DEFAULTS)
    p = Path(path) if path else ROOT / "config.json"
    if p.exists():
        cfg.update(json.loads(p.read_text(encoding="utf-8")))
    for k in ("text_model", "vision_model", "embed_model"):
        env = os.environ.get(f"QUOTES_{k.upper()}")
        if env:
            cfg[k] = env
    cfg["api_key"] = os.environ.get("QUOTES_API_KEY", "")
    cfg["base_url"] = os.environ.get("QUOTES_BASE_URL", "https://api.openai.com/v1")
    cfg["data_root_abs"] = (ROOT / cfg["data_root"]).resolve()
    cfg["db_path_abs"] = (ROOT / cfg["db_path"]).resolve()
    return cfg
```

- [ ] **Step 4: 运行验证通过**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quotes/app/config.py quotes/tests/test_config.py
git commit -m "feat: 配置加载（环境变量密钥、路径解析）"
```

---

### Task 2: 数据库层 db.py

**Files:**
- Create: `quotes/app/db.py`
- Test: `quotes/tests/test_db.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_db.py
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
        "email_date": None, "email_body": None, "processed_at": db.now(),
    })
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
```

- [ ] **Step 2: 运行验证失败**

Run: `python -m pytest tests/test_db.py -v`
Expected: FAIL，`AttributeError: module 'app.db' has no attribute 'connect'`

- [ ] **Step 3: 实现**

```python
# app/db.py
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
    conn.commit()
    return cur.fetchone()[0]

def existing_file(conn, path):
    return conn.execute(
        "SELECT id, content_hash FROM source_files WHERE path=?", (path,)).fetchone()

ITEM_COLUMNS = ["supplier", "category", "product_name", "spec", "brand", "model",
                "qty", "unit", "unit_price", "currency", "tax_included",
                "price_status", "quote_date", "terms", "source_location",
                "confidence", "needs_review"]

def insert_quote_items(conn, source_file_id: int, project_code: str, items: list) -> list:
    ids = []
    for it in items:
        tax = it.get("tax_included")
        tax = None if tax is None else int(bool(tax))
        cur = conn.execute(
            f"""INSERT INTO quote_items(source_file_id, project_code, {','.join(ITEM_COLUMNS)}, created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (source_file_id, project_code,
             *(it.get(c) for c in ITEM_COLUMNS[:-1]), tax,
             it.get("confidence", 1.0), int(bool(it.get("needs_review"))), now()))
        ids.append(cur.lastrowid)
    conn.commit()
    return ids

def delete_items_for_file(conn, source_file_id: int):
    conn.execute("DELETE FROM quote_items WHERE source_file_id=?", (source_file_id,))
    conn.commit()

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
```

- [ ] **Step 4: 运行验证通过**

Run: `python -m pytest tests/test_db.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add quotes/app/db.py quotes/tests/test_db.py
git commit -m "feat: SQLite 数据层（quote_items/source_files schema 与检索）"
```

---

### Task 3: 目录扫描 scanner.py

**Files:**
- Create: `quotes/app/ingestion/scanner.py`
- Test: `quotes/tests/test_scanner.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_scanner.py
from pathlib import Path
from app.ingestion import scanner

def test_scan_classifies_and_excludes(tmp_path):
    (tmp_path / "BAIC" / "7-axis").mkdir(parents=True)
    (tmp_path / "BAIC" / "7-axis" / "a.xlsx").write_bytes(b"x")
    (tmp_path / "BAIC" / "b.msg").write_bytes(b"y")
    (tmp_path / "Tesla" / "c.pdf").write_bytes(b"z")
    (tmp_path / "quotes" / "code.py").write_bytes(b"n")     # 排除目录
    (tmp_path / "BAIC" / "~$temp.xlsx").write_bytes(b"t")   # Office 临时文件
    (tmp_path / "BAIC" / "d.zip").write_bytes(b"u")         # 不支持类型
    recs = scanner.scan_directory(tmp_path)
    types = {(r.project_code, r.file_type) for r in recs}
    assert ("BAIC", ".xlsx") in types and ("BAIC", ".msg") in types and ("Tesla", ".pdf") in types
    assert all("quotes" not in r.path for r in recs)
    assert all(not Path(r.path).name.startswith("~$") for r in recs)
    assert all(r.content_hash for r in recs)
```

- [ ] **Step 2: 运行验证失败**

Run: `python -m pytest tests/test_scanner.py -v`
Expected: FAIL，`ModuleNotFoundError`/`AttributeError`

- [ ] **Step 3: 实现**

```python
# app/ingestion/scanner.py
"""扫描数据目录：分类文件类型、计算内容哈希（幂等依据）、按顶层目录得项目代号。"""
import hashlib
from dataclasses import dataclass
from pathlib import Path

SUPPORTED = {".msg", ".xlsx", ".pdf", ".png", ".jpg", ".jpeg", ".doc", ".pptx"}
EXCLUDE_DIRS = {"quotes", "docs", "__pycache__", ".git", ".trae", "attachments"}

@dataclass
class FileRecord:
    path: str
    file_type: str
    project_code: str
    content_hash: str

def file_hash(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def scan_directory(root) -> list:
    root = Path(root)
    out = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        if p.name.startswith("~$") or p.name.startswith("."):
            continue
        if p.suffix.lower() not in SUPPORTED:
            continue
        project = rel.parts[0] if len(rel.parts) > 1 else "_root"
        out.append(FileRecord(str(p), p.suffix.lower(), project, file_hash(p)))
    return out
```

- [ ] **Step 4: 运行验证通过**

Run: `python -m pytest tests/test_scanner.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quotes/app/ingestion/scanner.py quotes/tests/test_scanner.py
git commit -m "feat: 目录扫描与内容哈希"
```

---

### Task 4: Excel 解析 xlsx_parser.py

**Files:**
- Create: `quotes/app/ingestion/xlsx_parser.py`
- Test: `quotes/tests/test_xlsx_parser.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_xlsx_parser.py
import openpyxl
from app.ingestion.xlsx_parser import parse_xlsx

def test_parse_serializes_all_sheets(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "报价"
    ws.append(["设备", "数量", "单价"])
    ws.append(["七轴", 2, 47900.0])
    ws2 = wb.create_sheet("空表")
    ws2.append([None, None])
    f = tmp_path / "q.xlsx"
    wb.save(f)
    sheets = parse_xlsx(f)
    assert len(sheets) == 1                     # 全空 sheet 丢弃
    assert sheets[0].name == "报价"
    assert sheets[0].rows[0] == ["设备", "数量", "单价"]
    assert sheets[0].rows[1] == ["七轴", "2", "47900"]  # 数字字符串化、整数去 .0
```

- [ ] **Step 2: 运行验证失败**

Run: `python -m pytest tests/test_xlsx_parser.py -v`
Expected: FAIL，ModuleNotFoundError

- [ ] **Step 3: 实现**

```python
# app/ingestion/xlsx_parser.py
"""Excel 全 sheet 序列化为文本（结构判断交给 LLM 抽取）。"""
from dataclasses import dataclass
import openpyxl

@dataclass
class SheetData:
    name: str
    rows: list

def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v)

def parse_xlsx(path, max_rows=400, max_cols=40) -> list:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheets = []
    for ws in wb.worksheets:
        rows = [[_cell(c) for c in row[:max_cols]]
                for row in ws.iter_rows(max_row=max_rows, max_col=max_cols, values_only=True)]
        rows = [r for r in rows if any(str(x).strip() for x in r)]
        if rows:
            sheets.append(SheetData(ws.title, rows))
    wb.close()
    return sheets
```

- [ ] **Step 4: 运行验证通过**

Run: `python -m pytest tests/test_xlsx_parser.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quotes/app/ingestion/xlsx_parser.py quotes/tests/test_xlsx_parser.py
git commit -m "feat: Excel 报价单序列化解析"
```

---

### Task 5: PDF 解析 pdf_parser.py

**Files:**
- Create: `quotes/app/ingestion/pdf_parser.py`
- Test: `quotes/tests/test_pdf_parser.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_pdf_parser.py
import fitz
from app.ingestion.pdf_parser import parse_pdf, render_pages_to_png

def _make_pdf(path, text):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()

def test_text_pdf_no_vision(tmp_path):
    f = tmp_path / "a.pdf"
    _make_pdf(f, "Robot 7-axis price 47900 CNY unit qty total breakdown list")
    pdf = parse_pdf(f)
    assert pdf.needs_vision is False
    assert "47900" in pdf.pages[0]

def test_empty_pdf_needs_vision(tmp_path):
    f = tmp_path / "b.pdf"
    doc = fitz.open(); doc.new_page(); doc.save(f); doc.close()
    assert parse_pdf(f).needs_vision is True

def test_render_pages(tmp_path):
    f = tmp_path / "c.pdf"
    _make_pdf(f, "hello world page")
    imgs = render_pages_to_png(f, tmp_path / "out")
    assert len(imgs) == 1 and imgs[0].exists()
```

- [ ] **Step 2: 运行验证失败**

Run: `python -m pytest tests/test_pdf_parser.py -v`
Expected: FAIL，ModuleNotFoundError

- [ ] **Step 3: 实现**

```python
# app/ingestion/pdf_parser.py
"""PDF 文本层提取；无文本层（扫描版）转图片走视觉模型。"""
from dataclasses import dataclass
from pathlib import Path
import fitz

@dataclass
class PdfContent:
    pages: list
    needs_vision: bool

def parse_pdf(path, min_chars_per_page=20) -> PdfContent:
    doc = fitz.open(path)
    pages = [page.get_text() for page in doc]
    doc.close()
    needs = (not pages) or sum(len(t) for t in pages) / len(pages) < min_chars_per_page
    return PdfContent(pages, needs)

def render_pages_to_png(path, out_dir, dpi=120) -> list:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(path)
    outs = []
    for i, page in enumerate(doc):
        f = out_dir / f"page_{i + 1}.png"
        page.get_pixmap(dpi=dpi).save(f)
        outs.append(f)
    doc.close()
    return outs
```

- [ ] **Step 4: 运行验证通过**

Run: `python -m pytest tests/test_pdf_parser.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add quotes/app/ingestion/pdf_parser.py quotes/tests/test_pdf_parser.py
git commit -m "feat: PDF 文本/视觉双路解析"
```

---

### Task 6: 邮件解析 msg_parser.py

**Files:**
- Create: `quotes/app/ingestion/msg_parser.py`
- Test: `quotes/tests/test_msg_parser.py`

- [ ] **Step 1: 写失败测试（monkeypatch 伪造 extract_msg 返回）**

```python
# tests/test_msg_parser.py
from datetime import datetime, timezone
from app.ingestion import msg_parser

class _Att:
    def __init__(self, name, data):
        self.longFilename = name
        self.data = data

class _Msg:
    subject = "回复: 北汽项目询价-七轴"
    sender = "Ding <ding@fanuc.com>"
    date = datetime(2026, 9, 7, 10, 29, tzinfo=timezone.utc)
    body = "价格为电汇价格，承兑需重新议价"
    attachments = [_Att("报价单.xlsx", b"\xd0\xcf")]

def test_parse_msg_extracts_and_saves_attachments(tmp_path, monkeypatch):
    monkeypatch.setattr(msg_parser.extract_msg, "openMsg", lambda p: _Msg())
    em = msg_parser.parse_msg(tmp_path / "a.msg", tmp_path / "att")
    assert em.subject.startswith("回复")
    assert em.date.startswith("2026-09-07")
    assert "电汇" in em.body
    assert em.attachments[0].name == "报价单.xlsx"
    assert em.attachments[0].path.endswith("报价单.xlsx")

def test_parse_error_wrapped(tmp_path, monkeypatch):
    def boom(p):
        raise ValueError("bad file")
    monkeypatch.setattr(msg_parser.extract_msg, "openMsg", boom)
    try:
        msg_parser.parse_msg(tmp_path / "bad.msg", tmp_path / "att")
        assert False, "应当抛出 ParseError"
    except msg_parser.ParseError:
        pass
```

- [ ] **Step 2: 运行验证失败**

Run: `python -m pytest tests/test_msg_parser.py -v`
Expected: FAIL，ModuleNotFoundError

- [ ] **Step 3: 实现**

```python
# app/ingestion/msg_parser.py
"""解析 Outlook .msg：元数据、正文（商务条款来源）、附件落盘。"""
from dataclasses import dataclass
from pathlib import Path
import extract_msg

@dataclass
class Attachment:
    name: str
    path: str

@dataclass
class EmailContent:
    subject: str
    sender: str
    date: str
    body: str
    attachments: list

class ParseError(Exception):
    pass

def parse_msg(path, workdir) -> EmailContent:
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        m = extract_msg.openMsg(path)
        atts = []
        for a in m.attachments:
            name = a.longFilename or "attachment.bin"
            if not a.data:
                continue
            f = workdir / name
            f.write_bytes(a.data)
            atts.append(Attachment(name, str(f)))
        date = m.date.isoformat() if m.date else ""
        return EmailContent(m.subject or "", m.sender or "", date, m.body or "", atts)
    except Exception as e:
        raise ParseError(f"解析邮件失败 {path}: {e}") from e
```

- [ ] **Step 4: 运行验证通过**

Run: `python -m pytest tests/test_msg_parser.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add quotes/app/ingestion/msg_parser.py quotes/tests/test_msg_parser.py
git commit -m "feat: .msg 邮件解析（正文条款+附件落盘）"
```

---

### Task 7: LLM 客户端 llm_client.py（含测试用 Fake）

**Files:**
- Create: `quotes/app/ingestion/llm_client.py`
- Test: `quotes/tests/test_llm_client.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_llm_client.py
import pytest
from app.ingestion.llm_client import FakeLLMClient, LLMError, parse_json_loose

def test_parse_json_loose_strips_fences():
    assert parse_json_loose('```json\n{"a":1}\n```') == {"a": 1}
    assert parse_json_loose('{"b": 2}') == {"b": 2}

def test_fake_chat_json_and_chat():
    fake = FakeLLMClient(chat_responses=[{"items": []}, "纯文本回答"])
    assert fake.chat_json("s", "u") == {"items": []}
    assert fake.chat("s", "u") == "纯文本回答"

def test_fake_raises_when_exhausted():
    fake = FakeLLMClient(chat_responses=[])
    with pytest.raises(LLMError):
        fake.chat_json("s", "u")
```

- [ ] **Step 2: 运行验证失败**

Run: `python -m pytest tests/test_llm_client.py -v`
Expected: FAIL，ModuleNotFoundError

- [ ] **Step 3: 实现**

```python
# app/ingestion/llm_client.py
"""OpenAI 兼容 LLM 客户端（文本/视觉/embedding）+ 测试用 Fake。密钥来自环境变量。"""
import base64
import json
import re
from pathlib import Path

class LLMError(Exception):
    pass

def parse_json_loose(text: str) -> dict:
    t = text.strip()
    if t.startswith("```"):
        parts = re.split(r"```", t)
        t = parts[1] if len(parts) > 1 else t
        if t.startswith("json"):
            t = t[4:]
    return json.loads(t.strip())

class LLMClient:
    def __init__(self, cfg: dict):
        if not cfg.get("api_key"):
            raise LLMError("缺少环境变量 QUOTES_API_KEY")
        from openai import OpenAI
        self.client = OpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"])
        self.text_model = cfg["text_model"]
        self.vision_model = cfg["vision_model"]
        self.embed_model = cfg["embed_model"]

    def chat(self, system: str, user: str, images=None) -> str:
        content = [{"type": "text", "text": user}]
        for img in images or []:
            b64 = base64.b64encode(Path(img).read_bytes()).decode()
            content.append({"type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64}"}})
        model = self.vision_model if images else self.text_model
        resp = self.client.chat.completions.create(
            model=model, temperature=0,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": content}])
        return resp.choices[0].message.content

    def chat_json(self, system: str, user: str, images=None) -> dict:
        return parse_json_loose(self.chat(system, user, images))

    def embed(self, texts) -> list:
        resp = self.client.embeddings.create(model=self.embed_model, input=list(texts))
        return [d.embedding for d in resp.data]

class FakeLLMClient:
    """测试替身：按顺序弹出预设响应；Exception 实例则抛出。"""
    def __init__(self, chat_responses=(), embed_responses=()):
        self.chat_responses = list(chat_responses)
        self.embed_responses = list(embed_responses)

    def _pop(self):
        if not self.chat_responses:
            raise LLMError("FakeLLM: 预设响应已耗尽")
        r = self.chat_responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    def chat(self, system, user, images=None):
        return str(self._pop())

    def chat_json(self, system, user, images=None):
        r = self._pop()
        if not isinstance(r, dict):
            raise LLMError("FakeLLM: 该响应不是 dict")
        return r

    def embed(self, texts):
        if not self.embed_responses:
            raise LLMError("FakeLLM: 预设向量已耗尽")
        vs = self.embed_responses.pop(0)
        return [vs[i % len(vs)] for i in range(len(texts))]
```

- [ ] **Step 4: 运行验证通过**

Run: `python -m pytest tests/test_llm_client.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add quotes/app/ingestion/llm_client.py quotes/tests/test_llm_client.py
git commit -m "feat: LLM 客户端与测试替身"
```

---

### Task 8: 归一化与校验 normalize.py

**Files:**
- Create: `quotes/app/ingestion/normalize.py`
- Test: `quotes/tests/test_normalize.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_normalize.py
from app.ingestion.normalize import (normalize_price_status, clean_number,
                                     normalize_supplier, validate_item,
                                     cross_check_totals, SEED_CATEGORIES)

def test_price_status():
    assert normalize_price_status("成交价") == "成交价"
    assert normalize_price_status(None) == "未标注"
    assert normalize_price_status("历史") == "历史报价"
    assert normalize_price_status("随便") == "未标注"

def test_clean_number():
    assert clean_number("￥47,900元") == 47900.0
    assert clean_number(2) == 2.0
    assert clean_number("") is None
    assert clean_number("N/A") is None

def test_supplier_alias():
    assert normalize_supplier("盛允科技", ["上海盛允"]) is not None  # 无包含关系返回原名
    assert normalize_supplier("盛允", ["上海盛允机械(盛允)"]) == "上海盛允机械(盛允)"

def test_validate_item_flags_missing_currency():
    item, warnings = validate_item({"supplier": "KUKA", "category": "7-Axis",
        "product_name": "七轴", "spec": "5m", "qty": "2", "unit_price": "111,375",
        "currency": None, "tax_included": None, "price_status": "成交价"})
    assert item["unit_price"] == 111375.0 and item["qty"] == 2.0
    assert item["needs_review"] is True          # 有价格但币种/含税未识别
    assert any("币种" in w or "含税" in w for w in warnings)

def test_validate_item_clean():
    item, warnings = validate_item({"supplier": "KUKA", "category": "7-Axis",
        "product_name": "七轴", "spec": "5m", "qty": 1, "unit_price": 100.0,
        "currency": "cny", "tax_included": True, "price_status": "成交价"})
    assert item["currency"] == "CNY" and item["tax_included"] is True
    assert item["needs_review"] is False

def test_cross_check():
    items = [{"qty": 2, "unit_price": 100.0}, {"qty": 1, "unit_price": 50.0}]
    assert cross_check_totals(items, 250.0) == []                  # 偏差 0
    assert cross_check_totals(items, 300.0, tol=0.05)              # 偏差 20% -> 警告
    assert cross_check_totals(items, None) == []

def test_seed_categories():
    assert "7-Axis" in SEED_CATEGORIES and len(SEED_CATEGORIES) >= 15
```

- [ ] **Step 2: 运行验证失败**

Run: `python -m pytest tests/test_normalize.py -v`
Expected: FAIL，ModuleNotFoundError

- [ ] **Step 3: 实现**

```python
# app/ingestion/normalize.py
"""抽取结果归一化：数字/状态/供应商清洗，字段校验与小计交叉核对。"""
import re

SEED_CATEGORIES = [
    "7-Axis", "AGV", "Air Chuck", "APC Conveyor", "Arc Welding", "Deburring",
    "EMS", "Exhaust 除尘", "Hemming 滚边", "Hoist 吊具", "Laser 激光",
    "Marking 打码", "NC Locator", "PE Stamp", "Robot 机器人", "Roller bed 滚床",
    "Room 房体", "Sealing 涂胶", "Tip Dresser 修磨器", "Tool Changer 换枪盘",
    "Vision 视觉", "Welding Gun 焊枪",
]

PRICE_STATUS_MAP = [
    ("成交", "成交价"), ("本次报价", "本次报价"), ("历史报价", "历史报价"),
    ("历史", "历史报价"), ("预估", "预估价"), ("报价", "本次报价"),
]

def normalize_price_status(raw):
    if not raw:
        return "未标注"
    s = str(raw)
    for key, val in PRICE_STATUS_MAP:
        if key in s:
            return val
    return "未标注"

def clean_number(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").replace("，", "")
    s = re.sub(r"[￥¥$]|元|RMB", "", s).strip()
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group()) if m else None

def normalize_supplier(name, known_suppliers):
    if not name:
        return None
    strip = lambda s: re.sub(r"[（(].*?[)）]|\s+", "", str(s))
    n = strip(name)
    if not n:
        return str(name).strip()
    for k in known_suppliers:
        k2 = strip(k)
        if k2 and (n in k2 or k2 in n):
            return k
    return str(name).strip()

def _clean_tax(v):
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return v
    s = str(v)
    if s.lower() in ("true", "1", "含税", "含税价", "13%", "是"):
        return True
    if s.lower() in ("false", "0", "未税", "不含税", "否"):
        return False
    return None

def validate_item(item: dict):
    """清洗单条抽取记录；返回 (clean_item, warnings)。"""
    warnings = []
    price = clean_number(item.get("unit_price"))
    qty = clean_number(item.get("qty"))
    currency = (str(item["currency"]).strip().upper()
                if item.get("currency") else None)
    tax = _clean_tax(item.get("tax_included"))
    status = normalize_price_status(item.get("price_status"))
    needs_review = False
    if price is not None:
        if currency is None:
            needs_review, _ = True, warnings.append("缺少币种")
        if tax is None:
            needs_review = True
            warnings.append("未识别含税/未税")
    if not (item.get("product_name") or item.get("spec")):
        needs_review = True
        warnings.append("缺设备名与规格")
    clean = {
        "supplier": item.get("supplier"), "category": item.get("category"),
        "product_name": item.get("product_name"), "spec": item.get("spec"),
        "brand": item.get("brand"), "model": item.get("model"),
        "qty": qty, "unit": item.get("unit"),
        "unit_price": price, "currency": currency, "tax_included": tax,
        "price_status": status, "quote_date": item.get("quote_date"),
        "terms": item.get("terms"), "source_location": item.get("source_location"),
        "needs_review": needs_review,
    }
    return clean, warnings

def cross_check_totals(items, total_value, tol=0.05):
    """数量×单价 之和 与报价单合计交叉核对（无合计值时跳过）。"""
    if total_value is None:
        return []
    calc = sum((i.get("qty") or 0) * (i.get("unit_price") or 0) for i in items)
    if calc <= 0 or not items:
        return []
    if abs(calc - float(total_value)) / float(total_value) > tol:
        return [f"小计交叉核对不符: 计算值{calc:.0f} vs 合计{total_value}"]
    return []
```

- [ ] **Step 4: 运行验证通过**

Run: `python -m pytest tests/test_normalize.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add quotes/app/ingestion/normalize.py quotes/tests/test_normalize.py
git commit -m "feat: 抽取结果归一化与校验规则"
```

---

### Task 9: LLM 抽取器 extractor.py

**Files:**
- Create: `quotes/app/ingestion/extractor.py`
- Test: `quotes/tests/test_extractor.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_extractor.py
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
```

- [ ] **Step 2: 运行验证失败**

Run: `python -m pytest tests/test_extractor.py -v`
Expected: FAIL，ModuleNotFoundError

- [ ] **Step 3: 实现**

```python
# app/ingestion/extractor.py
"""LLM 结构化抽取：任意格式内容 → 统一 quote_items 记录（含重试）。"""
import json
from .llm_client import LLMError, parse_json_loose
from .normalize import validate_item

SYSTEM_EXTRACT = """你是采购报价数据抽取助手，从汽车焊装线设备询价/报价内容中抽取每一条报价明细。
只输出 JSON，不要任何解释。格式：
{"items":[
  {"supplier":"供应商","category":"品类","product_name":"设备名称","spec":"规格/配置描述",
   "brand":"品牌","model":"型号","qty":数字或null,"unit":"台/套/m/条等",
   "unit_price":数字或null,"currency":"CNY或USD","tax_included":true/false/null,
   "price_status":"成交价/本次报价/历史报价/预估价/未标注","quote_date":"YYYY-MM-DD或null",
   "terms":"付款/交付等商务条款","source_location":"来源位置，如 Sheet名!R行号 或 第N页"}],
 "email_terms":"邮件正文中的商务条款汇总，无则null",
 "supplier_name":"本文件/邮件所属供应商，判断不出则null"}
规则：
1. 价格一律转纯数字（去掉货币符号、千分位）；百分比、编号不是价格。
2. 汇总行/合计行/设计费管理费等非设备行也要抽取（product_name 写明"机械设计费"等），便于总价核对。
3. 拿不准的字段填 null，禁止编造；币种看文件是否注明未税/含税与人民币/美元。
4. 品类从"已知品类"列表中选最接近的，都不符合才自拟中英双语名。
5. 同一文件多 Sheet/多页都要覆盖，不要遗漏。"""

def extract_from_payload(client, file_label, payload_text, images=None,
                         known_categories=(), known_suppliers=()):
    hint = (f"已知品类：{','.join(known_categories) or '无'}\n"
            f"已知供应商：{','.join(known_suppliers) or '无'}\n\n"
            f"文件：{file_label}\n内容：\n{payload_text}")
    last_err = None
    for _ in range(3):  # 初次 + 2 次重试
        try:
            data = client.chat_json(SYSTEM_EXTRACT, hint, images=images)
            items = [validate_item(it)[0] for it in (data.get("items") or [])]
            return {"items": items,
                    "email_terms": data.get("email_terms"),
                    "supplier_name": data.get("supplier_name")}
        except (json.JSONDecodeError, LLMError, KeyError, TypeError) as e:
            last_err = e
            hint = f"{hint}\n\n[上次输出无法解析: {e}。请严格只输出一个合法 JSON 对象。]"
    raise LLMError(f"抽取失败 {file_label}: {last_err}")
```

- [ ] **Step 4: 运行验证通过**

Run: `python -m pytest tests/test_extractor.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add quotes/app/ingestion/extractor.py quotes/tests/test_extractor.py
git commit -m "feat: LLM 结构化抽取器（重试+清洗）"
```

---

### Task 10: 建库管道编排 pipeline.py

**Files:**
- Create: `quotes/app/ingestion/pipeline.py`
- Test: `quotes/tests/test_pipeline.py`

- [ ] **Step 1: 写失败测试（用临时目录 + FakeLLM 端到端跑通）**

```python
# tests/test_pipeline.py
import openpyxl
from app import db
from app.ingestion import pipeline
from app.ingestion.llm_client import FakeLLMClient

XLSX_REPLY = {"items": [
    {"supplier": "冠宇", "category": "Roller bed 滚床", "product_name": "高速固定滚床",
     "spec": None, "qty": 9, "unit_price": 30375, "currency": "CNY",
     "tax_included": False, "price_status": "成交价", "terms": None}],
    "email_terms": None, "supplier_name": "江苏冠宇"}

MSG_BODY_REPLY = {"items": [], "email_terms": "价格为电汇价格，承兑需重新议价",
                  "supplier_name": "FANUC"}

def _make_data(tmp_path):
    d = tmp_path / "BAIC" / "Roller bed"
    d.mkdir(parents=True)
    wb = openpyxl.Workbook(); wb.active.append(["设备", "数量", "单价"])
    wb.active.append(["高速固定滚床", 9, 30375]); wb.save(d / "冠宇报价.xlsx")
    return d

def test_pipeline_ingests_and_is_idempotent(tmp_path, monkeypatch):
    d = _make_data(tmp_path)
    # 邮件附件名与数据文件同名 -> 条款应关联到该报价文件
    class _Msg:
        subject = "回复: 询价-滚床"; sender = "a@b.c"
        date = "2026-09-04T00:00:00+00:00"; body = "正文"
        attachments = []
    monkeypatch.setattr(pipeline.msg_parser.extract_msg, "openMsg", lambda p: _Msg())
    (d.parent / "回复-滚床.msg").write_bytes(b"m")
    att_map = {("冠宇报价.xlsx").lower(): pipeline.msg_parser.EmailContent(
        "回复: 询价-滚床", "a@b.c", "2026-09-04", "电汇价", [])}
    monkeypatch.setattr(pipeline, "build_email_map", lambda recs, tmp: (att_map, {}))

    conn = db.connect(":memory:")
    # 文件按路径排序：xlsx(Roller bed 目录)先于 .msg(中文名)，Fake 响应按此顺序
    fake = FakeLLMClient(chat_responses=[XLSX_REPLY, MSG_BODY_REPLY])
    report = pipeline.run_ingestion(tmp_path, conn, fake, tmp_path / "review.csv")
    assert db.count_items(conn) == 1
    row = db.search_items(conn)[0]
    assert row["terms"] == "电汇价"                    # 邮件条款已关联
    sf = conn.execute("SELECT email_subject FROM source_files WHERE path LIKE '%冠宇%'").fetchone()
    assert sf["email_subject"] == "回复: 询价-滚床"    # 附件文件带邮件元数据

    # 幂等：哈希未变 -> 不再调用 LLM、不重复入库
    fake2 = FakeLLMClient(chat_responses=[])
    pipeline.run_ingestion(tmp_path, conn, fake2, tmp_path / "review2.csv")
    assert db.count_items(conn) == 1
    assert (tmp_path / "review.csv").exists()
```

- [ ] **Step 2: 运行验证失败**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: FAIL，ModuleNotFoundError

- [ ] **Step 3: 实现**

```python
# app/ingestion/pipeline.py
"""建库管道编排：扫描→解析→抽取→关联邮件条款→入库（幂等/断点续跑/复核报告）。"""
import argparse
import csv
import tempfile
from pathlib import Path

from .. import db
from ..config import load_config
from . import msg_parser, pdf_parser, scanner, xlsx_parser
from .extractor import extract_from_payload
from .llm_client import LLMClient, LLMError
from .normalize import SEED_CATEGORIES, normalize_supplier

SKIP_TYPES = {".doc", ".pptx"}  # v1 暂不支持，进报告提示人工处理

def build_payload(rec, tmpdir):
    """按类型构造 (payload_text, images)。"""
    if rec.file_type == ".xlsx":
        sheets = xlsx_parser.parse_xlsx(rec.path)
        text = "\n\n".join(
            f"## Sheet {s.name}\n" + "\n".join(" | ".join(r) for r in s.rows)
            for s in sheets)
        return text, None
    if rec.file_type == ".pdf":
        pdf = pdf_parser.parse_pdf(rec.path)
        if not pdf.needs_vision:
            return "\n\n".join(f"## 第{i+1}页\n{t}" for i, t in enumerate(pdf.pages)), None
        imgs = pdf_parser.render_pages_to_png(rec.path, Path(tmpdir) / "pdf_pages")
        return "这是一份报价单 PDF，请从图片中完整抽取报价明细。", imgs
    if rec.file_type in (".png", ".jpg", ".jpeg"):
        return "这是一张报价/价格截图，请抽取其中全部价格信息。", [rec.path]
    raise ValueError(f"unsupported {rec.file_type}")

def build_email_map(records, tmpdir):
    """解析全部 .msg：返回 (附件名小写->EmailContent, 邮件路径->EmailContent)。"""
    att_map, meta_map = {}, {}
    for rec in records:
        if rec.file_type != ".msg":
            continue
        try:
            em = msg_parser.parse_msg(rec.path, Path(tmpdir) / "emails" / Path(rec.path).stem)
        except msg_parser.ParseError:
            continue
        meta_map[rec.path] = em
        for a in em.attachments:
            att_map[a.name.lower()] = em
    return att_map, meta_map

def run_ingestion(root, conn, client, report_path, threshold=0.7):
    records = scanner.scan_directory(root)
    tmpdir = tempfile.mkdtemp(prefix="quotes_")
    att_map, meta_map = build_email_map(records, tmpdir)
    known_categories = [r[0] for r in conn.execute(
        "SELECT DISTINCT category FROM quote_items WHERE category IS NOT NULL")]
    known_categories = sorted(set(known_categories + SEED_CATEGORIES))
    known_suppliers = sorted({r["name"] for r in conn.execute("SELECT name FROM suppliers")})
    review_rows, failures, n_items = [], [], 0

    for rec in records:
        existing = db.existing_file(conn, rec.path)
        if existing and existing["content_hash"] == rec.content_hash:
            continue  # 幂等：未变化文件跳过
        if rec.file_type in SKIP_TYPES:
            review_rows.append([rec.path, "SKIP", "v1 暂不支持该格式，请人工处理"])
            continue
        try:
            if rec.file_type == ".msg":
                em = meta_map.get(rec.path) or msg_parser.parse_msg(
                    rec.path, Path(tmpdir) / "emails" / Path(rec.path).stem)
                payload = (f"邮件主题:{em.subject}\n发件人:{em.sender}\n"
                           f"日期:{em.date}\n正文:\n{em.body}")
                images = None
                email_meta = em
            else:
                payload, images = build_payload(rec, tmpdir)
                email_meta = att_map.get(Path(rec.path).name.lower())
            out = extract_from_payload(client, Path(rec.path).name, payload,
                                       images=images,
                                       known_categories=known_categories,
                                       known_suppliers=known_suppliers)
            items = out["items"]
            supplier_name = normalize_supplier(out["supplier_name"], known_suppliers) \
                if out["supplier_name"] else None
            email_terms = out["email_terms"] or (
                email_meta.body[:200] if email_meta else None)
            for it in items:
                if supplier_name and not it.get("supplier"):
                    it["supplier"] = supplier_name
                if email_terms and not it.get("terms"):
                    it["terms"] = email_terms
                it["confidence"] = 0.9 if not it.get("needs_review") else 0.5
                if it.get("confidence", 1) < threshold:
                    it["needs_review"] = True
            em_meta = email_meta
            sf_id = db.upsert_source_file(conn, {
                "path": rec.path, "content_hash": rec.content_hash,
                "file_type": rec.file_type, "project_code": rec.project_code,
                "email_subject": em_meta.subject if em_meta else None,
                "email_from": em_meta.sender if em_meta else None,
                "email_date": em_meta.date if em_meta else None,
                "email_body": (em_meta.body or None) if em_meta else None,
                "processed_at": db.now()})
            db.delete_items_for_file(conn, sf_id)
            db.insert_quote_items(conn, sf_id, rec.project_code, items)
            if supplier_name:
                conn.execute("INSERT OR IGNORE INTO suppliers(name) VALUES(?)",
                             (supplier_name,))
                conn.commit()
            for it in items:
                if it.get("needs_review"):
                    review_rows.append([rec.path, it.get("source_location", ""),
                                        f"{it.get('product_name','')} "
                                        f"{it.get('unit_price','')} 需复核"])
            n_items += len(items)
        except Exception as e:  # 断点续跑：失败记录后继续，不中断整体
            failures.append((rec.path, str(e)))
            review_rows.append([rec.path, "ERROR", str(e)[:200]])

    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["文件", "位置", "问题"])
        w.writerows(review_rows)
    print(f"处理完成：入库 {n_items} 条；复核 {len(review_rows)} 条；失败 {len(failures)} 个文件")
    for p, e in failures:
        print(f"  FAIL {p}: {e}")
    return report_path

def main():
    ap = argparse.ArgumentParser(description="报价数据建库管道")
    ap.add_argument("--root", default=None)
    ap.add_argument("--db", default=None)
    ap.add_argument("--report", default=None)
    args = ap.parse_args()
    cfg = load_config()
    root = args.root or cfg["data_root_abs"]
    db_path = args.db or cfg["db_path_abs"]
    report = args.report or (Path(db_path).parent / "review.csv")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = db.connect(db_path)
    client = LLMClient(cfg)
    run_ingestion(root, conn, client, report, threshold=cfg["confidence_threshold"])

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行验证通过**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: PASS（幂等断言同时验证 FakeLLMClient 空响应未被动用）

- [ ] **Step 5: 全量测试回归**

Run: `python -m pytest -v`
Expected: 全部通过

- [ ] **Step 6: Commit**

```bash
git add quotes/app/ingestion/pipeline.py quotes/tests/test_pipeline.py
git commit -m "feat: 建库管道（幂等、邮件条款关联、复核报告、断点续跑）"
```

---

### Task 11: 真实数据入库与抽样验收（人工检查点）

**Files:** 无新代码；产出 `quotes/data/quotes.db` 与 `quotes/data/review.csv`（均不入 git）。

- [ ] **Step 1: 设置环境变量并小样试跑（先跑通再全量）**

PowerShell（在 `d:\Projects\COMAU\quotes`）：

```powershell
$env:QUOTES_API_KEY="<你的key>"
$env:QUOTES_BASE_URL="<你的OpenAI兼容endpoint>"
python -m app.ingestion.pipeline --root "..\BAIC\Roller bed" --db data/test.db --report data/test_review.csv
```

Expected: 控制台输出入库条数；打开 `data/test.db`（DB Browser for SQLite 或 `python -c "from app import db; c=db.connect('data/test.db'); print(c.execute('SELECT product_name,unit_price,supplier,source_location FROM quote_items LIMIT 10').fetchall())"`）核对滚床报价与冠宇报价单一致。

- [ ] **Step 2: 全量入库**

```powershell
python -m app.ingestion.pipeline
```

Expected: 约 105 个文件处理完；打印入库总数（预计数百至上千条明细）。失败的文件会在控制台与 review.csv 列出。

- [ ] **Step 3: 抽样验收（设计文档第 10 节标准）**

从 `quote_items` 随机抽 30 条，人工打开溯源文件核对：
- 全字段准确率 ≥ 90%
- 价格 / 数量 / 供应商三关键字段 ≥ 95%

核对命令：

```powershell
python -c "from app import db; c=db.connect('data/quotes.db'); rows=c.execute('SELECT qi.id,qi.project_code,qi.supplier,qi.category,qi.product_name,qi.qty,qi.unit_price,qi.currency,qi.tax_included,qi.price_status,qi.source_location,sf.path FROM quote_items qi JOIN source_files sf ON sf.id=qi.source_file_id ORDER BY RANDOM() LIMIT 30').fetchall(); [print(tuple(r)) for r in rows]"
```

- [ ] **Step 4: 处理复核清单**

打开 `data/review.csv`，对 ERROR 行重跑（修复后直接重复 Step 2，幂等保证只处理变化文件）；对"需复核"行人工修正：直接在 DB Browser 中改库，或记录到 `data/manual_fixes.csv`（列：quote_item_id, 字段, 正确值）供后续脚本回写。

- [ ] **Step 5: 提交里程碑**

```bash
git add quotes
git commit -m "chore: 真实数据入库验收通过（数据文件不入库）" --allow-empty
```

---

## 验收标准（计划 A 完成 = 以下全部满足）

1. `python -m pytest` 全绿，覆盖率 ≥ 80%（`pip install pytest-cov; python -m pytest --cov=app --cov-report=term`）
2. `quotes/data/quotes.db` 含 BAIC 与 Tesla 两项目数据，每条 quote_item 可溯源到源文件+位置
3. 抽样 30 条：全字段 ≥90%、关键字段 ≥95% 准确
4. 重复运行管道不产生重复数据
