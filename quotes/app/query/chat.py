"""对话编排：意图解析 → SQL 检索 → 语义兜底 → 带溯源汇总。"""
import logging
from datetime import date
from statistics import median

from . import retriever
from .embeddings import semantic_search

log = logging.getLogger(__name__)

SYSTEM_INTENT = """把用户关于历史采购/报价的问题转成 JSON 查询条件。字段：
categories(品类列表), suppliers(供应商列表), projects(项目代号列表),
date_from, date_to("YYYY-MM-DD"或null), price_status("成交价/本次报价/历史报价/预估价"或null),
keyword(自由文本关键词或null), metrics(["count","min","max","median","table"]中若干)。
今天是{today}。只输出 JSON。

知识库当前可选值（用户口语词必须映射到其中最接近的标准值，
如"七轴"→"7-Axis"、"涂胶"→"Sealing 涂胶"、"BE22/BE13"→清单内对应项目；
映射不上则该字段置 null，并把原词放进 keyword）：
{vocab}"""

SYSTEM_ANSWER = """采购报价分析助手。只用"检索结果"作答，禁止编造。

严格按此结构输出，不多不少：
第1行 结论：**加粗**一句话给出直接答案（最低价/建议价/条数），可跟半句依据。
第2行 统计：照抄输入中已算好的统计行，禁止自己重算或改写数字。
第3部分 表格：≥2 条数据时必须给，列名照抄检索结果表头。
最后1行 固定输出：建议价为参考，需人工确认。

硬性规则：
- 表格最多 8 行，按检索结果给的顺序自上而下取，不要自行重排；被截断时表下补一行"另有 N 条未列出"。
- 单价、状态·日期、来源三列原样转写，禁止改数字、禁止省略 [来源:...]、禁止合并行。
- 除上述四部分外不写任何内容。禁止：开场白、复述问题、解释检索过程、逐行点评、
  方法论说明、风险提示堆砌、总结段、"如需进一步分析"之类收尾。
- 正文（表格行除外）合计 ≤120 字。
- 仅 1 条数据：不建表，结论行内说清价格与来源即可，统计行省略。
- 无数据：只回"库中无对应数据，建议发起新询价。"，其余全部省略。

示例（问"七轴各家报价对比"）：
**盛允 100,000 CNY 未税为当前最低成交价**，建议以此为基准议价。
统计：命中 3 条（供应商 3 家）；设备单价 最低 100,000 / 中位 118,000 / 最高 135,000 CNY

| 供应商 | 产品/规格 | 单价 | 状态·日期 | 来源 |
|---|---|---|---|---|
| 盛允 | 机器人七轴 11.5m | 100,000 CNY 未税 | 成交价 2026-09 | [来源:盛允报价.xlsx R2] |
| 通锦 | 七轴 12m | 118,000 CNY 未税 | 本次报价 2026-09 | [来源:通锦.xlsx R5] |
| 柯马 | 七轴 11m | 135,000 CNY 含税 | 历史报价 2026-08 | [来源:柯马.pdf 第2页] |

建议价为参考，需人工确认。"""

# 展示优先级：成交价最可信，未标注最次
STATUS_PRIORITY = {"成交价": 0, "本次报价": 1, "历史报价": 2, "预估价": 3, "未标注": 4}
TABLE_ROWS = 24   # 喂给模型的行上限：足够挑出前 8 行，同时避免超长 prompt
ANSWER_ROWS = 8   # 回答中表格行数上限（与 SYSTEM_ANSWER 中的约束保持一致）
PROD_CLIP = 40    # 产品/规格单元格字数上限：超长配置描述会撑爆表格
FILE_CLIP = 24    # 来源文件名字数上限
SUPPLIER_CLIP = 16  # 供应商字数上限：全称过长会挤占表格宽度
# 汇总行特征词：这类行是整包/区域合计，单价与单台设备不可比，
# 混入统计会让"最低价"失真（如 99 元的区域小计），展示时降权、统计时剔除
SUMMARY_WORDS = ("小计", "合计", "总计", "总价", "总额", "total", "subtotal")

def _is_summary(r) -> bool:
    t = f"{r.get('product_name') or ''} {r.get('spec') or ''}".lower()
    return any(w in t for w in SUMMARY_WORDS)

def _has_price(r) -> bool:
    """单价可用于比价：非空且大于 0（0 多为"含在整包内"的占位值，不是真实单价）。"""
    p = r.get("unit_price")
    return p is not None and p > 0

def _fmt_num(v) -> str:
    """整数去小数、其余保留两位，并加千分位：模型直接转写，不必再加工数字。"""
    if v is None:
        return "—"
    f = float(v)
    return f"{f:,.0f}" if f == int(f) else f"{f:,.2f}"

def _fmt_price(r) -> str:
    """单价+币种+含税压成一格，避免表格列数膨胀；币种缺失时不占位。"""
    if r.get("unit_price") is None:
        return "—"
    tax = {True: "含税", False: "未税"}.get(r.get("tax_included"), "税不明")
    return " ".join(filter(None, [_fmt_num(r["unit_price"]),
                                  r.get("currency") or "", tax]))

def _fmt_status(r) -> str:
    """价格状态+年月压成一格；日期只留 YYYY-MM，去掉日减少噪音。"""
    d = (r.get("quote_date") or "")[:7]
    return f"{r.get('price_status') or '未标注'}{' ' + d if d else ''}"

def _clip(s, n) -> str:
    """截断过长文本：整段配置描述会撑爆表格单元格，保留前缀已足够定位。"""
    s = str(s or "").strip()
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"

def _fmt_cite(r) -> str:
    name = _clip((r.get("source_path") or "").replace("\\", "/").split("/")[-1], FILE_CLIP)
    inner = f"{name} {r.get('source_location') or ''}".strip()
    return f"[来源:{inner}]"

def _fmt_rows(rows) -> tuple:
    """按目标表格列预格式化，返回 (表头, 数据行文本)。

    模型只需照抄，不必自己从长串字段里挑列，这是减少冗余输出的关键。
    跨项目查询时才补"项目"列，单项目查询保持表格精简。
    """
    multi_proj = len({r.get("project_code") for r in rows}) > 1
    header = ("项目 | " if multi_proj else "") + \
        "供应商 | 产品/规格 | 单价 | 状态·日期 | 来源"
    lines = []
    for r in rows:
        prod = _clip(f"{r.get('product_name') or ''} {r.get('spec') or ''}", PROD_CLIP) or "—"
        cells = ([r.get("project_code") or "—"] if multi_proj else []) + [
            _clip(r.get("supplier"), SUPPLIER_CLIP) or "—", prod,
            _fmt_price(r), _fmt_status(r), _fmt_cite(r)]
        lines.append(" | ".join(cells))
    return header, "\n".join(lines)

def _rank(rows) -> list:
    """排序：有价格 > 非汇总行 > 有供应商 > 成交价 > 日期新。

    真实库里无价格的子件行（减速机/拖链等）与区域小计行占比很高，不降权会占满
    表格前几行，导致回答看不出重点；先按可比价性排序，模型取前 N 行即最有价值的数据。
    """
    by_date = sorted(rows, key=lambda r: r.get("quote_date") or "", reverse=True)
    return sorted(by_date, key=lambda r: (
        0 if _has_price(r) else 1,
        1 if _is_summary(r) else 0,
        0 if r.get("supplier") else 1,
        STATUS_PRIORITY.get(r.get("price_status") or "未标注", 9)))

def _dedupe(rows) -> list:
    """去掉同供应商+同产品名+同单价的重复行（同一 PDF 被多处抽取时常见）。

    不含 spec：同一报价行的规格描述在两次抽取中常有标点差异，纳入会导致去重失效。
    rows 需已排序，保留首条即保留最优那条。仅用于展示，不影响命中总数。
    """
    seen, out = set(), []
    for r in rows:
        key = (r.get("supplier"), r.get("product_name"), r.get("unit_price"))
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out

def _stats_text(rows) -> str:
    """一行统计：条数、供应商数、价格区间与币种。

    价格区间剔除汇总行与无效价——整包合计、0 值占位与单台单价混在一起算
    min/median/max 毫无参考意义。币种缺失不计入混合币种判断。
    """
    priced = [r for r in rows if _has_price(r) and not _is_summary(r)]
    sups = len({r.get("supplier") for r in rows if r.get("supplier")})
    head = f"命中 {len(rows)} 条（供应商 {sups} 家）"
    if not priced:
        return head + "；无可比价的设备单价"
    prices = [r["unit_price"] for r in priced]
    curs = sorted({r["currency"] for r in priced if r.get("currency")})
    cur_txt = "/".join(curs) if curs else "币种未标注"
    if len(curs) > 1:
        cur_txt += "（混合币种，不可直接比价）"
    n_sum = len(rows) - len(priced)
    tail = f"；已剔除 {n_sum} 条汇总/无价行" if n_sum else ""
    return (f"{head}；设备单价 最低 {_fmt_num(min(prices))} / "
            f"中位 {_fmt_num(median(prices))} / 最高 {_fmt_num(max(prices))} "
            f"{cur_txt}{tail}")

def _cats(conn) -> list:
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT category FROM quote_items WHERE category IS NOT NULL")]

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

def _category_fallback(conn, client, question: str, cats: list) -> list:
    """0 命中时的品类兜底：让 LLM 把口语品类词归一到库内标准品类后重查。"""
    if not cats:
        return []
    try:
        out = client.chat_json(
            "从品类列表中为问题选择最相关的若干品类，只输出JSON:"
            "{\"categories\":[\"...\"]}；无合适则输出空数组。",
            f"品类列表：{'、'.join(cats)}\n问题：{question}")
        cs = [c for c in (out.get("categories") or []) if c in cats]
    except Exception as e:
        log.warning("品类兜底失败：%s", e)
        return []
    if not cs:
        log.debug("品类兜底未选出合适品类")
        return []
    log.info("品类兜底：口语词归一为 %s 后重查", cs)
    return [dict(r) for r in retriever.search(
        conn, retriever.QueryFilter(categories=cs))]

def answer_question(conn, client, question: str) -> dict:
    log.info("收到提问：%s", question)
    intent = client.chat_json(
        SYSTEM_INTENT.format(today=date.today().isoformat(), vocab=_vocab(conn)),
        question)
    log.debug("意图解析结果：%s", intent)
    f = retriever.filter_from_dict(intent)
    rows = [dict(r) for r in retriever.search(conn, f)]
    log.info("结构化检索命中 %d 条", len(rows))
    if not rows:  # 品类兜底：口语词与标准品类不一致（如"激光打码"→"Marking 打码"）
        rows = _category_fallback(conn, client, question, _cats(conn))
    if not rows:  # 语义兜底
        try:
            log.info("结构化与品类兜底均无命中，转语义检索")
            rows = semantic_search(conn, client, question)
        except Exception as e:
            log.warning("语义检索失败：%s", e)
            rows = []
    stats_txt = _stats_text(rows)
    log.info("检索汇总：%s", stats_txt)
    # 排序 + 去重后再截取：模型拿到的前几行就是最值得展示的数据，它不必自己筛选
    ranked = _dedupe(_rank(rows))
    shown = ranked[:TABLE_ROWS]
    if shown:
        header, table = _fmt_rows(shown)
        omitted = len(ranked) - len(shown)
        more = f"，另有 {omitted} 条未列出" if omitted > 0 else ""
        data_block = (f"检索结果（表格列名与行序照抄，共 {len(shown)} 行{more}）：\n"
                      f"{header}\n{table}")
    else:
        data_block = "检索结果：无"
    answer = client.chat(
        SYSTEM_ANSWER,
        f"问题：{question}\n统计：{stats_txt}\n"
        f"表格最多 {ANSWER_ROWS} 行。\n{data_block}")
    log.info("回答完成：命中 %d 条，展示 %d 行，回答 %d 字",
             len(rows), len(shown), len(answer or ""))
    return {"answer": answer,
            "matched_count": len(rows),
            "citations": [{"item_id": r["id"],
                           "source_path": r.get("source_path"),
                           "source_location": r.get("source_location")}
                          for r in shown[:ANSWER_ROWS]]}
