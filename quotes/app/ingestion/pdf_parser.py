"""PDF 文本层提取；无文本层（扫描版）标记 needs_vision，由管道渲染 PNG 走视觉模型。"""
from dataclasses import dataclass
from pathlib import Path
import pymupdf as fitz

@dataclass
class PdfContent:
    pages: list[str]
    needs_vision: bool

def parse_pdf(path: Path, min_chars_per_page: int = 20) -> PdfContent:
    """逐页提取文本层。任一判定为真则 needs_vision：无页面、
    或平均每页文本少于 min_chars_per_page 字符（视为扫描版）。"""
    doc = fitz.open(path)
    try:
        pages = [page.get_text() for page in doc]
    finally:
        doc.close()
    needs = (not pages) or sum(len(t) for t in pages) / len(pages) < min_chars_per_page
    return PdfContent(pages, needs)

def render_pages_to_png(path: Path, out_dir: Path, dpi: int = 120) -> list[Path]:
    """整本 PDF 每页渲染为 page_N.png（needs_vision 时供视觉模型用）。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(path)
    try:
        outs: list[Path] = []
        for i, page in enumerate(doc):
            f = out_dir / f"page_{i + 1}.png"
            page.get_pixmap(dpi=dpi).save(f)
            outs.append(f)
        return outs
    finally:
        doc.close()
