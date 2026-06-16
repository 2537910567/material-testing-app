"""
Qwen-VL 视觉分析模块 (V5.1)

模型策略：所有图纸统一使用 qwen3.7-plus（百炼平台）。
V5.1: Prompt 模板迁移至 prompts.py, 方向识别规则从 6→3 步简化。
"""

import base64
from typing import Dict, Any, Optional, List

from .model_provider import (
    QwenVLProvider,
    QWEN_VL_MODEL,
)
from .prompts import (
    CROSS_SECTION_SYSTEM as CROSS_SECTION_SYSTEM_PROMPT,
    CROSS_SECTION_USER,
    PLAN_DRAWING_SYSTEM as PLAN_DRAWING_SYSTEM_PROMPT,
    PLAN_DRAWING_USER,
)
from ..logger import get_logger

logger = get_logger(__name__)


# ==================== 横断面图分析 ====================


def analyze_cross_section(
    api_key: str,
    image_data: bytes,
    image_format: str = "png",
    file_name: str = "",
) -> Dict[str, Any]:
    """
    分析横断面图图片（V4.8: 统一使用 qwen3.7-plus）。
    """
    provider = QwenVLProvider(api_key, QWEN_VL_MODEL)

    file_hint = f' Filename: "{file_name}"' if file_name else ""
    user_prompt = CROSS_SECTION_USER.format(file_hint=file_hint)

    logger.info("Qwen-VL cross-section: %s (%d bytes, model=%s)",
                 file_name, len(image_data), provider.model_name)

    result = provider.call_with_image(image_data, image_format, user_prompt)

    if "error" in result:
        logger.warning("Qwen-VL cross-section failed: %s", result["error"])
        return {
            "pile_numbers": [], "road_orientation": "",
            "road_orientation_confidence": "low",
            "road_orientation_reason": "API error: " + str(result["error"])[:100],
            "road_orientation_evidence": {},
            "cross_section_features": {},
            "east_west": "未知", "description": "",
            "error": result["error"],
        }
    result.setdefault("pile_numbers", [])
    result.setdefault("road_orientation", "")
    result.setdefault("road_orientation_confidence", "medium")
    result.setdefault("road_orientation_reason", "")
    result.setdefault("road_orientation_evidence", {})
    result.setdefault("cross_section_features", {})
    result.setdefault("east_west", "未知")
    result.setdefault("description", "")
    return result


# ==================== 平面图分析 ====================


def analyze_plan_drawing(
    api_key: str,
    image_data: bytes,
    image_format: str = "png",
    file_name: str = "",
) -> Dict[str, Any]:
    """
    分析平面图图片（V4.8: 统一使用 qwen3.7-plus）。

    Returns:
        {
            "chainage_ranges": ["K0+582~K1+200"],
            "road_features": ["交叉口", "排水管"],
            "materials": [{"name": "钢筋", "spec": "HRB400", "location": "..."}],
            "tables": [["col1", "col2"], ...],
            "description": "..."
        }
    """
    provider = QwenVLProvider(api_key, QWEN_VL_MODEL)

    file_hint = f' ({file_name})' if file_name else ''
    user_prompt = PLAN_DRAWING_USER.format(file_hint=file_hint)

    logger.info("Qwen-VL plan drawing: %s (%d bytes, model=%s)",
                 file_name, len(image_data), provider.model_name)

    result = provider.call_with_image(image_data, image_format, user_prompt)

    if "error" in result:
        logger.warning("Qwen-VL plan drawing failed: %s", result["error"])
        return {
            "chainage_ranges": [], "road_features": [],
            "materials": [], "tables": [], "description": "",
            "error": result["error"],
        }
    result.setdefault("chainage_ranges", [])
    result.setdefault("road_features", [])
    result.setdefault("materials", [])
    result.setdefault("tables", [])
    result.setdefault("description", "")
    return result


# ==================== 统一入口 ====================

def analyze_drawing(
    provider,
    image_paths: List[str],
    drawing_type: str = "plan",
    batch_size: int = 4,
) -> Dict[str, Any]:
    """
    Analyze drawing images using Qwen-VL (V6.0: 批量多图 + 复用 provider).

    Args:
        provider: QwenVLProvider instance（复用，不每次新建）
        image_paths: list of PNG file paths（全量，无上限）
        drawing_type: "cross_section" or "plan"
        batch_size: 每批图片数（默认 4，范围 3-5 安全）

    Returns:
        dict with material_text, results, type, model
        or {"error": "..."} on failure
    """
    import os

    results = []
    model_name = provider.model_name

    # V6.0: 图片预处理 — 空白过滤 + 不缩放
    from .image_preprocess import preprocess_for_vl

    # V6.0: 分批收集图片
    # 读取+预处理所有图片，收集有效图片
    valid_images = []  # [(image_data, format), ...]
    for img_path in image_paths:
        if not os.path.exists(img_path):
            continue
        try:
            with open(img_path, "rb") as f:
                image_data = f.read()

            # V6.0: max_long_edge=0 不缩放，保留全部像素
            ptype = "drawing"
            processed = preprocess_for_vl(image_data, page_type=ptype)
            if processed is None:
                logger.info("analyze_drawing: 空白图片已跳过 — %s", img_path)
                continue
            valid_images.append((processed, "jpeg"))
        except Exception as e:
            logger.warning("analyze_drawing: preprocess failed for %s: %s", img_path, str(e))

    if not valid_images:
        return {"error": "No valid images to analyze"}

    # V6.0: 分批发送（每批 batch_size 张）
    # 单张也走批量模式（batch_size=1），通过 call_with_image 列表形式
    total_batches = (len(valid_images) + batch_size - 1) // batch_size
    logger.info("analyze_drawing: %d images → %d batches (batch_size=%d, model=%s)",
                 len(valid_images), total_batches, batch_size, model_name)

    for batch_idx in range(0, len(valid_images), batch_size):
        batch = valid_images[batch_idx:batch_idx + batch_size]

        # 根据 drawing_type 选择 prompt
        if drawing_type == "cross_section":
            prompt = CROSS_SECTION_USER.format(file_hint="")
        else:
            prompt = PLAN_DRAWING_USER.format(file_hint="")

        try:
            # V6.0: 列表形式 → provider 自动走多图模式
            res = provider.call_with_image(batch, None, prompt)
        except Exception as e:
            logger.warning("analyze_drawing: batch %d failed: %s",
                           batch_idx // batch_size + 1, str(e))
            continue

        if "error" in res:
            logger.warning("analyze_drawing: batch %d error: %s",
                           batch_idx // batch_size + 1, res["error"])
            continue

        results.append({
            "type": drawing_type,
            "model": model_name,
            "result": res,
        })

    if not results:
        return {"error": "No images could be analyzed"}

    material_text = extract_material_text_from_qwen_results(results)
    return {
        "material_text": material_text,
        "results": results,
        "type": drawing_type,
        "model": model_name,
    }


# 横断面图文件名关键词（保留用于判断 drawing_type，非模型选择）
CROSS_SECTION_PATTERNS = [
    "断面", "DM", "横断", "HD", "纵断", "ZD",
    "HENGDUAN", "ZONGDUAN", "CROSS",
]


def is_cross_section_drawing(filename: str) -> bool:
    """判断是否为横断面图（用于选择合适的分析 prompt）"""
    name_upper = filename.upper()
    for pattern in CROSS_SECTION_PATTERNS:
        if pattern.upper() in name_upper:
            return True
    return False


def extract_material_text_from_qwen_results(qwen_results: List[Dict]) -> str:
    """
    从千问分析结果中提取材料相关文本，用于补充 DeepSeek 文本分析。

    将 Qwen-VL 视觉分析得到的材料标注、表格数据、路段特征、精确尺寸
    转换成纯文本，合并到主文本中供 DeepSeek 分析。
    V4.7: 增加精确尺寸数据（road_width_m, layer_thicknesses）传递。
    """
    parts = ["\n=== Qwen-VL 视觉分析提取 ==="]
    for r in qwen_results:
        if r["type"] == "cross_section":
            res = r.get("result", {})
            parts.append(f"\n[横断面图 {r.get('model', '')}]")
            parts.append(f"桩号: {', '.join(res.get('pile_numbers', []))}")
            parts.append(f"路幅: {res.get('road_orientation', '')}")
            if res.get('road_orientation_confidence') == 'low':
                parts.append(f"⚠️ 路幅置信度: LOW - {res.get('road_orientation_reason', '')}")
            # V4.7: Precise dimensions for batch calculation
            evidence = res.get("road_orientation_evidence", {})
            if evidence:
                parts.append(f"车道数: 左{evidence.get('lane_count_left', 0)} / 右{evidence.get('lane_count_right', 0)}")
                if evidence.get("lane_width_left_m"):
                    parts.append(f"车道宽: 左{evidence['lane_width_left_m']}m / 右{evidence.get('lane_width_right_m', 0)}m")
            features = res.get("cross_section_features", {})
            if features:
                if features.get("road_width_total_m"):
                    parts.append(f"路面总宽: {features['road_width_total_m']}m")
                if features.get("median_width_m"):
                    parts.append(f"中央分隔带宽: {features['median_width_m']}m")
                if features.get("shoulder_width_left_m"):
                    parts.append(f"硬路肩/人行道: 左{features['shoulder_width_left_m']}m / 右{features.get('shoulder_width_right_m', 0)}m")
            # V4.7: Layer thicknesses for planned_batches calculation
            layers = res.get("layer_thicknesses", [])
            if layers:
                parts.append("路面结构层厚 (从上到下):")
                for lt in layers:
                    parts.append(f"  - {lt.get('layer_name', '?')}: {lt.get('thickness_mm', '?')}mm")
            parts.append(f"走向: {res.get('east_west', '未知')}")
            if res.get("description"):
                parts.append(f"描述: {res['description']}")
        else:
            res = r.get("result", {})
            parts.append(f"\n[平面图 {r.get('model', '')}]")
            if res.get("chainage_ranges"):
                parts.append(f"桩号范围: {', '.join(res['chainage_ranges'])}")
            if res.get("road_features"):
                parts.append(f"道路特征: {', '.join(res['road_features'])}")
            if res.get("description"):
                parts.append(f"描述: {res['description']}")
            if res.get("materials"):
                parts.append("材料标注:")
                for m in res["materials"]:
                    parts.append(f"  - {m.get('name', '')} {m.get('spec', '')} ({m.get('location', '')})")
            if res.get("tables"):
                parts.append("表格数据:")
                for row in res["tables"]:
                    parts.append(" | ".join(str(c) for c in row))

    return "\n".join(parts)
