import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import AppTheme 1.0
import AppState 1.0
import PlanTableModel 1.0
import SectionListModel 1.0

RoundedCard {
    id: panel
    objectName: "testingPlanTablePanel"
    shadowEnabled: true

    property int totalRows: 0
    property bool isEditMode: false  // V5.3: 表格编辑模式

    readonly property var colWidths: [40, 120, 60, 50, 80, 90, 160, 100, 80, 120, 150, 170, 100, 80, 190, 60, 100]
    readonly property var colHeaders: [
        "#", "路段(桩号)", "路幅", "车道", "分部工程", "子分部工程", "分项工程",
        "材料名称", "规格型号", "检测项目", "检测参数", "检测标准", "取样方法",
        "送检类型", "检验批/取样频率", "计划批次", "备注"
    ]
    readonly property var colFields: [
        "sequence", "section", "road_orientation", "lane_count", "sub_project",
        "sub_sub_project", "work_item", "material_name", "spec", "test_item",
        "test_param", "standard", "sampling_method", "inspection_type", "frequency",
        "planned_batches", "remarks"
    ]
    readonly property int totalWidth: {
        var s = 0; for (var i = 0; i < colWidths.length; i++) s += colWidths[i]; return s
    }

    property var hideSectionRow: ({})
    property var hideRoadOrientationRow: ({})

    function rebuildMergeLookups() {
        var mr = PlanTableModel.getMergeRanges()
        if (!mr || !mr.length) return
        hideSectionRow = {}; hideRoadOrientationRow = {}
        for (var i = 0; i < mr.length; i++) {
            var m = mr[i]
            if (m.column === 1) {
                for (var r = m.firstRow + 1; r <= m.lastRow; r++) hideSectionRow[r] = true
            } else if (m.column === 2) {
                for (var r2 = m.firstRow + 1; r2 <= m.lastRow; r2++) hideRoadOrientationRow[r2] = true
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: panel.padding
        spacing: AppTheme.spacing

        RowLayout {
            Layout.fillWidth: true
            Label {
                text: "送检计划"; font.pixelSize: AppTheme.fontSizeLg; font.bold: true
                color: AppTheme.textPrimary; Layout.fillWidth: true
            }
            Label {
                text: panel.totalRows + " 项"; font.pixelSize: AppTheme.fontSizeSm
                color: AppTheme.textSecondary
            }
            ActionButton {
                text: "导出选中"; buttonType: "success"
                enabled: AppState && AppState.currentProjectId && panel.totalRows > 0
                onClicked: {
                    if (AppState && SectionListModel) {
                        AppState.exportExcel(AppState.currentProjectId, "",
                            SectionListModel.getSelectedSections())
                    }
                }
            }
            ActionButton {
                text: "全部导出"; buttonType: "primary"
                enabled: AppState && AppState.currentProjectId && PlanTableModel && PlanTableModel.rowCount() > 0
                onClicked: {
                    if (AppState) AppState.exportExcel(AppState.currentProjectId, "", [])
                }
            }
        }

        Item {
            Layout.fillWidth: true; Layout.fillHeight: true; clip: true

            // ── 空状态 Overlay（独立 layer，绝对居中）──
            Rectangle {
                anchors.fill: parent
                color: "transparent"
                z: 10
                visible: panel.totalRows === 0 && !(AppState && AppState.isAnalyzing)

                Label {
                    anchors.centerIn: parent
                    text: {
                        // V4.5.6: 区分"有路段未选择"和"无路段无数据"
                        if (SectionListModel && !SectionListModel.isEmpty) {
                            return "请选择路段以查看送检计划"
                        }
                        return "暂无送检计划\n导入文件并完成 AI 分析后生成"
                    }
                    color: AppTheme.textDisabled
                    font.pixelSize: AppTheme.fontSize
                    horizontalAlignment: Text.AlignHCenter
                }
            }

            // ── 分析中 Overlay ──
            Rectangle {
                anchors.fill: parent
                color: "transparent"
                z: 10
                visible: AppState && AppState.isAnalyzing && panel.totalRows === 0

                Label {
                    anchors.centerIn: parent
                    text: "正在分析中...\n请稍候"
                    color: AppTheme.accent
                    font.pixelSize: AppTheme.fontSize
                    horizontalAlignment: Text.AlignHCenter
                }
            }

            // V4.6: 修复 QML Row 内不能使用 anchors.fill 的警告
            Item {
                id: headerContainer
                x: -tableFlick.contentX; z: 2
                width: panel.totalWidth; height: 28
                visible: panel.totalRows > 0
                Rectangle {
                    anchors.fill: parent
                    color: AppTheme.headerBg
                    border.color: AppTheme.border
                }
                Row {
                    id: headerRow
                    height: 28
                    Repeater {
                        model: colHeaders.length
                        delegate: Rectangle {
                            width: panel.colWidths[index] || 60; height: 28; color: "transparent"
                            border.color: AppTheme.border
                            Label {
                            anchors.centerIn: parent
                            text: panel.colHeaders[index] || ""
                            font.pixelSize: AppTheme.fontSizeSm; font.bold: true
                            color: AppTheme.textPrimary; elide: Text.ElideRight
                        }
                    }
                }
            }
        }

            // Table body
            Flickable {
                id: tableFlick
                anchors.fill: parent; anchors.topMargin: headerRow.visible ? 28 : 0
                contentWidth: panel.totalWidth; contentHeight: bodyColumn.height
                clip: true; boundsBehavior: Flickable.StopAtBounds
                visible: panel.totalRows > 0

                ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                Column {
                    id: bodyColumn; width: panel.totalWidth
                    Repeater {
                        id: tableRows
                        model: PlanTableModel
                        delegate: Rectangle {
                            readonly property int rowIdx: index
                            width: panel.totalWidth; height: 28
                            color: {
                                // V4.6: 低置信度左右幅行黄色警告
                                if (road_orientation_confidence === "low") return AppTheme.warningBg;
                                return rowIdx % 2 === 0 ? AppTheme.bgSurface : AppTheme.bgMain;
                            }
                            Row {
                                Repeater {
                                    model: 17  // V5.3: 全部 17 列
                                    delegate: Rectangle {
                                        readonly property string colField: index < panel.colFields.length ? panel.colFields[index] : ""
                                        width: panel.colWidths[index] || 60; height: 28
                                        color: panel.isEditMode ? AppTheme.editBg || "#FFFDE7" : "transparent"
                                        border.color: AppTheme.border
                                        // V5.3: 编辑模式绿色左边线标记
                                        Rectangle {
                                            anchors.left: parent.left; anchors.top: parent.top
                                            anchors.bottom: parent.bottom; width: 3
                                            color: AppTheme.editModifiedColor || "#4CAF50"
                                            visible: panel.isEditMode && cellEdit.modified
                                        }
                                        // Read-only Label (非编辑模式 + 非 editable 列)
                                        Label {
                                            id: cellLabel
                                            anchors.left: parent.left
                                            anchors.leftMargin: 4
                                            anchors.verticalCenter: parent.verticalCenter
                                            width: parent.width - 8
                                            visible: !panel.isEditMode && colField !== "planned_batches" && colField !== "remarks"
                                            text: {
                                                if (colField === "sequence")
                                                    return sequence !== undefined ? sequence : ""
                                                if (colField === "section")
                                                    return !panel.hideSectionRow[rowIdx] ? (section || "") : ""
                                                if (colField === "road_orientation")
                                                    return !panel.hideRoadOrientationRow[rowIdx] ? (road_orientation || "") : ""
                                                if (colField === "lane_count") return lane_count || ""
                                                if (colField === "sub_project") return sub_project || ""
                                                if (colField === "sub_sub_project") return sub_sub_project || ""
                                                if (colField === "work_item") return work_item || ""
                                                if (colField === "material_name") return material_name || ""
                                                if (colField === "spec") return spec || ""
                                                if (colField === "test_item") return test_item || ""
                                                if (colField === "test_param") return test_param || ""
                                                if (colField === "standard") return standard || ""
                                                if (colField === "sampling_method") return sampling_method || ""
                                                if (colField === "inspection_type") return inspection_type || ""
                                                if (colField === "frequency") return frequency || ""
                                                return ""
                                            }
                                            horizontalAlignment: (colField === "sequence" || colField === "road_orientation") ? Text.AlignHCenter : Text.AlignLeft
                                            font.pixelSize: AppTheme.fontSizeSm
                                            color: colField === "sequence" ? AppTheme.textSecondary : AppTheme.textPrimary
                                            elide: Text.ElideRight
                                            MouseArea {
                                                anchors.fill: parent
                                                hoverEnabled: true
                                                ToolTip.delay: 500
                                                ToolTip.text: cellLabel.text
                                                ToolTip.visible: containsMouse
                                            }
                                        }
                                        // V5.3: Editable TextInput (编辑模式 或 非编辑模式下 planned_batches/remarks)
                                        TextInput {
                                            id: cellEdit
                                            anchors.left: parent.left
                                            anchors.leftMargin: 4
                                            anchors.verticalCenter: parent.verticalCenter
                                            width: parent.width - 8
                                            visible: panel.isEditMode || colField === "planned_batches" || colField === "remarks"
                                            property bool modified: false
                                            text: {
                                                if (colField === "sequence") return sequence !== undefined ? sequence : ""
                                                if (colField === "section") return !panel.hideSectionRow[rowIdx] ? (section || "") : ""
                                                if (colField === "road_orientation") return !panel.hideRoadOrientationRow[rowIdx] ? (road_orientation || "") : ""
                                                if (colField === "lane_count") return lane_count || ""
                                                if (colField === "sub_project") return sub_project || ""
                                                if (colField === "sub_sub_project") return sub_sub_project || ""
                                                if (colField === "work_item") return work_item || ""
                                                if (colField === "material_name") return material_name || ""
                                                if (colField === "spec") return spec || ""
                                                if (colField === "test_item") return test_item || ""
                                                if (colField === "test_param") return test_param || ""
                                                if (colField === "standard") return standard || ""
                                                if (colField === "sampling_method") return sampling_method || ""
                                                if (colField === "inspection_type") return inspection_type || ""
                                                if (colField === "frequency") return frequency || ""
                                                if (colField === "planned_batches") return planned_batches || ""
                                                if (colField === "remarks") return remarks || ""
                                                return ""
                                            }
                                            font.pixelSize: AppTheme.fontSizeSm
                                            color: AppTheme.textPrimary
                                            clip: true
                                            selectByMouse: true
                                            activeFocusOnPress: panel.isEditMode
                                            readOnly: !panel.isEditMode && colField !== "planned_batches" && colField !== "remarks"
                                            onEditingFinished: {
                                                PlanTableModel.setData(
                                                    PlanTableModel.index(rowIdx, index),
                                                    text,
                                                    Qt.EditRole
                                                )
                                                if (panel.isEditMode) modified = true
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    Connections {
        target: PlanTableModel
        function onDataChangedSignal() { panel.rebuildMergeLookups() }
    }
    Connections {
        target: AppState
        enabled: AppState !== null
        function onAnalysisFinished(projectId, result) { panel.rebuildMergeLookups() }
    }
    Component.onCompleted: { if (panel.totalRows > 0) panel.rebuildMergeLookups() }
}
