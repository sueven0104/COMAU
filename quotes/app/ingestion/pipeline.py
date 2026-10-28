"""建库管道编排：扫描→解析→抽取→关联邮件条款→入库（幂等/断点续跑/复核报告）。"""
import argparse
import csv
import logging
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from .. import db
from ..config import load_config
from ..logsetup import setup_logging
from . import msg_parser, pdf_parser, scanner, xlsx_parser
from .extractor import extract_from_payload
from .llm_client import LLMClient
from .normalize import SEED_CATEGORIES, normalize_supplier

log = logging.getLogger(__name__)

SKIP_TYPES = {".doc", ".pptx"}  # v1 暂不支持，进报告提示人工处理
PAYLOAD_MAX_CHARS = 60_000      # 单文件 payload 上限：超限截断并记复核，防止超大表格拖垮 LLM

def build_payload(rec, tmpdir, max_rows=400):
    """按类型构造 (payload_text, images, truncated)。"""
    if rec.file_type == ".xlsx":
        sheets = xlsx_parser.parse_xlsx(rec.path, max_rows=max_rows)
        text = "\n\n".join(
            f"## Sheet {s.name}\n" + "\n".join(" | ".join(r) for r in s.rows)
            for s in sheets)
        return text, None, False
    if rec.file_type == ".pdf":
        pdf = pdf_parser.parse_pdf(rec.path)
        if not pdf.needs_vision:
            return "\n\n".join(f"## 第{i+1}页\n{t}" for i, t in enumerate(pdf.pages)), None, False
        imgs = pdf_parser.render_pages_to_png(rec.path, Path(tmpdir) / "pdf_pages")
        return "这是一份报价单 PDF，请从图片中完整抽取报价明细。", imgs, False
    if rec.file_type in (".png", ".jpg", ".jpeg"):
        return "这是一张报价/价格截图，请抽取其中全部价格信息。", [rec.path], False
    raise ValueError(f"unsupported {rec.file_type}")

def build_email_map(records, tmpdir):
    """解析全部 .msg：返回 (附件名小写->EmailContent, 邮件路径->EmailContent)。"""
    att_map, meta_map = {}, {}
    n_fail = 0
    for rec in records:
        if rec.file_type != ".msg":
            continue
        try:
            em = msg_parser.parse_msg(rec.path, Path(tmpdir) / "emails" / Path(rec.path).stem)
        except msg_parser.ParseError as e:
            log.warning("邮件解析失败，仅正文条款缺失：%s", e)
            n_fail += 1
            continue
        meta_map[rec.path] = em
        for a in em.attachments:
            att_map[a.name.lower()] = em
    log.info("邮件预解析完成：%d 封成功，%d 封失败，关联附件 %d 个",
             len(meta_map), n_fail, len(att_map))
    return att_map, meta_map

def run_ingestion(root, conn, client, report_path, threshold=0.7, workers=1,
                  payload_max_chars=PAYLOAD_MAX_CHARS, xlsx_max_rows=400):
    t_start = time.perf_counter()
    log.info("建库开始：root=%s workers=%d 阈值=%.2f payload上限=%d xlsx行上限=%d",
             root, workers, threshold, payload_max_chars, xlsx_max_rows)
    records, skipped = scanner.scan_directory(root)
    review_rows, failures, n_items = [], [], 0
    for p in skipped:  # 扫描期哈希失败的文件进报告，避免静默丢失
        review_rows.append([p, "SKIP", "无法读取文件（被占用？）"])

    def _extract_one(rec, work_idx):
        """工作线程：解析+抽取（无 DB 访问、无共享可变状态），返回结果 dict。"""
        name = Path(rec.path).name
        t0 = time.perf_counter()
        log.info("[%d] 开始处理 %s（%s）", work_idx, name, rec.file_type)
        try:
            if rec.file_type == ".msg":
                em = meta_map.get(rec.path) or msg_parser.parse_msg(
                    rec.path, Path(tmpdir) / "emails" / Path(rec.path).stem)
                payload = (f"邮件主题:{em.subject}\n发件人:{em.sender}\n"
                           f"日期:{em.date}\n正文:\n{em.body}")
                images = None
                email_meta = em
            else:
                # 每文件独立子目录，避免并行渲染 PDF 页图时同名覆盖
                payload, images, _ = build_payload(
                    rec, Path(tmpdir) / f"file_{work_idx}", max_rows=xlsx_max_rows)
                email_meta = att_map.get(Path(rec.path).name.lower())
            truncated = len(payload) > payload_max_chars
            if truncated:
                payload = payload[:payload_max_chars]
            out = extract_from_payload(client, Path(rec.path).name, payload,
                                       images=images,
                                       known_categories=known_categories,
                                       known_suppliers=known_suppliers)
            log.info("[%d] 完成 %s：抽取 %d 条，耗时 %.1fs%s",
                     work_idx, name, len(out["items"]), time.perf_counter() - t0,
                     "，关联邮件" if email_meta else "，未关联邮件")
            return {"rec": rec, "out": out, "email_meta": email_meta,
                    "truncated": truncated}
        except Exception as e:  # 断点续跑：单文件失败记录后继续，不中断整体
            log.error("[%d] 处理失败 %s（耗时 %.1fs）：%s",
                      work_idx, name, time.perf_counter() - t0, e)
            return {"rec": rec, "error": str(e)}

    with tempfile.TemporaryDirectory(prefix="quotes_") as tmpdir:
        att_map, meta_map = build_email_map(records, tmpdir)
        known_categories = [r[0] for r in conn.execute(
            "SELECT DISTINCT category FROM quote_items WHERE category IS NOT NULL")]
        known_categories = sorted(set(known_categories + SEED_CATEGORIES))
        known_suppliers = sorted({r["name"] for r in conn.execute("SELECT name FROM suppliers")})

        todo = []  # (rec, 序号)：需处理的文件
        n_unchanged = 0
        for rec in records:
            existing = db.existing_file(conn, rec.path)
            if existing and existing["content_hash"] == rec.content_hash:
                n_unchanged += 1  # 幂等：未变化文件跳过
                log.debug("内容未变化，跳过 %s", rec.path)
                continue
            if rec.file_type in SKIP_TYPES:
                review_rows.append([rec.path, "SKIP", "v1 暂不支持该格式，请人工处理"])
                log.info("暂不支持格式，跳过 %s", rec.path)
                continue
            todo.append((rec, len(todo) + 1))
        log.info("待处理 %d 个文件（未变化跳过 %d 个，不支持格式 %d 个）",
                 len(todo), n_unchanged,
                 sum(1 for r in review_rows if r[1] == "SKIP" and r[2].startswith("v1")))

        def _run_all():
            if workers <= 1:
                for rec, i in todo:
                    yield _extract_one(rec, i)
            else:
                with ThreadPoolExecutor(max_workers=workers) as ex:
                    futures = [ex.submit(_extract_one, rec, i) for rec, i in todo]
                    for f in futures:
                        yield f.result()

        for res in _run_all():
            rec = res["rec"]
            if "error" in res:
                failures.append((rec.path, res["error"]))
                review_rows.append([rec.path, "ERROR", res["error"][:200]])
                continue
            if res["truncated"]:
                review_rows.append([rec.path, "TRUNCATED",
                                    f"内容超 {payload_max_chars} 字符已截断，可能遗漏后半部分条目"])
                log.warning("内容超限已截断，可能遗漏条目：%s", rec.path)
            out = res["out"]
            email_meta = res["email_meta"]
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
            # upsert→delete→insert 单事务：中途失败整体回滚，避免新哈希已入库而条目为空
            with conn:
                sf_id = db.upsert_source_file(conn, {
                    "path": rec.path, "content_hash": rec.content_hash,
                    "file_type": rec.file_type, "project_code": rec.project_code,
                    "email_subject": email_meta.subject if email_meta else None,
                    "email_from": email_meta.sender if email_meta else None,
                    "email_date": email_meta.date if email_meta else None,
                    "email_body": (email_meta.body or None) if email_meta else None,
                    "processed_at": db.now()})
                db.delete_items_for_file(conn, sf_id)
                db.insert_quote_items(conn, sf_id, rec.project_code, items)
                if supplier_name:
                    conn.execute("INSERT OR IGNORE INTO suppliers(name) VALUES(?)",
                                 (supplier_name,))
            log.debug("入库 %s：文件 id=%d，条目 %d 条，供应商=%s",
                      rec.path, sf_id, len(items), supplier_name)
            if email_meta is None:  # 非 .msg 未关联到邮件，降级需可见
                review_rows.append([rec.path, "LINK", "未关联到任何邮件，条款缺失请人工核对"])
                log.info("未关联到任何邮件，条款缺失需人工核对：%s", rec.path)
            n_review_file = 0
            for it in items:
                if it.get("needs_review"):
                    reason = ("置信度低于阈值"
                              if it.get("confidence", 1) < threshold else "需复核")
                    review_rows.append([rec.path, it.get("source_location", ""),
                                        f"{it.get('product_name','')} "
                                        f"{it.get('unit_price','')} {reason}"])
                    n_review_file += 1
            if n_review_file:
                log.debug("%s 有 %d 条需复核", rec.path, n_review_file)
            n_items += len(items)

    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["文件", "位置", "问题"])
        w.writerows(review_rows)
    log.info("建库完成：入库 %d 条；复核 %d 条；失败 %d 个文件；耗时 %.1fs；"
             "复核报告 %s", n_items, len(review_rows), len(failures),
             time.perf_counter() - t_start, report_path)
    for p, e in failures:
        log.error("失败文件 %s：%s", p, e)
    return report_path

def main():
    ap = argparse.ArgumentParser(description="报价数据建库管道")
    ap.add_argument("--root", default=None)
    ap.add_argument("--db", default=None)
    ap.add_argument("--report", default=None)
    ap.add_argument("--workers", type=int, default=None,
                    help="并行抽取线程数（默认取 config 的 workers，缺省 1）")
    ap.add_argument("--payload-max", type=int, default=None,
                    help="单文件 payload 字符上限（默认 60000，超大表格可调小）")
    ap.add_argument("--xlsx-max-rows", type=int, default=None,
                    help="xlsx 每 sheet 最大行数（默认 400）")
    args = ap.parse_args()
    cfg = load_config()
    root = args.root or cfg["data_root_abs"]
    db_path = args.db or cfg["db_path_abs"]
    report = args.report or (Path(db_path).parent / "review.csv")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    # 长时间批量运行：默认落一份日志文件便于回溯（可用 QUOTES_LOG_FILE 覆盖）
    logfile = (Path(db_path).parent / "logs"
               / f"ingestion_{datetime.now():%Y%m%d_%H%M%S}.log")
    setup_logging(logfile=logfile)
    log.info("运行参数：root=%s db=%s report=%s workers=%s",
             root, db_path, report, args.workers or cfg.get("workers", 1))
    conn = db.connect(db_path)
    client = LLMClient(cfg)
    run_ingestion(root, conn, client, report,
                  threshold=cfg["confidence_threshold"],
                  workers=args.workers or cfg.get("workers", 1),
                  payload_max_chars=args.payload_max or PAYLOAD_MAX_CHARS,
                  xlsx_max_rows=args.xlsx_max_rows or 400)

if __name__ == "__main__":
    main()
