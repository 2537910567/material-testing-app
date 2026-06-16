import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import AppTheme 1.0

ApplicationWindow {
    id: window
    title: "参考标准库"
    width: 680
    height: 520
    minimumWidth: 500
    minimumHeight: 360
    flags: Qt.Dialog | Qt.WindowCloseButtonHint | Qt.WindowTitleHint
    visible: true
    color: AppTheme.bgMain

    property var allStandards: []
    property var filteredStandards: []
    property string searchText: ""
    property string selectedDiscipline: "全部"

    // 硬编码颜色（独立 engine 可能无法解析 AppTheme 单例）
    readonly property string chipSelBg: "#18181B"
    readonly property string chipSelFg: "#FAFAFA"
    readonly property string chipBg: "#F4F4F5"
    readonly property string chipFg: "#71717A"

    ListModel { id: discModel }

    Component.onCompleted: {
        try {
            var raw = AppState.getStandards("")
            if (raw && raw.length > 0) {
                allStandards = raw
                filteredStandards = raw
            }
        } catch(e) {
            console.log("StandardsWindow: load failed", e)
        }
        var discs = ["全部", "道路工程", "桥梁工程", "地基基础", "给排水",
                     "交通工程", "照明", "电气", "通信", "原材料",
                     "附属设施", "检测方法", "通用规范"]
        for (var i = 0; i < discs.length; i++) {
            discModel.append({ name: discs[i], sel: discs[i] === "全部" })
        }
    }

    function selectDisc(name) {
        for (var i = 0; i < discModel.count; i++) {
            discModel.setProperty(i, "sel", discModel.get(i).name === name)
        }
        selectedDiscipline = name
        applyFilter()
    }

    function applyFilter() {
        var result = allStandards
        if (selectedDiscipline !== "全部") {
            result = result.filter(function(s) {
                return s.discipline === selectedDiscipline
            })
        }
        if (searchText.trim() !== "") {
            var q = searchText.trim().toLowerCase()
            result = result.filter(function(s) {
                return (s.code && s.code.toLowerCase().indexOf(q) >= 0) ||
                       (s.name && s.name.toLowerCase().indexOf(q) >= 0) ||
                       (s.keywords && s.keywords.toLowerCase().indexOf(q) >= 0)
            })
        }
        filteredStandards = result
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: AppTheme.spacing
        spacing: AppTheme.spacingSm

        // Search
        RowLayout {
            Layout.fillWidth: true
            spacing: AppTheme.spacingSm
            TextField {
                id: searchField
                Layout.fillWidth: true
                placeholderText: "搜索标准编号、名称或关键词..."
                font.pixelSize: AppTheme.fontSize
                onTextChanged: { searchText = text; applyFilter() }
                background: Rectangle {
                    radius: AppTheme.radiusSmall
                    color: AppTheme.bgSurface
                    border.width: 1; border.color: AppTheme.border
                }
            }
            // V6.1: 清除搜索按钮
            Rectangle {
                visible: searchField.text.length > 0
                width: 24; height: 24; radius: 12
                color: AppTheme.bgHover
                Label {
                    anchors.centerIn: parent
                    text: "✕"
                    font.pixelSize: 12
                    color: AppTheme.textSecondary
                }
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: { searchField.text = ""; searchText = ""; applyFilter() }
                }
            }
        }

        // Discipline chips — Repeater + ListModel, 硬编码颜色
        Flow {
            Layout.fillWidth: true
            spacing: 4

            Repeater {
                model: discModel
                delegate: Rectangle {
                    width: t.implicitWidth + 16
                    height: 28
                    radius: 14
                    color: sel ? chipSelBg : chipBg
                    Text {
                        id: t
                        anchors.centerIn: parent
                        text: name
                        font.pixelSize: AppTheme.fontSizeSm
                        color: sel ? chipSelFg : chipFg
                    }
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: selectDisc(name)
                    }
                }
            }
        }

        Label {
            text: filteredStandards.length + " 本标准"
            color: AppTheme.textDisabled
            font.pixelSize: AppTheme.fontSizeSm
        }

        // Standards list
        ListView {
            id: listView
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: filteredStandards
            spacing: 2
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            delegate: Rectangle {
                width: listView.width
                height: 72
                radius: AppTheme.radiusSmall
                color: index % 2 === 0 ? AppTheme.bgSurface : AppTheme.bgMain

                // V6.1: 左侧类型颜色条
                Rectangle {
                    anchors.left: parent.left
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    width: 3
                    color: modelData.type === "国标" ? "#2563EB" :
                           modelData.type === "行标" ? "#16A34A" : "#9CA3AF"
                    radius: 2
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: AppTheme.spacingSm + 6
                    anchors.rightMargin: AppTheme.spacingSm
                    anchors.topMargin: AppTheme.spacingSm
                    anchors.bottomMargin: AppTheme.spacingSm
                    spacing: AppTheme.spacing

                    ColumnLayout {
                        Layout.preferredWidth: 180
                        spacing: 2
                        RowLayout {
                            spacing: AppTheme.spacingSm
                            Label {
                                text: modelData.code
                                font.pixelSize: AppTheme.fontSize; font.bold: true
                                color: AppTheme.accent
                            }
                            Rectangle {
                                radius: 3
                                width: typeLabel.implicitWidth + 8
                                height: typeLabel.implicitHeight + 4
                                color: modelData.type === "国标" ? AppTheme.badgeLeft :
                                       modelData.type === "行标" ? AppTheme.badgeNeutral : AppTheme.selection
                                Label {
                                    id: typeLabel
                                    text: modelData.type || ""
                                    anchors.centerIn: parent
                                    font.pixelSize: AppTheme.fontSizeXs || 10
                                    color: modelData.type === "国标" ? AppTheme.badgeTextLeft :
                                           modelData.type === "行标" ? AppTheme.badgeTextNeutral : AppTheme.textSecondary
                                }
                            }
                        }
                        Label {
                            text: modelData.version_year || ""
                            color: AppTheme.textDisabled
                            font.pixelSize: AppTheme.fontSizeSm
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        Label {
                            text: modelData.name
                            font.pixelSize: AppTheme.fontSize
                            color: AppTheme.textPrimary
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                        Label {
                            text: modelData.keywords || ""
                            font.pixelSize: AppTheme.fontSizeSm
                            color: AppTheme.textSecondary
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                    }

                    Label {
                        Layout.preferredWidth: 120
                        text: modelData.scope || ""
                        font.pixelSize: AppTheme.fontSizeSm
                        color: AppTheme.textDisabled
                        elide: Text.ElideRight
                        visible: modelData.scope && modelData.scope.length > 0
                    }
                }
            }

            Label {
                anchors.centerIn: parent
                text: allStandards.length === 0 ? "加载中..." : "无匹配标准"
                color: AppTheme.textDisabled
                font.pixelSize: AppTheme.fontSize
                visible: filteredStandards.length === 0
            }
        }
    }
}
