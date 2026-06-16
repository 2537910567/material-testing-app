"""
V5.3: 标准年度替换引擎

功能:
1. parse_standard_file(file_path) — 解析导入的标准文件（JSON格式）
2. match_series(standards_list) — 按标准系列匹配（同系列不同年份）
3. generate_preview(replace_map) — 生成替换预览
4. validate_standards(new_items) — 校验标准数据完整性
"""

import json
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional

from ..logger import get_logger

logger = get_logger(__name__)


def _extract_series(code: str) -> str:
    """从标准编号提取系列名（用于同年份替换匹配）。

    例:
    - GB 55032-2022 → "GB 55032"
    - JTG 3450-2019 → "JTG 3450"
    - GB/T 50081-2019 → "GB/T 50081"
    - CJJ 1-2008 → "CJJ 1"
    """
    # 去除年份，保留系列前缀+编号
    code_clean = re.sub(r'\s+', ' ', code.strip())
    # 匹配: <前缀> <编号> - <年份>
    m = re.match(r'^([A-Z/]+\s*\d+(?:\.\d+)?)\s*-\s*\d{4}$', code_clean)
    if m:
        return m.group(1).strip()
    # Fallback: 直接去掉末尾 "-年份"
    return re.sub(r'\s*-\s*\d{4}$', '', code_clean)


def parse_standard_file(file_path: str) -> Dict:
    """解析导入的标准文件。

    支持格式:
    1. JSON 数组: [{"code": "...", "name": "...", ...}, ...]
    2. JSON 对象: {"standards": [...]}

    Returns:
        {"standards": [...], "errors": [...]}
    """
    path = Path(file_path)
    if not path.exists():
        return {"standards": [], "errors": [f"文件不存在: {file_path}"]}

    try:
        with open(file_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as e:
        return {"standards": [], "errors": [f"JSON 解析失败: {e}"]}
    except Exception as e:
        return {"standards": [], "errors": [f"文件读取失败: {e}"]}

    if isinstance(data, dict):
        items = data.get("standards", data.get("items", []))
    elif isinstance(data, list):
        items = data
    else:
        return {"standards": [], "errors": ["不支持的格式：期望 JSON 数组或对象"]}

    if not items:
        return {"standards": [], "errors": ["文件中未找到标准数据"]}

    errors = []
    valid = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"第{i+1}项: 不是对象格式")
            continue
        code = item.get("code", "")
        name = item.get("name", "")
        if not code or not name:
            errors.append(f"第{i+1}项: 缺少 code 或 name 字段")
            continue
        valid.append(item)

    return {"standards": valid, "errors": errors}


def match_series(
    new_standards: List[Dict],
    existing_standards: List[Dict],
) -> Tuple[List[Dict], List[Dict]]:
    """将新标准与现有标准按系列匹配。

    Returns:
        (replacements, new_only)
        - replacements: [{"old": {...}, "new": {...}, "series": "..."}]
        - new_only: [{"new": {...}, "series": "..."}] — 新建（无旧版本匹配）
    """
    # 建立现有标准的 series → list 索引
    existing_by_series: Dict[str, List[Dict]] = {}
    for s in existing_standards:
        series = _extract_series(s.get("code", ""))
        if series:
            existing_by_series.setdefault(series, []).append(s)

    replacements = []
    new_only = []

    for new_s in new_standards:
        new_code = new_s.get("code", "")
        series = _extract_series(new_code)
        if series and series in existing_by_series:
            # 同系列存在 → 替换
            for old_s in existing_by_series[series]:
                replacements.append({
                    "old": old_s,
                    "new": new_s,
                    "series": series,
                    "action": "replace",
                })
        else:
            # 新系列 → 添加
            new_only.append({
                "new": new_s,
                "series": series,
                "action": "add",
            })

    return replacements, new_only


def generate_preview(
    replacements: List[Dict],
    new_only: List[Dict],
) -> str:
    """生成替换预览的文本描述"""
    lines = ["## 标准年度替换预览\n"]

    if replacements:
        lines.append(f"### 替换 ({len(replacements)}项)")
        for r in replacements:
            old_code = r["old"].get("code", "?")
            old_name = r["old"].get("name", "?")
            new_code = r["new"].get("code", "?")
            new_name = r["new"].get("name", "?")
            lines.append(f"- {old_code} → {new_code}")
            lines.append(f"  {old_name} → {new_name}")

    if new_only:
        lines.append(f"\n### 新增 ({len(new_only)}项)")
        for n in new_only:
            code = n["new"].get("code", "?")
            name = n["new"].get("name", "?")
            lines.append(f"- {code} {name}")

    if not replacements and not new_only:
        lines.append("无变更。")

    return "\n".join(lines)


def validate_standards(items: List[Dict]) -> List[str]:
    """校验标准数据完整性，返回错误列表"""
    errors = []
    required_fields = ["code", "name", "type", "discipline"]
    for i, item in enumerate(items):
        for field in required_fields:
            if not item.get(field):
                errors.append(f"第{i+1}项 ({item.get('code','?')}): 缺少 '{field}'")
    return errors
