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
        if any(part.lower() in EXCLUDE_DIRS for part in rel.parts):
            continue
        if p.name.startswith("~$") or p.name.startswith("."):
            continue
        if p.suffix.lower() not in SUPPORTED:
            continue
        project = rel.parts[0] if len(rel.parts) > 1 else "_root"
        out.append(FileRecord(str(p), p.suffix.lower(), project, file_hash(p)))
    return out
