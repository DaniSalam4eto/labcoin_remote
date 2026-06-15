"""Visual styling helpers for the Labcoin Music Remote app.

The palette deliberately avoids any beige / skin tones — the app now lives on a
deep midnight background with vivid neon accents. The core building blocks
exposed to ``app.py`` are:

  * `Theme`               -- font cache.
  * `NoteFountain`        -- floating colored music notes that decorate the
                              left and right edges of every screen.

Plus a handful of free functions that draw chunky 3D-feeling buttons,
crisp text, and the purple trapezoid remote with its gray coil antenna.
"""

from __future__ import annotations

import math
import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pygame

from bundle_paths import app_base_dir

# --------------------------------------------------------------------------
# Color palette — neutral console aesthetic (PS5 / Switch family).
# Deep near-black background; frosted-glass surfaces over it; a small set of
# vivid accents reserved for status, focus, and category color.
# --------------------------------------------------------------------------

# Background pair (deep near-black, barely-there vertical fall-off).
BG_TOP        = (14, 16, 22)       # #0E1016
BG_BOTTOM     = (4,  5,  10)       # #04050A

# Frosted-glass surfaces (RGBA — alpha matters).
GLASS_TINT       = (22, 26, 36, 168)   # default frosted card tint
GLASS_TINT_SOFT  = (28, 32, 44, 130)   # lighter tier (chips / pills)
GLASS_TINT_DEEP  = (16, 18, 28, 210)   # heavier tier (overlays)
GLASS_STROKE     = (255, 255, 255, 28) # 1-px inner stroke for cards
GLASS_STROKE_HI  = (255, 255, 255, 52) # for hovered / focused

# Solid panel tones used by tile widgets that don't sit on a card.
PANEL_FILL    = (28, 32, 42)       # #1C202A
PANEL_HI      = (42, 48, 62)       # #2A303E
PANEL_OUTLINE = (255, 255, 255)
PANEL_SHADOW  = (4, 5, 10)

# Text.
INK           = (245, 247, 252)
INK_SOFT      = (188, 196, 214)
INK_DIM       = (132, 140, 160)

# Status colors (used by the status pill + connection state).
STATUS_GREEN  = (62, 207, 142)     # connected
STATUS_AMBER  = (255, 184, 80)     # connecting / waiting
STATUS_RED    = (255, 95,  95)     # error / off
STATUS_BLUE   = (87, 182, 255)     # info

# Vibrant accents — kept (and lightly retuned) for back-compat with all the
# screens that still tag content with category color.
ACCENT_PINK   = (255, 119, 176)
ACCENT_CYAN   = (95,  214, 220)
ACCENT_YELLOW = (255, 210, 90)
ACCENT_GREEN  = STATUS_GREEN
ACCENT_GREEN_D = (60, 170, 110)
ACCENT_BLUE   = STATUS_BLUE
ACCENT_RED    = STATUS_RED
ACCENT_ORANGE = (255, 168, 88)
PURPLE        = (170, 122, 255)
PURPLE_DEEP   = (118, 78,  210)
ACCENT_PURPLE = PURPLE

# Controller cartoon (legacy, only drawn if explicitly requested).
ANTENNA_GRAY  = (200, 204, 215)
ANTENNA_DARK  = (132, 138, 156)

# Legacy aliases kept so older imports don't break.
BEIGE_BG       = BG_TOP
BEIGE_BG_DARK  = BG_BOTTOM
BEIGE_PANEL    = PANEL_FILL
BEIGE_PANEL_HI = PANEL_HI

NOTE_COLORS = [
    ACCENT_PINK, ACCENT_CYAN, ACCENT_YELLOW,
    ACCENT_GREEN, ACCENT_BLUE, ACCENT_ORANGE, PURPLE,
]


# --------------------------------------------------------------------------
# Font discovery — two stacks:
#   * Neutral UI (Segoe UI / Calibri family): used for English; reads clean on
#     the starfield instead of a rounded “doodle” face.
#   * Rounded game face (bundled Comfortaa, Comic fallbacks): used for
#     Bulgarian so Cyrillic stays on a deliberate display cut.
# --------------------------------------------------------------------------

_PACKAGE_FONTS = app_base_dir() / "fonts"
_BUNDLED_COMFORTAA = _PACKAGE_FONTS / "Comfortaa-Variable.ttf"


def _windows_fonts_dir() -> Path:
    return Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"


def _resolve_font_file(*filenames: str) -> Optional[str]:
    folder = _windows_fonts_dir()
    for name in filenames:
        # Fonts folder is case-insensitive on Windows; try exact then lower.
        for variant in (name, name.lower()):
            path = folder / variant
            if path.is_file():
                return str(path)
    return None


def bundled_cartoon_font_path() -> Optional[str]:
    """Rounded display font shipped in ``fonts/`` (Comfortaa variable)."""
    if _BUNDLED_COMFORTAA.is_file():
        return str(_BUNDLED_COMFORTAA)
    return None


def cartoon_font_heavy_path() -> Optional[str]:
    """Bolder headline weight: bundled Comfortaa, else Comic Sans Bold."""
    bundled = bundled_cartoon_font_path()
    if bundled:
        return bundled
    return _resolve_font_file(
        "comicz.ttf",
        "Comicbd.ttf",
        "comicbd.ttf",
    ) or cartoon_font_regular_path()


def cartoon_font_regular_path() -> Optional[str]:
    """Regular body weight: bundled Comfortaa, else Comic Sans."""
    bundled = bundled_cartoon_font_path()
    if bundled:
        return bundled
    return _resolve_font_file("comic.ttf", "Comic.ttf") or match_font_fallback()


def ui_font_regular_path() -> Optional[str]:
    return _resolve_font_file(
        "segoeui.ttf", "SegoeUI.ttf", "calibri.ttf", "Candara.ttf",
    )


def ui_font_semibold_path() -> Optional[str]:
    return _resolve_font_file(
        "seguisb.ttf", "SegoeUISemibold.ttf", "segoeuiz.ttf",
        "segoeuib.ttf", "SegoeUIBold.ttf",
    )


def ui_font_bold_path() -> Optional[str]:
    return _resolve_font_file(
        "segoeuib.ttf", "SegoeUIBold.ttf", "seguisb.ttf",
    )


def match_font_fallback() -> Optional[str]:
    try:
        return pygame.font.match_font(
            "comfortaa,nunito semibold,nunito,comic sans ms,fredoka one,"
            "coiny,baloo 2,segoe ui,calibri,candara,trebuchet ms,arial"
        )
    except Exception:
        return None


def match_ui_font_fallback() -> Optional[str]:
    """Sans-serif UI stack for Latin text — no rounded comic/game faces."""
    try:
        return pygame.font.match_font(
            "segoe ui semibold,segoe ui,nunito sans semibold,nunito sans,"
            "source sans 3,open sans,roboto,calibri,candara,trebuchet ms,"
            "liberation sans,arial,helvetica,ubuntu,noto sans"
        )
    except Exception:
        return None


def title_font_file(*, rounded_display: bool) -> Optional[str]:
    """Heavy headline / huge glyph face — Comfortaa stack vs neutral UI."""
    if rounded_display:
        return (cartoon_font_heavy_path()
                or ui_font_bold_path() or ui_font_semibold_path()
                or ui_font_regular_path() or match_font_fallback())
    return (ui_font_bold_path() or ui_font_semibold_path()
            or ui_font_regular_path() or match_ui_font_fallback())


def body_font_file(*, rounded_display: bool) -> Optional[str]:
    """Body / small text face paired with ``title_font_file``."""
    if rounded_display:
        return (cartoon_font_regular_path() or ui_font_regular_path()
                or match_font_fallback())
    return (ui_font_regular_path() or ui_font_semibold_path()
            or match_ui_font_fallback())


def make_main_menu_hint_fonts(
    screen_w: int,
    screen_h: int,
    *,
    rounded_display: bool = False,
) -> tuple[pygame.font.Font, pygame.font.Font]:
    """Smaller, tight headline + body for the lines under the logo."""
    if rounded_display:
        fb = match_font_fallback()
        head_path = (cartoon_font_heavy_path()
                     or ui_font_semibold_path() or ui_font_bold_path() or fb)
        sub_path = cartoon_font_regular_path() or ui_font_regular_path() or fb
    else:
        fb = match_ui_font_fallback()
        head_path = (ui_font_semibold_path() or ui_font_bold_path()
                     or ui_font_regular_path() or fb)
        sub_path = ui_font_regular_path() or ui_font_semibold_path() or fb
    # Compact sizes; respect vertical space on short windows.
    head_px = max(15, min(20, min(screen_w // 56, screen_h // 42)))
    sub_px = max(12, min(16, min(screen_w // 72, screen_h // 52)))
    head = pygame.font.Font(head_path, head_px) if head_path else pygame.font.Font(None, head_px)
    head.set_bold(False)
    sub = pygame.font.Font(sub_path, sub_px) if sub_path else pygame.font.Font(None, sub_px)
    sub.set_bold(False)
    return head, sub


def draw_crisp_label(surface: pygame.Surface, font: pygame.font.Font,
                     text: str, color: tuple[int, int, int],
                     pos: tuple[int, int], anchor: str = "midtop") -> pygame.Rect:
    """Text with a thin dark outline so it stays readable on the starfield."""
    main = font.render(text, True, color)
    rect = main.get_rect(**{anchor: pos})
    outline_rgb = (10, 12, 26)
    for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1),
                   (-1, -1), (1, -1), (-1, 1), (1, 1)):
        edge = font.render(text, True, outline_rgb)
        surface.blit(edge, rect.move(ox, oy))
    surface.blit(main, rect)
    return rect


@dataclass
class Theme:
    title_font: pygame.font.Font
    body_font:  pygame.font.Font
    small_font: pygame.font.Font
    huge_font:  pygame.font.Font
    mono_font:  pygame.font.Font

    @classmethod
    def make(cls, *, rounded_display: bool = False) -> "Theme":
        heavy_path = title_font_file(rounded_display=rounded_display)
        body_path = body_font_file(rounded_display=rounded_display)

        def _font(path: Optional[str], px: int) -> pygame.font.Font:
            f = pygame.font.Font(path, px) if path else pygame.font.Font(None, px)
            f.set_bold(False)
            return f

        title = _font(heavy_path, 34)
        huge = _font(heavy_path, 122)
        body = _font(body_path, 21)
        small = _font(body_path, 15)
        try:
            mono_name = pygame.font.match_font(
                "jetbrainsmono,consolas,couriernew,monospace"
            )
        except Exception:
            mono_name = None
        mono = pygame.font.Font(mono_name, 15)
        return cls(title_font=title, body_font=body, small_font=small,
                   huge_font=huge, mono_font=mono)


# --------------------------------------------------------------------------
# Image utilities.
# --------------------------------------------------------------------------

def load_image_alpha(path: Path) -> Optional[pygame.Surface]:
    """Load a transparent PNG / AVIF and return it as a pygame surface."""
    if not path.exists():
        return None
    suffix = path.suffix.lower()
    if suffix == ".avif":
        try:
            from PIL import Image  # type: ignore
            # Pillow 11.3+ decodes AVIF natively. The old `pillow-avif-plugin`
            # is obsolete and SEGFAULTS on import against Pillow 12 (a C crash
            # that a try/except can't catch), so we must not import it.
            img = Image.open(path).convert("RGBA")
            return pygame.image.frombuffer(
                img.tobytes(), img.size, "RGBA"
            ).convert_alpha()
        except Exception:
            return None
    try:
        return pygame.image.load(str(path)).convert_alpha()
    except Exception:
        return None


def colorize(surface: pygame.Surface, color: tuple[int, int, int]) -> pygame.Surface:
    """Replace the RGB of every non-transparent pixel with `color`."""
    try:
        from PIL import Image  # type: ignore
    except Exception:
        out = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        out.fill((*color, 255))
        out.blit(surface, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
        return out
    raw = pygame.image.tostring(surface, "RGBA")
    pil = Image.frombytes("RGBA", surface.get_size(), raw)
    alpha = pil.split()[3]
    tinted = Image.new("RGBA", pil.size, (*color, 255))
    tinted.putalpha(alpha)
    out_surface = pygame.image.fromstring(tinted.tobytes(), tinted.size, "RGBA")
    return out_surface.convert_alpha()


def scale_to_height(surface: pygame.Surface, target_h: int) -> pygame.Surface:
    w, h = surface.get_size()
    if h == 0:
        return surface
    scale = target_h / h
    return pygame.transform.smoothscale(surface, (max(1, int(w * scale)), target_h))


def scale_surface_high_quality(
    surface: pygame.Surface, max_w: int, max_h: int
) -> pygame.Surface:
    """Scale to fit inside ``max_w`` × ``max_h`` keeping aspect."""
    w, h = surface.get_size()
    if w <= 0 or h <= 0 or max_w <= 0 or max_h <= 0:
        return surface
    scale = min(max_w / w, max_h / h)
    nw = max(1, int(round(w * scale)))
    nh = max(1, int(round(h * scale)))
    if nw == w and nh == h:
        return surface.copy()
    try:
        from PIL import Image  # type: ignore
        try:
            resample = Image.Resampling.LANCZOS
        except AttributeError:  # Pillow < 9.1
            resample = Image.LANCZOS  # type: ignore[attr-defined]
        buf = pygame.image.tobytes(surface, "RGBA")
        pil = Image.frombytes("RGBA", (w, h), buf)
        pil = pil.resize((nw, nh), resample)
        out = pygame.image.frombytes(pil.tobytes(), pil.size, "RGBA")
        return out.convert_alpha()
    except Exception:
        return pygame.transform.smoothscale(surface, (nw, nh))


def scale_menu_logo(surface: pygame.Surface, max_w: int, max_h: int) -> pygame.Surface:
    """Scale the menu logo to fit ``max_w`` × ``max_h`` without ever *upscaling*
    past the asset's native resolution — blowing up small logos is what reads
    as blurry. Downscaling uses LANCZOS plus a very light unsharp pass."""
    w, h = surface.get_size()
    if w <= 0 or h <= 0 or max_w <= 0 or max_h <= 0:
        return surface.copy()
    scale = min(max_w / w, max_h / h, 1.0)
    nw = max(1, int(round(w * scale)))
    nh = max(1, int(round(h * scale)))
    if nw == w and nh == h:
        return surface.copy()
    try:
        from PIL import Image  # type: ignore
        try:
            from PIL import ImageFilter  # type: ignore
        except Exception:
            ImageFilter = None  # type: ignore[assignment]
        try:
            resample = Image.Resampling.LANCZOS
        except AttributeError:  # Pillow < 9.1
            resample = Image.LANCZOS  # type: ignore[attr-defined]
        buf = pygame.image.tobytes(surface, "RGBA")
        pil = Image.frombytes("RGBA", (w, h), buf)
        pil = pil.resize((nw, nh), resample)
        # Gentle sharpen only when we meaningfully shrank the bitmap.
        if ImageFilter is not None and scale < 0.92:
            pil = pil.filter(
                ImageFilter.UnsharpMask(radius=0.7, percent=90, threshold=2)
            )
        out = pygame.image.frombytes(pil.tobytes(), pil.size, "RGBA").convert_alpha()
        return out
    except Exception:
        return pygame.transform.smoothscale(surface, (nw, nh))


# --------------------------------------------------------------------------
# Floating note decoration.
# --------------------------------------------------------------------------

@dataclass
class _FloatingNote:
    image: pygame.Surface
    x: float
    y: float
    speed: float
    sway_amp: float
    sway_freq: float
    sway_phase: float
    spin: float
    spin_speed: float


class NoteFountain:
    """Endlessly streaming colored notes drifting up the side of the screen."""

    def __init__(self, note_pngs: list[pygame.Surface], side: str,
                 area: pygame.Rect, density: int = 7) -> None:
        self.side = side
        self.area = area
        self.note_pngs = note_pngs
        self.notes: list[_FloatingNote] = []
        for _ in range(density):
            self.notes.append(self._spawn(initial=True))

    def resize(self, area: pygame.Rect) -> None:
        self.area = area
        for n in self.notes:
            n.x = self._random_x()
            n.y = random.uniform(area.top, area.bottom)

    def _random_x(self) -> float:
        return random.uniform(self.area.left, self.area.right)

    def _spawn(self, initial: bool = False) -> _FloatingNote:
        base = random.choice(self.note_pngs)
        target_h = random.randint(22, 44)
        img = scale_to_height(base, target_h)
        # Soft ambient layer: knock back alpha so notes don't compete with cards.
        img = img.copy()
        img.set_alpha(80)
        return _FloatingNote(
            image=img,
            x=self._random_x(),
            y=(random.uniform(self.area.top, self.area.bottom)
               if initial else self.area.bottom + random.uniform(20, 200)),
            speed=random.uniform(20, 44),
            sway_amp=random.uniform(8, 22),
            sway_freq=random.uniform(0.6, 1.6),
            sway_phase=random.uniform(0, math.tau),
            spin=random.uniform(-8, 8),
            spin_speed=random.uniform(-18, 18),
        )

    def update(self, dt: float, t: float) -> None:
        for i, n in enumerate(self.notes):
            n.y -= n.speed * dt
            n.spin += n.spin_speed * dt
            if n.y + n.image.get_height() < self.area.top:
                self.notes[i] = self._spawn(initial=False)
                self.notes[i].y = self.area.bottom + random.uniform(10, 80)

    def draw(self, surface: pygame.Surface, t: float) -> None:
        for n in self.notes:
            sway = math.sin(t * n.sway_freq + n.sway_phase) * n.sway_amp
            img = pygame.transform.rotozoom(n.image, n.spin, 1.0)
            rect = img.get_rect(center=(int(n.x + sway), int(n.y)))
            surface.blit(img, rect)


def build_note_palette(note_paths: list[Path]) -> list[pygame.Surface]:
    """Load every note PNG once per accent color, return the cross-product."""
    raw: list[pygame.Surface] = []
    for p in note_paths:
        surf = load_image_alpha(p)
        if surf is None:
            continue
        raw.append(surf)
    if not raw:
        return []
    out: list[pygame.Surface] = []
    for surf in raw:
        for color in NOTE_COLORS:
            out.append(colorize(surf, color))
    return out


# --------------------------------------------------------------------------
# Drawing primitives.
# --------------------------------------------------------------------------

def _shade(color: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    """Multiply RGB by ``factor`` (clamped 0..255). >1 brightens, <1 darkens."""
    return (
        max(0, min(255, int(color[0] * factor))),
        max(0, min(255, int(color[1] * factor))),
        max(0, min(255, int(color[2] * factor))),
    )


def _stamp_rounded_shadow(surface: pygame.Surface, rect: pygame.Rect, *,
                            radius: int, alpha: int = 120, blur: int = 24,
                            offset_y: int = 14) -> None:
    """Blit a cached anti-aliased soft drop shadow under ``rect``."""
    sh = _drop_shadow(rect.size, radius, alpha=alpha, blur=blur)
    pad = blur * 2
    surface.blit(sh, (rect.left - pad, rect.top - pad + offset_y))


def draw_glass_card(surface: pygame.Surface, rect: pygame.Rect, *,
                     radius: int = 30,
                     tint: tuple[int, int, int, int] = GLASS_TINT,
                     stroke: tuple[int, int, int, int] = GLASS_STROKE,
                     shadow: bool = True,
                     spotlight: bool = True) -> None:
    """Frosted-glass rounded card with anti-aliased corners.

    Steps:
      1. Optional radial white spotlight under the card so it "pops" off the bg.
      2. Soft anti-aliased drop shadow (cached).
      3. Re-blit a crop of the pre-blurred background, clipped to a smooth
         PIL-built rounded mask — true frosted-glass crop.
      4. Translucent tint, clipped to the same mask.
      5. Anti-aliased rounded outline.
    """
    safe = rect.clip(surface.get_rect())
    if safe.width <= 0 or safe.height <= 0:
        return

    # Card-behind spotlight removed at user request — the drop shadow gives
    # the card enough depth without a visible white halo on dark backgrounds.
    del spotlight

    if shadow:
        _stamp_rounded_shadow(surface, rect, radius=radius,
                                alpha=130, blur=26, offset_y=20)

    mask = _rounded_mask(rect.size, radius)

    # Blurred bg crop, clipped to the rounded shape.
    blurred = _blurred_background(surface.get_size())
    glass = pygame.Surface(rect.size, pygame.SRCALPHA)
    glass.blit(blurred, (-rect.left, -rect.top))
    glass.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
    surface.blit(glass, rect.topleft)

    # Tint overlay, also clipped to the rounded shape.
    overlay = pygame.Surface(rect.size, pygame.SRCALPHA)
    overlay.fill(tint)
    overlay.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
    surface.blit(overlay, rect.topleft)

    # Crisp anti-aliased outline.
    surface.blit(_rounded_stroke(rect.size, radius, stroke, width=1),
                  rect.topleft)


def draw_pill_button(surface: pygame.Surface, rect: pygame.Rect,
                      label: str, theme: Theme, *,
                      primary: bool = True, hovered: bool = False,
                      font: Optional[pygame.font.Font] = None) -> None:
    """Glossy translucent glass capsule.

    No solid white fill, no icon badges — just a dark glass pill with a soft
    inner top highlight and a hairline white stroke. Smaller, body-font-sized
    label by default so 4–8-character labels fit comfortably."""
    del primary  # tint is the same either way; only the alpha differs slightly
    radius = rect.height // 2
    font = font or theme.body_font

    _stamp_rounded_shadow(surface, rect, radius=radius,
                            alpha=140 if hovered else 110,
                            blur=22, offset_y=14)

    mask = _rounded_mask(rect.size, radius)

    # 1) Frosted glass: blurred bg crop clipped to the capsule.
    blurred = _blurred_background(surface.get_size())
    glass = pygame.Surface(rect.size, pygame.SRCALPHA)
    glass.blit(blurred, (-rect.left, -rect.top))
    glass.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
    surface.blit(glass, rect.topleft)

    # 2) Light translucent wash — much more transparent than before so the
    # blurred background reads through. Alpha lifts a little on hover.
    wash = pygame.Surface(rect.size, pygame.SRCALPHA)
    wash_alpha = 90 if hovered else 60
    wash.fill((26, 30, 44, wash_alpha))
    wash.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
    surface.blit(wash, rect.topleft)

    # 3) Inner top highlight — slightly brighter gloss top, fades away.
    highlight_h = max(8, rect.height // 2)
    hi_layer = pygame.Surface(rect.size, pygame.SRCALPHA)
    for i in range(highlight_h):
        a = int(54 * (1.0 - i / max(1, highlight_h)))
        if a <= 0:
            continue
        pygame.draw.rect(hi_layer, (255, 255, 255, a),
                         pygame.Rect(0, i, rect.width, 1))
    hi_layer.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
    surface.blit(hi_layer, rect.topleft)

    # 4) Hairline outline — brighter when hovered.
    stroke = (255, 255, 255, 140 if hovered else 95)
    surface.blit(_rounded_stroke(rect.size, radius, stroke, width=1),
                  rect.topleft)

    # 5) Label.
    text_color = INK
    lbl = font.render(label, True, text_color)
    surface.blit(lbl, lbl.get_rect(center=rect.center))


def draw_chunky_button(surface: pygame.Surface, rect: pygame.Rect, label: str,
                       theme: Theme,
                       fill: tuple[int, int, int] = (245, 245, 245),
                       text_color: tuple[int, int, int] = (15, 15, 30),
                       hovered: bool = False,
                       depth: int = 7) -> None:
    """Back-compat shim — funnels into the new glass pill button."""
    del depth, fill, text_color
    draw_pill_button(surface, rect, label, theme,
                      primary=True, hovered=hovered)


def draw_status_pill(surface: pygame.Surface, anchor_point: tuple[int, int],
                      label: str, theme: Theme, *,
                      status: str = "offline",
                      t: float = 0.0,
                      anchor: str = "center") -> pygame.Rect:
    """Small glassy capsule with a colored status dot.

    ``anchor`` controls how ``anchor_point`` is interpreted — any of the
    pygame Rect anchor attributes (``center``, ``midright``, ``topright`` …).
    Pass ``"midright"`` to clamp the pill to the right edge of the screen so
    long labels (e.g. Bulgarian) don't clip off-screen.

    Status keys: ``"connected" | "connecting" | "offline" | "error" | "info"``.
    The dot pulses gently when ``connecting``."""
    color = {
        "connected": STATUS_GREEN,
        "connecting": STATUS_AMBER,
        "offline": INK_DIM,
        "error": STATUS_RED,
        "info": STATUS_BLUE,
    }.get(status, INK_DIM)
    dot_r = 6
    pad_x = 14
    pad_y = 8
    font = theme.small_font
    lbl = font.render(label, True, INK)
    w = lbl.get_width() + pad_x * 2 + dot_r * 2 + 10
    h = lbl.get_height() + pad_y * 2
    rect = pygame.Rect(0, 0, w, h)
    try:
        setattr(rect, anchor, anchor_point)
    except (AttributeError, TypeError):
        rect.center = anchor_point
    radius = h // 2

    mask = _rounded_mask(rect.size, radius)

    blurred = _blurred_background(surface.get_size())
    crop = pygame.Surface(rect.size, pygame.SRCALPHA)
    crop.blit(blurred, (-rect.left, -rect.top))
    crop.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
    surface.blit(crop, rect.topleft)

    wash = pygame.Surface(rect.size, pygame.SRCALPHA)
    wash.fill((22, 26, 36, 130))
    wash.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
    surface.blit(wash, rect.topleft)

    surface.blit(_rounded_stroke(rect.size, radius, (255, 255, 255, 60), 1),
                  rect.topleft)

    cx_dot = rect.left + pad_x + dot_r
    cy_dot = rect.centery
    if status == "connecting":
        pulse = 0.5 + 0.5 * math.sin(t * 3.4)
        halo_r = int(dot_r + 3 + 3 * pulse)
        blit_soft_halo(surface, (cx_dot, cy_dot), halo_r, color,
                        alpha=int(80 * (0.4 + 0.6 * pulse)), blur=5)
    # Flat anti-aliased dot — no fake gloss highlight.
    blit_smooth_circle(surface, (cx_dot, cy_dot), dot_r, color)

    surface.blit(lbl, (cx_dot + dot_r + 10,
                       rect.centery - lbl.get_height() // 2))
    return rect


def draw_action_hint(surface: pygame.Surface, anchor_left: tuple[int, int],
                      label: str, hint_letter: str, theme: Theme,
                      *, color: tuple[int, int, int] = INK) -> pygame.Rect:
    """Kept only for back-compat — newer screens render labels without the
    'press X' badge entirely. Falls back to a plain label."""
    del hint_letter
    lbl = theme.title_font.render(label, True, color)
    rect = lbl.get_rect(midleft=anchor_left)
    surface.blit(lbl, rect)
    return rect


def draw_remote_icon(surface: pygame.Surface, center: tuple[int, int],
                      *, scale: float = 1.0,
                      accent: tuple[int, int, int] = STATUS_BLUE,
                      pulse_t: float = 0.0,
                      connected: bool = False) -> pygame.Rect:
    """Minimalist glass controller silhouette with a 2×5 numpad."""
    cx, cy = center
    w = int(220 * scale)
    h = int(150 * scale)
    rect = pygame.Rect(0, 0, w, h)
    rect.center = (cx, cy)
    radius = int(26 * scale)

    _stamp_rounded_shadow(surface, rect, radius=radius,
                            alpha=120, blur=24, offset_y=14)
    mask = _rounded_mask(rect.size, radius)

    body_layer = pygame.Surface(rect.size, pygame.SRCALPHA)
    body_layer.fill((52, 58, 74, 235))
    body_layer.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
    surface.blit(body_layer, rect.topleft)

    # Glossy top highlight (matches the buttons).
    highlight_h = max(6, h // 3)
    hi = pygame.Surface(rect.size, pygame.SRCALPHA)
    for i in range(highlight_h):
        a = int(28 * (1.0 - i / max(1, highlight_h)))
        if a <= 0:
            continue
        pygame.draw.rect(hi, (255, 255, 255, a),
                         pygame.Rect(0, i, rect.width, 1))
    hi.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
    surface.blit(hi, rect.topleft)

    surface.blit(_rounded_stroke(rect.size, radius, (255, 255, 255, 50), 1),
                  rect.topleft)

    # Status LED — anti-aliased dot, soft halo when connected.
    led_cx = rect.centerx
    led_cy = rect.top + int(16 * scale)
    led_color = accent if connected else INK_DIM
    if connected:
        pulse = 0.5 + 0.5 * math.sin(pulse_t * 2.4)
        halo_r = int(8 * scale + 3 * pulse)
        blit_soft_halo(surface, (led_cx, led_cy), halo_r, led_color,
                        alpha=int(95 * (0.4 + 0.6 * pulse)), blur=5)
    blit_smooth_circle(surface, (led_cx, led_cy),
                       max(2, int(4 * scale)), led_color)

    # 2×5 numpad of soft dots — anti-aliased, with a slightly darker shadow.
    rows, cols = 5, 2
    pad_w = int(w * 0.32)
    pad_h = int(h * 0.62)
    pad_left = cx - pad_w // 2
    pad_top = cy - pad_h // 2 + int(12 * scale)
    dot_r = max(3, int(4.5 * scale))
    for r in range(rows):
        for c in range(cols):
            x = pad_left + (pad_w // (cols - 1)) * c
            y = pad_top + (pad_h // (rows - 1)) * r
            blit_smooth_circle(surface, (x, y), dot_r + 2,
                                (16, 18, 24), alpha=220)
            blit_smooth_circle(surface, (x, y), dot_r,
                                (235, 238, 246), alpha=210)
    return rect


# Back-compat name used elsewhere in the codebase.
def draw_doodle_button(surface: pygame.Surface, rect: pygame.Rect, label: str,
                       theme: Theme,
                       fill: tuple[int, int, int] = ACCENT_CYAN,
                       outline: Optional[tuple[int, int, int]] = None,
                       text_color: tuple[int, int, int] = (15, 15, 30),
                       hovered: bool = False,
                       seed: int = 0) -> None:
    del outline, seed
    draw_chunky_button(surface, rect, label, theme,
                       fill=fill, text_color=text_color, hovered=hovered)


def draw_doodle_text(surface: pygame.Surface, text: str, font: pygame.font.Font,
                     color: tuple[int, int, int], pos: tuple[int, int],
                     anchor: str = "center", shadow: bool = True) -> pygame.Rect:
    main = font.render(text, True, color)
    rect = main.get_rect(**{anchor: pos})
    if shadow:
        ghost = font.render(text, True, (0, 0, 0))
        ghost.set_alpha(120)
        surface.blit(ghost, rect.move(0, 3))
    surface.blit(main, rect)
    return rect


_BG_PLAIN_CACHE: dict[tuple[int, int], pygame.Surface] = {}
_BG_BLURRED_CACHE: dict[tuple[int, int], pygame.Surface] = {}
_GLOW_CACHE: dict[tuple[int, int, int, int], pygame.Surface] = {}
_ROUNDED_MASK_CACHE: dict[tuple[int, int, int], pygame.Surface] = {}
_ROUNDED_STROKE_CACHE: dict[tuple[int, int, int, int, int, int, int], pygame.Surface] = {}
_DROP_SHADOW_CACHE: dict[tuple[int, int, int, int, int], pygame.Surface] = {}
_SMOOTH_CIRCLE_CACHE: dict[tuple[int, int, int, int, int], pygame.Surface] = {}
_SOFT_HALO_CACHE: dict[tuple[int, int, int, int, int], pygame.Surface] = {}


def smooth_circle(radius: int,
                   color: tuple[int, int, int],
                   *, alpha: int = 255) -> pygame.Surface:
    """Anti-aliased filled circle. The shape is drawn in Pillow at 2×
    resolution and downsampled with LANCZOS — no visible stair-step pixels
    on the edge. Cached per (radius, color, alpha)."""
    if radius < 1:
        radius = 1
    key = (radius, color[0], color[1], color[2], alpha)
    cached = _SMOOTH_CIRCLE_CACHE.get(key)
    if cached is not None:
        return cached
    pad = 2  # leave a thin transparent border so AA pixels aren't clipped
    size = (radius * 2 + pad * 2, radius * 2 + pad * 2)
    try:
        from PIL import Image, ImageDraw  # type: ignore
    except Exception:
        surf = pygame.Surface(size, pygame.SRCALPHA)
        pygame.draw.circle(surf, (*color, alpha),
                           (size[0] // 2, size[1] // 2), radius)
        _SMOOTH_CIRCLE_CACHE[key] = surf
        return surf
    ss = 2
    big = Image.new("RGBA", (size[0] * ss, size[1] * ss), (0, 0, 0, 0))
    cx = size[0] * ss // 2
    cy = size[1] * ss // 2
    r = radius * ss
    ImageDraw.Draw(big).ellipse(
        (cx - r, cy - r, cx + r, cy + r),
        fill=(*color, alpha),
    )
    small = big.resize(size, Image.LANCZOS)
    surf = pygame.image.frombytes(small.tobytes(), size, "RGBA").convert_alpha()
    _SMOOTH_CIRCLE_CACHE[key] = surf
    return surf


def blit_smooth_circle(surface: pygame.Surface, center: tuple[int, int],
                        radius: int, color: tuple[int, int, int],
                        *, alpha: int = 255) -> None:
    """Center-anchored convenience wrapper around :func:`smooth_circle`."""
    img = smooth_circle(radius, color, alpha=alpha)
    surface.blit(img, (center[0] - img.get_width() // 2,
                        center[1] - img.get_height() // 2))


def soft_halo(radius: int, color: tuple[int, int, int],
               *, alpha: int = 90, blur: int = 4) -> pygame.Surface:
    """Soft Gaussian-blurred halo for status-dot glows and LED pulses."""
    if radius < 1:
        radius = 1
    key = (radius, color[0], color[1], color[2], (alpha << 8) | blur)
    cached = _SOFT_HALO_CACHE.get(key)
    if cached is not None:
        return cached
    pad = max(6, blur * 2 + 2)
    size = (radius * 2 + pad * 2, radius * 2 + pad * 2)
    try:
        from PIL import Image, ImageDraw, ImageFilter  # type: ignore
    except Exception:
        surf = pygame.Surface(size, pygame.SRCALPHA)
        pygame.draw.circle(surf, (*color, alpha),
                           (size[0] // 2, size[1] // 2), radius)
        _SOFT_HALO_CACHE[key] = surf
        return surf
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    cx, cy = size[0] // 2, size[1] // 2
    ImageDraw.Draw(img).ellipse(
        (cx - radius, cy - radius, cx + radius, cy + radius),
        fill=(*color, alpha),
    )
    img = img.filter(ImageFilter.GaussianBlur(radius=blur))
    surf = pygame.image.frombytes(img.tobytes(), size, "RGBA").convert_alpha()
    _SOFT_HALO_CACHE[key] = surf
    return surf


def blit_soft_halo(surface: pygame.Surface, center: tuple[int, int],
                    radius: int, color: tuple[int, int, int],
                    *, alpha: int = 90, blur: int = 4) -> None:
    """Center-anchored wrapper around :func:`soft_halo`."""
    img = soft_halo(radius, color, alpha=alpha, blur=blur)
    surface.blit(img, (center[0] - img.get_width() // 2,
                        center[1] - img.get_height() // 2))


def _bake_background(size: tuple[int, int]) -> pygame.Surface:
    """Render the cached, atmospheric background.

    Two big diffuse color orbs (cool blue top-left, violet bottom-right) drift
    over a deep neutral gradient. No stars, no music notes — just blurry color.
    """
    cached = _BG_PLAIN_CACHE.get(size)
    if cached is not None:
        return cached
    w, h = size
    try:
        from PIL import Image, ImageDraw, ImageFilter  # type: ignore
    except Exception:
        # Pillow missing — fall back to a plain pygame gradient.
        surf = pygame.Surface(size).convert()
        for y in range(h):
            t = y / max(1, h - 1)
            r = int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t)
            g = int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t)
            b = int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t)
            pygame.draw.line(surf, (r, g, b), (0, y), (w, y))
        _BG_PLAIN_CACHE[size] = surf
        return surf

    # Step 1 — slate-grey vertical gradient via a 1-px-wide strip resized up.
    strip = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        r = int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t)
        g = int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t)
        b = int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t)
        strip.putpixel((0, y), (r, g, b))
    base = strip.resize((w, h), Image.BILINEAR)

    # Step 2 — paint a few big soft-edged blobs on a black canvas, blur hard,
    # then composite over the grey with a low alpha so it stays subtle.
    orbs = Image.new("RGB", (w, h), (0, 0, 0))
    od = ImageDraw.Draw(orbs)
    # Cool blue blob biased to the top-left.
    od.ellipse(
        (int(-w * 0.20), int(-h * 0.30), int(w * 0.65), int(h * 0.65)),
        fill=(48, 96, 188),
    )
    # Violet blob biased to the bottom-right.
    od.ellipse(
        (int(w * 0.40), int(h * 0.45), int(w * 1.25), int(h * 1.35)),
        fill=(122, 60, 198),
    )
    # Warm wash mid-right.
    od.ellipse(
        (int(w * 0.55), int(-h * 0.10), int(w * 1.15), int(h * 0.55)),
        fill=(72, 132, 188),
    )
    orbs = orbs.filter(ImageFilter.GaussianBlur(radius=max(100, min(w, h) // 4)))

    blended = Image.blend(base, orbs, 0.35)

    raw = blended.tobytes()
    surf = pygame.image.frombytes(raw, size, "RGB").convert()
    _BG_PLAIN_CACHE[size] = surf
    return surf


def draw_background(surface: pygame.Surface) -> None:
    """Atmospheric blurry-grey background with soft color orbs baked in."""
    surface.blit(_bake_background(surface.get_size()), (0, 0))


def _blurred_background(size: tuple[int, int]) -> pygame.Surface:
    """Pre-blurred copy of the baked background, the 'frosted glass' source
    re-blitted inside every glass card."""
    cached = _BG_BLURRED_CACHE.get(size)
    if cached is not None:
        return cached
    plain = _bake_background(size)
    try:
        from PIL import Image, ImageFilter, ImageEnhance  # type: ignore
        raw = pygame.image.tobytes(plain, "RGB")
        pil = Image.frombytes("RGB", size, raw)
        pil = pil.filter(ImageFilter.GaussianBlur(radius=28))
        pil = ImageEnhance.Brightness(pil).enhance(0.78)
        blurred = pygame.image.frombytes(pil.tobytes(), size, "RGB").convert()
    except Exception:
        try:
            small = pygame.transform.smoothscale(
                plain, (max(8, size[0] // 18), max(8, size[1] // 18)),
            )
            blurred = pygame.transform.smoothscale(small, size).convert()
        except Exception:
            blurred = plain.copy()
    _BG_BLURRED_CACHE[size] = blurred
    return blurred


def invalidate_background_cache() -> None:
    """Called when the window resizes — clears every size-keyed cache."""
    _BG_PLAIN_CACHE.clear()
    _BG_BLURRED_CACHE.clear()
    _GLOW_CACHE.clear()
    # Mask / stroke / shadow caches are keyed by (w, h, radius...) so they
    # survive a resize cleanly; only the per-window caches need a flush.


# ----------------------------------------------------------------------------
# Anti-aliased rounded-rect primitives.
#
# pygame's `border_radius` is fast but visibly stair-stepped at small sizes.
# These helpers draw every rounded shape in Pillow at 2× resolution then
# downsample with LANCZOS, then convert to a pygame surface — clean corners
# regardless of size. Results are cached so each unique shape is built once.
# ----------------------------------------------------------------------------

_PIL_SUPERSAMPLE = 2


def _rounded_mask(size: tuple[int, int], radius: int) -> pygame.Surface:
    """White rounded-rect on a transparent background. Used as an alpha mask
    via ``BLEND_RGBA_MIN`` to clip an arbitrary surface to a smooth shape."""
    key = (size[0], size[1], radius)
    cached = _ROUNDED_MASK_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        from PIL import Image, ImageDraw  # type: ignore
    except Exception:
        # Fallback: pygame's stair-stepped corners — better than nothing.
        surf = pygame.Surface(size, pygame.SRCALPHA)
        pygame.draw.rect(surf, (255, 255, 255, 255),
                         pygame.Rect(0, 0, size[0], size[1]),
                         border_radius=radius)
        _ROUNDED_MASK_CACHE[key] = surf
        return surf
    ss = _PIL_SUPERSAMPLE
    big = Image.new("L", (size[0] * ss, size[1] * ss), 0)
    ImageDraw.Draw(big).rounded_rectangle(
        (0, 0, size[0] * ss - 1, size[1] * ss - 1),
        radius=radius * ss, fill=255,
    )
    small = big.resize(size, Image.LANCZOS)
    rgba = Image.new("RGBA", size, (255, 255, 255, 0))
    rgba.putalpha(small)
    surf = pygame.image.frombytes(rgba.tobytes(), size, "RGBA").convert_alpha()
    _ROUNDED_MASK_CACHE[key] = surf
    return surf


def _rounded_stroke(size: tuple[int, int], radius: int,
                     color: tuple[int, int, int, int],
                     width: int = 1) -> pygame.Surface:
    """Thin anti-aliased rounded-rect outline."""
    key = (size[0], size[1], radius, color[0], color[1], color[2], color[3] * 256 + width)
    cached = _ROUNDED_STROKE_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        from PIL import Image, ImageDraw  # type: ignore
    except Exception:
        surf = pygame.Surface(size, pygame.SRCALPHA)
        pygame.draw.rect(surf, color[:3] + (color[3],),
                         pygame.Rect(0, 0, size[0], size[1]),
                         width=width, border_radius=radius)
        _ROUNDED_STROKE_CACHE[key] = surf
        return surf
    ss = _PIL_SUPERSAMPLE
    big = Image.new("RGBA", (size[0] * ss, size[1] * ss), (0, 0, 0, 0))
    ImageDraw.Draw(big).rounded_rectangle(
        (0, 0, size[0] * ss - 1, size[1] * ss - 1),
        radius=radius * ss, outline=color, width=max(1, width * ss),
    )
    small = big.resize(size, Image.LANCZOS)
    surf = pygame.image.frombytes(small.tobytes(), size, "RGBA").convert_alpha()
    _ROUNDED_STROKE_CACHE[key] = surf
    return surf


def _drop_shadow(size: tuple[int, int], radius: int, *,
                  alpha: int = 110, blur: int = 22) -> pygame.Surface:
    """Soft drop shadow shaped like the rounded rect of ``size``. The returned
    surface is bigger than ``size`` so the blur isn't clipped at the edges."""
    key = (size[0], size[1], radius, alpha, blur)
    cached = _DROP_SHADOW_CACHE.get(key)
    if cached is not None:
        return cached
    pad = blur * 2
    out_size = (size[0] + pad * 2, size[1] + pad * 2)
    try:
        from PIL import Image, ImageDraw, ImageFilter  # type: ignore
    except Exception:
        surf = pygame.Surface(out_size, pygame.SRCALPHA)
        pygame.draw.rect(surf, (0, 0, 0, alpha),
                         pygame.Rect(pad, pad, size[0], size[1]),
                         border_radius=radius)
        _DROP_SHADOW_CACHE[key] = surf
        return surf
    ss = _PIL_SUPERSAMPLE
    big = Image.new("RGBA", (out_size[0] * ss, out_size[1] * ss), (0, 0, 0, 0))
    ImageDraw.Draw(big).rounded_rectangle(
        (pad * ss, pad * ss,
         (pad + size[0]) * ss - 1, (pad + size[1]) * ss - 1),
        radius=radius * ss, fill=(0, 0, 0, alpha),
    )
    big = big.filter(ImageFilter.GaussianBlur(radius=blur * ss))
    small = big.resize(out_size, Image.LANCZOS)
    surf = pygame.image.frombytes(small.tobytes(), out_size, "RGBA").convert_alpha()
    _DROP_SHADOW_CACHE[key] = surf
    return surf


def _radial_glow(size: tuple[int, int],
                  color: tuple[int, int, int],
                  alpha: int = 110) -> pygame.Surface:
    """Soft round white-ish glow used as a 'spotlight' behind glass cards.
    Cached per (size, color, alpha) so each card variant builds once."""
    key = (size[0], size[1], (color[0] << 16) | (color[1] << 8) | color[2], alpha)
    cached = _GLOW_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        from PIL import Image, ImageDraw, ImageFilter  # type: ignore
    except Exception:
        surf = pygame.Surface(size, pygame.SRCALPHA)
        pygame.draw.ellipse(surf, (*color, alpha),
                            pygame.Rect(0, 0, size[0], size[1]))
        _GLOW_CACHE[key] = surf
        return surf
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse(
        (int(size[0] * 0.18), int(size[1] * 0.18),
         int(size[0] * 0.82), int(size[1] * 0.82)),
        fill=(*color, alpha),
    )
    img = img.filter(ImageFilter.GaussianBlur(radius=max(28, min(size) // 6)))
    surf = pygame.image.frombytes(img.tobytes(), size, "RGBA").convert_alpha()
    _GLOW_CACHE[key] = surf
    return surf


# --------------------------------------------------------------------------
# The remote: purple trapezoid body, gray coil antenna.
# --------------------------------------------------------------------------

def _trapezoid_points(cx: int, cy: int, top_w: int, bottom_w: int,
                      height: int) -> list[tuple[int, int]]:
    half_t = top_w // 2
    half_b = bottom_w // 2
    top_y = cy - height // 2
    bot_y = cy + height // 2
    return [
        (cx - half_t, top_y),
        (cx + half_t, top_y),
        (cx + half_b, bot_y),
        (cx - half_b, bot_y),
    ]


def _draw_coil_antenna(surface: pygame.Surface, top_center: tuple[int, int],
                        height: int, t: float) -> None:
    """Draw a vertical helical coil (antenna) with a small ball at the tip.

    A gentle horizontal sway tied to ``t`` makes it feel alive without being
    distracting.
    """
    cx0, base_y = top_center
    sway = math.sin(t * 1.4) * 4
    tip_x = cx0 + int(sway)
    tip_y = base_y - height
    coil_w = 26
    turns = 11
    samples = 110
    pts: list[tuple[int, int]] = []
    for i in range(samples + 1):
        u = i / samples
        # Slight ease so coils bunch near the base just a touch.
        y = base_y - int(height * u)
        # Linear interpolate the central x from base->tip for sway.
        cx = int(cx0 + (tip_x - cx0) * u)
        x = cx + int(math.sin(u * turns * math.tau) * (coil_w * 0.5))
        pts.append((x, y))
    # Shadow strand (slightly offset, darker).
    shadow_pts = [(x + 2, y + 2) for x, y in pts]
    pygame.draw.lines(surface, (10, 10, 20), False, shadow_pts, 4)
    # Main coil.
    pygame.draw.lines(surface, ANTENNA_DARK, False, pts, 5)
    pygame.draw.lines(surface, ANTENNA_GRAY, False, pts, 3)
    # Tip ball.
    pygame.draw.circle(surface, (20, 20, 30), (tip_x + 1, tip_y + 1), 9)
    pygame.draw.circle(surface, ANTENNA_GRAY, (tip_x, tip_y), 9)
    pygame.draw.circle(surface, (255, 255, 255), (tip_x - 3, tip_y - 3), 3)


def draw_remote_placeholder(surface: pygame.Surface, center: tuple[int, int],
                            theme: Theme, t: float,
                            scale: float = 1.0,
                            include_numpad: bool = True) -> pygame.Rect:
    """Draw the purple trapezoid controller with a gray coil antenna.

    Returns the body rect (handy for layout). Wider at the top, narrower at the
    bottom, with a small flat collar where the antenna mounts.
    """
    cx, cy = center
    bob = math.sin(t * 1.4) * 4
    cy = int(cy + bob)
    body_w_top = int(280 * scale)
    body_w_bot = int(180 * scale)
    body_h = int(190 * scale)
    body_top_y = cy - body_h // 2
    body_bot_y = cy + body_h // 2

    # Drop shadow underneath.
    shadow_pts = _trapezoid_points(cx, cy + 14, body_w_top, body_w_bot, body_h)
    shadow_surf = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    pygame.draw.polygon(shadow_surf, (0, 0, 0, 110), shadow_pts)
    surface.blit(shadow_surf, (0, 0))

    # Body trapezoid (solid purple — never gradient).
    body_pts = _trapezoid_points(cx, cy, body_w_top, body_w_bot, body_h)
    pygame.draw.polygon(surface, PURPLE, body_pts)
    # Thin darker rim along the bottom for depth (tiny band, not a fill gradient).
    bottom_band = [
        body_pts[3],
        body_pts[2],
        (body_pts[2][0] - 4, body_pts[2][1] - 8),
        (body_pts[3][0] + 4, body_pts[3][1] - 8),
    ]
    pygame.draw.polygon(surface, PURPLE_DEEP, bottom_band)
    # Outline.
    pygame.draw.polygon(surface, (20, 18, 50), body_pts, 3)
    # Subtle top highlight strip.
    hl_pts = [
        (body_pts[0][0] + 12, body_pts[0][1] + 4),
        (body_pts[1][0] - 12, body_pts[1][1] + 4),
        (body_pts[1][0] - 18, body_pts[1][1] + 10),
        (body_pts[0][0] + 18, body_pts[0][1] + 10),
    ]
    hl_surf = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    pygame.draw.polygon(hl_surf, (255, 255, 255, 55), hl_pts)
    surface.blit(hl_surf, (0, 0))

    # Antenna mount collar — small flat strip at the top center.
    collar_w = int(60 * scale)
    collar_h = int(12 * scale)
    collar = pygame.Rect(0, 0, collar_w, collar_h)
    collar.midbottom = (cx, body_top_y + 4)
    pygame.draw.rect(surface, _shade(PURPLE, 0.85), collar, border_radius=4)
    pygame.draw.rect(surface, (20, 18, 50), collar, width=2, border_radius=4)
    # Tiny LED dots on the collar (pure decoration).
    for i in range(4):
        dx = collar.left + 10 + i * ((collar_w - 20) // 3)
        pygame.draw.circle(surface, (15, 15, 30),
                           (dx, collar.centery), 2)

    # Coil antenna sticking up.
    antenna_h = int(170 * scale)
    _draw_coil_antenna(surface, (cx, collar.top + 2), antenna_h, t)

    if include_numpad:
        # 5 rows × 2 cols numpad of soft holes on the body face.
        rows, cols = 5, 2
        pad_w = int(body_w_bot * 0.62)
        pad_h = int(body_h * 0.74)
        pad_left = cx - pad_w // 2
        pad_top = cy - pad_h // 2 + int(8 * scale)
        for r in range(rows):
            for c in range(cols):
                px = pad_left + (pad_w // (cols - 1)) * c if cols > 1 else pad_left + pad_w // 2
                py = pad_top + (pad_h // (rows - 1)) * r if rows > 1 else pad_top + pad_h // 2
                pygame.draw.circle(surface, _shade(PURPLE, 0.7), (px, py),
                                   int(8 * scale))
                pygame.draw.circle(surface, (20, 18, 50), (px, py),
                                   int(8 * scale), 2)
                pygame.draw.circle(surface, (255, 255, 255),
                                   (px - int(2 * scale), py - int(2 * scale)),
                                   max(1, int(2 * scale)))

    body_rect = pygame.Rect(0, 0, body_w_top, body_h)
    body_rect.center = (cx, cy)
    return body_rect
