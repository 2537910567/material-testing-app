import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import AppTheme 1.0
import AppState 1.0

/*
  SettingsPanel.qml — 设置弹出面板 (V4.9: TabBar + StackLayout)
  Tab1: 模型API — API Key 配置 + 测试连接
  Tab2: 关于 — 版本更新内容
*/

Popup {
    id: panel
    objectName: "settingsPanel"
    modal: true
    anchors.centerIn: parent
    width: 480
    height: 620
    closePolicy: Popup.CloseOnEscape

    background: Rectangle {
        color: AppTheme.bgSurface
        radius: AppTheme.radiusLarge
        border.color: AppTheme.border
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: AppTheme.spacingXl
        spacing: AppTheme.spacingLg

        // ── 标题栏 + 关闭按钮 ──────────────────
        RowLayout {
            Layout.fillWidth: true
            Label {
                text: "设置"
                font.pixelSize: AppTheme.fontSizeXl
                font.bold: true
                color: AppTheme.textPrimary
                Layout.fillWidth: true
            }
            ActionButton {
                objectName: "btnCloseSettings"
                text: "✕"
                buttonType: "toolbar"
                onClicked: { panel.close() }
                implicitWidth: 32
                implicitHeight: 32
            }
        }

        // ── TabBar ──────────────────────────
        TabBar {
            id: settingsTabBar
            Layout.fillWidth: true
            background: Rectangle {
                color: "transparent"
                Rectangle {
                    anchors.bottom: parent.bottom
                    width: parent.width; height: 1
                    color: AppTheme.border
                }
            }

            TabButton {
                text: "模型API"
                font.pixelSize: AppTheme.fontSizeSm
            }
            TabButton {
                text: "关于"
                font.pixelSize: AppTheme.fontSizeSm
            }
            TabButton {
                text: "标准"
                font.pixelSize: AppTheme.fontSizeSm
            }
        }

        StackLayout {
            id: settingsStack
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: settingsTabBar.currentIndex

            // ── Tab 1: 模型API（原有内容）──
            ColumnLayout {
                spacing: AppTheme.spacingLg

                // DeepSeek API Key
                ColumnLayout {
                    spacing: AppTheme.spacingSm
                    Label {
                        text: "DeepSeek API Key"
                        font.pixelSize: AppTheme.fontSize
                        color: AppTheme.textPrimary
                    }
                    TextField {
                        id: dsKeyField
                        Layout.fillWidth: true
                        implicitHeight: AppTheme.inputHeight
                        echoMode: TextInput.Password
                        placeholderText: "sk-..."
                        font.pixelSize: AppTheme.fontSize
                        text: ""
                    }
                    Label {
                        text: "用于文本材料分析和送检计划生成"
                        font.pixelSize: AppTheme.fontSizeSm
                        color: AppTheme.textSecondary
                    }
                }

                // Qwen-VL API Key
                ColumnLayout {
                    spacing: AppTheme.spacingSm
                    Label {
                        text: "Qwen-VL API Key (DashScope)"
                        font.pixelSize: AppTheme.fontSize
                        color: AppTheme.textPrimary
                    }
                    TextField {
                        id: qwenKeyField
                        Layout.fillWidth: true
                        implicitHeight: AppTheme.inputHeight
                        echoMode: TextInput.Password
                        placeholderText: "sk-..."
                        font.pixelSize: AppTheme.fontSize
                        text: ""
                    }
                    Label {
                        text: "用于横断面图视觉分析"
                        font.pixelSize: AppTheme.fontSizeSm
                        color: AppTheme.textSecondary
                    }
                }

                // V6.0: 模型选择
                ColumnLayout {
                    spacing: AppTheme.spacingSm
                    Label {
                        text: "DeepSeek 模型"
                        font.pixelSize: AppTheme.fontSize
                        color: AppTheme.textPrimary
                    }
                    ComboBox {
                        id: dsModelCombo
                        Layout.fillWidth: true
                        model: AppState.deepseekModels
                        textRole: "id"
                        currentIndex: {
                            var m = AppState.deepseekModels
                            for (var i = 0; i < m.length; i++) {
                                if (m[i].id === AppState.currentDeepseekModel) return i
                            }
                            return m.length > 0 ? 0 : -1
                        }
                        onCurrentIndexChanged: {
                            if (currentIndex >= 0) {
                                AppState.switchDeepseekModel(model[currentIndex].id)
                            }
                        }
                    }
                }

                ColumnLayout {
                    spacing: AppTheme.spacingSm
                    Label {
                        text: "Qwen-VL 模型"
                        font.pixelSize: AppTheme.fontSize
                        color: AppTheme.textPrimary
                    }
                    ComboBox {
                        id: qwenModelCombo
                        Layout.fillWidth: true
                        model: AppState.qwenModels
                        textRole: "id"
                        currentIndex: {
                            var m = AppState.qwenModels
                            for (var i = 0; i < m.length; i++) {
                                if (m[i].id === AppState.currentQwenModel) return i
                            }
                            return m.length > 0 ? 0 : -1
                        }
                        onCurrentIndexChanged: {
                            if (currentIndex >= 0) {
                                AppState.switchQwenModel(model[currentIndex].id)
                            }
                        }
                    }
                }

                // V6.0: 刷新模型列表按钮
                RowLayout {
                    ActionButton {
                        buttonType: "toolbar"
                        text: AppState.modelsLoading ? "刷新中..." : "🔄 刷新可用模型列表"
                        enabled: !AppState.modelsLoading
                        onClicked: { AppState.fetchModels() }
                    }
                }

                // 测试连接 (V5.2: 同步返回结果)
                RowLayout {
                    spacing: AppTheme.spacing

                    ActionButton {
                        buttonType: "toolbar"
                        text: "测试连接"
                        onClicked: {
                            if (AppState) {
                                testStatusLine1.visible = true
                                testStatusLine2.visible = true
                                testStatusLine1.text = "正在测试..."
                                testStatusLine1.color = AppTheme.accent
                                testStatusLine2.text = ""
                                var r = AppState.testConnection(dsKeyField.text, qwenKeyField.text)
                                if (!r) {
                                    testStatusLine1.text = "❌ 连接测试失败（无响应）"
                                    testStatusLine1.color = AppTheme.danger
                                    testStatusLine2.text = ""
                                    return
                                }
                                testStatusLine1.text = (r["ds_ok"] ? "✅ DeepSeek: 连接成功" : "❌ DeepSeek: " + (r["ds_msg"] || "失败"))
                                testStatusLine2.text = (r["qwen_ok"] ? "✅ Qwen-VL: 连接成功" : "❌ Qwen-VL: " + (r["qwen_msg"] || "失败"))
                                testStatusLine1.color = r["ds_ok"] ? AppTheme.cta : AppTheme.danger
                                testStatusLine2.color = r["qwen_ok"] ? AppTheme.cta : AppTheme.danger
                            }
                        }
                    }

                    ColumnLayout {
                        spacing: 0
                        Label {
                            id: testStatusLine1
                            visible: false
                            font.pixelSize: AppTheme.fontSizeSm
                            color: AppTheme.textSecondary
                            Layout.fillWidth: true
                            elide: Text.ElideRight
                        }
                        Label {
                            id: testStatusLine2
                            visible: false
                            font.pixelSize: AppTheme.fontSizeSm
                            color: AppTheme.textSecondary
                            Layout.fillWidth: true
                            elide: Text.ElideRight
                        }
                    }
                }

                // 按钮
                RowLayout {
                    Layout.alignment: Qt.AlignRight
                    spacing: AppTheme.spacing

                    ActionButton {
                        buttonType: "danger"
                        text: "清空密钥"
                        onClicked: {
                            dsKeyField.text = ""
                            qwenKeyField.text = ""
                            if (AppState) AppState.configureApiKey("", "")
                        }
                    }

                    ActionButton {
                        text: "取消"
                        flat: true
                        onClicked: { panel.close() }
                    }

                    ActionButton {
                        buttonType: "primary"
                        text: "保存"
                        onClicked: {
                            if (AppState) {
                                AppState.configureApiKey(dsKeyField.text, qwenKeyField.text)
                            }
                            panel.close()
                        }
                    }
                }
            }

            // ── Tab 2: 关于 ──
            ColumnLayout {
                spacing: AppTheme.spacingLg

                Label {
                    text: "工程材料送检分析系统"
                    font.pixelSize: AppTheme.fontSize
                    font.bold: true
                    color: AppTheme.textPrimary
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    color: AppTheme.bgMain
                    radius: AppTheme.radius
                    border.color: AppTheme.border

                    Flickable {
                        anchors.fill: parent
                        anchors.margins: AppTheme.spacingLg
                        contentHeight: aboutContent.implicitHeight
                        clip: true

                        Label {
                            id: aboutContent
                            width: parent.width
                            text: AppState ? AppState.getAboutInfo() : "加载中..."
                            font.pixelSize: AppTheme.fontSizeSm
                            color: AppTheme.textSecondary
                            wrapMode: Text.WordWrap
                            lineHeight: 1.6
                        }
                    }
                }
            }

            // ── Tab 3: 标准年度替换 (V5.3) ──
            ColumnLayout {
                spacing: AppTheme.spacingLg

                Label {
                    text: "标准年度替换"
                    font.pixelSize: AppTheme.fontSize
                    font.bold: true
                    color: AppTheme.textPrimary
                }

                Label {
                    text: "选择标准更新文件（JSON格式），\n自动匹配同系列旧标准并生成替换预览。"
                    font.pixelSize: AppTheme.fontSizeSm
                    color: AppTheme.textSecondary
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }

                ActionButton {
                    text: "选择文件并预览"
                    buttonType: "primary"
                    font.pixelSize: AppTheme.fontSizeSm
                    onClicked: {
                        // QML 不支持原生文件选择器，使用 Python 端处理
                        if (AppState) {
                            var result = AppState.importStandardsUpdate(standardsFilePath.text)
                            if (result && result.ok) {
                                standardsPreview.text = result.preview || ""
                                standardsStatus.text = "完成: 替换 " + (result.replaced || 0) + " 项, 新增 " + (result.added || 0) + " 项"
                                standardsStatus.color = AppTheme.success || "#4CAF50"
                            } else if (result) {
                                standardsPreview.text = result.preview || ""
                                standardsStatus.text = result.error || "导入失败"
                                standardsStatus.color = AppTheme.error || "#F44336"
                            }
                        }
                    }
                }

                TextField {
                    id: standardsFilePath
                    Layout.fillWidth: true
                    placeholderText: "标准更新文件路径 (JSON)"
                    font.pixelSize: AppTheme.fontSizeSm
                }

                Label {
                    id: standardsStatus
                    text: ""
                    font.pixelSize: AppTheme.fontSizeSm
                    color: AppTheme.textSecondary
                    Layout.fillWidth: true
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    color: AppTheme.bgMain
                    radius: AppTheme.radius
                    border.color: AppTheme.border

                    Flickable {
                        anchors.fill: parent
                        anchors.margins: AppTheme.spacing
                        contentHeight: standardsPreview.implicitHeight
                        clip: true

                        Label {
                            id: standardsPreview
                            width: parent.width
                            text: "预览将在此显示..."
                            font.pixelSize: AppTheme.fontSizeSm
                            color: AppTheme.textSecondary
                            wrapMode: Text.WordWrap
                            font.family: "Courier New"
                        }
                    }
                }
            }
        }
    }

    // 打开时加载已保存的 Key（自动回填）
    onOpened: {
        if (AppState) {
            var keys = AppState.getApiKeys()
            var ds = keys["ds_key"] || ""
            var qw = keys["qwen_key"] || ""
            if (ds) {
                dsKeyField.text = ds
                dsKeyField.placeholderText = "已保存 (输入新值覆盖)"
            }
            if (qw) {
                qwenKeyField.text = qw
                qwenKeyField.placeholderText = "已保存 (输入新值覆盖)"
            }
            // V6.0: 打开面板时自动刷新可用模型列表
            AppState.fetchModels()
        }
    }
}
