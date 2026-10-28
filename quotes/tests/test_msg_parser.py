import pytest

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

    def close(self):  # 模拟 extract_msg.MSGFile.close
        pass

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
    with pytest.raises(msg_parser.ParseError, match="bad.msg"):
        msg_parser.parse_msg(tmp_path / "bad.msg", tmp_path / "att")

def test_attachment_name_sanitized(tmp_path, monkeypatch):
    class _Msg2(_Msg):
        subject = "s"; sender = "f"; date = None
        body = "b"
        attachments = [_Att("..\\..\\evil:x*.xlsx", b"data")]
    monkeypatch.setattr(msg_parser.extract_msg, "openMsg", lambda p: _Msg2())
    em = msg_parser.parse_msg(tmp_path / "a.msg", tmp_path / "att")
    a = em.attachments[0]
    # 名字被消毒：无路径分量、无非法字符
    assert "/" not in a.name and "\\" not in a.name
    assert not any(ch in a.name for ch in '<>:"|?*')
    assert (tmp_path / "att" / a.name).exists()   # 落盘在 workdir 内

def test_duplicate_attachment_names(tmp_path, monkeypatch):
    class _Msg3(_Msg):
        subject = "s"; sender = "f"; date = None
        body = "b"
        attachments = [_Att("quote.xlsx", b"d1"), _Att("quote.xlsx", b"d2")]
    monkeypatch.setattr(msg_parser.extract_msg, "openMsg", lambda p: _Msg3())
    em = msg_parser.parse_msg(tmp_path / "a.msg", tmp_path / "att")
    names = [a.name for a in em.attachments]
    assert names[0] == "quote.xlsx" and names[1] == "quote_2.xlsx"
