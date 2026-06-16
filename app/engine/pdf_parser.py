"""
PDF 文档解析模块
从 PDF 文件中提取文字内容、表格数据，供 AI 分析使用
使用 PyMuPDF 作为主要引擎（中文支持更好）+ pdfplumber 补充表格提取
"""

import fitz  # PyMuPDF
import pdfplumber
import logging
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# ── V6.0: 按页类型动态 DPI ──────────────────────────────────────────────
# 文字页低 DPI 即可，图纸页需要高 DPI 保证 Vision 分析精度
PDF_DPI_TEXT = 200       # 纯文字页，低 DPI 省内存
PDF_DPI_DRAWING = 400    # 图纸页，A1 400dpi ≈ 13250×9350 像素
PDF_DPI_SCAN = 300       # 扫描页（图像类 PDF），折中
PDF_DPI_DEFAULT = 200    # 未知类型回退
PDF_RENDER_TIMEOUT = 180 # V6.0: 高 DPI 渲染超时延长至 180s（原 120s）


def extract_text_from_pdf(pdf_path: str) -> str:
    """
    从 PDF 提取所有文字内容（使用 PyMuPDF，中文支持好）

    Args:
        pdf_path: PDF 文件路径

    Returns:
        提取的纯文本内容
    """
    text_parts = []
    try:
        doc = fitz.open(pdf_path)
        for i, page in enumerate(doc):
            text = page.get_text("text")
            if text and text.strip():
                text_parts.append(f"=== 第 {i+1} 页 ===")
                text_parts.append(text.strip())
        doc.close()
    except Exception as e:
        # PyMuPDF 失败时回退到 pdfplumber
        text_parts.append(f"[PDF解析回退: {e}]")
        try:
            import pdfplumber
            with pdfplumber.open(pdf_path) as pdf:
                for i, page in enumerate(pdf.pages):
                    text = page.extract_text()
                    if text and text.strip():
                        text_parts.append(f"=== 第 {i+1} 页 ===")
                        text_parts.append(text.strip())
        except Exception as e2:
            text_parts.append(f"[PDF解析失败: {e2}]")

    return "\n\n".join(text_parts)


def extract_tables_from_pdf(pdf_path: str, max_pages: int = 0) -> List[Dict]:
    """
    从 PDF 提取表格数据（V6.0.1: PyMuPDF find_tables 为主，pdfplumber 回退）

    PyMuPDF 的 find_tables() 比 pdfplumber 快 5-10x，内存占用极低，
    可安全进行全量表提取，无需页数限制。

    Args:
        pdf_path: PDF 文件路径
        max_pages: 最大处理页数（0=全量，>0=限制；仅用于兼容接口）

    Returns:
        表格列表，每个表格包含页号和行数据
        [{"page": int, "table_index": int, "rows": [[str, ...], ...]}]
    """
    tables = []

    # ── 主路径: PyMuPDF find_tables() ──
    try:
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        pages_to_process = total_pages if max_pages <= 0 else min(total_pages, max_pages)

        for i in range(pages_to_process):
            page = doc[i]
            try:
                found = page.find_tables()
                if found:
                    for t_idx, table in enumerate(found.tables):
                        rows = table.extract()
                        if rows and len(rows) > 1:
                            tables.append({
                                "page": i + 1,
                                "table_index": t_idx,
                                "rows": rows
                            })
            except Exception:
                pass  # 单页失败不影响其他页

        doc.close()
        if tables:
            logger.info("extract_tables: PyMuPDF 从 %d 页中提取 %d 个表格 (%s)",
                        pages_to_process, len(tables), Path(pdf_path).name)
        return tables

    except Exception as e:
        logger.warning("extract_tables: PyMuPDF 失败 — %s，回退 pdfplumber", e)

    # ── 回退路径: pdfplumber（兼容旧版 PyMuPDF / 特殊 PDF） ──
    try:
        with pdfplumber.open(pdf_path) as pdf:
            pages_to_process = len(pdf.pages) if max_pages <= 0 else min(len(pdf.pages), max_pages)
            # pdfplumber 对大文件很慢，限制最大 50 页
            if pages_to_process > 50:
                logger.info("extract_tables: pdfplumber 回退限制 50 页 (总 %d 页)", pages_to_process)
                pages_to_process = 50
            for i in range(pages_to_process):
                page = pdf.pages[i]
                page_tables = page.extract_tables()
                for t_idx, table in enumerate(page_tables):
                    if table and len(table) > 1:
                        tables.append({
                            "page": i + 1,
                            "table_index": t_idx,
                            "rows": table
                        })
    except Exception as e2:
        logger.warning("extract_tables: pdfplumber 回退也失败 — %s", e2)

    return tables


def extract_pdf_content(pdf_path: str, max_pages: Optional[int] = 50,
                        skip_tables_for_large: bool = True) -> Dict:
    """
    综合提取 PDF 内容（文字 + 表格）

    V4.9.3: max_pages 默认 None（全量），不硬截断。由调用方通过策略控制。

    Returns:
        {
            "text": "纯文本内容",
            "tables": [表格列表],
            "pages": 总页数,
            "filename": "文件名",
            "truncated": True/False
        }
    """
    path = Path(pdf_path)

    # V4.9.4: 文件不存在时返回错误 dict，不抛异常
    if not path.exists():
        return {
            "text": "", "tables": [], "pages": 0,
            "filename": path.name, "truncated": False,
            "error": f"文件不存在: {pdf_path}"
        }

    file_size_mb = path.stat().st_size / (1024 * 1024)

    # 先快速获取总页数
    total_pages = 0
    try:
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        doc.close()
    except Exception:
        total_pages = 0

    truncated = False

    # 文本提取（仅当 max_pages 明确指定时才截断）
    if max_pages is not None and total_pages > max_pages:
        text = _extract_text_limited(pdf_path, max_pages, total_pages)
        truncated = True
    else:
        text = extract_text_from_pdf(pdf_path)

    # V6.0: 导入阶段不做表格提取（全量表格在转换阶段 extract_pdf_with_strategy 做）
    tables = []

    return {
        "text": text,
        "tables": tables,
        "pages": total_pages,
        "filename": path.name,
        "truncated": truncated,
        "file_size_mb": round(file_size_mb, 1),
    }


def _extract_text_limited(pdf_path: str, max_pages: int, total_pages: int) -> str:
    """限制页数的文本提取"""
    text_parts = [f"[文件共 {total_pages} 页，仅提取前 {max_pages} 页]"]
    try:
        doc = fitz.open(pdf_path)
        for i in range(min(max_pages, len(doc))):
            page = doc[i]
            text = page.get_text("text")
            if text and text.strip():
                text_parts.append(f"=== 第 {i+1} 页 ===")
                text_parts.append(text.strip())
        doc.close()
    except Exception as e:
        text_parts.append(f"[PDF解析失败: {e}]")
    return "\n\n".join(text_parts)


def extract_pdfs_from_folder(folder_path: str) -> List[Dict]:
    """
    批量提取文件夹中所有 PDF

    Args:
        folder_path: 文件夹路径

    Returns:
        PDF 内容列表
    """
    folder = Path(folder_path)
    pdf_files = list(folder.glob("*.pdf")) + list(folder.glob("*.PDF"))
    results = []
    for pdf_file in pdf_files:
        print(f"正在解析: {pdf_file.name}")
        content = extract_pdf_content(str(pdf_file))
        results.append(content)
    return results


def extract_pdf_with_strategy(pdf_path: str, page_types: Dict[int, str],
                              output_dir: str) -> Dict:
    """
    V4.9.3: 按页面类型分策略提取 PDF 内容。

    Args:
        pdf_path: PDF 文件路径
        page_types: {page_num: "text"|"drawing"|"scan"|"blank"} 分类结果
        output_dir: 输出目录（用于 PNG 图片）

    Returns:
        {
            "text": "全量文字",
            "png_paths": ["图纸/扫描页 PNG 路径"],
            "pages": 总页数,
            "filename": "...",
            "type_summary": {"text": N, "drawing": N, "scan": N, "blank": N}
        }
    """
    import os as _os

    path = Path(pdf_path)
    text_parts = []
    png_paths = []
    type_summary = {"text": 0, "drawing": 0, "scan": 0, "blank": 0, "unknown": 0}
    total_pages = 0

    try:
        doc = fitz.open(pdf_path)
        total_pages = len(doc)

        _os.makedirs(output_dir, exist_ok=True)
        pdf_base = path.stem

        # V4.9.3: 收集渲染任务，稍后并行处理
        render_tasks = []  # [(page_num,)]

        for i in range(total_pages):
            ptype = page_types.get(i, "unknown")
            type_summary[ptype] = type_summary.get(ptype, 0) + 1
            page = doc[i]

            if ptype == "blank":
                continue

            elif ptype == "text":
                text = page.get_text("text")
                if text and text.strip():
                    text_parts.append(f"=== 第 {i+1} 页 ===")
                    text_parts.append(text.strip())

            elif ptype in ("drawing", "scan"):
                render_tasks.append(i)
                # 标题栏文字提取（轻量，在主线程做）
                text = page.get_text("text")
                if text and text.strip():
                    text_parts.append(f"=== 第 {i+1} 页 (图纸) ===")
                    text_parts.append(text.strip()[:500])

            else:  # unknown
                text = page.get_text("text")
                if text and text.strip():
                    text_parts.append(f"=== 第 {i+1} 页 ===")
                    text_parts.append(text.strip())

        # V6.0: 按页类型分 DPI 并行渲染（ThreadPoolExecutor, max_workers=4）
        # 每线程独立打开 fitz.Document 保证线程安全
        # drawing → 400dpi, scan → 300dpi, 未知 → 200dpi
        if render_tasks:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            # 按页类型分组，不同 DPI
            drawing_pages = [n for n in render_tasks if page_types.get(n) == "drawing"]
            scan_pages = [n for n in render_tasks if page_types.get(n) == "scan"]
            unknown_pages = [n for n in render_tasks if page_types.get(n) not in ("drawing", "scan")]

            with ThreadPoolExecutor(max_workers=2) as executor:  # V6.0: 4→2, 防高DPI多文件内存暴涨
                futures = {}
                # 图纸页：400dpi
                if drawing_pages:
                    fut = executor.submit(_render_pages_worker, pdf_path, drawing_pages,
                                          output_dir, pdf_base, PDF_DPI_DRAWING)
                    futures[fut] = ("drawing", drawing_pages)
                # 扫描页：300dpi
                if scan_pages:
                    fut = executor.submit(_render_pages_worker, pdf_path, scan_pages,
                                          output_dir, pdf_base, PDF_DPI_SCAN)
                    futures[fut] = ("scan", scan_pages)
                # 未知页：200dpi
                if unknown_pages:
                    fut = executor.submit(_render_pages_worker, pdf_path, unknown_pages,
                                          output_dir, pdf_base, PDF_DPI_DEFAULT)
                    futures[fut] = ("unknown", unknown_pages)

                for fut in as_completed(futures):
                    try:
                        result = fut.result(timeout=PDF_RENDER_TIMEOUT)
                        png_paths.extend(result)
                    except Exception as e:
                        label, chunk = futures[fut]
                        logger.warning(
                            "extract_pdf_with_strategy: 渲染批次失败 [%s] pages %s — %s",
                            label, chunk[:5], e
                        )

        doc.close()

        # V6.0.1: 表格提取（PyMuPDF find_tables 为主，快速全量）
        # PyMuPDF 的 find_tables() 比 pdfplumber 快 5-10x，内存极低
        tables = []
        if total_pages > 0:
            try:
                tables = extract_tables_from_pdf(pdf_path, max_pages=0)  # 0 = 全量
            except Exception:
                logger.warning("extract_pdf_with_strategy: 表格提取失败 — %s", pdf_path, exc_info=True)

        return {
            "text": "\n\n".join(text_parts),
            "tables": tables,
            "png_paths": png_paths,
            "pages": total_pages,
            "filename": path.name,
            "type_summary": type_summary,
            "truncated": False,
            "file_size_mb": round(path.stat().st_size / (1024 * 1024), 1),
        }

    except Exception as e:
        logger.warning("extract_pdf_with_strategy: %s — %s", pdf_path, e)
        return {
            "text": "",
            "tables": [],
            "png_paths": [],
            "pages": total_pages,
            "filename": path.name,
            "type_summary": type_summary,
            "truncated": False,
            "error": str(e),
        }


def _render_pages_worker(pdf_path: str, page_nums: list, output_dir: str,
                          pdf_base: str, dpi: int = PDF_DPI_DEFAULT) -> list:
    """
    V4.9.3: 批量渲染 PDF 页面为 PNG（进程/线程 worker）。

    独立函数（非内嵌）以满足 ProcessPoolExecutor 的 picklable 要求。
    每进程独立打开 fitz.Document 保证线程/进程安全。
    """
    import os as _os
    results = []
    d = fitz.open(pdf_path)
    try:
        for pn in page_nums:
            pix = d[pn].get_pixmap(dpi=dpi)
            png_path = _os.path.join(output_dir, f"{pdf_base}_page_{pn+1:04d}.png")
            pix.save(png_path)
            results.append(png_path)
    finally:
        d.close()
    return results


def extract_page_images(pdf_path: str, output_dir: str, dpi: int = PDF_DPI_DEFAULT, max_pages: int = 0) -> List[str]:
    """
    用 PyMuPDF 将 PDF 每页渲染为 PNG 图片。

    Args:
        pdf_path: PDF 文件路径
        output_dir: 输出目录
        dpi: 渲染 DPI（默认 200）

    Returns:
        生成的 PNG 文件路径列表
    """
    import os
    os.makedirs(output_dir, exist_ok=True)

    paths = []
    try:
        doc = fitz.open(pdf_path)
        total = len(doc)
        limit = min(total, max_pages) if max_pages > 0 else total
        for i in range(limit):
            page = doc[i]
            pix = page.get_pixmap(dpi=dpi)
            out_path = os.path.join(output_dir, f"page_{i+1:04d}.png")
            pix.save(out_path)
            paths.append(out_path)
        doc.close()
    except Exception:
        logger.warning("extract_page_images: 提取页面图片失败", exc_info=True)
    return paths


def extract_text_fast(pdf_path: str, max_chars: int = 50000) -> str:
    """
    快速提取 PDF 文本（限制长度，适合直接送入 AI）

    Args:
        pdf_path: PDF 文件路径
        max_chars: 最大提取字符数

    Returns:
        提取的文本
    """
    text = extract_text_from_pdf(pdf_path)
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n... (已截取，原文共 {len(text)} 字符)"
    return text
