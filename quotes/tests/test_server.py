import io
import openpyxl
from fastapi.testclient import TestClient
from app import db
from app.web import server

def _client(monkeypatch, tmp_path):
    # 每个测试独立数据库连接，避免模块级缓存串库
    conn = db.connect(tmp_path / "test.db")
    server._CONN = conn
    monkeypatch.setattr(server, "get_conn", lambda: conn)
    return TestClient(server.app), conn

def _seed(conn):
    fid = conn.execute("""INSERT INTO source_files(path,content_hash,file_type,
        project_code,processed_at) VALUES('D:/a.xlsx','h','.xlsx','BAIC',?)
        RETURNING id""", (server.db.now(),)).fetchone()[0]
    conn.execute("""INSERT INTO quote_items(source_file_id,project_code,supplier,
        category,product_name,spec,brand,model,qty,unit,unit_price,currency,
        tax_included,price_status,quote_date,terms,source_location,confidence,
        needs_review,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (fid, "BAIC", "盛允", "7-Axis", "机器人七轴", "11.5m", "盛允", None, 1, "套",
         100.0, "CNY", 1, "成交价", "2026-09-01", None, "R2", 0.9, 0, server.db.now()))
    conn.commit()
    return fid

def test_chat_endpoint(monkeypatch, tmp_path):
    from app.ingestion.llm_client import FakeLLMClient
    tc, conn = _client(monkeypatch, tmp_path)
    _seed(conn)
    fake = FakeLLMClient(chat_responses=[
        {"categories": ["7-Axis"]}, "七轴成交价100元 [来源:a.xlsx R2]"])
    monkeypatch.setattr(server, "get_llm", lambda: fake)
    r = tc.post("/api/chat", json={"question": "七轴价格"})
    assert r.status_code == 200
    body = r.json()
    assert "100" in body["answer"] and body["matched_count"] == 1

def test_inquiry_upload_and_draft(monkeypatch, tmp_path):
    tc, conn = _client(monkeypatch, tmp_path)
    _seed(conn)
    from app.ingestion.llm_client import FakeLLMClient
    monkeypatch.setattr(server, "get_llm", lambda: FakeLLMClient())
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Inquiry table"
    ws.append(["Product", "Brand", "Qty"])
    ws.append(["7-Axis七轴 机器人七轴 11.5m", "盛允", 2])
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    r = tc.post("/api/inquiry/upload", files={"file": ("inq.xlsx", buf,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200
    data = r.json()
    assert data["results"][0]["tier"] == "精确匹配"
    r2 = tc.get(f"/api/inquiry/{data['batch_id']}/draft.xlsx")
    assert r2.status_code == 200 and len(r2.content) > 1000

def test_files_and_review_endpoints(monkeypatch, tmp_path):
    tc, conn = _client(monkeypatch, tmp_path)
    _seed(conn)
    assert tc.get("/api/files").status_code == 200
    assert tc.get("/api/review").status_code == 200
    meta = tc.get("/api/meta").json()
    assert "7-Axis" in meta["categories"] and "盛允" in meta["suppliers"]
    assert meta["category_stats"][0]["count"] >= 1


def test_static_assets(monkeypatch, tmp_path):
    tc, _ = _client(monkeypatch, tmp_path)
    assert tc.get("/").status_code == 200
    assert tc.get("/static/assets/logo-mark.png").status_code == 200
    assert tc.get("/favicon.ico").status_code == 200
