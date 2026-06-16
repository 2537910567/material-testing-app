"""
DWG/CAD 图纸解析模块
将 .dwg 文件转换为可读文本，提取材料表、桩号、图例等信息

支持两种模式：
1. 通过 ODA File Converter 转换 DWG→DXF（推荐，需安装 ODAFC）
2. ezdxf 直接读取 DXF 文件（如果已预先转换）

安装 ODA File Converter：
  https://www.opendesign.com/guestfiles/oda_file_converter
  下载安装后，默认路径为 C:/Program Files/ODA/ODAFileConverter/
"""

import hashlib
import os
import shutil
import subprocess
import tempfile
import time
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field

from ..logger import get_logger
logger = get_logger(__name__)


@dataclass
class DWGContent:
    """DWG 图纸提取结果"""
    filename: str
    file_path: str
    text_entities: List[Dict] = field(default_factory=list)  # [{text, layer, x, y}]
    block_attributes: List[Dict] = field(default_factory=list)  # [{tag, value, layer}]
    tables: List[List[List[str]]] = field(default_factory=list)  # [[[cell...]]]
    discipline: str = ""  # SⅠ/SⅡ/SⅣ... 工程专业代码
    description: str = ""  # 图纸描述（从图名提取）


# 会话临时目录追踪（用于退出时清理）
_session_temp_dirs: set = set()


def cleanup_session_temp_dirs() -> int:
    """清理本次会话中创建的所有临时转换目录"""
    import shutil
    cleaned = 0
    for d in list(_session_temp_dirs):
        try:
            if os.path.exists(d):
                shutil.rmtree(d, ignore_errors=True)
                cleaned += 1
        except Exception:
            pass
        _session_temp_dirs.discard(d)
    return cleaned


def cleanup_old_temp_dirs(max_age_days: int = 7) -> int:
    """清理 temp 目录中超过指定天数的 dwg2dxf_* 残留目录"""
    import time as _time
    tmp_root = tempfile.gettempdir()
    cutoff = _time.time() - max_age_days * 86400
    cleaned = 0
    try:
        for name in os.listdir(tmp_root):
            if name.startswith("dwg2dxf_"):
                full = os.path.join(tmp_root, name)
                if os.path.isdir(full):
                    try:
                        if os.path.getmtime(full) < cutoff:
                            import shutil
                            shutil.rmtree(full, ignore_errors=True)
                            cleaned += 1
                    except OSError:
                        pass
    except Exception:
        pass
    return cleaned


def _cleanup_intermediate_dxf(dxf_path: str):
    """V4.9.4: 删除 ODAFC 生成的中间 DXF 文件（释放磁盘空间）

    仅删除 dwg2dxf_* 临时目录或系统临时目录中的 DXF，
    不删除用户原始目录中的 DXF 文件。
    """
    tmp_root = tempfile.gettempdir()
    try:
        if not os.path.exists(dxf_path):
            return
        # 安全检查：只删除临时目录中的文件
        dxf_abs = os.path.abspath(dxf_path)
        tmp_abs = os.path.abspath(tmp_root)
        if dxf_abs.startswith(tmp_abs):
            os.remove(dxf_path)
            logger.debug("Cleaned up intermediate DXF: %s", dxf_path)
            # 同时尝试清理空的父目录
            parent = os.path.dirname(dxf_path)
            if parent.startswith(tmp_abs) and parent != tmp_abs:
                try:
                    if not os.listdir(parent):
                        os.rmdir(parent)
                except OSError:
                    pass
    except OSError as e:
        logger.debug("Failed to clean up intermediate DXF %s: %s", dxf_path, e)


def _validate_dxf_eof(dxf_path: str) -> bool:
    """V5.3: 检查 DXF 文件末尾是否有 EOF 标记，验证转换完整性。

    ODAFC 被超时 kill 时可能生成不完整的 DXF（缺少末尾 EOF），
    这种文件会导致后续 ezdxf 解析失败或产生错误数据。

    Returns:
        True if DXF ends with valid EOF marker, False otherwise.
    """
    try:
        # DXF 的 EOF 可能出现在最后几行，通常格式为 "  0\nEOF\n"
        # 读取文件末尾 512 字节即可覆盖
        file_size = os.path.getsize(dxf_path)
        if file_size < 10:
            return False
        with open(dxf_path, "rb") as fh:
            seek_pos = max(0, file_size - 1024)
            fh.seek(seek_pos)
            tail = fh.read(1024).decode("utf-8", errors="replace")
            # 匹配 DXF 标准 EOF 格式（最后一行或倒数几行）
            return "EOF" in tail.splitlines()[-4:]
    except Exception as e:
        logger.warning("_validate_dxf_eof: 无法检查 DXF 完整性 — %s", e)
        return True  # 无法检查时不阻塞（宁可放过，不能误杀）


# ODA File Converter 搜索路径
ODAFC_SEARCH_PATHS = [
    r"C:\Program Files\ODA\ODAFileConverter\ODAFileConverter.exe",
    r"C:\Program Files\ODA\ODAFileConverter 27.1.0\ODAFileConverter.exe",
    r"C:\Program Files (x86)\ODA\ODAFileConverter\ODAFileConverter.exe",
    r"C:\ODA\ODAFileConverter\ODAFileConverter.exe",
]


def find_odafc() -> Optional[str]:
    """查找已安装的 ODA File Converter"""
    # 1. 先检查固定路径
    for path in ODAFC_SEARCH_PATHS:
        if os.path.exists(path):
            return path

    # 2. 扫描 Program Files/ODA/ 下的版本号目录
    oda_base = Path(r"C:\Program Files\ODA")
    if oda_base.exists():
        for subdir in oda_base.iterdir():
            if subdir.is_dir() and "ODAFileConverter" in subdir.name:
                exe = subdir / "ODAFileConverter.exe"
                if exe.exists():
                    return str(exe)

    # 3. 尝试从 PATH 搜索
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags = subprocess.CREATE_NO_WINDOW | subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        result = subprocess.run(
            ["where", "ODAFileConverter.exe"],
            capture_output=True, text=True, timeout=5,
            startupinfo=startupinfo,
        )
        if result.stdout.strip():
            return result.stdout.strip().split("\n")[0]
    except Exception:
        pass
    return None


def convert_dwg_to_dxf(dwg_path: str, output_dir: Optional[str] = None,
                       cancel_event=None) -> Optional[str]:
    """
    用 ODA File Converter 将 DWG 转为 DXF

    V5.1: 文件大小自适应超时 + 降级版本重试。
    V5.2: cancel_event — 取消时优雅终止 ODAFC 而非强杀。

    Returns:
        DXF 文件路径，失败返回 None
    """
    odafc = find_odafc()
    if not odafc:
        return None

    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="dwg2dxf_")
        _session_temp_dirs.add(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    input_dir = str(Path(dwg_path).parent)
    dwg_name = Path(dwg_path).name

    # V5.1: 文件大小自适应超时
    try:
        file_size_mb = os.path.getsize(dwg_path) / (1024 * 1024)
    except Exception:
        file_size_mb = 1.0
    if file_size_mb < 1:
        timeout = 60
    elif file_size_mb < 5:
        timeout = 90
    else:
        timeout = 120

    # ODAFC 命令行格式:
    # ODAFileConverter <InDir> <OutDir> <Ver> <Fmt> <Recurse> <Audit> <FileFilter>
    # V5.1: 从高版本到低版本尝试
    versions = ["ACAD2018", "ACAD2013", "ACAD2010"]
    if file_size_mb < 5:
        versions = versions[:1]  # 小文件只试 ACAD2018

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags = subprocess.CREATE_NO_WINDOW | subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE

    for ver in versions:
        args = [odafc, input_dir, output_dir, ver, "DXF", "0", "1", dwg_name]
        try:
            # V5.3: IDLE 优先级 — ODAFC 只在系统完全空闲时运行，不抢 UI CPU
            IDLE_PRIORITY = 0x00000040  # IDLE_PRIORITY_CLASS
            proc = subprocess.Popen(args, startupinfo=startupinfo,
                                   creationflags=IDLE_PRIORITY)
            # 轮询等待，每 0.5s 检查取消事件
            poll_interval = 0.5
            elapsed = 0.0
            while proc.poll() is None and elapsed < timeout:
                if cancel_event and cancel_event.is_set():
                    proc.terminate()  # 优雅终止（SIGTERM / CTRL_BREAK）
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()   # 超时后强杀
                        proc.wait()
                    logger.info("ODAFC cancelled by user")
                    return None
                import time as _sleep
                _sleep.sleep(poll_interval)
                elapsed += poll_interval

            if proc.poll() is None:
                proc.kill()
                proc.wait()
                logger.warning("ODAFC timeout (%ds) for %s", timeout, dwg_name)
                continue  # try next version

            for f in os.listdir(output_dir):
                if f.lower().endswith(".dxf"):
                    dxf_result = os.path.join(output_dir, f)
                    # V5.3: DXF 完整性校验 — 检查末尾 EOF 标记
                    if not _validate_dxf_eof(dxf_result):
                        logger.warning("ODAFC produced incomplete DXF (no EOF): %s", dxf_result)
                        try:
                            os.unlink(dxf_result)
                        except Exception:
                            pass
                        continue  # try next version
                    if ver != "ACAD2018":
                        logger.info("ODAFC success with version %s (downgraded from ACAD2018)", ver)
                    return dxf_result

            # No DXF produced — try next version
            if ver != versions[-1]:
                logger.warning("ODAFC with %s returned no DXF, trying next version...", ver)
        except subprocess.TimeoutExpired:
            logger.warning("ODAFC timeout with %s (%ds)", ver, timeout)
            if ver != versions[-1]:
                continue
        except Exception as e:
            logger.warning("ODAFC error with %s: %s", ver, e)
            if ver != versions[-1]:
                continue

    return None


def _has_chinese_chars(s: str) -> bool:
    """检测字符串是否包含中文字符（ODAFC 不支持中文路径）"""
    return bool(re.search(r'[一-鿿]', s))


def _copy_to_ascii_temp(src_path: str) -> Optional[str]:
    """将文件链接/复制到 ASCII 临时目录，返回新路径。用于绕过 ODAFC 中文路径限制。

    V4.9.4: 优先使用硬链接(os.link)替代文件复制，瞬间完成且不占磁盘空间。
    硬链接失败时回退到物理复制（跨卷场景）。
    """
    try:
        src = Path(src_path)
        tmp_dir = tempfile.mkdtemp(prefix="odafc_ascii_")
        _session_temp_dirs.add(tmp_dir)
        # 使用 hash 生成唯一 ASCII 文件名
        name_hash = hashlib.md5(src.name.encode()).hexdigest()[:8]
        ascii_name = name_hash + src.suffix.lower()
        dst = Path(tmp_dir) / ascii_name
        # V4.9.4: 硬链接优先（零拷贝），回退到物理复制
        try:
            os.link(src_path, str(dst))
            logger.debug("Hardlinked to ASCII temp: %s -> %s", src_path, dst)
        except OSError:
            shutil.copy2(src_path, dst)
            logger.info("Copied to ASCII temp (hardlink failed): %s -> %s", src_path, dst)
        return str(dst)
    except Exception as e:
        logger.warning("Failed to copy/link to ASCII temp: %s", e)
        return None


def convert_dxf_to_png_ezdxf(dxf_path: str, output_dir: str,
                              dpi: int = 150, figsize: tuple = (12, 9),
                              render_timeout: int = 120,
                              modelspace_only: bool = True) -> List[str]:
    """
    V4.9: 用 ezdxf + matplotlib 将 DXF 渲染为 PNG。
    V4.9.3: 增加 dpi/figsize 参数支持多策略渲染。
    V4.9.4: render_timeout 按文件大小缩放；modelspace_only 跳过 PaperSpace 布局。

    速度: ~5-15s/DXF（取决于 DXF 复杂度）

    Returns:
        生成的 PNG 文件路径列表
    """
    import matplotlib
    matplotlib.use('Agg')  # 非交互后端，避免与 Qt 冲突
    import matplotlib.pyplot as plt
    import ezdxf
    from ezdxf.addons.drawing import RenderContext, Frontend
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

    try:
        doc = ezdxf.readfile(dxf_path)
    except Exception as e:
        logger.warning("Failed to read DXF: %s — %s", dxf_path, e)
        return []

    os.makedirs(output_dir, exist_ok=True)
    png_files = []

    # 渲染 modelspace + paper space layouts（V4.9.4: modelspace_only 跳过 PaperSpace）
    layouts = [doc.modelspace()]
    if not modelspace_only:
        try:
            for name in doc.layouts.names():
                layout = doc.layouts.get(name)
                if layout and layout.name != "Model":
                    layouts.append(layout)
        except Exception:
            pass

    for i, msp in enumerate(layouts):
        try:
            fig = plt.figure(figsize=figsize)
            ax = fig.add_axes([0, 0, 1, 1])
            ctx = RenderContext(doc)
            backend = MatplotlibBackend(ax)

            # V4.9.4: 渲染超时按参数缩放（小文件用短超时，大文件用长超时）
            from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
            render_done = {"ok": False, "error": None}

            def _render():
                try:
                    Frontend(ctx, backend).draw_layout(msp, finalize=True)
                    render_done["ok"] = True
                except Exception as e:
                    render_done["error"] = str(e)

            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_render)
                try:
                    future.result(timeout=render_timeout)
                except FutureTimeoutError:
                    logger.warning("DXF渲染超时(%ds): %s layout %d, 跳过渲染", render_timeout, dxf_path, i)
                    plt.close(fig)
                    continue

            if render_done["error"]:
                raise RuntimeError(render_done["error"])

            suffix = "" if i == 0 else f"_layout{i}"
            png_path = os.path.join(output_dir, f"{Path(dxf_path).stem}{suffix}.png")
            fig.savefig(png_path, dpi=dpi)
            plt.close(fig)

            # V4.9.3: 空白 Paper Space 过滤
            if _is_blank_png(png_path):
                os.remove(png_path)
                logger.debug("convert_dxf_to_png_ezdxf: 空白布局已过滤 — %s", png_path)
            else:
                png_files.append(png_path)
        except Exception as e:
            logger.warning("Failed to render layout %d for %s: %s", i, dxf_path, e)
            try:
                plt.close('all')
            except Exception:
                pass

    if not png_files:
        logger.warning("ezdxf produced no PNG for: %s", dxf_path)
    return png_files

def convert_dxf_to_png_pymupdf(dxf_path: str, output_dir: str,
                               dpi: int = 150, render_timeout: int = 60) -> List[str]:
    """
    V4.9.4: 用 ezdxf + PyMuPDF (fitz) 将 DXF 渲染为 PNG。

    PyMuPdfBackend 比 matplotlib 快 10-38x，是所有策略的首选渲染器。
    自动渲染 modelspace + 所有 PaperSpace layouts。

    Returns:
        生成的 PNG 文件路径列表
    """
    import ezdxf
    from ezdxf.addons.drawing import RenderContext, Frontend
    from ezdxf.addons.drawing.pymupdf import PyMuPdfBackend
    from ezdxf.addons.drawing.layout import Page, Margins

    try:
        doc = ezdxf.readfile(dxf_path)
    except Exception as e:
        logger.warning("Failed to read DXF: %s — %s", dxf_path, e)
        return []

    os.makedirs(output_dir, exist_ok=True)
    png_files = []

    # 收集所有 layouts
    layouts_info = [("modelspace", doc.modelspace())]
    try:
        for name in doc.layouts.names():
            layout = doc.layouts.get(name)
            if layout and layout.name != "Model":
                layouts_info.append((layout.name, layout))
    except Exception:
        pass

    for li, (lname, msp) in enumerate(layouts_info):
        try:
            # 获取布局的页面大小(mm)
            try:
                page_setup = msp.page_setup()
                pw = page_setup.paper_width
                ph = page_setup.paper_height
                if pw <= 0 or ph <= 0:
                    pw, ph = 841, 594  # A1 landscape default
            except Exception:
                pw, ph = 841, 594

            pymupdf_page = Page(pw, ph, margins=Margins(5, 5, 5, 5))
            backend = PyMuPdfBackend()
            ctx = RenderContext(doc)
            frontend = Frontend(ctx, backend)

            # 渲染（带超时保护）
            from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
            render_done = {"ok": False, "error": None}

            def _render():
                try:
                    frontend.draw_layout(msp, finalize=True)
                    render_done["ok"] = True
                except Exception as e:
                    render_done["error"] = str(e)

            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_render)
                try:
                    future.result(timeout=render_timeout)
                except FutureTimeoutError:
                    logger.warning("PyMuPDF渲染超时(%ds): %s layout %d, 跳过",
                                 render_timeout, dxf_path, li)
                    continue

            if render_done["error"]:
                raise RuntimeError(render_done["error"])
            if not render_done["ok"]:
                continue

            # 导出 PNG 字节
            png_bytes = backend.get_pixmap_bytes(pymupdf_page, fmt="png", dpi=dpi)

            suffix = "" if li == 0 else f"_layout{li}"
            png_path = os.path.join(output_dir, f"{Path(dxf_path).stem}{suffix}.png")
            with open(png_path, "wb") as f:
                f.write(png_bytes)

            if _is_blank_png(png_path):
                os.remove(png_path)
                logger.debug("convert_dxf_to_png_pymupdf: 空白布局已过滤 — %s", png_path)
            else:
                png_files.append(png_path)

        except Exception as e:
            logger.warning("PyMuPDF render failed for layout %d of %s: %s", li, dxf_path, e)

    if not png_files:
        logger.warning("PyMuPDF produced no PNG for: %s", dxf_path)
    return png_files


def _is_blank_png(png_path: str, color_threshold: int = 5) -> bool:
    """V4.9.3: 快速检测 PNG 是否为空白（Paper Space）"""
    try:
        from PIL import Image
        img = Image.open(png_path)
        w, h = img.size
        pixels = w * h
        # 大图降采样
        if pixels > 1_000_000:
            scale = min(200.0 / w, 200.0 / h)
            if scale < 1.0:
                img = img.resize((int(w * scale), int(h * scale)), Image.NEAREST)
        colors = img.getcolors(maxcolors=256)
        img.close()
        if colors is None:
            return False  # > 256 色
        return len(colors) < color_threshold
    except Exception:
        return False


def convert_dxf_to_png_cairo(dxf_path: str, output_dir: str,
                              max_long_edge: int = 2048,
                              render_timeout: int = 60) -> List[str]:
    """
    V4.9.3: 用 ezdxf + pycairo 快速渲染 DXF（3-5x  matplotlib）。
    V4.9.4: 增加 ThreadPoolExecutor 超时保护 + 动态分辨率缩放。

    注意: pycairo 是可选依赖，未安装时自动回退到 matplotlib。

    Returns:
        生成的 PNG 文件路径列表
    """
    import ezdxf

    # V4.9.4: DXF 文件越大，降低分辨率防止 OOM
    try:
        dxf_size_mb = os.path.getsize(dxf_path) / (1024 * 1024)
    except OSError:
        dxf_size_mb = 0
    if dxf_size_mb > 30:
        max_long_edge = min(max_long_edge, 1024)
    elif dxf_size_mb > 10:
        max_long_edge = min(max_long_edge, 2048)

    try:
        doc = ezdxf.readfile(dxf_path)
    except Exception as e:
        logger.warning("Failed to read DXF for Cairo: %s — %s", dxf_path, e)
        return []

    try:
        import cairo
        from ezdxf.addons.drawing import RenderContext, Frontend
        from ezdxf.addons.drawing.pycairo import PyCairoBackend
    except ImportError:
        logger.info("pycairo/PyCairoBackend 不可用，回退到 matplotlib")
        # V4.9.4: 传递 render_timeout 和 modelspace_only，避免默认 120s 超时
        _timeout = min(render_timeout, 45)  # 最多 45s
        return convert_dxf_to_png_ezdxf(dxf_path, output_dir,
                                        dpi=100, figsize=(10, 7.5),
                                        render_timeout=_timeout,
                                        modelspace_only=True)

    os.makedirs(output_dir, exist_ok=True)
    png_files = []

    layouts = [doc.modelspace()]
    try:
        for name in doc.layouts.names():
            layout = doc.layouts.get(name)
            if layout and layout.name != "Model":
                layouts.append(layout)
    except Exception:
        pass

    for i, msp in enumerate(layouts):
        try:
            # 创建 Cairo 图像表面
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, max_long_edge, max_long_edge)
            ctx_cairo = cairo.Context(surface)
            # 白色背景
            ctx_cairo.set_source_rgb(1, 1, 1)
            ctx_cairo.paint()

            render_ctx = RenderContext(doc)
            backend = PyCairoBackend(ctx_cairo)

            # V4.9.4: draw_layout 可能卡死（复杂 DXF），加超时保护
            from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
            render_done = {"ok": False, "error": None}

            def _cairo_render():
                try:
                    Frontend(render_ctx, backend).draw_layout(msp, finalize=True)
                    render_done["ok"] = True
                except Exception as e:
                    render_done["error"] = str(e)

            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_cairo_render)
                try:
                    future.result(timeout=render_timeout)
                except FutureTimeoutError:
                    logger.warning("Cairo渲染超时(%ds): %s layout %d, 跳过渲染", render_timeout, dxf_path, i)
                    continue

            if render_done["error"]:
                raise RuntimeError(render_done["error"])
            if not render_done["ok"]:
                continue

            suffix = "" if i == 0 else f"_layout{i}"
            png_path = os.path.join(output_dir, f"{Path(dxf_path).stem}{suffix}.png")
            surface.write_to_png(png_path)

            if _is_blank_png(png_path):
                os.remove(png_path)
                logger.debug("convert_dxf_to_png_cairo: 空白布局已过滤 — %s", png_path)
            else:
                png_files.append(png_path)

        except Exception as e:
            logger.warning("Cairo render failed for layout %d of %s: %s", i, dxf_path, e)

    if not png_files:
        logger.warning("Cairo produced no PNG for: %s", dxf_path)
    return png_files


def convert_cad_with_strategy(dwg_path: str, strategy: str,
                               output_dir: str = "",
                               cancel_event=None) -> Dict:
    """
    V4.9.3: 按策略转换 CAD 文件。

    Args:
        dwg_path: DWG/DXF 文件路径
        strategy: "standard_render" | "reduced_render" | "cairo_render" | "text_only"
        output_dir: 输出目录

    Returns:
        {"png_paths": [...], "text": "...", "strategy": "...", "error": None}
    """
    if not os.path.exists(dwg_path):
        return {"png_paths": [], "text": "", "strategy": strategy,
                "error": f"文件不存在: {dwg_path}"}

    original_path = dwg_path

    # 中文路径处理
    if _has_chinese_chars(dwg_path):
        ascii_path = _copy_to_ascii_temp(dwg_path)
        if ascii_path:
            dwg_path = ascii_path
        else:
            return {"png_paths": [], "text": "", "strategy": strategy,
                    "error": "中文路径复制到 ASCII 临时目录失败"}

    # Step 1: DWG → DXF
    dxf_path = None
    if dwg_path.lower().endswith(".dwg"):
        dxf_path = convert_dwg_to_dxf(dwg_path, cancel_event=cancel_event)
        if not dxf_path:
            return {"png_paths": [], "text": "", "strategy": strategy,
                    "error": "DWG→DXF 转换失败"}
    else:
        dxf_path = dwg_path  # 已经是 DXF

    if not output_dir:
        output_dir = tempfile.mkdtemp(prefix="cad2png_")
        _session_temp_dirs.add(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    # Step 2: 文字提取（所有策略都做）
    # V4.9.4: text_only 策略使用更低的实体上限（3万），防止超大 DXF 无界遍历
    _max_entities = 30000 if strategy == "text_only" else 50000
    content = parse_dxf_to_content(dxf_path, max_entities=_max_entities)
    text = extract_all_text([content]) if content else ""

    # Step 3: 按策略渲染
    png_paths = []

    try:
        if strategy == "text_only":
            # V6.0: 120dpi 预览
            try:
                quick_pngs = convert_dxf_to_png_pymupdf(dxf_path, output_dir,
                                                        dpi=120, render_timeout=30)
                if quick_pngs:
                    png_paths = quick_pngs[:1]
                    logger.info("text_only bonus render: %s", png_paths[0])
            except Exception:
                pass  # 渲染失败不影响文字提取

        elif strategy == "standard_high":
            # V6.0: 400dpi — 1-2MB 主力文件
            png_paths = convert_dxf_to_png_pymupdf(dxf_path, output_dir,
                                                   dpi=400, render_timeout=180)
            if not png_paths:
                png_paths = convert_dxf_to_png_ezdxf(dxf_path, output_dir,
                                                      dpi=200, figsize=(16, 12),
                                                      render_timeout=120,
                                                      modelspace_only=True)

        elif strategy == "standard_plus":
            # V6.0: 350dpi — 2-5MB 偏大文件
            png_paths = convert_dxf_to_png_pymupdf(dxf_path, output_dir,
                                                   dpi=350, render_timeout=180)
            if not png_paths:
                png_paths = convert_dxf_to_png_ezdxf(dxf_path, output_dir,
                                                      dpi=200, figsize=(14, 10),
                                                      render_timeout=120,
                                                      modelspace_only=True)

        elif strategy == "standard_render":
            # <0.5MB 小文件，150dpi 不变
            png_paths = convert_dxf_to_png_pymupdf(dxf_path, output_dir,
                                                   dpi=150, render_timeout=60)
            if not png_paths:
                png_paths = convert_dxf_to_png_ezdxf(dxf_path, output_dir,
                                                      dpi=100, figsize=(10, 7.5),
                                                      render_timeout=45,
                                                      modelspace_only=True)

        elif strategy == "reduced_render":
            # V6.0: 200dpi — 5-10MB
            png_paths = convert_dxf_to_png_pymupdf(dxf_path, output_dir,
                                                   dpi=200, render_timeout=120)
            if not png_paths:
                png_paths = convert_dxf_to_png_ezdxf(dxf_path, output_dir,
                                                      dpi=120, figsize=(10, 7.5),
                                                      render_timeout=60,
                                                      modelspace_only=True)

        elif strategy == "cairo_render":
            png_paths = convert_dxf_to_png_pymupdf(dxf_path, output_dir,
                                                   dpi=120, render_timeout=30)

        else:
            png_paths = convert_dxf_to_png_pymupdf(dxf_path, output_dir,
                                                   dpi=120, render_timeout=30)
    finally:
        # V4.9.4: ODAFC 生成的中间 DXF 文件使用后立即删除，释放磁盘空间
        # （仅清理 ODAFC 输出的临时 DXF，不清理用户自己的 DXF）
        if dxf_path != dwg_path and dxf_path != original_path:
            _cleanup_intermediate_dxf(dxf_path)

    return {
        "png_paths": png_paths,
        "text": text,
        "strategy": strategy,
        "error": None if png_paths or strategy == "text_only" else "未生成 PNG",
    }


def convert_dwg_to_png(dwg_path: str, output_dir: Optional[str] = None, max_images: int = 0) -> List[str]:
    """
    V4.9: DWG → PNG 完整管线（ODAFC v27 DXF + ezdxf/matplotlib PNG）。
    1. 中文路径 → ASCII 临时目录
    2. ODAFC v27: DWG → DXF
    3. ezdxf+matplotlib: DXF → PNG
    总耗时: ~5-20s/DWG

    Returns:
        生成的 PNG 文件路径列表
    """
    if not os.path.exists(dwg_path):
        return []

    original_path = dwg_path

    # 1. 中文路径 → 复制到 ASCII 临时目录
    if _has_chinese_chars(dwg_path):
        ascii_path = _copy_to_ascii_temp(dwg_path)
        if ascii_path:
            dwg_path = ascii_path
        else:
            return []

    # 2. DWG → DXF (ODAFC v27)
    dxf_path = convert_dwg_to_dxf(dwg_path)
    if not dxf_path:
        logger.warning("DWG→DXF failed for: %s", original_path)
        return []

    # 3. DXF → PNG (ezdxf + matplotlib)
    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="dwg2png_")
        _session_temp_dirs.add(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    png_files = convert_dxf_to_png_pymupdf(dxf_path, output_dir, dpi=150)
    if max_images > 0 and len(png_files) > max_images:
        png_files = png_files[:max_images]

    if not png_files:
        logger.warning("DXF→PNG failed for: %s (DXF: %s)", original_path, dxf_path)
    return png_files


def convert_dwg_batch(dwg_files: List[str], output_dir: str) -> Dict[str, str]:
    """
    V4.6: 并行批量转换 DWG→DXF（ThreadPoolExecutor，max_workers=4）。

    每个 worker 启动独立 ODAFC 子进程，天然并行，不阻塞主线程。
    注意：ODAFC 子进程在 FileImportThread (QThread) 的 worker 线程中运行，不影响 GUI。

    Returns:
        {dwg_path: dxf_path} 映射
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    odafc = find_odafc()
    if not odafc:
        return {}

    if not dwg_files:
        return {}

    os.makedirs(output_dir, exist_ok=True)
    max_workers = min(4, len(dwg_files), os.cpu_count() or 4)

    result = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_dwg = {}
        for dwg_path in dwg_files:
            future = executor.submit(convert_dwg_to_dxf, dwg_path, output_dir)
            future_to_dwg[future] = dwg_path

        for future in as_completed(future_to_dwg):
            dwg_path = future_to_dwg[future]
            try:
                dxf_path = future.result()
                if dxf_path:
                    result[dwg_path] = dxf_path
            except Exception as e:
                print(f"  WARN: DWG→DXF failed: {Path(dwg_path).name} — {e}")

    return result


def parse_dxf_to_content(dxf_path: str, filename: str = "",
                         max_entities: int = 50000) -> DWGContent:
    """
    用 ezdxf 解析 DXF 文件，提取文字和表格

    Args:
        dxf_path: DXF 文件路径
        filename: 原始文件名
        max_entities: TEXT/MTEXT 最大提取数量（默认 50000），
                      超大 DXF（>50MB）可设置更低值防止无界遍历

    Returns:
        DWGContent 结构化数据
    """
    import ezdxf

    content = DWGContent(
        filename=filename or Path(dxf_path).name,
        file_path=dxf_path
    )

    try:
        doc = ezdxf.readfile(dxf_path)
        msp = doc.modelspace()

        # 1. 提取 TEXT / MTEXT 实体（V4.9.4: 添加 max_entities 上限防止超大 DXF 无界遍历）
        entity_count = 0
        for entity in msp.query("TEXT MTEXT"):
            if entity_count >= max_entities:
                logger.warning(
                    "DXF text entity limit reached (%d), stopping extraction for: %s "
                    "(file may be very large, consider reducing max_entities)",
                    max_entities, dxf_path
                )
                break
            entity_count += 1
            # V4.9.4: 每 5000 个实体让出 GIL，防止 UI 线程长时间无响应
            if entity_count % 5000 == 0:
                time.sleep(0)

            text = ""
            layer = entity.dxf.layer
            insert_point = entity.dxf.insert if hasattr(entity.dxf, 'insert') else None

            if entity.dxftype() == "TEXT":
                text = entity.dxf.text
            elif entity.dxftype() == "MTEXT":
                text = entity.text

            if text.strip():
                content.text_entities.append({
                    "text": text.strip(),
                    "layer": layer,
                    "x": round(insert_point.x, 2) if insert_point else 0,
                    "y": round(insert_point.y, 2) if insert_point else 0,
                })

        # 2. 提取 INSERT（图块）+ ATTRIB（属性）
        for entity in msp.query("INSERT"):
            if entity.attribs:
                for attrib in entity.attribs:
                    content.block_attributes.append({
                        "tag": attrib.dxf.tag,
                        "value": attrib.dxf.text,
                        "layer": entity.dxf.layer,
                    })

        # 3. 提取 ACAD_TABLE
        for entity in msp.query("ACAD_TABLE"):
            table = []
            for row_idx in range(entity.rows):
                row = []
                for col_idx in range(entity.cols):
                    cell_text = ""
                    try:
                        cell = entity.cell(row_idx, col_idx)
                        if cell:
                            cell_text = cell.text if hasattr(cell, 'text') else str(cell)
                    except Exception:
                        pass
                    row.append(cell_text.strip())
                if any(row):
                    table.append(row)
            if table:
                content.tables.append(table)

        # 4. 从文件名和内容推断专业
        content.discipline = _detect_discipline(filename, content.text_entities)

        # 5. 提取图纸标题（通常包含在图框中的大号文字）
        content.description = _extract_title(content.text_entities)

        doc.close()

    except Exception as e:
        # 记录解析失败
        content.text_entities.append({
            "text": f"[DWG解析异常: {str(e)}]",
            "layer": "ERROR",
            "x": 0, "y": 0
        })

    return content


def parse_dwg(dwg_path: str, auto_convert: bool = True) -> Optional[DWGContent]:
    """
    解析 DWG/DXF 文件（主入口）

    支持的文件格式：
    - .dxf — 直接用 ezdxf 解析（推荐）
    - .dwg — 需 ODA File Converter 转换为 DXF 后解析

    流程：.dwg → (ODAFC)→ .dxf → ezdxf → 结构化数据

    Returns:
        DWGContent 或 None
    """
    path = Path(dwg_path)
    if not path.exists():
        return None

    ext = path.suffix.lower()

    # DXF 文件 —— 直接解析
    if ext == ".dxf":
        return parse_dxf_to_content(str(path), path.name)

    # DWG 文件 —— 需要转换
    # 先检查是否有同名 DXF
    dxf_path = str(path.with_suffix(".dxf"))
    if not os.path.exists(dxf_path):
        dxf_path = str(path.with_suffix(".DXF"))

    if os.path.exists(dxf_path):
        return parse_dxf_to_content(dxf_path, path.name)

    # 自动转换
    if auto_convert:
        dxf_path = convert_dwg_to_dxf(dwg_path)
        if dxf_path:
            return parse_dxf_to_content(dxf_path, path.name)

    return None


def parse_dwg_batch(
    dwg_files: List[str],
    progress_callback=None
) -> List[DWGContent]:
    """
    批量解析 DWG 文件

    Args:
        dwg_files: DWG 文件路径列表
        progress_callback: 进度回调 (current, total, filename)

    Returns:
        DWGContent 列表
    """
    # 先批量转换
    if progress_callback:
        progress_callback(0, len(dwg_files), "准备转换 DWG 文件...")

    results = []
    for i, dwg_path in enumerate(dwg_files):
        if progress_callback:
            progress_callback(i + 1, len(dwg_files), f"解析: {Path(dwg_path).name}")

        content = parse_dwg(dwg_path, auto_convert=True)
        if content:
            results.append(content)

    return results



def _detect_discipline(filename: str, text_entities: List[Dict]) -> str:
    """从文件名/内容推断工程专业（SⅠ~SⅦ）"""
    # 按文件名模式（V4.9.4: 修复 Unicode 罗马数字单字符匹配）
    patterns = {
        "SⅠ": r"[Ss][ⅠI1]|[Ss]-? ?[ⅠI1]",
        "道路": r"SⅠ|道路|路面|路基|路床|路缘石|平面",
        "SⅡ": r"[Ss](?:Ⅱ|II|2)|[Ss]-? ?(?:Ⅱ|II|2)",
        "交通": r"SⅡ|交通|标志|标线|护栏|信号",
        "SⅢ": r"[Ss](?:Ⅲ|III|3)|[Ss]-? ?(?:Ⅲ|III|3)",
        "桥涵": r"SⅢ|桥涵|箱涵|涵洞",
        "SⅣ": r"[Ss](?:Ⅳ|IV|4)|[Ss]-? ?(?:Ⅳ|IV|4)",
        "排水": r"SⅣ|排水|雨水|污水|管道|检查井",
        "SⅤ": r"[Ss][ⅤV]|[Ss]-? ?[ⅤV]",
        "照明": r"SⅤ|照明|路灯",
        "SⅥ": r"[Ss](?:Ⅵ|VI|6)|[Ss]-? ?(?:Ⅵ|VI|6)",
        "电力": r"SⅥ|电力|电缆|配电",
        "SⅦ": r"[Ss](?:Ⅶ|VII|7)|[Ss]-? ?(?:Ⅶ|VII|7)",
        "通信": r"SⅦ|通信|电信|管线",
    }

    # 先按文件名匹配（V4.9.4: 倒序检查，长/多字符模式优先，防止 SⅠ 错匹配 SIV 等）
    for key in ["SⅦ", "SⅥ", "SⅤ", "SⅣ", "SⅢ", "SⅡ", "SⅠ"]:
        if re.search(patterns[key], filename):
            return key

    # 再按内容匹配
    all_text = " ".join([t["text"] for t in text_entities[:100]])
    for key in ["道路", "交通", "桥涵", "排水", "照明", "电力", "通信"]:
        if re.search(patterns[key], all_text):
            return key

    return "未知"


def _extract_title(text_entities: List[Dict]) -> str:
    """从文字实体中提取图纸标题"""
    # 找最大字高的 TEXT（通常在标题栏）
    for t in text_entities:
        text = t["text"].strip()
        if len(text) > 4 and (
            "图" in text or "表" in text or "设计" in text
            or "平面" in text or "断面" in text or "纵断" in text
        ):
            return text
    return ""


def extract_all_text(dwg_contents: List[DWGContent]) -> str:
    """
    将所有 DWG 解析结果汇总为纯文本，供 AI 分析使用

    Returns:
        汇总文本
    """
    parts = []
    for content in dwg_contents:
        parts.append(f"\n===== CAD图纸: {content.filename} =====")
        parts.append(f"专业: {content.discipline}")
        if content.description:
            parts.append(f"标题: {content.description}")

        # 表格优先
        for table in content.tables:
            parts.append("表格:")
            for row in table:
                parts.append(" | ".join(row))
            parts.append("")

        # 块属性
        if content.block_attributes:
            parts.append("图块属性:")
            for attr in content.block_attributes[:50]:
                parts.append(f"{attr['tag']} = {attr['value']}")
            parts.append("")

        # 文字列表
        parts.append("文字内容:")
        for t in content.text_entities[:200]:
            parts.append(f"  [{t['layer']}] {t['text']}")

    return "\n".join(parts)


def get_discipline_summary(dwg_contents: List[DWGContent]) -> List[Dict]:
    """
    获取各专业图纸汇总

    Returns:
        [{discipline, count, files}]
    """
    summary = {}
    for c in dwg_contents:
        disc = c.discipline
        if disc not in summary:
            summary[disc] = {"count": 0, "files": []}
        summary[disc]["count"] += 1
        summary[disc]["files"].append(c.filename)

    return [
        {"discipline": k, "count": v["count"], "files": v["files"]}
        for k, v in sorted(summary.items())
    ]
