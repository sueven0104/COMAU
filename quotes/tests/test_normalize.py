from app.ingestion.normalize import (normalize_price_status, clean_number,
                                     normalize_supplier, validate_item,
                                     cross_check_totals, SEED_CATEGORIES)

def test_price_status():
    assert normalize_price_status("成交价") == "成交价"
    assert normalize_price_status(None) == "未标注"
    assert normalize_price_status("历史") == "历史报价"
    assert normalize_price_status("随便") == "未标注"

def test_clean_number():
    assert clean_number("￥47,900元") == 47900.0
    assert clean_number(2) == 2.0
    assert clean_number("") is None
    assert clean_number("N/A") is None

def test_supplier_alias():
    assert normalize_supplier("盛允科技", ["上海盛允"]) is not None  # 无包含关系返回原名
    assert normalize_supplier("盛允", ["上海盛允机械(盛允)"]) == "上海盛允机械(盛允)"

def test_validate_item_flags_missing_currency():
    item, warnings = validate_item({"supplier": "KUKA", "category": "7-Axis",
        "product_name": "七轴", "spec": "5m", "qty": "2", "unit_price": "111,375",
        "currency": None, "tax_included": None, "price_status": "成交价"})
    assert item["unit_price"] == 111375.0 and item["qty"] == 2.0
    assert item["needs_review"] is True          # 有价格但币种/含税未识别
    assert any("币种" in w or "含税" in w for w in warnings)

def test_validate_item_blank_currency():
    item, warnings = validate_item({"product_name": "七轴", "qty": 1,
        "unit_price": 100.0, "currency": " ", "tax_included": True,
        "price_status": "成交价"})
    assert item["currency"] is None and item["needs_review"] is True
    assert any("币种" in w for w in warnings)

def test_validate_item_clean():
    item, warnings = validate_item({"supplier": "KUKA", "category": "7-Axis",
        "product_name": "七轴", "spec": "5m", "qty": 1, "unit_price": 100.0,
        "currency": "cny", "tax_included": True, "price_status": "成交价"})
    assert item["currency"] == "CNY" and item["tax_included"] is True
    assert item["needs_review"] is False

def test_cross_check():
    items = [{"qty": 2, "unit_price": 100.0}, {"qty": 1, "unit_price": 50.0}]
    assert cross_check_totals(items, 250.0) == []                  # 偏差 0
    assert cross_check_totals(items, 300.0, tol=0.05)              # 偏差 20% -> 警告
    assert cross_check_totals(items, None) == []

def test_cross_check_zero_total():
    items = [{"qty": 2, "unit_price": 100.0}, {"qty": 1, "unit_price": 50.0}]
    assert cross_check_totals(items, 0) == []                      # 合计为 0 跳过，不除零

def test_seed_categories():
    assert "7-Axis" in SEED_CATEGORIES and len(SEED_CATEGORIES) >= 15
