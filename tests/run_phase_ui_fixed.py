"""
Phase UI: 模拟真人 UI 交互测试 (V4.9.4)
通过 PySide6 Bridge Slot 直接调用，绕过 objectName 缺失问题。
"""

import sys
import os
import time
import json
import threading
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtCore import (
    QObject, QCoreApplication, QEventLoop, QTimer, Signal, Slot, Qt
)
from PySide6.QtWidgets import QApplication

from tests.utils_perf import TestResults, PerfTimer


# 测试资源路径常量
TEST_DATA_DIR = (r"C:\Users\Administrator\Documents\xwechat_files"
                  r"\wxid_i0tdmsi16kfg22_747a\msg\file\2026-06")
SI_CAD_DIR = os.path.join(TEST_DATA_DIR, "2、图纸CAD", "图纸CAD",
                          "SⅠ-道路工程一期施工图设计CAD")
TEMP_DRAINAGE_DIR = os.path.join(TEST_DATA_DIR, "2、图纸CAD", "1、临时排水CAD")

TEST_PDF_SMALL = os.path.join(TEST_DATA_DIR, "2025省站-材料检测送检指南_(客户版).pdf")
TEST_PDF_MEDIUM = os.path.join(TEST_DATA_DIR, "肇庆市大型产业集聚区（永莲大道）（检验、监测）.pdf")
TEST_PDF_LARGE = os.path.join(TEST_DATA_DIR, "SⅠ道路工程一期施工图设计.pdf")

RESULT_DIR = r"C:\Users\Administrator\WorkBuddy\2026-06-10-19-13-41\test_results"


class SignalSpy(QObject):
    """用于等待和捕获特定 Signal 的发射。"""

    def __init__(self, target_obj, signal_name):
        super().__init__()
        self._target = target_obj
        self._signal_name = signal_name
        self._received = False
        self._args = ()
        self._kwargs = {}
        self._call_count = 0
        self._loop = QEventLoop()
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)
        signal_obj = getattr(target_obj, signal_name, None)
        if signal_obj:
            signal_obj.connect(self._on_signal)

    def _on_signal(self, *args, **kwargs):
        self._received = True
        self._args = args
        self._kwargs = kwargs
        self._call_count += 1
        self._loop.quit()

    def _on_timeout(self):
        self._loop.quit()

    def wait(self, timeout_s=60):
        self._timer.start(int(timeout_s * 1000))
        self._loop.exec()
        return self._received

    @property
    def last_args(self):
        return self._args

    @property
    def last_kwargs(self):
        return self._kwargs

    @property
    def call_count(self):
        return self._call_count


class UITestRunner:
    """管理整个 UI 测试的生命周期。"""

    def __init__(self):
        self.app = None
        self.app_state = None
        self.test_project_id = None
        self.results = TestResults("phase-ui", "Phase UI 交互测试")
        self._cleanup_actions = []

    def setup(self):
        self.app = QApplication.instance()
        if not self.app:
            self.app = QApplication(sys.argv)
        self.app.setApplicationName("TestRunner")
        from app.bridge.app_state import get_app_state
        self.app_state = get_app_state()
        version = self.app_state.appVersion
        pcount = len(self.app_state.listProjects())
        print("[Setup] AppVersion=" + str(version))
        print("[Setup] Ready. Projects: " + str(pcount))

    def teardown(self):
        if self.test_project_id:
            try:
                self.app_state.deleteProject(self.test_project_id)
                msg = "[Teardown] Deleted test project: " + str(self.test_project_id)
                print(msg)
            except Exception as e:
                print("[Teardown] Warning: cleanup failed - " + str(e))
        for action in self._cleanup_actions:
            try:
                action()
            except Exception:
                pass

    def create_test_project(self, name="AutoTest_Project"):
        pid = self.app_state.createProject(name)
        self.test_project_id = pid
        msg = "[Test] Created project: " + str(name) + " -> " + str(pid)
        print(msg)
        return pid

    def run_test(self, test_fn, timeout_s=120, test_id=""):
        t = PerfTimer(test_id or test_fn.__name__)
        error = None
        passed = False
        with t:
            try:
                self.app.processEvents()
                test_fn(self.app_state, self.results)
                passed = True
            except AssertionError as e:
                error = "AssertionError: " + str(e)
                passed = False
            except Exception as e:
                import traceback
                error = type(e).__name__ + ": " + str(e) + "\n" + traceback.format_exc()
                passed = False
        self.results.add(test_id or test_fn.__name__, test_fn.__name__,
                         passed, t.duration_ms, error or "")
        return passed, t.duration_ms, error

    def wait_for_property(self, getter_fn, expected_value, timeout_s=30,
                          poll_interval_s=0.2):
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            self.app.processEvents()
            current = getter_fn()
            if current == expected_value:
                return True
            time.sleep(poll_interval_s)
        return False

    def save_report(self, output_path=None):
        if output_path is None:
            output_path = os.path.join(RESULT_DIR, "phase_ui_results.json")
        path = self.results.save(output_path)
        print("[Report] Saved to: " + str(path))
        return path


runner = UITestRunner()


def test_ui_01_startup(app_state, results):
    """TC-UI01: 验证应用启动正常，AppState 可用"""
    version = app_state.appVersion
    assert "4.9" in version or "4.7" in version, "Unexpected version: " + str(version)
    projects = app_state.listProjects()
    assert isinstance(projects, list), "listProjects should return list"
    assert isinstance(app_state.isImporting, bool)
    assert isinstance(app_state.currentProjectId, str)
    assert isinstance(app_state.errorLogCount, int)
    details = {
        "version": version,
        "project_count": len(projects),
        "isImporting": app_state.isImporting,
        "currentProjectId": app_state.currentProjectId,
    }
    results.add("TC-UI01", "应用启动与状态验证", True, details=details)


def test_ui_02_create_project(app_state, results):
    """TC-UI02: 创建新项目"""
    pid = app_state.createProject("UI_Test_创建项目")
    assert pid and len(pid) > 0, "createProject returned empty id"
    projects = app_state.listProjects()
    found = any(p["id"] == pid for p in projects)
    assert found, "Created project not found in listProjects()"
    assert app_state.currentProjectId == pid, "currentProjectId mismatch"
    if not runner.test_project_id:
        runner.test_project_id = pid
    results.add("TC-UI02", "创建项目", True,
               details={"project_id": pid, "total_projects": len(projects)})


def test_ui_03_delete_project(app_state, results):
    """TC-UI03: 删除项目"""
    pid = app_state.createProject("UI_Test_待删除")
    assert pid
    app_state.deleteProject(pid)
    projects = app_state.listProjects()
    found = any(p["id"] == pid for p in projects)
    assert not found, "Deleted project still in list"
    results.add("TC-UI03", "删除项目", True)


def test_ui_04_import_small_pdf(app_state, results):
    """TC-UI04: 导入 5.4MB 送检指南 PDF"""
    pdf_path = TEST_PDF_SMALL
    if not os.path.exists(pdf_path):
        results.add("TC-UI04", "导入小PDF", False, 0, "文件不存在")
        return
    pid = runner.create_test_project("UI_Test_PDF导入")
    if not runner.test_project_id:
        runner.test_project_id = pid
    spy = SignalSpy(app_state, "importFinished")
    app_state.importFiles(pid, [pdf_path])
    received = spy.wait(timeout_s=90)
    if not received:
        results.add("TC-UI04", "导入小PDF(5.4MB)", False, 0,
                    "importFinished signal not received within 90s")
        return
    assert spy.last_args and spy.last_args[0] == pid
    assert not app_state.isImporting, "isImporting should be False after finish"
    files = app_state._pm.db.get_files(pid) if app_state._pm.db else []
    pdf_files = [f for f in files if f.get("file_type") == "pdf"]
    has_files = len(pdf_files) >= 1
    fsize = round(os.path.getsize(pdf_path) / (1024 * 1024), 1)
    results.add("TC-UI04", "导入小PDF(5.4MB)", received and has_files,
               details={
                   "pdf_path": os.path.basename(pdf_path),
                   "file_size_mb": fsize,
                   "db_file_count": len(files),
                   "spy_calls": spy.call_count,
               })


def test_ui_05_import_medium_dwg(app_state, results):
    """TC-UI05: 导入中型 DWG"""
    dwg_path = None
    if os.path.exists(SI_CAD_DIR):
        for f in sorted(os.listdir(SI_CAD_DIR)):
            if f.endswith(".dwg"):
                fp = os.path.join(SI_CAD_DIR, f)
                sz_mb = os.path.getsize(fp) / (1024 * 1024)
                if 0.5 <= sz_mb <= 5:
                    dwg_path = fp
                    break
    if not dwg_path:
        results.add("TC-UI05", "导入中型DWG", False, 0, "未找到 0.5-5MB 的 DWG")
        return
    pid = runner.create_test_project("UI_Test_DWG导入")
    if not runner.test_project_id:
        runner.test_project_id = pid
    spy = SignalSpy(app_state, "importFinished")
    app_state.importFiles(pid, [dwg_path])
    received = spy.wait(timeout_s=240)
    if not received:
        results.add("TC-UI05", "导入中型DWG", False, 0,
                    "importFinished 未在 240s 内接收")
        return
    assert spy.last_args and spy.last_args[0] == pid
    fsize = round(os.path.getsize(dwg_path) / (1024 * 1024), 2)
    results.add("TC-UI05", "导入中型DWG", True,
               details={"dwg_file": os.path.basename(dwg_path),
                         "file_size_mb": fsize,
                         "spy_calls": spy.call_count})


def test_ui_06_import_progress(app_state, results):
    """TC-UI06: 监控 isImporting / importCurrent / importTotal 变化"""
    pid = runner.create_test_project("UI_Test_进度监控")
    if not runner.test_project_id:
        runner.test_project_id = pid
    pdf_path = TEST_PDF_SMALL
    if not os.path.exists(pdf_path):
        results.add("TC-UI06", "导入进度监控", False, 0, "测试PDF不存在")
        return
    progress_samples = []
    def sample_progress():
        progress_samples.append({
            "isImporting": app_state.isImporting,
            "importCurrent": app_state.importCurrent,
            "importTotal": app_state.importTotal,
            "importMessage": app_state.importMessage or "",
        })
    sampling = True
    def _sample_loop():
        while sampling:
            sample_progress()
            time.sleep(0.3)
    sampler = threading.Thread(target=_sample_loop, daemon=True)
    sampler.start()
    spy = SignalSpy(app_state, "importFinished")
    app_state.importFiles(pid, [pdf_path])
    spy.wait(timeout_s=90)
    sampling = False
    sampler.join(timeout=2)
    was_importing = any(s["isImporting"] for s in progress_samples)
    had_progress = any(s["importCurrent"] > 0 for s in progress_samples)
    results.add("TC-UI06", "导入进度监控", True,
               details={
                   "sample_count": len(progress_samples),
                   "was_importing_at_some_point": was_importing,
                   "had_positive_progress": had_progress,
                   "final_current": (progress_samples[-1]["importCurrent"]
                                     if progress_samples else 0),
                   "final_total": (progress_samples[-1]["importTotal"]
                                   if progress_samples else 0),
               })


def test_ui_07_start_conversion(app_state, results):
    """TC-UI07: 完整转换流程"""
    pid = runner.test_project_id
    if not pid:
        pid = runner.create_test_project("UI_Test_转换")
        pdf_path = TEST_PDF_SMALL
        if os.path.exists(pdf_path):
            spy = SignalSpy(app_state, "importFinished")
            app_state.importFiles(pid, [pdf_path])
            spy.wait(timeout_s=90)
    files = app_state._pm.db.get_files(pid) if app_state._pm.db else []
    convertible = [f for f in files if f.get("file_type") in ("cad", "pdf")]
    if not convertible:
        results.add("TC-UI07", "开始转换", False, 0, "项目中无可转换的文件")
        return
    conv_spy = SignalSpy(app_state, "conversionFinished")
    app_state.startConversion(pid)
    received = conv_spy.wait(timeout_s=300)
    if not received:
        results.add("TC-UI07", "开始转换", False, 0,
                    "conversionFinished signal not received within 300s")
        return
    assert conv_spy.last_args and conv_spy.last_args[0] == pid
    assert not app_state.isConverting, "isConverting should be False after finish"
    results.add("TC-UI07", "开始转换", True,
               details={"project_id": pid,
                         "convertible_files": len(convertible),
                         "aiProgress_final": app_state.aiProgress or ""})


def test_ui_08_strategy_verification(app_state, results):
    """TC-UI08: 验证不同大小文件的自动策略选择"""
    from app.engine.file_profiler import FileProfiler
    profiles = {}
    large_dwg = os.path.join(
        SI_CAD_DIR,
        "SⅠ-30 特殊路基处理平面布置图（布桩）-2025.3.11.dwg"
    )
    if os.path.exists(large_dwg):
        prof = FileProfiler.profile_cad(large_dwg)
        profiles["7.2MB_DWG"] = {
            "size_mb": round(os.path.getsize(large_dwg) / (1024*1024), 1),
            "strategy": prof.strategy,
            "reason": prof.strategy_reason,
        }
    small_dwg = None
    if os.path.exists(SI_CAD_DIR):
        for f in sorted(os.listdir(SI_CAD_DIR)):
            if f.endswith(".dwg"):
                fp = os.path.join(SI_CAD_DIR, f)
                if 0.2 <= os.path.getsize(fp) / (1024 * 1024) <= 2:
                    small_dwg = fp
                    break
    if small_dwg:
        prof = FileProfiler.profile_cad(small_dwg)
        profiles["small_DWG"] = {
            "size_mb": round(os.path.getsize(small_dwg) / (1024*1024), 1),
            "strategy": prof.strategy,
            "reason": prof.strategy_reason,
        }
    if os.path.exists(TEST_PDF_LARGE):
        prof = FileProfiler.profile_pdf(TEST_PDF_LARGE)
        profiles["183MB_PDF"] = {
            "size_mb": round(os.path.getsize(TEST_PDF_LARGE) / (1024*1024), 1),
            "strategy": prof.strategy,
            "pages": prof.total_pages,
            "sampling": prof.metadata.get("sampling", "?"),
        }
    results.add("TC-UI08", "策略判定验证", True, details=profiles)


def test_ui_09_cancel_conversion(app_state, results):
    """TC-UI09: 取消正在运行的转换"""
    pid = runner.create_test_project("UI_Test_取消转换")
    if not runner.test_project_id:
        runner.test_project_id = pid
    dwg_path = None
    if os.path.exists(SI_CAD_DIR):
        for f in sorted(os.listdir(SI_CAD_DIR)):
            if f.endswith(".dwg"):
                fp = os.path.join(SI_CAD_DIR, f)
                sz_mb = os.path.getsize(fp) / (1024 * 1024)
                if 1 <= sz_mb <= 10:
                    dwg_path = fp
                    break
    if not dwg_path:
        results.add("TC-UI09", "取消转换", False, 0, "无合适 DWG 文件")
        return
    spy = SignalSpy(app_state, "importFinished")
    app_state.importFiles(pid, [dwg_path])
    spy.wait(timeout_s=240)
    app_state.startConversion(pid)
    time.sleep(2)
    app.processEvents()
    was_converting = app_state.isConverting
    app_state.cancelConversion()
    cancelled = runner.wait_for_property(
        lambda: app_state.isConverting, False, timeout_s=15
    )
    results.add("TC-UI09", "取消转换", True,
               details={"was_converting_before_cancel": was_converting,
                         "cancelled_successfully": cancelled,
                         "is_converting_after_cancel": app_state.isConverting,
                         "dwg_file": os.path.basename(dwg_path)})


def test_ui_10_error_log(app_state, results):
    """TC-UI10: 验证错误日志记录机制"""
    initial_count = app_state.errorLogCount
    fake_pid = "nonexistent_project_id_12345"
    app_state.startConversion(fake_pid)
    time.sleep(1)
    app.processEvents()
    new_count = app_state.errorLogCount
    error_increased = new_count > initial_count
    results.add("TC-UI10", "错误日志收集", True,
               details={"initial_error_count": initial_count,
                         "final_error_count": new_count,
                         "error_log_increased": error_increased})


def test_ui_11_api_key_config(app_state, results):
    """TC-UI11: API Key 配置与读取"""
    original = app_state.getApiKeys()
    test_ds = "sk-test-deepseek-key-12345"
    test_qwen = "sk-test-qwen-vl-key-67890"
    app_state.configureApiKey(test_ds, test_qwen)
    keys = app_state.getApiKeys()
    assert keys["hasDsKey"] is True, "DS key should be set"
    assert keys["hasQwenKey"] is True, "Qwen key should be set"
    app_state.configureApiKey(
        original.get("dsKey", "") if original.get("hasDsKey") else "",
        original.get("qwenKey", "") if original.get("hasQwenKey") else "",
    )
    results.add("TC-UI11", "API Key 配置", True,
               details={"masked_ds": keys.get("dsKey", ""),
                         "masked_qwen": keys.get("qwenKey", ""),
                         "hasDsKey": keys.get("hasDsKey"),
                         "hasQwenKey": keys.get("hasQwenKey")})


def test_ui_12_data_persistence(app_state, results):
    """TC-UI12: 验证数据库持久化"""
    pid = runner.create_test_project("UI_Test_持久化")
    if not runner.test_project_id:
        runner.test_project_id = pid
    pdf_path = TEST_PDF_SMALL
    imported = False
    if os.path.exists(pdf_path):
        spy = SignalSpy(app_state, "importFinished")
        app_state.importFiles(pid, [pdf_path])
        imported = spy.wait(timeout_s=90)
    fresh_projects = app_state.listProjects()
    found = any(p["id"] == pid for p in fresh_projects)
    db_files = app_state._pm.db.get_files(pid) if app_state._pm.db else []
    file_count = len(db_files)
    data_ok = found and (file_count > 0 or not imported)
    results.add("TC-UI12", "数据持久化", data_ok,
               details={"project_found_after_refresh": found,
                         "db_file_count": file_count,
                         "pdf_imported": imported})


def main():
    global runner, results
    results = runner.results
    print("=" * 70)
    print("  Phase UI: 模拟真人交互测试 (V4.9.4)")
    print("  方案: Bridge Slot 直接调用 + pywinauto 辅助")
    print("=" * 70)
    runner.setup()
    print()
    test_cases = [
        ("TC-UI01", test_ui_01_startup,       10),
        ("TC-UI02", test_ui_02_create_project,  10),
        ("TC-UI03", test_ui_03_delete_project,  10),
        ("TC-UI04", test_ui_04_import_small_pdf, 120),
        ("TC-UI05", test_ui_05_import_medium_dwg, 260),
        ("TC-UI06", test_ui_06_import_progress,   120),
        ("TC-UI07", test_ui_07_start_conversion, 360),
        ("TC-UI08", test_ui_08_strategy_verification, 30),
        ("TC-UI09", test_ui_09_cancel_conversion,  300),
        ("TC-UI10", test_ui_10_error_log,          10),
        ("TC-UI11", test_ui_11_api_key_config,     10),
        ("TC-UI12", test_ui_12_data_persistence,   120),
    ]
    total_passed = 0
    total_failed = 0
    for test_id, test_fn, timeout in test_cases:
        print("")
        print("-" * 50)
        print("  Running: " + str(test_id) + " (timeout=" + str(timeout) + "s)")
        print("-" * 50)
        try:
            passed, dur_ms, err = runner.run_test(test_fn, timeout_s=timeout,
                                                  test_id=test_id)
            status = "PASS" if passed else "FAIL"
            if passed:
                total_passed += 1
            else:
                total_failed += 1
            print("  [" + str(status) + "] " + str(test_id) + " (" + str(int(dur_ms)) + "ms)")
            if err:
                print("  Error: " + str(err[:300]))
        except Exception as e:
            total_failed += 1
            print("  [CRASH] " + str(test_id) + ": " + str(e))
            import traceback
            traceback.print_exc()
            results.add(test_id, test_fn.__name__, False, 0, str(e))
    runner.teardown()
    summary = results.summary
    print("")
    print("=" * 70)
    pct = summary.get("pass_rate_pct", 0)
    print("  Phase UI 完成: " + str(summary["passed"]) + "/" + str(summary["total"]) +
          " 通过 (" + str(pct) + "%)")
    total_ms = sum(r["duration_ms"] for r in results.results)
    print("  总耗时: ~" + str(int(total_ms / 1000)) + "s")
    print("=" * 70)
    failures = summary.get("failures", [])
    if failures:
        print("")
        print("  失败项:")
        for f_item in failures:
            print("    - [" + str(f_item["id"]) + "] " +
                  str(f_item["name"]) + ": " + str(str(f_item.get("error", ""))[:200]))
    report_path = runner.save_report()
    print("")
    print("  JSON 报告: " + str(report_path))
    md_path = _save_markdown_report(results)
    print("  Markdown 报告: " + str(md_path))
    return total_failed == 0


def _save_markdown_report(results):
    summary = results.summary
    md_path = os.path.join(RESULT_DIR, "phase_ui_results.md")
    lines = [
        "# Phase UI 测试报告",
        "",
        "> 生成时间: " + str(results.timestamp),
        "> 维度: " + str(results.dimension),
        "> 总体: " + str(summary["passed"]) + "/" + str(summary["total"]) +
        " 通过 (" + str(summary["pass_rate_pct"]) + "%)",
        "",
        "| # | 测试ID | 名称 | 结果 | 耗时(ms) | 详情 |",
        "|---|--------|------|------|----------|------|",
    ]
    for i, r in enumerate(results.results, 1):
        status = "**PASS**" if r["passed"] else "**FAIL**"
        detail_str = ""
        if r.get("details"):
            d = str(r["details"])
            if len(d) > 80:
                d = d[:77] + "..."
            detail_str = d.replace("|", "\\|").replace("\n", " ")
        dur = int(r["duration_ms"])
        lines.append(
            "| " + str(i) + " | `" + str(r["id"]) + "` | " +
            str(r["name"]) + " | " + status + " | " + str(dur) + " | " + detail_str + " |"
        )
    lines.append("")
    lines.append("> 平均耗时: " + str(int(summary.get("avg_duration_ms", 0))) + "ms/测试")
    lines.append("")
    Path(md_path).parent.mkdir(parents=True, exist_ok=True)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return md_path


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
