"""统一日志配置：控制台 + 可选文件输出；Web 服务与建库管道共用。

级别默认 INFO，可用环境变量 QUOTES_LOG_LEVEL=DEBUG 调整排查问题；
QUOTES_LOG_FILE 指定日志文件路径（追加写入）。
"""
import logging
import os
import sys
from pathlib import Path

# 文件里带完整日期，控制台只留时分秒减少噪音
_FMT_CONSOLE = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
_FMT_FILE = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
_DATEFMT = "%H:%M:%S"

_configured = False


def setup_logging(level=None, logfile=None):
    """幂等配置根 logger。重复调用不叠加 handler。

    level: 日志级别名（缺省取 QUOTES_LOG_LEVEL，再缺省 INFO）
    logfile: 额外写入的日志文件（缺省取 QUOTES_LOG_FILE）
    """
    global _configured
    if _configured:
        return
    lvl_name = str(level or os.environ.get("QUOTES_LOG_LEVEL") or "INFO").upper()
    try:
        lvl = logging.getLevelName(lvl_name)
        if not isinstance(lvl, int):
            raise ValueError(lvl_name)
    except ValueError:
        sys.stderr.write(f"[logsetup] 无效日志级别 {lvl_name}，回退 INFO\n")
        lvl = logging.INFO
    file_path = logfile or os.environ.get("QUOTES_LOG_FILE")

    root = logging.getLogger()
    root.setLevel(lvl)
    fmt_c = logging.Formatter(_FMT_CONSOLE, _DATEFMT)
    con = logging.StreamHandler()
    con.setFormatter(fmt_c)
    root.addHandler(con)
    if file_path:
        p = Path(file_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(p, encoding="utf-8")
        fh.setFormatter(logging.Formatter(_FMT_FILE))
        root.addHandler(fh)
    _configured = True
