"""本地 Web 服务：对话、清单上传匹配、草稿下载、数据管理。"""
import logging
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import db
from ..config import load_config
from ..ingestion.llm_client import LLMClient, LLMError
from ..logsetup import setup_logging
from ..relpath import resolve_relative, to_relative
from ..query import chat as chat_mod
from ..matching import inquiry as inquiry_mod, matcher as matcher_mod
from ..export import draft as draft_mod

logger = logging.getLogger(__name__)

app = FastAPI(title="AI 报价查询系统")
CFG = load_config()
setup_logging()
logger.info("服务初始化：db=%s text=%s vision=%s embed=%s",
            CFG["db_path_abs"], CFG["text_model"], CFG["vision_model"],
            CFG["embed_model"])

# 内存态：batch_id -> (lines, matches)
BATCHES = {}
_CONN = None

def get_conn():
    """懒加载正式库连接；测试通过 monkeypatch 替换并直接设置 _CONN。"""
    global _CONN
    if _CONN is None:
        Path(CFG["db_path_abs"]).parent.mkdir(parents=True, exist_ok=True)
        _CONN = db.connect(CFG["db_path_abs"])
        logger.info("数据库连接就绪：%s", CFG["db_path_abs"])
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
        logger.warning("对话请求被拒绝：问题为空")
        raise HTTPException(400, "问题不能为空")
    t0 = time.perf_counter()
    try:
        out = chat_mod.answer_question(get_conn(), get_llm(), body.question)
        # 溯源路径一律返回 raw_data 相对路径（库内存的是建库机的绝对路径）
        for c in out.get("citations", []):
            c["source_path"] = to_relative(c.get("source_path") or "")
        logger.info("对话接口完成：耗时 %.1fs，命中 %d 条",
                    time.perf_counter() - t0, out["matched_count"])
        return out
    except LLMError as exc:
        # 配置/鉴权类问题：直接告知原因，避免前端只看到 500
        logger.error("对话接口 LLM 错误：%s", exc)
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        logger.exception("对话处理失败")
        raise HTTPException(500, f"问答处理失败：{exc}") from exc

@app.post("/api/inquiry/upload")
async def api_inquiry_upload(file: UploadFile = File(...)):
    t0 = time.perf_counter()
    suffix = Path(file.filename or "").suffix.lower()
    if suffix != ".xlsx":
        logger.warning("清单上传被拒绝：%r 不是 .xlsx", file.filename)
        raise HTTPException(400, "只支持 .xlsx 询价清单")
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        f.write(await file.read())
        tmp = f.name
    lines = inquiry_mod.parse_inquiry_xlsx(tmp)
    if not lines:
        logger.warning("清单解析为空：%r（未识别到表头）", file.filename)
        raise HTTPException(422, "未识别到询价清单表头（需含 Product/Qty 等列）")
    try:
        matches = matcher_mod.match_batch(get_conn(), get_llm(), lines)
    except LLMError as exc:
        logger.error("清单匹配 LLM 错误：%s", exc)
        raise HTTPException(503, str(exc)) from exc
    batch_id = uuid4().hex
    BATCHES[batch_id] = (lines, matches)
    logger.info("清单上传完成：%r 共 %d 行，批次 %s…，耗时 %.1fs",
                file.filename, len(lines), batch_id[:8],
                time.perf_counter() - t0)
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
        logger.warning("草稿下载失败：批次 %s… 不存在或已过期", batch_id[:8])
        raise HTTPException(404, "批次不存在或已过期，请重新上传")
    lines, matches = BATCHES[batch_id]
    out = Path(tempfile.gettempdir()) / f"draft_{batch_id}.xlsx"
    draft_mod.export_draft(get_conn(), lines, matches, out,
                           data_root=CFG["data_root_abs"])
    logger.info("草稿已生成：批次 %s…，%d 行 -> %s", batch_id[:8], len(lines), out)
    return FileResponse(out, filename="报价建议草稿.xlsx")

@app.get("/api/source")
def api_source(path: str):
    """按相对路径返回 raw_data 内的源文件，浏览器可直接预览 PDF/图片。"""
    try:
        real = resolve_relative(path, CFG["data_root_abs"])
    except ValueError:
        logger.warning("源文件请求被拒绝（路径越界）：%r", path)
        raise HTTPException(400, "路径不合法")
    if not real.is_file():
        logger.warning("源文件不存在：%s", real)
        raise HTTPException(404, "文件不存在或已被移动")
    return FileResponse(real, filename=real.name, content_disposition_type="inline")

@app.get("/api/files")
def api_files():
    rows = get_conn().execute(
        """SELECT sf.path, sf.project_code, sf.file_type, sf.email_subject,
                  sf.email_date, COUNT(qi.id) AS item_count
           FROM source_files sf LEFT JOIN quote_items qi ON qi.source_file_id=sf.id
           GROUP BY sf.id ORDER BY sf.project_code, sf.path""").fetchall()
    logger.debug("文件列表查询：%d 个源文件", len(rows))
    files = []
    for r in rows:
        d = dict(r)
        d["path"] = to_relative(d["path"])
        files.append(d)
    return {"files": files}

@app.get("/api/review")
def api_review():
    rows = get_conn().execute(
        """SELECT qi.id, qi.product_name, qi.unit_price, qi.supplier,
                  qi.source_location, sf.path
           FROM quote_items qi JOIN source_files sf ON sf.id=qi.source_file_id
           WHERE qi.needs_review=1 LIMIT 500""").fetchall()
    logger.debug("复核列表查询：%d 条待复核", len(rows))
    review = []
    for r in rows:
        d = dict(r)
        d["path"] = to_relative(d["path"])
        review.append(d)
    return {"review": review}

@app.get("/api/meta")
def api_meta():
    conn = get_conn()
    cats = [r[0] for r in conn.execute(
        "SELECT DISTINCT category FROM quote_items WHERE category IS NOT NULL")]
    sups = [r[0] for r in conn.execute(
        "SELECT DISTINCT supplier FROM quote_items WHERE supplier IS NOT NULL")]
    projs = [r[0] for r in conn.execute(
        "SELECT DISTINCT project_code FROM quote_items")]
    cat_stats = [{"name": r[0], "count": r[1]} for r in conn.execute(
        """SELECT category, COUNT(*) AS n FROM quote_items
           WHERE category IS NOT NULL GROUP BY category ORDER BY n DESC LIMIT 8""")]
    return {"categories": cats, "suppliers": sups, "projects": projs,
            "category_stats": cat_stats}


@app.get("/favicon.ico")
def favicon():
    return FileResponse(Path(__file__).parent / "static" / "assets" / "favicon.png")


app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"),
          name="static")

@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")
