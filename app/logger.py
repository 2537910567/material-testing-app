"""
应用程序日志系统

特性：
- TimedRotatingFileHandler 按天滚动，保留30天
- 文件级别 DEBUG，控制台级别 INFO
- 启动时自动清理过期日志
"""

import logging
import os
import time
from pathlib import Path
from logging.handlers import TimedRotatingFileHandler
from typing import Optional

LOG_DIR = Path.home() / ".material_testing_tool" / "logs"
MAX_LOG_AGE_DAYS = 30

_logger: Optional[logging.Logger] = None


def get_logger(name: str = "material_testing") -> logging.Logger:
    """获取日志器（如尚未初始化则自动初始化）"""
    global _logger
    if _logger is None:
        setup_logging()
    return logging.getLogger(name)


def setup_logging(log_dir: Optional[Path] = None, max_age_days: int = MAX_LOG_AGE_DAYS) -> logging.Logger:
    """
    初始化日志系统。

    Args:
        log_dir: 日志目录，默认为 ~/.material_testing_tool/logs/
        max_age_days: 日志保留天数，默认 30

    Returns:
        root logger
    """
    global _logger

    if log_dir is None:
        log_dir = LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)

    # 清理过期日志
    cleanup_old_logs(log_dir, max_age_days)

    log_file = log_dir / "app.log"

    # 根日志器 (使用真正的 root logger，确保所有子 logger 的消息都能传播到此)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # 避免重复添加 handler
    if root.handlers:
        return root

    # 文件 handler：DEBUG，按天滚动，保留 max_age_days 天
    file_handler = TimedRotatingFileHandler(
        filename=str(log_file),
        when="D",
        interval=1,
        backupCount=max_age_days,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-7s] %(name)s %(filename)s:%(lineno)d — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    # 控制台 handler：INFO
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-7s] %(message)s",
        datefmt="%H:%M:%S",
    ))

    root.addHandler(file_handler)
    root.addHandler(console_handler)

    # V6.0.1: 抑制第三方库 DEBUG 日志（pdfminer 会生成 GB 级日志）
    for noisy in ["pdfminer", "PIL", "matplotlib", "urllib3"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _logger = root
    root.info("日志系统已初始化 | 日志目录: %s", log_dir)
    return root


def cleanup_old_logs(log_dir: Optional[Path] = None, max_age_days: int = MAX_LOG_AGE_DAYS) -> int:
    """
    清理过期日志文件。

    Args:
        log_dir: 日志目录
        max_age_days: 超过此天数的文件将被删除

    Returns:
        删除的文件数量
    """
    if log_dir is None:
        log_dir = LOG_DIR
    if not log_dir.exists():
        return 0

    cutoff = time.time() - max_age_days * 86400
    deleted = 0
    for f in log_dir.iterdir():
        if f.is_file() and f.suffix in (".log", ".gz"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    deleted += 1
            except OSError:
                pass
    return deleted
