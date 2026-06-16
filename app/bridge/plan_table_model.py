"""
PlanTableModel — 16 列送检计划表格模型。

列: 序号|路段(桩号)|路幅|分部工程|子分部工程|分项工程|
     材料名称|规格型号|检测项目|检测参数|检测标准|取样方法|
     送检类型|检验批/取样频率|计划批次|备注
"""

from PySide6.QtCore import QAbstractTableModel, Qt, QModelIndex, Signal, Slot

COLUMNS = [
    "序号", "路段(桩号)", "路幅", "车道", "分部工程", "子分部工程", "分项工程",
    "材料名称", "规格型号", "检测项目", "检测参数", "检测标准", "取样方法",
    "送检类型", "检验批/取样频率", "计划批次", "备注",
]

COLUMN_KEYS = [
    "sequence", "section", "road_orientation", "lane_count", "sub_project",
    "sub_sub_project", "work_item", "material_name", "spec", "test_item",
    "test_param", "standard", "sampling_method", "inspection_type", "frequency",
    "planned_batches", "remarks",
]

# V5.3: 全部 17 列可编辑（编辑模式下）
EDITABLE_COLUMNS = set(range(17))  # 0-16 all editable


class PlanTableModel(QAbstractTableModel):
    """16 列送检计划 QAbstractTableModel"""

    dataChangedSignal = Signal()
    loaded = Signal(int)  # row_count
    editingModeChanged = Signal(bool)  # V5.3: 编辑模式切换

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []              # 当前显示的行（过滤后）
        self._all_rows = []          # V4.5.5: 全部数据（未过滤）
        self._selected_sections = set()  # V4.5.5: 选中的路段名集合
        self._db = None
        self._is_edit_mode = False   # V5.3: 编辑模式
        self._modified_cells = set()  # V5.3: {(row, col)} 修改过的单元格

    def set_db_manager(self, db):
        """绑定 DatabaseManager 实例（由 main.py 调用）"""
        self._db = db

    def _apply_filter(self):
        """V4.5.6: 根据 _selected_sections 过滤行 — 无选择时显示空表"""
        if not self._selected_sections:
            # 用户未选择任何路段 → 不显示任何行，等待用户选择
            self._rows = []
        else:
            self._rows = [
                r for r in self._all_rows
                if r.get("section", "") in self._selected_sections
            ]

    @Slot("QVariantList")
    def setSelectedSections(self, sections: list):
        """V4.5.5: 设置选中的路段列表并重新过滤"""
        names = []
        for s in (sections or []):
            if isinstance(s, dict):
                names.append(s.get("sectionName", s.get("section", "")))
            else:
                names.append(str(s))
        self._selected_sections = set(names)
        self.beginResetModel()
        self._apply_filter()
        self.endResetModel()
        self.dataChangedSignal.emit()

    # ── QAbstractTableModel ─────────────────────────────

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(COLUMNS)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._rows):
            return None

        row = self._rows[index.row()]

        if role == Qt.DisplayRole:
            key = COLUMN_KEYS[index.column()]
            value = row.get(key, "")
            return str(value) if value is not None else ""
        elif role == Qt.TextAlignmentRole:
            if index.column() == 0:  # 序号居中
                return Qt.AlignCenter
            return Qt.AlignLeft | Qt.AlignVCenter
        elif Qt.UserRole < role <= Qt.UserRole + len(COLUMN_KEYS):
            # Custom roles for QML delegate access (e.g. model.section)
            col = role - Qt.UserRole - 1
            if 0 <= col < len(COLUMN_KEYS):
                value = row.get(COLUMN_KEYS[col], "")
                return str(value) if value is not None else ""
        elif role == Qt.UserRole + 17:  # V4.6: road_orientation_confidence
            return row.get("road_orientation_confidence", "")

        return None

    def setData(self, index, value, role=Qt.EditRole):
        """V5.3: 编辑模式下支持全部 17 列编辑，追踪修改单元格"""
        if not index.isValid() or index.row() >= len(self._rows):
            return False
        if role == Qt.EditRole and index.column() in EDITABLE_COLUMNS:
            key = COLUMN_KEYS[index.column()]
            new_val = str(value) if value is not None else ""
            old_val = self._rows[index.row()].get(key, "")
            if new_val == old_val:
                return True  # 值未变，跳过
            self._rows[index.row()][key] = new_val
            # V5.3: 编辑模式下追踪修改，攒批保存
            if self._is_edit_mode:
                self._modified_cells.add((index.row(), index.column()))
            else:
                # 非编辑模式：立即持久化（兼容旧行为）
                if self._db:
                    try:
                        item_id = self._rows[index.row()].get("id")
                        if item_id:
                            self._db.update_plan_item(item_id, key, new_val)
                    except Exception as e:
                        import logging
                        logging.getLogger(__name__).warning("Failed to persist edit: %s", e)
            # V6.0: 空列表 = 所有 role 都变更，确保 QML Label/TextInput 同步刷新
            self.dataChanged.emit(index, index, [])
            self.dataChangedSignal.emit()
            return True
        return False

    def flags(self, index):
        default_flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.isValid() and index.column() in EDITABLE_COLUMNS:
            return default_flags | Qt.ItemIsEditable
        return default_flags

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            if 0 <= section < len(COLUMNS):
                return COLUMNS[section]
        return None

    def roleNames(self):
        roles = {Qt.DisplayRole: b"display"}
        for i, key in enumerate(COLUMN_KEYS):
            roles[Qt.UserRole + i + 1] = key.encode()
        roles[Qt.UserRole + 17] = b"road_orientation_confidence"  # V4.6
        return roles

    # ── Public Methods ──────────────────────────────────

    @Slot("QVariantMap")
    def loadFromResult(self, result: dict):
        """从 AI 分析结果加载"""
        self.beginResetModel()
        self._all_rows = result.get("testing_plan", [])
        self._apply_filter()
        self.endResetModel()
        self.loaded.emit(len(self._rows))
        self.dataChangedSignal.emit()

    @Slot(str)
    def loadFromDatabase(self, project_id: str = ""):
        """从 SQLite 加载送检计划"""
        self.beginResetModel()
        if self._db and project_id:
            try:
                items = self._db.get_testing_plan_items(project_id)
                self._all_rows = items or []
            except Exception:
                self._all_rows = []
        else:
            self._all_rows = []
        self._apply_filter()
        self.endResetModel()
        self.loaded.emit(len(self._rows))
        self.dataChangedSignal.emit()

    def setRows(self, rows: list):
        """直接设置行数据"""
        self.beginResetModel()
        self._rows = rows or []
        self.endResetModel()
        self.loaded.emit(len(self._rows))
        self.dataChangedSignal.emit()

    def getRow(self, row: int) -> dict:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return {}

    # ── V5.3: 编辑模式 ──────────────────────────────────

    @Slot(bool)
    def setEditingMode(self, enabled: bool):
        """切换编辑模式"""
        if self._is_edit_mode == enabled:
            return
        self._is_edit_mode = enabled
        self._modified_cells.clear()
        self.editingModeChanged.emit(enabled)

    def isEditing(self) -> bool:
        """是否处于编辑模式"""
        return self._is_edit_mode

    @Slot(result="QVariantList")
    def getModifiedCells(self) -> list:
        """V5.3: 返回修改过的单元格列表（QML 可调用）"""
        result = []
        for row, col in self._modified_cells:
            if row < len(self._rows):
                key = COLUMN_KEYS[col] if col < len(COLUMN_KEYS) else ""
                result.append({
                    "row": row,
                    "column": col,
                    "key": key,
                    "value": self._rows[row].get(key, ""),
                    "id": self._rows[row].get("id"),
                })
        return result

    @Slot()
    def clearModifiedCells(self):
        """V5.3: 清除修改标记（QML 可调用）"""
        self._modified_cells.clear()

    @Slot(result="QVariantList")
    def getMergeRanges(self) -> list:
        """V4.5.5: 返回需要合并的单元格范围。
        column=1 (路段/桩号): 同 section 合并
        column=2 (路幅): 同 section + 同 road_orientation 合并"""
        if not self._rows:
            return []
        merges = []
        n = len(self._rows)

        # column 1 (路段): 相同桩号合并
        start = 0
        for i in range(1, n):
            if self._rows[i].get("section") != self._rows[start].get("section"):
                if i - start > 1:
                    merges.append({"firstRow": start, "lastRow": i - 1, "column": 1})
                start = i
        if n - start > 1:
            merges.append({"firstRow": start, "lastRow": n - 1, "column": 1})

        # column 2 (路幅): 相同 section + road_orientation 合并
        start = 0
        for i in range(1, n):
            if (self._rows[i].get("section") != self._rows[start].get("section") or
                    self._rows[i].get("road_orientation") != self._rows[start].get("road_orientation")):
                if i - start > 1:
                    merges.append({"firstRow": start, "lastRow": i - 1, "column": 2})
                start = i
        if n - start > 1:
            merges.append({"firstRow": start, "lastRow": n - 1, "column": 2})

        return merges
