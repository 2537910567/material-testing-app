import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database.schema import migrate, SCHEMA_VERSION


@pytest.fixture
def temp_db():
    """In-memory SQLite database with full schema."""
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    migrate(conn, SCHEMA_VERSION)
    yield conn
    conn.close()


@pytest.fixture
def db_manager(temp_db, monkeypatch):
    """DatabaseManager backed by in-memory SQLite."""
    from app.database.db_manager import DatabaseManager
    import threading

    class MemDB(DatabaseManager):
        def __init__(self):
            self.db_path = ":memory:"
            self._lock = threading.Lock()
            self._conn = temp_db
            self._read_conn = temp_db  # V4.9.4: 内存库读写同连接
    return MemDB()


@pytest.fixture
def sample_plan():
    """Minimal testing plan with 2 items."""
    return [
        {
            "sequence": 1, "section": "K0+100~K0+200", "road_orientation": "双侧",
            "sub_project": "路基工程", "sub_sub_project": "/", "work_item": "土方路基",
            "material_name": "路基填料", "spec": "土", "test_item": "压实度",
            "test_param": "压实度", "standard": "CJJ 1-2008", "sampling_method": "灌砂法",
            "inspection_type": "见证取样", "frequency": "每1000㎡ 3点",
            "planned_batches": "", "lane_count": "", "remarks": ""
        },
        {
            "sequence": 2, "section": "K0+200~K0+400", "road_orientation": "双侧",
            "sub_project": "路面工程", "sub_sub_project": "沥青面层", "work_item": "AC-20中面层",
            "material_name": "沥青混合料", "spec": "AC-20", "test_item": "马歇尔稳定度",
            "test_param": "稳定度、流值", "standard": "JTG E20-2011", "sampling_method": "现场取样",
            "inspection_type": "见证取样", "frequency": "每台班1次",
            "planned_batches": "", "lane_count": "", "remarks": ""
        }
    ]
