"""
V4.9.4: ProjectTreeModel — 统一 QAbstractItemModel 替代 ProjectListModel + FileListModel。

两级树结构:
    Root (不可见)
      └── Project (项目节点, depth=0)
            ├── file_1.dwg (文件叶子, depth=1)
            ├── file_2.pdf
            └── ...

特性:
- Lazy load: 文件列表在项目首次展开时才从 DB 加载
- 增量更新: dataChanged 替代 beginResetModel
- 性能: QML TreeView 原生虚拟化 + delegate 回收
"""

from PySide6.QtCore import QAbstractItemModel, QModelIndex, Qt, Signal, Slot, Property
from typing import List, Dict, Optional, Any


class ProjectTreeNode:
    """树节点（项目或文件）"""
    __slots__ = ('node_type', 'data', 'parent', 'children', 'loaded')

    def __init__(self, node_type: str, data: Dict, parent: Optional['ProjectTreeNode'] = None):
        self.node_type = node_type    # "project" | "file"
        self.data = data              # 从 DB 加载的原始数据 dict
        self.parent = parent
        self.children: List['ProjectTreeNode'] = []
        self.loaded = False           # 项目的文件列表是否已加载

    @property
    def row(self) -> int:
        """在本级兄弟中的索引"""
        if self.parent:
            return self.parent.children.index(self)
        return 0


# ── 角色定义 ──────────────────────────────────────────────
class Roles:
    NodeTypeRole = Qt.UserRole + 1      # "project" | "file"
    ProjectIdRole = Qt.UserRole + 2     # 项目 ID
    FileIdRole = Qt.UserRole + 3        # 文件 ID
    FileTypeRole = Qt.UserRole + 4      # "cad" | "pdf" | "word" | "excel"
    ParseStatusRole = Qt.UserRole + 5   # "done" | "error" | ""
    ConversionStatusRole = Qt.UserRole + 6
    HasAnalysisRole = Qt.UserRole + 7   # bool
    DisciplineRole = Qt.UserRole + 8    # "SⅠ" | "PDF" | "Word" | ...
    FileSizeRole = Qt.UserRole + 9      # 格式化后的文件大小字符串
    FilePathRole = Qt.UserRole + 10
    DescriptionRole = Qt.UserRole + 11
    TotalFilesRole = Qt.UserRole + 12   # 项目的文件总数
    DisplayNameRole = Qt.UserRole + 14  # 节点显示名称
    HasChildrenRole = Qt.UserRole + 15  # 是否有子节点

    # 角色名映射（QML 使用）
    _names = {
        NodeTypeRole: b"nodeType",
        ProjectIdRole: b"projectId",
        FileIdRole: b"fileId",
        FileTypeRole: b"fileType",
        ParseStatusRole: b"parseStatus",
        ConversionStatusRole: b"conversionStatus",
        HasAnalysisRole: b"hasAnalysis",
        DisciplineRole: b"discipline",
        FileSizeRole: b"fileSize",
        FilePathRole: b"filePath",
        DescriptionRole: b"description",
        TotalFilesRole: b"totalFiles",
        HasChildrenRole: b"hasChildren",
        DisplayNameRole: b"displayName",
    }

    @classmethod
    def roleNames(cls) -> Dict[int, bytes]:
        return cls._names


class ProjectTreeModel(QAbstractItemModel):
    """
    VS Code 风格两级树模型。

    用法:
        model = ProjectTreeModel()
        model.set_db_manager(db)
        model.refresh()  # 从 DB 加载项目列表
    """

    projectsChanged = Signal()
    countChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._db = None
        self._root = ProjectTreeNode("root", {})
        self._projects: List[ProjectTreeNode] = []  # 顶级项目节点引用
        self._count = 0

    def set_db_manager(self, db):
        """绑定 DatabaseManager 实例"""
        self._db = db

    # ── QAbstractItemModel 必须实现的方法 ──────────────────

    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        if not parent.isValid():
            # 根节点的子节点 = 项目列表
            if row < len(self._projects):
                return self.createIndex(row, column, self._projects[row])
            return QModelIndex()
        # 父节点是项目 → 子节点是文件
        parent_node: ProjectTreeNode = parent.internalPointer()
        if parent_node and parent_node.node_type == "project":
            if row < len(parent_node.children):
                return self.createIndex(row, column, parent_node.children[row])
        return QModelIndex()

    def parent(self, index: QModelIndex) -> QModelIndex:
        if not index.isValid():
            return QModelIndex()
        node: ProjectTreeNode = index.internalPointer()
        if node and node.parent and node.parent.node_type != "root":
            return self.createIndex(node.parent.row, 0, node.parent)
        return QModelIndex()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if not parent.isValid():
            return len(self._projects)
        node: ProjectTreeNode = parent.internalPointer()
        if node and node.node_type == "project":
            return len(node.children)
        return 0

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 1  # 单列树

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None
        node: ProjectTreeNode = index.internalPointer()
        if not node:
            return None

        d = node.data
        if node.node_type == "project":
            if role == Qt.DisplayRole or role == Roles.DisplayNameRole:
                return d.get("name", "未命名")
            if role == Roles.NodeTypeRole:
                return "project"
            if role == Roles.ProjectIdRole:
                return d.get("id", "")
            if role == Roles.TotalFilesRole:
                return d.get("totalFiles", 0)
            if role == Roles.HasAnalysisRole:
                return d.get("hasAnalysis", False)
            if role == Roles.HasChildrenRole:
                return True
            if role == Roles.ParseStatusRole:
                return "done"  # 项目本身无此状态
            if role == Roles.ConversionStatusRole:
                return "done"
        elif node.node_type == "file":
            if role == Qt.DisplayRole or role == Roles.DisplayNameRole:
                return d.get("file_name", "")
            if role == Roles.NodeTypeRole:
                return "file"
            if role == Roles.ProjectIdRole:
                return d.get("project_id", "")
            if role == Roles.FileIdRole:
                return d.get("id", 0)
            if role == Roles.FileTypeRole:
                return d.get("file_type", "")
            if role == Roles.ParseStatusRole:
                return d.get("parse_status", "")
            if role == Roles.ConversionStatusRole:
                return d.get("conversion_status", "")
            if role == Roles.HasAnalysisRole:
                return d.get("has_analysis", False)
            if role == Roles.DisciplineRole:
                return d.get("discipline", "未知")
            if role == Roles.FileSizeRole:
                return d.get("file_size_str", "")
            if role == Roles.FilePathRole:
                return d.get("file_path", "")
            if role == Roles.DescriptionRole:
                return d.get("description", "")
            if role == Roles.HasChildrenRole:
                return False
        return None

    # ── count Property (QML bindable) ────────────────────
    def _get_count(self):
        return self._count

    count = Property(int, _get_count, notify=countChanged)

    def roleNames(self) -> Dict[int, bytes]:
        return Roles.roleNames()

    def hasChildren(self, parent: QModelIndex = QModelIndex()) -> bool:
        if not parent.isValid():
            return len(self._projects) > 0
        node: ProjectTreeNode = parent.internalPointer()
        if node and node.node_type == "project":
            return True  # 项目始终标记为有子节点（即使文件尚未加载）
        return False

    # ── 公共方法 ──────────────────────────────────────────

    @Slot()
    def refresh(self):
        """从 DB 重新加载项目列表（保留展开状态）"""
        if not self._db:
            return
        self.beginResetModel()
        self._projects.clear()

        try:
            rows = self._db.list_projects()
            for proj_data in (rows or []):
                node = ProjectTreeNode("project", proj_data)
                self._projects.append(node)
        except Exception:
            import logging
            logging.getLogger(__name__).warning("ProjectTreeModel.refresh: 刷新失败", exc_info=True)

        self._count = len(self._projects)
        self.endResetModel()
        self.countChanged.emit()
        self.projectsChanged.emit()

    @Slot(str)
    def removeProject(self, project_id: str):
        """V6.0: 移除单个项目节点，不重建整棵树（保持展开状态）"""
        for i, node in enumerate(self._projects):
            if node.data.get("id") == project_id:
                parent_idx = QModelIndex()
                self.beginRemoveRows(parent_idx, i, i)
                self._projects.pop(i)
                self.endRemoveRows()
                self._count = len(self._projects)
                self.countChanged.emit()
                return

    @Slot(str, result=bool)
    def refreshProject(self, project_id: str) -> bool:
        """V6.0: 增量刷新文件列表（对比新旧，不触发 TreeView 折叠）"""
        if not self._db:
            return False

        proj_node = None
        proj_row = -1
        for i, node in enumerate(self._projects):
            if node.data.get("id") == project_id:
                proj_node = node
                proj_row = i
                break

        if not proj_node:
            return False

        parent_idx = self.index(proj_row, 0, QModelIndex())

        # 从 DB 加载最新文件列表
        files = self._db.get_files(project_id) or []
        new_map = {str(f.get("id")): f for f in files}
        old_map = {str(c.data.get("id")): c for c in proj_node.children}

        # 找出要删除的文件
        removed = []
        for i, child in enumerate(proj_node.children):
            fid = str(child.data.get("id"))
            if fid not in new_map:
                removed.append(i)

        # 从后往前删（保持索引有效）
        for i in reversed(removed):
            self.beginRemoveRows(parent_idx, i, i)
            proj_node.children.pop(i)
            self.endRemoveRows()

        # 找出要新增的文件
        existing_ids = {str(c.data.get("id")) for c in proj_node.children}
        insert_idx = len(proj_node.children)
        for f in files:
            if str(f.get("id")) not in existing_ids:
                child = ProjectTreeNode("file", f, proj_node)
                self.beginInsertRows(parent_idx, insert_idx, insert_idx)
                proj_node.children.append(child)
                self.endInsertRows()
                insert_idx += 1

        proj_node.loaded = True
        return True

    def _load_files(self, proj_node: ProjectTreeNode, parent_idx: QModelIndex):
        """懒加载项目的文件列表"""
        if proj_node.loaded or not self._db:
            return
        proj_node.loaded = True

        project_id = proj_node.data.get("id")
        files = self._db.get_files(project_id)
        if not files:
            return

        # 附加 has_analysis 信息
        has_analysis = self._db.has_analysis(project_id) if hasattr(self._db, 'has_analysis') else False

        count = len(files)
        self.beginInsertRows(parent_idx, 0, count - 1)
        for f in files:
            f["project_id"] = project_id
            f["has_analysis"] = has_analysis
            f["file_size_str"] = _format_file_size(f.get("file_size", 0))
            child = ProjectTreeNode("file", f, parent=proj_node)
            proj_node.children.append(child)
        self.endInsertRows()

    def canFetchMore(self, parent: QModelIndex) -> bool:
        """TreeView 懒加载钩子"""
        if not parent.isValid():
            return False
        node: ProjectTreeNode = parent.internalPointer()
        if node and node.node_type == "project" and not node.loaded:
            return True
        return False

    def fetchMore(self, parent: QModelIndex):
        """TreeView 展开时触发懒加载"""
        if not parent.isValid():
            return
        node: ProjectTreeNode = parent.internalPointer()
        if node and node.node_type == "project" and not node.loaded:
            self._load_files(node, parent)

    # ── 查找方法 ─────────────────────────────────────────

    def find_project_node(self, project_id: str) -> Optional[ProjectTreeNode]:
        for node in self._projects:
            if node.data.get("id") == project_id:
                return node
        return None

    def project_id_at(self, index: QModelIndex) -> str:
        """获取任意节点所属的项目 ID"""
        if not index.isValid():
            return ""
        node: ProjectTreeNode = index.internalPointer()
        if node.node_type == "project":
            return node.data.get("id", "")
        else:
            return node.data.get("project_id", "")


def _format_file_size(size_bytes: int) -> str:
    """格式化文件大小"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
