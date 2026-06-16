"""
V5.3: 领域知识关键词匹配引擎

从工程文档内容提取关键词（专业类型、材料名、结构类型、检测项），
在 standards_seed.json 中按关键词+专业匹配 Top-5 相关标准，
将匹配结果注入 AI prompt 以提高分析准确性。

集成点: 在 ai_agent.py 的 _inject_standards_to_prompt() 中调用。
"""

import json
import re
from pathlib import Path
from typing import List, Dict, Set, Optional

from ..logger import get_logger

logger = get_logger(__name__)

# ── 工程领域关键词库 ──────────────────────────────────────────────────

# 专业类型关键词（按 SⅠ-SⅦ 分类）
DISCIPLINE_KEYWORDS: Dict[str, List[str]] = {
    "道路工程": ["道路", "路基", "路面", "行车道", "人行道", "路缘石", "边坡",
                "填方", "挖方", "基层", "底基层", "面层", "沥青", "水泥混凝土路面",
                "级配碎石", "水稳", "水泥稳定", "二灰", "路床", "路堤"],
    "桥梁工程": ["桥梁", "桥涵", "桥台", "桥墩", "墩台", "梁体", "箱梁", "T梁",
                "空心板", "盖梁", "桩基", "承台", "支座", "伸缩缝", "桥面",
                "预应力", "张拉", "孔道", "压浆"],
    "地基基础": ["地基", "基础", "桩基", "承载力", "复合地基", "换填", "强夯",
                 "CFG桩", "水泥搅拌桩", "管桩", "灌注桩", "基坑", "锚杆"],
    "给排水": ["给水", "排水", "雨水", "污水", "管道", "检查井", "闭水试验",
               "沟槽", "回填", "HDPE", "球墨铸铁管", "混凝土管"],
    "附属设施": ["交通设施", "标志", "标线", "护栏", "波形梁", "标牌",
                 "无障碍", "盲道", "缘石坡道", "信号灯", "钢结构", "焊接", "镀锌"],
    # V6.0: 新增专业关键词
    "交通工程": ["交通标志", "标线", "信号灯", "护栏", "监控", "诱导", "防眩",
                "反光", "热熔", "标牌", "电子警察", "可变情报板"],
    "照明": ["路灯", "照度", "亮度", "LED", "灯具", "灯杆", "电缆", "配电箱",
             "接地", "防雷", "功率密度", "显色性"],
    "电气": ["电缆", "配电", "供配电", "接地", "防雷", "变压器", "开关柜",
             "绝缘", "耐压试验", "电缆头", "等电位", "接地电阻"],
    "通信": ["光缆", "通信管道", "综合布线", "人孔", "手孔", "配线架",
             "光纤", "衰减", "OTDR", "熔接", "管孔", "PVC-U管"],
    "原材料": ["水泥", "钢筋", "混凝土", "沥青", "砂", "碎石", "卵石", "粉煤灰",
              "外加剂", "钢绞线", "锚具", "波纹管", "钢板", "型钢"],
}

# 材料关键词
MATERIAL_KEYWORDS = [
    "水泥", "钢筋", "混凝土", "沥青", "砂", "碎石", "卵石", "粉煤灰", "矿粉",
    "外加剂", "减水剂", "膨胀剂", "速凝剂", "钢绞线", "锚具", "波纹管",
    "钢板", "型钢", "钢管", "球墨铸铁", "HDPE", "PVC", "PE", "砌块", "砖",
    "石灰", "水泥稳定碎石", "级配碎石", "沥青混合料", "SMA", "AC-", "ATB-",
    "土工格栅", "土工布", "防水卷材", "止水带",
]

# 结构类型关键词
STRUCTURE_KEYWORDS = [
    "路基", "路面", "桥梁", "涵洞", "隧道", "挡土墙", "边坡", "排水沟",
    "检查井", "箱涵", "管涵", "盖板涵", "拱涵", "U型槽", "锚杆框架梁",
    "抗滑桩", "路面结构", "底基层", "基层", "面层", "封层", "透层", "粘层",
]

# 检测项关键词
TEST_ITEM_KEYWORDS = [
    "压实度", "弯沉", "平整度", "抗压强度", "抗折强度", "劈裂强度",
    "承载力", "密实度", "含水率", "液限", "塑限", "CBR", "回弹模量",
    "针入度", "软化点", "延度", "马歇尔", "动稳定度", "残留稳定度",
    "冻融", "渗透", "钢筋保护层", "碳化深度", "氯离子", "锈蚀",
    "预应力", "张拉", "压浆", "静载试验", "动载试验", "超声波",
    "低应变", "高应变", "钻芯", "回弹", "取芯",
]


def extract_keywords(content: str) -> Dict[str, List[str]]:
    """
    从工程文档内容中提取结构化关键词。

    Returns:
        {
            "disciplines": ["道路工程", "桥梁工程", ...],
            "materials": ["水泥", "钢筋", ...],
            "structures": ["路基", "路面", ...],
            "test_items": ["压实度", "弯沉", ...],
        }
    """
    if not content or not isinstance(content, str):
        return {"disciplines": [], "materials": [], "structures": [], "test_items": []}

    result = {
        "disciplines": [],
        "materials": [],
        "structures": [],
        "test_items": [],
    }

    # 专业匹配
    for discipline, keywords in DISCIPLINE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in content)
        if score >= 1:
            result["disciplines"].append(discipline)

    # 材料匹配
    result["materials"] = [kw for kw in MATERIAL_KEYWORDS if kw in content]

    # 结构匹配
    result["structures"] = [kw for kw in STRUCTURE_KEYWORDS if kw in content]

    # 检测项匹配
    result["test_items"] = [kw for kw in TEST_ITEM_KEYWORDS if kw in content]

    return result


def _load_standards_db() -> List[Dict]:
    """加载预置标准知识库"""
    db_path = Path(__file__).parent.parent / "database" / "standards_seed.json"
    try:
        with open(db_path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as e:
        logger.warning("standards_matcher: 无法加载标准库 — %s", e)
        return []


def match_standards(
    keywords: Dict[str, List[str]],
    discipline: Optional[str] = None,
    top_k: int = 5,
) -> List[Dict]:
    """
    在标准知识库中按关键词+专业匹配 Top-K 相关标准。

    匹配策略:
    1. 专业优先 (discipline exact match → +3)
    2. 关键词重叠数 (intersection count)
    3. 按总分降序排列，返回 Top-K

    Args:
        keywords: extract_keywords() 的输出
        discipline: 可选的专业过滤（如 "SⅠ" → "道路工程"）
        top_k: 返回前 K 个（默认 5）

    Returns:
        Matched standards list (with extra "score" field)
    """
    db = _load_standards_db()
    if not db:
        return []

    # 将 discipline 映射为中文专业名
    disc_map = {
        "SⅠ": "道路工程", "S1": "道路工程", "道路": "道路工程", "road": "道路工程",
        "SⅡ": "桥梁工程", "S2": "桥梁工程", "桥梁": "桥梁工程", "bridge": "桥梁工程",
        "SⅢ": "给排水", "S3": "给排水", "s3": "给排水",
        "SⅣ": "地基基础", "S4": "地基基础",
        "SⅤ": "附属设施", "S5": "附属设施",
        "SⅥ": "原材料", "S6": "原材料",
        "SⅦ": "检测方法", "S7": "检测方法",
    }
    target_disc = disc_map.get(discipline, discipline)

    # 收集所有提取的词（flat set）
    extracted_words: Set[str] = set()
    for v in keywords.values():
        if isinstance(v, list):
            extracted_words.update(v)
    if target_disc:
        extracted_words.add(target_disc)

    scored = []
    for std in db:
        score = 0
        std_kw = std.get("keywords", [])
        std_disc = std.get("discipline", "")

        # 专业匹配加分
        if target_disc and target_disc == std_disc:
            score += 3
        elif target_disc and target_disc in std_disc:
            score += 1

        # 关键词重叠数
        overlap = len(extracted_words & set(std_kw))
        score += overlap

        if score > 0:
            scored.append({**std, "score": score})

    scored.sort(key=lambda x: x["score"], reverse=True)
    result = scored[:top_k]

    if result:
        logger.info(
            "standards_matcher: matched %d standards (disc=%s, keywords=%d)",
            len(result), discipline or "auto",
            sum(len(v) for v in keywords.values()),
        )

    return result


def inject_matched_standards_to_prompt(
    matched_standards: List[Dict],
    system_prompt: str,
) -> str:
    """
    将匹配到的标准信息注入 system prompt。

    格式: 在 prompt 末尾追加 "### Matched Standards (Top-N by keyword relevance):"
    """
    if not matched_standards:
        return system_prompt

    lines = [
        "\n\n### Matched Standards (Top-{} by keyword relevance):".format(len(matched_standards)),
    ]
    for s in matched_standards:
        lines.append(
            f"- {s['code']} {s['name']} "
            f"({s.get('type', '')}, {s.get('discipline', '')}, 匹配分={s.get('score', 0)})"
        )
    lines.append(
        "\n⚠️ Prioritize these matched standards when generating the testing plan. "
        "If a standard above conflicts with your training data, the matched standard takes priority."
    )

    return system_prompt + "\n".join(lines)
