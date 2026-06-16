"""
SQLite schema DDL + versioned migration.

Database: ~/.material_testing_tool/material_testing.db
"""

SCHEMA_VERSION = 13

DDL_V1 = """
-- Projects table (replaces individual JSON files)
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    notes TEXT DEFAULT '',
    last_export TEXT DEFAULT ''
);

-- Files table (one row per imported file)
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    file_name TEXT NOT NULL,
    file_type TEXT NOT NULL CHECK(file_type IN ('cad', 'pdf')),
    file_size INTEGER,
    file_mtime REAL,
    discipline TEXT DEFAULT '',
    description TEXT DEFAULT '',
    parse_status TEXT NOT NULL DEFAULT 'pending'
        CHECK(parse_status IN ('pending', 'parsing', 'done', 'error')),
    parse_error TEXT DEFAULT NULL,
    parse_duration_ms INTEGER DEFAULT NULL,
    parsed_at TEXT DEFAULT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(project_id, file_path)
);

-- Text entities from CAD parsing
CREATE TABLE IF NOT EXISTS text_entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    layer TEXT DEFAULT '',
    pos_x REAL DEFAULT 0.0,
    pos_y REAL DEFAULT 0.0
);
CREATE INDEX IF NOT EXISTS idx_text_entities_file ON text_entities(file_id);

-- Block attributes from CAD parsing
CREATE TABLE IF NOT EXISTS block_attributes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    value TEXT DEFAULT '',
    layer TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_block_attrs_file ON block_attributes(file_id);

-- Tables extracted from CAD/PDF
CREATE TABLE IF NOT EXISTS extracted_tables (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    table_index INTEGER NOT NULL DEFAULT 0,
    page_number INTEGER DEFAULT NULL,
    row_count INTEGER NOT NULL DEFAULT 0,
    col_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_tables_file ON extracted_tables(file_id);

-- Table cells (normalized)
CREATE TABLE IF NOT EXISTS table_cells (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_id INTEGER NOT NULL REFERENCES extracted_tables(id) ON DELETE CASCADE,
    row_idx INTEGER NOT NULL,
    col_idx INTEGER NOT NULL,
    cell_text TEXT DEFAULT ''
);

-- Road sections identified during parsing
CREATE TABLE IF NOT EXISTS road_sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    section_name TEXT NOT NULL,
    left_right TEXT DEFAULT '双侧',
    description TEXT DEFAULT '',
    sub_projects TEXT DEFAULT '',
    source_file_id INTEGER REFERENCES files(id) ON DELETE SET NULL,
    identified_by TEXT DEFAULT 'text',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_sections_project ON road_sections(project_id);

-- Page-to-chainage mappings (平面分幅图)
CREATE TABLE IF NOT EXISTS page_chainage_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL DEFAULT 0,
    chainage_start TEXT DEFAULT '',
    chainage_end TEXT DEFAULT '',
    left_right TEXT DEFAULT '双侧',
    confidence REAL DEFAULT 0.0,
    identified_by TEXT DEFAULT 'text'
);

-- AI analysis results
CREATE TABLE IF NOT EXISTS analysis_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    analysis_type TEXT NOT NULL DEFAULT 'full',
    model_name TEXT NOT NULL,
    sections_included TEXT DEFAULT '',
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Individual testing plan items (16 columns)
CREATE TABLE IF NOT EXISTS testing_plan_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id INTEGER NOT NULL REFERENCES analysis_results(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL DEFAULT 0,
    section TEXT DEFAULT '',
    left_right TEXT DEFAULT '双侧',
    sub_project TEXT DEFAULT '',
    sub_sub_project TEXT DEFAULT '',
    work_item TEXT DEFAULT '',
    material_name TEXT DEFAULT '',
    spec TEXT DEFAULT '',
    test_item TEXT DEFAULT '',
    test_param TEXT DEFAULT '',
    standard TEXT DEFAULT '',
    sampling_method TEXT DEFAULT '',
    inspection_type TEXT DEFAULT '见证取样',
    frequency TEXT DEFAULT '',
    planned_batches TEXT DEFAULT '',
    remarks TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_plan_items_analysis ON testing_plan_items(analysis_id);
CREATE INDEX IF NOT EXISTS idx_plan_items_section ON testing_plan_items(section);

-- App settings (replaces config.json for advanced settings)
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

DDL_V2 = """

-- Vision analysis results (per-file, from Qwen-VL)
CREATE TABLE IF NOT EXISTS vision_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    model_name TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_vision_results_file ON vision_results(file_id);
"""

DDL_V3 = """
-- V3: Add thumbnail_path column to files table
ALTER TABLE files ADD COLUMN thumbnail_path TEXT DEFAULT '';
"""

DDL_V4 = """
-- V4: AI analysis result cache
CREATE TABLE IF NOT EXISTS ai_cache (
    cache_key TEXT PRIMARY KEY,
    result_json TEXT NOT NULL,
    model_name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ai_cache_created ON ai_cache(created_at);
"""

DDL_V5 = """
-- V5: Construction layers hierarchy (路段→施工层→材料/检测)
CREATE TABLE IF NOT EXISTS construction_layers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    section_name TEXT NOT NULL,
    left_right TEXT DEFAULT '双侧',
    step INTEGER NOT NULL,
    layer_name TEXT NOT NULL,
    thickness TEXT DEFAULT '',
    construction_process TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_layers_section ON construction_layers(project_id, section_name);

CREATE TABLE IF NOT EXISTS layer_materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    layer_id INTEGER NOT NULL REFERENCES construction_layers(id) ON DELETE CASCADE,
    material_name TEXT NOT NULL,
    spec TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_materials_layer ON layer_materials(layer_id);

CREATE TABLE IF NOT EXISTS layer_tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    layer_id INTEGER NOT NULL REFERENCES construction_layers(id) ON DELETE CASCADE,
    test_item TEXT NOT NULL,
    test_param TEXT DEFAULT '',
    timing TEXT DEFAULT '',
    frequency TEXT DEFAULT '',
    standard TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_tests_layer ON layer_tests(layer_id);
"""

DDL_V7 = """
-- V7: Expand file_type CHECK to include word/excel — V4.9
-- SQLite does not support ALTER CHECK, so we rebuild the files table.
CREATE TABLE IF NOT EXISTS files_v7 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    file_name TEXT NOT NULL,
    file_type TEXT NOT NULL CHECK(file_type IN ('cad', 'pdf', 'word', 'excel')),
    file_size INTEGER,
    file_mtime REAL,
    discipline TEXT DEFAULT '',
    description TEXT DEFAULT '',
    parse_status TEXT NOT NULL DEFAULT 'pending'
        CHECK(parse_status IN ('pending', 'parsing', 'done', 'error')),
    parse_error TEXT DEFAULT NULL,
    parse_duration_ms INTEGER DEFAULT NULL,
    parsed_at TEXT DEFAULT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    thumbnail_path TEXT DEFAULT '',
    UNIQUE(project_id, file_path)
);

INSERT INTO files_v7 SELECT * FROM files;

DROP TABLE files;

ALTER TABLE files_v7 RENAME TO files;
"""

DDL_V6 = """
-- V6: Construction procedures (施工步骤明细) + Analysis checkpoints (断点恢复) — V4.8
CREATE TABLE IF NOT EXISTS layer_procedures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    layer_id INTEGER NOT NULL REFERENCES construction_layers(id) ON DELETE CASCADE,
    step_order INTEGER NOT NULL,
    step_name TEXT NOT NULL,
    step_description TEXT DEFAULT '',
    key_points TEXT DEFAULT '',
    applicable_standards TEXT DEFAULT '',
    parameters TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_procedures_layer ON layer_procedures(layer_id);

CREATE TABLE IF NOT EXISTS analysis_checkpoints (
    project_id TEXT PRIMARY KEY,
    step TEXT NOT NULL,
    vision_processed_files TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);
"""

DDL_V8 = """
-- V8: Rename left_right → road_orientation (路幅) — V4.9.2
ALTER TABLE road_sections RENAME COLUMN left_right TO road_orientation;
ALTER TABLE page_chainage_mappings RENAME COLUMN left_right TO road_orientation;
ALTER TABLE testing_plan_items RENAME COLUMN left_right TO road_orientation;
ALTER TABLE construction_layers RENAME COLUMN left_right TO road_orientation;
"""

DDL_V9 = """
-- V9: File profiles (文件预分析结果缓存) — V4.9.3
CREATE TABLE IF NOT EXISTS file_profiles (
    file_id INTEGER PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
    file_md5 TEXT NOT NULL,
    profile_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_file_profiles_md5 ON file_profiles(file_md5);
"""

DDL_V10 = """
-- V10: File conversion status (文件转换状态) — V4.9.3
ALTER TABLE files ADD COLUMN conversion_status TEXT DEFAULT '';
"""

DDL_V11 = """
-- V11: 路幅值域简化 + 新增车道列 — V4.9.4
ALTER TABLE testing_plan_items ADD COLUMN lane_count TEXT DEFAULT '';
"""

DDL_V12 = """
-- V12 (V5.2.0): 转换错误详情 + AI可观测性 + 标准知识库 + 项目参考资料

-- 2c: 转换错误详情
ALTER TABLE files ADD COLUMN conversion_error TEXT DEFAULT '';

-- 6: AI 管线可观测性
ALTER TABLE ai_cache ADD COLUMN latency_ms INTEGER DEFAULT 0;
ALTER TABLE ai_cache ADD COLUMN token_count INTEGER DEFAULT 0;
ALTER TABLE ai_cache ADD COLUMN retry_count INTEGER DEFAULT 0;

-- 9a: 参考知识库 — 全局标准库（预置数据，只读）
CREATE TABLE IF NOT EXISTS standards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT '行标',
    discipline TEXT NOT NULL DEFAULT '道路工程',
    keywords TEXT DEFAULT '',
    scope TEXT DEFAULT '',
    version_year INTEGER,
    is_active INTEGER DEFAULT 1
);

-- 9a: 项目参考资料 — 记录项目文档中引用的标准
CREATE TABLE IF NOT EXISTS project_references (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    standard_code TEXT NOT NULL,
    source TEXT DEFAULT 'document',
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (standard_code) REFERENCES standards(code)
);
"""

DDL_V13 = """
-- V13 (V5.3.0): 标准表 — 添加系列列用于年度替换匹配
ALTER TABLE standards ADD COLUMN series TEXT DEFAULT '';
"""

MIGRATIONS = [
    (1, DDL_V1),
    (2, DDL_V1 + DDL_V2),
    (3, DDL_V3),
    (4, DDL_V4),
    (5, DDL_V5),
    (6, DDL_V6),
    (7, DDL_V7),
    (8, DDL_V8),
    (9, DDL_V9),
    (10, DDL_V10),
    (11, DDL_V11),
    (12, DDL_V12),
    (13, DDL_V13),
]


def migrate(conn, target_version: int = SCHEMA_VERSION):
    """Apply all pending migrations up to target_version."""
    # Ensure version tracking table exists
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)")
    conn.commit()

    cur = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()
    current = cur[0]

    for ver, sql in MIGRATIONS:
        if ver > current and ver <= target_version:
            conn.executescript(sql)
            conn.execute("INSERT OR REPLACE INTO schema_version (version) VALUES (?)", (ver,))
            conn.commit()
