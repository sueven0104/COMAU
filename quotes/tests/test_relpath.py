import pytest

from app.relpath import resolve_relative, to_relative

def test_to_relative_anchors_on_raw_data():
    assert to_relative("D:\\Projects\\COMAU\\raw_data\\BAIC\\00 框架\\a.png") == \
        "raw_data/BAIC/00 框架/a.png"
    assert to_relative("/home/x/raw_data/Tesla/b.msg") == "raw_data/Tesla/b.msg"
    assert to_relative("raw_data/c.pdf") == "raw_data/c.pdf"

def test_to_relative_no_false_anchor_or_missing():
    # xxx_raw_data/ 不是锚点；无锚点路径原样返回（分隔符统一）
    assert to_relative("C:/x/my_raw_data/a.pdf") == "C:/x/my_raw_data/a.pdf"
    assert to_relative("D:/BAIC/盛允.xlsx") == "D:/BAIC/盛允.xlsx"
    assert to_relative("") == ""
    assert to_relative(None) is None

def test_resolve_relative_containment(tmp_path):
    root = tmp_path / "raw_data"
    (root / "BAIC").mkdir(parents=True)
    assert resolve_relative("raw_data/BAIC/a.pdf", root) == \
        (root / "BAIC" / "a.pdf").resolve()
    # 越出 raw_data 根 / 绝对路径注入 → 拒绝
    with pytest.raises(ValueError):
        resolve_relative("quotes/app/config.py", root)
    with pytest.raises(ValueError):
        resolve_relative("../outside.txt", root)
    with pytest.raises(ValueError):
        resolve_relative("", root)
