"""
工程材料送检分析系统 - 入口
基于 DeepSeek AI 的智能送检计划生成工具

用法:
    py -3 main.py              # 启动 QML GUI
"""

import sys
import os
import atexit

# 确保能找到 app 包
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.logger import setup_logging, cleanup_old_logs
logger = setup_logging()

from PySide6.QtCore import Qt


def _cleanup_on_exit():
    """退出时清理临时文件"""
    try:
        from app.engine.dwg_parser import cleanup_session_temp_dirs
        cleaned = cleanup_session_temp_dirs()
        if cleaned:
            logger.info("Cleaned %d session temp dir(s)", cleaned)
    except Exception:
        pass


def _startup_cleanup():
    """启动时清理过期临时文件"""
    try:
        from app.engine.dwg_parser import cleanup_old_temp_dirs
        c = cleanup_old_temp_dirs(max_age_days=7)
        if c:
            logger.info("Cleaned %d old temp dir(s) (>7 days)", c)
    except Exception:
        pass


def _common_setup():
    """启动前通用设置"""
    _startup_cleanup()
    atexit.register(_cleanup_on_exit)



def run_gui():
    """启动 QML GUI"""
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon
    from PySide6.QtGui import QIcon
    from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterSingletonInstance
    from PySide6.QtQuickControls2 import QQuickStyle

    # QML 也需要高 DPI 设置
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    # 使用 QApplication（不是 QGuiApplication）以支持 QFileDialog 等 Widget
    app = QApplication(sys.argv)
    app.setApplicationName("工程材料送检分析系统")
    app.setApplicationVersion("6.1.2")
    app.setOrganizationName("MaterialTestingTool")

    # 应用图标（多路径回退，兼容开发环境和 PyInstaller 打包）
    from PySide6.QtGui import QIcon
    _base_dir = os.path.dirname(os.path.abspath(__file__))
    _meipass = getattr(sys, "_MEIPASS", None)  # PyInstaller 打包后的资源目录
    _icon_candidates = [
        os.path.join(_meipass, "app_icon.png") if _meipass else None,
        os.path.join(_base_dir, "app_icon.png"),
        os.path.join(_base_dir, "app", "resources", "icon.png"),
        r"C:\Users\Administrator\Desktop\file_type_vscode_icon_130084.png",
    ]
    for _ip in _icon_candidates:
        if _ip and os.path.exists(_ip):
            app.setWindowIcon(QIcon(_ip))
            logger.info("App icon loaded: %s", _ip)
            break
    else:
        logger.warning("App icon not found in any candidate path")

    # 使用 Fusion 风格（与 QWidget 版一致的外观基础）
    QQuickStyle.setStyle("Fusion")

    logger.info("Starting QML GUI (V6.0.0)...")

    # ── V5.2: 导入标准知识库种子数据（仅首次）──
    try:
        from app.database.db_manager import DatabaseManager
        from app.database.schema import migrate, SCHEMA_VERSION
        import sqlite3 as _sq
        from pathlib import Path as _P
        db_dir = _P.home() / ".material_testing_tool"
        db_dir.mkdir(parents=True, exist_ok=True)
        db_path = str(db_dir / "material_testing.db")
        _conn = _sq.connect(db_path)
        migrate(_conn, SCHEMA_VERSION)
        count = _conn.execute("SELECT COUNT(*) FROM standards").fetchone()[0]
        _conn.close()
        # V6.0: 每次启动都同步种子数据（INSERT OR IGNORE 保证不重复）
        dm = DatabaseManager(db_path)
        n = dm.import_standards_seed()
        if n > 0:
            logger.info("Imported %d new standards from seed", n)
        dm.close()
    except Exception as e:
        logger.warning("Standards seed import skipped: %s", e)

    # ── 创建 Bridge 对象 ──────────────────────────
    from app.bridge.theme import ThemeObject
    from app.bridge.app_state import get_app_state
    from app.bridge.project_model import ProjectListModel
    from app.bridge.file_model import FileListModel
    from app.bridge.section_model import SectionListModel
    from app.bridge.plan_table_model import PlanTableModel
    from app.bridge.project_tree_model import ProjectTreeModel  # V4.9.4: 统一树模型

    app_state = get_app_state()
    project_list_model = ProjectListModel()
    project_list_model.set_project_manager(app_state._pm)
    file_list_model = FileListModel()
    section_list_model = SectionListModel()
    plan_table_model = PlanTableModel()
    project_tree_model = ProjectTreeModel()  # V4.9.4
    if app_state._pm and app_state._pm.db:
        file_list_model.set_db_manager(app_state._pm.db)
        section_list_model.set_db_manager(app_state._pm.db)
        plan_table_model.set_db_manager(app_state._pm.db)
        project_tree_model.set_db_manager(app_state._pm.db)  # V4.9.4
        project_tree_model.refresh()  # V4.9.4: 启动时初始加载项目列表

    # ── V5.2: 读取并应用主题偏好 ──
    theme_instance = ThemeObject()
    app_state._theme_instance = theme_instance  # V6.1: 供 StandardsWindow 独立引擎使用
    try:
        saved_mode = app_state._config.theme_mode
        if saved_mode in ("light", "dark"):
            theme_instance.setThemeMode(saved_mode)
    except Exception:
        pass

    # ── 注册 QML 单例（保持 Python 引用防止 GC）──
    qmlRegisterSingletonInstance(ThemeObject, "AppTheme", 1, 0, "AppTheme", theme_instance)
    qmlRegisterSingletonInstance(type(app_state), "AppState", 1, 0, "AppState", app_state)
    qmlRegisterSingletonInstance(type(project_list_model), "ProjectListModel", 1, 0, "ProjectListModel", project_list_model)
    qmlRegisterSingletonInstance(type(file_list_model), "FileListModel", 1, 0, "FileListModel", file_list_model)
    qmlRegisterSingletonInstance(type(section_list_model), "SectionListModel", 1, 0, "SectionListModel", section_list_model)
    qmlRegisterSingletonInstance(type(plan_table_model), "PlanTableModel", 1, 0, "PlanTableModel", plan_table_model)
    qmlRegisterSingletonInstance(type(project_tree_model), "ProjectTreeModel", 1, 0, "ProjectTreeModel", project_tree_model)

    # ── 创建 QML 引擎并加载 ────────────────────────
    engine = QQmlApplicationEngine()

    # V6.1: PyInstaller 打包后 QML 在 _MEIPASS/qml/，开发环境在 app/qml/
    qml_dir = os.path.join(_meipass, "qml") if _meipass else \
              os.path.join(os.path.dirname(os.path.abspath(__file__)), "app", "qml")
    qml_main = os.path.join(qml_dir, "main.qml")

    if not os.path.exists(qml_main):
        logger.error("QML file not found: %s", qml_main)
        print(f"[ERROR] QML file not found: {qml_main}")
        sys.exit(1)

    def _on_qml_warning(warnings_list):
        for w in warnings_list:
            logger.warning("QML: %s", w.toString())

    engine.warnings.connect(_on_qml_warning)

    # V6.1: 系统托盘图标（转换/AI完成时弹通知）
    _tray = QSystemTrayIcon()
    _tray_icon_path = None
    for _ip in _icon_candidates:
        if _ip and os.path.exists(_ip):
            _tray_icon_path = _ip
            break
    if _tray_icon_path:
        _tray.setIcon(QIcon(_tray_icon_path))
    _tray.setToolTip("工程材料送检分析系统")
    _tray.show()

    # 连接 AppState 信号到托盘通知
    from app.bridge.app_state import get_app_state
    _as = get_app_state()
    def _on_conv_finished(pid):
        _tray.showMessage("工程材料送检分析系统",
                          "✅ 转换完成！可以开始 AI 分析",
                          QSystemTrayIcon.MessageIcon.Information, 8000)
    def _on_analysis_finished(pid, result):
        _tray.showMessage("工程材料送检分析系统",
                          "✅ AI 分析完成！可以导出 Excel",
                          QSystemTrayIcon.MessageIcon.Information, 8000)
    _as.conversionFinished.connect(_on_conv_finished)
    _as.analysisFinished.connect(_on_analysis_finished)

    engine.load(qml_main)

    if not engine.rootObjects():
        logger.error("Failed to load QML — engine has no root objects")
        print("[ERROR] QML load failed — check QML syntax and imports")
        sys.exit(1)

    logger.info("QML GUI loaded successfully")

    sys.exit(app.exec())


def main():
    """应用程序入口"""
    _common_setup()
    run_gui()

if __name__ == "__main__":
    main()
