import openpyxl
from app.ingestion.xlsx_parser import parse_xlsx

def test_parse_serializes_all_sheets(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "报价"
    ws.append(["设备", "数量", "单价"])
    ws.append(["七轴", 2, 47900.0])
    ws2 = wb.create_sheet("空表")
    ws2.append([None, None])
    f = tmp_path / "q.xlsx"
    wb.save(f)
    sheets = parse_xlsx(f)
    assert len(sheets) == 1                     # 全空 sheet 丢弃
    assert sheets[0].name == "报价"
    assert sheets[0].rows[0] == ["设备", "数量", "单价"]
    assert sheets[0].rows[1] == ["七轴", "2", "47900"]  # 数字字符串化、整数去 .0
