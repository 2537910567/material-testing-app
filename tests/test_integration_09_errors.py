"""
维度9: 错误场景测试 (V4.9.4)
验证所有错误场景都能优雅处理，不崩溃。
"""

import sys, os, json, tempfile, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path
from tests.utils_perf import TestResults, PerfTimer

# ── 测试数据路径 ─────────────────────────────────────────────────────
TEST_DATA_DIR = r"C:\Users\Administrator\Documents\xwechat_files\wxid_i0tdmsi16kfg22_747a\msg\file\2026-06"
SI_DIR = os.path.join(TEST_DATA_DIR, "2、图纸CAD", "图纸CAD", "SⅠ-道路工程一期施工图设计CAD")


def find_file(dir_path, pattern=None):
    """在目录中查找文件"""
    if not dir_path or not os.path.exists(dir_path):
        return None
    for f in os.listdir(dir_path):
        if f.endswith(".dwg") or f.endswith(".pdf"):
            fp = os.path.join(dir_path, f)
            if pattern and pattern.lower() in f.lower():
                return fp
            return fp
    return None


def test_error_scenarios():
    """执行所有错误场景测试"""
    results = TestResults("9-errors", "错误场景测试 - 27个场景")

    # E9.1: 空 API Key → AI 分析
    t = PerfTimer("E9.1")
    with t:
        try:
            from app.engine.model_provider import DeepSeekProvider
            p = DeepSeekProvider("")
            r = p.call("test", "test", max_tokens=10)
            passed = "error" in r
            err = r.get("error", "")
        except Exception as e:
            passed = False
            err = str(e)
    results.add("E9.1", "空API Key → 返回error", passed, t.duration_ms, err)

    # E9.2: 损坏 PDF
    t = PerfTimer("E9.3")
    with t:
        try:
            from app.engine.pdf_parser import extract_pdf_content
            tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
            tmp.write(b"this is not a valid pdf garbage data \x00\x01\x02" * 100)
            tmp.close()
            r = extract_pdf_content(tmp.name)
            os.unlink(tmp.name)
            passed = isinstance(r, dict) and "text" in r
            err = ""
        except Exception as e:
            passed = False
            err = str(e)
    results.add("E9.2", "损坏PDF文件", passed, t.duration_ms, err)

    # E9.3: 损坏 DWG
    t = PerfTimer("E9.4")
    with t:
        try:
            from app.engine.dwg_parser import parse_dwg
            tmp = tempfile.NamedTemporaryFile(suffix=".dwg", delete=False)
            tmp.write(b"garbage dwg data \x00\x01\x02" * 100)
            tmp.close()
            r = parse_dwg(tmp.name, auto_convert=False)
            os.unlink(tmp.name)
            # .dwg 无法直接解析，应该返回 None（无ODAFC不会转）
            passed = r is None or hasattr(r, 'text_entities')
            err = ""
        except Exception as e:
            passed = False
            err = str(e)
    results.add("E9.3", "损坏DWG文件", passed, t.duration_ms, err)

    # E9.4: 损坏 Excel
    t = PerfTimer("E9.5")
    with t:
        try:
            from app.engine.excel_parser import extract_excel_content
            tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
            tmp.write(b"garbage" * 100)
            tmp.close()
            r = extract_excel_content(tmp.name)
            os.unlink(tmp.name)
            passed = isinstance(r, dict) and "text" in r
            err = ""
        except Exception as e:
            passed = False
            err = str(e)
    results.add("E9.4", "损坏Excel文件", passed, t.duration_ms, err)

    # E9.5: 损坏 Word
    t = PerfTimer("E9.6")
    with t:
        try:
            from app.engine.word_parser import extract_word_content
            tmp = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
            tmp.write(b"garbage" * 100)
            tmp.close()
            r = extract_word_content(tmp.name)
            os.unlink(tmp.name)
            passed = isinstance(r, dict) and "text" in r
            err = ""
        except Exception as e:
            passed = False
            err = str(e)
    results.add("E9.5", "损坏Word文件", passed, t.duration_ms, err)

    # E9.6: ODAFC 检测
    t = PerfTimer("E9.7")
    with t:
        try:
            from app.engine.dwg_parser import find_odafc
            r = find_odafc()
            passed = r is None or (isinstance(r, str) and os.path.exists(r))
            err = f"result={r}" if not passed else ""
        except Exception as e:
            passed = False
            err = str(e)
    results.add("E9.6", "ODAFC检测", passed, t.duration_ms, err)

    # E9.7: DB 空项目操作
    t = PerfTimer("E9.11")
    with t:
        try:
            from app.database.db_manager import DatabaseManager
            db = DatabaseManager()
            files = db.get_files("nonexistent")
            passed = files == []
            err = ""
        except Exception as e:
            passed = False
            err = str(e)
    results.add("E9.7", "空项目获取文件列表", passed, t.duration_ms, err)

    # E9.8: 删除不存在的文件
    t = PerfTimer("E9.18")
    with t:
        try:
            from app.database.db_manager import DatabaseManager
            db = DatabaseManager()
            db.delete_file(999999)
            passed = True
            err = ""
        except Exception as e:
            passed = False
            err = str(e)
    results.add("E9.8", "删除不存在的文件", passed, t.duration_ms, err)

    # E9.9: 文件不存在
    t = PerfTimer("E9.9")
    with t:
        try:
            from app.engine.pdf_parser import extract_pdf_content
            r = extract_pdf_content(r"C:\nonexistent_file_xyz.pdf")
            passed = isinstance(r, dict) and "text" in r
            err = ""
        except Exception as e:
            passed = False
            err = str(e)
    results.add("E9.9", "不存在的PDF文件", passed, t.duration_ms, err)

    # E9.10: 中文路径复制
    t = PerfTimer("E9.15")
    with t:
        try:
            from app.engine.dwg_parser import _has_chinese_chars, _copy_to_ascii_temp
            test_path = r"D:\中文路径测试文件.dwg"
            passed = _has_chinese_chars(test_path) == True
            err = ""
        except Exception as e:
            passed = False
            err = str(e)
    results.add("E9.10", "中文字符检测", passed, t.duration_ms, err)

    # E9.11: DLL 测试 — 解析空白内容
    t = PerfTimer("E9.23")
    with t:
        try:
            from app.engine.ai_agent import _parse_json_response
            r = _parse_json_response("not json at all")
            passed = "error" in r
            err = ""
        except Exception as e:
            passed = False
            err = str(e)
    results.add("E9.11", "损坏JSON解析", passed, t.duration_ms, err)

    # E9.12: 空内容分片
    t = PerfTimer("E9.12")
    with t:
        try:
            from app.engine.ai_agent import _split_content_into_chunks
            r = _split_content_into_chunks("")
            passed = r == [""] or r == []
            err = ""
        except Exception as e:
            passed = False
            err = str(e)
    results.add("E9.12", "空内容分片", passed, t.duration_ms, err)

    # E9.13: 超大 API Key
    t = PerfTimer("E9.22")
    with t:
        try:
            from app.config import _encrypt_key, _decrypt_key
            long_key = "x" * 5000
            enc = _encrypt_key(long_key)
            dec = _decrypt_key(enc)
            passed = dec == long_key
            err = ""
        except Exception as e:
            passed = False
            err = str(e)
    results.add("E9.13", "超长API Key加解密", passed, t.duration_ms, err)

    # E9.14: 空 API Key 加解密
    t = PerfTimer("E9.14")
    with t:
        try:
            from app.config import _encrypt_key, _decrypt_key
            passed = _encrypt_key("") == "" and _decrypt_key("") == ""
            err = ""
        except Exception as e:
            passed = False
            err = str(e)
    results.add("E9.14", "空Key加解密", passed, t.duration_ms, err)

    # E9.15: 未知专业 CAD
    t = PerfTimer("E9.15")
    with t:
        try:
            from app.engine.dwg_parser import _detect_discipline
            disc = _detect_discipline("unknown_file_xyz.dwg", [])
            passed = disc == "未知"
            err = ""
        except Exception as e:
            passed = False
            err = str(e)
    results.add("E9.15", "未知专业CAD检测", passed, t.duration_ms, err)

    # E9.16: 标准提取 — 空内容
    t = PerfTimer("E9.16")
    with t:
        try:
            from app.engine.ai_agent import _extract_standards_from_content
            r = _extract_standards_from_content("")
            passed = r == []
            err = ""
        except Exception as e:
            passed = False
            err = str(e)
    results.add("E9.16", "空内容标准提取", passed, t.duration_ms, err)

    # E9.17: 标准提取 — 正常内容
    t = PerfTimer("E9.17")
    with t:
        try:
            from app.engine.ai_agent import _extract_standards_from_content
            r = _extract_standards_from_content("按GB 55032-2022和JTG 3450-2019执行")
            passed = len(r) >= 2
            err = str(r) if not passed else ""
        except Exception as e:
            passed = False
            err = str(e)
    results.add("E9.17", "正常标准提取", passed, t.duration_ms, err)

    # E9.18: 去重 — 空列表
    t = PerfTimer("E9.18")
    with t:
        try:
            from app.engine.ai_agent import _deduplicate_testing_plan
            r = _deduplicate_testing_plan([])
            passed = r == []
            err = ""
        except Exception as e:
            passed = False
            err = str(e)
    results.add("E9.18", "空列表去重", passed, t.duration_ms, err)

    # E9.19: 去重 — 有重复
    t = PerfTimer("E9.19")
    with t:
        try:
            from app.engine.ai_agent import _deduplicate_testing_plan
            items = [
                {"section": "K0+000~K1+000", "road_orientation": "双侧", "material_name": "水泥", "test_item": "强度", "sub_project": "路基", "work_item": "土方路基"},
                {"section": "K0+000~K1+000", "road_orientation": "双侧", "material_name": "水泥", "test_item": "强度", "sub_project": "路基", "work_item": "土方路基"},
            ]
            r = _deduplicate_testing_plan(items)
            passed = len(r) == 1
            err = f"got {len(r)}" if not passed else ""
        except Exception as e:
            passed = False
            err = str(e)
    results.add("E9.19", "重复条目去重", passed, t.duration_ms, err)

    # E9.20: 桩号精度修正 — 无精度丢失
    t = PerfTimer("E9.20")
    with t:
        try:
            from app.engine.ai_agent import _fix_station_precision
            result = {"sections": [{"section": "K0+582~K1+200"}], "testing_plan": []}
            r = _fix_station_precision("桩号范围K0+582~K1+200, 道路全长1280m", result)
            passed = r["sections"][0]["section"] == "K0+582~K1+200"
            err = r["sections"][0]["section"] if not passed else ""
        except Exception as e:
            passed = False
            err = str(e)
    results.add("E9.20", "桩号精度:无精度丢失", passed, t.duration_ms, err)

    # E9.21: 桩号精度修正 — 有小数
    t = PerfTimer("E9.21")
    with t:
        try:
            from app.engine.ai_agent import _fix_station_precision
            result = {"sections": [{"section": "K2+691~K3+100"}], "testing_plan": []}
            r = _fix_station_precision("从K2+691.502到K3+100.250", result)
            passed = ".502" in r["sections"][0]["section"] or ".250" in r["sections"][0]["section"]
            err = r["sections"][0]["section"] if not passed else ""
        except Exception as e:
            passed = False
            err = str(e)
    results.add("E9.21", "桩号精度:小数修正", passed, t.duration_ms, err)

    # E9.22: Merge 结构结果 — 全部有 error
    t = PerfTimer("E9.22")
    with t:
        try:
            from app.engine.ai_agent import _merge_structure_results
            r = _merge_structure_results([{"error": "err1"}, {"error": "err2"}])
            passed = r["sections"] == [] and r["project_info"] == {}
            err = ""
        except Exception as e:
            passed = False
            err = str(e)
    results.add("E9.22", "合并结构:全error", passed, t.duration_ms, err)

    # E9.23: 智能分片 — 空内容
    t = PerfTimer("E9.23")
    with t:
        try:
            from app.engine.ai_agent import _split_content_into_chunks_smart
            r = _split_content_into_chunks_smart("", 100)
            passed = r == [""] or r == []
            err = ""
        except Exception as e:
            passed = False
            err = str(e)
    results.add("E9.23", "智能分片:空内容", passed, t.duration_ms, err)

    # E9.24: 图片空白检测
    t = PerfTimer("E9.24")
    with t:
        try:
            from PIL import Image
            import io
            from app.engine.image_preprocess import _is_blank
            img = Image.new("RGB", (100, 100), (255, 255, 255))
            passed = _is_blank(img) == True
            err = ""
        except Exception as e:
            passed = False
            err = str(e)
    results.add("E9.24", "空白图片检测", passed, t.duration_ms, err)

    # E9.25: 图片非空白检测
    t = PerfTimer("E9.25")
    with t:
        try:
            from PIL import Image, ImageDraw
            from app.engine.image_preprocess import _is_blank
            img = Image.new("RGB", (100, 100), (255, 255, 255))
            draw = ImageDraw.Draw(img)
            for i in range(10):
                draw.rectangle([i*10, 0, i*10+5, 100], fill=(i*20, i*10, 0))
            passed = _is_blank(img) == False
            err = ""
        except Exception as e:
            passed = False
            err = str(e)
    results.add("E9.25", "非空白图片检测", passed, t.duration_ms, err)

    # E9.26: 空分析结果生成 Excel
    t = PerfTimer("E9.26")
    with t:
        try:
            from app.report.report_generator import generate_testing_plan
            tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
            tmp.close()
            r = generate_testing_plan(tmp.name,
                project_info={"project_name": "test"},
                testing_plan=[],
            )
            os.unlink(tmp.name)
            passed = r and os.path.exists(r) if isinstance(r, str) else False
            err = ""
        except Exception as e:
            passed = False
            err = str(e)
    results.add("E9.26", "空分析结果生成Excel", passed, t.duration_ms, err)

    # E9.27: 清理不存在的临时目录
    t = PerfTimer("E9.27")
    with t:
        try:
            from app.engine.dwg_parser import cleanup_session_temp_dirs, cleanup_old_temp_dirs
            c1 = cleanup_session_temp_dirs()
            c2 = cleanup_old_temp_dirs(max_age_days=1)
            passed = c1 >= 0 and c2 >= 0
            err = ""
        except Exception as e:
            passed = False
            err = str(e)
    results.add("E9.27", "临时目录清理", passed, t.duration_ms, err)

    # 保存结果
    out_dir = os.path.join(os.path.dirname(__file__), "..", "_test_output", "reports")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "dimension_9_errors.json")
    results.save(out_path)

    summary = results.summary
    print(f"\n{'='*50}")
    print(f"维度9: 错误场景测试")
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
    test_error_scenarios()
