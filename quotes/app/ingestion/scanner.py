"""扫描数据目录：分类文件类型、计算内容哈希（幂等依据）、按顶层目录得项目代号。"""
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

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

def scan_directory(root) -> tuple[list[FileRecord], list[str]]:
    root = Path(root)
    records: list[FileRecord] = []
    skipped: list[str] = []
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
        # 哈希算不出（如 Excel/PDF 被占用抛 PermissionError）的文件后续也无法解析，
        # 跳过并记录，不中断整个扫描
        try:
            digest = file_hash(p)
        except OSError as e:
            log.warning("无法读取文件（被占用？），跳过：%s（%s）", p, e)
            skipped.append(str(p))
            continue
        project = rel.parts[0] if len(rel.parts) > 1 else "_root"
        records.append(FileRecord(str(p), p.suffix.lower(), project, digest))
    by_type: dict[str, int] = {}
    for r in records:
        by_type[r.file_type] = by_type.get(r.file_type, 0) + 1
    log.info("扫描 %s 完成：%d 个文件（%s），%d 个无法读取跳过",
             root, len(records),
             " ".join(f"{k}×{v}" for k, v in sorted(by_type.items())) or "空",
             len(skipped))
    return records, skipped
