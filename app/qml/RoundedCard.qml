import QtQuick
import AppTheme 1.0

/*
  RoundedCard.qml — 通用圆角卡片容器

  所有面板应使用此组件包裹以获得一致的圆角、边框和阴影效果。
*/

Rectangle {
    id: card
    color: AppTheme.bgSurface
    radius: AppTheme.radius
    border.width: 1
    border.color: AppTheme.border

    // 内边距 — 子内容应使用此属性而非手动设置 margin
    property int padding: AppTheme.spacing

    // 是否显示阴影 — 通过下方偏移的 Rectangle 模拟
    property bool shadowEnabled: false

    // 模拟阴影层（无模糊，提供深度感）
    Rectangle {
        anchors.fill: parent
        anchors.topMargin: 2
        anchors.leftMargin: 1
        radius: card.radius
        color: AppTheme.shadowColor
        visible: card.shadowEnabled
        z: -1
    }
}
