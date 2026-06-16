"""
DeepSeek API 集成模块 (V5.1)
多轮分步分析 — 先识别结构，再按路段分组分析材料，避免 JSON 截断
V5.1: Prompt 模板迁移至 prompts.py, JSON 解析统一入口在 model_provider.py
"""

import json
import re
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional

from ..logger import get_logger
from .prompts import (
    STRUCTURE_DETECTION_SYSTEM, STRUCTURE_DETECTION_USER,
    MATERIAL_ANALYSIS_SYSTEM, MATERIAL_ANALYSIS_USER,
    FALLBACK_SYSTEM, FALLBACK_USER,
    build_material_system_with_fewshot,
)
from .standards_matcher import (
    extract_keywords, match_standards, inject_matched_standards_to_prompt,
)
from .model_provider import _parse_json_response  # V5.1: 统一入口

logger = get_logger(__name__)

DEEPSEEK_MODEL = "deepseek-v4-flash"
CONTENT_MAX_CHARS = 80000


# ==================== Content chunking ====================

def _split_content_into_chunks(content: str, max_chars: int = CONTENT_MAX_CHARS) -> List[str]:
    """
    按段落边界（连续换行符）将超长内容拆分为多个等大片段。

    每片段尽量不超过 max_chars；如果单个段落超过限制，则在句子边界处截断。
    """
    if len(content) <= max_chars:
        return [content]

    paragraphs = re.split(r'\n{2,}', content)
    chunks = []
    current = ""

    for para in paragraphs:
        if len(current) + len(para) + 2 <= max_chars:
            current = (current + "\n\n" + para) if current else para
        else:
            if current:
                chunks.append(current.strip())
            # 单段落超大：按句子边界截断
            if len(para) > max_chars:
                sentences = re.split(r'(?<=[。！？\n])\s*', para)
                current = ""
                for sent in sentences:
                    if len(current) + len(sent) <= max_chars:
                        current += sent
                    else:
                        if current:
                            chunks.append(current.strip())
                        current = sent[:max_chars]
            else:
                current = para

    if current.strip():
        chunks.append(current.strip())

    logger.info("Content split into %d chunks (max %d chars each)", len(chunks), max_chars)
    return chunks


def _split_content_into_chunks_smart(content: str, max_chars: int = CONTENT_MAX_CHARS) -> List[str]:
    r"""
    V4.6: 智能分片 — 按段落相关性排序，优先保留高分段落。
    避免超长内容导致分片数量爆炸，提升 AI 分析质量。

    提取关键词：桩号 (K\d+\+\d+)、材料名、标准编号，
    每个段落计算相关性得分，高分段落优先保留。
    """
    if len(content) <= max_chars:
        return [content]

    # Step 1: 关键词提取
    section_pattern = r'K\d+\+[\d.]+'
    material_pattern = r'(混凝土|钢筋|沥青|水泥|砂石|砖|石灰|掺合料|外加剂|管材|电缆|PE管|HDPE|PVC|砌块|砂浆|路基填料)'
    standard_pattern = r'(GB\s*\d+[.\d]*\s*-\s*\d{4}|GB/T\s*\d+[.\d]*\s*-\s*\d{4}|JTG\s*[A-Z]?\d*\s*-\s*\d{4}|CJJ\s*\d+\s*-\s*\d{4}|DBJ/T\s*\d+\s*-\s*\d{4})'

    # Step 2: 段落拆分 + 相关性评分
    paragraphs = re.split(r'\n{2,}', content)

    def _relevance(para: str) -> int:
        score = 0
        if re.search(section_pattern, para):
            score += 3  # 桩号最重要
        if re.search(material_pattern, para):
            score += 2  # 材料名
        if re.search(standard_pattern, para):
            score += 2  # 标准编号
        if '分部' in para or '分项' in para or '检验批' in para:
            score += 1
        return score

    scored = [(p, _relevance(p)) for p in paragraphs]
    # V5.3: 保留原始文档顺序（工程文档桩号/施工层有连续上下文，乱序会误导 AI）

    # Step 3: 分片（按原始顺序，相关性仅用于决定边界位置）
    chunks = []
    current = ""
    for para, score in scored:
        if len(current) + len(para) + 2 <= max_chars:
            current = (current + "\n\n" + para) if current else para
        else:
            if current:
                chunks.append(current.strip())
            # 单段落超大：截断
            current = para[:max_chars] if len(para) > max_chars else para

    if current.strip():
        chunks.append(current.strip())

    logger.info("Smart chunking: %d paragraphs → %d chunks (relevance-sorted)", len(paragraphs), len(chunks))
    return chunks


def _deduplicate_testing_plan(items: List[Dict]) -> List[Dict]:
    """按 composite key 去重，保留首次出现顺序"""
    seen = set()
    unique = []
    for item in items:
        key = tuple(str(item.get(f, "")) for f in (
            "section", "road_orientation", "material_name",
            "test_item", "sub_project", "work_item"
        ))
        if key not in seen:
            seen.add(key)
            unique.append(item)
    if len(items) != len(unique):
        logger.info("Dedup: %d items → %d unique", len(items), len(unique))
    return unique


def _deduplicate_text(cad_text: str, pdf_text: str) -> str:
    """
    V6.0: CAD+PDF 混合模式下的文字去重。

    同一份工程文档通过 CAD 和 PDF 提取后会有大量重复内容
    （材料表、标准编号、桩号说明等）。合并后逐行去重，
    保留 PDF 文字在前（更完整），CAD 文字补充不同的行。

    Args:
        cad_text: CAD/DXF 提取的文字
        pdf_text: PDF 提取的文字

    Returns:
        去重合并后的文字
    """
    if not cad_text:
        return pdf_text
    if not pdf_text:
        return cad_text

    pdf_lines = pdf_text.split("\n")
    cad_lines = cad_text.split("\n")

    # PDF 在前，CAD 中未出现的行追加
    seen = set()
    merged = []
    for line in pdf_lines:
        stripped = line.strip()
        if stripped and stripped not in seen:
            seen.add(stripped)
        merged.append(line)

    added = 0
    for line in cad_lines:
        stripped = line.strip()
        if stripped and stripped not in seen:
            seen.add(stripped)
            merged.append(line)
            added += 1

    result = "\n".join(merged)
    logger.info("Text dedup: PDF %d lines + CAD %d lines → %d lines (%d new from CAD)",
                len(pdf_lines), len(cad_lines), len(merged), added)
    return result


def _extract_sections_from_plan(testing_plan: List[Dict]) -> List[Dict]:
    """V4.5.3: 从 testing_plan 提取唯一的 (section, road_orientation) 组合为 sections。
    AI fallback 路径返回的 JSON 没有 sections 字段，需要从送检计划中逆向提取。"""
    seen = set()
    sections = []
    for item in testing_plan:
        sec = item.get("section", "")
        lr = item.get("road_orientation", "")
        if not sec:
            continue
        key = (sec, lr)
        if key not in seen:
            seen.add(key)
            sections.append({"section": sec, "road_orientation": lr or ""})
    return sections


def _fix_station_precision(original_text: str, result: Dict) -> Dict:
    """
    V5.1: 从原始文档文本提取精确桩号（含3位小数），修正 AI 舍入的桩号值。

    问题: AI 可能将 K2+691.502 简化为 K2+691，导致桩号精度丢失。
    方案: 从原始 CAD/PDF 文本中用正则提取所有含小数的桩号，构建
          "整数版→精确版" 映射，自动修正 result 中的 section/桩号字段。

    V5.1 增强:
    - 支持更多桩号前缀 (DK, 桩号, 里程, K线)
    - K0+000 格式完整性校验
    - AI 输出桩号在原文中完全找不到时标记 station_confidence: "low"

    处理范围: sections[].section, testing_plan[].section,
             construction_layers[].section, project_info.road_length
    """
    if not original_text:
        return result

    # Step 1: 从原始文本提取所有含小数的桩号
    # V5.1: 扩展前缀支持 — K, DK, 桩号, 里程
    station_pattern = r'(?:DK|K)\s*\d+\+[\d.]+'
    # 范围提取 (K0+000.000~K1+000.000)
    range_matches = re.findall(rf'({station_pattern})\s*~\s*({station_pattern})', original_text)
    # 单点桩号 (3位小数，典型 CAD 标注精度)
    single_matches = re.findall(r'(?:DK|K)\s*\d+\+\d+\.\d{2,}', original_text)
    # 桩号/里程 上下文模式
    label_matches = re.findall(r'(?:桩号|里程|K线)\s*[:：]?\s*((?:DK|K)\s*\d+\+[\d.]+)', original_text)

    if not range_matches and not single_matches:
        # V5.1: 无精确桩号时标记低置信度
        has_stations_in_result = bool(
            result.get("sections") or result.get("testing_plan")
        )
        if has_stations_in_result:
            logger.info("桩号精度修正: 原始文本中未找到含小数桩号，部分桩号可能精度不足")
        return result

    # Step 2: 构建修正映射
    station_map: Dict[str, str] = {}   # "K2+691" → "K2+691.502"
    range_map: Dict[str, str] = {}     # "K2+691~K3+100" → "K2+691.502~K3+100.250"

    # 规范化函数：移除多余空格
    def _norm(s: str) -> str:
        return re.sub(r'\s+', '', s)

    for start, end in range_matches:
        start_n = _norm(start)
        end_n = _norm(end)
        start_int = re.sub(r'\.\d+$', '', start_n)
        end_int = re.sub(r'\.\d+$', '', end_n)
        truncated = f"{start_int}~{end_int}"
        precise = f"{start_n}~{end_n}"
        if truncated != precise:
            range_map[truncated] = precise
        if start_int != start_n:
            station_map[start_int] = start_n
        if end_int != end_n:
            station_map[end_int] = end_n

    for station in single_matches:
        s_norm = _norm(station)
        station_int = re.sub(r'\.\d+$', '', s_norm)
        if station_int != s_norm:
            # 有冲突时保留小数位更长的版本
            if station_int not in station_map or len(s_norm) > len(station_map[station_int]):
                station_map[station_int] = s_norm

    # V5.1: 扩展映射 - 桩号/里程/K线前缀版本
    for m in label_matches:
        s_norm = _norm(m)
        if '.' in s_norm:
            station_int = re.sub(r'\.\d+$', '', s_norm)
            if station_int != s_norm:
                if station_int not in station_map or len(s_norm) > len(station_map[station_int]):
                    station_map[station_int] = s_norm

    if not station_map and not range_map:
        return result

    logger.info("桩号精度修正: %d 个站点映射, %d 个范围映射",
                len(station_map), len(range_map))

    # V5.1: 构建原文中所有完整桩号的集合，用于置信度检查
    all_source_stations = set()
    all_source_stations.update(station_map.values())
    for _s in single_matches:
        all_source_stations.add(_norm(_s))
    for _s in label_matches:
        all_source_stations.add(_norm(_s))

    def _check_station_confidence(section_val: str) -> str:
        """V5.1: 检查 AI 输出的桩号是否在原文中有匹配"""
        if not section_val or '~' not in section_val:
            return "low" if (section_val and _norm(section_val) not in all_source_stations
                           and not any(_norm(section_val).startswith(s[:6]) for s in all_source_stations if s)) else ""
        # 范围桩号
        parts = section_val.split('~')
        found_any = False
        for p in parts:
            pn = _norm(p.strip())
            if pn in all_source_stations:
                found_any = True
                break
            # 前缀匹配（前6个字符）
            if any(s.startswith(pn[:6]) for s in all_source_stations if s and len(s) >= 6):
                found_any = True
                break
        return "" if found_any else "low"

    # Step 3: 修正函数
    def _fix_value(val: str) -> str:
        """修正单个桩号字符串"""
        if not val:
            return val
        val_n = _norm(val)
        # 先尝试精确匹配完整范围
        for truncated, precise in range_map.items():
            if val_n == truncated:
                return precise
        # 替换字符串中的整数桩号为精确桩号（跳过已有小数的）
        def _replace_station(m):
            full = m.group(0)
            full_n = _norm(full)
            return station_map.get(full_n, full)
        return re.sub(r'(?:DK|K)\s*\d+\+\d+(?![.\d])', _replace_station, val)

    # Step 4: 修正 result 各字段 + V5.1 置信度标记
    low_confidence_sections = []

    for s in result.get("sections", []):
        if s.get("section"):
            s["section"] = _fix_value(s["section"])
            conf = _check_station_confidence(s["section"])
            if conf == "low":
                s["station_confidence"] = "low"
                low_confidence_sections.append(s["section"])

    for item in result.get("testing_plan", []):
        if item.get("section"):
            item["section"] = _fix_value(item["section"])
            conf = _check_station_confidence(item["section"])
            if conf == "low":
                item["station_confidence"] = "low"

    for layer in result.get("construction_layers", []):
        if layer.get("section"):
            layer["section"] = _fix_value(layer["section"])

    pi = result.get("project_info", {})
    if pi.get("road_length"):
        pi["road_length"] = _fix_value(pi["road_length"])

    if low_confidence_sections:
        logger.warning("桩号置信度 low: %s (原文中未找到匹配)", low_confidence_sections[:5])

    return result


def _merge_structure_results(results: List[Dict]) -> Dict:
    """
    合并多个 chunk 的结构检测结果。
    sections 取并集（按桩号范围去重），project_info 取第一个非空的。
    """
    if not results:
        return {"sections": [], "project_info": {}, "contract_info": {}, "key_notes": []}
    if len(results) == 1:
        return results[0]

    merged_sections = []
    seen_ranges = set()
    for r in results:
        if "error" in r:
            continue
        for s in r.get("sections", []):
            sec_name = s.get("section", s.get("name", ""))
            if sec_name and sec_name not in seen_ranges:
                seen_ranges.add(sec_name)
                merged_sections.append(s)

    # 取第一个有内容的 project_info
    project_info = {}
    for r in results:
        pi = r.get("project_info", {})
        if pi.get("project_name") or pi.get("location"):
            project_info = pi
            break

    contract_info = {}
    key_notes = []
    for r in results:
        if r.get("contract_info") and not contract_info:
            contract_info = r["contract_info"]
        key_notes.extend(r.get("key_notes", []))

    return {
        "sections": merged_sections,
        "project_info": project_info,
        "contract_info": contract_info,
        "key_notes": list(set(key_notes)),
    }


# ==================== Prompts：单次完整分析（回退用） ====================

def _build_system_prompt() -> str:
    """[deprecated] Fallback single-pass system prompt — use multi-round structure+material flow instead."""
    return FALLBACK_SYSTEM


def _build_user_prompt(content: str) -> str:
    """[deprecated] Fallback single-pass user prompt."""
    return FALLBACK_USER.format(content=content)


# ==================== Prompts：结构识别（第1轮） ====================

def _build_structure_system_prompt() -> str:
    """Step 1 system prompt — external template from prompts.py (V5.1)."""
    return STRUCTURE_DETECTION_SYSTEM


def _build_structure_user_prompt(content: str) -> str:
    """Step 1 user prompt — format with document content."""
    return STRUCTURE_DETECTION_USER.format(content=content)


# ==================== Prompts：材料分析（第2+轮） ====================

def _build_material_system_prompt(discipline: str = "") -> str:
    """V5.3: Step 2 system prompt — 含专业匹配 Few-Shot 示例."""
    return build_material_system_with_fewshot(discipline)


def _build_material_user_prompt(content: str, sections: List[Dict], project_info: Dict) -> str:
    """Step 2 user prompt — format with target sections, project context, and document content."""
    sec_list = "\n".join(
        f"  - {s.get('section', s.get('name', ''))}: {s.get('description', '')} "
        f"[分部: {', '.join(s.get('sub_projects', []))}]"
        for s in sections
    )

    return MATERIAL_ANALYSIS_USER.format(
        sec_list=sec_list,
        project_name=project_info.get('project_name', ''),
        location=project_info.get('location', ''),
        road_length=project_info.get('road_length', ''),
        content=content,
    )



# ==================== 标准提取与 Prompt 增强 ====================

def _extract_standards_from_content(content: str) -> List[str]:
    """
    从上传文档内容中自动提取标准编号。

    匹配常见的标准编号格式：
    - GB 55032-2022, GB/T 50081-2019
    - JTG E20-2011, JTG 3450-2019
    - CJJ 1-2008
    - DBJ/T15-38-2019
    """
    patterns = [
        r'GB\s*\d+(?:\.\d+)?\s*-\s*\d{4}',           # GB 175-2023, GB 1499.1-2024
        r'GB/T\s*\d+(?:\.\d+)?\s*-\s*\d{4}',         # GB/T 50081-2019
        r'GBZ\s*\d+\s*-\s*\d{4}',                     # GBZ 标准
        r'JTG\s*[A-Z]?\d*\s*-\s*\d{4}',               # JTG E20-2011, JTG 3420-2020
        r'JTG/T\s*[A-Z]?\d*\s*-\s*\d{4}',             # JTG/T 推荐标准
        r'CJJ\s*\d+\s*-\s*\d{4}',                     # CJJ 1-2008
        r'DBJ/T\s*\d+\s*-\s*\d{4}',                   # DBJ/T15-38-2019
        r'JGJ\s*\d+\s*-\s*\d{4}',                     # JGJ 建筑行业标准
        r'JC/T\s*\d+\s*-\s*\d{4}',                    # JC/T 建材行业标准
        r'JT/T\s*\d+\s*-\s*\d{4}',                    # JT/T 交通行业标准
    ]

    standards = set()
    for pattern in patterns:
        matches = re.findall(pattern, content, re.IGNORECASE)
        # 规范化：去除多余空格
        for m in matches:
            normalized = re.sub(r'\s+', ' ', m).strip()
            standards.add(normalized)

    if standards:
        logger.info("Extracted %d standards from documents: %s",
                     len(standards), sorted(standards))
    return sorted(standards)


def _inject_standards_to_prompt(system_prompt: str, content: str, discipline: str = "") -> str:
    """
    V5.3: 标准注入增强 — 文档标准提取 + 关键词匹配 Top-5 标准。
    V6.0: 支持 discipline 参数，按专业过滤匹配结果。

    1. 从文档内容提取标准编号（如 GB 55032-2022）
    2. 从文档内容提取工程关键词 → 匹配 standards_seed.json Top-5（含专业过滤）
    3. 将两者注入 system prompt
    """
    standards_in_docs = _extract_standards_from_content(content)

    # V6.0: 关键词匹配标准 — 传递 discipline 进行专业过滤
    try:
        kw = extract_keywords(content)
        disc = discipline if discipline else None
        matched = match_standards(kw, discipline=disc, top_k=5)
    except Exception:
        logger.warning("_inject_standards_to_prompt: 关键词匹配失败", exc_info=True)
        matched = []

    if not standards_in_docs and not matched:
        return system_prompt

    parts = [system_prompt]

    if matched:
        parts.append(inject_matched_standards_to_prompt(matched, ""))

    if standards_in_docs:
        standards_text = (
            "\n\n### Standards Found in Uploaded Documents (MUST USE THESE IF RELEVANT):\n"
            + "\n".join(f"- {s}" for s in standards_in_docs)
        )
        parts.append(standards_text)

    parts.append(
        "\n\n⚠️ If a standard listed above conflicts with your training data, "
        "the version listed above takes priority."
    )

    return "\n".join(parts)


# ==================== ModelProvider-based analysis ====================

def _compute_cache_key(system_prompt: str, user_prompt: str, model_name: str) -> str:
    """V4.9.3: 对完整 prompt 做 hash — 修复前2000字符截断导致的误命中过期缓存"""
    raw = system_prompt + "|" + user_prompt + "|" + model_name
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _parallel_api_calls(
    provider,
    sys_prompt_func: Callable,
    usr_prompt_func: Callable,
    chunks: List,
    max_workers: int = 5,
    max_tokens: int = 8192,
    progress_callback: Callable = None,
) -> List[Dict]:
    """
    V4.6: 并行调用 AI API 的通用函数。

    Args:
        provider: ModelProvider instance
        sys_prompt_func: callable() -> str for system prompt (no args)
        usr_prompt_func: callable(chunk) -> str for user prompt (takes one chunk)
        chunks: list of chunk data (one per API call)
        max_workers: max concurrent API calls (default 5, safe for DeepSeek V4-Flash)
        max_tokens: max_tokens per call
        progress_callback: optional callable(str)

    Returns:
        List of result dicts, same length as chunks. Failed calls → {"error": str}.
    """
    n = len(chunks)
    results = [None] * n
    completed = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_idx = {}
        for idx, chunk in enumerate(chunks):
            # sys_prompt_func(chunk) 支持按 chunk 动态生成 system prompt
            system_prompt = sys_prompt_func(chunk)
            user_prompt = usr_prompt_func(chunk)
            future = executor.submit(
                provider.call,
                system_prompt,
                user_prompt,
                max_tokens,
            )
            future_to_idx[future] = idx

        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                logger.error("API call failed (chunk %d/%d): %s", idx + 1, n, e)
                results[idx] = {"error": str(e)}

            completed += 1
            if progress_callback:
                progress_callback(f"API 调用进度: {completed}/{n}")

    return results


def analyze_with_provider(
    provider,
    content: str,
    progress_callback=None,
    db_manager=None,
    discipline: str = "",
) -> Dict[str, Any]:
    """
    使用 ModelProvider 进行多轮分步分析。
    V4.6: 支持 AI 结果缓存（需传入 db_manager），减少重复 API 调用。
    V6.0: 支持 discipline 参数，传递给 prompt 和标准匹配以提升专业准确性。

    Args:
        provider: ModelProvider instance
        content: combined document text
        progress_callback: callable(str) for progress updates
        db_manager: optional DatabaseManager for caching (V4.6)
        discipline: 专业名称（如"道路工程"/"给排水"等），用于 Few-Shot 选择
    """
    chunks = _split_content_into_chunks_smart(content, CONTENT_MAX_CHARS)
    logger.info("Provider analysis: %d chunks, provider=%s", len(chunks), provider.model_name)

    # Check cache for full analysis (only when db_manager is available)
    if db_manager is not None:
        # V5.3: 缓存 key 使用全部 chunks 的 hash（不含 TTL）
        combined_user_prompt = "|||".join(
            _build_user_prompt(c) for c in chunks
        )
        cache_key = _compute_cache_key(
            _build_system_prompt(), combined_user_prompt,
            getattr(provider, 'model_name', 'unknown')
        )
        cached = db_manager.get_ai_cache(cache_key)
        if cached:
            logger.info("AI cache hit — returning cached result (%d items)",
                         len(cached.get("testing_plan", [])))
            return cached

    # Step 1: Structure detection — parallel per chunk
    total_steps = 1 + (len(chunks) if chunks else 0)  # will be refined after grouping
    if progress_callback:
        progress_callback(f"第1步: 结构检测分析中（{len(chunks)} 分片）...")
    structure_results = _parallel_api_calls(
        provider=provider,
        sys_prompt_func=lambda c: _inject_standards_to_prompt(_build_structure_system_prompt(), c, discipline),
        usr_prompt_func=lambda c: _build_structure_user_prompt(c),
        chunks=chunks,
        max_workers=5,
        max_tokens=8192,
        progress_callback=progress_callback,
    )
    structure = _merge_structure_results(structure_results)

    if all("error" in r for r in structure_results):
        if progress_callback:
            progress_callback("结构检测失败，回退到完整分析模式...")
        if len(chunks) > 1:
            logger.warning("结构检测全部失败 — 仅用 chunk 0/共%d个，可能丢失数据", len(chunks))
        result = provider.call(
            _inject_standards_to_prompt(_build_system_prompt(), chunks[0], discipline),
            _build_user_prompt(chunks[0]),
            max_tokens=32768
        )
        # V4.5.3: 从 testing_plan 提取 sections 字段（fallback 路径缺少）
        if "error" not in result and "sections" not in result:
            result["sections"] = _extract_sections_from_plan(result.get("testing_plan", []))
        if "error" not in result and chunks:
            result = _fix_station_precision(chunks[0], result)
        if db_manager is not None:
            try:
                db_manager.save_ai_cache(cache_key, result, getattr(provider, 'model_name', 'unknown'))
            except Exception as e:
                logger.warning("Failed to save AI cache (fallback): %s", e)
        return result

    sections = structure.get("sections", [])
    project_info = structure.get("project_info", {})

    if not sections:
        result = provider.call(
            _inject_standards_to_prompt(_build_system_prompt(), chunks[0], discipline),
            _build_user_prompt(chunks[0]),
            max_tokens=32768
        )
        if "error" not in result:
            result["project_info"] = result.get("project_info", project_info)
            # V4.5.3: 从 testing_plan 提取 sections 字段（fallback 路径缺少）
            if "sections" not in result:
                result["sections"] = _extract_sections_from_plan(result.get("testing_plan", []))
            if chunks:
                result = _fix_station_precision(chunks[0], result)
        if db_manager is not None:
            try:
                db_manager.save_ai_cache(cache_key, result, getattr(provider, 'model_name', 'unknown'))
            except Exception as e:
                logger.warning("Failed to save AI cache (fallback): %s", e)
        return result

    # Step 2: Group sections (V4.7: 2 per group due to heavier construction_layers output)
    n = len(sections)
    if n <= 2:
        groups = [sections]
    elif n <= 4:
        mid = (n + 1) // 2
        groups = [sections[:mid], sections[mid:]]
    else:
        groups = [sections[i:i+2] for i in range(0, n, 2)]

    total_steps = 1 + len(groups)
    primary_content = chunks[0] if chunks else content

    # Step 2: Parallel material analysis
    if progress_callback:
        progress_callback(f"第2步: 材料分析中（{len(groups)} 组）...")
    material_results = _parallel_api_calls(
        provider=provider,
        sys_prompt_func=lambda g: _inject_standards_to_prompt(
            _build_material_system_prompt(discipline), primary_content, discipline
        ),
        usr_prompt_func=lambda g: _build_material_user_prompt(primary_content, g, project_info),
        chunks=groups,
        max_workers=3,  # V5.3: 降到3避免API限流
        max_tokens=32768,
        progress_callback=progress_callback,
    )

    all_plan = []
    all_layers = []  # V4.7: collect construction_layers from all groups
    for result in material_results:
        if "error" in result:
            continue
        items = result.get("testing_plan", [])
        all_plan.extend(items)
        # V4.7: collect construction_layers (graceful fallback if missing)
        layers = result.get("construction_layers", [])
        if layers:
            all_layers.extend(layers)

    all_plan = _deduplicate_testing_plan(all_plan)
    for i, item in enumerate(all_plan):
        item["sequence"] = i + 1
        # V4.9.2: No longer default to "双侧" — empty is better than fabricated
        if "road_orientation" not in item:
            item["road_orientation"] = ""

    final_result = {
        "project_info": project_info,
        "testing_plan": all_plan,
        "contract_info": structure.get("contract_info", {}),
        "key_notes": structure.get("key_notes", []),
        "sections": sections,
        "construction_layers": all_layers,  # V4.7: pass to DB storage
    }

    # V4.8: 修正 AI 可能舍入的桩号精度（从原始文本提取精确值）
    primary_text = chunks[0] if chunks else content
    final_result = _fix_station_precision(primary_text, final_result)

    # Save cache after successful analysis
    if db_manager is not None:
        cache_key = _compute_cache_key(
            _build_system_prompt(), _build_user_prompt(content),
            getattr(provider, 'model_name', 'unknown')
        )
        try:
            db_manager.save_ai_cache(
                cache_key, final_result,
                getattr(provider, 'model_name', 'unknown')
            )
        except Exception as e:
            logger.warning("Failed to save AI cache: %s", e)

    return final_result


# ==================== 保留旧版签名兼容 ====================

# _build_system_prompt and _build_user_prompt are now fallback-only (used when structure detection fails)
# The new multi-pass flow uses _build_structure_* and _build_material_* prompts instead.
