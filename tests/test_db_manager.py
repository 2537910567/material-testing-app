import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# NOTE: conftest.py provides `db_manager` and `sample_plan` fixtures


class TestProjectCRUD:
    def test_create_project(self, db_manager):
        p = db_manager.create_project("测试项目")
        assert p["id"]
        assert p["name"] == "测试项目"
        assert p["total_files"] == 0

    def test_create_project_default_name(self, db_manager):
        p = db_manager.create_project("")
        assert p["name"].startswith("新项目")

    def test_get_project_not_found(self, db_manager):
        assert db_manager.get_project("nonexistent") is None

    def test_list_projects(self, db_manager):
        db_manager.create_project("A")
        db_manager.create_project("B")
        projects = db_manager.list_projects()
        assert len(projects) == 2

    def test_delete_project(self, db_manager):
        p = db_manager.create_project("ToDelete")
        db_manager.delete_project(p["id"])
        assert db_manager.get_project(p["id"]) is None

    def test_update_project_name(self, db_manager):
        p = db_manager.create_project("Old")
        db_manager.update_project_name(p["id"], "New")
        refreshed = db_manager.get_project(p["id"])
        assert refreshed["name"] == "New"


class TestFileCRUD:
    def test_add_file(self, db_manager):
        p = db_manager.create_project("F")
        fid = db_manager.add_file(p["id"], "C:/test/test.dwg", "cad")
        assert fid is not None

    def test_add_duplicate_file(self, db_manager):
        p = db_manager.create_project("F2")
        fid1 = db_manager.add_file(p["id"], "C:/test/test.dwg", "cad")
        fid2 = db_manager.add_file(p["id"], "C:/test/test.dwg", "cad")
        assert fid1 == fid2

    def test_get_files(self, db_manager):
        p = db_manager.create_project("F3")
        db_manager.add_file(p["id"], "C:/test/a.dwg", "cad")
        db_manager.add_file(p["id"], "C:/test/b.pdf", "pdf")
        files = db_manager.get_files(p["id"])
        assert len(files) == 2

    def test_get_unparsed_files(self, db_manager):
        p = db_manager.create_project("F4")
        db_manager.add_file(p["id"], "C:/test/a.dwg", "cad")
        unparsed = db_manager.get_unparsed_files(p["id"])
        assert len(unparsed) == 1


class TestEntitiesAndAnalysis:
    def test_store_and_get_text(self, db_manager):
        p = db_manager.create_project("T")
        fid = db_manager.add_file(p["id"], "C:/test/t.dwg", "cad")
        entities = [{"text": "桩号 K0+100", "layer": "TEXT", "x": 10, "y": 20}]
        db_manager.store_text_entities(fid, entities)
        text = db_manager.get_extracted_text(p["id"])
        assert "K0+100" in text

    def test_store_analysis_result(self, db_manager):
        p = db_manager.create_project("A")
        result = {"testing_plan": [], "project_info": {"project_name": "Test"}, "sections": []}
        db_manager.store_analysis_result(p["id"], result, model_name="deepseek-v4-flash")
        assert db_manager.has_analysis(p["id"])

    def test_latest_analysis_roundtrip(self, db_manager):
        p = db_manager.create_project("AR")
        plan = [
            {"sequence": 1, "section": "K0+000", "road_orientation": "双侧", "sub_project": "路基",
             "sub_sub_project": "/", "work_item": "土方", "material_name": "填料", "spec": "",
             "test_item": "压实", "test_param": "", "standard": "", "sampling_method": "",
             "inspection_type": "见证取样", "frequency": "", "planned_batches": "", "remarks": ""}
        ]
        result = {"testing_plan": plan, "project_info": {}, "sections": []}
        db_manager.store_analysis_result(p["id"], result)
        latest = db_manager.get_latest_analysis(p["id"])
        assert latest is not None
        assert len(latest["testing_plan"]) == 1
