"""
项目管理模块
管理多个项目的数据持久化、文件导入、分析结果存储
"""

import json
import uuid
import re
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
from dataclasses import dataclass, field, asdict


@dataclass
class Project:
    """项目数据模型"""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M"))
    updated_at: str = ""
    cad_files: List[str] = field(default_factory=list)  # 文件路径列表
    pdf_files: List[str] = field(default_factory=list)
    extracted_text: str = ""       # 所有文件提取的文本汇总
    dwg_summary: List[Dict] = field(default_factory=list)  # 各专业图纸汇总
    analysis_result: Optional[Dict] = None  # AI 分析结果
    last_export: str = ""
    notes: str = ""

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict):
        p = cls()
        p.id = data.get("id", p.id)
        p.name = data.get("name", p.name)
        p.created_at = data.get("created_at", p.created_at)
        p.updated_at = data.get("updated_at", "")
        p.cad_files = data.get("cad_files", [])
        p.pdf_files = data.get("pdf_files", [])
        p.extracted_text = data.get("extracted_text", "")
        p.dwg_summary = data.get("dwg_summary", [])
        p.analysis_result = data.get("analysis_result")
        p.last_export = data.get("last_export", "")
        p.notes = data.get("notes", p.notes)
        return p

    @property
    def total_files(self) -> int:
        return len(self.cad_files) + len(self.pdf_files)

    @property
    def cad_count(self) -> int:
        return len(self.cad_files)

    @property
    def pdf_count(self) -> int:
        return len(self.pdf_files)

    @property
    def has_analysis(self) -> bool:
        return self.analysis_result is not None


class ProjectManager:
    """项目管理器 (V4: SQLite-backed)"""

    def __init__(self, data_dir: Optional[str] = None, db_manager=None):
        # V4: Use SQLite
        if db_manager is None:
            from ..database.db_manager import DatabaseManager
            db_manager = DatabaseManager()
        self._db = db_manager

        # V3 compat: keep old path for migration
        self.data_dir = Path(data_dir or str(Path.home() / ".material_testing_tool" / "projects"))

    def save(self, project_id: str):
        """Mark project as updated (SQLite handles this automatically)."""
        pass  # All writes go through DB immediately

    def create_project(self, name: str = "") -> Project:
        d = self._db.create_project(name or f"新项目_{datetime.now().strftime('%m%d%H%M')}")
        return Project(
            id=d["id"], name=d["name"],
            created_at=d["created_at"], updated_at=d["updated_at"],
            cad_files=d.get("cad_files", []), pdf_files=d.get("pdf_files", []),
            analysis_result=d.get("analysis_result"),
            dwg_summary=d.get("dwg_summary", []),
            extracted_text=d.get("extracted_text", ""),
        )

    def delete_project(self, project_id: str):
        self._db.delete_project(project_id)

    def get_project(self, project_id: str) -> Optional[Project]:
        d = self._db.get_project(project_id)
        if not d:
            return None
        return Project(
            id=d["id"], name=d["name"],
            created_at=d["created_at"], updated_at=d["updated_at"],
            cad_files=d.get("cad_files", []), pdf_files=d.get("pdf_files", []),
            analysis_result=d.get("analysis_result"),
            dwg_summary=d.get("dwg_summary", []),
            extracted_text=d.get("extracted_text", ""),
        )

    def list_projects(self) -> List[Project]:
        return [Project(
            id=d["id"], name=d["name"],
            created_at=d["created_at"], updated_at=d["updated_at"],
            cad_files=d.get("cad_files", []), pdf_files=d.get("pdf_files", []),
            analysis_result=d.get("analysis_result"),
            dwg_summary=d.get("dwg_summary", []),
            extracted_text=d.get("extracted_text", ""),
        ) for d in self._db.list_projects()]

    def add_files(self, project_id: str, file_paths: List[str], file_type: str = ""):
        new_files = []
        for fp in file_paths:
            # V6.0: 自动从扩展名检测文件类型
            if not file_type:
                ext = Path(fp).suffix.lower()
                if ext in (".dwg", ".dxf"):
                    ft = "cad"
                elif ext == ".pdf":
                    ft = "pdf"
                elif ext in (".docx", ".doc"):
                    ft = "word"
                elif ext in (".xlsx", ".xls"):
                    ft = "excel"
                else:
                    ft = "cad"  # fallback
            else:
                ft = file_type
            fid = self._db.add_file(project_id, str(Path(fp).resolve()), ft)
            if fid:
                new_files.append(fp)
        return new_files

    def set_extracted_text(self, project_id: str, text: str):
        # Text is stored via entity tables per-file; this is kept for backward compat
        # but does nothing in SQLite mode (text entities are stored per-file on parse)
        pass

    def set_analysis_result(self, project_id: str, result: Dict):
        self._db.store_analysis_result(project_id, result, model_name="deepseek-v4-flash")
        # Also store sections
        sections = result.get("sections", [])
        if sections:
            self._db.store_road_sections(project_id, sections)

    def set_dwg_summary(self, project_id: str, summary: List[Dict]):
        # Summary is computed from files.discipline; no explicit storage needed
        pass

    def get_road_sections(self, project_id: str) -> List[Dict]:
        return self._db.get_road_sections(project_id)

    def update_project_name(self, project_id: str, name: str):
        self._db.update_project_name(project_id, name)

    @property
    def db(self):
        return self._db

    def auto_detect_name(self, text: str) -> str:
        """从文件内容自动检测项目名称"""
        patterns = [
            r"([^\s]{2,}[大道路线路段]{1,3}[^\s]{0,10}(项目|工程))",
            r"项目名称[：:]\s*(.+?)(?:\n|$)",
            r"工程名称[：:]\s*(.+?)(?:\n|$)",
            r"(肇[庆慶][^\s]{2,}(?:大道|路|项目|工程))",
            r"([^\s]{3,}(?:配套|基础设施|产业集聚)[^\s]{3,}(?:项目|工程))",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                name = match.group(1) if match.lastindex else match.group(0)
                name = name.strip().rstrip("项目").rstrip("工程")
                if len(name) >= 4:
                    return name
        return ""

    def guess_project_for_file(self, file_path: str, file_type: str) -> Optional[str]:
        """根据文件名/路径猜测应该属于哪个已有项目"""
        name = Path(file_path).stem
        for p in self.list_projects():
            if p.name and p.name in name:
                return p.id
        return None
