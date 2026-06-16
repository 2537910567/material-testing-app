"""
V4.7: Construction layers CRUD tests
Tests for storing and retrieving construction layer hierarchy data.
"""
import pytest


class TestConstructionLayers:
    """Test construction_layers table CRUD operations"""

    def test_store_and_retrieve_layers(self, temp_db, db_manager):
        """Store construction layers and retrieve them"""
        pid = "test-project-1"
        db_manager._conn.execute(
            "INSERT INTO projects (id, name, created_at, updated_at) "
            "VALUES (?, ?, datetime('now'), datetime('now'))",
            (pid, "Test Project")
        )
        db_manager._conn.commit()

        layers = [
            {
                "section": "K0+100~K0+500",
                "road_orientation": "双侧",
                "step": 1,
                "layer_name": "底基层",
                "thickness": "150mm",
                "construction_process": "摊铺→碾压→养生",
                "materials": [
                    {"name": "级配碎石", "spec": "0~31.5mm"},
                ],
                "tests": [
                    {
                        "test_item": "压实度",
                        "test_param": "压实度≥96%",
                        "timing": "每层碾压后",
                        "frequency": "每层每1000㎡ 3点",
                        "standard": "CJJ 1-2008",
                    },
                    {
                        "test_item": "弯沉值",
                        "test_param": "回弹弯沉",
                        "timing": "养生后",
                        "frequency": "每车道每20m 1点",
                        "standard": "JTG 3450-2019",
                    },
                ],
            },
            {
                "section": "K0+100~K0+500",
                "road_orientation": "双侧",
                "step": 2,
                "layer_name": "基层",
                "thickness": "200mm",
                "construction_process": "拌合→运输→摊铺→碾压→养生",
                "materials": [
                    {"name": "水泥稳定碎石", "spec": "水泥剂量5%"},
                    {"name": "水泥", "spec": "P.O 42.5"},
                ],
                "tests": [
                    {
                        "test_item": "无侧限抗压强度",
                        "test_param": "≥3.5MPa",
                        "timing": "养生7天后",
                        "frequency": "每2000㎡ 1组",
                        "standard": "JTG/T F20-2015",
                    },
                ],
            },
        ]

        db_manager.store_construction_layers(pid, layers)

        results = db_manager.get_construction_layers(pid)
        assert len(results) == 2
        assert results[0]["layer_name"] == "底基层"
        assert results[0]["step"] == 1
        assert len(results[0]["materials"]) == 1
        assert len(results[0]["tests"]) == 2

    def test_filter_by_section(self, temp_db, db_manager):
        """Retrieve layers filtered by section_name"""
        pid = "test-project-2"
        db_manager._conn.execute(
            "INSERT INTO projects (id, name, created_at, updated_at) "
            "VALUES (?, ?, datetime('now'), datetime('now'))",
            (pid, "Test Project 2")
        )
        db_manager._conn.commit()

        layers = [
            {
                "section": "K0+582~K0+800",
                "road_orientation": "左幅",
                "step": 1,
                "layer_name": "下面层",
                "thickness": "60mm",
                "construction_process": "",
                "materials": [{"name": "AC-20C", "spec": ""}],
                "tests": [{"test_item": "压实度", "test_param": "", "timing": "", "frequency": "", "standard": "CJJ 1-2008"}],
            },
            {
                "section": "K0+800~K1+200",
                "road_orientation": "右幅",
                "step": 1,
                "layer_name": "上面层",
                "thickness": "40mm",
                "construction_process": "",
                "materials": [{"name": "SMA-13", "spec": ""}],
                "tests": [{"test_item": "抗滑", "test_param": "", "timing": "", "frequency": "", "standard": "JTG 3450-2019"}],
            },
        ]

        db_manager.store_construction_layers(pid, layers)

        results = db_manager.get_construction_layers(pid, "K0+582~K0+800")
        assert len(results) == 1
        assert results[0]["layer_name"] == "下面层"
        assert results[0]["road_orientation"] == "左幅"

        results_empty = db_manager.get_construction_layers(pid, "K2+000~K3+000")
        assert len(results_empty) == 0

    def test_cascade_delete(self, temp_db, db_manager):
        """Verify CASCADE delete removes layers+materials+tests"""
        pid = "test-project-3"
        db_manager._conn.execute(
            "INSERT INTO projects (id, name, created_at, updated_at) "
            "VALUES (?, ?, datetime('now'), datetime('now'))",
            (pid, "Test Project 3")
        )
        db_manager._conn.commit()

        layers = [{
            "section": "K0+000~K1+000",
            "road_orientation": "双侧",
            "step": 1,
            "layer_name": "基层",
            "thickness": "200mm",
            "construction_process": "",
            "materials": [{"name": "碎石", "spec": ""}],
            "tests": [{"test_item": "压实度", "test_param": "", "timing": "", "frequency": "", "standard": ""}],
        }]

        db_manager.store_construction_layers(pid, layers)
        results = db_manager.get_construction_layers(pid)
        assert len(results) == 1
        layer_id = results[0]["id"]

        mat_row = db_manager._conn.execute(
            "SELECT COUNT(*) FROM layer_materials WHERE layer_id=?", (layer_id,)
        ).fetchone()
        assert mat_row[0] == 1

        db_manager._conn.execute("DELETE FROM projects WHERE id=?", (pid,))
        db_manager._conn.commit()

        mat_after = db_manager._conn.execute(
            "SELECT COUNT(*) FROM layer_materials WHERE layer_id=?", (layer_id,)
        ).fetchone()
        assert mat_after[0] == 0

    def test_replace_on_reanalysis(self, temp_db, db_manager):
        """Re-storing layers replaces old data"""
        pid = "test-project-4"
        db_manager._conn.execute(
            "INSERT INTO projects (id, name, created_at, updated_at) "
            "VALUES (?, ?, datetime('now'), datetime('now'))",
            (pid, "Test Project 4")
        )
        db_manager._conn.commit()

        layers1 = [{
            "section": "K0+000~K1+000",
            "road_orientation": "双侧",
            "step": 1,
            "layer_name": "old_layer",
            "thickness": "150mm",
            "construction_process": "",
            "materials": [],
            "tests": [],
        }]
        db_manager.store_construction_layers(pid, layers1)
        assert len(db_manager.get_construction_layers(pid)) == 1

        layers2 = [
            {
                "section": "K0+000~K1+000",
                "road_orientation": "双侧",
                "step": 1,
                "layer_name": "new_base",
                "thickness": "200mm",
                "construction_process": "",
                "materials": [{"name": "C20", "spec": ""}],
                "tests": [{"test_item": "strength", "test_param": "", "timing": "", "frequency": "", "standard": ""}],
            },
            {
                "section": "K1+000~K2+000",
                "road_orientation": "双侧",
                "step": 1,
                "layer_name": "new_surface",
                "thickness": "50mm",
                "construction_process": "",
                "materials": [],
                "tests": [],
            },
        ]
        db_manager.store_construction_layers(pid, layers2)
        results2 = db_manager.get_construction_layers(pid)
        assert len(results2) == 2
        assert results2[0]["layer_name"] == "new_base"
        assert results2[1]["layer_name"] == "new_surface"
