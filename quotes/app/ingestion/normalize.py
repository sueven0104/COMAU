"""抽取结果归一化：数字/状态/供应商清洗，字段校验与小计交叉核对。"""
import re

SEED_CATEGORIES = [
    "7-Axis", "AGV", "Air Chuck", "APC Conveyor", "Arc Welding", "Deburring",
    "EMS", "Exhaust 除尘", "Hemming 滚边", "Hoist 吊具", "Laser 激光",
    "Marking 打码", "NC Locator", "PE Stamp", "Robot 机器人", "Roller bed 滚床",
    "Room 房体", "Sealing 涂胶", "Tip Dresser 修磨器", "Tool Changer 换枪盘",
    "Vision 视觉", "Welding Gun 焊枪",
]

PRICE_STATUS_MAP = [
    ("成交", "成交价"), ("本次报价", "本次报价"), ("历史报价", "历史报价"),
    ("历史", "历史报价"), ("预估", "预估价"), ("报价", "本次报价"),
]

def normalize_price_status(raw):
    if not raw:
        return "未标注"
    s = str(raw)
    for key, val in PRICE_STATUS_MAP:
        if key in s:
            return val
    return "未标注"

def clean_number(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").replace("，", "")
    s = re.sub(r"[￥¥$]|元|RMB", "", s).strip()
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group()) if m else None

def normalize_supplier(name, known_suppliers):
    if not name:
        return None
    strip = lambda s: re.sub(r"[（(].*?[)）]|\s+", "", str(s))
    n = strip(name)
    if not n:
        return str(name).strip()
    for k in known_suppliers:
        k2 = strip(k)
        if k2 and (n in k2 or k2 in n):
            return k
    return str(name).strip()

def _clean_tax(v):
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return v
    s = str(v)
    if s.lower() in ("true", "1", "含税", "含税价", "13%", "是"):
        return True
    if s.lower() in ("false", "0", "未税", "不含税", "否"):
        return False
    return None

def validate_item(item: dict):
    """清洗单条抽取记录；返回 (clean_item, warnings)。"""
    warnings = []
    price = clean_number(item.get("unit_price"))
    qty = clean_number(item.get("qty"))
    currency = (str(item["currency"]).strip().upper()
                if item.get("currency") else None)
    tax = _clean_tax(item.get("tax_included"))
    status = normalize_price_status(item.get("price_status"))
    needs_review = False
    if price is not None:
        if currency is None:
            needs_review = True
            warnings.append("缺少币种")
        if tax is None:
            needs_review = True
            warnings.append("未识别含税/未税")
    if not (item.get("product_name") or item.get("spec")):
        needs_review = True
        warnings.append("缺设备名与规格")
    clean = {
        "supplier": item.get("supplier"), "category": item.get("category"),
        "product_name": item.get("product_name"), "spec": item.get("spec"),
        "brand": item.get("brand"), "model": item.get("model"),
        "qty": qty, "unit": item.get("unit"),
        "unit_price": price, "currency": currency, "tax_included": tax,
        "price_status": status, "quote_date": item.get("quote_date"),
        "terms": item.get("terms"), "source_location": item.get("source_location"),
        "needs_review": needs_review,
    }
    return clean, warnings

def cross_check_totals(items, total_value, tol=0.05):
    """数量×单价 之和 与报价单合计交叉核对（无合计值时跳过）。"""
    if total_value is None:
        return []
    calc = sum((i.get("qty") or 0) * (i.get("unit_price") or 0) for i in items)
    if calc <= 0 or not items:
        return []
    if abs(calc - float(total_value)) / float(total_value) > tol:
        return [f"小计交叉核对不符: 计算值{calc:.0f} vs 合计{total_value}"]
    return []
