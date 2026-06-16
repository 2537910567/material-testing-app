"""
ProjectListModel — QAbstractListModel 封装项目列表，供 QML ListView 使用。

V4.5.6: VS Code 风格精简 — 移除 CadCountRole/PdfCountRole/UpdatedAtRole。

角色:
  - NameRole:        项目名称
  - ProjectIdRole:   项目 ID
  - TotalFilesRole:  文件总数
  - HasAnalysisRole: 是否有分析结果
"""

from PySide6.QtCore import QAbstractListModel, Qt, QModelIndex, Signal, Slot


class ProjectListModel(QAbstractListModel):
    """QML 项目列表数据模型"""

    # 自定义角色 (V4.5.6: 移除 CadCount/PdfCount/UpdatedAt)
    NameRole = Qt.UserRole + 1
    ProjectIdRole = Qt.UserRole + 2
    TotalFilesRole = Qt.UserRole + 5
    HasAnalysisRole = Qt.UserRole + 6

    def __init__(self, project_manager=None, parent=None):
        super().__init__(parent)
        self._pm = project_manager  # ProjectManager instance
        self._projects = []         # List[Project]

    # ── QAbstractListModel 接口 ─────────────────────────

    def rowCount(self, parent=QModelIndex()):
        return len(self._projects)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._projects):
            return None

        p = self._projects[index.row()]

        if role == Qt.DisplayRole or role == self.NameRole:
            return p.name or "未命名项目"
        elif role == self.ProjectIdRole:
            return p.id
        elif role == self.TotalFilesRole:
            return p.total_files
        elif role == self.HasAnalysisRole:
            return p.has_analysis

        return None

    def roleNames(self):
        return {
            self.NameRole: b"projectName",
            self.ProjectIdRole: b"projectId",
            self.TotalFilesRole: b"totalFiles",
            self.HasAnalysisRole: b"hasAnalysis",
        }

    # ── 公共方法 ────────────────────────────────────────

    @Slot()
    def refresh(self):
        """从 ProjectManager 重新加载项目列表"""
        self.beginResetModel()
        if self._pm:
            self._projects = self._pm.list_projects()
        else:
            self._projects = []
        self.endResetModel()

    def set_project_manager(self, pm):
        """设置 ProjectManager 实例"""
        self._pm = pm
        self.refresh()

    def get_project_id(self, row: int) -> str:
        """获取指定行的项目 ID"""
        if 0 <= row < len(self._projects):
            return self._projects[row].id
        return ""

    def get_project_name(self, row: int) -> str:
        """获取指定行的项目名称"""
        if 0 <= row < len(self._projects):
            return self._projects[row].name
        return ""
