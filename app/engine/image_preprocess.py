"""
V4.9.3: 图片预处理管线 — VL API 前的空白过滤 + 自适应压缩 + 增强

所有送 Qwen-VL 的图片统一做三步处理:
  1. 空白检测 → 过滤 Paper Space 等空白页
  2. 自适应尺寸（长边 ≤ 3072px, LANCZOS）
  3. 色彩归一化（RGBA→RGB, 灰度→RGB）
  4. 扫描页可选 CLAHE 增强（cv2, 可选依赖）
  5. JPEG 输出 quality=90

V5.3: max_long_edge 从 2048→3072, JPEG quality 从 85→90
V6.0: max_long_edge 3072→4096, JPEG quality 90→100（画质拉满）

效果预估:
  - API 传输量缩小 80-90%
  - 识别准确率显著提升（尤其大图纸文字识别）
  - 空白 Paper Space 自动丢弃
"""

import io
from typing import Optional, Tuple
from PIL import Image

from ..logger import get_logger

logger = get_logger(__name__)

# ── 公开 API ────────────────────────────────────────────────────────


def preprocess_for_vl(
    image_data: bytes,
    page_type: str = "drawing",
    max_long_edge: int = 0,
    jpeg_quality: int = 100,
) -> Optional[bytes]:
    """
    V6.0: 预处理图片，准备送 VL API（画质拉满版 — 不缩放保留全部像素）。

    Args:
        image_data: 原始图片字节
        page_type: 页面类型 — "drawing" | "text" | "scan" | "blank"
        max_long_edge: 长边最大像素（默认 0=不缩放, V6.0 从 4096 改为 0）
        jpeg_quality: JPEG 输出质量（默认 100）

    Returns:
        处理后的 JPEG 字节，如果为空白则返回 None
    """
    try:
        img = Image.open(io.BytesIO(image_data))
    except Exception as e:
        logger.warning("preprocess_for_vl: 无法打开图片 — %s", e)
        return image_data

    img = _normalize_color(img)

    if _is_blank(img):
        logger.info("preprocess_for_vl: 空白图片已过滤 (%s)", page_type)
        return None

    img = _resize_if_needed(img, max_long_edge)

    if page_type == "scan":
        img = _enhance_scan(img)

    out_buf = io.BytesIO()
    img.convert("RGB").save(out_buf, format="JPEG", quality=jpeg_quality)
    return out_buf.getvalue()


# ── 内部函数 ─────────────────────────────────────────────────────────


def _is_blank(img: Image.Image, color_threshold: int = 5) -> bool:
    """
    检测图片是否为空白（Paper Space / 纯色背景）。

    判定规则: 唯一颜色数 < color_threshold → 空白。
    采样加速: 对 > 1M 像素的图片进行降采样。
    """
    w, h = img.size
    pixels = w * h

    if pixels > 1_000_000:
        scale = min(200.0 / w, 200.0 / h)
        if scale < 1.0:
            small = img.resize((int(w * scale), int(h * scale)), Image.NEAREST)
        else:
            small = img
    else:
        small = img

    colors = small.getcolors(maxcolors=256)
    if colors is None:
        return False

    unique_count = len(colors)
    if unique_count < color_threshold:
        dominant = sorted(colors, key=lambda x: x[0], reverse=True)[:3]
        logger.debug(
            "_is_blank: unique_colors=%d (threshold=%d), top_colors=%s",
            unique_count, color_threshold,
            [(c, "#{:02x}{:02x}{:02x}".format(*rgb[:3]) if isinstance(rgb, tuple) else str(rgb))
             for c, rgb in dominant]
        )
        return True
    return False


def _resize_if_needed(img: Image.Image, max_long_edge: int = 3072) -> Image.Image:
    """
    如果长边超过 max_long_edge，等比例缩放到目标尺寸。
    使用 LANCZOS 重采样，保持线条清晰度。
    max_long_edge=0 时不缩放（V6.0: 保留全部像素送 VL）。
    """
    if max_long_edge <= 0:
        return img  # V6.0: 不缩放

    w, h = img.size
    long_edge = max(w, h)

    if long_edge <= max_long_edge:
        return img

    scale = max_long_edge / long_edge
    new_w = int(w * scale)
    new_h = int(h * scale)

    logger.debug("_resize_if_needed: %dx%d -> %dx%d (scale=%.2f)", w, h, new_w, new_h, scale)
    return img.resize((new_w, new_h), Image.LANCZOS)


def _normalize_color(img: Image.Image) -> Image.Image:
    """
    统一颜色空间：
    - RGBA → 白底 RGB（Alpha 混合到白色背景）
    - P（调色板）→ RGB
    - 灰度 L / LA → RGB
    - CMYK → RGB
    - 已是 RGB → 原样返回
    """
    mode = img.mode

    if mode == "RGB":
        return img

    if mode == "RGBA":
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[3])
        return background

    if mode == "P":
        return img.convert("RGBA").convert("RGB")

    if mode in ("L", "LA"):
        return img.convert("RGB")

    if mode == "CMYK":
        return img.convert("RGB")

    logger.debug("_normalize_color: 未知模式 %s，尝试 convert('RGB')", mode)
    try:
        return img.convert("RGB")
    except Exception:
        return img


def _enhance_scan(img: Image.Image) -> Image.Image:
    """
    扫描页增强：CLAHE（限制对比度自适应直方图均衡化）。
    cv2 为可选依赖，未安装时跳过增强直接返回原图。
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        logger.debug("_enhance_scan: cv2 未安装，跳过 CLAHE 增强")
        return img

    try:
        arr = np.array(img.convert("RGB"))
        arr_bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

        lab = cv2.cvtColor(arr_bgr, cv2.COLOR_BGR2LAB)
        l, a, b_ch = cv2.split(lab)

        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        l_eq = clahe.apply(l)

        lab_eq = cv2.merge([l_eq, a, b_ch])
        enhanced_bgr = cv2.cvtColor(lab_eq, cv2.COLOR_LAB2BGR)

        enhanced_rgb = cv2.cvtColor(enhanced_bgr, cv2.COLOR_BGR2RGB)
        return Image.fromarray(enhanced_rgb)

    except Exception as e:
        logger.warning("_enhance_scan: CLAHE 增强失败 — %s", e)
        return img


# ── 批量处理 ─────────────────────────────────────────────────────────


def preprocess_batch(
    image_paths: list,
    page_type: str = "drawing",
    max_long_edge: int = 4096,
    jpeg_quality: int = 100,
) -> list:
    """
    批量预处理图片文件。

    Args:
        image_paths: PNG 文件路径列表
        page_type: 页面类型
        max_long_edge: 长边最大像素
        jpeg_quality: JPEG 质量

    Returns:
        [(path, processed_bytes_or_None), ...]
    """
    results = []
    for p in image_paths:
        try:
            with open(p, "rb") as f:
                raw = f.read()
            processed = preprocess_for_vl(raw, page_type, max_long_edge, jpeg_quality)
            results.append((p, processed))
        except Exception as e:
            logger.warning("preprocess_batch: %s — %s", p, e)
            results.append((p, None))
    return results
