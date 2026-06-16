"""
FileListModel — QAbstractListModel 封装文件列表，供 QML TableView/ListView 使用。

角色:
  - FileNameRole:          文件名
  - DisciplineRole:        专业 (SⅠ-SⅦ / PDF / 未知)
  - FileTypeRole:          类型 ("cad" | "pdf" | "word" | "excel")
  - FileSizeRole:          文件大小字符串
  - FilePathRole:          绝对路径
  - ParseStatusRole:       解析状态 ("pending" | "done" | "error")
  - DescriptionRole:       描述
  - ThumbnailPathRole:     缩略图
  - FileIdRole:            文件 ID
  - ConversionStatusRole:  转换状态 (V4.9.3: "" | "done" | "error")
  - HasAnalysisRole:       AI 分析状态 (V4.9.3: bool)
"""

from PySide6.QtCore import QAbstractListModel, Qt, QModelIndex, Signal, Slot


class FileListModel(QAbstractListModel):
    """QML 文件列表数据模型"""

    FileNameRole = Qt.UserRole + 1
    DisciplineRole = Qt.UserRole + 2
    FileTypeRole = Qt.UserRole + 3
    FileSizeRole = Qt.UserRole + 4
    FilePathRole = Qt.UserRole + 5
    ParseStatusRole = Qt.UserRole + 6
    DescriptionRole = Qt.UserRole + 7
    ThumbnailPathRole = Qt.UserRole + 8
    FileIdRole = Qt.UserRole + 9  # V4.7: file ID for replace/delete operations
    ConversionStatusRole = Qt.UserRole + 10  # V4.9.3: 转换状态
    HasAnalysisRole = Qt.UserRole + 11       # V4.9.3: AI 分析状态

    # 刷新完成信号
    refreshed = Signal(int)  # file_count

    def __init__(self, db_manager=None, parent=None):
        super().__init__(parent)
        self._db = db_manager  # DatabaseManager instance
        self._files = []       # List[dict]
        self._current_project_id = ""
        self._has_analysis = False  # V4.9.4: 项目级别 AI 分析状态

    # ── QAbstractListModel 接口 ─────────────────────────

    def rowCount(self, parent=QModelIndex()):
        return len(self._files)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._files):
            return None

        f = self._files[index.row()]

        if role == Qt.DisplayRole or role == self.FileNameRole:
            return f.get("file_name", "")
        elif role == self.DisciplineRole:
            disc = f.get("discipline", "")
            return disc if disc else ("PDF" if f.get("file_type") == "pdf" else "未知")
        elif role == self.FileTypeRole:
            return f.get("file_type", "")
        elif role == self.FileSizeRole:
            return self._format_size(f.get("file_size", 0))
        elif role == self.FilePathRole:
            return f.get("file_path", "")
        elif role == self.ParseStatusRole:
            return f.get("parse_status", "pending")
        elif role == self.DescriptionRole:
            return f.get("description", "")
        elif role == self.ThumbnailPathRole:
            return f.get("thumbnail_path", "")
        elif role == self.FileIdRole:
            return f.get("id", 0)
        elif role == self.ConversionStatusRole:
            return f.get("conversion_status", "")
        elif role == self.HasAnalysisRole:
            # V4.9.4: AI 分析是项目级别操作，所有文件共享同一状态
            return self._has_analysis

        return None

    def roleNames(self):
        return {
            self.FileNameRole: b"fileName",
            self.DisciplineRole: b"discipline",
            self.FileTypeRole: b"fileType",
            self.FileSizeRole: b"fileSize",
            self.FilePathRole: b"filePath",
            self.ParseStatusRole: b"parseStatus",
            self.DescriptionRole: b"description",
            self.ThumbnailPathRole: b"thumbnailPath",
            self.FileIdRole: b"fileId",
            self.ConversionStatusRole: b"conversionStatus",
            self.HasAnalysisRole: b"hasAnalysis",
        }

    # ── 公共方法 ────────────────────────────────────────

    @Slot(str)
    def refresh(self, project_id: str = ""):
        """从数据库重新加载文件列表"""
        pid = project_id or self._current_project_id
        self._current_project_id = pid

        self.beginResetModel()
        if pid and self._db:
            self._files = self._db.get_files(pid)
            self._has_analysis = self._db.has_analysis(pid)  # V4.9.4: 项目级别
        else:
            self._files = []
            self._has_analysis = False
        self.endResetModel()
        self.refreshed.emit(len(self._files))

    def set_db_manager(self, db):
        """设置 DatabaseManager 实例"""
        self._db = db

    def get_file_path(self, row: int) -> str:
        """获取指定行的文件路径"""
        if 0 <= row < len(self._files):
            return self._files[row].get("file_path", "")
        return ""


    @Slot(int, str)
    def removeFile(self, row: int, project_id: str = ""):
        """Remove a file from the project and refresh the list."""
        if 0 <= row < len(self._files):
            file_info = self._files[row]
            file_id = file_info.get("id")
            if file_id and self._db:
                self._db.delete_file(file_id)
            # Remove from local cache
            self._files.pop(row)
            self.refresh(project_id)

    # ── 辅助 ────────────────────────────────────────────

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        if not size_bytes or size_bytes < 1024:
            return f"{size_bytes or 0} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
