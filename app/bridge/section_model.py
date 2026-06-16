"""
SectionListModel — QAbstractListModel 封装路段列表，V4.5.5 卡片选中模式。

角色:
  - SectionNameRole: 路段名称 (如 "K0+100~K0+200")
  - RoadOrientationRole:   路幅
  - DescriptionRole: 描述
  - SourceFileRole:  来源文件路径
  - SelectedRole:    是否选中 (bool, QML role "selected")
"""

from PySide6.QtCore import QAbstractListModel, Property, Qt, QModelIndex, Signal, Slot


class SectionListModel(QAbstractListModel):
    """QML 路段列表数据模型（卡片选择）"""

    SectionNameRole = Qt.UserRole + 1
    LeftRightRole = Qt.UserRole + 2
    DescriptionRole = Qt.UserRole + 3
    SourceFileRole = Qt.UserRole + 4
    SelectedRole = Qt.UserRole + 5

    sectionsChanged = Signal()
    selectedChanged = Signal()  # V4.5.5: 选中状态变化

    def __init__(self, db_manager=None, parent=None):
        super().__init__(parent)
        self._db = db_manager
        self._sections = []       # List[dict] from DB
        self._selected = set()    # V4.5.5: 选中的 index 集合 (替代 _checked)

    # ── QAbstractListModel 接口 ─────────────────────────

    def rowCount(self, parent=QModelIndex()):
        return len(self._sections)

    @Property(bool, notify=sectionsChanged)
    def isEmpty(self):
        return len(self._sections) == 0

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._sections):
            return None

        s = self._sections[index.row()]
        row = index.row()

        if role == Qt.DisplayRole or role == self.SectionNameRole:
            return s.get("section_name", "")
        elif role == self.LeftRightRole:
            return s.get("road_orientation", "")
        elif role == self.DescriptionRole:
            return s.get("description", "")
        elif role == self.SourceFileRole:
            return s.get("source_file_id", "")
        elif role == self.SelectedRole:
            return row in self._selected
        # 保留 CheckStateRole 兼容旧代码
        elif role == Qt.CheckStateRole:
            return Qt.Checked if row in self._selected else Qt.Unchecked

        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def roleNames(self):
        return {
            self.SectionNameRole: b"sectionName",
            self.LeftRightRole: b"leftRight",
            self.DescriptionRole: b"description",
            self.SourceFileRole: b"sourceFile",
            self.SelectedRole: b"selected",
        }

    # ── 公共方法 ────────────────────────────────────────

    @Slot(str)
    def refresh(self, project_id: str = ""):
        """从数据库加载路段列表，默认不选中任何路段"""
        self.beginResetModel()
        if project_id and self._db:
            self._sections = self._db.get_road_sections(project_id) or []
        else:
            self._sections = []
        self._selected = set()  # V4.5.6: 默认不选中，通知 PlanTableModel 清空过滤
        self.endResetModel()
        self.sectionsChanged.emit()
        self.selectedChanged.emit()  # V4.5.6: 路段刷新后确保 PlanTableModel 收到空选择集

    @Slot(int)
    def toggleSection(self, index: int):
        """V4.5.5: 切换指定索引的选中状态（卡片点击）"""
        if 0 <= index < len(self._sections):
            if index in self._selected:
                self._selected.discard(index)
            else:
                self._selected.add(index)
            model_index = self.index(index)
            self.dataChanged.emit(model_index, model_index, [self.SelectedRole])
            self.selectedChanged.emit()

    @Slot()
    def selectAll(self):
        """V4.5.5: 全选所有路段"""
        self._selected = set(range(len(self._sections)))
        self.dataChanged.emit(self.index(0), self.index(len(self._sections) - 1), [self.SelectedRole])
        self.selectedChanged.emit()

    @Slot()
    def deselectAll(self):
        """V4.5.5: 取消全选"""
        self._selected = set()
        if self._sections:
            self.dataChanged.emit(self.index(0), self.index(len(self._sections) - 1), [self.SelectedRole])
        self.selectedChanged.emit()

    @Slot(result=bool)
    def hasAnySelected(self) -> bool:
        """V4.5.5: 是否有任何路段被选中"""
        return len(self._selected) > 0

    @Slot(result="QVariantList")
    def getSelectedSections(self) -> list:
        """V5.0: 返回选中的路段对象列表（含 roadOrientation 供 ProcessFlow 使用）"""
        result = []
        for i in sorted(self._selected):
            sec = self._sections[i]
            result.append({
                "sectionName": sec.get("section_name", ""),
                "roadOrientation": sec.get("road_orientation", ""),
            })
        return result

    def set_db_manager(self, db):
        """设置 DatabaseManager 实例"""
        self._db = db
