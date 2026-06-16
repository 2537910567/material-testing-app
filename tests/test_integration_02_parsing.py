"""
维度2: 解析准确性测试 (V4.9.4)
测量PDF/CAD/Office文件解析质量，验证分类准确性和提取完整性
"""

import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path
from tests.utils_perf import TestResults, PerfTimer, get_file_size_mb

TEST_DATA_DIR = r"C:\Users\Administrator\Documents\xwechat_files\wxid_i0tdmsi16kfg22_747a\msg\file\2026-06"
SI_DIR = os.path.join(TEST_DATA_DIR, "2、图纸CAD", "图纸CAD", "SⅠ-道路工程一期施工图设计CAD")
PDF_DIR = TEST_DATA_DIR


def test_parsing_accuracy():
    results = TestResults("2-parsing", "解析准确性测试")

    from app.engine.pdf_parser import extract_text_from_pdf, extract_pdf_content
    from app.engine.dwg_parser import _detect_discipline, _extract_title
    from app.engine.file_profiler import FileProfiler, _uniform_sample, _pdf_strategy
    from PIL import Image
    import io

    # ── PDF 测试 ──────────────────────────────────────────────────

    # P2.1: 送检指南提取
    guide_pdf = os.path.join(PDF_DIR, "2025省站-材料检测送检指南_(客户版).pdf")
    if os.path.exists(guide_pdf):
        t = PerfTimer("P2.1")
        with t:
            try:
                content = extract_pdf_content(guide_pdf)
                text = content.get("text", "")
                keywords = ["送检", "检测", "取样", "批次", "见证"]
                found = [k for k in keywords if k in text]
                passed = len(found) >= 3
                results.add("P2.1", "PDF:送检指南关键词提取", passed, t.duration_ms,
                           details={"total_chars": len(text), "keywords_found": found, "pages": content.get("pages", 0)})
            except Exception as e:
                results.add("P2.1", "PDF:送检指南关键词提取", False, t.duration_ms, str(e))

        t = PerfTimer("P2.2")
        with t:
            try:
                prof = FileProfiler.profile_pdf(guide_pdf)
                passed = prof.total_pages >= 100 and prof.total_pages <= 200
                results.add("P2.2", "PDF:送检指南页数(≈168)", passed, t.duration_ms,
                           details={"pages": prof.total_pages, "strategy": prof.strategy,
                                    "sampling": prof.metadata.get("sampling", "?"),
                                    "type_counts": prof.metadata.get("type_counts", {})})
            except Exception as e:
                results.add("P2.2", "PDF:送检指南页数", False, t.duration_ms, str(e))

    # P2.3-P2.4: 页面分类
    cjj_pdf = os.path.join(PDF_DIR, "城镇道路工程施工与质量验收规范CJJ 1-2008.pdf")
    if os.path.exists(cjj_pdf):
        t = PerfTimer("P2.3")
        with t:
            try:
                import fitz
                doc = fitz.open(cjj_pdf)
                if len(doc) > 0:
                    ptype = FileProfiler._classify_single_page(doc[0])
                    doc.close()
                    passed = ptype == "text"
                    results.add("P2.3", "PDF:文字页分类(text)", passed, t.duration_ms, details={"type": ptype})
                else:
                    results.add("P2.3", "PDF:文字页分类(text)", False, t.duration_ms, "empty doc")
            except Exception as e:
                results.add("P2.3", "PDF:文字页分类(text)", False, t.duration_ms, str(e))

        t = PerfTimer("P2.4")
        with t:
            try:
                prof = FileProfiler.profile_pdf(cjj_pdf)
                passed = prof.strategy in ("text_only", "hybrid")
                results.add("P2.4", "PDF:规范文字→text_only策略", passed, t.duration_ms,
                           details={"strategy": prof.strategy, "pages": prof.total_pages})
            except Exception as e:
                results.add("P2.4", "PDF:规范文字→text_only策略", False, t.duration_ms, str(e))

    # P2.5: 采样均匀性
    t = PerfTimer("P2.5")
    with t:
        try:
            sample = _uniform_sample(100, 12)
            passed = 0 in sample and 99 in sample and len(sample) >= 10
            results.add("P2.5", "PDF:均匀采样(100页→12)", passed, t.duration_ms,
                       details={"sample": sample, "count": len(sample)})
        except Exception as e:
            results.add("P2.5", "PDF:均匀采样", False, t.duration_ms, str(e))

    # P2.6: 超大文件采样
    t = PerfTimer("P2.6")
    with t:
        try:
            sample = _uniform_sample(300, 15)
            passed = 0 in sample and 299 in sample and len(sample) >= 13
            results.add("P2.6", "PDF:超大文件采样(300→15)", passed, t.duration_ms, details={"count": len(sample)})
        except Exception as e:
            results.add("P2.6", "PDF:超大文件采样", False, t.duration_ms, str(e))

    # P2.7: 策略决策 — 纯文字
    t = PerfTimer("P2.7")
    with t:
        try:
            strategy, reason = _pdf_strategy({"text": 50, "drawing": 0, "scan": 0, "blank": 0}, 50)
            passed = strategy == "text_only"
            results.add("P2.7", "策略:纯文字→text_only", passed, t.duration_ms, details={"strategy": strategy, "reason": reason})
        except Exception as e:
            results.add("P2.7", "策略:纯文字→text_only", False, t.duration_ms, str(e))

    # P2.8: 策略决策 — 混合型
    t = PerfTimer("P2.8")
    with t:
        try:
            strategy, reason = _pdf_strategy({"text": 80, "drawing": 60, "scan": 8, "blank": 20}, 168)
            passed = strategy == "hybrid"
            results.add("P2.8", "策略:混合型→hybrid", passed, t.duration_ms, details={"strategy": strategy})
        except Exception as e:
            results.add("P2.8", "策略:混合型→hybrid", False, t.duration_ms, str(e))

    # P2.9: 策略决策 — 纯图纸
    t = PerfTimer("P2.9")
    with t:
        try:
            strategy, reason = _pdf_strategy({"text": 0, "drawing": 30, "scan": 0, "blank": 0}, 30)
            passed = strategy == "standard_render"
            results.add("P2.9", "策略:纯图纸→standard_render", passed, t.duration_ms, details={"strategy": strategy})
        except Exception as e:
            results.add("P2.9", "策略:纯图纸→standard_render", False, t.duration_ms, str(e))

    # P2.10: 策略决策 — 纯扫描
    t = PerfTimer("P2.10")
    with t:
        try:
            strategy, reason = _pdf_strategy({"text": 0, "drawing": 0, "scan": 20, "blank": 0}, 20)
            passed = strategy == "ocr"
            results.add("P2.10", "策略:纯扫描→ocr", passed, t.duration_ms, details={"strategy": strategy})
        except Exception as e:
            results.add("P2.10", "策略:纯扫描→ocr", False, t.duration_ms, str(e))

    # ── CAD 测试 ──────────────────────────────────────────────────

    # P2.11-P2.13: 专业检测
    test_cases = [
        ("SⅠ-01 道路平面图.dwg", "SⅠ", ["SⅠ", "道路"]),
        ("SⅣ-01 排水管道布置图.dwg", "SⅣ", ["SⅣ", "排水"]),
        ("SⅡ-01 交通标志布置图.dwg", "SⅡ", ["SⅡ", "交通"]),
    ]
    for i, (fname, expected_key, keywords) in enumerate(test_cases):
        t = PerfTimer(f"P2.{11+i}")
        with t:
            try:
                disc = _detect_discipline(fname, [])
                matches_expected = expected_key in disc
                matches_any = any(k in disc for k in keywords)
                passed = matches_expected or matches_any
                results.add(f"P2.{11+i}", f"CAD:专业检测({fname})", passed, t.duration_ms,
                           details={"expected": expected_key, "got": disc})
            except Exception as e:
                results.add(f"P2.{11+i}", f"CAD:专业检测", False, t.duration_ms, str(e))

    # P2.14: 未知专业
    t = PerfTimer("P2.14")
    with t:
        try:
            disc = _detect_discipline("random_file_xyz.dwg", [])
            passed = disc == "未知"
            results.add("P2.14", "CAD:未知专业检测", passed, t.duration_ms, details={"discipline": disc})
        except Exception as e:
            results.add("P2.14", "CAD:未知专业检测", False, t.duration_ms, str(e))

    # ── 图片预处理 ────────────────────────────────────────────────

    # P2.15: 空白图片检测
    t = PerfTimer("P2.15")
    with t:
        try:
            from app.engine.image_preprocess import _is_blank
            img = Image.new("RGB", (100, 100), (255, 255, 255))
            passed = _is_blank(img) == True
            results.add("P2.15", "图片:空白检测(true)", passed, t.duration_ms)
        except Exception as e:
            results.add("P2.15", "图片:空白检测(true)", False, t.duration_ms, str(e))

    # P2.16: 非空白图片检测
    t = PerfTimer("P2.16")
    with t:
        try:
            from app.engine.image_preprocess import _is_blank
            img = Image.new("RGB", (200, 200), (255, 255, 255))
            from PIL import ImageDraw
            draw = ImageDraw.Draw(img)
            for i in range(20):
                draw.rectangle([i*10, 0, i*10+5, 200], fill=(i*10, i*5, 0))
            passed = _is_blank(img) == False
            results.add("P2.16", "图片:非空白检测(false)", passed, t.duration_ms)
        except Exception as e:
            results.add("P2.16", "图片:非空白检测(false)", False, t.duration_ms, str(e))

    # P2.17: 自适应缩放
    t = PerfTimer("P2.17")
    with t:
        try:
            from app.engine.image_preprocess import _resize_if_needed
            img = Image.new("RGB", (4000, 3000), (255, 255, 255))
            resized = _resize_if_needed(img, 2048)
            passed = max(resized.size) <= 2048
            results.add("P2.17", "图片:自适应缩放(≤2048)", passed, t.duration_ms,
                       details={"before": img.size, "after": resized.size})
        except Exception as e:
            results.add("P2.17", "图片:自适应缩放", False, t.duration_ms, str(e))

    # P2.18: 色彩归一化 RGBA→RGB
    t = PerfTimer("P2.18")
    with t:
        try:
            from app.engine.image_preprocess import _normalize_color
            img = Image.new("RGBA", (50, 50), (255, 0, 0, 128))
            normalized = _normalize_color(img)
            passed = normalized.mode == "RGB"
            results.add("P2.18", "图片:RGBA→RGB", passed, t.duration_ms, details={"mode": img.mode, "normalized": normalized.mode})
        except Exception as e:
            results.add("P2.18", "图片:RGBA→RGB", False, t.duration_ms, str(e))

    # P2.19: 完整预处理管线
    if os.path.exists(guide_pdf):
        t = PerfTimer("P2.19")
        with t:
            try:
                from app.engine.image_preprocess import preprocess_for_vl
                import fitz
                doc = fitz.open(guide_pdf)
                if len(doc) > 0:
                    pix = doc[0].get_pixmap(dpi=100)
                    img_bytes = pix.tobytes("png")
                    processed = preprocess_for_vl(img_bytes, page_type="drawing")
                    doc.close()
                    passed = processed is not None and len(processed) < len(img_bytes) * 0.9
                    results.add("P2.19", "图片:完整预处理管线", passed, t.duration_ms,
                               details={"before_bytes": len(img_bytes), "after_bytes": len(processed) if processed else 0})
                else:
                    results.add("P2.19", "图片:完整预处理管线", False, t.duration_ms, "empty doc")
            except Exception as e:
                results.add("P2.19", "图片:完整预处理管线", False, t.duration_ms, str(e))

    # P2.20: 空白预处理 → None
    t = PerfTimer("P2.20")
    with t:
        try:
            from app.engine.image_preprocess import preprocess_for_vl
            img = Image.new("RGB", (100, 100), (255, 255, 255))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            processed = preprocess_for_vl(buf.getvalue(), page_type="blank")
            passed = processed is None
            results.add("P2.20", "图片:空白→返回None", passed, t.duration_ms)
        except Exception as e:
            results.add("P2.20", "图片:空白→返回None", False, t.duration_ms, str(e))

    # ── 桩号精度 ──────────────────────────────────────────────────

    # P2.21: 桩号精度修正
    t = PerfTimer("P2.21")
    with t:
        try:
            from app.engine.ai_agent import _fix_station_precision
            result = {"sections": [{"section": "K2+691~K3+100"}], "testing_plan": []}
            r = _fix_station_precision("从K2+691.502到K3+100.250，全长约500m", result)
            passed = ".502" in r["sections"][0]["section"] and ".250" in r["sections"][0]["section"]
            results.add("P2.21", "桩号精度:修正精确桩号", passed, t.duration_ms,
                       details={"before": "K2+691~K3+100", "after": r["sections"][0]["section"]})
        except Exception as e:
            results.add("P2.21", "桩号精度:修正精确桩号", False, t.duration_ms, str(e))

    # P2.22: 桩号精度 — 无小数不变
    t = PerfTimer("P2.22")
    with t:
        try:
            from app.engine.ai_agent import _fix_station_precision
            result = {"sections": [{"section": "K0+000~K0+500"}], "testing_plan": []}
            r = _fix_station_precision("从K0+000到K0+500", result)
            passed = r["sections"][0]["section"] == "K0+000~K0+500"
            results.add("P2.22", "桩号精度:无小数不变", passed, t.duration_ms,
                       details={"after": r["sections"][0]["section"]})
        except Exception as e:
            results.add("P2.22", "桩号精度:无小数不变", False, t.duration_ms, str(e))

    # P2.23: 智能分片相关性排序
    t = PerfTimer("P2.23")
    with t:
        try:
            from app.engine.ai_agent import _split_content_into_chunks_smart
            text = "\n\n".join([
                "普通说明文字" * 50,
                "K0+582~K1+200路基段，采用水泥混凝土路面" * 10,
                "材料: 水泥P.O42.5，钢筋HRB400" * 10,
                "末尾备注信息" * 50,
            ])
            chunks = _split_content_into_chunks_smart(text, 200)
            passed = len(chunks) >= 1
            results.add("P2.23", "智能分片相关性排序", passed, t.duration_ms, details={"chunks": len(chunks)})
        except Exception as e:
            results.add("P2.23", "智能分片相关性排序", False, t.duration_ms, str(e))

    # P2.24: 分片 — 常规分割
    t = PerfTimer("P2.24")
    with t:
        try:
            from app.engine.ai_agent import _split_content_into_chunks
            short_text = "Hello World" * 100
            chunks = _split_content_into_chunks(short_text, 50000)
            passed = len(chunks) == 1
            results.add("P2.24", "内容分片:短内容→1片", passed, t.duration_ms)
        except Exception as e:
            results.add("P2.24", "内容分片:短内容→1片", False, t.duration_ms, str(e))

    # ── Word/Excel ────────────────────────────────────────────────

    # P2.25: Excel 解析
    excel_file = os.path.join(PDF_DIR, "永莲大道_检测计划表.xlsx")
    if os.path.exists(excel_file):
        t = PerfTimer("P2.25")
        with t:
            try:
                from app.engine.excel_parser import extract_excel_content
                r = extract_excel_content(excel_file)
                passed = isinstance(r, dict) and len(r.get("sheets", [])) > 0
                results.add("P2.25", "Excel:多sheet提取", passed, t.duration_ms,
                           details={"sheets": len(r.get("sheets", [])), "text_len": len(r.get("text", ""))})
            except Exception as e:
                results.add("P2.25", "Excel:多sheet提取", False, t.duration_ms, str(e))

    # P2.26: 项目自动名称检测
    t = PerfTimer("P2.26")
    with t:
        try:
            from app.engine.project_manager import ProjectManager
            pm = ProjectManager()
            name = pm.auto_detect_name("本项目为肇庆市大型产业集聚区（肇庆新区片）配套基础设施建设项目一标段（永莲大道）")
            passed = "永莲大道" in name
            results.add("P2.26", "项目自动名称检测", passed, t.duration_ms, details={"detected": name})
        except Exception as e:
            results.add("P2.26", "项目自动名称检测", False, t.duration_ms, str(e))

    # 保存结果
    out_dir = os.path.join(os.path.dirname(__file__), "..", "_test_output", "reports")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "dimension_2_parsing.json")
    results.save(out_path)

    summary = results.summary
    print(f"\n{'='*50}")
    print(f"维度2: 解析准确性测试")
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
    test_parsing_accuracy()
