"""解析新项目询价清单 xlsx：定位 Inquiry 表、容错映射表头、产出清单行。"""
from dataclasses import dataclass
import openpyxl

@dataclass
class InquiryLine:
    row_index: int
    product: str
    spec: str = None
    brand: str = None
    qty: float = None
    unit: str = None
    category: str = None

# 表头别名：列表顺序 = 优先级（category 优先于 commodity 列；含真实清单的 Descripton 拼写）
ALIASES = {
    "product": ["product", "product name", "名称"],
    "spec": ["descripton", "description", "规格", "描述", "说明"],
    "qty": ["qty.", "qty", "数量"],
    "category": ["category", "品类", "commodity"],
    "brand": ["brand", "品牌", "vendor list"],
}
HEADER_KEYS = ["product", "spec", "qty", "category", "brand"]
NUM = "0123456789."
NOT_BRAND = {"推荐", "tbd", "无", "/"}

def _norm(s) -> str:
    return "".join(str(s).lower().split()) if s is not None else ""

def _map_header(row) -> dict:
    """按字段优先级映射列号：先精确匹配首选别名，再退而求其次。"""
    m = {}
    for field, names in ALIASES.items():
        for name in names:
            for j, cell in enumerate(row):
                if _norm(cell) == _norm(name) and j not in m.values():
                    m[field] = j
                    break
            if field in m:
                break
    return m

def _to_num(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = "".join(ch for ch in str(v) if ch in NUM)
    return float(s) if s else None

def parse_inquiry_xlsx(path) -> list:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheets = sorted(wb.worksheets,
                    key=lambda ws: 0 if "inquiry" in _norm(ws.title) else 1)
    for ws in sheets:
        grid = [list(r) for r in ws.iter_rows(values_only=True)]
        # 名字含 inquiry 的 sheet 放宽表头判定（Product+Qty 即可），其他 sheet 需 3 个字段
        need = 2 if "inquiry" in _norm(ws.title) else 3
        header_row, mapping = None, None
        for i, row in enumerate(grid[:10]):
            m = _map_header(row)
            if sum(1 for k in HEADER_KEYS if k in m) >= need:
                header_row, mapping = i, m
                break
        if header_row is None:
            continue
        lines = []
        for i, row in enumerate(grid[header_row + 1:], start=header_row + 2):
            def get(field):
                j = mapping.get(field)
                return row[j] if j is not None and j < len(row) else None
            product, spec = get("product"), get("spec")
            if not (product or spec):
                continue
            if product and _norm(product) in ("(blank)", "总计", "x"):
                continue
            if not any(v not in (None, "") for v in row):
                continue
            brand_raw = get("brand")
            brand = str(brand_raw).strip() if brand_raw else None
            if brand and _norm(brand) in NOT_BRAND:
                brand = None  # "推荐"等占位值不是品牌
            lines.append(InquiryLine(
                row_index=i, product=str(product).strip() if product else None,
                spec=str(spec).strip() if spec else None,
                brand=brand, qty=_to_num(get("qty")),
                unit=None, category=str(get("category")).strip() if get("category") else None))
        if lines:
            wb.close()
            return lines
    wb.close()
    return []
