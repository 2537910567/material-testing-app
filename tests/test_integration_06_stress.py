"""
维度6/7/8: 压力测试 (V4.9.4)
小规模(5文件)/中规模(15文件)/缩减大规模(30文件)
"""

import sys, os, json, time, tempfile, shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from tests.utils_perf import TestResults, PerfTimer, ResourceMonitor, get_file_size_mb

TEST_DATA_DIR = r"C:\Users\Administrator\Documents\xwechat_files\wxid_i0tdmsi16kfg22_747a\msg\file\2026-06"
SI_DIR = os.path.join(TEST_DATA_DIR, "2、图纸CAD", "图纸CAD", "SⅠ-道路工程一期施工图设计CAD")
SII_DIR = os.path.join(TEST_DATA_DIR, "2、图纸CAD", "图纸CAD", "SⅡ-交通工程一期施工图设计CAD")
SIII_DIR = os.path.join(TEST_DATA_DIR, "2、图纸CAD", "图纸CAD", "SⅢ-桥涵工程一期施工图设计CAD")
SIV_DIR = os.path.join(TEST_DATA_DIR, "2、图纸CAD", "图纸CAD", "SⅣ-排水工程一期施工图设计CAD")
SV_DIR = os.path.join(TEST_DATA_DIR, "2、图纸CAD", "图纸CAD", "SⅤ-照明工程一期施工图设计CAD")
SVI_DIR = os.path.join(TEST_DATA_DIR, "2、图纸CAD", "图纸CAD", "SⅥ-电力工程一期施工图设计CAD")
SVII_DIR = os.path.join(TEST_DATA_DIR, "2、图纸CAD", "图纸CAD", "SⅦ-通信工程一期施工图设计CAD")
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


def collect_cad_files(dir_path, max_count=5):
    """从目录收集CAD文件"""
    files = []
    if not dir_path or not os.path.exists(dir_path):
        return files
    for f in sorted(os.listdir(dir_path)):
        if f.endswith(".dwg") and len(files) < max_count:
            files.append(os.path.join(dir_path, f))
    return files


def run_stress_test(name: str, file_list: list, results: TestResults, test_prefix: str):
    """运行压力测试 — 模拟 Phase 0 (Profile) + Phase 1 (Conversion)"""
    from app.engine.file_profiler import FileProfiler
    from app.engine.dwg_parser import find_odafc, convert_cad_with_strategy
    from app.engine.pdf_parser import extract_pdf_with_strategy

    total = len(file_list)
    results.add(f"{test_prefix}_setup", f"{name}: 准备{total}个文件", True, 0,
               details={"file_count": total, "total_size_mb": round(sum(get_file_size_mb(f) for f in file_list), 1)})

    # Phase 0: Profile
    t0 = time.perf_counter()
    profiles = {}
    phase0_ok = 0
    phase0_errors = 0
    for i, fp in enumerate(file_list):
        try:
            ext = Path(fp).suffix.lower()
            if ext == ".dwg":
                prof = FileProfiler.profile_cad(fp)
            elif ext == ".pdf":
                prof = FileProfiler.profile_pdf(fp)
            else:
                prof = FileProfiler.profile_document(fp)
            profiles[fp] = prof
            phase0_ok += 1
        except Exception as e:
            phase0_errors += 1
            results.add(f"{test_prefix}_p0_{i}", f"Phase0: {Path(fp).name}", False, 0, str(e))

    phase0_duration = (time.perf_counter() - t0) * 1000
    results.add(f"{test_prefix}_phase0", f"{name}: Phase0完成", phase0_errors == 0,
               round(phase0_duration),
               details={"ok": phase0_ok, "errors": phase0_errors, "duration_ms": round(phase0_duration, 1)})

    # Phase 1: Strategy Conversion (并行, 按策略分组)
    odafc = find_odafc()
    if not odafc:
        results.add(f"{test_prefix}_phase1", f"{name}: Phase1跳过(无ODAFC)", False, 0, "ODAFC not found")
        return

    t1 = time.perf_counter()
    phase1_ok = 0
    phase1_errors = 0
    phase1_results = []

    # 按策略分组
    groups = {}
    for fp in file_list:
        prof = profiles.get(fp)
        strategy = prof.strategy if prof else "standard_render"
        groups.setdefault(strategy, []).append(fp)

    for strategy, group_files in groups.items():
        workers = {"text_only": 8, "standard_render": 4, "reduced_render": 3,
                   "cairo_render": 2, "ocr": 2}.get(strategy, 3)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {}
            for fp in group_files:
                future = executor.submit(_convert_one_file, fp, strategy)
                futures[future] = fp
            for future in as_completed(futures):
                fp = futures[future]
                try:
                    result = future.result(timeout=300)
                    if result.get("error"):
                        phase1_errors += 1
                        phase1_results.append({"file": Path(fp).name, "status": "error", "error": result["error"]})
                    else:
                        phase1_ok += 1
                        phase1_results.append({"file": Path(fp).name, "status": "ok", "pngs": len(result.get("png_paths", []))})
                except Exception as e:
                    phase1_errors += 1
                    phase1_results.append({"file": Path(fp).name, "status": "error", "error": str(e)})

    phase1_duration = (time.perf_counter() - t1) * 1000
    results.add(f"{test_prefix}_phase1", f"{name}: Phase1完成", phase1_errors < phase1_ok,
               round(phase1_duration),
               details={"ok": phase1_ok, "errors": phase1_errors, "duration_ms": round(phase1_duration, 1),
                        "results": phase1_results})

    total_duration = round((time.perf_counter() - t0) * 1000, 1)
    results.add(f"{test_prefix}_total", f"{name}: 总计", phase1_errors < phase1_ok,
               total_duration,
               details={"total_duration_ms": total_duration, "ok": phase1_ok, "errors": phase1_errors})

    return phase0_duration, phase1_duration, phase1_results


def _convert_one_file(fp: str, strategy: str) -> dict:
    """转换单个文件（供线程池调用）"""
    from app.engine.dwg_parser import convert_cad_with_strategy
    from app.engine.pdf_parser import extract_pdf_with_strategy
    import tempfile

    ext = Path(fp).suffix.lower()
    tmpd = tempfile.mkdtemp(prefix="stress_conv_")

    try:
        if ext == ".dwg":
            result = convert_cad_with_strategy(fp, strategy)
            if result.get("error"):
                return {"error": result["error"], "png_paths": []}
            return {"png_paths": result.get("png_paths", []), "error": None}
        elif ext == ".pdf":
            page_types = {}
            # 简化: 全部当成drawing
            result = extract_pdf_with_strategy(fp, page_types, tmpd)
            return {"png_paths": result.get("png_paths", []), "error": None}
        return {"png_paths": [], "error": None}
    except Exception as e:
        return {"error": str(e), "png_paths": []}
    finally:
        try:
            shutil.rmtree(tmpd, ignore_errors=True)
        except Exception:
            pass


def test_small_scale():
    """小规模: 5个文件"""
    results = TestResults("6-stress-small", "小规模压力测试(5文件)")

    files = []
    # 1 DWG
    dwg = find_dwg(SI_DIR, "", 10, 5) or find_dwg(SI_DIR, "", 0, 10)
    if dwg:
        files.append(dwg)
    # 2 PDFs
    for pdf_name in ["2025省站-材料检测送检指南_(客户版).pdf", "ZQ202504210011肇庆市大型产业集聚区（肇庆新区片）配套基础设施建设项目一标段（永莲大道）(1)(1).pdf"]:
        pdf_path = os.path.join(PDF_DIR, pdf_name)
        if os.path.exists(pdf_path):
            files.append(pdf_path)
    # 1 Excel
    excel = os.path.join(PDF_DIR, "永莲大道_检测计划表.xlsx")
    if os.path.exists(excel):
        files.append(excel)

    print(f"小规模: {len(files)} 个文件 ({sum(get_file_size_mb(f) for f in files):.1f}MB)")
    run_stress_test("小规模", files, results, "S6")

    out_dir = os.path.join(os.path.dirname(__file__), "..", "_test_output", "reports")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "dimension_6_stress_small.json")
    results.save(out_path)
    print(f"\n维度6完成, 结果: {out_path}")
    return results.summary


def test_medium_scale():
    """中规模: 15个文件"""
    results = TestResults("7-stress-medium", "中规模压力测试(15文件)")

    files = []
    # 5 DWGs (跨专业)
    for cdir, label in [(SI_DIR, "SⅠ"), (SII_DIR, "SⅡ"), (SIII_DIR, "SⅢ"), (SIV_DIR, "SⅣ"), (TEMP_DIR, "TEMP")]:
        dwg = find_dwg(cdir, "", 10, 10)
        if dwg:
            files.append(dwg)
            print(f"  CAD: {Path(dwg).name}")

    # 4 PDFs
    for pdf_name in ["2025省站-材料检测送检指南_(客户版).pdf",
                      "城镇道路工程施工与质量验收规范CJJ 1-2008.pdf",
                      "肇庆市大型产业集聚区（肇庆新区片）配套基础设施建设项目一标段（永莲大道）（检验、监测）.pdf"]:
        pdf_path = os.path.join(PDF_DIR, pdf_name)
        if os.path.exists(pdf_path) and pdf_path not in files:
            files.append(pdf_path)
            print(f"  PDF: {pdf_name}")

    # 1 Excel
    excel = os.path.join(PDF_DIR, "永莲大道_检测计划表.xlsx")
    if os.path.exists(excel):
        files.append(excel)

    print(f"中规模: {len(files)} 个文件 ({sum(get_file_size_mb(f) for f in files):.1f}MB)")
    run_stress_test("中规模", files, results, "S7")

    out_dir = os.path.join(os.path.dirname(__file__), "..", "_test_output", "reports")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "dimension_7_stress_medium.json")
    results.save(out_path)
    print(f"\n维度7完成, 结果: {out_path}")
    return results.summary


def test_large_scale():
    """缩减大规模: 30个文件"""
    results = TestResults("8-stress-large", "缩减大规模压力测试(30文件)")

    files = []

    # 20 DWGs from all disciplines
    cad_dirs = [
        (SI_DIR, 5), (SII_DIR, 3), (SIII_DIR, 3), (SIV_DIR, 3),
        (SV_DIR, 2), (SVI_DIR, 2), (SVII_DIR, 2), (TEMP_DIR, 2),
    ]
    for cdir, count in cad_dirs:
        cfiles = collect_cad_files(cdir, count)
        for fp in cfiles:
            if fp not in files:
                files.append(fp)
                print(f"  CAD: {Path(fp).name} ({get_file_size_mb(fp):.1f}MB)")

    # 5 PDFs (including 184MB giant)
    pdf_files_to_add = [
        "2025省站-材料检测送检指南_(客户版).pdf",
        "城镇道路工程施工与质量验收规范CJJ 1-2008.pdf",
        "肇庆市大型产业集聚区（肇庆新区片）配套基础设施建设项目一标段（永莲大道）（检验、监测）.pdf",
        "ZQ202504210011肇庆市大型产业集聚区（肇庆新区片）配套基础设施建设项目一标段（永莲大道）(1)(1).pdf",
        "SⅠ道路工程一期施工图设计.pdf",  # 184MB
    ]
    for pdf_name in pdf_files_to_add:
        pdf_path = os.path.join(PDF_DIR, pdf_name)
        if os.path.exists(pdf_path):
            files.append(pdf_path)
            print(f"  PDF: {pdf_name} ({get_file_size_mb(pdf_path):.1f}MB)")

    # 2 Excel
    excel = os.path.join(PDF_DIR, "永莲大道_检测计划表.xlsx")
    if os.path.exists(excel) and excel not in files:
        files.append(excel)
    xls_file = os.path.join(PDF_DIR, "永莲大道 路基压实度、厚度 26.5.18（未报检）.xls")
    if os.path.exists(xls_file):
        files.append(xls_file)

    print(f"\n大规模: {len(files)} 个文件")
    total_mb = sum(get_file_size_mb(f) for f in files)
    # Phase 0 全量（Profile 不调用 ODAFC）
    print(f"Phase 0 开始: {len(files)} 个文件 ({total_mb:.1f}MB)...")
    monitor = ResourceMonitor(interval=1.0)
    monitor.start()

    run_stress_test("大规模", files, results, "S8")

    resource_report = monitor.stop()
    results.add("S8_monitor", "资源监控", True, 0, details=resource_report)
    if "memory" in resource_report:
        print(f"资源监控: 内存峰值{resource_report['memory']['peak_mb']}MB, "
              f"线程峰值{resource_report['threads']['peak']}")
    else:
        print(f"资源监控: {resource_report.get('error', '数据不可用')}")

    out_dir = os.path.join(os.path.dirname(__file__), "..", "_test_output", "reports")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "dimension_8_stress_large.json")
    results.save(out_path)
    print(f"\n维度8完成, 结果: {out_path}")
    return results.summary


if __name__ == "__main__":
    import sys
    if "--large" in sys.argv:
        test_large_scale()
    elif "--medium" in sys.argv:
        test_medium_scale()
    else:
        test_small_scale()
