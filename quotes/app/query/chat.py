"""对话编排：意图解析 → SQL 检索 → 语义兜底 → 带溯源汇总。"""
from datetime import date
from . import retriever
from .embeddings import semantic_search

SYSTEM_INTENT = """把用户关于历史采购/报价的问题转成 JSON 查询条件。字段：
categories(品类列表), suppliers(供应商列表), projects(项目代号列表),
date_from, date_to("YYYY-MM-DD"或null), price_status("成交价/本次报价/历史报价/预估价"或null),
keyword(自由文本关键词或null), metrics(["count","min","max","median","table"]中若干)。
今天是{today}。只输出 JSON。

知识库当前可选值（用户口语词必须映射到其中最接近的标准值，
如"七轴"→"7-Axis"、"涂胶"→"Sealing 涂胶"、"BE22/BE13"→清单内对应项目；
映射不上则该字段置 null，并把原词放进 keyword）：
{vocab}"""

SYSTEM_ANSWER = """你是采购报价分析助手。仅基于"检索结果"回答用户问题，禁止编造数据。
每个价格后必须以[来源:文件名 位置]形式标注溯源；数据不足时明确说明库中无对应数据；
适当给出数量、最低/中位/最高价等统计；回答末尾提示"建议价为参考，需人工确认"。"""

def _fmt_row(r) -> str:
    name = (r.get("source_path") or "").replace("\\", "/").split("/")[-1]
    tax = "含税" if r["tax_included"] else ("未税" if r["tax_included"] is not None else "税率不明")
    return (f"{r['project_code']} | {r['supplier']} | {r['category']} | "
            f"{r['product_name']} {r['spec'] or ''} | qty={r['qty']} | "
            f"{r['unit_price']} {r['currency'] or ''} {tax} | "
            f"{r['price_status']} | {r['quote_date'] or ''} | "
            f"[来源:{name} {r['source_location'] or ''}]")

def _vocab(conn) -> str:
    cats = [r[0] for r in conn.execute(
        "SELECT DISTINCT category FROM quote_items WHERE category IS NOT NULL")]
    sups = [r[0] for r in conn.execute(
        "SELECT DISTINCT supplier FROM quote_items WHERE supplier IS NOT NULL")]
    projs = [r[0] for r in conn.execute(
        "SELECT DISTINCT project_code FROM quote_items")]
    return (f"品类：{'、'.join(cats)}\n"
            f"供应商：{'、'.join(sups)}\n"
            f"项目：{'、'.join(projs)}")

def answer_question(conn, client, question: str) -> dict:
    intent = client.chat_json(
        SYSTEM_INTENT.format(today=date.today().isoformat(), vocab=_vocab(conn)),
        question)
    f = retriever.filter_from_dict(intent)
    rows = [dict(r) for r in retriever.search(conn, f)]
    if not rows:  # 语义兜底
        try:
            rows = semantic_search(conn, client, question)
        except Exception:
            rows = []
    prices = [r["unit_price"] for r in rows if r.get("unit_price") is not None]
    from statistics import median
    stats_txt = (f"命中{len(rows)}条；价格 min={min(prices)} 中位={median(prices)} "
                 f"max={max(prices)}（币种以各条目为准）") if prices else f"命中{len(rows)}条"
    table = "\n".join(_fmt_row(r) for r in rows[:60])
    answer = client.chat(
        SYSTEM_ANSWER,
        f"用户问题：{question}\n统计：{stats_txt}\n检索结果：\n{table or '（无）'}")
    return {"answer": answer,
            "matched_count": len(rows),
            "citations": [{"item_id": r["id"],
                           "source_path": r.get("source_path"),
                           "source_location": r.get("source_location")}
                          for r in rows[:20]]}
