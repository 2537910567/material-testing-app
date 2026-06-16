import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import AppTheme 1.0
import AppState 1.0

// ── ProcessFlow — 施工检测工序流程 (V5.0: 从 main.qml 抽取为独立组件) ──
// 4 级结构: 路段 → 施工层 → 工序 + 材料 + 检测

RoundedCard {
    id: processFlow
    shadowEnabled: true
    padding: AppTheme.spacing

    property string projectId: ""
    property var selectedSections: []
    property var layersData: []

    function loadLayers() {
        if (!AppState || !processFlow.projectId || processFlow.selectedSections.length === 0) {
            processFlow.layersData = []
            return
        }
        var allLayers = []
        for (var i = 0; i < processFlow.selectedSections.length; i++) {
            var sec = processFlow.selectedSections[i]
            var sectionName = sec.sectionName || ""
            if (!sectionName) continue
            var layers = AppState.getConstructionLayers(processFlow.projectId, sectionName)
            if (layers && layers.length > 0) {
                var lr = sec.roadOrientation || ""
                allLayers.push({
                    sectionName: sectionName,
                    leftRight: lr,
                    layers: layers
                })
            }
        }
        processFlow.layersData = allLayers
    }

    onSelectedSectionsChanged: loadLayers()
    onProjectIdChanged: loadLayers()

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: processFlow.padding
        spacing: AppTheme.spacingSm

        RowLayout {
            Layout.fillWidth: true
            Label {
                text: "施工检测工序流程"
                font.pixelSize: AppTheme.fontSizeLg
                font.bold: true
                color: AppTheme.textPrimary
                Layout.fillWidth: true
            }
        }

        // 空状态占位
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: processFlow.layersData.length === 0

            Label {
                anchors.centerIn: parent
                text: processFlow.projectId
                      ? (processFlow.selectedSections.length === 0
                         ? "请在上方路段卡片中选择路段"
                         : (processFlow.layersData.length === 0
                            ? "暂无工序流程数据，请先进行 AI 分析"
                            : ""))
                      : "请先选择一个项目"
                color: AppTheme.textDisabled
                font.pixelSize: AppTheme.fontSize
                horizontalAlignment: Text.AlignHCenter
            }
        }

        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            visible: processFlow.layersData.length > 0
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            ColumnLayout {
                width: parent ? parent.width : 400
                spacing: AppTheme.spacing

                Repeater {
                    model: processFlow.layersData

                    // ── L1: 路段容器 ──
                    delegate: Rectangle {
                        id: sectionContainer
                        Layout.fillWidth: true
                        Layout.preferredHeight: sectionContainer.secExpanded
                                ? (sectionColumn.implicitHeight + AppTheme.spacing * 2)
                                : 36
                        color: "transparent"
                        border.width: 1
                        border.color: AppTheme.border
                        radius: AppTheme.radius

                        property string secName: modelData.sectionName || ""
                        property string lr: modelData.leftRight || "双侧"
                        property bool secExpanded: true

                        Behavior on height { NumberAnimation { duration: 120 } }

                        ColumnLayout {
                            id: sectionColumn
                            anchors.fill: parent
                            anchors.margins: AppTheme.spacing
                            spacing: AppTheme.spacingSm

                            RowLayout {
                                spacing: AppTheme.spacingSm
                                Label {
                                    text: sectionContainer.secExpanded ? "▼" : "▶"
                                    font.pixelSize: 10
                                    color: AppTheme.textSecondary
                                }
                                Label {
                                    text: sectionContainer.secName
                                    font.pixelSize: AppTheme.fontSize
                                    font.bold: true
                                    color: AppTheme.textPrimary
                                }
                                Rectangle {
                                    width: 36; height: 18; radius: 4
                                    color: {
                                        if (sectionContainer.lr === "左幅") return AppTheme.badgeLeft
                                        if (sectionContainer.lr === "右幅") return AppTheme.badgeRight
                                        return AppTheme.badgeNeutral
                                    }
                                    Label {
                                        anchors.centerIn: parent
                                        text: sectionContainer.lr
                                        font.pixelSize: 9
                                        color: {
                                            if (sectionContainer.lr === "左幅") return AppTheme.badgeTextLeft
                                            if (sectionContainer.lr === "右幅") return AppTheme.badgeTextRight
                                            return AppTheme.badgeTextNeutral
                                        }
                                    }
                                }
                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: { sectionContainer.secExpanded = !sectionContainer.secExpanded }
                                }
                            }

                            ColumnLayout {
                                visible: sectionContainer.secExpanded
                                spacing: 4

                                Repeater {
                                    model: modelData.layers || []

                                    // ── L2: 施工层 ──
                                    delegate: Rectangle {
                                        id: layerDelegate
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: layerDelegate.layerExpanded ? (layerColumn.implicitHeight + 8) : 36
                                        color: AppTheme.bgHover
                                        radius: AppTheme.radiusSmall

                                        property bool layerExpanded: true
                                        property var layerData: modelData
                                        Behavior on height { NumberAnimation { duration: 120 } }

                                        ColumnLayout {
                                            id: layerColumn
                                            anchors.fill: parent
                                            anchors.margins: 8
                                            spacing: 4

                                            RowLayout {
                                                spacing: 6
                                                Label {
                                                    text: layerDelegate.layerExpanded ? "▼" : "▶"
                                                    font.pixelSize: 9
                                                    color: AppTheme.textSecondary
                                                }
                                                Rectangle {
                                                    width: 22; height: 18; radius: 4
                                                    color: AppTheme.accent
                                                    Label {
                                                        anchors.centerIn: parent
                                                        text: layerDelegate.layerData.step || "?"
                                                        font.pixelSize: 9; font.bold: true
                                                        color: AppTheme.textOnAccent
                                                    }
                                                }
                                                Label {
                                                    text: (layerDelegate.layerData.layer_name || "未命名层")
                                                    font.pixelSize: AppTheme.fontSizeSm
                                                    font.bold: true
                                                    color: AppTheme.textPrimary
                                                    Layout.fillWidth: true
                                                    elide: Text.ElideRight
                                                }
                                                Rectangle {
                                                    visible: (layerDelegate.layerData.thickness || "") !== ""
                                                    width: Math.min(thicknessLabel.implicitWidth + 12, 120)
                                                    height: 16; radius: 3
                                                    color: AppTheme.bgSurface
                                                    Label {
                                                        id: thicknessLabel
                                                        text: layerDelegate.layerData.thickness || ""
                                                        font.pixelSize: 9
                                                        color: AppTheme.textSecondary
                                                        anchors.verticalCenter: parent.verticalCenter
                                                        anchors.left: parent.left
                                                        anchors.leftMargin: 6
                                                        anchors.right: parent.right
                                                        anchors.rightMargin: 6
                                                        elide: Text.ElideRight
                                                    }
                                                }
                                                MouseArea {
                                                    anchors.fill: parent
                                                    cursorShape: Qt.PointingHandCursor
                                                    onClicked: { layerDelegate.layerExpanded = !layerDelegate.layerExpanded }
                                                }
                                            }

                                            ColumnLayout {
                                                visible: layerDelegate.layerExpanded
                                                spacing: 2

                                                RowLayout {
                                                    visible: (layerDelegate.layerData.construction_process || "") !== ""
                                                    spacing: 4
                                                    Label {
                                                        text: "施工工序:"
                                                        font.pixelSize: 9
                                                        font.bold: true
                                                        color: AppTheme.textSecondary
                                                    }
                                                    Label {
                                                        text: layerDelegate.layerData.construction_process || ""
                                                        font.pixelSize: 9
                                                        color: AppTheme.accent
                                                        wrapMode: Text.WordWrap
                                                        Layout.fillWidth: true
                                                    }
                                                }

                                                // ── L3: 施工步骤 (Procedures) ──
                                                Repeater {
                                                    model: layerDelegate.layerData.procedures || []
                                                    delegate: Rectangle {
                                                        Layout.fillWidth: true
                                                        height: procColumn.implicitHeight + 8
                                                        color: AppTheme.bgHover
                                                        radius: 4
                                                        border.width: 1
                                                        border.color: AppTheme.selection

                                                        ColumnLayout {
                                                            id: procColumn
                                                            anchors.fill: parent
                                                            anchors.margins: 6
                                                            spacing: 3

                                                            RowLayout {
                                                                spacing: 4
                                                                Rectangle {
                                                                    width: 20; height: 16; radius: 4
                                                                    color: AppTheme.cta
                                                                    Label {
                                                                        anchors.centerIn: parent
                                                                        text: modelData.step_order ? modelData.step_order : "?"
                                                                        font.pixelSize: 8; font.bold: true
                                                                        color: AppTheme.textOnAccent
                                                                    }
                                                                }
                                                                Label {
                                                                    text: modelData.step_name || ""
                                                                    font.pixelSize: 10; font.bold: true
                                                                    color: AppTheme.textPrimary
                                                                    Layout.fillWidth: true
                                                                    wrapMode: Text.WordWrap
                                                                }
                                                                Label {
                                                                    text: (modelData.applicable_standards || "") !== ""
                                                                          ? modelData.applicable_standards : ""
                                                                    font.pixelSize: 8
                                                                    color: AppTheme.textDisabled
                                                                    visible: (modelData.applicable_standards || "") !== ""
                                                                }
                                                            }
                                                            RowLayout {
                                                                visible: (modelData.step_description || "") !== ""
                                                                spacing: 4
                                                                Label {
                                                                    text: "操作:"
                                                                    font.pixelSize: 8; font.bold: true
                                                                    color: AppTheme.textSecondary
                                                                }
                                                                Label {
                                                                    text: modelData.step_description || ""
                                                                    font.pixelSize: 8
                                                                    color: AppTheme.textPrimary
                                                                    wrapMode: Text.WordWrap
                                                                    Layout.fillWidth: true
                                                                }
                                                            }
                                                            RowLayout {
                                                                visible: (modelData.key_points || "") !== ""
                                                                spacing: 4
                                                                Label {
                                                                    text: "要点:"
                                                                    font.pixelSize: 8; font.bold: true
                                                                    color: AppTheme.warning
                                                                }
                                                                Label {
                                                                    text: modelData.key_points || ""
                                                                    font.pixelSize: 8
                                                                    color: AppTheme.textSecondary
                                                                    wrapMode: Text.WordWrap
                                                                    Layout.fillWidth: true
                                                                }
                                                            }
                                                        }
                                                    }
                                                }

                                                // ── L3: 材料 ──
                                                Repeater {
                                                    model: layerDelegate.layerData.materials || []
                                                    delegate: RowLayout {
                                                        spacing: 4
                                                        Rectangle {
                                                            width: 8; height: 4; radius: 2
                                                            color: AppTheme.cta
                                                        }
                                                        Label {
                                                            text: "材料:"
                                                            font.pixelSize: 9
                                                            font.bold: true
                                                            color: AppTheme.textSecondary
                                                        }
                                                        Label {
                                                            text: (modelData.name || modelData.material_name || "") +
                                                                  ((modelData.spec || "") !== "" ? " (" + modelData.spec + ")" : "")
                                                            font.pixelSize: 9
                                                            color: AppTheme.textPrimary
                                                        }
                                                    }
                                                }

                                                // ── L3: 检测 ──
                                                Repeater {
                                                    model: layerDelegate.layerData.tests || []
                                                    delegate: Rectangle {
                                                        Layout.fillWidth: true
                                                        height: testColumn.implicitHeight + 8
                                                        color: AppTheme.bgSurface
                                                        radius: 3
                                                        border.width: 1
                                                        border.color: AppTheme.border

                                                        ColumnLayout {
                                                            id: testColumn
                                                            anchors.fill: parent
                                                            anchors.margins: 4
                                                            spacing: 3

                                                            RowLayout {
                                                                spacing: 4
                                                                Label {
                                                                    text: "检测"
                                                                    font.pixelSize: 8
                                                                    font.bold: true
                                                                    color: AppTheme.textOnAccent
                                                                    leftPadding: 4; rightPadding: 4
                                                                    topPadding: 1; bottomPadding: 1
                                                                    background: Rectangle {
                                                                        color: AppTheme.danger
                                                                        radius: 3
                                                                    }
                                                                }
                                                                Label {
                                                                    text: (modelData.test_item || "") +
                                                                          ((modelData.test_param || "") !== "" ? " | " + modelData.test_param : "")
                                                                    font.pixelSize: 9
                                                                    font.bold: true
                                                                    color: AppTheme.textPrimary
                                                                    elide: Text.ElideRight
                                                                    Layout.fillWidth: true
                                                                }
                                                            }
                                                            RowLayout {
                                                                spacing: 4
                                                                visible: (modelData.timing || modelData.frequency || modelData.standard || "") !== ""
                                                                Label {
                                                                    text: (modelData.timing || "") !== "" ? "⏱" + modelData.timing : ""
                                                                    font.pixelSize: 8
                                                                    color: AppTheme.textSecondary
                                                                    visible: (modelData.timing || "") !== ""
                                                                }
                                                                Label {
                                                                    text: (modelData.frequency || "") !== "" ? "📋" + modelData.frequency : ""
                                                                    font.pixelSize: 8
                                                                    color: AppTheme.textSecondary
                                                                    visible: (modelData.frequency || "") !== ""
                                                                }
                                                                Label {
                                                                    text: modelData.standard || ""
                                                                    font.pixelSize: 8
                                                                    color: AppTheme.accent
                                                                    elide: Text.ElideRight
                                                                    Layout.fillWidth: true
                                                                    visible: (modelData.standard || "") !== ""
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
                    }
                }
            }
        }
    }
}
