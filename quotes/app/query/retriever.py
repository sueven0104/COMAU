"""结构化检索：QueryFilter 构造 SQL，大小写不敏感，支持日期区间与统计。"""
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
    q, args = " WHERE 1=1", []
    for col, vals in (("LOWER(category)", f.categories),
                      ("LOWER(supplier)", f.suppliers),
                      ("LOWER(project_code)", f.projects)):
        if vals:
            q += f" AND {col} IN ({','.join('?' * len(vals))})"
            args += [v.lower() for v in vals]
    if f.price_status:
        q += " AND price_status=?"; args.append(f.price_status)
    if f.date_from:
        q += " AND quote_date>=?"; args.append(f.date_from)
    if f.date_to:
        q += " AND quote_date<=?"; args.append(f.date_to)
    if f.keyword:
        q += " AND (product_name LIKE ? OR spec LIKE ? OR brand LIKE ?)"
        args += [f"%{f.keyword}%"] * 3
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
