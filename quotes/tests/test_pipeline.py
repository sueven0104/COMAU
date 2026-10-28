import openpyxl

from datetime import datetime, timezone

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
        # parse_msg 会调用 date.isoformat()，stub 须与真实 extract_msg 一致返回 datetime
        date = datetime(2026, 9, 4, tzinfo=timezone.utc)
        body = "正文"
        attachments = []
        def close(self): pass
    monkeypatch.setattr(pipeline.msg_parser.extract_msg, "openMsg", lambda p: _Msg())
    (d.parent / "回复-滚床.msg").write_bytes(b"m")
    att_map = {("冠宇报价.xlsx").lower(): pipeline.msg_parser.EmailContent(
        "回复: 询价-滚床", "a@b.c", "2026-09-04", "电汇价", [])}
    monkeypatch.setattr(pipeline, "build_email_map", lambda recs, tmp: (att_map, {}))

    conn = db.connect(":memory:")
    # 文件按路径排序：BAIC/Roller bed/冠宇报价.xlsx 先于 BAIC/回复-滚床.msg
    # （'R' U+0052 < '回' U+56DE），Fake 响应按此顺序
    fake = FakeLLMClient(chat_responses=[XLSX_REPLY, MSG_BODY_REPLY])
    report = pipeline.run_ingestion(tmp_path, conn, fake, tmp_path / "review.csv")
    assert db.count_items(conn) == 1
    row = db.search_items(conn)[0]
    assert row["terms"] == "电汇价"                    # 邮件条款已关联
    sf = conn.execute("SELECT email_subject FROM source_files WHERE path LIKE '%冠宇%'").fetchone()
    assert sf["email_subject"] == "回复: 询价-滚床"    # 附件文件带邮件元数据

    # 幂等：哈希未变 -> 不再调用 LLM、不重复入库。
    # 旧版仅靠 fake2 响应耗尽抛错保护，但异常会被管道 except 吞掉导致假绿；
    # 这里额外对 chat_json 计数，硬断言未变化文件不触发任何 LLM 调用。
    fake2 = FakeLLMClient(chat_responses=[])
    calls = []
    orig_chat = fake2.chat_json
    def _counting(*a, **k):
        calls.append(1)
        return orig_chat(*a, **k)
    fake2.chat_json = _counting
    pipeline.run_ingestion(tmp_path, conn, fake2, tmp_path / "review2.csv")
    assert db.count_items(conn) == 1
    assert not calls   # 未变化文件不得触发任何 LLM 调用
    assert (tmp_path / "review.csv").exists()
