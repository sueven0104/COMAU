"""解析 Outlook .msg：元数据、正文（商务条款来源）、附件落盘。"""
from dataclasses import dataclass
from pathlib import Path
import re

import extract_msg

@dataclass
class Attachment:
    name: str
    path: str

@dataclass
class EmailContent:
    subject: str
    sender: str
    date: str
    body: str
    attachments: list[Attachment]

class ParseError(Exception):
    pass

def _unique_path(workdir: Path, name: str, used: set[str]) -> Path:
    """同名附件去重命名：报价单.xlsx → 报价单_2.xlsx、报价单_3.xlsx…"""
    stem, suffix = Path(name).stem, Path(name).suffix
    candidate = workdir / name
    n = 2
    while name in used or candidate.exists():
        name = f"{stem}_{n}{suffix}"
        candidate = workdir / name
        n += 1
    used.add(name)
    return candidate

def parse_msg(path: Path, workdir: Path) -> EmailContent:
    """openMsg 到附件落盘整体纳入 try，任何异常统一包成 ParseError 向管道传播。"""
    workdir = Path(workdir)
    m = None
    try:
        workdir.mkdir(parents=True, exist_ok=True)
        m = extract_msg.openMsg(path)
        atts: list[Attachment] = []
        used: set[str] = set()
        for a in m.attachments:
            name = a.longFilename or "attachment.bin"
            if not a.data:
                continue
            name = Path(str(name).replace("/", "\\")).name      # 剥离路径分量，防路径穿越
            name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .") or "attachment.bin"
            f = _unique_path(workdir, name, used)
            f.write_bytes(a.data)
            atts.append(Attachment(f.name, str(f)))
        date = m.date.isoformat() if m.date else ""
        return EmailContent(m.subject or "", m.sender or "", date, m.body or "", atts)
    except Exception as e:
        raise ParseError(f"解析邮件失败 {path}: {e}") from e
    finally:
        if m is not None:
            m.close()
