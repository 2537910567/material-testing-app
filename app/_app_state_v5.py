"""
全局应用状态 — QObject 单例，桥接 engine/database 层到 QML。

持有 AppConfig、ProjectManager 实例，封装 FileImportThread 和 AIAnalysisThread
为 QML 可访问的 Signal/Slot。
"""

import os
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from PySide6.QtCore import QObject, Signal, Slot, Property, QThread
from PySide6.QtQml import QmlElement
from PySide6.QtWidgets import QFileDialog

from ..config import AppConfig
from ..engine.project_manager import ProjectManager, Project
from ..engine.ai_agent import analyze_with_provider
from ..engine.model_provider import ModelProviderFactory
from ..engine.pdf_parser import extract_pdf_content, extract_page_images
from ..engine.dwg_parser import parse_dwg, extract_all_text, convert_dwg_to_png
from ..report.report_generator import generate_testing_plan
from ..logger import get_logger

logger = get_logger("bridge")


def _detect_testing_guide(file_path: str, content_text: str = "") -> bool:
    """
    V4.6: 检测文件是否为送检指南。

    检测策略：
    1. 文件名关键词匹配（文件名检测）
    2. PDF 内容关键词匹配（文本检测）
    """
    file_name = Path(file_path).name.lower()
    name_keywords = ["送检指南", "检测指南", "送检指引", "材料检测", "testing guide"]
    if any(kw in file_name for kw in name_keywords):
        return True

    if content_text:
        content_keywords = ["送检频率", "检验批", "取样频率", "检测频次",
                           "inspection frequency", "送检计划", "检验批次"]
        if any(kw in content_text for kw in content_keywords):
            return True

    return False


# ==================== Worker Threads ====================


# V5.0: Thread classes in worker_*.py
from .worker_import import FileImportThread
from .worker_profile import ProfileThread
from .worker_conversion import StrategyConversionThread
from .worker_analysis import AIAnalysisThread
from .worker_export import ExportThread
from .worker_connect import ConnectionTestThread

# ==================== AppState Singleton ====================

class AppState(QObject):
    """
    全局应用状态，暴露给 QML 的 context property。

    Properties (可绑定):
      - currentProjectId: str
      - currentProjectName: str
      - isImporting: bool
      - isAnalyzing: bool
      - importCurrent: int
      - importTotal: int
      - importMessage: str
      - aiProgress: str
      - appVersion: str
    """

    # ── Signals ──────────────────────────────────────────
    currentProjectIdChanged = Signal()
    currentProjectNameChanged = Signal()
    isImportingChanged = Signal()
    isAnalyzingChanged = Signal()
    isConvertingChanged = Signal()    # V4.9.2
    isAnalysisPausedChanged = Signal()
    importCurrentChanged = Signal()
    importTotalChanged = Signal()
    importMessageChanged = Signal()
    aiProgressChanged = Signal()
    isExportingChanged = Signal()
    projectsChanged = Signal()

    # 操作结果信号
    analysisFinished = Signal(str, object)   # project_id, result
    analysisError = Signal(str, str)         # project_id, error_msg
    importFinished = Signal(str)             # project_id
    conversionFinished = Signal(str)          # project_id (V4.9.3)
    exportFinished = Signal(str)             # output_path
    exportError = Signal(str)                # error_msg
    projectDeleted = Signal(str)             # project_id (删除项目后通知 QML 清空面板)
    errorLogChanged = Signal()               # V4.9: 错误日志更新
    connectionTestFinished = Signal("QVariantMap")  # V4.9.4: API连接测试结果

    def __init__(self, parent=None):
        super().__init__(parent)
        self._config = AppConfig()
        self._pm = ProjectManager()
        self._import_thread = None
        self._conversion_thread = None
        self._profile_thread = None      # V4.9.3
        self._ai_thread = None
        self._export_thread = None

        # Internal state
        self._current_project_id = ""
        self._current_project_name = ""
        self._is_importing = False
        self._is_converting = False     # V4.9.2
        self._conversion_current = 0    # V4.9.3
        self._conversion_total = 0      # V4.9.3
        self._is_analyzing = False
        self._is_analysis_paused = False
        self._analysis_current = 0      # V4.9.3
        self._analysis_total = 0        # V4.9.3
        self._is_exporting = False
        self._import_current = 0
        self._import_total = 0
        self._import_message = ""
        self._ai_progress = ""

        # V4.9: 错误日志收集
        self._error_log: list = []
        self._error_log_count = 0

        # Accumulate parsed results during import
        self._cad_results = []
        self._pdf_results = []

    # ── Properties ───────────────────────────────────────

    # currentProjectId
    def _get_current_project_id(self) -> str:
        return self._current_project_id

    def _set_current_project_id(self, value: str):
        if self._current_project_id != value:
            self._current_project_id = value
            self.currentProjectIdChanged.emit()
            # Sync project name
            if value:
                proj = self._pm.get_project(value)
                self._set_current_project_name(proj.name if proj else "")
            else:
                self._set_current_project_name("")

    currentProjectId = Property(str, _get_current_project_id, _set_current_project_id,
                                notify=currentProjectIdChanged)

    # currentProjectName
    def _get_current_project_name(self) -> str:
        return self._current_project_name

    def _set_current_project_name(self, value: str):
        if self._current_project_name != value:
            self._current_project_name = value
            self.currentProjectNameChanged.emit()

    currentProjectName = Property(str, _get_current_project_name, _set_current_project_name,
                                  notify=currentProjectNameChanged)

    # isImporting
    def _get_is_importing(self) -> bool:
        return self._is_importing

    def _set_is_importing(self, value: bool):
        if self._is_importing != value:
            self._is_importing = value
            self.isImportingChanged.emit()

    isImporting = Property(bool, _get_is_importing, _set_is_importing, notify=isImportingChanged)

    # isAnalyzing
    def _get_is_analyzing(self) -> bool:
        return self._is_analyzing

    def _set_is_analyzing(self, value: bool):
        if self._is_analyzing != value:
            self._is_analyzing = value
            self.isAnalyzingChanged.emit()

    isAnalyzing = Property(bool, _get_is_analyzing, _set_is_analyzing, notify=isAnalyzingChanged)

    # isConverting (V4.9.2)
    def _get_is_converting(self) -> bool:
        return self._is_converting

    def _set_is_converting(self, value: bool):
        if self._is_converting != value:
            self._is_converting = value
            self.isConvertingChanged.emit()

    isConverting = Property(bool, _get_is_converting, _set_is_converting, notify=isConvertingChanged)

    # conversionCurrent (V4.9.3) — 转换进度百分比
    conversionCurrentChanged = Signal()

    def _get_conversion_current(self) -> int:
        return self._conversion_current

    def _set_conversion_current(self, value: int):
        if self._conversion_current != value:
            self._conversion_current = value
            self.conversionCurrentChanged.emit()

    conversionCurrent = Property(int, _get_conversion_current, _set_conversion_current,
                                 notify=conversionCurrentChanged)

    # conversionTotal (V4.9.3)
    conversionTotalChanged = Signal()

    def _get_conversion_total(self) -> int:
        return self._conversion_total

    def _set_conversion_total(self, value: int):
        if self._conversion_total != value:
            self._conversion_total = value
            self.conversionTotalChanged.emit()

    conversionTotal = Property(int, _get_conversion_total, _set_conversion_total,
                                notify=conversionTotalChanged)

    def _set_conversion_progress(self, current: int, total: int, detail: str = ""):
        """V4.9.3: 更新转换进度（当前/总数 + 详情文字）"""
        self._set_conversion_current(current)
        self._set_conversion_total(total)
        if detail:
            self._set_ai_progress(f"转换 {current}/{total}: {detail}")
        else:
            pct = round(current / total * 100) if total > 0 else 0
            self._set_ai_progress(f"转换 {current}/{total} ({pct}%)")

    # isAnalysisPaused
    def _get_is_analysis_paused(self) -> bool:
        return self._is_analysis_paused

    def _set_is_analysis_paused(self, value: bool):
        if self._is_analysis_paused != value:
            self._is_analysis_paused = value
            self.isAnalysisPausedChanged.emit()

    isAnalysisPaused = Property(bool, _get_is_analysis_paused, _set_is_analysis_paused,
                                notify=isAnalysisPausedChanged)

    # analysisCurrent (V4.9.3) — AI 分析进度百分比
    analysisCurrentChanged = Signal()

    def _get_analysis_current(self) -> int:
        return self._analysis_current

    def _set_analysis_current(self, value: int):
        if self._analysis_current != value:
            self._analysis_current = value
            self.analysisCurrentChanged.emit()

    analysisCurrent = Property(int, _get_analysis_current, _set_analysis_current,
                               notify=analysisCurrentChanged)

    # analysisTotal (V4.9.3)
    analysisTotalChanged = Signal()

    def _get_analysis_total(self) -> int:
        return self._analysis_total

    def _set_analysis_total(self, value: int):
        if self._analysis_total != value:
            self._analysis_total = value
            self.analysisTotalChanged.emit()

    analysisTotal = Property(int, _get_analysis_total, _set_analysis_total,
                             notify=analysisTotalChanged)

    # importCurrent
    def _get_import_current(self) -> int:
        return self._import_current

    def _set_import_current(self, value: int):
        if self._import_current != value:
            self._import_current = value
            self.importCurrentChanged.emit()

    importCurrent = Property(int, _get_import_current, _set_import_current, notify=importCurrentChanged)

    # importTotal
    def _get_import_total(self) -> int:
        return self._import_total

    def _set_import_total(self, value: int):
        if self._import_total != value:
            self._import_total = value
            self.importTotalChanged.emit()

    importTotal = Property(int, _get_import_total, _set_import_total, notify=importTotalChanged)

    # importMessage
    def _get_import_message(self) -> str:
        return self._import_message

    def _set_import_message(self, value: str):
        if self._import_message != value:
            self._import_message = value
            self.importMessageChanged.emit()

    importMessage = Property(str, _get_import_message, _set_import_message, notify=importMessageChanged)

    # aiProgress
    def _get_ai_progress(self) -> str:
        return self._ai_progress

    def _set_ai_progress(self, value: str):
        if self._ai_progress != value:
            self._ai_progress = value
            self.aiProgressChanged.emit()

    aiProgress = Property(str, _get_ai_progress, _set_ai_progress, notify=aiProgressChanged)

    # isExporting
    def _get_is_exporting(self) -> bool:
        return self._is_exporting

    def _set_is_exporting(self, value: bool):
        if self._is_exporting != value:
            self._is_exporting = value
            self.isExportingChanged.emit()

    isExporting = Property(bool, _get_is_exporting, _set_is_exporting, notify=isExportingChanged)

    # appVersion (read-only)
    def _get_app_version(self) -> str:
        from PySide6.QtWidgets import QApplication
        return QApplication.instance().applicationVersion() if QApplication.instance() else "4.9.4"

    appVersion = Property(str, _get_app_version, constant=True)

    # V4.9: errorLogCount (read-only)
    def _get_error_log_count(self) -> int:
        return self._error_log_count

    errorLogCount = Property(int, _get_error_log_count, notify=errorLogChanged)

    # ── Public Slots (QML callable) ──────────────────────

    @Slot(str, result="QVariantList")
    def listProjects(self):
        """返回项目列表 [{id, name, cadCount, pdfCount, hasAnalysis, updatedAt}]"""
        projects = self._pm.list_projects()
        result = []
        for p in projects:
            result.append({
                "id": p.id,
                "name": p.name,
                "cadCount": p.cad_count,
                "pdfCount": p.pdf_count,
                "totalFiles": p.total_files,
                "hasAnalysis": p.has_analysis,
                "updatedAt": p.updated_at,
            })
        return result

    @Slot(str, result=str)
    def createProject(self, name: str = "") -> str:
        """创建新项目，返回 project_id"""
        proj = self._pm.create_project(name)
        self.projectsChanged.emit()
        logger.info("Created project: %s (%s)", proj.id, proj.name)
        return proj.id

    @Slot(str)
    def deleteProject(self, project_id: str):
        """删除项目"""
        was_current = self._current_project_id == project_id
        self._pm.delete_project(project_id)
        if was_current:
            self._set_current_project_id("")
        self.projectDeleted.emit(project_id)
        self.projectsChanged.emit()
        logger.info("Deleted project: %s", project_id)

    @Slot(str, str)
    def renameProject(self, project_id: str, name: str):
        """重命名项目"""
        self._pm.update_project_name(project_id, name)
        if self._current_project_id == project_id:
            self._set_current_project_name(name)
        self.projectsChanged.emit()

    @Slot(str, int, str)
    def replaceFile(self, project_id: str, file_id: int, old_file_path: str = ""):
        """V4.9: 替换项目中的文件 — 删除旧文件，选择新文件导入并自动解析（支持所有格式）"""
        if not project_id or not file_id:
            logger.warning("replaceFile: missing project_id or file_id")
            return

        # 1. Open file dialog for new file
        filters = "所有支持格式 (*.dwg *.dxf *.pdf *.docx *.xlsx);;CAD 图纸 (*.dwg *.dxf);;PDF 文档 (*.pdf);;Word 文档 (*.docx);;Excel 表格 (*.xlsx)"
        paths, _ = QFileDialog.getOpenFileNames(
            None,
            "选择替换文件",
            self._config.last_project_dir or "",
            filters
        )
        if not paths:
            return

        new_path = paths[0]
        self._config.last_project_dir = str(Path(new_path).parent)

        # 2. Determine file type (V4.9: 支持 word/excel)
        ext = Path(new_path).suffix.lower()
        if ext in (".dwg", ".dxf"):
            file_type = "cad"
        elif ext == ".pdf":
            file_type = "pdf"
        elif ext == ".docx":
            file_type = "word"
        elif ext == ".xlsx":
            file_type = "excel"
        else:
            file_type = "pdf"

    @Slot(str, int)
    def deleteFile(self, project_id: str, file_id: int):
        """V4.9.4: 删除单个文件（从右键菜单调用）"""
        if not project_id or not file_id:
            return
        try:
            self._pm.db.delete_file(file_id)
            self.projectsChanged.emit()
            logger.info("Deleted file %d from project %s", file_id, project_id)
        except Exception as e:
            logger.error("deleteFile failed: %s", e)

        # 3. Delete old file (CASCADE handles text_entities, etc.)
        try:
            self._pm.db.delete_file(file_id)
        except Exception as e:
            logger.error("replaceFile: failed to delete old file %d: %s", file_id, e)

        # 4. Add new file to project
        self._pm.add_files(project_id, [new_path], file_type)

        # 5. Trigger incremental import for the new file
        self.importFiles(project_id, [new_path])

        # 6. Notify UI to refresh
        self.projectsChanged.emit()
        logger.info("Replaced file (id=%d) with %s in project %s", file_id, new_path, project_id)

    @Slot(str, result="QVariantList")
    def pickAndImportFiles(self, project_id: str) -> list:
        """V4.9: 打开文件对话框选择文件并导入（自动识别所有支持格式）。返回选中的文件路径列表。"""
        if not project_id:
            return []

        filters = "所有支持格式 (*.dwg *.dxf *.pdf *.docx *.xlsx);;CAD 图纸 (*.dwg *.dxf);;PDF 文档 (*.pdf);;Word 文档 (*.docx);;Excel 表格 (*.xlsx)"

        paths, _ = QFileDialog.getOpenFileNames(
            None,
            "选择要导入的文件",
            self._config.last_project_dir or "",
            filters
        )

        if not paths:
            return []

        # 更新最近目录
        self._config.last_project_dir = str(Path(paths[0]).parent)

        # V4.9: 根据后缀自动分类
        cad_files = [p for p in paths if Path(p).suffix.lower() in (".dwg", ".dxf")]
        pdf_files = [p for p in paths if Path(p).suffix.lower() == ".pdf"]
        word_files = [p for p in paths if Path(p).suffix.lower() == ".docx"]
        excel_files = [p for p in paths if Path(p).suffix.lower() == ".xlsx"]

        all_paths = cad_files + pdf_files + word_files + excel_files
        if all_paths:
            # 添加到项目（按类型分别调用 add_files）
            if cad_files:
                self._pm.add_files(project_id, cad_files, "cad")
            if pdf_files:
                self._pm.add_files(project_id, pdf_files, "pdf")
            if word_files:
                self._pm.add_files(project_id, word_files, "word")
            if excel_files:
                self._pm.add_files(project_id, excel_files, "excel")
            self.importFiles(project_id, all_paths)

        return all_paths

    @Slot(str, "QVariantList")
    def importFiles(self, project_id: str, file_paths: list):
        """V4.9: 导入文件到项目。自动根据后缀识别类型 (cad/pdf/word/excel)。"""
        if self._is_importing:
            logger.warning("Import already in progress, ignoring")
            return

        # V4.9: 根据后缀自动分类
        cad_files, pdf_files, word_files, excel_files = [], [], [], []
        for fp in file_paths:
            ext = Path(fp).suffix.lower()
            if ext in (".dwg", ".dxf"):
                cad_files.append(fp)
            elif ext == ".pdf":
                pdf_files.append(fp)
            elif ext == ".docx":
                word_files.append(fp)
            elif ext == ".xlsx":
                excel_files.append(fp)

        if not any([cad_files, pdf_files, word_files, excel_files]):
            logger.warning("No valid files to import")
            return

        # V4.9: 构建 file_groups dict 传给 FileImportThread
        file_groups = {"cad": cad_files, "pdf": pdf_files, "word": word_files, "excel": excel_files}

        self._cad_results = []
        self._pdf_results = []

        # 启动导入线程
        self._import_thread = FileImportThread(file_groups, project_id, db=self._pm.db, skip_parsed=True)
        self._import_thread.file_started.connect(self._on_file_started)
        self._import_thread.progress.connect(self._on_import_progress)
        self._import_thread.file_done.connect(self._on_file_done)
        self._import_thread.error.connect(self._on_import_file_error)
        self._import_thread.queue_finished.connect(lambda: self._on_import_finished(project_id))
        self._import_thread.start()

        import time
        self._import_start_time = time.time()
        self._set_is_importing(True)
        self._set_import_current(0)
        self._set_import_total(len(cad_files) + len(pdf_files) + len(word_files) + len(excel_files))
        self._set_import_message("准备导入...")
        total = sum(len(files) for files in file_groups.values())
        logger.info("Started import: %d CAD + %d PDF + %d Word + %d Excel files",
                    len(cad_files), len(pdf_files), len(word_files), len(excel_files))

    @Slot()
    def pauseImport(self):
        """暂停导入"""
        if self._import_thread:
            self._import_thread.pause()
            self._set_import_message("已暂停")
            logger.info("Import paused")

    @Slot()
    def resumeImport(self):
        """继续导入"""
        if self._import_thread:
            self._import_thread.resume()
            self._set_import_message("继续导入...")
            logger.info("Import resumed")

    @Slot()
    def cancelImport(self):
        """取消导入（不阻塞 UI，线程后台自毁）"""
        if self._import_thread:
            self._import_thread.cancel()
            try:
                self._import_thread.finished.disconnect()
            except Exception:
                pass
            try:
                self._import_thread.error.disconnect()
            except Exception:
                pass
            self._import_thread = None
        self._set_is_importing(False)
        self._set_import_message("已取消")
        logger.info("Import cancelled")

    # ── V4.9.2: Conversion (Phase 1) ──────────────────────

    @Slot(str)
    def startConversion(self, project_id: str):
        """V4.9.3: Phase 0 (ProfileThread) → Phase 1 (StrategyConversionThread)"""
        # 立即给用户反馈
        logger.info("startConversion called for project %s", project_id)
        if not project_id:
            self._add_error_log("转换错误", "请先在项目列表中右键选择一个项目")
            return

        try:
            # 清理上次可能残留的线程状态（不断开信号，cancel 后立即置 None）
            if hasattr(self, '_profile_thread') and self._profile_thread:
                self._profile_thread.cancel()
                try:
                    self._profile_thread.finished.disconnect()
                except Exception:
                    pass
                self._profile_thread = None
            if hasattr(self, '_conversion_thread') and self._conversion_thread:
                self._conversion_thread.cancel()
                try:
                    self._conversion_thread.finished.disconnect()
                except Exception:
                    pass
                self._conversion_thread = None

            if not self._pm or not self._pm.db:
                logger.error("startConversion: DB not available")
                self._set_ai_progress("❌ 数据库未就绪，请重启应用")
                self._add_error_log("系统错误", "数据库未就绪，请重启应用")
                return

            files = self._pm.db.get_files(project_id)
            logger.info("startConversion: %d files in project %s", len(files), project_id)

            to_convert = [f for f in files if f.get("file_type") in ("cad", "pdf")]
            if not to_convert:
                word_excel_count = len([f for f in files if f.get('file_type') in ('word', 'excel')])
                msg = f"没有需要转换的文件（{len(files)} 个文件中 {word_excel_count} 个为 Word/Excel，可直接 AI 分析）"
                self._set_is_converting(True)  # 短暂显示进度条让用户看到消息
                self._set_ai_progress(msg)
                self._add_error_log("转换提示", msg)
                # 2秒后自动隐藏
                from PySide6.QtCore import QTimer
                QTimer.singleShot(3000, lambda: self._set_is_converting(False))
                return

            # Phase 0: 预分析（鉴定文件类型 → 决定转换策略）
            self._set_ai_progress("Phase 0: 预分析文件类型...")
            self._set_conversion_progress(0, len(to_convert), "0%")
            self._profile_thread = ProfileThread(project_id, self._pm.db, to_convert)
            self._profile_thread.progress.connect(self._on_conversion_progress)
            self._profile_thread.finished.connect(
                lambda results: self._on_profile_finished(project_id, to_convert)
            )
            self._profile_thread.error.connect(lambda e: self._add_error_log("预分析错误", e))
            self._profile_thread.start()
            self._set_is_converting(True)
            logger.info("Started profiling for project %s: %d files", project_id, len(to_convert))

        except Exception as e:
            import traceback
            logger.exception("startConversion crashed")
            self._set_ai_progress(f"❌ 启动转换失败: {str(e)[:100]}")
            self._add_error_log("系统错误", f"启动转换失败: {str(e)[:200]}")
            self._set_is_converting(False)

    def _on_profile_finished(self, project_id: str, files_to_convert: list):
        """V4.9.3: Phase 0 完成 → 启动 Phase 1 StrategyConversionThread"""
        self._set_ai_progress("Phase 1: 分策略转换...")

        self._conversion_thread = StrategyConversionThread(project_id, self._pm.db, files_to_convert)
        self._conversion_thread.progress.connect(self._on_conversion_progress)
        self._conversion_thread.file_progress.connect(self._on_conversion_file_progress)
        self._conversion_thread.conversion_done.connect(self._on_conversion_file_done)
        self._conversion_thread.conversion_error.connect(self._on_conversion_file_error)
        self._conversion_thread.finished.connect(lambda: self._on_conversion_finished(project_id))
        self._conversion_thread.start()
        logger.info("Started strategy conversion for project %s: %d files", project_id, len(files_to_convert))

    @Slot()
    def cancelConversion(self):
        """取消转换 — 仅设置取消标志，线程自行安全退出，信号保持连接"""
        if hasattr(self, '_profile_thread') and self._profile_thread:
            self._profile_thread.cancel()
            logger.info("ProfileThread cancel requested")
        if hasattr(self, '_conversion_thread') and self._conversion_thread:
            self._conversion_thread.cancel()
            logger.info("StrategyConversionThread cancel requested")
        self._set_is_converting(False)
        self._set_ai_progress("转换已取消")
        logger.info("Conversion cancel requested")

    def _on_conversion_progress(self, msg: str):
        self._set_ai_progress(msg)

    def _on_conversion_file_progress(self, current: int, total: int, detail: str):
        self._set_conversion_progress(current, total, detail)

    def _on_conversion_file_done(self, file_id: int, png_path: str):
        """V4.9.3: Store converted PNG path + conversion_status=done in DB.
        V4.9.4: 空路径 = 文字型PDF，标记为 text_only 跳过 Vision。
        """
        if self._pm.db:
            try:
                if png_path:
                    self._pm.db.set_setting(f"converted_png_{file_id}", png_path)
                else:
                    # 文字型PDF / Word / Excel — 无需Vision
                    self._pm.db.set_setting(f"conversion_type_{file_id}", "text_only")
                self._pm.db.set_conversion_status(file_id, "done")
            except Exception as e:
                logger.warning("Failed to store PNG path for file %d: %s", file_id, e)

    def _on_conversion_file_error(self, file_id: int, error_msg: str):
        self._add_error_log("转换错误", f"文件 #{file_id}: {error_msg}")
        if self._pm.db:
            try:
                self._pm.db.set_conversion_status(file_id, "error")
            except Exception:
                pass

    def _on_conversion_finished(self, project_id: str):
        self._set_is_converting(False)
        self._set_ai_progress("✅ 转换完成，可以开始 AI 分析")
        try:
            self._pm.db.set_setting(f"conversion_done_{project_id}", "1")
            # Word/Excel 文件无需转换，直接标记完成
            files = self._pm.db.get_files(project_id)
            for f in files:
                if f.get("file_type") in ("word", "excel"):
                    self._pm.db.set_conversion_status(f["id"], "done")
        except Exception:
            pass
        self.conversionFinished.emit(project_id)
        logger.info("Conversion finished for project %s", project_id)

    # ── AI Analysis (Phase 2) ─────────────────────────────

    @Slot(str)
    def startAnalysis(self, project_id: str):
        """Start AI analysis (V4.9.3: phase 2 — requires conversion to be done)"""
        # 清理上次可能残留的线程状态（已取消但仍在后台运行的线程）
        if self._ai_thread:
            if not self._ai_thread.isFinished():
                logger.warning("Analysis thread still running, disconnecting and replacing")
                try:
                    self._ai_thread.finished.disconnect()
                except Exception:
                    pass
                try:
                    self._ai_thread.error.disconnect()
                except Exception:
                    pass
                try:
                    self._ai_thread.paused.disconnect()
                except Exception:
                    pass
            self._ai_thread = None
        self._set_is_analyzing(False)
        self._set_is_analysis_paused(False)

        # V4.8: 离线检测
        ds_key = self._config.api_key
        if not ds_key:
            self.analysisError.emit(project_id, "请先配置 DeepSeek API Key")
            return

        import requests
        try:
            resp = requests.head("https://api.deepseek.com", timeout=5)
        except requests.exceptions.ConnectionError:
            self.analysisError.emit(project_id, "当前处于离线状态，无法启动 AI 分析。\n您可以查看和编辑已有项目的送检计划。")
            return
        except Exception:
            pass  # 其他错误不阻塞，让后续 API 调用自己处理

        qwen_key = self._config.qwen_api_key
        files = self._pm.db.get_files(project_id) if self._pm.db else []
        if not files:
            self.analysisError.emit(project_id, "没有已导入的文件。请先导入 CAD/PDF 文件。")
            return

        # V4.8: 检查断点
        checkpoint = self._pm.db.get_checkpoint(project_id) if self._pm.db else None
        if checkpoint:
            logger.info("Found checkpoint for project %s: step=%s", project_id, checkpoint.get("step", "?"))

        self._ai_thread = AIAnalysisThread(project_id, self._pm.db, ds_key, qwen_key, self._config)
        self._ai_thread.progress.connect(self._set_ai_progress)
        self._ai_thread.finished.connect(lambda result: self._on_analysis_finished(project_id, result))
        self._ai_thread.error.connect(lambda err: self._on_analysis_error(project_id, err))
        self._ai_thread.paused.connect(self._set_is_analysis_paused)
        self._ai_thread.start()

        self._set_is_analyzing(True)
        self._set_is_analysis_paused(False)
        # 延迟设置初始消息，让线程第一条进度消息先显示
        unparsed = self._pm.db.get_unparsed_files(project_id) if self._pm.db else []
        if unparsed:
            self._set_ai_progress(f"正在解析 {len(unparsed)} 个文件...")
        else:
            self._set_ai_progress("正在准备 AI 分析..." + ("（断点恢复）" if checkpoint else ""))
        logger.info("Started AI analysis for project: %s", project_id)

    @Slot()
    def pauseAnalysis(self):
        """暂停 AI 分析"""
        if self._ai_thread and self._is_analyzing:
            self._ai_thread.pause()
            self._set_ai_progress("分析已暂停")
            logger.info("Analysis paused")

    @Slot()
    def resumeAnalysis(self):
        """继续 AI 分析"""
        if self._ai_thread and self._is_analyzing:
            self._ai_thread.resume()
            self._set_ai_progress("继续分析...")
            logger.info("Analysis resumed")

    @Slot()
    def cancelAnalysis(self):
        """取消 AI 分析（不断开信号，立即重置状态，线程后台自毁）"""
        if self._ai_thread:
            self._ai_thread.cancel()
            # 断开旧线程信号，防止回调污染新分析
            try:
                self._ai_thread.finished.disconnect()
            except Exception:
                pass
            try:
                self._ai_thread.error.disconnect()
            except Exception:
                pass
            try:
                self._ai_thread.paused.disconnect()
            except Exception:
                pass
            self._ai_thread = None
        self._set_is_analyzing(False)
        self._set_is_analysis_paused(False)
        self._set_ai_progress("分析已取消")
        logger.info("Analysis cancelled")

    @Slot(str, str, "QVariantList")
    def exportExcel(self, project_id: str, output_path: str = "",
                    selected_sections: list = None):
        """异步导出 Excel 送检计划（V4.5.5: 支持按选中路段过滤）"""
        if self._is_exporting:
            logger.warning("Export already in progress, ignoring")
            return

        proj = self._pm.get_project(project_id)
        if not proj:
            self.exportError.emit("项目不存在")
            return

        if not proj.analysis_result:
            self.exportError.emit("请先完成 AI 分析再导出")
            return

        result = proj.analysis_result
        project_info = result.get("project_info", {})
        testing_plan = result.get("testing_plan", [])
        contract_info = result.get("contract_info")
        key_notes = result.get("key_notes", [])
        sections = result.get("sections", [])
        construction_layers = result.get("construction_layers", [])  # V4.7

        # V4.5.5: 按选中路段过滤
        if selected_sections and len(selected_sections) > 0:
            selected_set = set(selected_sections)
            testing_plan = [
                item for item in testing_plan
                if item.get("section", "") in selected_set
            ]
            sections = [
                s for s in sections
                if s.get("section", "") in selected_set
            ]

        if not output_path:
            # 弹出保存文件对话框让用户选择路径
            default_name = f"{proj.name}_送检计划.xlsx" if proj.name else "送检计划.xlsx"
            default_path = os.path.join(self._config.output_dir, default_name)
            output_path, _ = QFileDialog.getSaveFileName(
                None, "导出送检计划", default_path,
                "Excel 文件 (*.xlsx);;所有文件 (*)"
            )
            if not output_path:  # 用户取消
                return

        self._set_is_exporting(True)
        self._export_thread = ExportThread(
            output_path, project_info, testing_plan,
            contract_info, key_notes, proj.name, sections, construction_layers
        )
        self._export_thread.finished.connect(self._on_export_finished)
        self._export_thread.error.connect(self._on_export_error)
        self._export_thread.start()
        logger.info("Started async export for project: %s", project_id)

    def _on_export_finished(self, output_path: str):
        self._set_is_exporting(False)
        self.exportFinished.emit(output_path)
        logger.info("Exported to: %s", output_path)

    def _on_export_error(self, error_msg: str):
        self._set_is_exporting(False)
        self.exportError.emit(error_msg)
        logger.error("Export failed: %s", error_msg)

    @Slot(str, str)
    def configureApiKey(self, ds_key: str, qwen_key: str):
        """配置 API 密钥"""
        if ds_key:
            self._config.api_key = ds_key
        if qwen_key:
            self._config.qwen_api_key = qwen_key
        logger.info("API keys updated")

    @Slot(result="QVariantMap")
    def getApiKeys(self) -> dict:
        """获取已保存的 API 密钥（脱敏显示）"""
        ds = self._config.api_key
        qwen = self._config.qwen_api_key
        return {
            "dsKey": self._mask_key(ds),
            "qwenKey": self._mask_key(qwen),
            "hasDsKey": bool(ds),
            "hasQwenKey": bool(qwen),
        }

    @Slot(str, result="str")
    def getPlanDrawingImage(self, project_id: str) -> str:
        """获取项目的总体平面图 PNG 路径"""
        if not project_id or not self._pm.db:
            return ""
        path = self._pm.db.get_setting("plan_drawing_%s" % project_id)
        # 验证文件存在
        if path:
            import os
            if not os.path.exists(path):
                return ""
        return path or ""

    @Slot(str, str, result="QVariantList")
    def getConstructionLayers(self, project_id: str, section_name: str = "") -> list:
        """V4.7: 获取指定项目/路段的施工层数据（供 ProcessFlow QML 使用）"""
        if not project_id or not self._pm.db:
            return []
        try:
            layers = self._pm.db.get_construction_layers(project_id, section_name)
            return layers
        except Exception as e:
            logger.error("getConstructionLayers failed: %s", e)
            return []

    @Slot(str, str, result="QVariantMap")
    def testConnection(self, ds_key: str, qwen_key: str):
        """V4.9.4: 异步测试 DeepSeek 和 Qwen-VL API 连接（不阻塞 UI）"""
        ds_test_key = ds_key.strip() if ds_key.strip() else self._config.api_key
        qwen_test_key = qwen_key.strip() if qwen_key.strip() else self._config.qwen_api_key

        self._conn_test_thread = ConnectionTestThread(ds_test_key, qwen_test_key)
        self._conn_test_thread.finished.connect(self._on_connection_test_done)
        self._conn_test_thread.start()
        logger.info("Connection test started (async)")

    def _on_connection_test_done(self, result: dict):
        """V4.9.4: 连接测试完成 → 转发结果到 QML"""
        logger.info(
            "Connection test: DS=%s Qwen=%s",
            "OK" if result["ds_ok"] else result["ds_msg"],
            "OK" if result["qwen_ok"] else result["qwen_msg"],
        )
        self.connectionTestFinished.emit(result)

    @Slot(str, result="QVariantMap")
    def getProjectFiles(self, project_id: str) -> dict:
        """获取项目文件列表 {cadFiles: [...], pdfFiles: [...]}"""
        if not project_id or not self._pm.db:
            return {"cadFiles": [], "pdfFiles": []}

        files = self._pm.db.get_files(project_id)
        cad_files = []
        pdf_files = []
        for f in files:
            entry = {
                "id": f.get("id"),
                "fileName": f.get("file_name", ""),
                "filePath": f.get("file_path", ""),
                "discipline": f.get("discipline", "未知"),
                "fileSize": self._format_size(f.get("file_size", 0)),
                "parseStatus": f.get("parse_status", "pending"),
                "description": f.get("description", ""),
            }
            if f.get("file_type") == "cad":
                cad_files.append(entry)
            else:
                pdf_files.append(entry)

        return {"cadFiles": cad_files, "pdfFiles": pdf_files}

    @Slot(str, result="QVariantList")
    def getRoadSections(self, project_id: str) -> list:
        """获取路段列表"""
        return self._pm.get_road_sections(project_id)

    @Slot(str, result=str)
    def getExtractedText(self, project_id: str) -> str:
        """获取项目的聚合文本内容（预览用）"""
        if not project_id or not self._pm.db:
            return ""
        text = self._pm.db.get_extracted_text(project_id)
        return text[:50000] if text else ""

    @Slot(str, result="QVariantMap")
    def getAnalysisResult(self, project_id: str) -> dict:
        """获取分析结果"""
        proj = self._pm.get_project(project_id)
        if proj and proj.analysis_result:
            return proj.analysis_result
        return {}

    @Slot(result="QVariantList")
    def getTestingPlanItems(self, project_id: str = "") -> list:
        """获取送检计划明细（16列）"""
        if not project_id or not self._pm.db:
            return []
        return self._pm.db.get_testing_plan_items(project_id)

    # ── Internal Handlers ────────────────────────────────

    def _on_import_progress(self, current: int, total: int, msg: str):
        self._set_import_current(current)
        self._set_import_total(total)
        self._set_import_message(msg)

    def _on_file_started(self, file_path: str, project_id: str):
        """Update file parse_status to 'parsing' when import begins processing a file."""
        if project_id and self._pm.db:
            try:
                files = self._pm.db.get_files(project_id)
                for f in files:
                    if f.get("file_path") == file_path:
                        self._pm.db.update_file_parse_status(f["id"], "parsing", "", "")
                        break
            except Exception:
                pass

    def _generate_thumbnail(self, file_path: str, file_type: str, thumb_dir: Path) -> str:
        """Generate a thumbnail image for a DWG or PDF file. Returns path or empty string."""
        try:
            thumb_dir.mkdir(parents=True, exist_ok=True)
            fname = Path(file_path).stem.replace(" ", "_").replace(".", "_")
            thumb_path = str(thumb_dir / f"{fname}_thumb.png")

            if file_type == "cad":
                images = convert_dwg_to_png(file_path)
                if images:
                    import shutil
                    shutil.copy2(images[0], thumb_path)
                    return thumb_path
            else:
                import tempfile
                tmpd = tempfile.mkdtemp(prefix="thumb_")
                images = extract_page_images(file_path, tmpd, max_pages=1)
                if images:
                    import shutil
                    shutil.copy2(images[0], thumb_path)
                    return thumb_path
        except Exception as e:
            logger.debug("Thumbnail generation failed for %s: %s", file_path, e)
        return ""

    def _on_file_done(self, file_path: str, project_id: str, result):
        if result is not None:
            # Store parsed entities to SQLite
            # V4.9.4: 使用信号中传递的 project_id（FileImportThread 初始化时固定），
            # 避免回退到可能已变更的 currentProjectId（竞态）
            if not project_id:
                logger.warning("_on_file_done: project_id is empty, skipping storage for %s", file_path)
                return
            if self._pm.db:
                try:
                    from ..engine.dwg_parser import DWGContent
                    file_name = Path(file_path).name
                    # V4.9.4: 用写连接 _conn 查 file_id（避开 _read_conn 的 WAL 快照问题）
                    row = self._pm.db._conn.execute(
                        "SELECT id FROM files WHERE file_path=? AND project_id=?",
                        (file_path, project_id)
                    ).fetchone()
                    file_id = row[0] if row else None

                    if not file_id:
                        logger.warning("_on_file_done: file_id not found for %s in project %s", file_path, project_id)

                    if file_id:
                        is_cad = isinstance(result, DWGContent)
                        # V4.9: 从后缀确定 word/excel
                        ext = Path(file_path).suffix.lower()
                        if is_cad:
                            # Store CAD entities
                            entities = []
                            for te in result.text_entities:
                                entities.append({
                                    "text": te.text if hasattr(te, 'text') else str(te),
                                    "layer": getattr(te, 'layer', ''),
                                    "pos_x": getattr(te, 'pos_x', 0),
                                    "pos_y": getattr(te, 'pos_y', 0),
                                })
                            self._pm.db.store_text_entities(file_id, entities)
                            self._pm.db.update_file_parse_status(
                                file_id, "done", result.discipline, result.description
                            )
                        elif isinstance(result, dict) and "text" in result:
                            # V4.9: PDF / Word / Excel result
                            if ext == ".docx":
                                discipline = "Word"
                            elif ext == ".xlsx":
                                discipline = "Excel"
                            else:
                                discipline = "PDF"
                            description = ""
                            guide_text = result.get("text", "")
                            # V4.9.3: 检测送检指南（PDF + Word）
                            if ext in (".pdf", ".docx") and _detect_testing_guide(file_path, guide_text):
                                discipline = "送检指南"
                                description = "TESTING_GUIDE"
                                logger.info("Detected testing guide: %s", file_name)
                            # V4.9: Word/Excel 文本先存入 text_entities
                            lines = guide_text.split("\n")
                            entities = [{"text": l, "layer": discipline, "pos_x": 0, "pos_y": 0} for l in lines[:20000]]  # V4.9.3: 5000→20000
                            self._pm.db.store_text_entities(file_id, entities)
                            self._pm.db.update_file_parse_status(
                                file_id, "done", discipline, description
                            )
                            # V4.9.4: Word/Excel 无需转换，导入后直接标记转换完成
                            if ext in (".docx", ".xlsx"):
                                self._pm.db.set_conversion_status(file_id, "done")

                        # Generate thumbnail (non-blocking: quick first-page only)
                        thumb_dir = Path(self._config.config_dir) / "thumbnails"
                        ftype = "cad" if is_cad else ("word" if ext == ".docx" else ("excel" if ext == ".xlsx" else "pdf"))
                        thumb_path = self._generate_thumbnail(file_path, ftype, thumb_dir)
                        if thumb_path:
                            self._pm.db.update_file_thumbnail(file_id, thumb_path)
                except Exception as e:
                    logger.warning("Failed to store parse result for %s: %s", file_path, e)

    def _on_import_file_error(self, msg: str):
        logger.warning("Import file error: %s", msg)
        self._add_error_log("导入错误", msg)

    def _on_import_finished(self, project_id: str):
        import time
        from PySide6.QtCore import QTimer
        # V4.9.4: 立即通知 QML 刷新（不等 QTimer 延迟），确保文件列表和状态即时更新
        self.importFinished.emit(project_id)
        self.projectsChanged.emit()
        elapsed = time.time() - self._import_start_time if hasattr(self, '_import_start_time') else 0
        MIN_DISPLAY_MS = 1500  # 最小显示时间，避免小文件一闪而过
        if elapsed * 1000 < MIN_DISPLAY_MS:
            delay = int(MIN_DISPLAY_MS - elapsed * 1000)
            QTimer.singleShot(delay, lambda: self._finish_import(project_id))
        else:
            self._finish_import(project_id)

    def _finish_import(self, project_id: str):
        """V4.9.4: 导入完成后的清理工作 + 兜底解析"""
        from PySide6.QtCore import QTimer
        self._set_is_importing(False)
        self._set_import_message("导入完成")
        # 1.5s 后清空进度消息，避免进度条残留
        QTimer.singleShot(1500, lambda: self._set_import_message(""))
        # V4.9.4: 兜底解析 — 确保所有 pending 文件最终被解析
        QTimer.singleShot(100, lambda: self._ensure_files_parsed(project_id))
        # Auto-detect project name if still default
        proj = self._pm.get_project(project_id)
        if proj and (not proj.name or proj.name.startswith("新项目")):
            text = ""
            if self._pm.db:
                text = self._pm.db.get_extracted_text(project_id)
            if text:
                detected = self._pm.auto_detect_name(text)
                if detected and detected != proj.name:
                    self._pm.update_project_name(project_id, detected)
                    self._set_current_project_name(detected)
        self.importFinished.emit(project_id)
        self.projectsChanged.emit()

    def _ensure_files_parsed(self, project_id: str):
        """V4.9.4: 兜底 — 后台解析 pending 文件（仅轻量文件，跳过重型CAD），完成后刷新 UI"""
        if not self._pm.db:
            return
        files = self._pm.db.get_files(project_id)
        # 只处理轻量文件 (PDF/Word/Excel)，CAD 由 FileImportThread._store_parse_result 直接处理
        pending = [f for f in files
                   if f.get("parse_status") != "done"
                   and f.get("file_type") in ("pdf", "word", "excel")]
        if not pending:
            return
        logger.info("Fallback parsing %d pending lightweight file(s)", len(pending))
        from threading import Thread
        def _parse_all():
            parsed = 0
            for f in pending:
                fpath = f.get("file_path", "")
                ftype = f.get("file_type", "pdf")
                if not fpath or not os.path.exists(fpath):
                    continue
                try:
                    if ftype == "pdf":
                        result = extract_pdf_content(fpath)
                    elif ftype == "word":
                        from ..engine.word_parser import extract_word_content
                        result = extract_word_content(fpath)
                    elif ftype == "excel":
                        from ..engine.excel_parser import extract_excel_content
                        result = extract_excel_content(fpath)
                    else:
                        continue
                    if result is not None:
                        self._on_file_done(fpath, project_id, result)
                        parsed += 1
                except Exception as e:
                    logger.warning("Fallback parse failed for %s: %s", fpath, e)
            if parsed > 0:
                logger.info("Fallback parsed %d files, refreshing UI", parsed)
                self.projectsChanged.emit()
        Thread(target=_parse_all, daemon=True).start()

    def _on_analysis_finished(self, project_id: str, result: dict):
        if not self._ai_thread:  # 旧线程回调，忽略
            return
        self._set_is_analyzing(False)
        self._set_is_analysis_paused(False)
        self._set_ai_progress("分析完成")
        # Save result
        self._pm.set_analysis_result(project_id, result)
        self.analysisFinished.emit(project_id, result)
        self.projectsChanged.emit()

    def _on_analysis_error(self, project_id: str, error_msg: str):
        if not self._ai_thread:  # 旧线程回调，忽略
            return
        self._set_is_analyzing(False)
        self._set_is_analysis_paused(False)
        self._set_ai_progress(f"分析失败: {error_msg}")
        self._add_error_log("分析错误", error_msg)
        self.analysisError.emit(project_id, error_msg)

    # ── Helpers ──────────────────────────────────────────

    def _add_error_log(self, level: str, message: str):
        """V4.9: 追加错误日志条目"""
        from datetime import datetime
        entry = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "level": level,
            "message": message[:500],  # 截断过长消息
        }
        self._error_log.append(entry)
        # 保留最近 100 条
        if len(self._error_log) > 100:
            self._error_log = self._error_log[-100:]
        self._error_log_count += 1
        self.errorLogChanged.emit()

    # V4.9.3: errorLogList Property — QML 直接绑定，自动刷新
    def _get_error_log_list(self) -> list:
        return list(self._error_log)

    errorLogList = Property("QVariantList", _get_error_log_list, notify=errorLogChanged)

    @Slot(result="QVariantList")
    def getErrorLog(self) -> list:
        """V4.9: 返回错误日志列表 (兼容旧调用)"""
        return list(self._error_log)

    @Slot()
    def clearErrorLog(self):
        """V4.9: 清空错误日志"""
        self._error_log.clear()
        self._error_log_count = 0
        self.errorLogChanged.emit()

    @Slot(result="QString")
    def getAboutInfo(self) -> str:
        """V4.9.4: 返回关于信息（当前版本更新内容）"""
        from PySide6.QtWidgets import QApplication
        ver = QApplication.instance().applicationVersion() if QApplication.instance() else "4.9.4"
        return (
            f"工程材料送检分析系统 V{ver}\n\n"
            "本版更新 (2026-06-10):\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "【智能转换管线】\n"
            "• Phase 0 文件预分析：PDF 逐页分类(text/drawing/scan/blank) + CAD 复杂度估算\n"
            "• Phase 1 分策略转换：按策略自动分流(standard/reduced/cairo/text_only/ocr)\n"
            "• 图片预处理：VL API 前空白过滤 + 自适应压缩 + JPEG 输出(缩小 90%)\n"
            "• OCR 集成：Tesseract 5.5 + 中文包，扫描 PDF 文字提取从 0 → 可用\n"
            "• CAD 渲染超时保护：120s 自动跳过 + 错误日志记录\n\n"
            "【性能优化】\n"
            "• PDF 文字提取：移除 100 页硬限制 → 全量分策略\n"
            "• pdfplumber 表格提取：限制 30 页(102s → 19s)\n"
            "• 送检指南(168页)转换：150s → 56s (2.7x)\n\n"
            "【Bug 修复】\n"
            "• Qwen-VL: 新增 2 次重试 + 指数退避(对齐 DeepSeek)\n"
            "• AI 缓存: 完整 prompt hash(修复前 2000 字符截断误命中)\n"
            "• 文字实体: 5000→20000 行(大型 PDF 不再截断)\n"
            "• 送检指南检测: 扩展到 Word 格式\n"
            "• 取消转换后无法重启(Phase 0 未清理)\n"
            "• 开始分析无响应(_is_analyzing 状态残留)\n"
            "• 进度条: indeterminate → 百分比显示\n"
            "• CAD 转换无反馈: 增加文件大小 + 分步进度\n\n"
            "技术栈: Python 3.12 + PySide6 + DeepSeek V4 + Qwen-VL + SQLite + Tesseract"
        )

    @staticmethod
    def _mask_key(key: str) -> str:
        if not key or len(key) < 8:
            return key or ""
        return key[:4] + "*" * (len(key) - 8) + key[-4:]

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.1f} MB"


# 全局单例
_instance = None


def get_app_state() -> AppState:
    """获取 AppState 全局单例"""
    global _instance
    if _instance is None:
        _instance = AppState()
    return _instance
