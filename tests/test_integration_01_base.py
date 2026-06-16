"""
维度1: 功能完整性测试 (V4.9.4)
验证所有基本功能正常运作 — 项目CRUD / 文件导入 / Profile / 转换 / 导出 / 设置
"""

import sys, os, json, tempfile, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path
from tests.utils_perf import TestResults, PerfTimer, get_file_size_mb

TEST_DATA_DIR = r"C:\Users\Administrator\Documents\xwechat_files\wxid_i0tdmsi16kfg22_747a\msg\file\2026-06"
SI_DIR = os.path.join(TEST_DATA_DIR, "2、图纸CAD", "图纸CAD", "SⅠ-道路工程一期施工图设计CAD")
SIV_DIR = os.path.join(TEST_DATA_DIR, "2、图纸CAD", "图纸CAD", "SⅣ-排水工程一期施工图设计CAD")
TEMP_DIR = os.path.join(TEST_DATA_DIR, "2、图纸CAD", "1、临时排水CAD")
PDF_DIR = TEST_DATA_DIR


def find_dwg(dir_path, min_size_kb=0, max_size_mb=100):
    if not dir_path or not os.path.exists(dir_path):
        return None
    for f in sorted(os.listdir(dir_path)):
        if f.endswith(".dwg"):
            fp = os.path.join(dir_path, f)
            sz = os.path.getsize(fp) / 1024
            if min_size_kb <= sz and sz / 1024 <= max_size_mb:
                return fp
    return None


def test_functional():
    results = TestResults("1-functional", "功能完整性测试")

    from app.config import AppConfig
    from app.database.db_manager import DatabaseManager
    from app.engine.project_manager import ProjectManager
    from app.engine.pdf_parser import extract_pdf_content, extract_text_from_pdf
    from app.engine.dwg_parser import parse_dwg, find_odafc
    from app.engine.file_profiler import FileProfiler

    db = DatabaseManager()
    pm = ProjectManager(db_manager=db)

    # F1.1-F1.6: 项目 CRUD
    t = PerfTimer("F1.1")
    with t:
        try:
            proj = pm.create_project("测试项目_F1")
            p = pm.get_project(proj.id)
            results.add("F1.1", "创建项目", p is not None and len(proj.id) == 8, t.duration_ms)
        except Exception as e:
            results.add("F1.1", "创建项目", False, t.duration_ms, str(e))

    proj_id = proj.id if 'proj' in dir() and proj else None

    t = PerfTimer("F1.2")
    with t:
        try:
            proj2 = pm.create_project("永莲大道工程")
            results.add("F1.2", "中文项目名", proj2.name == "永莲大道工程", t.duration_ms)
        except Exception as e:
            results.add("F1.2", "中文项目名", False, t.duration_ms, str(e))

    t = PerfTimer("F1.3")
    with t:
        try:
            pm.update_project_name(proj2.id, "新名称")
            p = pm.get_project(proj2.id)
            results.add("F1.3", "重命名项目", p and p.name == "新名称", t.duration_ms)
        except Exception as e:
            results.add("F1.3", "重命名项目", False, t.duration_ms, str(e))

    t = PerfTimer("F1.4")
    with t:
        try:
            pm.delete_project(proj2.id)
            p = pm.get_project(proj2.id)
            results.add("F1.4", "删除项目", p is None, t.duration_ms)
        except Exception as e:
            results.add("F1.4", "删除项目", False, t.duration_ms, str(e))

    t = PerfTimer("F1.5")
    with t:
        try:
            projects = pm.list_projects()
            results.add("F1.5", "项目列表", isinstance(projects, list), t.duration_ms)
        except Exception as e:
            results.add("F1.5", "项目列表", False, t.duration_ms, str(e))

    # F1.7-F1.11: 文件导入
    if proj_id:
        # CAD 文件
        small_dwg = find_dwg(SI_DIR, min_size_kb=10, max_size_mb=1)
        if small_dwg:
            t = PerfTimer("F1.7")
            with t:
                try:
                    fid = db.add_file(proj_id, small_dwg, "cad")
                    results.add("F1.7", "导入DWG文件", fid is not None and fid > 0, t.duration_ms, details={"path": small_dwg})
                except Exception as e:
                    results.add("F1.7", "导入DWG文件", False, t.duration_ms, str(e))

        # PDF 文件
        guide_pdf = os.path.join(PDF_DIR, "2025省站-材料检测送检指南_(客户版).pdf")
        if os.path.exists(guide_pdf):
            t = PerfTimer("F1.8")
            with t:
                try:
                    fid = db.add_file(proj_id, guide_pdf, "pdf")
                    results.add("F1.8", "导入PDF文件", fid is not None and fid > 0, t.duration_ms, details={"path": guide_pdf})
                except Exception as e:
                    results.add("F1.8", "导入PDF文件", False, t.duration_ms, str(e))

        # Excel
        excel_file = os.path.join(PDF_DIR, "永莲大道_检测计划表.xlsx")
        if os.path.exists(excel_file):
            t = PerfTimer("F1.9")
            with t:
                try:
                    fid = db.add_file(proj_id, excel_file, "excel")
                    results.add("F1.9", "导入Excel文件", fid is not None and fid > 0, t.duration_ms)
                except Exception as e:
                    results.add("F1.9", "导入Excel文件", False, t.duration_ms, str(e))

        # 重复导入
        if small_dwg:
            t = PerfTimer("F1.10")
            with t:
                try:
                    fid2 = db.add_file(proj_id, small_dwg, "cad")
                    results.add("F1.10", "重复导入", fid2 is not None, t.duration_ms)
                except Exception as e:
                    results.add("F1.10", "重复导入", False, t.duration_ms, str(e))

    # F1.11-F1.16: 解析
    if proj_id and small_dwg:
        t = PerfTimer("F1.11")
        with t:
            try:
                content = parse_dwg(small_dwg)
                ok = content is not None and hasattr(content, 'text_entities')
                results.add("F1.11", "解析DWG文本", ok, t.duration_ms)
            except Exception as e:
                results.add("F1.11", "解析DWG文本", False, t.duration_ms, str(e))

    if os.path.exists(guide_pdf):
        t = PerfTimer("F1.12")
        with t:
            try:
                content = extract_pdf_content(guide_pdf)
                ok = isinstance(content, dict) and len(content.get("text", "")) > 100
                results.add("F1.12", "解析PDF文本", ok, t.duration_ms, details={"chars": len(content.get("text", ""))})
            except Exception as e:
                results.add("F1.12", "解析PDF文本", False, t.duration_ms, str(e))

    # F1.13-F1.16: Excel 解析
    if os.path.exists(excel_file):
        t = PerfTimer("F1.13")
        with t:
            try:
                from app.engine.excel_parser import extract_excel_content
                r = extract_excel_content(excel_file)
                ok = isinstance(r, dict) and len(r.get("text", "")) > 0
                results.add("F1.13", "解析Excel", ok, t.duration_ms)
            except Exception as e:
                results.add("F1.13", "解析Excel", False, t.duration_ms, str(e))

    # F1.14-F1.16: FileProfiler
    if os.path.exists(guide_pdf):
        t = PerfTimer("F1.14")
        with t:
            try:
                prof = FileProfiler.profile_pdf(guide_pdf)
                ok = prof.strategy != "" and prof.total_pages > 0
                results.add("F1.14", "Profile PDF(送检指南)", ok, t.duration_ms,
                           details={"strategy": prof.strategy, "pages": prof.total_pages})
            except Exception as e:
                results.add("F1.14", "Profile PDF(送检指南)", False, t.duration_ms, str(e))

    cjj_pdf = os.path.join(PDF_DIR, "城镇道路工程施工与质量验收规范CJJ 1-2008.pdf")
    if os.path.exists(cjj_pdf):
        t = PerfTimer("F1.15")
        with t:
            try:
                prof = FileProfiler.profile_pdf(cjj_pdf)
                ok = prof.strategy != ""
                results.add("F1.15", "Profile PDF(规范文字)", ok, t.duration_ms, details={"strategy": prof.strategy})
            except Exception as e:
                results.add("F1.15", "Profile PDF(规范文字)", False, t.duration_ms, str(e))

    # CAD Profile
    test_dwg = small_dwg or find_dwg(SI_DIR, min_size_kb=100, max_size_mb=5)
    if test_dwg:
        t = PerfTimer("F1.16")
        with t:
            try:
                prof = FileProfiler.profile_cad(test_dwg)
                ok = prof.strategy != "" and prof.file_size_mb > 0
                results.add("F1.16", "Profile CAD", ok, t.duration_ms,
                           details={"strategy": prof.strategy, "size_mb": prof.file_size_mb})
            except Exception as e:
                results.add("F1.16", "Profile CAD", False, t.duration_ms, str(e))

    # F1.17-F1.18: 导出测试
    t = PerfTimer("F1.17")
    with t:
        try:
            from app.report.report_generator import generate_testing_plan
            sample_plan = [
                {"sequence": 1, "section": "K0+000~K0+500", "road_orientation": "双侧",
                 "sub_project": "路基工程", "sub_sub_project": "/", "work_item": "土方路基",
                 "material_name": "路基填料", "spec": "土", "test_item": "压实度",
                 "test_param": "压实度", "standard": "CJJ 1-2008",
                 "sampling_method": "灌砂法", "inspection_type": "见证取样",
                 "frequency": "每层每1000㎡ 3点", "planned_batches": "4批", "remarks": ""}
            ]
            tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
            tmp.close()
            out = generate_testing_plan(tmp.name, project_info={"project_name": "测试项目"}, testing_plan=sample_plan)
            os.unlink(tmp.name)
            results.add("F1.17", "Excel导出(正常)", bool(out), t.duration_ms)
        except Exception as e:
            results.add("F1.17", "Excel导出(正常)", False, t.duration_ms, str(e))

    # F1.18: 空计划导出
    t = PerfTimer("F1.18")
    with t:
        try:
            from app.report.report_generator import generate_testing_plan
            tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
            tmp.close()
            out = generate_testing_plan(tmp.name, project_info={"project_name": "空测试"}, testing_plan=[])
            os.unlink(tmp.name)
            results.add("F1.18", "Excel导出(空)", bool(out), t.duration_ms)
        except Exception as e:
            results.add("F1.18", "Excel导出(空)", False, t.duration_ms, str(e))

    # F1.19: 检测送检指南
    t = PerfTimer("F1.19")
    with t:
        try:
            from app.bridge.app_state import _detect_testing_guide
            r = _detect_testing_guide("2025省站-材料检测送检指南_(客户版).pdf")
            results.add("F1.19", "检测送检指南(文件名)", r is True, t.duration_ms)
        except Exception as e:
            results.add("F1.19", "检测送检指南(文件名)", False, t.duration_ms, str(e))

    # F1.20: 检测送检指南(内容)
    if os.path.exists(guide_pdf):
        t = PerfTimer("F1.20")
        with t:
            try:
                from app.bridge.app_state import _detect_testing_guide
                text = extract_text_from_pdf(guide_pdf)[:500]
                r = _detect_testing_guide(guide_pdf, text)
                results.add("F1.20", "检测送检指南(内容)", r is True, t.duration_ms)
            except Exception as e:
                results.add("F1.20", "检测送检指南(内容)", False, t.duration_ms, str(e))

    # F1.21: Config test
    t = PerfTimer("F1.21")
    with t:
        try:
            cfg = AppConfig()
            cfg.output_dir = r"C:\Temp\test_out"
            loaded = cfg.output_dir
            results.add("F1.21", "设置: 输出目录", loaded == r"C:\Temp\test_out", t.duration_ms)
        except Exception as e:
            results.add("F1.21", "设置: 输出目录", False, t.duration_ms, str(e))

    # F1.22: ODAFC 检测
    t = PerfTimer("F1.22")
    with t:
        try:
            odafc = find_odafc()
            ok = odafc is not None and os.path.exists(odafc)
            results.add("F1.22", "ODAFC检测", ok, t.duration_ms, details={"path": str(odafc) if odafc else ""})
        except Exception as e:
            results.add("F1.22", "ODAFC检测", False, t.duration_ms, str(e))

    # F1.23: 自动检测项目名称
    t = PerfTimer("F1.23")
    with t:
        try:
            name = pm.auto_detect_name("本项目为肇庆市大型产业集聚区（肇庆新区片）配套基础设施建设项目一标段（永莲大道）道路工程")
            ok = "永莲大道" in name or len(name) >= 4
            results.add("F1.23", "自动检测项目名称", ok, t.duration_ms, details={"detected": name})
        except Exception as e:
            results.add("F1.23", "自动检测项目名称", False, t.duration_ms, str(e))

    # F1.24: Analysis result CRUD
    if proj_id:
        t = PerfTimer("F1.24")
        with t:
            try:
                db.store_analysis_result(proj_id, {
                    "project_info": {"project_name": "测试"},
                    "testing_plan": sample_plan if 'sample_plan' in dir() else [{"sequence": 1, "section": "K0+000", "road_orientation": "双侧", "sub_project": "路基", "sub_sub_project": "/", "work_item": "土方", "material_name": "土", "spec": "", "test_item": "压实度", "test_param": "", "standard": "", "sampling_method": "", "inspection_type": "见证取样", "frequency": "", "planned_batches": "", "remarks": ""}],
                })
                ok = db.has_analysis(proj_id)
                results.add("F1.24", "存储+查询分析结果", ok, t.duration_ms)
            except Exception as e:
                results.add("F1.24", "存储+查询分析结果", False, t.duration_ms, str(e))

    # F1.25: 清理测试项目
    if proj_id:
        try:
            pm.delete_project(proj_id)
        except Exception:
            pass

    # 保存结果
    out_dir = os.path.join(os.path.dirname(__file__), "..", "_test_output", "reports")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "dimension_1_functional.json")
    results.save(out_path)

    summary = results.summary
    print(f"\n{'='*50}")
    print(f"维度1: 功能完整性测试")
    print(f"{'='*50}")
    print(f"总计: {summary['total']}, 通过: {summary['passed']}, 失败: {summary['failed']}")
    print(f"通过率: {summary['pass_rate_pct']}%")
    if summary['failures']:
        print(f"\n失败项:")
        for f in summary['failures']:
            print(f"  ❌ {f['id']}: {f['name']} — {f['error']}")
    print(f"结果已保存: {out_path}")
    return summary


if __name__ == "__main__":
    test_functional()
