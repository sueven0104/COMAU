"""溯源路径换算：库内绝对路径 ↔ raw_data 相对路径。

source_files.path 记录的是建库机器上的绝对路径，换机器后即失效。
展示与打开一律换算成以 raw_data 为锚点的相对路径（raw_data/<项目>/...）；
反向解析仅允许落在当前 raw_data 根内，防止目录穿越。
"""
from pathlib import Path, PurePosixPath

ANCHOR = "raw_data/"

def to_relative(path: str) -> str:
    """任意来源路径 → raw_data/... 相对路径；找不到锚点时原样返回（分隔符统一为 /）。"""
    if not path:
        return path
    p = str(path).replace("\\", "/")
    low = p.lower()
    i = low.rfind(ANCHOR)
    while i > 0 and p[i - 1] != "/":  # 排除 xxx_raw_data/ 这类误匹配
        i = low.rfind(ANCHOR, 0, i)
    return p[i:] if i >= 0 else p

def resolve_relative(rel: str, data_root) -> Path:
    """raw_data/... → 当前机器的绝对路径；越出 raw_data 根则拒绝。"""
    root = Path(data_root).resolve()
    real = (root.parent / PurePosixPath(rel)).resolve()
    if real != root and root not in real.parents:
        raise ValueError(f"路径越出数据根目录：{rel}")
    return real
