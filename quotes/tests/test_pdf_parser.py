import fitz
from app.ingestion.pdf_parser import parse_pdf, render_pages_to_png

def _make_pdf(path, text):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()

def test_text_pdf_no_vision(tmp_path):
    f = tmp_path / "a.pdf"
    _make_pdf(f, "Robot 7-axis price 47900 CNY unit qty total breakdown list")
    pdf = parse_pdf(f)
    assert pdf.needs_vision is False
    assert "47900" in pdf.pages[0]

def test_empty_pdf_needs_vision(tmp_path):
    f = tmp_path / "b.pdf"
    doc = fitz.open(); doc.new_page(); doc.save(f); doc.close()
    assert parse_pdf(f).needs_vision is True

def test_render_pages(tmp_path):
    f = tmp_path / "c.pdf"
    _make_pdf(f, "hello world page")
    imgs = render_pages_to_png(f, tmp_path / "out")
    assert len(imgs) == 1 and imgs[0].exists()
