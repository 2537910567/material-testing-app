"""
V4.9.3: OCR 辅助模块 — PaddleOCR / Tesseract 统一入口

对扫描型 PDF 页面进行文字识别。可选依赖，未安装时优雅降级。

优先级: PaddleOCR → Tesseract → 降级提示
单例加载: 避免重复初始化模型

依赖:
  - paddleocr (可选, ~200MB) — 主力 OCR，中文识别率高
  - pytesseract + tesseract-ocr (可选, ~30MB) — 回退引擎
"""

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 单例缓存
_ocr_engine = None
_ocr_engine_type = None  # "paddle" | "tesseract" | None


def ocr_available() -> bool:
    """检测是否有可用的 OCR 引擎"""
    return _get_engine() is not None


def ocr_engine_type() -> Optional[str]:
    """返回当前使用的 OCR 引擎类型"""
    _get_engine()  # 触发初始化
    return _ocr_engine_type


def run_ocr(image_path: str, lang: str = "ch") -> str:
    """
    对图片运行 OCR，提取文字。

    Args:
        image_path: 图片文件路径（PNG/JPEG）
        lang: 语言 — "ch" (中文), "en" (英文), "ch_en" (中英混合)

    Returns:
        识别出的文字内容。OCR 不可用时返回 "[OCR 未安装]" 提示。
    """
    engine = _get_engine()
    engine_type = _ocr_engine_type

    if engine is None:
        return f"[OCR 未安装 — 请安装 paddleocr 或 pytesseract 以启用 OCR]"

    try:
        if engine_type == "paddle":
            return _ocr_paddle(engine, image_path, lang)
        elif engine_type == "tesseract":
            return _ocr_tesseract(engine, image_path, lang)
        else:
            return f"[OCR 引擎未知: {engine_type}]"
    except Exception as e:
        logger.warning("OCR failed for %s: %s", image_path, e)
        return f"[OCR 失败: {e}]"


def _get_engine():
    """惰性初始化 OCR 引擎（单例）"""
    global _ocr_engine, _ocr_engine_type

    if _ocr_engine is not None:
        return _ocr_engine

    # 尝试 PaddleOCR
    try:
        from paddleocr import PaddleOCR
        _ocr_engine = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
        _ocr_engine_type = "paddle"
        logger.info("OCR engine: PaddleOCR")
        return _ocr_engine
    except ImportError:
        logger.debug("PaddleOCR not installed")
    except Exception as e:
        logger.warning("PaddleOCR init failed: %s", e)

    # 回退 Tesseract
    try:
        import pytesseract
        # V4.9.3: 自动检测 Windows 安装路径
        tesseract_exe = os.environ.get("TESSERACT_CMD", "")
        if not tesseract_exe:
            candidates = [
                r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            ]
            for c in candidates:
                if os.path.exists(c):
                    tesseract_exe = c
                    break
        if tesseract_exe:
            pytesseract.pytesseract.tesseract_cmd = tesseract_exe
        _ocr_engine = pytesseract
        _ocr_engine_type = "tesseract"
        logger.info("OCR engine: Tesseract (fallback) — %s", tesseract_exe or "PATH")
        return _ocr_engine
    except ImportError:
        logger.debug("pytesseract not installed")
    except Exception as e:
        logger.warning("Tesseract init failed: %s", e)

    _ocr_engine_type = None
    logger.warning("No OCR engine available — install paddleocr or pytesseract")
    return None


def _ocr_paddle(engine, image_path: str, lang: str = "ch") -> str:
    """PaddleOCR 识别"""
    result = engine.ocr(image_path, cls=True)
    if not result or not result[0]:
        return ""

    lines = []
    for line in result[0]:
        text = line[1][0] if isinstance(line[1], (list, tuple)) else line[1]
        if text and str(text).strip():
            lines.append(str(text).strip())

    return "\n".join(lines)


def _ocr_tesseract(engine, image_path: str, lang: str = "ch") -> str:
    """Tesseract OCR 识别"""
    lang_map = {"ch": "chi_sim", "en": "eng", "ch_en": "chi_sim+eng"}
    tesseract_lang = lang_map.get(lang, "chi_sim")

    text = engine.image_to_string(image_path, lang=tesseract_lang)
    return text.strip() if text else ""
