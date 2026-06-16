"""
DatabaseManager — SQLite CRUD + JSON migration.

Replaces JSON file persistence with entity-granular SQLite storage.
"""

import json
import uuid
import time
import sqlite3
import shutil
import threading
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

from .schema import migrate, SCHEMA_VERSION
from ..logger import get_logger

logger = get_logger(__name__)

DEFAULT_DB_PATH = Path.home() / ".material_testing_tool" / "material_testing.db"


class DatabaseManager:
    """SQLite-backed project and file data manager."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = str(DEFAULT_DB_PATH)
        self.db_path = db_path
        self._lock = threading.Lock()  # 写操作串行化

        # Ensure directory
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        # Open connection, enable WAL for concurrent reads
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

        # V4.9.4: 专用只读连接 — 供 UI 线程查询，完全避开写锁竞争
        self._read_conn = sqlite3.connect(db_path, check_same_thread=False)
        self._read_conn.execute("PRAGMA query_only=ON")

        # Run migrations
        migrate(self._conn, SCHEMA_VERSION)

        # V5.3: 启动时检查数据库完整性（损坏则提前发现）
        try:
            integrity = self._conn.execute("PRAGMA integrity_check").fetchone()
            if integrity and integrity[0] != "ok":
                logger.error("Database integrity check FAILED: %s", integrity[0])
        except Exception:
            logger.warning("Database integrity check skipped (DB may not be fully initialized)")

        # Auto-migrate old JSON projects if database is empty
        self._maybe_migrate_json()

    # ==================== Project CRUD ====================

    def create_project(self, name: str = "") -> Dict:
        pid = str(uuid.uuid4())[:8]
        if not name:
            name = f"新项目_{datetime.now().strftime('%m%d%H%M')}"
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        with self._lock:
            self._conn.execute(
                "INSERT INTO projects (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (pid, name, now, now)
            )
            self._conn.commit()
        logger.info("Project created: %s (%s)", name, pid)
        return self.get_project(pid)

    def get_project(self, project_id: str) -> Optional[Dict]:
        row = self._conn.execute(
            "SELECT id, name, created_at, updated_at, notes, last_export FROM projects WHERE id=?",
            (project_id,)
        ).fetchone()
        if not row:
            return None
        p = dict(zip(["id", "name", "created_at", "updated_at", "notes", "last_export"], row))
        # Count files
        p["cad_files"] = self._get_file_paths(project_id, "cad")
        p["pdf_files"] = self._get_file_paths(project_id, "pdf")
        p["cad_count"] = len(p["cad_files"])
        p["pdf_count"] = len(p["pdf_files"])
        p["total_files"] = p["cad_count"] + p["pdf_count"]
        p["has_analysis"] = self.has_analysis(project_id)
        # Get dwg_summary
        p["dwg_summary"] = self.get_discipline_summary(project_id)
        # Get extracted_text (aggregated from entity tables)
        p["extracted_text"] = self.get_extracted_text(project_id)
        # Get latest analysis result
        p["analysis_result"] = self.get_latest_analysis(project_id)
        return p

    def delete_project(self, project_id: str):
        with self._lock:
            self._conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
            self._conn.commit()
        logger.info("Project deleted: %s", project_id)

    def list_projects(self) -> List[Dict]:
        # V5.3: 批量 JOIN 替代 N+1 查询（消除每项目的 6+ 独立 SQL）
        rows = self._conn.execute(
            """SELECT p.id, p.name, p.created_at, p.updated_at, p.notes, p.last_export,
                      COUNT(f.id) as total_files,
                      SUM(CASE WHEN f.file_type='cad' THEN 1 ELSE 0 END) as cad_count,
                      SUM(CASE WHEN f.file_type='pdf' THEN 1 ELSE 0 END) as pdf_count
               FROM projects p
               LEFT JOIN files f ON f.project_id = p.id
               GROUP BY p.id
               ORDER BY p.updated_at DESC"""
        ).fetchall()
        projects = []
        for row in rows:
            pid = row[0]
            p = {"id": pid, "name": row[1], "created_at": row[2],
                 "updated_at": row[3], "notes": row[4], "last_export": row[5],
                 "total_files": row[6], "cad_count": row[7], "pdf_count": row[8],
                 "cad_files": [], "pdf_files": [],
                 "has_analysis": self.has_analysis(pid),
                 "dwg_summary": self.get_discipline_summary(pid),
                 "extracted_text": "", "analysis_result": None}
            projects.append(p)
        return projects

    def update_project_name(self, project_id: str, name: str):
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        with self._lock:
            self._conn.execute(
                "UPDATE projects SET name=?, updated_at=? WHERE id=?",
                (name, now, project_id)
            )
            self._conn.commit()

    # ==================== File CRUD ====================

    def add_file(self, project_id: str, file_path: str, file_type: str) -> Optional[int]:
        """Add file record, returns file_id or None if already exists."""
        path = Path(file_path).resolve()
        fname = path.name
        try:
            fsize = path.stat().st_size
            fmtime = path.stat().st_mtime
        except OSError:
            fsize = None
            fmtime = None

        try:
            with self._lock:
                cur = self._conn.execute(
                    """INSERT INTO files (project_id, file_path, file_name, file_type,
                       file_size, file_mtime) VALUES (?, ?, ?, ?, ?, ?)""",
                    (project_id, str(path), fname, file_type, fsize, fmtime)
                )
                self._conn.commit()
                fid = cur.lastrowid
                logger.debug("File added: %s (id=%d, type=%s)", fname, fid, file_type)
                return fid
        except sqlite3.IntegrityError:
            # File already exists for this project
            row = self._conn.execute(
                "SELECT id FROM files WHERE project_id=? AND file_path=?",
                (project_id, str(path))
            ).fetchone()
            return row[0] if row else None

    def get_files(self, project_id: str, file_type: Optional[str] = None) -> List[Dict]:
        cols = ["id", "file_path", "file_name", "file_type", "file_size", "file_mtime",
                "discipline", "description", "parse_status", "parse_error",
                "conversion_status", "thumbnail_path"]  # V4.9.3: +conversion_status
        # V4.9.4: 使用只读连接避免与转换线程写锁竞争
        if file_type:
            rows = self._read_conn.execute(
                f"""SELECT {', '.join(cols)}
                   FROM files WHERE project_id=? AND file_type=? ORDER BY id""",
                (project_id, file_type)
            ).fetchall()
        else:
            rows = self._read_conn.execute(
                f"""SELECT {', '.join(cols)}
                   FROM files WHERE project_id=? ORDER BY id""",
                (project_id,)
            ).fetchall()
        return [dict(zip(cols, r)) for r in rows]

    def set_conversion_status(self, file_id: int, status: str):
        """V4.9.3: 更新文件转换状态 ('' / 'done' / 'error')"""
        with self._lock:
            self._conn.execute(
                "UPDATE files SET conversion_status=? WHERE id=?", (status, file_id)
            )
            self._conn.commit()

    def get_unparsed_files(self, project_id: str) -> List[Dict]:
        """Files that are pending or whose mtime has changed since last parse."""
        rows = self._conn.execute(
            """SELECT id, file_path, file_name, file_type, file_size, file_mtime,
               discipline, parse_status FROM files
               WHERE project_id=? AND (parse_status != 'done' OR parse_status IS NULL)""",
            (project_id,)
        ).fetchall()
        return [dict(zip(
            ["id", "file_path", "file_name", "file_type", "file_size", "file_mtime",
             "discipline", "parse_status"], r)) for r in rows]

    def update_file_parse_status(self, file_id: int, status: str,
                                  discipline: str = "", description: str = "",
                                  error: Optional[str] = None):
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        with self._lock:
            self._conn.execute(
                """UPDATE files SET parse_status=?, discipline=?, description=?,
                   parse_error=?, parsed_at=? WHERE id=?""",
                (status, discipline, description, error, now, file_id)
            )
            self._conn.commit()

    def update_file_thumbnail(self, file_id: int, thumbnail_path: str):
        with self._lock:
            self._conn.execute(
                "UPDATE files SET thumbnail_path=? WHERE id=?",
                (thumbnail_path, file_id)
            )
            self._conn.commit()

    def _get_file_paths(self, project_id: str, file_type: str) -> List[str]:
        rows = self._conn.execute(
            "SELECT file_path FROM files WHERE project_id=? AND file_type=? ORDER BY id",
            (project_id, file_type)
        ).fetchall()
        return [r[0] for r in rows]

    def delete_file(self, file_id: int):
        """删除文件及其所有关联数据（外键 ON DELETE CASCADE 自动处理子表）"""
        with self._lock:
            self._conn.execute("DELETE FROM files WHERE id=?", (file_id,))
            self._conn.commit()

    # ==================== Entity storage ====================

    def store_text_entities(self, file_id: int, entities: List[Dict]):
        """批量存储 text_entities，先删旧数据"""
        with self._lock:
            self._conn.execute("DELETE FROM text_entities WHERE file_id=?", (file_id,))
            self._conn.executemany(
                "INSERT INTO text_entities (file_id, text, layer, pos_x, pos_y) VALUES (?, ?, ?, ?, ?)",
                [(file_id, e.get("text", ""), e.get("layer", ""),
                  e.get("x", 0), e.get("y", 0)) for e in entities]
            )
            self._conn.commit()

    def store_block_attributes(self, file_id: int, attrs: List[Dict]):
        with self._lock:
            self._conn.execute("DELETE FROM block_attributes WHERE file_id=?", (file_id,))
            self._conn.executemany(
                "INSERT INTO block_attributes (file_id, tag, value, layer) VALUES (?, ?, ?, ?)",
                [(file_id, a.get("tag", ""), a.get("value", ""), a.get("layer", "")) for a in attrs]
            )
            self._conn.commit()

    def store_tables(self, file_id: int, tables: List[List[List[str]]], page_number: Optional[int] = None):
        with self._lock:
            # Delete old tables for this file
            old = self._conn.execute("SELECT id FROM extracted_tables WHERE file_id=?", (file_id,)).fetchall()
            for (tid,) in old:
                self._conn.execute("DELETE FROM table_cells WHERE table_id=?", (tid,))
            self._conn.execute("DELETE FROM extracted_tables WHERE file_id=?", (file_id,))

            for ti, table in enumerate(tables):
                if not table:
                    continue
                ncols = max(len(row) for row in table) if table else 0
                cur = self._conn.execute(
                    "INSERT INTO extracted_tables (file_id, table_index, page_number, row_count, col_count) VALUES (?, ?, ?, ?, ?)",
                    (file_id, ti, page_number, len(table), ncols)
                )
                tid = cur.lastrowid
                for ri, row in enumerate(table):
                    for ci, cell in enumerate(row):
                        self._conn.execute(
                            "INSERT INTO table_cells (table_id, row_idx, col_idx, cell_text) VALUES (?, ?, ?, ?)",
                            (tid, ri, ci, cell if cell else "")
                        )
            self._conn.commit()

    def get_extracted_text(self, project_id: str) -> str:
        """Aggregate all text entities for a project into a single string."""
        rows = self._conn.execute(
            """SELECT t.text FROM text_entities t
               JOIN files f ON t.file_id = f.id
               WHERE f.project_id=? ORDER BY t.id""",
            (project_id,)
        ).fetchall()
        if not rows:
            return ""
        return "\n".join(r[0] for r in rows)

    def get_extracted_testing_guide_text(self, project_id: str) -> str:
        """V4.6: 获取项目中送检指南文件的聚合文本（用于 AI Prompt 前置）"""
        rows = self._conn.execute(
            """SELECT t.text FROM text_entities t
               JOIN files f ON t.file_id = f.id
               WHERE f.project_id=? AND f.description='TESTING_GUIDE'
               ORDER BY t.id""",
            (project_id,)
        ).fetchall()
        if not rows:
            return ""
        return "\n".join(r[0] for r in rows)

    # ==================== Road sections ====================

    def store_road_sections(self, project_id: str, sections: List[Dict]):
        with self._lock:
            self._conn.execute("DELETE FROM road_sections WHERE project_id=?", (project_id,))
            for s in sections:
                self._conn.execute(
                    """INSERT INTO road_sections (project_id, section_name, road_orientation, description, sub_projects, identified_by)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (project_id,
                     s.get("section", s.get("name", "")),
                     s.get("road_orientation", "双侧"),
                     s.get("description", ""),
                     json.dumps(s.get("sub_projects", []), ensure_ascii=False),
                     s.get("identified_by", "text"))
                )
            self._conn.commit()

    def get_road_sections(self, project_id: str) -> List[Dict]:
        rows = self._conn.execute(
            """SELECT id, section_name, road_orientation, description, sub_projects, identified_by
               FROM road_sections WHERE project_id=? ORDER BY id""",
            (project_id,)
        ).fetchall()
        return [dict(zip(["id", "section_name", "road_orientation", "description", "sub_projects", "identified_by"], r))
                for r in rows]

    def store_page_chainage_mappings(self, project_id: str, mappings: List[Dict]):
        with self._lock:
            self._conn.execute("DELETE FROM page_chainage_mappings WHERE project_id=?", (project_id,))
            for m in mappings:
                self._conn.execute(
                    """INSERT INTO page_chainage_mappings
                       (project_id, file_id, page_number, chainage_start, chainage_end, road_orientation, confidence, identified_by)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (project_id, m.get("file_id", 0), m.get("page_number", 0),
                     m.get("chainage_start", ""), m.get("chainage_end", ""),
                     m.get("road_orientation", "双侧"), m.get("confidence", 0.0),
                     m.get("identified_by", "text"))
                )
            self._conn.commit()

    # ==================== Analysis results ====================

    def store_analysis_result(self, project_id: str, result: Dict, model_name: str = "",
                               sections_included: str = ""):
        with self._lock:
            # Store full JSON result
            cur = self._conn.execute(
                """INSERT INTO analysis_results (project_id, analysis_type, model_name, sections_included, result_json)
                   VALUES (?, 'full', ?, ?, ?)""",
                (project_id, model_name, sections_included, json.dumps(result, ensure_ascii=False))
            )
            aid = cur.lastrowid

            # Normalize testing plan items
            plan = result.get("testing_plan", [])
            if not isinstance(plan, list):
                plan = []  # V4.9.3: 防御非列表值
            for item in plan:
                self._conn.execute(
                    """INSERT INTO testing_plan_items
                       (analysis_id, sequence, section, road_orientation, sub_project, sub_sub_project,
                        work_item, material_name, spec, test_item, test_param, standard,
                        sampling_method, inspection_type, frequency, planned_batches, remarks, lane_count)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (aid,
                     item.get("sequence", 0), item.get("section", ""),
                     item.get("road_orientation", ""),
                     item.get("sub_project", ""), item.get("sub_sub_project", ""),
                     item.get("work_item", ""), item.get("material_name", ""),
                     item.get("spec", ""), item.get("test_item", ""),
                     item.get("test_param", ""), item.get("standard", ""),
                     item.get("sampling_method", ""), item.get("inspection_type", "见证取样"),
                     item.get("frequency", ""), item.get("planned_batches", ""),
                     item.get("remarks", ""), item.get("lane_count", ""))
                )
            # V4.7: Store construction_layers if present
            layers = result.get("construction_layers", [])
            if layers:
                self._store_construction_layers_internal(project_id, layers)

            self._conn.commit()
            return aid

    def get_latest_analysis(self, project_id: str) -> Optional[Dict]:
        row = self._conn.execute(
            "SELECT result_json FROM analysis_results WHERE project_id=? ORDER BY created_at DESC LIMIT 1",
            (project_id,)
        ).fetchone()
        if row:
            return json.loads(row[0])
        return None

    def has_analysis(self, project_id: str) -> bool:
        row = self._read_conn.execute(
            "SELECT COUNT(*) FROM analysis_results WHERE project_id=?", (project_id,)
        ).fetchone()
        return row[0] > 0 if row else False

    def get_testing_plan_items(self, project_id: str, section_ids: Optional[List[int]] = None) -> List[Dict]:
        cursor = None
        if section_ids:
            cursor = self._conn.execute(
                """SELECT tpi.* FROM testing_plan_items tpi
                   JOIN analysis_results ar ON tpi.analysis_id = ar.id
                   WHERE ar.project_id=? AND tpi.section IN (
                       SELECT section_name FROM road_sections WHERE id IN ({})
                   ) ORDER BY tpi.sequence""".format(','.join('?' * len(section_ids))),
                [project_id] + section_ids
            )
        else:
            cursor = self._conn.execute(
                """SELECT tpi.* FROM testing_plan_items tpi
                   JOIN analysis_results ar ON tpi.analysis_id = ar.id
                   WHERE ar.project_id=? ORDER BY tpi.sequence""",
                (project_id,)
            )
        rows = cursor.fetchall() if cursor else []
        cols = [d[0] for d in cursor.description] if rows else []
        return [dict(zip(cols, r)) for r in rows]

    def update_plan_item(self, item_id: int, key: str, value: str):
        """V4.8: 更新送检计划单个字段（仅 planned_batches 和 remarks）"""
        allowed = {"planned_batches", "remarks"}
        if key not in allowed:
            return
        with self._lock:
            self._conn.execute(
                f"UPDATE testing_plan_items SET {key}=? WHERE id=?",
                (value, item_id)
            )
            self._conn.commit()

    def batch_update_plan_items(self, items: list) -> int:
        """V5.3: 事务批量更新送检计划字段（编辑模式攒批保存）。

        Args:
            items: [{"id": int, "key": str, "value": str}, ...]

        Returns:
            成功更新的行数
        """
        # 合法列名白名单（USE_TYPES）
        VALID_KEYS = {
            "sequence", "section", "road_orientation", "lane_count",
            "sub_project", "sub_sub_project", "work_item", "material_name",
            "spec", "test_item", "test_param", "standard", "sampling_method",
            "inspection_type", "frequency", "planned_batches", "remarks",
        }
        updated = 0
        with self._lock:
            for item in items:
                kid = int(item.get("id", 0))
                key = str(item.get("key", ""))
                value = str(item.get("value", ""))
                if kid <= 0 or key not in VALID_KEYS:
                    continue
                self._conn.execute(
                    f"UPDATE testing_plan_items SET {key}=? WHERE id=?",
                    (value, kid)
                )
                updated += 1
            self._conn.commit()
        return updated

    # ==================== Construction layers (V4.7) ====================

    def _store_construction_layers_internal(self, project_id: str, layers: List[Dict]):
        """Internal: store construction layers WITHOUT acquiring lock (caller must hold lock)."""
        # Delete old layers for this project (CASCADE removes materials + tests)
        self._conn.execute(
            "DELETE FROM construction_layers WHERE project_id=?", (project_id,)
        )
        for layer in layers:
            cur = self._conn.execute(
                """INSERT INTO construction_layers
                   (project_id, section_name, road_orientation, step, layer_name, thickness, construction_process)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (project_id,
                 layer.get("section", ""),
                 layer.get("road_orientation", "双侧"),
                 layer.get("step", 1),
                 layer.get("layer_name", ""),
                 layer.get("thickness", ""),
                 layer.get("construction_process", ""))
            )
            layer_id = cur.lastrowid

            # Store layer materials
            for mat in layer.get("materials", []):
                if isinstance(mat, dict):
                    self._conn.execute(
                        "INSERT INTO layer_materials (layer_id, material_name, spec) VALUES (?, ?, ?)",
                        (layer_id, mat.get("name", mat.get("material_name", "")),
                         mat.get("spec", ""))
                    )
                elif isinstance(mat, str):
                    self._conn.execute(
                        "INSERT INTO layer_materials (layer_id, material_name, spec) VALUES (?, ?, ?)",
                        (layer_id, mat, "")
                    )

            # Store layer tests
            for test in layer.get("tests", []):
                self._conn.execute(
                    """INSERT INTO layer_tests
                       (layer_id, test_item, test_param, timing, frequency, standard)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (layer_id,
                     test.get("test_item", ""),
                     test.get("test_param", ""),
                     test.get("timing", ""),
                     test.get("frequency", ""),
                     test.get("standard", ""))
                )

            # V4.8: Store construction procedures (施工步骤)
            for proc in layer.get("procedures", []):
                import json
                params = proc.get("parameters", {})
                params_json = json.dumps(params, ensure_ascii=False) if isinstance(params, dict) else str(params)
                self._conn.execute(
                    """INSERT INTO layer_procedures
                       (layer_id, step_order, step_name, step_description, key_points,
                        applicable_standards, parameters)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (layer_id,
                     proc.get("step_order", 0),
                     proc.get("step_name", ""),
                     proc.get("step_description", ""),
                     proc.get("key_points", ""),
                     proc.get("applicable_standards", ""),
                     params_json)
                )

    def store_construction_layers(self, project_id: str, layers: List[Dict]):
        """Store construction layers for a project (with lock)."""
        with self._lock:
            self._store_construction_layers_internal(project_id, layers)
            self._conn.commit()

    def get_construction_layers(self, project_id: str, section_name: str = "") -> List[Dict]:
        """Get construction layers for a project, optionally filtered by section_name."""
        if section_name:
            layer_rows = self._conn.execute(
                """SELECT * FROM construction_layers
                   WHERE project_id=? AND section_name=?
                   ORDER BY step""",
                (project_id, section_name)
            ).fetchall()
        else:
            layer_rows = self._conn.execute(
                """SELECT * FROM construction_layers
                   WHERE project_id=?
                   ORDER BY section_name, step""",
                (project_id,)
            ).fetchall()

        result = []
        for lr in layer_rows:
            layer_dict = {
                "id": lr[0], "project_id": lr[1], "section_name": lr[2],
                "road_orientation": lr[3], "step": lr[4], "layer_name": lr[5],
                "thickness": lr[6], "construction_process": lr[7],
            }

            # Fetch materials
            mat_rows = self._conn.execute(
                "SELECT material_name, spec FROM layer_materials WHERE layer_id=?",
                (lr[0],)
            ).fetchall()
            layer_dict["materials"] = [
                {"name": m[0], "spec": m[1]} for m in mat_rows
            ]

            # Fetch tests
            test_rows = self._conn.execute(
                "SELECT test_item, test_param, timing, frequency, standard FROM layer_tests WHERE layer_id=?",
                (lr[0],)
            ).fetchall()
            layer_dict["tests"] = [
                {"test_item": t[0], "test_param": t[1], "timing": t[2],
                 "frequency": t[3], "standard": t[4]}
                for t in test_rows
            ]

            # V4.8: Fetch procedures
            proc_rows = self._conn.execute(
                """SELECT step_order, step_name, step_description, key_points,
                          applicable_standards, parameters
                   FROM layer_procedures WHERE layer_id=? ORDER BY step_order""",
                (lr[0],)
            ).fetchall()
            layer_dict["procedures"] = [
                {
                    "step_order": p[0], "step_name": p[1],
                    "step_description": p[2] or "", "key_points": p[3] or "",
                    "applicable_standards": p[4] or "", "parameters": p[5] or ""
                }
                for p in proc_rows
            ]

            result.append(layer_dict)
        return result

    # ==================== Analysis Checkpoints (V4.8) ====================

    def save_checkpoint(self, project_id: str, step: str, vision_processed_files: str = ""):
        """V4.8: 保存分析断点"""
        with self._lock:
            self._conn.execute(
                """INSERT OR REPLACE INTO analysis_checkpoints
                   (project_id, step, vision_processed_files, created_at)
                   VALUES (?, ?, ?, datetime('now'))""",
                (project_id, step, vision_processed_files)
            )
            self._conn.commit()

    def get_checkpoint(self, project_id: str) -> dict | None:
        """V4.8: 获取分析断点"""
        row = self._conn.execute(
            "SELECT step, vision_processed_files FROM analysis_checkpoints WHERE project_id=?",
            (project_id,)
        ).fetchone()
        if row:
            return {"step": row[0], "vision_processed_files": row[1]}
        return None

    def clear_checkpoint(self, project_id: str):
        """V4.8: 清除分析断点（分析正常完成后调用）"""
        with self._lock:
            self._conn.execute(
                "DELETE FROM analysis_checkpoints WHERE project_id=?", (project_id,)
            )
            self._conn.commit()

    # ==================== Discipline summary ====================

    def get_discipline_summary(self, project_id: str) -> List[Dict]:
        rows = self._conn.execute(
            """SELECT discipline, COUNT(*) as cnt, GROUP_CONCAT(file_name) as files
               FROM files WHERE project_id=? AND parse_status='done'
               GROUP BY discipline ORDER BY cnt DESC""",
            (project_id,)
        ).fetchall()
        return [
            {"discipline": r[0] or "未知", "count": r[1], "files": r[2].split(",") if r[2] else []}
            for r in rows
        ]

    # ==================== Settings ====================

    def get_setting(self, key: str, default: str = "") -> str:
        row = self._conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str):
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)
            )
            self._conn.commit()

    # ==================== AI Cache ====================

    def get_ai_cache(self, cache_key: str) -> dict | None:
        """获取缓存的 AI 分析结果。返回 None 如果未命中。"""
        row = self._conn.execute(
            "SELECT result_json FROM ai_cache WHERE cache_key=?",
            (cache_key,)
        ).fetchone()
        if row:
            import json
            logger.debug("AI cache hit: %s...", cache_key[:16])
            return json.loads(row[0])
        return None

    def save_ai_cache(self, cache_key: str, result: dict, model_name: str):
        """V5.2: 缓存 AI 分析结果（含性能元数据）。"""
        import json
        # 提取 _meta 字段避免存入结果 JSON
        meta = result.pop("_meta", {}) if isinstance(result, dict) else {}
        result_json = json.dumps(result, ensure_ascii=False)
        # 恢复 _meta（不影响调用方后续使用）
        if meta:
            result["_meta"] = meta
        latency_ms = meta.get("latency_ms", 0)
        token_count = meta.get("token_count", 0)
        retry_count = meta.get("retry_count", 0)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO ai_cache (cache_key, result_json, model_name, latency_ms, token_count, retry_count) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (cache_key, result_json, model_name, latency_ms, token_count, retry_count)
            )
            self._conn.commit()
        logger.debug("AI cache saved: %s... (model=%s, %dms, %d tokens, %d retries)",
                     cache_key[:16], model_name, latency_ms, token_count, retry_count)

    # ==================== File Profiles (V4.9.3) ====================

    def save_file_profile(self, file_id: int, file_md5: str, profile_dict: dict):
        """V4.9.3: 保存文件预分析结果"""
        import json
        profile_json = json.dumps(profile_dict, ensure_ascii=False)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO file_profiles (file_id, file_md5, profile_json) "
                "VALUES (?, ?, ?)",
                (file_id, file_md5, profile_json)
            )
            self._conn.commit()

    def get_file_profile(self, file_id: int) -> dict | None:
        """V4.9.3: 获取文件预分析结果"""
        row = self._conn.execute(
            "SELECT profile_json FROM file_profiles WHERE file_id=?", (file_id,)
        ).fetchone()
        if row:
            import json
            return json.loads(row[0])
        return None

    def get_file_profiles_batch(self, file_ids: list) -> dict:
        """V4.9.3: 批量获取文件预分析结果 → {file_id: profile_dict}"""
        if not file_ids:
            return {}
        placeholders = ",".join("?" * len(file_ids))
        rows = self._conn.execute(
            f"SELECT file_id, profile_json FROM file_profiles WHERE file_id IN ({placeholders})",
            file_ids
        ).fetchall()
        import json
        return {row[0]: json.loads(row[1]) for row in rows}

    # ==================== Migration from JSON ====================

    def _maybe_migrate_json(self):
        """If database has no projects and old JSON directory exists, auto-migrate."""
        row = self._conn.execute("SELECT COUNT(*) FROM projects").fetchone()
        if row and row[0] > 0:
            return

        json_dir = Path.home() / ".material_testing_tool" / "projects"
        if not json_dir.exists():
            return

        json_files = list(json_dir.glob("*.json"))
        if not json_files:
            return

        logger.info("Found %d JSON project files, starting migration...", len(json_files))
        migrated = self._migrate_json_to_sqlite(json_dir)
        if migrated > 0:
            # Rename old directory as backup (don't delete)
            backup_dir = json_dir.parent / "projects_backup_v3"
            try:
                shutil.move(str(json_dir), str(backup_dir))
                logger.info("Migrated %d projects, old data backed up to %s", migrated, backup_dir)
            except Exception as e:
                logger.warning("Migration backup failed: %s (old data not moved)", e)

    def _migrate_json_to_sqlite(self, json_dir: Path) -> int:
        """Import old JSON project files into SQLite. Returns count of migrated projects."""
        count = 0
        for f in json_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                pid = data.get("id", str(uuid.uuid4())[:8])
                name = data.get("name", f.name)
                created = data.get("created_at", datetime.now().strftime("%Y-%m-%d %H:%M"))
                updated = data.get("updated_at", created)

                # Insert project
                self._conn.execute(
                    "INSERT INTO projects (id, name, created_at, updated_at, notes) VALUES (?, ?, ?, ?, ?)",
                    (pid, name, created, updated, data.get("notes", ""))
                )

                # Insert CAD files
                for fp in data.get("cad_files", []):
                    if Path(fp).exists():
                        self._add_migration_file(pid, fp, "cad")

                # Insert PDF files
                for fp in data.get("pdf_files", []):
                    if Path(fp).exists():
                        self._add_migration_file(pid, fp, "pdf")

                # Store parsed text if present
                text = data.get("extracted_text", "")
                if text:
                    # Create a synthetic file entry for the accumulated text
                    cur = self._conn.execute(
                        "INSERT INTO files (project_id, file_path, file_name, file_type, parse_status) VALUES (?, ?, ?, ?, ?)",
                        (pid, f"migrated://{pid}/text", "migrated_text.txt", "cad", "done")
                    )
                    mid = cur.lastrowid
                    # Split text into lines as synthetic text_entities
                    lines = text.split("\n")
                    self._conn.executemany(
                        "INSERT INTO text_entities (file_id, text) VALUES (?, ?)",
                        [(mid, line) for line in lines[:10000]]  # cap at 10K lines
                    )
                    self._conn.commit()

                # Store analysis result if present
                result = data.get("analysis_result")
                if result:
                    self._conn.execute(
                        "INSERT INTO analysis_results (project_id, analysis_type, model_name, result_json) VALUES (?, 'full', 'migrated', ?)",
                        (pid, json.dumps(result, ensure_ascii=False))
                    )
                    # Extract testing plan items
                    plan = result.get("testing_plan", [])
                    for item in plan:
                        self._conn.execute(
                            """INSERT INTO testing_plan_items
                               (analysis_id, sequence, section, road_orientation, sub_project, sub_sub_project,
                                work_item, material_name, spec, test_item, test_param, standard,
                                sampling_method, inspection_type, frequency, planned_batches, remarks, lane_count)
                               VALUES (last_insert_rowid(), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (item.get("sequence", 0), item.get("section", ""),
                             item.get("road_orientation", ""),
                             item.get("sub_project", ""), item.get("sub_sub_project", ""),
                             item.get("work_item", ""), item.get("material_name", ""),
                             item.get("spec", ""), item.get("test_item", ""),
                             item.get("test_param", ""), item.get("standard", ""),
                             item.get("sampling_method", ""), item.get("inspection_type", "见证取样"),
                             item.get("frequency", ""), item.get("planned_batches", ""),
                             item.get("remarks", ""), item.get("lane_count", ""))
                        )

                # Store road sections
                sections = data.get("analysis_result", {}).get("sections", [])
                if not sections and result:
                    sections = (result or {}).get("sections", [])
                for s in sections:
                    self._conn.execute(
                        """INSERT INTO road_sections (project_id, section_name, road_orientation, description, sub_projects)
                           VALUES (?, ?, ?, ?, ?)""",
                        (pid, s.get("section", s.get("name", "")),
                         s.get("road_orientation", "双侧"),
                         s.get("description", ""),
                         json.dumps(s.get("sub_projects", []), ensure_ascii=False))
                    )

                self._conn.commit()
                count += 1
                logger.info("Migrated project: %s", name)
            except Exception as e:
                logger.warning("Failed to migrate %s: %s", f.name, e)

        self._conn.commit()
        return count

    def _add_migration_file(self, project_id: str, file_path: str, file_type: str):
        path = Path(file_path)
        try:
            fsize = path.stat().st_size
            fmtime = path.stat().st_mtime
        except OSError:
            fsize = None
            fmtime = None
        try:
            self._conn.execute(
                "INSERT INTO files (project_id, file_path, file_name, file_type, file_size, file_mtime, parse_status) VALUES (?, ?, ?, ?, ?, ?, 'done')",
                (project_id, file_path, path.name, file_type, fsize, fmtime)
            )
        except sqlite3.IntegrityError:
            pass

    # ==================== Vision results ====================

    def store_vision_result(self, file_id: int, model_name: str, result: Dict):
        """Store per-file vision analysis result (Qwen-VL)."""
        import json
        result_json = json.dumps(result, ensure_ascii=False)
        with self._lock:
            # Delete old result for this file first (replace)
            self._conn.execute("DELETE FROM vision_results WHERE file_id=?", (file_id,))
            self._conn.execute(
                "INSERT INTO vision_results (file_id, model_name, result_json) VALUES (?, ?, ?)",
                (file_id, model_name, result_json)
            )
            self._conn.commit()

    def get_vision_result(self, file_id: int) -> Optional[Dict]:
        """Get vision result for a specific file."""
        import json
        row = self._conn.execute(
            "SELECT result_json FROM vision_results WHERE file_id=? ORDER BY created_at DESC LIMIT 1",
            (file_id,)
        ).fetchone()
        if row:
            return json.loads(row[0])
        return None

    def has_vision_result(self, file_id: int) -> bool:
        """Check if a file already has a vision analysis result."""
        row = self._conn.execute(
            "SELECT COUNT(*) FROM vision_results WHERE file_id=?", (file_id,)
        ).fetchone()
        return row[0] > 0 if row else False

    def get_all_vision_results(self, project_id: str) -> Dict[int, Dict]:
        """Get all vision results for a project, keyed by file_id."""
        import json
        rows = self._conn.execute(
            """SELECT v.file_id, v.result_json, f.file_name, f.file_type
               FROM vision_results v
               JOIN files f ON v.file_id = f.id
               WHERE f.project_id=?""",
            (project_id,)
        ).fetchall()
        results = {}
        for row in rows:
            try:
                results[row[0]] = {
                    "result": json.loads(row[1]),
                    "file_name": row[2],
                    "file_type": row[3],
                }
            except Exception:
                pass
        return results

    def get_files_without_vision(self, project_id: str) -> List[Dict]:
        """Get files that need vision analysis (CAD/PDF only — word/excel skip vision). V4.9"""
        rows = self._conn.execute(
            """SELECT f.id, f.file_path, f.file_name, f.file_type, f.discipline
               FROM files f
               LEFT JOIN vision_results v ON f.id = v.file_id
               WHERE f.project_id=? AND f.parse_status='done' AND v.id IS NULL
               AND f.file_type IN ('cad', 'pdf')""",
            (project_id,)
        ).fetchall()
        return [dict(zip(["id", "file_path", "file_name", "file_type", "discipline"], r)) for r in rows]

    # ==================== Standards Knowledge Base (V5.2) ====================

    def import_standards_seed(self, json_path: str = None) -> int:
        """V5.2: 从 JSON 种子文件导入预置标准到 standards 表。返回导入数量。"""
        import json as _json
        if json_path is None:
            from pathlib import Path as _P
            import sys
            _meipass = getattr(sys, "_MEIPASS", None)
            if _meipass:
                json_path = _P(_meipass) / "database" / "standards_seed.json"
            else:
                json_path = _P(__file__).parent / "standards_seed.json"
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = _json.load(f)
        except Exception as e:
            logger.warning("Failed to load standards seed: %s", e)
            return 0
        count = 0
        with self._lock:
            for item in data:
                keywords = item.get("keywords", [])
                kw_str = ", ".join(keywords) if isinstance(keywords, list) else str(keywords)
                try:
                    self._conn.execute(
                        "INSERT OR IGNORE INTO standards (code, name, type, discipline, keywords, scope, version_year, is_active) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (item["code"], item["name"], item.get("type", "行标"),
                         item.get("discipline", "道路工程"), kw_str,
                         item.get("scope", ""), item.get("version_year"),
                         1 if item.get("mandatory", False) or item.get("is_active", True) else 1)
                    )
                    if self._conn.changes() > 0:
                        count += 1
                except Exception as e:
                    logger.debug("Skip standard %s: %s", item.get("code", "?"), e)
            self._conn.commit()
        logger.info("Imported %d standards from seed", count)
        return count

    def search_standards(self, keywords: str = "", discipline: str = "") -> list:
        """V5.2: 按关键词/专业搜索标准。返回匹配的标准列表。"""
        sql = "SELECT code, name, type, discipline, keywords, scope, version_year FROM standards WHERE is_active=1"
        params = []
        if keywords:
            terms = keywords.replace(",", " ").replace("，", " ").split()
            like_clauses = []
            for t in terms[:5]:  # 最多5个关键词
                like_clauses.append("(keywords LIKE ? OR name LIKE ?)")
                params.extend([f"%{t}%", f"%{t}%"])
            if like_clauses:
                sql += " AND (" + " OR ".join(like_clauses) + ")"
        if discipline:
            sql += " AND discipline = ?"
            params.append(discipline)
        sql += " ORDER BY CASE type WHEN '国标' THEN 1 WHEN '行标' THEN 2 ELSE 3 END, version_year DESC"
        rows = self._conn.execute(sql, params).fetchall()
        return [
            {"code": r[0], "name": r[1], "type": r[2], "discipline": r[3],
             "keywords": r[4], "scope": r[5], "version_year": r[6]}
            for r in rows
        ]

    def get_standards_by_discipline(self, discipline: str) -> list:
        """V5.2: 按专业获取标准列表。"""
        return self.search_standards(discipline=discipline)

    def get_matching_standards_for_keywords(self, keyword_list: list) -> list:
        """V5.2: 从关键词列表匹配标准，返回匹配到的标准编号列表（用于注入 prompt）。"""
        results = []
        seen = set()
        for kw in keyword_list[:10]:
            rows = self._conn.execute(
                "SELECT code FROM standards WHERE is_active=1 AND keywords LIKE ? "
                "ORDER BY CASE type WHEN '国标' THEN 1 WHEN '行标' THEN 2 ELSE 3 END LIMIT 3",
                (f"%{kw}%",)
            ).fetchall()
            for r in rows:
                if r[0] not in seen:
                    seen.add(r[0])
                    results.append(r[0])
        return results

    def get_standards_count(self) -> int:
        """V5.2: 标准总数。"""
        row = self._conn.execute("SELECT COUNT(*) FROM standards WHERE is_active=1").fetchone()
        return row[0] if row else 0

    def update_standards(self, replace_map: list, new_items: list) -> dict:
        """V5.3: 事务更新标准库（年度替换）。

        Args:
            replace_map: [{"old_code": "GB 1499.1-2024", "new": {...}}, ...]
            new_items: [{...}, ...] 全新标准

        Returns:
            {"replaced": N, "added": N, "errors": [...]}
        """
        result = {"replaced": 0, "added": 0, "errors": []}
        with self._lock:
            try:
                # 替换：标记旧标准为 inactive，插入新标准
                for r in (replace_map or []):
                    old_code = r.get("old_code", "")
                    new_std = r.get("new", {})
                    if not old_code or not new_std:
                        continue
                    # 标记旧标准为 inactive
                    self._conn.execute(
                        "UPDATE standards SET is_active=0 WHERE code=?",
                        (old_code,)
                    )
                    # 插入新标准
                    kw_list = new_std.get("keywords", [])
                    kw_str = ", ".join(kw_list) if isinstance(kw_list, list) else str(kw_list)
                    self._conn.execute(
                        """INSERT OR REPLACE INTO standards
                           (code, name, type, discipline, keywords, scope, version_year, series, is_active)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                        (
                            new_std.get("code", ""),
                            new_std.get("name", ""),
                            new_std.get("type", "行标"),
                            new_std.get("discipline", "通用规范"),
                            kw_str,
                            new_std.get("scope", ""),
                            new_std.get("version_year", 0),
                            new_std.get("series", ""),
                        )
                    )
                    result["replaced"] += 1

                # 新增
                for item in (new_items or []):
                    code = item.get("code", "")
                    if not code:
                        continue
                    kw_list = item.get("keywords", [])
                    kw_str = ", ".join(kw_list) if isinstance(kw_list, list) else str(kw_list)
                    self._conn.execute(
                        """INSERT OR IGNORE INTO standards
                           (code, name, type, discipline, keywords, scope, version_year, series, is_active)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                        (
                            code,
                            item.get("name", ""),
                            item.get("type", "行标"),
                            item.get("discipline", "通用规范"),
                            kw_str,
                            item.get("scope", ""),
                            item.get("version_year", 0),
                            item.get("series", ""),
                        )
                    )
                    result["added"] += 1

                self._conn.commit()
            except Exception as e:
                self._conn.rollback()
                result["errors"].append(str(e))
                import traceback
                logger.error("update_standards failed: %s", traceback.format_exc())
        return result

    def close(self):
        self._conn.close()
        if self._read_conn:
            self._read_conn.close()
