"""四档匹配：规则优先（品类/品牌/文本相似度），LLM 仅兜底品类分类。建议价仅供参考。"""
import re
from dataclasses import dataclass, field
from statistics import median

from .. import db

@dataclass
class MatchResult:
    line_id: int
    tier: str                 # 精确匹配/相似匹配/弱匹配/无匹配
    suggested_price: float = None
    price_range: tuple = None
    quote_item_ids: list = field(default_factory=list)
    basis: str = None         # 参考依据：项目/供应商/日期/状态
    explanation: str = None   # 差异说明

def _tokens(s) -> set:
    if not s:
        return set()
    s = str(s).lower()
    words = set(re.findall(r"[a-z0-9]+", s))
    cjk = {s[i] for i in range(len(s)) if "\u4e00" <= s[i] <= "\u9fff"}
    return words | cjk

def similarity(a, b) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), len(tb))

def _brand_equal(a, b) -> bool:
    if not a or not b:
        return False
    return _norm_brand(a) == _norm_brand(b) or _norm_brand(a) in _norm_brand(b) \
        or _norm_brand(b) in _norm_brand(a)

def _norm_brand(s):
    return re.sub(r"\s+", "", str(s)).lower()

def guess_category(conn, line, client=None):
    """品类猜测：品类词在清单行文本中的覆盖率 ≥0.5 即命中，取覆盖最全者；LLM 兜底。"""
    cats = [r[0] for r in conn.execute(
        "SELECT DISTINCT category FROM quote_items WHERE category IS NOT NULL")]
    text = _tokens(" ".join(
        str(x) for x in (line.category, line.product, line.spec) if x))
    if not text:
        return None

    def cover(c):
        ct = _tokens(c)
        return len(ct & text) / len(ct) if ct else 0.0

    best = max(cats, key=cover, default=None)
    if best and cover(best) >= 0.5:
        return best
    if client is not None:  # LLM 兜底分类
        try:
            out = client.chat_json(
                "从给定品类列表中为设备选择最接近的品类，只输出JSON:{\"category\":\"...\"}；都不合适输出null。",
                f"品类列表：{','.join(cats)}\n设备：{line.product} {line.spec or ''}")
            c = out.get("category")
            if c in cats:
                return c
        except Exception:
            pass
    return None

def _line_text(line) -> str:
    return " ".join(str(x) for x in (line.product, line.spec, line.category) if x)

def match_line(conn, line, client=None) -> MatchResult:
    cat = guess_category(conn, line, client)
    cands = [dict(r) for r in db.search_items(conn, categories=[cat])] if cat else []
    if not cands:
        return MatchResult(line_id=line.row_index, tier="无匹配",
                           explanation="库中无该品类历史报价，需发起新询价")
    lt = _line_text(line)
    scored = []
    for c in cands:
        s = max(similarity(lt, f"{c['product_name']} {c['spec'] or ''}"),
                similarity(lt, f"{c['category']} {c['product_name']}"))
        scored.append((c, s))
    exact = [c for c, s in scored if s >= 0.5 and _brand_equal(line.brand, c["brand"])]
    exact_same_brand = [c for c, s in scored if s >= 0.5]
    similar = [c for c, s in scored if 0.25 <= s < 0.5] or exact_same_brand
    prefer = lambda lst: sorted(
        lst, key=lambda c: (c["price_status"] != "成交价", -(c["quote_date"] or "")))[0]

    def basis_of(lst):
        seen, parts = set(), []
        for c in sorted(lst, key=lambda x: (x["price_status"] != "成交价", -(x["quote_date"] or ""))):
            key = (c["project_code"], c["supplier"], c["price_status"])
            if key not in seen:
                seen.add(key)
                parts.append(f"{c['project_code']}/{c['supplier']}/{c['quote_date'] or '?'}/{c['price_status']}")
            if len(parts) >= 3:
                break
        return "；".join(parts)

    if exact:
        best = prefer(exact)
        return MatchResult(line.row_index, "精确匹配", suggested_price=best["unit_price"],
                           quote_item_ids=[c["id"] for c in exact],
                           basis=basis_of(exact),
                           explanation=f"同品类同品牌规格相近，参考成交价优先")
    if similar:
        prices = [c["unit_price"] for c in similar if c["unit_price"] is not None]
        brands = {c["brand"] for c in similar if c["brand"]}
        diffs = []
        if line.brand and brands and not any(_brand_equal(line.brand, b) for b in brands):
            diffs.append(f"品牌差异：清单 {line.brand} vs 历史 {'/'.join(list(brands)[:3])}")
        return MatchResult(line.row_index, "相似匹配",
                           suggested_price=median(prices) if prices else None,
                           price_range=(min(prices), max(prices)) if prices else None,
                           quote_item_ids=[c["id"] for c in similar],
                           basis=basis_of(similar),
                           explanation="；".join(filter(None, diffs + ["同品类，品牌/规格存在差异"])))
    prices = [c["unit_price"] for c in cands if c["unit_price"] is not None]
    return MatchResult(line.row_index, "弱匹配",
                       suggested_price=median(prices) if prices else None,
                       price_range=(min(prices), max(prices)) if prices else None,
                       quote_item_ids=[c["id"] for c in cands],
                       basis=basis_of(cands),
                       explanation="仅品类相同，价格区间跨度大，务必人工判断")

def match_batch(conn, client, lines) -> list:
    return [match_line(conn, ln, client) for ln in lines]
