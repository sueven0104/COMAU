"""结构化检索：QueryFilter 构造 SQL，大小写不敏感，支持日期区间与统计。"""
import re
from dataclasses import dataclass
from statistics import median

@dataclass
class QueryFilter:
    categories: list = None
    suppliers: list = None
    projects: list = None
    date_from: str = None
    date_to: str = None
    price_status: str = None
    keyword: str = None

def filter_from_dict(d: dict) -> QueryFilter:
    def lst(k):
        v = d.get(k)
        return [str(x) for x in v] if isinstance(v, list) and v else None
    return QueryFilter(
        categories=lst("categories"), suppliers=lst("suppliers"),
        projects=lst("projects"), date_from=d.get("date_from") or None,
        date_to=d.get("date_to") or None,
        price_status=d.get("price_status") or None,
        keyword=d.get("keyword") or None)

def _where(f: QueryFilter):
    # 列名全限定：JOIN source_files 后两表均有 project_code，裸列名会歧义
    q, args = " WHERE 1=1", []
    for col, vals in (("LOWER(quote_items.category)", f.categories),
                      ("LOWER(quote_items.supplier)", f.suppliers),
                      ("LOWER(quote_items.project_code)", f.projects)):
        if vals:
            q += f" AND {col} IN ({','.join('?' * len(vals))})"
            args += [v.lower() for v in vals]
    if f.price_status:
        q += " AND quote_items.price_status=?"; args.append(f.price_status)
    if f.date_from:
        q += " AND quote_items.quote_date>=?"; args.append(f.date_from)
    if f.date_to:
        q += " AND quote_items.quote_date<=?"; args.append(f.date_to)
    if f.keyword:
        # 多词 keyword 按空格分词 OR 匹配：词可能分布在不同列（如 brand=Fronius + name=CMT）
        terms = [t for t in re.split(r"\s+", f.keyword.strip()) if t] or [f.keyword]
        conds = []
        for t in terms:
            conds.append("(quote_items.product_name LIKE ? OR quote_items.spec LIKE ? "
                         "OR quote_items.brand LIKE ?)")
            args += [f"%{t}%"] * 3
        q += " AND (" + " OR ".join(conds) + ")"
    return q, args

def search(conn, f: QueryFilter, limit=200):
    q, args = _where(f)
    return conn.execute(
        "SELECT quote_items.*, source_files.path AS source_path FROM quote_items "
        "LEFT JOIN source_files ON source_files.id=source_file_id"
        + q + " ORDER BY quote_date DESC LIMIT ?", (*args, limit)).fetchall()

def stats(conn, f: QueryFilter):
    rows = search(conn, f, limit=100000)
    prices = [r["unit_price"] for r in rows if r["unit_price"] is not None]
    return {"count": len(rows),
            "min": min(prices) if prices else None,
            "max": max(prices) if prices else None,
            "median": median(prices) if prices else None}
