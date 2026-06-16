"""
维度3: 转换管线性能基准 (V4.9.4)
测量 Phase 0 + Phase 1 各操作延迟，建立性能基线
"""

import sys, os, json, time, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path
from tests.utils_perf import TestResults, PerfMeasurement, PerfTimer, get_file_size_mb

TEST_DATA_DIR = r"C:\Users\Administrator\Documents\xwechat_files\wxid_i0tdmsi16kfg22_747a\msg\file\2026-06"
SI_DIR = os.path.join(TEST_DATA_DIR, "2、图纸CAD", "图纸CAD", "SⅠ-道路工程一期施工图设计CAD")
SIV_DIR = os.path.join(TEST_DATA_DIR, "2、图纸CAD", "图纸CAD", "SⅣ-排水工程一期施工图设计CAD")
TEMP_DIR = os.path.join(TEST_DATA_DIR, "2、图纸CAD", "1、临时排水CAD")
PDF_DIR = TEST_DATA_DIR


def find_dwg(dir_path, keyword="", min_kb=0, max_mb=100):
    if not dir_path or not os.path.exists(dir_path):
        return None
    for f in sorted(os.listdir(dir_path)):
        if not f.endswith(".dwg"):
            continue
        if keyword and keyword.lower() not in f.lower():
            continue
        fp = os.path.join(dir_path, f)
        sz = os.path.getsize(fp) / 1024
        if min_kb <= sz and sz / 1024 <= max_mb:
            return fp
    return None


def test_conversion_perf():
    results = TestResults("3-perf", "转换管线性能基准")

    from app.engine.file_profiler import FileProfiler, _cad_strategy
    from app.engine.dwg_parser import find_odafc, convert_dwg_to_dxf, convert_dxf_to_png_ezdxf
    from app.engine.pdf_parser import extract_page_images, extract_tables_from_pdf, extract_pdf_with_strategy

    # C3.1-C3.4: Phase 0 — PDF Profile
    pdf_files = [
        ("送检指南(5.4MB)", os.path.join(PDF_DIR, "2025省站-材料检测送检指南_(客户版).pdf")),
        ("CJJ规范(5.8MB)", os.path.join(PDF_DIR, "城镇道路工程施工与质量验收规范CJJ 1-2008.pdf")),
    ]
    for label, pdf_path in pdf_files:
        if os.path.exists(pdf_path):
            t = PerfTimer(f"Profile {label}")
            with t:
                try:
                    prof = FileProfiler.profile_pdf(pdf_path)
                    m = PerfMeasurement(test_id=f"C3.{label.split('(')[0]}",
                        operation="profile_pdf", file_path=pdf_path,
                        file_size_mb=get_file_size_mb(pdf_path),
                        duration_ms=t.duration_ms,
                        strategy=prof.strategy,
                        output_count=prof.total_pages,
                        notes=f"sampling={prof.metadata.get('sampling','?')}, "
                              f"types={prof.metadata.get('type_counts',{})}")
                    results.add_perf(m)
                    ok = True
                except Exception as e:
                    ok = False
            results.add(f"C3.1_{label[:4]}", f"Phase0:Profile {label}", ok, t.duration_ms)

    # C3.5-C3.9: Phase 0 — CAD Profile
    cad_sizes = [
        ("极小(<0.2MB)", SI_DIR, "", 0, 0.2),
        ("小(0.2-2MB)", SI_DIR, "", 100, 2),
        ("中(2-5MB)", SIV_DIR, "", 2000, 5),
        ("大(5-10MB)", SI_DIR, "特殊路基", 5000, 10),
    ]
    for label, cdir, kw, minkb, maxmb in cad_sizes:
        fp = find_dwg(cdir, kw, minkb, maxmb)
        if fp:
            t = PerfTimer(f"Profile CAD {label}")
            with t:
                try:
                    prof = FileProfiler.profile_cad(fp)
                    m = PerfMeasurement(test_id=f"C3.CAD_{label[:4]}",
                        operation="profile_cad", file_path=fp,
                        file_size_mb=prof.file_size_mb,
                        duration_ms=t.duration_ms,
                        strategy=prof.strategy)
                    results.add_perf(m)
                    ok = True
                except Exception as e:
                    ok = False
            results.add(f"C3.5_{label[:4]}", f"Phase0:Profile CAD {label}", ok, t.duration_ms,
                       details={"file": Path(fp).name, "strategy": prof.strategy if 'prof' in dir() else "?"})

    # C3.10: Profile Excel
    excel_file = os.path.join(PDF_DIR, "永莲大道_检测计划表.xlsx")
    if os.path.exists(excel_file):
        t = PerfTimer("Profile Excel")
        with t:
            try:
                prof = FileProfiler.profile_document(excel_file)
                m = PerfMeasurement(test_id="C3.10",
                    operation="profile_document", file_path=excel_file,
                    file_size_mb=get_file_size_mb(excel_file),
                    duration_ms=t.duration_ms, strategy=prof.strategy)
                results.add_perf(m)
                ok = prof.strategy == "text_only"
            except Exception as e:
                ok = False
        results.add("C3.10", "Phase0:Profile Excel", ok, t.duration_ms)

    # C3.12-C3.13: DWG→DXF 转换
    odafc = find_odafc()
    if odafc:
        for label, cdir, kw, minkb, maxmb in [
            ("小CAD", SI_DIR, "", 10, 1),
            ("大CAD(5.9MB)", SIV_DIR, "DXT", 5000, 10),
        ]:
            fp = find_dwg(cdir, kw, minkb, maxmb)
            if fp:
                t = PerfTimer(f"DWG→DXF {label}")
                with t:
                    try:
                        dxf = convert_dwg_to_dxf(fp)
                        ok = dxf is not None
                        sz = get_file_size_mb(dxf) if dxf else 0
                        m = PerfMeasurement(test_id=f"C3.12_{label[:4]}",
                            operation="dwg_to_dxf", file_path=fp,
                            file_size_mb=get_file_size_mb(fp),
                            duration_ms=t.duration_ms, output_size_mb=sz,
                            notes=f"dxf={dxf}" if dxf else "")
                        results.add_perf(m)
                    except Exception as e:
                        ok = False
                results.add(f"C3.12_{label[:4]}", f"Phase1:DWG→DXF {label}", ok, t.duration_ms)

        # C3.14: DXF→PNG
        test_dwg = find_dwg(SI_DIR, "", 10, 1) or find_dwg(SI_DIR, "", 0, 5)
        if test_dwg:
            dxf_path = convert_dwg_to_dxf(test_dwg)
            if dxf_path:
                t = PerfTimer("DXF→PNG standard")
                with t:
                    try:
                        tmpd = tempfile.mkdtemp(prefix="perf_png_")
                        pngs = convert_dxf_to_png_ezdxf(dxf_path, tmpd, dpi=200, figsize=(16, 12))
                        ok = len(pngs) > 0
                        m = PerfMeasurement(test_id="C3.14",
                            operation="dxf_to_png", file_path=dxf_path,
                            file_size_mb=get_file_size_mb(dxf_path),
                            duration_ms=t.duration_ms,
                            output_count=len(pngs), strategy="standard_render")
                        results.add_perf(m)
                    except Exception as e:
                        ok = False
                results.add("C3.14", "Phase1:DXF→PNG(standard)", ok, t.duration_ms,
                           details={"pngs": len(pngs) if 'pngs' in dir() else 0})

    # C3.16-C3.17: PDF→PNG
    if os.path.exists(pdf_files[0][1]):
        t = PerfTimer("PDF→PNG first 5p")
        with t:
            try:
                tmpd = tempfile.mkdtemp(prefix="perf_pdfpng_")
                pngs = extract_page_images(pdf_files[0][1], tmpd, dpi=200, max_pages=5)
                ok = len(pngs) > 0
                m = PerfMeasurement(test_id="C3.17",
                    operation="pdf_to_png", file_path=pdf_files[0][1],
                    file_size_mb=get_file_size_mb(pdf_files[0][1]),
                    duration_ms=t.duration_ms,
                    output_count=len(pngs))
                results.add_perf(m)
            except Exception as e:
                ok = False
        results.add("C3.17", "Phase1:PDF→PNG(前5页)", ok, t.duration_ms,
                   details={"pngs": len(pngs) if 'pngs' in dir() else 0, "ms_per_page": round(t.duration_ms / 5, 1) if t.duration_ms > 0 else 0})

    # C3.19: PDF 表格提取
    if os.path.exists(pdf_files[0][1]):
        t = PerfTimer("PDF table extract")
        with t:
            try:
                tables = extract_tables_from_pdf(pdf_files[0][1], max_pages=10)
                ok = True
                m = PerfMeasurement(test_id="C3.19",
                    operation="pdf_table_extract", file_path=pdf_files[0][1],
                    file_size_mb=get_file_size_mb(pdf_files[0][1]),
                    duration_ms=t.duration_ms, output_count=len(tables))
                results.add_perf(m)
            except Exception as e:
                ok = False
        results.add("C3.19", "PDF表格提取(前10页)", ok, t.duration_ms,
                   details={"tables": len(tables) if 'tables' in dir() else 0})

    # C3.20-C3.21: 策略决策验证
    t = PerfTimer("Strategy all PDF")
    with t:
        try:
            from app.engine.file_profiler import _pdf_strategy
            tests = [
                ({"text": 50, "drawing": 0, "scan": 0, "blank": 0}, 50, "text_only"),
                ({"text": 0, "drawing": 30, "scan": 0, "blank": 0}, 30, "standard_render"),
                ({"text": 0, "drawing": 0, "scan": 20, "blank": 0}, 20, "ocr"),
                ({"text": 80, "drawing": 60, "scan": 8, "blank": 20}, 168, "hybrid"),
            ]
            all_ok = all(_pdf_strategy(tc[0], tc[1])[0] == tc[2] for tc in tests)
            results.add("C3.20", "策略决策:PDF全类型", all_ok, t.duration_ms,
                       details={"tests": len(tests)})
        except Exception as e:
            results.add("C3.20", "策略决策:PDF全类型", False, t.duration_ms, str(e))

    t = PerfTimer("Strategy CAD")
    with t:
        try:
            from app.engine.file_profiler import _cad_strategy
            cad_tests = [
                (0.05, 0.3, "standard_high"),     # V6.0: <2MB → 250dpi
                (3.0, 18.0, "standard_render"),    # V6.0: 2-5MB → 180dpi
                (7.0, 42.0, "reduced_render"),     # V6.0: 5-10MB → 120dpi
                (15.0, 90.0, "text_only"),          # V6.0: >10MB → text_only
            ]
            all_ok = all(_cad_strategy(sz, dxf)[0] == exp for sz, dxf, exp in cad_tests)
            results.add("C3.21", "策略决策:CAD全尺寸", all_ok, t.duration_ms,
                       details={"tests": len(cad_tests)})
        except Exception as e:
            results.add("C3.21", "策略决策:CAD全尺寸", False, t.duration_ms, str(e))

    # 保存结果
    out_dir = os.path.join(os.path.dirname(__file__), "..", "_test_output", "reports")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "dimension_3_perf.json")
    results.save(out_path)

    summary = results.summary
    print(f"\n{'='*50}")
    print(f"维度3: 转换管线性能基准")
    print(f"{'='*50}")
    print(f"总计: {summary['total']}, 通过: {summary['passed']}, 失败: {summary['failed']}")
    print(f"通过率: {summary['pass_rate_pct']}%")
    if results.perf_measurements:
        print(f"\n性能基线 ({len(results.perf_measurements)} 条):")
        for pm in results.perf_measurements[:10]:
            print(f"  {pm['operation']}: {pm['duration_ms']:.0f}ms ({pm.get('strategy','')})")
    if summary['failures']:
        print(f"\n失败项:")
        for f in summary['failures']:
            print(f"  ❌ {f['id']}: {f['name']} — {f['error']}")
    print(f"结果已保存: {out_path}")
    return summary


if __name__ == "__main__":
    test_conversion_perf()
