"""
Theme QObject — V5.2: shadcn/ui Zinc 动态主题系统

通过 context property "AppTheme" 注入 QML。
支持浅色/深色模式动态切换（themeChanged 信号驱动所有绑定更新）。

设计: shadcn Zinc — 近黑主色 + Zinc 灰度 + text-first 美学。
"""

from PySide6.QtCore import QObject, Property, Signal, Slot
from .theme_tokens import LIGHT_TOKENS, get_token_set


class ThemeObject(QObject):
    """QML 可直接访问的主题属性 — V5.2: 动态 themeChanged 驱动"""

    themeChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mode = "light"
        self._tokens = LIGHT_TOKENS.copy()

    # ── Theme mode ───────────────────────────────────

    @Slot(str)
    def setThemeMode(self, mode: str):
        if mode not in ("light", "dark"):
            return
        if mode == self._mode:
            return
        self._mode = mode
        self._tokens = get_token_set(mode)
        self.themeChanged.emit()

    @Property(str, notify=themeChanged)
    def themeMode(self):
        return self._mode

    # ── Colors: Surface ──────────────────────────────

    @Property(str, notify=themeChanged)
    def bgMain(self): return self._tokens["bgMain"]

    @Property(str, notify=themeChanged)
    def bgSurface(self): return self._tokens["bgSurface"]

    @Property(str, notify=themeChanged)
    def bgHover(self): return self._tokens["bgHover"]

    # ── Colors: Text ─────────────────────────────────

    @Property(str, notify=themeChanged)
    def textPrimary(self): return self._tokens["textPrimary"]

    @Property(str, notify=themeChanged)
    def textSecondary(self): return self._tokens["textSecondary"]

    @Property(str, notify=themeChanged)
    def textDisabled(self): return self._tokens["textDisabled"]

    @Property(str, notify=themeChanged)
    def textOnAccent(self): return self._tokens["textOnAccent"]

    # ── Colors: Borders ──────────────────────────────

    @Property(str, notify=themeChanged)
    def border(self): return self._tokens["border"]

    # ── Colors: Accent ───────────────────────────────

    @Property(str, notify=themeChanged)
    def accent(self): return self._tokens["accent"]

    @Property(str, notify=themeChanged)
    def accentHover(self): return self._tokens["accentHover"]

    @Property(str, notify=themeChanged)
    def accentPressed(self): return self._tokens["accentPressed"]

    # ── Colors: CTA ──────────────────────────────────

    @Property(str, notify=themeChanged)
    def cta(self): return self._tokens["cta"]

    @Property(str, notify=themeChanged)
    def ctaHover(self): return self._tokens["ctaHover"]

    @Property(str, notify=themeChanged)
    def ctaPressed(self): return self._tokens["ctaPressed"]

    # ── Colors: Semantic ─────────────────────────────

    @Property(str, notify=themeChanged)
    def success(self): return self._tokens["success"]

    @Property(str, notify=themeChanged)
    def successHover(self): return self._tokens["successHover"]

    @Property(str, notify=themeChanged)
    def warning(self): return self._tokens["warning"]

    @Property(str, notify=themeChanged)
    def danger(self): return self._tokens["danger"]

    # ── Colors: States ───────────────────────────────

    @Property(str, notify=themeChanged)
    def selection(self): return self._tokens["selection"]

    @Property(str, notify=themeChanged)
    def headerBg(self): return self._tokens["headerBg"]

    # ── Colors: Log Levels ───────────────────────────

    @Property(str, notify=themeChanged)
    def logLevelError(self): return self._tokens["logLevelError"]

    @Property(str, notify=themeChanged)
    def logLevelWarning(self): return self._tokens["logLevelWarning"]

    # ── Colors: Background States ────────────────────

    @Property(str, notify=themeChanged)
    def warningBg(self): return self._tokens["warningBg"]

    @Property(str, notify=themeChanged)
    def procedureBg(self): return self._tokens["procedureBg"]

    # ── Colors: Shadow ───────────────────────────────

    @Property(str, notify=themeChanged)
    def shadowColor(self): return self._tokens["shadowColor"]

    # ── Colors: Badges ───────────────────────────────

    @Property(str, notify=themeChanged)
    def badgeLeft(self): return self._tokens["badgeLeft"]

    @Property(str, notify=themeChanged)
    def badgeRight(self): return self._tokens["badgeRight"]

    @Property(str, notify=themeChanged)
    def badgeNeutral(self): return self._tokens["badgeNeutral"]

    @Property(str, notify=themeChanged)
    def badgeTextLeft(self): return self._tokens["badgeTextLeft"]

    @Property(str, notify=themeChanged)
    def badgeTextRight(self): return self._tokens["badgeTextRight"]

    @Property(str, notify=themeChanged)
    def badgeTextNeutral(self): return self._tokens["badgeTextNeutral"]

    # ── Dimensions: Radii ────────────────────────────

    @Property(int, notify=themeChanged)
    def radiusSmall(self): return self._tokens["radiusSmall"]

    @Property(int, notify=themeChanged)
    def radius(self): return self._tokens["radius"]

    @Property(int, notify=themeChanged)
    def radiusLarge(self): return self._tokens["radiusLarge"]

    # ── Dimensions: Typography ───────────────────────

    @Property(int, notify=themeChanged)
    def fontSizeXs(self): return self._tokens["fontSizeXs"]

    @Property(int, notify=themeChanged)
    def fontSizeSm(self): return self._tokens["fontSizeSm"]

    @Property(int, notify=themeChanged)
    def fontSize(self): return self._tokens["fontSize"]

    @Property(int, notify=themeChanged)
    def fontSizeLg(self): return self._tokens["fontSizeLg"]

    @Property(int, notify=themeChanged)
    def fontSizeXl(self): return self._tokens["fontSizeXl"]

    # ── Dimensions: Layout ───────────────────────────

    @Property(int, notify=themeChanged)
    def toolbarHeight(self): return self._tokens["toolbarHeight"]

    @Property(int, notify=themeChanged)
    def statusBarHeight(self): return self._tokens["statusBarHeight"]

    @Property(int, notify=themeChanged)
    def sidebarMinWidth(self): return self._tokens["sidebarMinWidth"]

    @Property(int, notify=themeChanged)
    def buttonHeight(self): return self._tokens["buttonHeight"]

    @Property(int, notify=themeChanged)
    def inputHeight(self): return self._tokens["inputHeight"]

    # ── Dimensions: Spacing ──────────────────────────

    @Property(int, notify=themeChanged)
    def spacingSm(self): return self._tokens["spacingSm"]

    @Property(int, notify=themeChanged)
    def spacing(self): return self._tokens["spacing"]

    @Property(int, notify=themeChanged)
    def spacingLg(self): return self._tokens["spacingLg"]

    @Property(int, notify=themeChanged)
    def spacingXl(self): return self._tokens["spacingXl"]
