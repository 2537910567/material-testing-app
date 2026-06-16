"""
V5.2.0: shadcn/ui 设计令牌 — Zinc 灰度体系

浅色 + 深色令牌集，通过 theme.py 的 ThemeObject 动态切换。
"""


def hsl_to_hex(h: float, s: float, l: float) -> str:
    """HSL (h:0-360, s:0-100%, l:0-100%) → "#RRGGBB" """
    s /= 100.0
    l /= 100.0
    c = (1.0 - abs(2.0 * l - 1.0)) * s
    x = c * (1.0 - abs((h / 60.0) % 2 - 1.0))
    m = l - c / 2.0
    r, g, b = 0.0, 0.0, 0.0
    if h < 60:
        r, g, b = c, x, 0.0
    elif h < 120:
        r, g, b = x, c, 0.0
    elif h < 180:
        r, g, b = 0.0, c, x
    elif h < 240:
        r, g, b = 0.0, x, c
    elif h < 300:
        r, g, b = x, 0.0, c
    else:
        r, g, b = c, 0.0, x
    return "#{:02X}{:02X}{:02X}".format(
        int((r + m) * 255), int((g + m) * 255), int((b + m) * 255)
    )


# ═══════════════ 浅色令牌 (Zinc Light) ═══════════════

LIGHT_TOKENS = {
    # Core surface
    "bgMain": "#FAFAFA",          # zinc-50
    "bgSurface": "#FFFFFF",       # white
    "bgHover": "#F4F4F5",        # zinc-100 / secondary
    "bgActive": "#E4E4E7",       # zinc-200

    # Text
    "textPrimary": "#09090B",     # zinc-950 / foreground
    "textSecondary": "#71717A",   # zinc-500 / muted-foreground
    "textDisabled": "#A1A1AA",   # zinc-400
    "textOnAccent": "#FAFAFA",   # primary-foreground

    # Borders
    "border": "#E4E4E7",         # zinc-200
    "inputBorder": "#E4E4E7",    # input

    # Accent (near-black primary)
    "accent": "#18181B",          # zinc-900 / primary
    "accentHover": "#27272A",    # zinc-800
    "accentPressed": "#3F3F46",  # zinc-700
    "ring": "#18181B",           # ring

    # CTA (same as accent in Zinc)
    "cta": "#18181B",
    "ctaHover": "#27272A",
    "ctaPressed": "#3F3F46",

    # Semantic
    "success": "#22C55E",         # green-500
    "successHover": "#16A34A",   # green-600
    "warning": "#F59E0B",         # amber-500
    "danger": "#EF4444",          # red-500 / destructive
    "warningBg": "#FEF3C7",      # amber-50
    "procedureBg": "#F4F4F5",    # zinc-100

    # Log levels
    "logLevelError": "#EF4444",
    "logLevelWarning": "#F59E0B",

    # States
    "selection": "#F4F4F5",       # secondary
    "headerBg": "#FAFAFA",       # zinc-50

    # Badges
    "badgeLeft": "#DBEAFE",       # blue-100
    "badgeRight": "#FEE2E2",     # red-100
    "badgeNeutral": "#F4F4F5",   # zinc-100
    "badgeTextLeft": "#1E40AF",  # blue-800
    "badgeTextRight": "#DC2626", # red-600
    "badgeTextNeutral": "#71717A", # zinc-500

    # Shadow
    "shadowColor": "#0A000000",   # 10% alpha black

    # Radius (unchanged from current)
    "radiusSmall": 4,
    "radius": 8,
    "radiusLarge": 12,

    # Spacing (4px grid)
    "spacingXs": 2,
    "spacingSm": 4,
    "spacing": 8,
    "spacingLg": 12,
    "spacingXl": 20,
    "spacing2xl": 24,
    "spacing3xl": 32,

    # Typography
    "fontSizeXs": 10,
    "fontSizeSm": 12,
    "fontSize": 14,
    "fontSizeLg": 16,
    "fontSizeXl": 18,
    "fontSize2xl": 20,
    "fontSize3xl": 24,
    "fontSize4xl": 30,

    # Layout
    "toolbarHeight": 48,
    "statusBarHeight": 28,
    "sidebarMinWidth": 240,
    "buttonHeight": 36,
    "inputHeight": 36,
}


# ═══════════════ 深色令牌 (Zinc Dark) ═══════════════

DARK_TOKENS = {
    "bgMain": "#09090B",          # zinc-950
    "bgSurface": "#18181B",       # zinc-900
    "bgHover": "#27272A",         # zinc-800
    "bgActive": "#3F3F46",        # zinc-700

    "textPrimary": "#FAFAFA",     # zinc-50
    "textSecondary": "#A1A1AA",   # zinc-400
    "textDisabled": "#71717A",    # zinc-500
    "textOnAccent": "#09090B",    # near-black on light accent

    "border": "#27272A",          # zinc-800
    "inputBorder": "#3F3F46",     # zinc-700

    "accent": "#FAFAFA",          # zinc-50 (inverted)
    "accentHover": "#E4E4E7",    # zinc-200
    "accentPressed": "#D4D4D8",  # zinc-300
    "ring": "#D4D4D8",

    "cta": "#FAFAFA",
    "ctaHover": "#E4E4E7",
    "ctaPressed": "#D4D4D8",

    "success": "#22C55E",
    "successHover": "#4ADE80",
    "warning": "#F59E0B",
    "danger": "#EF4444",
    "warningBg": "#422006",       # amber-950
    "procedureBg": "#27272A",     # zinc-800

    "logLevelError": "#F87171",   # red-400
    "logLevelWarning": "#FBBF24", # amber-400

    "selection": "#27272A",
    "headerBg": "#09090B",

    "badgeLeft": "#1E3A5F",       # blue-900
    "badgeRight": "#7F1D1D",     # red-900
    "badgeNeutral": "#27272A",
    "badgeTextLeft": "#93C5FD",  # blue-300
    "badgeTextRight": "#FCA5A5", # red-300
    "badgeTextNeutral": "#A1A1AA",

    "shadowColor": "#0A000000",

    "radiusSmall": 4,
    "radius": 8,
    "radiusLarge": 12,

    "spacingXs": 2,
    "spacingSm": 4,
    "spacing": 8,
    "spacingLg": 12,
    "spacingXl": 20,
    "spacing2xl": 24,
    "spacing3xl": 32,

    "fontSizeXs": 10,
    "fontSizeSm": 12,
    "fontSize": 14,
    "fontSizeLg": 16,
    "fontSizeXl": 18,
    "fontSize2xl": 20,
    "fontSize3xl": 24,
    "fontSize4xl": 30,

    "toolbarHeight": 48,
    "statusBarHeight": 28,
    "sidebarMinWidth": 240,
    "buttonHeight": 36,
    "inputHeight": 36,
}


def get_token_set(mode: str = "light") -> dict:
    """返回指定模式的令牌集"""
    if mode == "dark":
        return DARK_TOKENS.copy()
    return LIGHT_TOKENS.copy()
