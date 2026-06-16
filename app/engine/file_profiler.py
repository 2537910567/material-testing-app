"""
V4.9.3: 文件预分析引擎 (Phase 0) — PDF 类型鉴定 + CAD 复杂度估算

在转换(Phase 1)和AI分析(Phase 2)之前，快速预分析每个文件的特性，
输出 FileProfile 供 StrategyConversionThread 使用的分策略处理。

核心设计:
  - PDF 采样策略: 混合型自动升级为全量逐页分类
  - CAD 复杂度估算: 仅凭文件大小快速估算
  - 策略选择: 全自动高质量，不暴露给用户
  - 缓存 key: file_id + file_md5 (DB 持久化)
"""

import os
import hashlib
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple

import fitz  # PyMuPDF

from ..logger import get_logger

logger = get_logger(__name__)


# ── Data class ───────────────────────────────────────────────────────


@dataclass
class FileProfile:
    """文件预分析结果"""

    file_id: int = 0
    file_type: str = ""  # "pdf" | "cad" | "word" | "excel"
    file_path: str = ""
    file_size_mb: float = 0.0
    file_md5: str = ""

    # PDF 专属
    total_pages: int = 0
    page_types: Dict[int, str] = field(default_factory=dict)  # {page_num: "text"|"drawing"|"scan"|"blank"}

    # CAD 专属
    cad_complexity: Dict = field(default_factory=dict)  # {estimated_dxf_mb, entity_count_estimate}

    # 策略决策
    strategy: str = ""  # "text_only" | "standard_render" | "reduced_render" | "cairo_render" | "ocr" | "hybrid"
    strategy_reason: str = ""

    # 元数据
    metadata: Dict = field(default_factory=dict)
    profile_version: str = "4.9.3"

    def to_dict(self) -> dict:
        return asdict(self)


# ── FileProfiler ──────────────────────────────────────────────────────


class FileProfiler:
    """Phase 0: 快速文件预分析"""

    # PDF 页面分类阈值
    TEXT_MIN_CHARS = 200          # 文字页: ≥ 200 chars
    DRAWING_MAX_CHARS = 2000      # 图纸页: 文字 < 2000 + 矢量路径 > 50
    SCAN_MAX_CHARS = 50           # 扫描页: 文字 < 50 + 有图片
    BLANK_MAX_CHARS = 10          # 空白页: 文字 < 10 + 无图片 + 路径 < 5
    DRAWING_PATH_MIN = 50         # 图纸页最少矢量路径数

    # CAD 复杂度阈值 — V6.0: 1-5MB 猛拉画质，耗时不管
    CAD_SIZE_SMALL = 0.5        # MB  → standard_render (150dpi 不变)
    CAD_SIZE_MEDIUM = 2.0       # MB  → standard_high (400dpi)
    CAD_SIZE_LARGE = 5.0        # MB  → standard_plus (350dpi)
    CAD_SIZE_HUGE = 10.0        # MB  → reduced_render (200dpi)

    # DXF 膨胀率估算
    DXF_EXPANSION_RATIO = 6.0     # DWG → DXF 平均膨胀倍数

    # ── PDF 端 ─────────────────────────────────────────────────────

    @staticmethod
    def profile_pdf(file_path: str) -> FileProfile:
        """
        分析 PDF 文件，逐页分类。

        Args:
            file_path: PDF 文件路径

        Returns:
            FileProfile with page_types
        """
        path = Path(file_path)
        file_size_mb = path.stat().st_size / (1024 * 1024)
        file_md5 = _compute_file_md5(file_path)
        profile = FileProfile(
            file_type="pdf",
            file_path=file_path,
            file_size_mb=round(file_size_mb, 1),
            file_md5=file_md5,
        )

        try:
            doc = fitz.open(file_path)
            profile.total_pages = len(doc)

            # 采样策略
            if profile.total_pages <= 30:
                # ≤ 30 页: 全量逐页分类
                sample_pages = range(profile.total_pages)
                profile.metadata["sampling"] = "full"
            elif profile.total_pages <= 200:
                # 31-200 页: 均匀采样 12 页
                sample_pages = _uniform_sample(profile.total_pages, 12)
                profile.metadata["sampling"] = "uniform_12"
            else:
                # > 200 页: 均匀采样 15 页
                sample_pages = _uniform_sample(profile.total_pages, 15)
                profile.metadata["sampling"] = "uniform_15"

            has_mixed = False
            dominant_type = None
            type_counts = {"text": 0, "drawing": 0, "scan": 0, "blank": 0}

            for page_num in sample_pages:
                ptype = FileProfiler._classify_single_page(doc[page_num])
                profile.page_types[page_num] = ptype
                type_counts[ptype] += 1

            # 检测混合型 — 采样中出现 2+ 种类型
            non_blank_types = {k: v for k, v in type_counts.items() if k != "blank" and v > 0}
            if len(non_blank_types) >= 2:
                has_mixed = True

            # 混合型 + 非全量采样 → 自动升级为全量逐页分类
            if has_mixed and profile.metadata["sampling"] != "full":
                logger.info(
                    "profile_pdf: 混合型 PDF (%s), 升级为全量分类 (%d 页)",
                    path.name, profile.total_pages
                )
                profile.metadata["sampling"] = "upgraded_to_full"
                # V5.3: 保留已采样页的分类结果
                sampled_types = dict(profile.page_types)
                profile.page_types.clear()
                for page_num in range(profile.total_pages):
                    if page_num in sampled_types:
                        profile.page_types[page_num] = sampled_types[page_num]
                    else:
                        ptype = FileProfiler._classify_single_page(doc[page_num])
                        profile.page_types[page_num] = ptype
                        type_counts[ptype] = type_counts.get(ptype, 0) + 1

            # 重新统计全量结果
            if has_mixed:
                type_counts = {"text": 0, "drawing": 0, "scan": 0, "blank": 0}
                for ptype in profile.page_types.values():
                    type_counts[ptype] += 1

            # 确定主导类型
            dominant_type = max(type_counts, key=type_counts.get)
            profile.metadata["type_counts"] = type_counts
            profile.metadata["dominant_type"] = dominant_type

            # V4.9.3: 采样模式下，统一类型 → 传播到所有未分类页
            sampling = profile.metadata.get("sampling", "full")
            if sampling != "full" and not has_mixed:
                for page_num in range(profile.total_pages):
                    if page_num not in profile.page_types:
                        profile.page_types[page_num] = dominant_type
                type_counts[dominant_type] = profile.total_pages
                profile.metadata["type_counts"] = type_counts
                profile.metadata["type_propagation"] = f"propagated_{dominant_type}_to_all"

            # 策略决策
            profile.strategy, profile.strategy_reason = _pdf_strategy(
                type_counts, profile.total_pages
            )

            # 检测是否为分层 PDF
            profile.metadata["is_layered"] = FileProfiler._detect_layered_pdf(doc)

            doc.close()

        except Exception as e:
            logger.warning("profile_pdf 失败: %s — %s", file_path, e)
            profile.strategy = "text_only"  # 最保守策略
            profile.strategy_reason = f"预分析失败: {e}"
            profile.metadata["error"] = str(e)

        return profile

    @staticmethod
    def _classify_single_page(page: fitz.Page) -> str:
        """
        判定单个 PDF 页面类型（V4.9.3: 短路优化 — 文字页跳过昂贵操作）。

        Args:
            page: PyMuPDF Page 对象

        Returns:
            "text" | "drawing" | "scan" | "blank"
        """
        # 1. 文字提取（最快，先做）
        text = page.get_text("text")
        text_chars = len(text.strip()) if text else 0

        # V4.9.3 短路: 文字 >= 2000（图纸页上限）直接判定 text，跳过昂贵操作
        if text_chars >= FileProfiler.DRAWING_MAX_CHARS:
            return "text"

        # 2. 矢量路径检测（仅在文字少时做）
        path_count = 0
        try:
            drawings = page.get_drawings()
            path_count = len(drawings) if drawings else 0
        except Exception:
            pass

        # 图纸页: 文字少 + 路径多
        if text_chars < FileProfiler.DRAWING_MAX_CHARS and path_count > FileProfiler.DRAWING_PATH_MIN:
            return "drawing"

        # 3. 图片检测（仅在文字极少时做）
        image_count = 0
        if text_chars < FileProfiler.SCAN_MAX_CHARS:
            try:
                image_list = page.get_images(full=True)
                image_count = len(image_list) if image_list else 0
            except Exception:
                pass

            # 扫描页: 文字极少 + 有嵌入图片
            if image_count >= 1:
                return "scan"

        # 4. 空白页判定
        if text_chars < FileProfiler.BLANK_MAX_CHARS and image_count == 0 and path_count < 5:
            return "blank"

        # 5. 默认: 有少量文字偏向 text，有小量路径偏向 drawing
        if text_chars >= 50:
            return "text"
        if path_count > 0:
            return "drawing"

        return "blank"

    @staticmethod
    def _detect_layered_pdf(doc: fitz.Document) -> bool:
        """检测 PDF 是否包含图层（分层 PDF）"""
        try:
            # 检查 catalog 中的 OCProperties
            catalog = doc.pdf_catalog()
            if catalog and "OCProperties" in catalog:
                return True
        except Exception:
            pass
        return False

    # ── CAD 端 ─────────────────────────────────────────────────────

    @staticmethod
    def profile_cad(file_path: str) -> FileProfile:
        """
        分析 CAD 文件，仅凭文件大小估算复杂度。

        Args:
            file_path: DWG/DXF 文件路径

        Returns:
            FileProfile with cad_complexity and strategy
        """
        path = Path(file_path)
        file_size_mb = path.stat().st_size / (1024 * 1024)
        file_md5 = _compute_file_md5(file_path)

        estimated_dxf_mb = file_size_mb * FileProfiler.DXF_EXPANSION_RATIO

        profile = FileProfile(
            file_type="cad",
            file_path=file_path,
            file_size_mb=round(file_size_mb, 1),
            file_md5=file_md5,
            cad_complexity={
                "estimated_dxf_mb": round(estimated_dxf_mb, 1),
                "file_size_mb": round(file_size_mb, 1),
                "expansion_ratio": FileProfiler.DXF_EXPANSION_RATIO,
            },
        )

        strategy, reason = _cad_strategy(file_size_mb, estimated_dxf_mb)
        profile.strategy = strategy
        profile.strategy_reason = reason

        return profile

    # ── Word/Excel 直通 ─────────────────────────────────────────────

    @staticmethod
    def profile_document(file_path: str) -> FileProfile:
        """
        Word/Excel 文件无需特殊处理，直通。

        Returns:
            FileProfile with strategy="text_only"
        """
        path = Path(file_path)
        ext = path.suffix.lower()
        file_size_mb = path.stat().st_size / (1024 * 1024)
        file_md5 = _compute_file_md5(file_path)

        if ext == ".docx":
            ftype = "word"
        elif ext in (".xlsx", ".xls"):
            ftype = "excel"
        else:
            ftype = "pdf"  # fallback

        return FileProfile(
            file_type=ftype,
            file_path=file_path,
            file_size_mb=round(file_size_mb, 1),
            file_md5=file_md5,
            strategy="text_only",
            strategy_reason="Word/Excel 文件直通文字提取",
        )


# ── 采样工具 ──────────────────────────────────────────────────────────


def _uniform_sample(total: int, n: int) -> List[int]:
    """均匀采样 n 个索引，覆盖头/中/尾"""
    if total <= n:
        return list(range(total))

    step = total / n
    indices = []
    for i in range(n):
        idx = int(i * step)
        if idx >= total:
            idx = total - 1
        if idx not in indices:
            indices.append(idx)

    # 确保包含首页和末页
    if 0 not in indices:
        indices.insert(0, 0)
    if total - 1 not in indices:
        # 替换最后一个采样点为末页
        if len(indices) >= n and indices[-1] != total - 1:
            indices[-1] = total - 1
        else:
            indices.append(total - 1)

    return sorted(set(indices))


def _compute_file_md5(file_path: str, chunk_size: int = 8192) -> str:
    """快速计算文件 MD5"""
    h = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                h.update(chunk)
    except Exception:
        return ""
    return h.hexdigest()


# ── 策略决策 ──────────────────────────────────────────────────────────


def _pdf_strategy(type_counts: dict, total_pages: int) -> Tuple[str, str]:
    """
    根据 PDF 页面类型分布决定处理策略。

    Returns:
        (strategy, reason)
    """
    text_pages = type_counts.get("text", 0)
    drawing_pages = type_counts.get("drawing", 0)
    scan_pages = type_counts.get("scan", 0)
    blank_pages = type_counts.get("blank", 0)
    non_blank = total_pages - blank_pages

    # 纯文本 PDF
    if text_pages >= non_blank * 0.95:
        return "text_only", f"纯文本 ({text_pages}/{total_pages} 页文字)"

    # 纯图纸 PDF
    if drawing_pages >= non_blank * 0.95:
        return "standard_render", f"纯图纸 ({drawing_pages}/{total_pages} 页转PNG)"

    # 纯扫描 PDF
    if scan_pages >= non_blank * 0.95:
        return "ocr", f"纯扫描件 ({scan_pages}/{total_pages} 页需OCR)"

    # 混合型 — 图纸+文字
    if drawing_pages > 0 and text_pages > 0 and scan_pages < non_blank * 0.1:
        return "hybrid", f"混合型: {text_pages} 文字 + {drawing_pages} 图纸 + {scan_pages} 扫描"

    # 混合含扫描
    if scan_pages > 0:
        return "hybrid", f"混合型含扫描件: {text_pages} 文字 + {drawing_pages} 图纸 + {scan_pages} 扫描"

    # 默认
    return "hybrid", f"未分类: text={text_pages}, drawing={drawing_pages}, scan={scan_pages}"


def _cad_strategy(file_size_mb: float, estimated_dxf_mb: float) -> Tuple[str, str]:
    """
    V6.0: CAD 渲染策略 — 聚焦主流文件（<5MB），重点提升 0.5-5MB。

    Returns:
        (strategy, reason)
    """
    if estimated_dxf_mb > 500:
        return "text_only", f"DXF膨胀风险 ({estimated_dxf_mb:.0f}MB) — 仅文字提取"

    if file_size_mb < FileProfiler.CAD_SIZE_SMALL:
        return "standard_render", f"小 CAD ({file_size_mb:.1f}MB) — 150dpi 标准渲染"

    if file_size_mb < FileProfiler.CAD_SIZE_MEDIUM:
        return "standard_high", f"主力 CAD ({file_size_mb:.1f}MB) — 400dpi"

    if file_size_mb < FileProfiler.CAD_SIZE_LARGE:
        return "standard_plus", f"偏大 CAD ({file_size_mb:.1f}MB) — 350dpi"

    if file_size_mb < FileProfiler.CAD_SIZE_HUGE:
        return "reduced_render", f"大 CAD ({file_size_mb:.1f}MB) — 200dpi"

    return "text_only", f"超大 CAD ({file_size_mb:.1f}MB) — 仅文字 + 120dpi 预览"
