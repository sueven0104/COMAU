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
