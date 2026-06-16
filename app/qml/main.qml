import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import QtQuick.Dialogs
import AppTheme 1.0
import AppState 1.0
import ProjectListModel 1.0
import FileListModel 1.0
import SectionListModel 1.0
import PlanTableModel 1.0
import ProjectTreeModel 1.0

ApplicationWindow {
    id: mainWindow
    objectName: "mainWindow"
    visible: true
    width: 1400
    height: 900
    minimumWidth: 1000
    minimumHeight: 700
    title: "工程材料送检分析系统 V" + (AppState ? AppState.appVersion : "4.7.0")
    color: AppTheme.bgMain

    // ── ToolBar ──────────────────────────────────────
    header: ToolBar {
        id: mainToolBar
        objectName: "mainToolBar"
        height: AppTheme.toolbarHeight

        background: Rectangle {
            color: AppTheme.bgSurface
            Rectangle {
                anchors.bottom: parent.bottom
                width: parent.width; height: 1
                color: AppTheme.border
            }
        }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: AppTheme.spacingXl
            anchors.rightMargin: AppTheme.spacingXl
            spacing: AppTheme.spacingLg

            Label {
                text: "工程材料送检分析系统"
                font.pixelSize: AppTheme.fontSizeLg; font.bold: true
                color: AppTheme.textPrimary
                Layout.maximumWidth: 240; elide: Text.ElideRight
            }

            Rectangle { width: 1; height: 22; color: AppTheme.border }

            // Import progress
            ColumnLayout {
                Layout.fillWidth: true; Layout.preferredWidth: 280
                spacing: 2; visible: AppState && AppState.isImporting
                RowLayout {
                    spacing: 6
                    ProgressBar {
                        id: importBar
                        objectName: "importProgressBar"
                        Layout.fillWidth: true; Layout.preferredHeight: 6
                        value: AppState && AppState.importTotal > 0
                               ? AppState.importCurrent / AppState.importTotal : 0
                        background: Rectangle { implicitHeight: 6; color: AppTheme.bgHover; radius: 3 }
                        contentItem: Item {
                            implicitHeight: 6
                            Rectangle {
                                width: importBar.visualPosition * parent.width; height: parent.height
                                radius: 3; color: AppTheme.cta
                            }
                        }
                    }
                    Label {
                        text: AppState && AppState.importTotal > 0
                              ? Math.round(AppState.importCurrent / AppState.importTotal * 100) + "%" : ""
                        font.pixelSize: AppTheme.fontSizeSm; font.bold: true
                        color: AppTheme.cta; Layout.preferredWidth: 36
                    }
                }
                Label {
                    text: AppState ? (AppState.importMessage || "") : ""
                    font.pixelSize: AppTheme.fontSizeSm; color: AppTheme.textSecondary; elide: Text.ElideRight
                }
            }

            // V4.9.3: Conversion progress (确定式进度条)
            ColumnLayout {
                Layout.fillWidth: true; Layout.preferredWidth: 350
                spacing: 2; visible: AppState && AppState.isConverting
                RowLayout {
                    spacing: 4
                    ProgressBar {
                        id: convBar
                        objectName: "conversionProgressBar"
                        Layout.fillWidth: true; Layout.preferredHeight: 6
                        indeterminate: false
                        value: AppState && AppState.conversionTotal > 0
                               ? AppState.conversionCurrent / AppState.conversionTotal : 0
                        clip: true
                        background: Rectangle { implicitHeight: 6; color: AppTheme.bgHover; radius: 3 }
                        contentItem: Item {
                            id: convContent
                            implicitHeight: 6
                            Rectangle {
                                width: convBar.visualPosition * convContent.width
                                height: convContent.height
                                radius: 3; color: AppTheme.cta
                            }
                        }
                    }
                    Label {
                        text: AppState && AppState.conversionTotal > 0
                              ? Math.round(AppState.conversionCurrent / AppState.conversionTotal * 100) + "%" : ""
                        font.pixelSize: AppTheme.fontSizeSm; font.bold: true
                        color: AppTheme.cta; Layout.preferredWidth: 36
                    }
                    ActionButton {
                        buttonType: "danger"; text: "✕"
                        font.pixelSize: 12; implicitWidth: 24; implicitHeight: 24
                        leftPadding: 2; rightPadding: 2
                        ToolTip.visible: hovered; ToolTip.text: "取消转换"
                        onClicked: { if (AppState) AppState.cancelConversion() }
                    }
                }
                Label {
                    text: AppState ? (AppState.aiProgress || "") : ""
                    font.pixelSize: AppTheme.fontSizeSm; color: AppTheme.textSecondary
                    elide: Text.ElideRight; Layout.fillWidth: true
                }
            }

            // AI progress (V4.9.3: 支持百分比)
            ColumnLayout {
                Layout.fillWidth: true; Layout.preferredWidth: 350
                spacing: 2; visible: AppState && AppState.isAnalyzing
                RowLayout {
                    spacing: 4
                    ProgressBar {
                        id: aiBar
                        objectName: "aiProgressBar"
                        Layout.fillWidth: true; Layout.preferredHeight: 6
                        indeterminate: AppState && AppState.analysisTotal === 0
                        value: AppState && AppState.analysisTotal > 0
                               ? AppState.analysisCurrent / AppState.analysisTotal : 0
                        clip: true
                        background: Rectangle { implicitHeight: 6; color: AppTheme.bgHover; radius: 3 }
                        contentItem: Item {
                            id: aiContent
                            implicitHeight: 6
                            Rectangle {
                                width: aiBar.indeterminate
                                       ? aiContent.width * 0.4
                                       : aiBar.visualPosition * aiContent.width
                                height: aiContent.height; radius: 3; color: AppTheme.accent
                                NumberAnimation on x {
                                    running: aiBar.indeterminate && aiBar.visible
                                    from: -aiContent.width * 0.4; to: aiContent.width
                                    duration: 1500; loops: Animation.Infinite
                                }
                            }
                        }
                    }
                    Label {
                        text: AppState && AppState.analysisTotal > 0
                              ? Math.round(AppState.analysisCurrent / AppState.analysisTotal * 100) + "%" : ""
                        font.pixelSize: AppTheme.fontSizeSm; font.bold: true
                        color: AppTheme.accent; Layout.preferredWidth: 36
                        visible: AppState && AppState.analysisTotal > 0
                    }
                    ActionButton {
                        buttonType: "toolbar"
                        text: AppState && AppState.isAnalysisPaused ? "▶" : "⏸"
                        font.pixelSize: 14; implicitWidth: 28; implicitHeight: 28
                        ToolTip.visible: hovered
                        ToolTip.text: AppState && AppState.isAnalysisPaused ? "继续" : "暂停"
                        onClicked: {
                            if (AppState && AppState.isAnalysisPaused) AppState.resumeAnalysis()
                            else if (AppState) AppState.pauseAnalysis()
                        }
                    }
                    ActionButton {
                        buttonType: "danger"; text: "✕"
                        font.pixelSize: 12; implicitWidth: 24; implicitHeight: 24
                        leftPadding: 2; rightPadding: 2
                        ToolTip.visible: hovered; ToolTip.text: "取消"
                        onClicked: { if (AppState) AppState.cancelAnalysis() }
                    }
                }
                Label {
                    text: AppState ? (AppState.aiProgress || "") : ""
                    font.pixelSize: AppTheme.fontSizeSm
                    color: AppState && AppState.isAnalysisPaused ? AppTheme.cta : AppTheme.textSecondary
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
            }

            // Export progress
            ColumnLayout {
                Layout.fillWidth: true; Layout.preferredWidth: 120
                spacing: 2; visible: AppState && AppState.isExporting
                ProgressBar {
                    Layout.fillWidth: true; Layout.preferredHeight: 6; indeterminate: true
                    background: Rectangle { implicitHeight: 6; color: AppTheme.bgHover; radius: 3 }
                }
                Label { text: "导出中..."; font.pixelSize: AppTheme.fontSizeSm; color: AppTheme.textSecondary }
            }

            Item { Layout.fillWidth: true; visible: !(AppState && (AppState.isImporting || AppState.isConverting || AppState.isAnalyzing || AppState.isExporting)) }

            // V4.9.4: 工具栏操作按钮 — 无需右键即可启动转换/分析
            ActionButton {
                objectName: "btnStartConversion"
                buttonType: "primary"
                text: "开始转换"
                font.pixelSize: 12; implicitHeight: 28
                visible: AppState && AppState.currentProjectId !== "" && !AppState.isConverting && !AppState.isAnalyzing
                onClicked: { if (AppState) AppState.startConversion(AppState.currentProjectId) }
                ToolTip.visible: hovered
                ToolTip.text: "转换 CAD/PDF 文件为图片（Phase 1）"
            }
            ActionButton {
                objectName: "btnStartAnalysis"
                buttonType: "primary"
                text: "AI 分析"
                font.pixelSize: 12; implicitHeight: 28
                visible: AppState && AppState.currentProjectId !== "" && !AppState.isConverting && !AppState.isAnalyzing
                onClicked: { if (AppState) AppState.startAnalysis(AppState.currentProjectId) }
                ToolTip.visible: hovered
                ToolTip.text: "使用 AI 分析工程图纸（Phase 2）"
            }

            // V5.3: 表格编辑/保存按钮（V6.0: 保存后自动退出编辑模式，移除独立退出按钮）
            ActionButton {
                id: btnEditMode
                objectName: "btnEditMode"
                buttonType: "primary"
                text: "编辑"
                font.pixelSize: 12; implicitHeight: 28
                visible: AppState && AppState.currentProjectId !== "" && !AppState.isAnalyzing
                       && (!testingPlanTable || !testingPlanTable.isEditMode)
                onClicked: {
                    if (testingPlanTable) {
                        testingPlanTable.isEditMode = true
                        if (PlanTableModel) PlanTableModel.setEditingMode(true)
                    }
                }
                ToolTip.visible: hovered
                ToolTip.text: "进入编辑模式修改送检计划表格"
            }
            ActionButton {
                id: btnSaveEdit
                objectName: "btnSaveEdit"
                buttonType: "success"
                text: "保存"
                font.pixelSize: 12; implicitHeight: 28
                visible: testingPlanTable && testingPlanTable.isEditMode && AppState && AppState.currentProjectId !== ""
                onClicked: {
                    if (PlanTableModel && AppState) {
                        var cells = PlanTableModel.getModifiedCells()
                        if (cells && cells.length > 0) {
                            AppState.saveEditingChanges(cells)
                        }
                        PlanTableModel.clearModifiedCells()
                        testingPlanTable.isEditMode = false
                        PlanTableModel.setEditingMode(false)
                    }
                }
                ToolTip.visible: hovered
                ToolTip.text: "保存编辑并退出编辑模式"
            }

            // V5.2: 参考标准库按钮
            ActionButton {
                objectName: "btnStandards"
                buttonType: "toolbar"; text: "📋"; font.pixelSize: 16
                implicitWidth: 32; implicitHeight: 32
                onClicked: { if (AppState) AppState.openStandardsWindow() }
                ToolTip.visible: hovered
                ToolTip.text: "参考标准库 (GB/JTG/CJJ)"
            }

            ActionButton {
                objectName: "btnSettings"
                buttonType: "toolbar"; text: "⚙"; font.pixelSize: 18
                implicitWidth: 32; implicitHeight: 32
                onClicked: settingsPanel.open()
            }

            // V4.9.3: 错误日志按钮 → 弹出独立窗口
            ActionButton {
                id: errorBtn
                objectName: "btnErrorLog"
                buttonType: "toolbar"
                text: AppState && AppState.errorLogCount > 0 ? "⚠ " + AppState.errorLogCount : "⚠"
                font.pixelSize: 14
                implicitWidth: AppState && AppState.errorLogCount > 0 ? 48 : 32
                implicitHeight: 32
                visible: true
                onClicked: errorLogPopup.open()
                ToolTip.visible: hovered
                ToolTip.text: "错误日志"
            }
        }
    }

    // ── V6.1.1: ColumnLayout 包裹更新提示条 + 2-column 布局 ──
    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // V6.1: 更新提示条
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: updater.visible ? 36 : 0
            visible: AppState && AppState.updateAvailable
            id: updater
            color: AppTheme.warningBg
            RowLayout {
                anchors.fill: parent
                anchors.margins: 6
                Label {
                    text: "发现新版本 v" + (AppState.updateVersion || "") + " | 当前 v" + AppState.appVersion
                    color: AppTheme.textPrimary
                    font.pixelSize: AppTheme.fontSizeSm
                }
                Item { Layout.fillWidth: true }
                Rectangle {
                    height: 24; radius: 12
                    width: updateBtnText.implicitWidth + 20
                    color: AppTheme.accent
                    Label {
                        id: updateBtnText
                        anchors.centerIn: parent
                        text: "立即更新"
                        font.pixelSize: AppTheme.fontSizeSm
                        color: AppTheme.textOnAccent
                    }
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            var r = AppState.downloadUpdate()
                            if (r && r.ok) AppState.installUpdate(r.path)
                        }
                    }
                }
                Label {
                    text: "忽略"
                    font.pixelSize: AppTheme.fontSizeSm
                    color: AppTheme.textSecondary
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: AppState.dismissUpdate()
                    }
                }
            }
        }

        // ── 2-column RowLayout ──
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            // Left: ProjectTree
            ProjectTree {
            id: projectTree
            objectName: "projectTree"
            Layout.preferredWidth: 260
            Layout.minimumWidth: 260
            Layout.maximumWidth: 260
            Layout.fillHeight: true

            onProjectSelected: function(projectId) {
                if (AppState) AppState.currentProjectId = projectId
                if (FileListModel) FileListModel.refresh(projectId)
                if (SectionListModel) SectionListModel.refresh(projectId)
                if (PlanTableModel) {
                    PlanTableModel.loadFromDatabase(projectId)
                    testingPlanTable.totalRows = PlanTableModel.rowCount()
                }
                if (processFlow) {
                    processFlow.projectId = projectId
                }
            }
        }

        // Right: SectionCards + TabBar + StackLayout
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            // ── 路段选择卡片 ────
            RoundedCard {
                id: sectionCards
                objectName: "sectionCards"
                Layout.fillWidth: true
                Layout.preferredHeight: 120
                Layout.minimumHeight: 120
                Layout.maximumHeight: 120
                shadowEnabled: true
                padding: AppTheme.spacing

                property bool hasSelection: false

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: sectionCards.padding
                    spacing: AppTheme.spacingSm

                    RowLayout {
                        Layout.fillWidth: true
                        Label {
                            text: "路段选择"
                            font.pixelSize: AppTheme.fontSize
                            font.bold: true
                            color: AppTheme.textPrimary
                            Layout.fillWidth: true
                        }
                        ActionButton {
                            buttonType: "toolbar"; text: "全选"
                            font.pixelSize: AppTheme.fontSizeSm; implicitHeight: 26
                            onClicked: {
                                if (SectionListModel) SectionListModel.selectAll()
                                sectionCards.hasSelection = true
                            }
                        }
                        ActionButton {
                            buttonType: "toolbar"; text: "全不选"
                            font.pixelSize: AppTheme.fontSizeSm; implicitHeight: 26
                            onClicked: {
                                if (SectionListModel) SectionListModel.deselectAll()
                                sectionCards.hasSelection = false
                            }
                        }
                    }

                    ListView {
                        id: sectionCardsList
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        orientation: ListView.Horizontal
                        clip: true
                        spacing: AppTheme.spacing
                        model: SectionListModel
                        ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }

                        delegate: Rectangle {
                            id: card
                            width: 140; height: 56
                            radius: AppTheme.radius
                            clip: true
                            border.width: card.sel ? 2 : 1
                            border.color: card.sel ? AppTheme.accent : AppTheme.border
                            color: card.sel ? AppTheme.selection : AppTheme.bgSurface

                            property bool sel: model.selected || false

                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    if (SectionListModel) {
                                        SectionListModel.toggleSection(index)
                                        sectionCards.hasSelection = SectionListModel.hasAnySelected()
                                    }
                                }
                            }

                            ColumnLayout {
                                anchors.centerIn: parent
                                width: parent.width - 8
                                spacing: 2

                                Label {
                                    text: sectionName || ""
                                    font.pixelSize: 10
                                    font.bold: true
                                    color: AppTheme.textPrimary
                                    horizontalAlignment: Text.AlignHCenter
                                    Layout.fillWidth: true
                                    elide: Text.ElideRight
                                }

                                Rectangle {
                                    Layout.alignment: Qt.AlignHCenter
                                    width: 36; height: 16; radius: 3
                                    color: {
                                        if (leftRight === "左幅") return AppTheme.badgeLeft
                                        if (leftRight === "右幅") return AppTheme.badgeRight
                                        return AppTheme.badgeNeutral
                                    }
                                    Label {
                                        anchors.centerIn: parent
                                        text: leftRight || "双侧"
                                        font.pixelSize: 8
                                        color: {
                                            if (leftRight === "左幅") return AppTheme.badgeTextLeft
                                            if (leftRight === "右幅") return AppTheme.badgeTextRight
                                            return AppTheme.badgeTextNeutral
                                        }
                                    }
                                }
                            }
                        }

                        // Empty state
                        Label {
                            anchors.centerIn: parent
                            text: AppState && AppState.isAnalyzing
                                  ? "正在分析..."
                                  : "暂无路段，AI 分析后自动生成"
                            color: AppState && AppState.isAnalyzing ? AppTheme.accent : AppTheme.textDisabled
                            font.pixelSize: AppTheme.fontSizeSm
                            visible: SectionListModel && SectionListModel.isEmpty
                        }
                    }
                }
            }

            // ── Tab Bar (V4.7) ────
            TabBar {
                id: viewTabBar
                objectName: "mainTabBar"
                Layout.fillWidth: true
                background: Rectangle {
                    color: AppTheme.bgSurface
                    Rectangle {
                        anchors.bottom: parent.bottom
                        width: parent.width; height: 1
                        color: AppTheme.border
                    }
                }

                TabButton {
                    text: "送检计划表"
                    font.pixelSize: AppTheme.fontSizeSm
                }
                TabButton {
                    text: "工序流程"
                    font.pixelSize: AppTheme.fontSizeSm
                }
            }

            StackLayout {
                id: viewStack
                objectName: "viewStack"
                Layout.fillWidth: true
                Layout.fillHeight: true
                currentIndex: viewTabBar.currentIndex

                TestingPlanTable {
                    id: testingPlanTable
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                }

                // ── ProcessFlow (V5.0: 独立组件) ────
                ProcessFlow {
                    id: processFlow
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                }
            }
        }
    }

    // ── Footer ───────────────────────────────────────
    footer: Rectangle {
        height: AppTheme.statusBarHeight
        color: AppTheme.bgSurface
        border.color: AppTheme.border

        Label {
            anchors.centerIn: parent
            text: "V" + (AppState ? AppState.appVersion : "4.7.0")
            color: AppTheme.textDisabled; font.pixelSize: AppTheme.fontSizeSm
        }
    }

    SettingsPanel { id: settingsPanel }

    // ── 错误日志独立弹窗 (V4.9.3) ──────────────────
    Popup {
        id: errorLogPopup
        modal: true
        anchors.centerIn: parent
        width: 560; height: 440
        closePolicy: Popup.CloseOnEscape
        padding: 0

        background: Rectangle {
            color: AppTheme.bgSurface
            radius: AppTheme.radiusLarge
            border.color: AppTheme.border
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: AppTheme.spacingXl
            spacing: AppTheme.spacing

            // 标题栏
            RowLayout {
                Layout.fillWidth: true
                Label {
                    text: "错误日志"
                    font.pixelSize: AppTheme.fontSizeLg
                    font.bold: true
                    color: AppTheme.textPrimary
                    Layout.fillWidth: true
                }
                ActionButton {
                    buttonType: "toolbar"; text: "清空"
                    font.pixelSize: AppTheme.fontSizeSm
                    implicitWidth: 48; implicitHeight: 28
                    onClicked: { if (AppState) AppState.clearErrorLog() }
                }
                ActionButton {
                    buttonType: "toolbar"; text: "✕"
                    font.pixelSize: 14; implicitWidth: 32; implicitHeight: 32
                    onClicked: errorLogPopup.close()
                }
            }

            // 表头
            RowLayout {
                Layout.fillWidth: true; spacing: 8
                Label { text: "时间"; font.pixelSize: AppTheme.fontSizeSm; font.bold: true;
                        color: AppTheme.textDisabled; Layout.preferredWidth: 60 }
                Label { text: "级别"; font.pixelSize: AppTheme.fontSizeSm; font.bold: true;
                        color: AppTheme.textDisabled; Layout.preferredWidth: 70 }
                Label { text: "内容"; font.pixelSize: AppTheme.fontSizeSm; font.bold: true;
                        color: AppTheme.textDisabled; Layout.fillWidth: true }
            }

            Rectangle { Layout.fillWidth: true; height: 1; color: AppTheme.border }

            // 空状态
            Label {
                text: "暂无错误"
                font.pixelSize: AppTheme.fontSize
                color: AppTheme.textDisabled
                Layout.alignment: Qt.AlignCenter
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
                visible: !AppState || !AppState.errorLogList || AppState.errorLogList.length === 0
            }

            // 错误列表
            ListView {
                id: errorView
                Layout.fillWidth: true; Layout.fillHeight: true
                clip: true
                model: AppState ? AppState.errorLogList : []
                spacing: 4

                delegate: Rectangle {
                    width: errorView.width
                    height: Math.max(28, msgLabel.implicitHeight + 8)
                    radius: 4
                    color: index % 2 === 0 ? AppTheme.bgMain : AppTheme.bgHover

                    RowLayout {
                        anchors.fill: parent; anchors.margins: 4
                        spacing: 8
                        Label {
                            text: modelData ? modelData.time || "" : ""
                            font.pixelSize: AppTheme.fontSizeSm
                            color: AppTheme.textDisabled
                            Layout.preferredWidth: 60
                        }
                        Rectangle {
                            width: 8; height: 8; radius: 4
                            color: (modelData && modelData.level === "分析错误") ? AppTheme.logLevelError : AppTheme.logLevelWarning
                        }
                        Label {
                            text: modelData ? (modelData.level || "") : ""
                            font.pixelSize: AppTheme.fontSizeSm; font.bold: true
                            color: (modelData && modelData.level === "分析错误") ? AppTheme.logLevelError : AppTheme.logLevelWarning
                            Layout.preferredWidth: 60
                        }
                        Label {
                            id: msgLabel
                            text: modelData ? (modelData.message || "") : ""
                            font.pixelSize: AppTheme.fontSizeSm
                            color: AppTheme.textSecondary
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                        }
                    }
                }
            }
        }
    }  // RowLayout (2-column)

    }  // ColumnLayout (update banner + main layout)

    // ── Connections ──────────────────────────────────
    Connections {
        target: AppState
        enabled: AppState !== null

        function onImportFinished(projectId) {
            if (FileListModel) FileListModel.refresh(projectId)
            if (SectionListModel) SectionListModel.refresh(projectId)
        }

        // V6.1.1: 导入失败错误提示
        function onImportError(projectId, errorMsg) {
            errorDialog.show("导入错误", errorMsg)
        }

        function onConversionFinished(projectId) {
            if (FileListModel) FileListModel.refresh(projectId)
        }

        function onAnalysisFinished(projectId, result) {
            if (FileListModel) FileListModel.refresh(projectId)
            if (SectionListModel) SectionListModel.refresh(projectId)
            if (PlanTableModel) {
                PlanTableModel.loadFromDatabase(projectId)
                testingPlanTable.totalRows = PlanTableModel.rowCount()
                testingPlanTable.rebuildMergeLookups()
            }
            if (processFlow) {
                processFlow.projectId = projectId
                processFlow.loadLayers()
            }
        }

        function onAnalysisError(projectId, errorMsg) {
            console.log("Analysis error:", errorMsg)
            errorDialog.show("分析失败", errorMsg)
        }

        function onExportFinished(outputPath) {
            console.log("Exported to:", outputPath)
        }

        function onExportError(errorMsg) {
            console.log("Export error:", errorMsg)
            errorDialog.show("导出失败", errorMsg)
        }

        function onProjectDeleted(projectId) {
            if (FileListModel) FileListModel.refresh("")
            if (SectionListModel) SectionListModel.refresh("")
            if (PlanTableModel) {
                PlanTableModel.loadFromDatabase("")
                testingPlanTable.totalRows = 0
            }
        }

        // V5.3: 混合文件类型提示
        function onMixedFileTypesDetected(typeCounts) {
            if (!typeCounts || typeCounts.length < 2) return
            var msg = "检测到混合文件类型:\n"
            for (var i = 0; i < typeCounts.length; i++) {
                var typeName = typeCounts[i].type
                if (typeName === "cad") typeName = "CAD图纸"
                else if (typeName === "pdf") typeName = "PDF文档"
                else if (typeName === "word") typeName = "Word文档"
                else if (typeName === "excel") typeName = "Excel表格"
                msg += "  " + typeName + ": " + typeCounts[i].count + " 个文件\n"
            }
            msg += "\nCAD 和 PDF 文件将按不同策略处理。\n导入将继续进行。"
            mixedFileDialog.show("混合文件类型", msg)
        }
    }

    // ── 路段选中 → 送检计划/工序流程联动 ────────────
    Connections {
        target: SectionListModel
        enabled: SectionListModel !== null
        function onSelectedChanged() {
            if (PlanTableModel && SectionListModel) {
                PlanTableModel.setSelectedSections(SectionListModel.getSelectedSections())
                testingPlanTable.totalRows = PlanTableModel.rowCount()
                testingPlanTable.rebuildMergeLookups()
            }
            if (processFlow && SectionListModel) {
                processFlow.selectedSections = SectionListModel.getSelectedSections()
            }
        }
    }

    // V5.3: 混合文件类型提示弹窗
    MessageDialog {
        id: mixedFileDialog
        title: "提示"
        buttons: MessageDialog.Ok
        function show(title, msg) {
            mixedFileDialog.title = title
            mixedFileDialog.text = msg
            mixedFileDialog.open()
        }
    }

    // V4.9.4: 错误提示弹窗（导出错误 / 分析错误）
    MessageDialog {
        id: errorDialog
        title: "提示"
        buttons: MessageDialog.Ok
        function show(title, msg) {
            errorDialog.title = title
            errorDialog.text = msg
            errorDialog.open()
        }
    }

    Component.onCompleted: {
        if (ProjectListModel) ProjectListModel.refresh()
    }
}
