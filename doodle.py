"""Visual styling helpers for the Labcoin Music Remote app.

The palette deliberately avoids any beige / skin tones — the app now lives on a
deep midnight background with vivid neon accents. The core building blocks
exposed to ``app.py`` are:

  * `Theme`               -- font cache.
  * `NoteFountain`        -- floating colored music notes that decorate the
                              left and right edges of every screen.

Plus a handful of free functions that draw soft-shadowed panels, chunky
3D-feeling buttons, crisp text, and the purple trapezoid remote with its
gray coil antenna.
"""

from __future__ import annotations

import math
import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pygame

# --------------------------------------------------------------------------
# Color palette — vivid, playful, and explicitly *not* beige/skin-tone.
# All gradients are vertical *background* gradients only; per the design
# brief the controller and other purple surfaces are solid (no purple
# gradients anywhere).
# --------------------------------------------------------------------------

# Background pair (deep midnight, very subtle vertical gradient).
BG_TOP        = (16, 18, 38)       # #101226
BG_BOTTOM     = (8, 9, 22)         # #080916

# Panel / surface tones.
PANEL_FILL    = (28, 30, 58)       # #1C1E3A
PANEL_HI      = (40, 44, 80)       # #282C50
PANEL_OUTLINE = (255, 255, 255)
PANEL_SHADOW  = (4, 4, 14)

# Text.
INK           = (245, 245, 255)    # near-white
INK_SOFT      = (180, 184, 220)
INK_DIM       = (130, 134, 175)

# Controller.
PURPLE        = (158, 96, 255)     # #9E60FF — solid; no gradient ever
PURPLE_DEEP   = (108, 60, 200)     # used only as a thin shading band, *not* a fill gradient
ANTENNA_GRAY  = (200, 204, 215)
ANTENNA_DARK  = (132, 138, 156)

# Vibrant accents (used for buttons, headlines, notes).
ACCENT_PINK   = (255, 99, 176)     # #FF63B0
ACCENT_CYAN   = (77, 224, 214)     # #4DE0D6
ACCENT_YELLOW = (255, 217, 61)     # #FFD93D
ACCENT_GREEN  = (91, 212, 119)     # #5BD477
ACCENT_GREEN_D = (60, 170, 90)
ACCENT_BLUE   = (87, 182, 255)     # #57B6FF
ACCENT_RED    = (255, 96, 109)     # #FF606D
ACCENT_ORANGE = (255, 159, 67)     # #FF9F43
ACCENT_PURPLE = PURPLE             # alias

# Legacy aliases kept so older imports don't break (just point at the new palette).
BEIGE_BG       = BG_TOP
BEIGE_BG_DARK  = BG_BOTTOM
BEIGE_PANEL    = PANEL_FILL
BEIGE_PANEL_HI = PANEL_HI

NOTE_COLORS = [
    ACCENT_PINK, ACCENT_CYAN, ACCENT_YELLOW,
    ACCENT_GREEN, ACCENT_BLUE, ACCENT_ORANGE, PURPLE,
]


# --------------------------------------------------------------------------
# Font discovery — real TTF files render Cyrillic much cleaner than synthetic
# pygame.bold on random fallbacks.
# --------------------------------------------------------------------------

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
            "segoe ui,segoeui,calibri,candara,trebuchet ms,arial"
        )
    except Exception:
        return None


def make_main_menu_hint_fonts(screen_w: int, screen_h: int
                               ) -> tuple[pygame.font.Font, pygame.font.Font]:
    """Smaller, tight headline + body for the lines under the logo."""
    fb = match_font_fallback()
    head_path = ui_font_semibold_path() or ui_font_bold_path() \
        or ui_font_regular_path() or fb
    sub_path = ui_font_regular_path() or fb
    # Compact sizes; respect vertical space on short windows.
    head_px = max(15, min(20, min(screen_w // 56, screen_h // 42)))
    sub_px = max(12, min(16, min(screen_w // 72, screen_h // 52)))
    head = pygame.font.Font(head_path, head_px)
    head.set_bold(False)
    sub = pygame.font.Font(sub_path, sub_px)
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
    def make(cls) -> "Theme":
        fb = match_font_fallback()
        reg = ui_font_regular_path()
        bold = ui_font_bold_path()
        semi = ui_font_semibold_path()
        title_path = bold or semi or reg or fb
        body_path = reg or fb
        huge_path = bold or semi or title_path

        title = pygame.font.Font(title_path, 34)
        title.set_bold(False)
        huge = pygame.font.Font(huge_path, 122)
        huge.set_bold(False)
        body = pygame.font.Font(body_path, 21)
        body.set_bold(False)
        small = pygame.font.Font(body_path, 15)
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
            try:
                import pillow_avif  # noqa: F401  (registers AVIF plugin)
            except Exception:
                pass
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
        target_h = random.randint(34, 64)
        img = scale_to_height(base, target_h)
        return _FloatingNote(
            image=img,
            x=self._random_x(),
            y=(random.uniform(self.area.top, self.area.bottom)
               if initial else self.area.bottom + random.uniform(20, 200)),
            speed=random.uniform(28, 60),
            sway_amp=random.uniform(8, 22),
            sway_freq=random.uniform(0.6, 1.6),
            sway_phase=random.uniform(0, math.tau),
            spin=random.uniform(-12, 12),
            spin_speed=random.uniform(-25, 25),
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


def draw_doodle_panel(surface: pygame.Surface, rect: pygame.Rect,
                      fill: tuple[int, int, int] = PANEL_FILL,
                      outline: tuple[int, int, int] = PANEL_OUTLINE,
                      radius: int = 24, seed: int = 0) -> None:
    """Soft-shadowed rounded panel.

    ``seed`` is accepted for API compatibility but no longer used to
    randomise the outline — the new look is clean, not hand-drawn.
    """
    del seed  # unused, kept for back-compat with existing call sites
    shadow = rect.move(0, 8)
    shadow_surf = pygame.Surface((rect.width + 24, rect.height + 24), pygame.SRCALPHA)
    pygame.draw.rect(shadow_surf, (*PANEL_SHADOW, 130),
                     pygame.Rect(12, 12, rect.width, rect.height),
                     border_radius=radius + 2)
    surface.blit(shadow_surf, (shadow.left - 12, shadow.top - 12))
    pygame.draw.rect(surface, fill, rect, border_radius=radius)
    # Inner highlight band along the top edge for a glassy feel.
    hl = pygame.Surface((rect.width - 8, max(1, radius)), pygame.SRCALPHA)
    pygame.draw.rect(hl, (255, 255, 255, 22),
                     pygame.Rect(0, 0, hl.get_width(), hl.get_height()),
                     border_radius=radius)
    surface.blit(hl, (rect.left + 4, rect.top + 2))
    if outline is not None:
        pygame.draw.rect(surface, outline, rect, width=2, border_radius=radius)


def draw_chunky_button(surface: pygame.Surface, rect: pygame.Rect, label: str,
                       theme: Theme,
                       fill: tuple[int, int, int] = ACCENT_CYAN,
                       text_color: tuple[int, int, int] = (15, 15, 30),
                       hovered: bool = False,
                       depth: int = 7) -> None:
    """3D-feeling chunky button — a darker base sits behind a flat top face.

    The dark base shows through at the bottom edge to suggest thickness, like
    the tile boxes from the button-check screen.
    """
    rect = rect.copy()
    if hovered:
        rect = rect.inflate(6, 6)
        depth = max(3, depth - 2)
    base_color = _shade(fill, 0.55)
    base = rect.move(0, depth)
    pygame.draw.rect(surface, base_color, base, border_radius=18)
    top = rect
    pygame.draw.rect(surface, fill, top, border_radius=18)
    # Glassy top highlight.
    hl = pygame.Rect(top.left + 6, top.top + 4, top.width - 12, max(4, top.height // 4))
    hl_surf = pygame.Surface(hl.size, pygame.SRCALPHA)
    pygame.draw.rect(hl_surf, (255, 255, 255, 65),
                     pygame.Rect(0, 0, hl.width, hl.height),
                     border_radius=14)
    surface.blit(hl_surf, hl.topleft)
    # Outline.
    pygame.draw.rect(surface, _shade(fill, 0.4), top, width=2, border_radius=18)
    txt = theme.title_font.render(label, True, text_color)
    surface.blit(txt, txt.get_rect(center=top.center))


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


def draw_background(surface: pygame.Surface) -> None:
    """Deep midnight gradient with a subtle starfield dot pattern.

    Background is the only place a vertical gradient is allowed; it's a
    midnight-navy fade, not purple.
    """
    w, h = surface.get_size()
    top = BG_TOP
    bot = BG_BOTTOM
    for y in range(h):
        t = y / max(1, h - 1)
        r = int(top[0] + (bot[0] - top[0]) * t)
        g = int(top[1] + (bot[1] - top[1]) * t)
        b = int(top[2] + (bot[2] - top[2]) * t)
        pygame.draw.line(surface, (r, g, b), (0, y), (w, y))
    _draw_starfield(surface)


_STARFIELD_CACHE: dict[tuple[int, int], pygame.Surface] = {}


def _draw_starfield(surface: pygame.Surface) -> None:
    w, h = surface.get_size()
    key = (w, h)
    cached = _STARFIELD_CACHE.get(key)
    if cached is None:
        rng = random.Random(7)
        layer = pygame.Surface((w, h), pygame.SRCALPHA)
        # Soft scattered dots — 0.6 per 1000 px² density.
        count = max(40, (w * h) // 1700)
        for _ in range(count):
            x = rng.randint(0, w - 1)
            y = rng.randint(0, h - 1)
            r = rng.choice([1, 1, 1, 2, 2, 3])
            a = rng.randint(40, 140)
            color = rng.choice([
                (255, 255, 255, a),
                (180, 220, 255, a),
                (220, 180, 255, a),
            ])
            pygame.draw.circle(layer, color, (x, y), r)
        _STARFIELD_CACHE[key] = layer
        cached = layer
    surface.blit(cached, (0, 0))


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
