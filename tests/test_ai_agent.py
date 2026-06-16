import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "material-testing-app"))

from app.engine.ai_agent import (
    _parse_json_response, _split_content_into_chunks,
    _deduplicate_testing_plan, _merge_structure_results,
    _fix_station_precision
)


class TestParseJsonResponse:
    def test_direct_valid_json(self):
        result = _parse_json_response('{"key": "value"}')
        assert result == {"key": "value"}

    def test_markdown_code_block(self):
        result = _parse_json_response('```json\n{"a": 1}\n```')
        assert result == {"a": 1}

    def test_markdown_no_lang(self):
        result = _parse_json_response('```\n{"b": 2}\n```')
        assert result == {"b": 2}

    def test_nested_in_text(self):
        result = _parse_json_response('prefix text {"c": 3} suffix')
        assert result == {"c": 3}

    def test_truncated_json(self):
        result = _parse_json_response('{"d": [1, 2, 3')
        assert "error" in result
        assert "truncated" in result["error"]

    def test_completely_invalid(self):
        result = _parse_json_response("not json at all")
        assert "error" in result


class TestSplitContentIntoChunks:
    def test_under_limit_no_split(self):
        content = "short content"
        chunks = _split_content_into_chunks(content, max_chars=80000)
        assert len(chunks) == 1
        assert chunks[0] == content

    def test_exact_boundary_split(self):
        content = "para1\n\npara2\n\npara3"
        chunks = _split_content_into_chunks(content, max_chars=10)
        assert len(chunks) >= 1

    def test_empty_content(self):
        chunks = _split_content_into_chunks("", max_chars=100)
        assert chunks == [""]

    def test_single_long_paragraph(self):
        content = "A" * 300
        chunks = _split_content_into_chunks(content, max_chars=100)
        assert len(chunks) >= 1  # single long para without sentence boundaries becomes 1 chunk
        assert all(len(c) <= 100 for c in chunks)


class TestDeduplicateTestingPlan:
    def test_no_duplicates(self):
        items = [
            {"section": "A", "material_name": "M1", "test_item": "T1"},
            {"section": "B", "material_name": "M2", "test_item": "T2"},
        ]
        result = _deduplicate_testing_plan(items)
        assert len(result) == 2

    def test_exact_duplicates_removed(self):
        items = [
            {"section": "A", "road_orientation": "双侧", "material_name": "M1",
             "test_item": "T1", "sub_project": "P1", "work_item": "W1"},
            {"section": "A", "road_orientation": "双侧", "material_name": "M1",
             "test_item": "T1", "sub_project": "P1", "work_item": "W1"},
        ]
        result = _deduplicate_testing_plan(items)
        assert len(result) == 1

    def test_partial_match_kept(self):
        items = [
            {"section": "A", "road_orientation": "双侧", "material_name": "M1",
             "test_item": "T1", "sub_project": "P1", "work_item": "W1"},
            {"section": "A", "road_orientation": "双侧", "material_name": "M1",
             "test_item": "T2", "sub_project": "P1", "work_item": "W1"},
        ]
        result = _deduplicate_testing_plan(items)
        assert len(result) == 2

    def test_empty_list(self):
        result = _deduplicate_testing_plan([])
        assert result == []


class TestMergeStructureResults:
    def test_single_result(self):
        results = [{"sections": [{"section": "K0+000~K0+100"}], "project_info": {"project_name": "Test"}}]
        merged = _merge_structure_results(results)
        assert len(merged["sections"]) == 1

    def test_multiple_results_dedup_sections(self):
        results = [
            {"sections": [{"section": "A"}, {"section": "B"}], "project_info": {}, "contract_info": {}, "key_notes": []},
            {"sections": [{"section": "B"}, {"section": "C"}], "project_info": {}, "contract_info": {}, "key_notes": []},
        ]
        merged = _merge_structure_results(results)
        names = [s["section"] for s in merged["sections"]]
        assert sorted(names) == ["A", "B", "C"]

    def test_all_errors_returns_empty(self):
        results = [{"error": "fail1"}, {"error": "fail2"}]
        merged = _merge_structure_results(results)
        assert merged["sections"] == []

    def test_first_project_info_wins(self):
        results = [
            {"sections": [], "project_info": {"project_name": "First"}, "contract_info": {}, "key_notes": []},
            {"sections": [], "project_info": {"project_name": "Second"}, "contract_info": {}, "key_notes": []},
        ]
        merged = _merge_structure_results(results)
        assert merged["project_info"]["project_name"] == "First"


class TestFixStationPrecision:
    """V4.8: 桩号小数精度修正"""

    def test_no_precision_available_returns_unchanged(self):
        """原始文本无小数桩号 → 原样返回"""
        text = "K0+582~K1+200 路基填方段"
        result = {
            "sections": [{"section": "K0+582~K1+200"}],
            "testing_plan": [{"section": "K0+582~K1+200"}],
        }
        fixed = _fix_station_precision(text, result)
        assert fixed["sections"][0]["section"] == "K0+582~K1+200"

    def test_fixes_integer_station_to_decimal_from_range(self):
        """原始文本 K2+691.502~K3+100.250 → AI 返回 K2+691~K3+100 → 自动修复"""
        text = "K2+691.502~K3+100.250 填方段"
        result = {
            "sections": [{"section": "K2+691~K3+100"}],
            "testing_plan": [{"section": "K2+691~K3+100"}],
        }
        fixed = _fix_station_precision(text, result)
        assert fixed["sections"][0]["section"] == "K2+691.502~K3+100.250"
        assert fixed["testing_plan"][0]["section"] == "K2+691.502~K3+100.250"

    def test_fixes_single_station_precision(self):
        """单点桩号 K2+691.502 → AI 返回 K2+691 → 自动修复"""
        text = "桥梁起点 K2+691.502"
        result = {
            "sections": [{"section": "K2+691~K2+800"}],
            "testing_plan": [{"section": "K2+691~K2+800"}],
        }
        fixed = _fix_station_precision(text, result)
        assert fixed["sections"][0]["section"] == "K2+691.502~K2+800"
        assert fixed["testing_plan"][0]["section"] == "K2+691.502~K2+800"

    def test_preserves_already_precise_stations(self):
        """已有小数的桩号不被修改（只修正整数桩号）"""
        text = "K2+691.502"
        result = {
            "sections": [{"section": "K2+691.5~K3+100.2"}],
            "testing_plan": [{"section": "K2+691.5"}],
        }
        fixed = _fix_station_precision(text, result)
        # K2+691.5 已有小数，不被修正；只修正无小数的 K2+691
        assert fixed["sections"][0]["section"] == "K2+691.5~K3+100.2"
        assert fixed["testing_plan"][0]["section"] == "K2+691.5"

    def test_only_fixes_integer_stations_not_partial_decimals(self):
        """整数桩号被修复，已有小数的保留不变"""
        text = "K2+691.502~K3+100.250"
        result = {
            "sections": [{"section": "K2+691~K3+100.5"}],
            "testing_plan": [{"section": "K2+691.5~K3+100"}],
        }
        fixed = _fix_station_precision(text, result)
        # sections: K2+691(int)→K2+691.502, K3+100.5(已有小数)→保留
        assert fixed["sections"][0]["section"] == "K2+691.502~K3+100.5"
        # testing_plan: K2+691.5(已有小数)→保留, K3+100(int)→K3+100.250
        assert fixed["testing_plan"][0]["section"] == "K2+691.5~K3+100.250"

    def test_fixes_construction_layers(self):
        """construction_layers 中的桩号也需修正"""
        text = "K0+582.000~K1+200.500"
        result = {
            "sections": [],
            "testing_plan": [],
            "construction_layers": [
                {"section": "K0+582~K1+200", "layer_name": "路基填筑"}
            ],
        }
        fixed = _fix_station_precision(text, result)
        assert fixed["construction_layers"][0]["section"] == "K0+582.000~K1+200.500"

    def test_fixes_project_info_road_length(self):
        """project_info.road_length 也需修正"""
        text = "道路全长 K0+582.000~K3+872.500"
        result = {
            "project_info": {"road_length": "K0+582~K3+872"},
            "sections": [],
            "testing_plan": [],
        }
        fixed = _fix_station_precision(text, result)
        assert fixed["project_info"]["road_length"] == "K0+582.000~K3+872.500"

    def test_empty_text_returns_unchanged(self):
        """空文本 → 原样返回"""
        result = {"sections": [{"section": "K2+691~K3+100"}]}
        fixed = _fix_station_precision("", result)
        assert fixed["sections"][0]["section"] == "K2+691~K3+100"

    def test_no_stations_in_text_returns_unchanged(self):
        """文本中无桩号 → 原样返回"""
        result = {"sections": [{"section": "K2+691~K3+100"}]}
        fixed = _fix_station_precision("这是一段没有桩号的描述文本", result)
        assert fixed["sections"][0]["section"] == "K2+691~K3+100"

    # ── V5.1 新增测试 ──

    def test_dk_prefix_station(self):
        """V5.1: DK 前缀桩号也正确识别和修正"""
        text = "DK0+582.502~DK1+200.250 填方段"
        result = {
            "sections": [{"section": "DK0+582~DK1+200"}],
            "testing_plan": [{"section": "DK0+582~DK1+200"}],
        }
        fixed = _fix_station_precision(text, result)
        assert fixed["sections"][0]["section"] == "DK0+582.502~DK1+200.250"

    def test_station_with_label_prefix(self):
        """V5.1: 桩号/里程 标签前缀也识别"""
        text = "桩号: K1+234.567 为起点，里程: K2+345.678 为终点"
        result = {
            "sections": [{"section": "K1+234~K2+345"}],
        }
        fixed = _fix_station_precision(text, result)
        assert fixed["sections"][0]["section"] == "K1+234.567~K2+345.678"

    def test_spaced_station_format(self):
        """V5.1: K 和数字之间有空格也能识别"""
        text = "K 2+691.502~K 3+100.250"
        result = {
            "sections": [{"section": "K2+691~K3+100"}],
        }
        fixed = _fix_station_precision(text, result)
        assert fixed["sections"][0]["section"] == "K2+691.502~K3+100.250"

    def test_confidence_low_when_no_match(self):
        """V5.1: AI 输出桩号在原文中完全找不到时标记 station_confidence=low"""
        text = "K0+582.000~K1+200.500 填方段"
        result = {
            "sections": [{"section": "K9+999~K9+999"}],
            "testing_plan": [{"section": "K9+999~K9+999"}],
        }
        fixed = _fix_station_precision(text, result)
        assert fixed["sections"][0].get("station_confidence") == "low"
        assert fixed["testing_plan"][0].get("station_confidence") == "low"

    def test_confidence_ok_when_prefix_match(self):
        """V5.1: 桩号前缀匹配时不标记 low（如 K2+691 对 K2+691.502 匹配前6字符）"""
        text = "K2+691.502~K3+100.250"
        result = {
            "sections": [{"section": "K2+691~K3+100"}],
        }
        fixed = _fix_station_precision(text, result)
        # 修复后应变为精确值，且无 station_confidence=low
        assert fixed["sections"][0]["section"] == "K2+691.502~K3+100.250"
        assert "station_confidence" not in fixed["sections"][0] or fixed["sections"][0].get("station_confidence") == ""

    def test_preserves_kline_prefix(self):
        """V5.1: K线前缀桩号识别"""
        text = "K线 K0+123.456~K0+789.012"
        result = {
            "sections": [{"section": "K0+123~K0+789"}],
        }
        fixed = _fix_station_precision(text, result)
        assert fixed["sections"][0]["section"] == "K0+123.456~K0+789.012"
