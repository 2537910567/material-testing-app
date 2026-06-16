"""
Phase Perf: 大文件转换性能测试 (V4.9.4)
直接调用 Engine 函数，精确测量耗时/内存/策略。
无需 GUI，可在纯 Python 环境运行。
"""

import sys
import os
import json
import time
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.utils_perf import (
    TestResults, PerfTimer, PerfMeasurement,
    ResourceMonitor, get_file_size_mb
)

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    print("[WARN] psutil 未安装，内存/CPU 监控不可用")


# ============================================================
# 常量定义
# ============================================================
TEST_DATA_DIR = (r"C:\Users\Administrator\Documents\xwechat_files"
                  r"\wxid_i0tdmsi16kfg22_747a\msg\file\2026-06")
SI_CAD_DIR = os.path.join(TEST_DATA_DIR, "2、图纸CAD", "图纸CAD",
                          "SⅠ-道路工程一期施工图设计CAD")
TEMP_DRAINAGE_DIR = os.path.join(TEST_DATA_DIR, "2、图纸CAD", "1、临时排水CAD")
RESULT_DIR = r"C:\Users\Administrator\WorkBuddy\2026-06-10-19-13-41\test_results"

TEST_PDF_SMALL = os.path.join(TEST_DATA_DIR, "2025省站-材料检测送检指南_(客户版).pdf")
TEST_PDF_MEDIUM = os.path.join(TEST_DATA_DIR, "肇庆市大型产业集聚区（永莲大道）（检验、监测）.pdf")
TEST_PDF_LARGE = os.path.join(TEST_DATA_DIR, "SⅠ道路工程一期施工图设计.pdf")

TEST_DWG_LARGE_7MB = os.path.join(
    SI_CAD_DIR,
    "SⅠ-30 特殊路基处理平面布置图（布桩）-2025.3.11.dwg"
)
TEST_DWG_XLARGE_15MB = os.path.join(
    TEMP_DRAINAGE_DIR,
    "CIV-2~3、永莲大道（永安大道）临时排污平面设计图.dwg"
)


# ============================================================
# 工具函数
# ============================================================

def find_dwg(dir_path, keyword="", min_mb=0, max_mb=999):
    """按大小范围查找 DWG 文件。返回路径或 None。"""
    if not dir_path or not os.path.exists(dir_path):
        return None
    candidates = []
    for f in sorted(os.listdir(dir_path)):
        if not f.lower().endswith(".dwg"):
            continue
        if keyword and keyword.lower() not in f.lower():
            continue
        fp = os.path.join(dir_path, f)
        size_mb = os.path.getsize(fp) / (1024 * 1024)
        if min_mb <= size_mb <= max_mb:
            candidates.append((fp, size_mb))
    if candidates:
        target = (min_mb + max_mb) / 2
        candidates.sort(key=lambda x: abs(x[1] - target))
        return candidates[0][0]
    return None


def measure_operation(label, func, *args, **kwargs):
    """
    执行操作并测量性能指标。
    Returns:
        (result, PerfMeasurement)
    """
    proc = psutil.Process(os.getpid()) if HAS_PSUTIL else None
    mem_before = proc.memory_info().rss / (1024 * 1024) if proc else 0

    t = PerfTimer(label)
    result = None
    error = None
    monitor = None

    with t:
        try:
            if HAS_PSUTIL:
                monitor = ResourceMonitor(interval=0.5)
                monitor.start()

            result = func(*args, **kwargs)

            if monitor:
                monitor.stop()
        except Exception as e:
            error = str(e)

    mem_after = proc.memory_info().rss / (1024 * 1024) if proc else 0
    peak_mem = max(mem_after, mem_before)

    m = PerfMeasurement(
        test_id=label,
        operation=label.split(":")[0] if ":" in label else label,
        duration_ms=t.duration_ms,
        peak_memory_mb=round(peak_mem, 1),
        memory_delta_mb=round(mem_after - mem_before, 1),
        error=error,
    )
    if monitor and not error:
        r = monitor.get_report()
        if "error" not in r:
            cpu_peak = r.get("cpu", {}).get("peak_pct", "?")
            mem_peak = r.get("memory", {}).get("peak_mb", "?")
            handles = r.get("handles", {}).get("peak", "?")
            m.notes = ("cpu_peak=" + str(cpu_peak) + "%, "
                        "mem_peak=" + str(mem_peak) + "MB, "
                        "handles_peak=" + str(handles))
    return result, m


def print_perf_header(label, file_path):
    """打印测试开始信息"""
    sz = get_file_size_mb(file_path) if file_path else 0
    bname = os.path.basename(file_path) if file_path else "?"
    msg = ("\n  [" + str(label) + "] " + str(bname) +
            " (" + str(round(sz, 1)) + "MB)")
    print(msg)


# ============================================================
# TP-DWG01: 15.2MB 超大 DWG -> text_only 策略验证
# ============================================================
def perf_dwg_01_xlarge_text_only(results):
    """TP-DWG01: 15.2MB DWG - text_only 策略 + ODAFC 转换时间测量"""
    from app.engine.file_profiler import FileProfiler
    from app.engine.dwg_parser import convert_cad_with_strategy, _has_chinese_chars

    dwg_path = TEST_DWG_XLARGE_15MB
    if not os.path.exists(dwg_path):
        results.add("TP-DWG01", "15.2MB DWG text_only", False, 0,
                    "文件不存在: " + str(dwg_path))
        return

    print_perf_header("DWG01", dwg_path)
    file_size_mb = get_file_size_mb(dwg_path)

    # Step 1: Profile (策略判定)
    prof_result, m_profile = measure_operation(
        "DWG01:profile", FileProfiler.profile_cad, dwg_path
    )
    m_profile.file_path = dwg_path
    m_profile.file_size_mb = file_size_mb
    m_profile.file_type = "cad"
    if prof_result:
        m_profile.strategy = prof_result.strategy
        reason = prof_result.strategy_reason
    else:
        m_profile.strategy = ""
        reason = "N/A"
    m_profile.notes = ("reason=" + str(reason) + ", "
                        "has_chinese_path=" + str(_has_chinese_chars(dwg_path)))
    results.add_perf(m_profile)

    strategy = prof_result.strategy if prof_result else "text_only"
    print("    Profile -> strategy=" + str(strategy) + " (" + str(reason) + ")")

    # Step 2: 按 strategy 执行转换
    conv_result, m_conv = measure_operation(
        "DWG01:convert_" + str(strategy),
        convert_cad_with_strategy, dwg_path, strategy
    )
    m_conv.file_path = dwg_path
    m_conv.file_size_mb = file_size_mb
    m_conv.file_type = "cad"
    m_conv.strategy = strategy
    if conv_result and isinstance(conv_result, dict):
        png_count = len(conv_result.get("png_paths", []))
        text_len = len(conv_result.get("text", ""))
        m_conv.output_count = png_count
        note = ("png=" + str(png_count) +
                 ", text_chars=" + str(text_len) +
                 ", error=" + str(conv_result.get("error", "None")))
        m_conv.notes = note
    results.add_perf(m_conv)

    has_text = (conv_result and isinstance(conv_result, dict)
                and len(conv_result.get("text", "")) > 10)
    passed = prof_result is not None and (has_text or m_conv.output_count > 0)

    details = {
        "file_size_mb": file_size_mb,
        "strategy": strategy,
        "strategy_reason": reason,
        "png_count": m_conv.output_count,
        "text_length": len(conv_result.get("text", "")) if conv_result else 0,
        "has_chinese_path": _has_chinese_chars(dwg_path),
        "duration_s": round(m_conv.duration_ms / 1000, 1),
        "peak_memory_mb": m_conv.peak_memory_mb,
    }
    results.add("TP-DWG01", "15.2MB DWG [" + str(strategy) + "]",
               passed, m_conv.duration_ms, details=details)
    dur_s = round(m_conv.duration_ms / 1000, 1)
    peak = round(m_conv.peak_memory_mb, 0)
    status = "PASS" if passed else "FAIL"
    print("    [" + status + "] - " + str(dur_s) + "s, peak=" +
          str(peak) + "MB, strategy=" + str(strategy))


# ============================================================
# TP-DWG02: 7.2MB 大 DWG -> 策略边界测试
# ============================================================
def perf_dwg_02_large_boundary(results):
    """TP-DWG02: 7.2MB DWG - CAD_SIZE_HUGE(7.0MB) 阈值边界验证"""
    from app.engine.file_profiler import FileProfiler
    from app.engine.dwg_parser import convert_cad_with_strategy

    dwg_path = TEST_DWG_LARGE_7MB
    if not os.path.exists(dwg_path):
        dwg_path = find_dwg(SI_CAD_DIR, "", 5, 10)
    if not dwg_path or not os.path.exists(dwg_path):
        results.add("TP-DWG02", "7.2MB DWG 策略边界", False, 0,
                    "未找到 5-10MB 的 DWG 测试文件")
        return

    print_perf_header("DWG02", dwg_path)
    file_size_mb = get_file_size_mb(dwg_path)

    # Step 1: Profile
    prof, m1 = measure_operation("DWG02:profile", FileProfiler.profile_cad, dwg_path)
    m1.file_path = dwg_path
    m1.file_size_mb = file_size_mb
    m1.file_type = "cad"
    if prof:
        m1.strategy = prof.strategy
        reason = prof.strategy_reason
    else:
        m1.strategy = ""
        reason = "?"
    results.add_perf(m1)

    strategy = prof.strategy if prof else "unknown"
    print("    Profile -> strategy=" + str(strategy) + " (" + str(reason) + ")")

    # Step 2: Convert with determined strategy
    conv, m2 = measure_operation("DWG02:convert_" + str(strategy),
                                  convert_cad_with_strategy, dwg_path, strategy)
    m2.file_path = dwg_path
    m2.file_size_mb = file_size_mb
    m2.file_type = "cad"
    m2.strategy = strategy
    if conv and isinstance(conv, dict):
        m2.output_count = len(conv.get("png_paths", []))
        note = ("text_len=" + str(len(conv.get("text", ""))) +
                 ", err=" + str(conv.get("error", "None")))
        m2.notes = note
    results.add_perf(m2)

    passed = prof is not None
    details = {"strategy": strategy,
               "reason": reason,
               "png_count": m2.output_count,
               "peak_mb": m2.peak_memory_mb}
    results.add("TP-DWG02", "7.2MB DWG [" + str(strategy) + "] (" + str(round(file_size_mb, 1)) + "MB)",
               passed, m2.duration_ms, details=details)
    dur_s = round(m2.duration_ms / 1000, 1)
    status = "PASS" if passed else "FAIL"
    print("    [" + status + "] - " + str(dur_s) + "s, strategy=" +
          str(strategy) + ", png=" + str(m2.output_count))


# ============================================================
# TP-DWG03: 3-4MB 中型 DWG -> reduced_render 渲染
# ============================================================
def perf_dwg_03_medium_reduced(results):
    """TP-DWG03: 3-4MB DWG - reduced_render 渲染 (含 matplotlib PNG 输出)"""
    from app.engine.file_profiler import FileProfiler
    from app.engine.dwg_parser import convert_cad_with_strategy

    dwg_path = find_dwg(SI_CAD_DIR, "", 2.5, 5)
    if not dwg_path:
        dwg_path = find_dwg(SI_CAD_DIR, "", 1, 6)
    if not dwg_path:
        results.add("TP-DWG03", "3-4MB DWG reduced_render", False, 0,
                    "未找到 1-6MB 的 DWG 测试文件")
        return

    print_perf_header("DWG03", dwg_path)
    file_size_mb = get_file_size_mb(dwg_path)

    # 强制使用 reduced_render (而非自动策略)
    strategy = "reduced_render"
    conv, m = measure_operation("DWG03:convert_" + str(strategy),
                                convert_cad_with_strategy, dwg_path, strategy)
    m.file_path = dwg_path
    m.file_size_mb = file_size_mb
    m.file_type = "cad"
    m.strategy = strategy
    if conv and isinstance(conv, dict):
        m.output_count = len(conv.get("png_paths", []))
        note = ("png=" + str(m.output_count) +
                    ", text=" + str(len(conv.get("text", ""))) +
                    ", err=" + str(conv.get("error", "")))
        m.notes = note
    results.add_perf(m)

    has_png = m.output_count and m.output_count > 0
    has_text = conv and isinstance(conv, dict) and len(conv.get("text", "")) > 0
    passed = conv is not None and (has_png or has_text)

    details = {"strategy": strategy, "png_count": m.output_count,
               "has_text_content": has_text,
               "peak_mb": m.peak_memory_mb, "error": m.error}
    results.add("TP-DWG03", "3-4MB DWG [" + str(strategy) + "] (" + str(round(file_size_mb, 1)) + "MB)",
               passed, m.duration_ms, details=details)
    dur_s = round(m.duration_ms / 1000, 1)
    status = "PASS" if passed else "FAIL"
    print("    [" + status + "] - " + str(dur_s) + "s, png=" +
          str(m.output_count))


# ============================================================
# TP-DWG04: 批量 DWG 吞吐量测试
# ============================================================
def perf_dwg_04_batch_throughput(results):
    """TP-DWG04: 批量多个 DWG - convert_dwg_batch 并行吞吐量测量"""
    from app.engine.dwg_parser import convert_dwg_batch

    # 收集最多 10 个小型 DWG (快速完成批量测试)
    dwg_files = []
    if os.path.exists(SI_CAD_DIR):
        for f in sorted(os.listdir(SI_CAD_DIR)):
            if f.endswith(".dwg"):
                fp = os.path.join(SI_CAD_DIR, f)
                sz_mb = os.path.getsize(fp) / (1024 * 1024)
                if 0.1 <= sz_mb <= 3:
                    dwg_files.append((fp, sz_mb))
                if len(dwg_files) >= 10:
                    break

    if len(dwg_files) < 3:
        results.add("TP-DWG04", "批量 DWG 吞吐", False, 0,
                    "仅找到 " + str(len(dwg_files)) + " 个合适 DWG 文件 (需要>=3)")
        return

    # 只取文件路径列表
    dwg_paths = [fp for fp, _ in dwg_files]
    total_size = sum(sz for _, sz in dwg_files)
    output_dir = tempfile.mkdtemp(prefix="dwg_batch_test_")

    print("\n  [DWG04] 批量: " + str(len(dwg_files)) + " 个文件, 总 " +
          str(round(total_size, 1)) + "MB")
    for fp, sz in dwg_files:
        print("           " + str(os.path.basename(fp)) + " (" +
              str(round(sz, 2)) + "MB)")

    batch_result, m = measure_operation(
        "DWG04:batch_convert",
        convert_dwg_batch, dwg_paths, output_dir
    )
    m.file_type = "cad"
    m.operation = "convert_dwg_batch"
    m.output_count = len(batch_result) if batch_result else 0
    m.notes = ("files_submitted=" + str(len(dwg_paths)) +
                 ", success=" + str(m.output_count))

    # 计算吞吐量
    duration_s = m.duration_ms / 1000
    if duration_s > 0:
        throughput = m.output_count / duration_s * 60
    else:
        throughput = 0
    m.notes = m.notes + ", throughput=" + str(round(throughput, 1)) + " files/min"
    results.add_perf(m)

    passed = batch_result is not None and m.output_count >= len(dwg_paths) * 0.5
    details = {
        "file_count": len(dwg_paths),
        "success_count": m.output_count,
        "total_size_mb": round(total_size, 1),
        "throughput_per_min": round(throughput, 1),
        "duration_s": round(duration_s, 1),
        "success_rate": round(m.output_count / len(dwg_paths) * 100, 1) if dwg_files else 0,
    }
    results.add("TP-DWG04", "批量" + str(len(dwg_files)) + " DWG 吞吐",
               passed, m.duration_ms, details=details)
    dur_s = round(duration_s, 1)
    status = "PASS" if passed else "FAIL"
    print("    [" + status + "] - " + str(m.output_count) + "/" +
          str(len(dwg_paths)) + " 成功, " +
          str(round(throughput, 1)) + " 文件/分钟")


# ============================================================
# TP-DWG05: 中文路径 vs ASCII 路径性能对比
# ============================================================
def perf_dwg_05_chinese_path(results):
    """TP-DWG05: 中文路径 ODAFC 开销 - 对比原始路径与 ASCII 复制后路径"""
    from app.engine.dwg_parser import convert_dwg_to_dxf, _copy_to_ascii_temp, _has_chinese_chars

    # 选一个小 DWG 用于快速对比
    dwg_path = find_dwg(SI_CAD_DIR, "", 0.2, 2)
    if not dwg_path:
        results.add("TP-DWG05", "中文路径开销", False, 0, "未找到 0.2-2MB 小 DWG")
        return

    print_perf_header("DWG05", dwg_path)
    file_size_mb = get_file_size_mb(dwg_path)

    # 如果原始路径没有中文，复制到中文路径来制造中文路径场景
    cleanup_dir = None
    original_is_chinese = _has_chinese_chars(dwg_path)
    if not original_is_chinese:
        chinese_dir = tempfile.mkdtemp(prefix="\u6d4b\u8bd5\u4e2d\u6587\u8def\u5f84_")
        chinese_path = os.path.join(chinese_dir, os.path.basename(dwg_path))
        shutil.copy2(dwg_path, chinese_path)
        dwg_path = chinese_path
        cleanup_dir = chinese_dir
        print("    制造中文路径: " + str(chinese_path))

    print("    有中文字符: " + str(_has_chinese_chars(dwg_path)))

    # A: 直接从中文路径调用 (内部会走 ASCII 临时目录降级逻辑)
    _, m_direct = measure_operation("DWG05:direct_from_path", convert_dwg_to_dxf, dwg_path)
    m_direct.file_path = dwg_path
    m_direct.file_size_mb = file_size_mb
    m_direct.file_type = "cad"
    path_type = "chinese" if _has_chinese_chars(dwg_path) else "ascii"
    m_direct.notes = ("path_type=" + str(path_type) + ", " +
                       "dxf=" + ("ok" if not m_direct.error else "fail") + "}")
    results.add_perf(m_direct)

    # B: 手动 ASCII 复制后再调用 (模拟优化后的流程)
    ascii_copy_time = 0
    t_copy = PerfTimer("DWG05:manual_ascii_copy")
    with t_copy:
        ascii_path = _copy_to_ascii_temp(dwg_path)
        if ascii_path:
            ascii_copy_time = t_copy.duration_ms
            _, m_ascii_op = measure_operation("DWG05:convert_after_ascii_copy",
                                               convert_dwg_to_dxf, ascii_path)
            m_ascii_op.file_path = ascii_path
            m_ascii_op.file_type = "cad"
            note = ("copy_cost=" + str(round(ascii_copy_time, 0)) + "ms, " +
                                 "dxf=" + ("ok" if not m_ascii_op.error else "fail") + "}")
            m_ascii_op.notes = note
            results.add_perf(m_ascii_op)

    # 计算开销百分比
    overhead_pct = 0
    if m_ascii_op.error is None and m_direct.error is None:
        base_time = max(m_ascii_op.duration_ms, 1)
        diff = m_direct.duration_ms - m_ascii_op.duration_ms
        overhead_pct = diff / base_time * 100

    details = {"direct_ms": round(m_direct.duration_ms, 0),
               "ascii_copy_ms": round(ascii_copy_time, 0),
               "ascii_convert_ms": round(m_ascii_op.duration_ms, 0),
               "overhead_pct": round(overhead_pct, 1),
               "has_chinese": _has_chinese_chars(dwg_path),
               "original_was_chinese": original_is_chinese}
    passed = m_direct.error is None or m_ascii_op.error is None
    results.add("TP-DWG05", "中文路径开销 (" + str(file_size_mb) + "MB)",
               passed, max(m_direct.duration_ms, m_ascii_op.duration_ms),
               details=details)
    print("    direct=" + str(round(m_direct.duration_ms, 0)) + "ms, " +
          "ascii_total=" + str(round(ascii_copy_time + m_ascii_op.duration_ms, 0)) + "ms, " +
          "overhead=" + str(round(overhead_pct, 0)) + "%")

    # 清理中文临时目录
    if cleanup_dir and os.path.exists(cleanup_dir):
        shutil.rmtree(cleanup_dir, ignore_errors=True)


# ============================================================
# TP-PDF01: 183MB PDF -> file_profiler.profile_pdf (策略判定)
# ============================================================
def perf_pdf_01_xlarge_profile(results):
    """TP-PDF01: 183MB 超大 PDF - 预分析/逐页分类耗时测量"""
    from app.engine.file_profiler import FileProfiler

    pdf_path = TEST_PDF_LARGE
    if not os.path.exists(pdf_path):
        results.add("TP-PDF01", "183MB PDF 预分析", False, 0,
                    "文件不存在: " + str(pdf_path))
        return

    print_perf_header("PDF01", pdf_path)
    file_size_mb = get_file_size_mb(pdf_path)

    prof, m = measure_operation("PDF01:profile_pdf", FileProfiler.profile_pdf, pdf_path)
    m.file_path = pdf_path
    m.file_size_mb = file_size_mb
    m.file_type = "pdf"
    if prof:
        m.strategy = prof.strategy
        m.output_count = prof.total_pages
        type_counts = prof.metadata.get("type_counts", {})
        sampling = prof.metadata.get("sampling", "?")
        note = ("pages=" + str(m.output_count) +
                    ", sampling=" + str(sampling) +
                    ", types=" + str(type_counts) +
                    ", reason=" + str(prof.strategy_reason))
        m.notes = note
    else:
        m.strategy = ""
    results.add_perf(m)

    passed = prof is not None and prof.total_pages > 0
    details = {"pages": m.output_count,
               "strategy": m.strategy,
               "sampling": sampling if prof else "?",
               "type_counts": type_counts if prof else {},
               "duration_s": round(m.duration_ms / 1000, 1),
               "peak_memory_mb": m.peak_memory_mb}
    results.add("TP-PDF01", "183MB PDF 预分析 (" + str(file_size_mb) + "MB)",
               passed, m.duration_ms, details=details)
    dur_s = round(m.duration_ms / 1000, 1)
    status = "PASS" if passed else "FAIL"
    print("    [" + status + "] - " + str(dur_s) + "s, " +
          str(m.output_count) + " 页, sampling=" + str(sampling if prof else "?)")


# ============================================================
# TP-PDF02: 183MB PDF -> extract_pdf_content (文字提取)
# ============================================================
def perf_pdf_02_xlarge_text(results):
    """TP-PDF02: 183MB 超大 PDF - 全文提取 (内存密集型操作)"""
    from app.engine.pdf_parser import extract_pdf_content

    pdf_path = TEST_PDF_LARGE
    if not os.path.exists(pdf_path):
        results.add("TP-PDF02", "183MB PDF 文字提取", False, 0, "文件不存在")
        return

    print_perf_header("PDF02", pdf_path)
    file_size_mb = get_file_size_mb(pdf_path)

    content, m = measure_operation("PDF02:extract_text", extract_pdf_content, pdf_path)
    m.file_path = pdf_path
    m.file_size_mb = file_size_mb
    m.file_type = "pdf"
    if content and isinstance(content, dict):
        text_len = len(content.get("text", ""))
        table_count = len(content.get("tables", []))
        pages = content.get("pages", 0)
        truncated = content.get("truncated", False)
        m.output_count = text_len
        note = ("chars=" + str(text_len) +
                   ", tables=" + str(table_count) +
                   ", pages=" + str(pages) +
                   ", truncated=" + str(truncated))
        m.notes = note
    else:
        m.output_count = 0
    results.add_perf(m)

    passed = content is not None and isinstance(content, dict) and \
             len(content.get("text", "")) > 100
    details = {"text_chars": m.output_count,
               "tables": len(content.get("tables", [])) if content else 0,
               "pages": content.get("pages", 0) if content else 0,
               "truncated": content.get("truncated", False) if content else False,
               "duration_s": round(m.duration_ms / 1000, 1),
               "peak_memory_mb": m.peak_memory_mb}
    results.add("TP-PDF02", "183MB PDF 文字提取 (" + str(file_size_mb) + "MB)",
               passed, m.duration_ms, details=details)
    dur_s = round(m.duration_ms / 1000, 1)
    peak = round(m.peak_memory_mb, 0)
    status = "PASS" if passed else "FAIL"
    print("    [" + status + "] - " + str(dur_s) + "s, " +
          str(m.output_count) + " chars, peak=" + str(peak) + "MB")


# ============================================================
# TP-PDF03: 183MB PDF -> 前30页渲染测试
# ============================================================
def perf_pdf_03_xlarge_render30(results):
    """TP-PDF03: 183MB 超大 PDF - 前30页渲染 (串行渲染性能基准)"""
    from app.engine.file_profiler import FileProfiler
    from app.engine.pdf_parser import extract_pdf_with_strategy

    pdf_path = TEST_PDF_LARGE
    if not os.path.exists(pdf_path):
        results.add("TP-PDF03", "183MB PDF 渲染30页", False, 0, "文件不存在")
        return

    print_perf_header("PDF03", pdf_path)
    file_size_mb = get_file_size_mb(pdf_path)

    # 先做 page_types (只采样几页用于确定类型)
    prof = FileProfiler.profile_pdf(pdf_path)
    page_types = prof.page_types if prof else {}

    # 取前 30 页的类型子集
    page_types_30 = {}
    count = 0
    for k in list(page_types.keys()):
        if count >= 30:
            break
        page_types_30[k] = page_types[k]
        count += 1

    output_dir = tempfile.mkdtemp(prefix="pdf_render30_")
    total_p = prof.total_pages if prof else "?"
    print("    页面类型采样: " + str(len(page_types_30)) + " 页 (总页数=" +
          str(total_p) + ")")

    render_result, m = measure_operation(
        "PDF03:render_30pages",
        extract_pdf_with_strategy, pdf_path, page_types_30, output_dir
    )
    m.file_path = pdf_path
    m.file_size_mb = file_size_mb
    m.file_type = "pdf"
    if render_result and isinstance(render_result, dict):
        png_count = len(render_result.get("png_paths", []))
        text_len = len(render_result.get("text", ""))
        rendered_pages = render_result.get("pages", 0)
        m.output_count = png_count
        note = ("png=" + str(png_count) +
                    ", text_chars=" + str(text_len) +
                    ", pages_claimed=" + str(rendered_pages) + ")")
        m.notes = note
    results.add_perf(m)

    avg_per_page_ms = m.duration_ms / 30 if m.duration_ms > 0 else 0
    passed = render_result is not None
    details = {"page_types_sampled": len(page_types_30),
               "total_page_count": prof.total_pages if prof else 0,
               "png_count": m.output_count,
               "duration_s": round(m.duration_ms / 1000, 1),
               "avg_per_page_ms": round(avg_per_page_ms, 0),
               "peak_memory_mb": m.peak_memory_mb}
    results.add("TP-PDF03", "183MB PDF 渲染前30页 (" + str(file_size_mb) + "MB)",
               passed, m.duration_ms, details=details)
    dur_s = round(m.duration_ms / 1000, 1)
    status = "PASS" if passed else "FAIL"
    print("    [" + status + "] - " + str(dur_s) + "s, " +
          str(m.output_count) + " PNGs, " +
          str(round(avg_per_page_ms, 0)) + "ms/page")


# ============================================================
# TP-PDF04: 18.4MB PDF -> 完整管线 (文字+表格)
# ============================================================
def perf_pdf_04_medium_full_pipeline(results):
    """TP-PDF04: 18.4MB 中等 PDF - 完整提取管线 (含表格)"""
    from app.engine.pdf_parser import extract_pdf_content

    pdf_path = TEST_PDF_MEDIUM
    if not os.path.exists(pdf_path):
        results.add("TP-PDF04", "18.4MB PDF 完整管线", False, 0, "文件不存在")
        return

    print_perf_header("PDF04", pdf_path)
    file_size_mb = get_file_size_mb(pdf_path)

    # 完整内容提取 (<50MB 会包含表格)
    content, m = measure_operation("PDF04:full_pipeline", extract_pdf_content, pdf_path)
    m.file_path = pdf_path
    m.file_size_mb = file_size_mb
    m.file_type = "pdf"
    if content and isinstance(content, dict):
        text_len = len(content.get("text", ""))
        tables = content.get("tables", [])
        table_count = len(tables)
        table_rows = 0
        for t in tables:
            table_rows += len(t.get("rows", []))
        pages = content.get("pages", 0)
        m.output_count = text_len
        note = ("chars=" + str(text_len) +
                    ", tables=" + str(table_count) +
                    ", table_rows=" + str(table_rows) +
                    ", pages=" + str(pages))
        m.notes = note
    results.add_perf(m)

    # 与小 PDF 效率对比
    small_efficiency_note = ""
    small_path = TEST_PDF_SMALL
    if os.path.exists(small_path):
        _, sm = measure_operation("PDF04:small_compare", extract_pdf_content, small_path)
        if sm.duration_ms > 0 and m.output_count > 0:
            rate_big = m.output_count / (m.duration_ms / 1000)
            small_sz = get_file_size_mb(small_path)
            small_efficiency_note = ("small(" + str(round(small_sz, 1)) +
                                     "MB)=" + str(round(sm.duration_ms, 0)) + "ms")

    passed = content is not None and isinstance(content, dict)
    rate_str = ""
    if m.duration_ms > 0 and m.output_count > 0:
        rate_str = str(round(m.output_count / (m.duration_ms / 1000), 0))
    details = {"text_chars": m.output_count,
               "tables": table_count if content else 0,
               "table_rows": table_rows if content else 0,
               "pages": content.get("pages", 0) if content else 0,
               "duration_s": round(m.duration_ms / 1000, 1),
               "chars_per_sec": rate_str,
               "peak_memory_mb": m.peak_memory_mb,
               "compare_small": small_efficiency_note}
    results.add("TP-PDF04", "18.4MB PDF 完整管线 (" + str(file_size_mb) + "MB)",
               passed, m.duration_ms, details=details)
    dur_s = round(m.duration_ms / 1000, 1)
    status = "PASS" if passed else "FAIL"
    print("    [" + status + "] - " + str(dur_s) + "s, " +
          str(m.output_count) + " chars, " + rate_str + " chars/s")


# ============================================================
# 主执行入口
# ============================================================
def main():
    """执行全部 Phase Perf 测试"""
    results = TestResults("phase-perf", "大文件转换性能基准测试 V4.9.4")

    print("=" * 72)
    print("  Phase Perf: 大文件转换性能基准测试 (V4.9.4)")
    print("=" * 72)
    if not HAS_PSUTIL:
        print("  [WARN] psutil 未安装 -- 内存/CPU 数据将缺失")
        print("         安装: pip install psutil")
    print()

    # Part A: DWG 性能测试
    print("  +-- DWG Performance Tests --+")
    perf_dwg_01_xlarge_text_only(results)     # 15.2MB text_only
    perf_dwg_02_large_boundary(results)        # 7.2MB boundary
    perf_dwg_03_medium_reduced(results)        # 3-4MB reduced_render
    perf_dwg_04_batch_throughput(results)      # Batch throughput
    perf_dwg_05_chinese_path(results)          # Chinese path overhead

    # Part B: PDF 性能测试
    print("\n  +-- PDF Performance Tests --+")
    perf_pdf_01_xlarge_profile(results)        # 183MB profile
    perf_pdf_02_xlarge_text(results)           # 183MB text extraction
    perf_pdf_03_xlarge_render30(results)       # 183MB render first 30 pages
    perf_pdf_04_medium_full_pipeline(results)   # 18.4MB full pipeline

    # 摘要输出
    summary = results.summary
    total_dur_s = sum(r["duration_ms"] for r in results.results) / 1000

    print("\n" + "=" * 72)
    pct = summary.get("pass_rate_pct", 0)
    print("  Phase Perf 完成: " + str(summary["passed"]) + "/" +
          str(summary["total"]) + " 通过 (" + str(round(pct, 1)) + "%)")
    print("  总耗时: " + str(round(total_dur_s, 1)) + "s (~" +
          str(round(total_dur_s / 60, 1)) + "min)")
    print("  平均: " + str(int(summary.get("avg_duration_ms", 0))) + "ms/测试")
    print("=" * 72)

    # 打印失败项
    failures = summary.get("failures", [])
    if failures:
        print("\n  失败项:")
        for f_item in failures:
            err = str(f_item.get("error", ""))[:200]
            print("    FAIL | " + str(f_item["id"]) + " | " +
                  str(f_item["name"]) + ": " + err)

    # 保存 JSON 报告
    json_path = os.path.join(RESULT_DIR, "phase_perf_results.json")
    saved_json = results.save(json_path)
    print("\n  JSON 报告: " + str(saved_json))

    # 保存 Markdown 人读报告
    md_path = _save_markdown_report(results)
    print("  Markdown 报告: " + str(md_path))

    return len(failures) == 0


def _save_markdown_report(results):
    """生成人读友好的 Markdown 报告"""
    summary = results.summary
    md_path = os.path.join(RESULT_DIR, "phase_perf_results.md")
    lines = [
        "# Phase Perf 性能测试报告",
        "",
        "> 生成时间: " + str(results.timestamp),
        "> 维度: " + str(results.dimension) + " - " + str(results.description),
        "> 总体: " + str(summary["passed"]) + "/" + str(summary["total"]) +
        " 通过 (" + str(round(summary.get("pass_rate_pct", 0), 1)) + "%)",
        "",
        "## 性能测量详情",
        "",
        "| 测试ID | 操作 | 文件大小(MB) | 策略 | 耗时(ms) | 峰值内存(MB) | 内存增量(MB) | 状态 | 备注 |",
        "|--------|------|-------------|------|----------|-------------|-------------|------|------|",
    ]
    for pm in results.perf_measurements:
        status = "**OK**" if not pm.error else "**ERR**"
        fname = os.path.basename(pm.file_path) if pm.file_path else "-"
        if len(fname) > 30:
            fname = fname[:27] + "..."
        row = ("| `" + str(pm.test_id) + "` | " + str(pm.operation) +
                " | " + str(round(pm.file_size_mb, 1)) + " | " +
                str(pm.strategy or "-") + " | " +
                str(int(pm.duration_ms)) + " | " +
                str(round(pm.peak_memory_mb, 0)) + " | " +
                str(round(pm.memory_delta_mb, 0)) + " | " + status + " | " +
                str((pm.notes or "-")[:60]) + " |")
        lines.append(row)

    lines.append("\n> 平均耗时: " + str(int(summary.get("avg_duration_ms", 0))) + "ms/测试\n")
    lines.append("\n## 测试结果\n")
    for r in results.results:
        status = "**PASS**" if r["passed"] else "**FAIL**"
        detail_str = ""
        if r.get("details"):
            d = str(r["details"])
            if len(d) > 120:
                d = d[:117] + "..."
            detail_str = d.replace("|", "\\|").replace("\n", " ")
        line = ("- [" + status + "] **`" + str(r["id"]) + "`**: " +
                 str(r["name"]) + " (`" + str(int(r["duration_ms"])) + "ms`)")
        lines.append(line)
        if detail_str:
            lines.append("  - " + detail_str)

    Path(md_path).parent.mkdir(parents=True, exist_ok=True)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return md_path


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
