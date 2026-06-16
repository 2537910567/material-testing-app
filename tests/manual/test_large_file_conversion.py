"""
大文件转换性能测试（独立进程版）
每次只测一个文件，Python进程退出自动释放全部内存。

用法:
    py -3 -B tests/manual/test_large_file_conversion.py
"""

import os
import sys
import time
import gc
import tracemalloc
import tempfile
import shutil
import logging
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# ═══════════════════════════════════════════════════════════════
# 抑制第三方库 DEBUG 日志 — 关键!
# ═══════════════════════════════════════════════════════════════
for noisy in ["pdfminer", "PIL", "matplotlib", "urllib3", "requests"]:
    logging.getLogger(noisy).setLevel(logging.WARNING)

BASE_DIR = Path(r"C:\Users\Administrator\Documents\xwechat_files\wxid_i0tdmsi16kfg22_747a\msg\file\2026-06")

PDF_TESTS = [
    ("S1道路183MB", BASE_DIR / "SⅠ道路工程一期施工图设计.pdf"),
    ("S2交通91MB",  BASE_DIR / "1、肇庆市大型产业集聚区(肇庆新区片)配套基础设施建设项目一标段(永莲大道)PDF图纸" / "SⅡ交通工程一期施工图设计.pdf"),
    ("S4排水67MB",  BASE_DIR / "1、肇庆市大型产业集聚区(肇庆新区片)配套基础设施建设项目一标段(永莲大道)PDF图纸" / "SⅣ排水工程一期施工图设计.pdf"),
]

CAD_TESTS = [
    ("临时排污16MB",    BASE_DIR / "2、图纸CAD" / "1、临时排水CAD" / "CIV-2~3、永莲大道（永安大道）临时排污平面设计图.dwg"),
    ("特殊路基7.2MB",   BASE_DIR / "2、图纸CAD" / "图纸CAD" / "SⅠ-道路工程一期施工图设计CAD" / "SⅠ-30 特殊路基处理平面布置图（布桩）-2025.3.11.dwg"),
]


def fmt_size(b):
    for u in ["B","KB","MB","GB"]:
        if b < 1024: return f"{b:.1f}{u}"
        b /= 1024


def fmt_time(s):
    if s < 1:   return f"{s*1000:.0f}ms"
    elif s < 60: return f"{s:.1f}s"
    else:
        m, sec = divmod(s, 60)
        return f"{int(m)}m{int(sec)}s"


def test_one_pdf(label, pdf_path, temp_root):
    """测试单个PDF：预分析 + 转换，记录耗时"""
    from app.engine.file_profiler import FileProfiler
    from app.engine.pdf_parser import extract_pdf_with_strategy

    print(f"\n{'='*60}", flush=True)
    print(f"[PDF] {label}", flush=True)
    print(f"  文件: {pdf_path}", flush=True)

    if not pdf_path.exists():
        print(f"  ERROR 文件不存在!", flush=True)
        return None

    fsize = pdf_path.stat().st_size
    print(f"  大小: {fmt_size(fsize)}", flush=True)

    # ── 预分析 ──
    gc.collect()
    t0 = time.perf_counter()
    try:
        profile = FileProfiler.profile_pdf(str(pdf_path))
    except Exception as e:
        print(f"  ERROR 预分析失败: {e}", flush=True)
        return None
    t1 = time.perf_counter()

    type_counts = {}
    for pt in profile.page_types.values():
        type_counts[pt] = type_counts.get(pt, 0) + 1
    print(f"  预分析: {fmt_time(t1-t0)} | {profile.total_pages}页 | 策略={profile.strategy}", flush=True)
    print(f"  页类型: {type_counts}", flush=True)

    # ── 转换 ──
    gc.collect()
    out_dir = temp_root / "pdf" / Path(pdf_path).stem
    out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    try:
        result = extract_pdf_with_strategy(str(pdf_path), profile.page_types, str(out_dir))
    except Exception as e:
        print(f"  ERROR 转换失败: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return None
    t1 = time.perf_counter()

    png_n = len(result.get("png_paths", []))
    text_n = len(result.get("text", ""))
    err = result.get("error", "")

    # 释放 PDF 引用
    del result
    gc.collect()

    print(f"  转换: {fmt_time(t1-t0)} | {png_n} PNG | {text_n:,}字符", flush=True)
    if err:
        print(f"  WARNING: {err}", flush=True)

    return {
        "label": label,
        "pages": profile.total_pages,
        "strategy": profile.strategy,
        "page_types": type_counts,
        "profile_time": t1 - t0 if 't1' in dir() else 0,  # will fix below
        "convert_time": t1 - t0 if 't0' in dir() else 0,
        "png_count": png_n,
        "text_chars": text_n,
        "error": err,
    }


def test_one_cad(label, dwg_path, temp_root):
    """测试单个CAD：完整管线 parse_dwg，记录耗时"""
    from app.engine.dwg_parser import parse_dwg

    print(f"\n{'='*60}", flush=True)
    print(f"[CAD] {label}", flush=True)
    print(f"  文件: {dwg_path}", flush=True)

    if not dwg_path.exists():
        print(f"  ERROR 文件不存在!", flush=True)
        return None

    fsize = dwg_path.stat().st_size
    print(f"  大小: {fmt_size(fsize)}", flush=True)

    gc.collect()
    t0 = time.perf_counter()
    try:
        content = parse_dwg(str(dwg_path), auto_convert=True)
    except Exception as e:
        print(f"  ERROR 解析失败: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return None
    t1 = time.perf_counter()

    if content:
        combined_text = " ".join(e.get("text", "") for e in content.text_entities)
        print(f"  OK {fmt_time(t1-t0)} | {len(content.text_entities):,}实体 | "
              f"{len(content.block_attributes)}块属性 | {len(content.tables)}表 | 专业={content.discipline}", flush=True)
        print(f"  文字: {len(combined_text):,}字符", flush=True)
        result = {
            "label": label,
            "time": t1 - t0,
            "entities": len(content.text_entities),
            "block_attrs": len(content.block_attributes),
            "tables": len(content.tables),
            "discipline": content.discipline,
            "text_chars": len(combined_text),
        }
    else:
        print(f"  ERROR 返回None", flush=True)
        result = {"label": label, "time": t1 - t0, "error": "返回None"}

    del content
    gc.collect()
    return result


# ── main ──

def main():
    print("=" * 60, flush=True)
    print("  大文件转换性能测试 V2 (逐文件释放内存)", flush=True)
    print("=" * 60, flush=True)

    temp_root = Path(tempfile.gettempdir()) / "large_file_test"
    if temp_root.exists():
        shutil.rmtree(temp_root, ignore_errors=True)
    temp_root.mkdir(parents=True, exist_ok=True)

    pdf_results = []
    cad_results = []

    # ── PDF 测试（逐个） ──
    for label, path in PDF_TESTS:
        r = test_one_pdf(label, path, temp_root)
        if r:
            pdf_results.append(r)
        gc.collect()
        # 检查内存
        import psutil
        mem = psutil.Process().memory_info().rss
        print(f"  [内存] 当前进程: {mem/1024/1024:.0f}MB", flush=True)

    # ── CAD 测试（逐个） ──
    for label, path in CAD_TESTS:
        r = test_one_cad(label, path, temp_root)
        if r:
            cad_results.append(r)
        gc.collect()
        import psutil
        mem = psutil.Process().memory_info().rss
        print(f"  [内存] 当前进程: {mem/1024/1024:.0f}MB", flush=True)

    # ── 汇总 ──
    print(f"\n\n{'#'*60}", flush=True)
    print(f"# 汇总报告", flush=True)
    print(f"{'#'*60}", flush=True)

    print(f"\n  PDF 测试结果:", flush=True)
    for r in pdf_results:
        print(f"    {r['label']:.<20s} {r['pages']}页 | 策略={r['strategy']} | "
              f"{r['png_count']}PNG | {r['text_chars']:,}字符", flush=True)

    print(f"\n  CAD 测试结果:", flush=True)
    for r in cad_results:
        if "error" in r:
            print(f"    {r['label']:.<20s} {fmt_time(r['time'])} | ERROR: {r['error']}", flush=True)
        else:
            print(f"    {r['label']:.<20s} {fmt_time(r['time'])} | {r['entities']:,}实体 | "
                  f"专业={r['discipline']}", flush=True)

    print(f"\n  临时文件: {temp_root}", flush=True)


if __name__ == "__main__":
    main()
