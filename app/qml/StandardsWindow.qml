import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// V6.1: 全部颜色硬编码 — 独立 QQmlApplicationEngine 无法解析 AppTheme 单例

ApplicationWindow {
    id: window
    title: "参考标准库"
    width: 700; height: 540
    minimumWidth: 500; minimumHeight: 360
    flags: Qt.Dialog | Qt.WindowCloseButtonHint | Qt.WindowTitleHint
    visible: true
    color: "#FAFAFA"

    // 硬编码颜色（Light Theme: shadcn Zinc）
    readonly property color cBg:          "#FAFAFA"
    readonly property color cSurface:     "#FFFFFF"
    readonly property color cBorder:      "#E4E4E7"
    readonly property color cText:        "#09090B"
    readonly property color cText2:       "#71717A"
    readonly property color cText3:       "#A1A1AA"
    readonly property color cAccent:      "#18181B"
    readonly property color cBlueBadge:   "#DBEAFE"
    readonly property color cBlueText:    "#1D4ED8"
    readonly property color cGrayBadge:   "#F4F4F5"
    readonly property color cGrayText:    "#374151"
    readonly property color cGreen:       "#16A34A"
    readonly property color cBlue:        "#2563EB"
    readonly property color cGray:        "#9CA3AF"

    property var allStandards: []
    property var filteredStandards: []
    property string searchText: ""
    property string selectedDiscipline: "全部"

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
        for (var i = 0; i < discs.length; i++)
            discModel.append({ name: discs[i], sel: discs[i] === "全部" })
    }

    function selectDisc(name) {
        for (var i = 0; i < discModel.count; i++)
            discModel.setProperty(i, "sel", discModel.get(i).name === name)
        selectedDiscipline = name
        applyFilter()
    }

    function applyFilter() {
        var result = allStandards
        if (selectedDiscipline !== "全部")
            result = result.filter(function(s) { return s.discipline === selectedDiscipline })
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
        anchors.margins: 8
        spacing: 4

        // Search + Clear
        RowLayout {
            Layout.fillWidth: true; spacing: 4
            TextField {
                id: searchField
                Layout.fillWidth: true
                placeholderText: "搜索标准编号、名称或关键词..."
                font.pixelSize: 14
                onTextChanged: { searchText = text; applyFilter() }
                background: Rectangle {
                    radius: 4; color: cSurface
                    border.width: 1; border.color: cBorder
                }
            }
            Rectangle {
                visible: searchField.text.length > 0
                width: 24; height: 24; radius: 12; color: cGrayBadge
                Label {
                    anchors.centerIn: parent
                    text: "✕"; font.pixelSize: 12; color: cText2
                }
                MouseArea {
                    anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                    onClicked: { searchField.text = ""; searchText = ""; applyFilter() }
                }
            }
        }

        // Discipline chips
        Flow {
            Layout.fillWidth: true; spacing: 4
            Repeater {
                model: discModel
                delegate: Rectangle {
                    width: t.implicitWidth + 16; height: 28; radius: 14
                    color: sel ? cAccent : cGrayBadge
                    Text {
                        id: t; anchors.centerIn: parent; text: name
                        font.pixelSize: 12; color: sel ? cBg : cText2
                    }
                    MouseArea {
                        anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                        onClicked: selectDisc(name)
                    }
                }
            }
        }

        Label {
            text: filteredStandards.length + " 本标准"
            color: cText3; font.pixelSize: 12
        }

        // Standards list
        ListView {
            id: listView
            Layout.fillWidth: true; Layout.fillHeight: true
            clip: true; model: filteredStandards; spacing: 2
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            delegate: Rectangle {
                width: listView.width; height: 72; radius: 4
                color: index % 2 === 0 ? cSurface : cBg

                // Left color strip
                Rectangle {
                    anchors.left: parent.left
                    anchors.top: parent.top; anchors.bottom: parent.bottom
                    width: 3; radius: 2
                    color: modelData.type === "国标" ? cBlue :
                           modelData.type === "行标" ? cGreen : cGray
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 10; anchors.rightMargin: 8
                    anchors.topMargin: 8; anchors.bottomMargin: 8
                    spacing: 8

                    // Code + type badge + year
                    ColumnLayout {
                        Layout.preferredWidth: 180; spacing: 2
                        RowLayout {
                            spacing: 4
                            Label {
                                text: modelData.code; font.pixelSize: 14
                                font.bold: true; color: cAccent
                            }
                            Rectangle {
                                radius: 3
                                width: typeBadge.implicitWidth + 8
                                height: typeBadge.implicitHeight + 4
                                color: modelData.type === "国标" ? cBlueBadge :
                                       modelData.type === "行标" ? cGrayBadge : cGrayBadge
                                Label {
                                    id: typeBadge; text: modelData.type || ""
                                    font.pixelSize: 10; anchors.centerIn: parent
                                    color: modelData.type === "国标" ? cBlueText : cGrayText
                                }
                            }
                        }
                        Label {
                            text: modelData.version_year || ""
                            color: cText3; font.pixelSize: 12
                        }
                    }

                    // Name + keywords
                    ColumnLayout {
                        Layout.fillWidth: true; spacing: 2
                        Label {
                            text: modelData.name; font.pixelSize: 14
                            color: cText; elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                        Label {
                            text: modelData.keywords || ""
                            font.pixelSize: 12; color: cText2
                            elide: Text.ElideRight; Layout.fillWidth: true
                        }
                    }

                    Label {
                        Layout.preferredWidth: 120
                        text: modelData.scope || ""; font.pixelSize: 12
                        color: cText3; elide: Text.ElideRight
                        visible: modelData.scope && modelData.scope.length > 0
                    }
                }
            }

            Label {
                anchors.centerIn: parent
                text: allStandards.length === 0 ? "加载中..." : "无匹配标准"
                color: cText3; font.pixelSize: 14
                visible: filteredStandards.length === 0
            }
        }
    }
}
