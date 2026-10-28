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
