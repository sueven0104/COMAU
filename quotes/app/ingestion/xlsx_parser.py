"""Excel 全 sheet 序列化为文本（结构判断交给 LLM 抽取）。"""
import datetime
from dataclasses import dataclass
import openpyxl

@dataclass
class SheetData:
    name: str
    rows: list

def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime.datetime):  # datetime 是 date 的子类，须先判
        if (v.hour, v.minute, v.second) == (0, 0, 0):
            return v.strftime("%Y-%m-%d")
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, datetime.date):
        return v.isoformat()
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v)

def parse_xlsx(path, max_rows=400, max_cols=40) -> list:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheets = []
    for ws in wb.worksheets:
        rows = []
        for row in ws.iter_rows(max_row=max_rows, max_col=max_cols, values_only=True):
            cells = [_cell(c) for c in row[:max_cols]]
            # read_only 模式下 iter_rows 会 pad 到 max_cols，裁掉行尾空单元格
            last = max((i for i, c in enumerate(cells) if c.strip()), default=-1)
            cells = cells[:last + 1]
            if cells:
                rows.append(cells)
        if rows:
            sheets.append(SheetData(ws.title, rows))
    wb.close()
    return sheets
