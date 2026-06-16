import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import AppTheme 1.0
import AppState 1.0
import ProjectTreeModel 1.0

/*
  ProjectTree.qml — V4.9.4: TreeView 重构（VS Code 资源管理器风格）

  两级树结构:
    Project (项目节点, depth=0)
      └── file.dwg / file.pdf / file.docx / file.xlsx (文件叶子, depth=1)

  性能: TreeView 原生虚拟化 + delegate 回收池，即使 100 个文件也只渲染可见行。
*/

RoundedCard {
    id: panel
    objectName: "projectTreePanel"
    shadowEnabled: true
    padding: AppTheme.spacing

    signal projectSelected(string projectId)

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: panel.padding
        spacing: AppTheme.spacing

        // ── 标题栏 ───────────────────────────────────────
        RowLayout {
            Layout.fillWidth: true
            spacing: AppTheme.spacingSm

            Label {
                text: "项目列表"
                font.pixelSize: AppTheme.fontSizeLg
                font.bold: true
                color: AppTheme.textPrimary
                Layout.fillWidth: true
            }

            ActionButton {
                objectName: "btnNewProject"
                buttonType: "primary"
                text: "+"
                font.pixelSize: 18; font.bold: true
                implicitWidth: 28; implicitHeight: 28
                leftPadding: 0; rightPadding: 0
                onClicked: newProjectDialog.open()
            }
        }

        // ── TreeView ─────────────────────────────────────
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            // 空的提示（V4.9.4: 放在 TreeView 外部）
            Label {
                text: "点击 + 新建项目"
                color: AppTheme.textDisabled
                font.pixelSize: AppTheme.fontSize
                anchors.centerIn: parent
                visible: ProjectTreeModel && ProjectTreeModel.count === 0
            }

            TreeView {
                id: treeView
                objectName: "projectTreeView"
                anchors.fill: parent
                clip: true
                model: ProjectTreeModel
                selectionModel: ItemSelectionModel { model: ProjectTreeModel }
                visible: ProjectTreeModel && ProjectTreeModel.count > 0

                // 树形样式常量
                readonly property int indentWidth: 20
                readonly property int rowHeight: 28
                readonly property int twistieSize: 20

            // ── Delegate ──────────────────────────────────
            delegate: Rectangle {
                id: treeRow
                required property TreeView treeView
                required property bool isTreeNode
                required property bool expanded
                required property int hasChildren
                required property int depth
                required property int row
                required property bool current
                required property var model

                implicitWidth: treeView.width
                implicitHeight: treeView.rowHeight
                color: {
                    if (current) return AppTheme.selection
                    if (rowHover.hovered) return AppTheme.bgHover
                    return "transparent"
                }
                radius: AppTheme.radiusSmall

                // 节点类型和状态（TreeView delegate 中角色通过 model.xxx 访问）
                readonly property string nodeType: isTreeNode && hasChildren ? "project" : "file"
                readonly property bool isProject: isTreeNode && hasChildren
                readonly property string parseStatus: model.parseStatus || ""
                readonly property string conversionStatus: model.conversionStatus || ""
                readonly property bool hasAnalysis: model.hasAnalysis !== undefined ? model.hasAnalysis : false
                readonly property string projectId: model.projectId || ""

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 2 + depth * treeView.indentWidth
                    anchors.rightMargin: 4
                    spacing: 4

                    // ── 旋钮 (twistie) ────────────────────
                    Label {
                        id: twistie
                        visible: isTreeNode && hasChildren
                        text: expanded ? "❯" : "❯"
                        rotation: expanded ? 90 : 0
                        font.pixelSize: AppTheme.fontSize
                        color: AppTheme.textSecondary
                        Layout.preferredWidth: treeView.twistieSize + 6
                        Layout.alignment: Qt.AlignVCenter
                        horizontalAlignment: Text.AlignHCenter
                    }

                    // ── 状态点 (仅文件) ────────────────────
                    // 解析状态
                    Item {
                        visible: !isProject
                        Layout.preferredWidth: 10
                        implicitHeight: 16
                        Label {
                            anchors.centerIn: parent
                            text: {
                                if (model.parseStatus === "done") return "●"
                                if (model.parseStatus === "error") return "✕"
                                return "○"
                            }
                            font.pixelSize: 9
                            color: model.parseStatus === "done" ? AppTheme.success
                                   : (model.parseStatus === "error" ? AppTheme.danger : AppTheme.textDisabled)
                        }
                        HoverHandler { id: parseHover }
                        ToolTip {
                            visible: parseHover.hovered
                            text: model.parseStatus === "done" ? "解析完成"
                                  : (model.parseStatus === "error" ? "解析失败" : "待解析")
                        }
                    }
                    // 转换状态
                    Item {
                        visible: !isProject
                        Layout.preferredWidth: 10
                        implicitHeight: 16
                        Label {
                            anchors.centerIn: parent
                            text: {
                                if (model.conversionStatus === "done") return "●"
                                if (model.conversionStatus === "error") return "✕"
                                return "○"
                            }
                            font.pixelSize: 9
                            color: model.conversionStatus === "done" ? AppTheme.success
                                   : (model.conversionStatus === "error" ? AppTheme.danger : AppTheme.textDisabled)
                        }
                        HoverHandler { id: convHover }
                        ToolTip {
                            visible: convHover.hovered
                            text: model.conversionStatus === "done" ? "转换完成"
                                  : (model.conversionStatus === "error" ? "转换失败" : "待转换")
                        }
                    }
                    // AI分析状态
                    Item {
                        visible: !isProject
                        Layout.preferredWidth: 10
                        implicitHeight: 16
                        Label {
                            anchors.centerIn: parent
                            text: (model.hasAnalysis !== undefined && model.hasAnalysis) ? "●" : "○"
                            font.pixelSize: 9
                            color: (model.hasAnalysis !== undefined && model.hasAnalysis) ? AppTheme.accent : AppTheme.textDisabled
                        }
                        HoverHandler { id: aiHover }
                        ToolTip {
                            visible: aiHover.hovered
                            text: (model.hasAnalysis !== undefined && model.hasAnalysis) ? "已分析" : "未分析"
                        }
                    }

                    // ── 文件名 / 项目名 ────────────────────
                    Label {
                        text: model.displayName || model.display || ""
                        font.pixelSize: AppTheme.fontSize
                        font.bold: isProject
                        color: AppTheme.textPrimary
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }

                    // ── 专业标签 (仅文件) ──────────────────
                    Rectangle {
                        visible: !isProject && model.discipline && model.discipline !== "" && model.discipline !== "未知"
                        radius: 3
                        color: AppTheme.bgHover
                        implicitWidth: discLabel.implicitWidth + 8
                        implicitHeight: 18
                        Layout.alignment: Qt.AlignVCenter
                        Label {
                            id: discLabel
                            anchors.centerIn: parent
                            text: model.discipline || ""
                            font.pixelSize: 9
                            color: AppTheme.textSecondary
                        }
                    }
                }

                // ── 交互 ──────────────────────────────────
                HoverHandler { id: rowHover }

                TapHandler {
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    onTapped: function(eventPoint, button) {
                        treeView.selectionModel.setCurrentIndex(
                            treeView.model.index(row, 0, undefined),
                            ItemSelectionModel.ClearAndSelect)

                        if (button === Qt.RightButton) {
                            if (isProject) {
                                projectCtxMenu.projectId = model.projectId || ""
                                projectCtxMenu.projectName = model.displayName || ""
                                projectCtxMenu.row = row
                                projectCtxMenu.popup()
                            } else {
                                var fid = model.fileId || 0
                                var fpath = model.filePath || ""
                                fileCtxMenu.fileId = fid
                                fileCtxMenu.filePath = fpath
                                fileCtxMenu.fileRow = row
                                fileCtxMenu.projectId = model.projectId || ""
                                fileCtxMenu.popup()
                            }
                        } else if (button === Qt.LeftButton) {
                            if (isProject) {
                                // 整行点击 → 展开/折叠 + 选中
                                treeView.toggleExpanded(row)
                                panel.projectSelected(model.projectId || "")
                            }
                        }
                    }
                }
            }
            }
        }
    }

    // ── 新建项目对话框 ───────────────────────────────────
    Dialog {
        id: newProjectDialog
        title: "新建项目"
        modal: true; width: 320; height: 160
        parent: Overlay.overlay
        anchors.centerIn: Overlay.overlay

        background: Rectangle {
            color: AppTheme.bgSurface
            radius: AppTheme.radiusLarge
            border.color: AppTheme.border
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: AppTheme.spacing
            spacing: AppTheme.spacing
            Label { text: "项目名称:"; font.pixelSize: AppTheme.fontSizeSm }
            TextField {
                id: projectNameInput
                Layout.fillWidth: true
                placeholderText: "输入项目名称（可选，留空自动识别）"
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignHCenter
                spacing: AppTheme.spacing
                ActionButton {
                    text: "取消"; flat: true
                    onClicked: { projectNameInput.text = ""; newProjectDialog.close() }
                }
                ActionButton {
                    buttonType: "primary"
                    text: "创建"
                    onClicked: {
                        if (AppState) {
                            AppState.createProject(projectNameInput.text)
                        }
                        projectNameInput.text = ""
                        newProjectDialog.close()
                    }
                }
            }
        }
    }

    // ── 项目上下文菜单 ────────────────────────────────────
    Menu {
        id: projectCtxMenu
        objectName: "projectContextMenu"
        property string projectId: ""
        property string projectName: ""
        property int row: -1

        MenuItem { objectName: "menuImportFile"; text: "导入文件"
            onTriggered: { if (AppState && projectCtxMenu.projectId) AppState.pickAndImportFiles(projectCtxMenu.projectId) } }
        MenuSeparator {}
        MenuItem { objectName: "menuExportExcel"; text: "导出 Excel"
            onTriggered: { if (AppState && projectCtxMenu.projectId) AppState.exportExcel(projectCtxMenu.projectId, "") } }
        MenuSeparator {}
        MenuItem { objectName: "menuRenameProject"; text: "重命名"
            onTriggered: {
                renameDialog.renameId = projectCtxMenu.projectId
                renameInput.text = projectCtxMenu.projectName
                renameDialog.open()
            }
        }
        MenuItem { objectName: "menuDeleteProject"; text: "删除项目"; onTriggered: {
            deleteConfirmDialog.projectIdToDelete = projectCtxMenu.projectId
            deleteConfirmDialog.projectNameToDelete = projectCtxMenu.projectName
            deleteConfirmDialog.open()
        }}
    }

    // ── 文件上下文菜单 ────────────────────────────────────
    Menu {
        id: fileCtxMenu
        property int fileId: 0
        property string filePath: ""
        property int fileRow: -1
        property string projectId: ""

        MenuItem { text: "替换文件"
            onTriggered: { if (AppState && fileCtxMenu.projectId) AppState.replaceFile(fileCtxMenu.projectId, fileCtxMenu.fileId, fileCtxMenu.filePath) } }
        MenuItem { text: "删除文件"; onTriggered: {
            if (AppState && fileCtxMenu.projectId) AppState.deleteFile(fileCtxMenu.projectId, fileCtxMenu.fileId)
        }}
    }

    // ── 重命名对话框 ──────────────────────────────────────
    Dialog {
        id: renameDialog
        title: "重命名项目"
        modal: true; width: 320; height: 160
        parent: Overlay.overlay
        anchors.centerIn: Overlay.overlay
        property string renameId: ""

        background: Rectangle {
            color: AppTheme.bgSurface
            radius: AppTheme.radiusLarge
            border.color: AppTheme.border
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: AppTheme.spacing
            spacing: AppTheme.spacing
            Label { text: "新名称:"; font.pixelSize: AppTheme.fontSizeSm }
            TextField {
                id: renameInput; Layout.fillWidth: true
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignHCenter
                spacing: AppTheme.spacing
                ActionButton { text: "取消"; flat: true; onClicked: { renameInput.text = ""; renameDialog.close() } }
                ActionButton {
                    buttonType: "primary"; text: "确定"
                    onClicked: {
                        if (AppState && renameDialog.renameId) AppState.renameProject(renameDialog.renameId, renameInput.text)
                        renameInput.text = ""
                        renameDialog.close()
                    }
                }
            }
        }
    }

    // ── 删除确认对话框 ────────────────────────────────────
    Dialog {
        id: deleteConfirmDialog
        title: "确认删除"
        modal: true; width: 340; height: 180
        parent: Overlay.overlay
        anchors.centerIn: Overlay.overlay
        property string projectIdToDelete: ""
        property string projectNameToDelete: ""

        background: Rectangle {
            color: AppTheme.bgSurface
            radius: AppTheme.radiusLarge
            border.color: AppTheme.border
        }

        ColumnLayout {
            anchors.fill: parent; anchors.margins: AppTheme.spacing
            spacing: AppTheme.spacing
            Label {
                text: "删除项目 «" + (deleteConfirmDialog.projectNameToDelete || "") + "»？"
                font.pixelSize: AppTheme.fontSize; wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignHCenter
                Layout.fillWidth: true
            }
            Label {
                text: "所有文件和分析结果将被永久删除。"
                font.pixelSize: AppTheme.fontSizeSm; color: AppTheme.textSecondary
                wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignHCenter
                Layout.fillWidth: true
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignHCenter
                spacing: AppTheme.spacing
                ActionButton { text: "取消"; flat: true; onClicked: deleteConfirmDialog.close() }
                ActionButton {
                    buttonType: "danger"; text: "删除"
                    onClicked: {
                        if (AppState && deleteConfirmDialog.projectIdToDelete) {
                            AppState.deleteProject(deleteConfirmDialog.projectIdToDelete)
                        }
                        deleteConfirmDialog.close()
                    }
                }
            }
        }
    }

    property var _expandedPids: []

    // ── 信号监听 ─────────────────────────────────────────
    Connections {
        target: AppState
        function onProjectsChanged() {
            // 保存展开的项目 ID
            _expandedPids = []
            for (var i = 0; i < treeView.rows; i++) {
                if (treeView.isExpanded(i)) {
                    var idx = ProjectTreeModel.index(i, 0)
                    var pid = ProjectTreeModel.data(idx, 258)  // ProjectIdRole
                    if (pid) _expandedPids.push(pid)
                }
            }
            ProjectTreeModel.refresh()
            Qt.callLater(function() {
                for (var r = 0; r < treeView.rows; r++) {
                    var mi = ProjectTreeModel.index(r, 0)
                    var pi = ProjectTreeModel.data(mi, 256)
                    if (pi && _expandedPids.indexOf(pi) >= 0) {
                        treeView.expand(r)
                    }
                }
            })
        }
        function onImportFinished(projectId) {
            ProjectTreeModel.refreshProject(projectId)
        }
        function onConversionFinished(projectId) {
            ProjectTreeModel.refreshProject(projectId)
        }
        function onAnalysisFinished(projectId, result) {
            ProjectTreeModel.refreshProject(projectId)
        }
    }
}
