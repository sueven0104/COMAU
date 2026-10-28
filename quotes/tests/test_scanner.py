from pathlib import Path
from app.ingestion import scanner

def _put(p: Path, data: bytes):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)

def test_scan_classifies_and_excludes(tmp_path):
    _put(tmp_path / "BAIC" / "7-axis" / "a.xlsx", b"x")
    _put(tmp_path / "BAIC" / "b.msg", b"y")
    _put(tmp_path / "Tesla" / "c.pdf", b"z")
    _put(tmp_path / "quotes" / "code.py", b"n")     # 排除目录
    _put(tmp_path / "BAIC" / "~$temp.xlsx", b"t")   # Office 临时文件
    _put(tmp_path / "BAIC" / "d.zip", b"u")         # 不支持类型
    recs = scanner.scan_directory(tmp_path)
    types = {(r.project_code, r.file_type) for r in recs}
    assert ("BAIC", ".xlsx") in types and ("BAIC", ".msg") in types and ("Tesla", ".pdf") in types
    assert all("quotes" not in r.path for r in recs)
    assert all(not Path(r.path).name.startswith("~$") for r in recs)
    assert all(r.content_hash for r in recs)
