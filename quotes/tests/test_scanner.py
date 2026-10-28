from pathlib import Path
from app.ingestion import scanner

def _put(p: Path, data: bytes):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)

def test_scan_classifies_and_excludes(tmp_path):
    _put(tmp_path / "BAIC" / "7-axis" / "a.xlsx", b"x")
    _put(tmp_path / "BAIC" / "b.msg", b"y")
    _put(tmp_path / "Tesla" / "c.pdf", b"x")     # 与 a.xlsx 同内容，验证哈希一致性
    _put(tmp_path / "quotes" / "notes.xlsx", b"n")  # 排除目录（后缀受支持，验证目录排除）
    _put(tmp_path / "BAIC" / "~$temp.xlsx", b"t")   # Office 临时文件
    _put(tmp_path / "BAIC" / "d.zip", b"u")         # 不支持类型
    recs, skipped = scanner.scan_directory(tmp_path)
    assert skipped == []
    assert len(recs) == 3                        # 只剩 a.xlsx/b.msg/c.pdf（排除 quotes、~$、zip）
    types = {(r.project_code, r.file_type) for r in recs}
    assert ("BAIC", ".xlsx") in types and ("BAIC", ".msg") in types and ("Tesla", ".pdf") in types
    assert all("quotes" not in r.path for r in recs)
    assert all(not Path(r.path).name.startswith("~$") for r in recs)
    assert all(r.content_hash for r in recs)
    # content_hash：同内容两文件哈希相同
    hashes = {Path(r.path).name: r.content_hash for r in recs}
    assert hashes["a.xlsx"] == hashes["c.pdf"]
    assert hashes["b.msg"] not in (hashes["a.xlsx"], hashes["c.pdf"])  # 不同内容哈希不同
    # 修改文件内容后重扫，哈希变化；未变文件哈希不变
    _put(tmp_path / "BAIC" / "b.msg", b"y-modified")
    recs2, _ = scanner.scan_directory(tmp_path)
    hashes2 = {Path(r.path).name: r.content_hash for r in recs2}
    assert hashes2["b.msg"] != hashes["b.msg"]
    assert hashes2["a.xlsx"] == hashes["a.xlsx"]

def test_scan_skips_locked_files(tmp_path, monkeypatch):
    (tmp_path / "BAIC").mkdir(parents=True)
    (tmp_path / "BAIC" / "a.xlsx").write_bytes(b"x")
    (tmp_path / "BAIC" / "b.msg").write_bytes(b"y")
    orig = scanner.file_hash
    def flaky(p):
        if p.name == "a.xlsx":
            raise PermissionError("locked by Excel")
        return orig(p)
    monkeypatch.setattr(scanner, "file_hash", flaky)
    recs, skipped = scanner.scan_directory(tmp_path)
    assert [Path(r.path).name for r in recs] == ["b.msg"]
    assert [Path(s).name for s in skipped] == ["a.xlsx"]
