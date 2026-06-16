import QtQuick
import QtQuick.Controls
import AppTheme 1.0

Button {
    id: btn

    /*
      buttonType values:
        ""          — default (flat surface)
        "toolbar"   — icon-only, transparent bg, 32×32
        "primary"   — accent bg, white text (main actions)
        "success"   — green bg, white text (export)
        "danger"    — red bg, white text (delete)
        "warning"   — amber bg, white text
    */
    property string buttonType: ""

    font.pixelSize: AppTheme.fontSize
    flat: buttonType === "toolbar"
    leftPadding: AppTheme.spacingLg
    rightPadding: AppTheme.spacingLg
    topPadding: AppTheme.spacingSm
    bottomPadding: AppTheme.spacingSm
    implicitHeight: AppTheme.buttonHeight
    hoverEnabled: true

    // foreground (text) color
    readonly property color _fg: {
        if (!enabled) return AppTheme.textDisabled
        switch (btn.buttonType) {
            case "primary":
            case "success":
            case "danger":
            case "warning":
                return AppTheme.textOnAccent
            default:
                return AppTheme.textPrimary
        }
    }

    readonly property color _bg: {
        if (!enabled) return AppTheme.bgSurface
        switch (btn.buttonType) {
            case "primary":  return btn.hovered ? AppTheme.accentHover : AppTheme.accent
            case "success":  return btn.hovered ? AppTheme.successHover : AppTheme.success
            case "danger":   return AppTheme.danger
            case "warning":  return AppTheme.warning
            case "toolbar":  return btn.hovered ? AppTheme.bgHover : "transparent"
            default:         return AppTheme.bgSurface
        }
    }

    // V4.5.4: 显式 background + contentItem，替代不稳定的 palette 块
    // 解决 Windows PySide6 下 toolbar 按钮文字颜色不可见的问题
    background: Rectangle {
        color: btn._bg
        radius: AppTheme.radiusSmall
        border.color: btn.buttonType === "toolbar" ? "transparent" : AppTheme.border
        border.width: btn.buttonType === "" ? 1 : 0
    }

    contentItem: Label {
        text: btn.text
        font: btn.font
        color: btn._fg
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }
}
