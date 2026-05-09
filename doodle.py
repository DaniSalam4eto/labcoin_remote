"""Doodle / cartoon styling helpers for the Labcoin Music Remote app.

Everything visual that wants to look hand-drawn or skin-toned ("bejov" /
beige) lives here so the UI screens in `app.py` stay short.

The two main building blocks are:

  * `Theme`               -- color palette + cached fonts.
  * `NoteFountain`        -- the floating colored music notes that decorate
                              the left and right edges of every screen.

Plus a handful of free functions that draw rounded buttons, panels, and
text with a slight pen-jitter so things read as cartoon rather than CAD.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pygame

# --------------------------------------------------------------------------
# Color palette: warm beige / human skin-tone family + bright doodle accents.
# --------------------------------------------------------------------------

BEIGE_BG       = (245, 224, 196)
BEIGE_BG_DARK  = (228, 200, 167)
BEIGE_PANEL    = (252, 235, 213)
BEIGE_PANEL_HI = (255, 244, 226)
INK            = (60, 35, 20)
INK_SOFT       = (110, 78, 52)
ACCENT_RED     = (220, 90, 70)
ACCENT_GREEN   = (76, 162, 92)
ACCENT_GREEN_D = (50, 120, 70)
ACCENT_BLUE    = (80, 140, 210)
ACCENT_YELLOW  = (240, 195, 70)
ACCENT_PURPLE  = (160, 100, 190)
ACCENT_PINK    = (235, 130, 175)
ACCENT_ORANGE  = (235, 145, 70)

NOTE_COLORS = [
    ACCENT_RED, ACCENT_BLUE, ACCENT_YELLOW,
    ACCENT_PURPLE, ACCENT_PINK, ACCENT_ORANGE, ACCENT_GREEN,
]


@dataclass
class Theme:
    title_font: pygame.font.Font
    body_font:  pygame.font.Font
    small_font: pygame.font.Font
    huge_font:  pygame.font.Font

    @classmethod
    def make(cls) -> "Theme":
        # Comic Sans is the canonical "doodle" font on Windows. Fall back to
        # whatever pygame can find if the user nuked it.
        try:
            title_name = pygame.font.match_font("comicsansms,comic sans ms,segoe print")
        except Exception:
            title_name = None
        body_name = title_name
        return cls(
            title_font=pygame.font.Font(title_name, 36),
            body_font=pygame.font.Font(body_name, 22),
            small_font=pygame.font.Font(body_name, 16),
            huge_font=pygame.font.Font(title_name, 110),
        )


# --------------------------------------------------------------------------
# Image utilities.
# --------------------------------------------------------------------------

def load_image_alpha(path: Path) -> Optional[pygame.Surface]:
    """Load a transparent PNG / AVIF and return it as a pygame surface.

    AVIF is routed through Pillow because pygame's image loader does not
    handle it natively.
    """
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
            return pygame.image.fromstring(img.tobytes(), img.size, "RGBA").convert_alpha()
        except Exception:
            return None
    try:
        return pygame.image.load(str(path)).convert_alpha()
    except Exception:
        return None


def colorize(surface: pygame.Surface, color: tuple[int, int, int]) -> pygame.Surface:
    """Replace the RGB of every non-transparent pixel with `color`.

    The alpha channel of the source is kept verbatim, so anti-aliased
    edges still look soft. Implemented through PIL to avoid pulling
    numpy in for `pygame.surfarray`.
    """
    try:
        from PIL import Image  # type: ignore
    except Exception:
        # Fallback: fill solid color and clip with source alpha via BLEND_RGBA_MIN.
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
    """Load every note PNG once per accent color, return the cross-product.

    Result list is randomly indexable; each surface already has its color
    baked in so per-frame blitting is free.
    """
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
# Doodle drawing helpers.
# --------------------------------------------------------------------------

def jitter_polyline(points: list[tuple[float, float]], amount: float = 1.4,
                    seed: int = 0) -> list[tuple[int, int]]:
    rng = random.Random(seed)
    return [(int(x + rng.uniform(-amount, amount)),
             int(y + rng.uniform(-amount, amount))) for x, y in points]


def _rounded_rect_points(rect: pygame.Rect, radius: int, n_per_corner: int = 6
                         ) -> list[tuple[float, float]]:
    r = min(radius, rect.width // 2, rect.height // 2)
    cx_l, cx_r = rect.left + r, rect.right - r
    cy_t, cy_b = rect.top + r, rect.bottom - r
    pts: list[tuple[float, float]] = []
    # Top edge then top-right arc, etc. Going clockwise starting top-left arc end.
    # Order: top-left arc (180->270), top edge, top-right arc (270->360),
    # right edge, bottom-right arc (0->90), bottom edge, bottom-left arc (90->180), left edge.
    for i in range(n_per_corner + 1):
        a = math.radians(180 + 90 * i / n_per_corner)
        pts.append((cx_l + math.cos(a) * r, cy_t + math.sin(a) * r))
    for i in range(n_per_corner + 1):
        a = math.radians(270 + 90 * i / n_per_corner)
        pts.append((cx_r + math.cos(a) * r, cy_t + math.sin(a) * r))
    for i in range(n_per_corner + 1):
        a = math.radians(0 + 90 * i / n_per_corner)
        pts.append((cx_r + math.cos(a) * r, cy_b + math.sin(a) * r))
    for i in range(n_per_corner + 1):
        a = math.radians(90 + 90 * i / n_per_corner)
        pts.append((cx_l + math.cos(a) * r, cy_b + math.sin(a) * r))
    return pts


def draw_doodle_panel(surface: pygame.Surface, rect: pygame.Rect,
                      fill: tuple[int, int, int] = BEIGE_PANEL,
                      outline: tuple[int, int, int] = INK,
                      radius: int = 22, seed: int = 17) -> None:
    """Filled rounded rect with a wobbly, double-stroked outline."""
    pygame.draw.rect(surface, fill, rect, border_radius=radius)
    base = _rounded_rect_points(rect, radius)
    # Two slightly-different jittered passes give the hand-drawn look.
    for i, (amount, width, shade) in enumerate(((1.6, 4, outline), (1.0, 2, BEIGE_BG_DARK))):
        pts = jitter_polyline(base, amount=amount, seed=seed + i)
        if len(pts) >= 2:
            pygame.draw.lines(surface, shade, True, pts, width)


def draw_doodle_button(surface: pygame.Surface, rect: pygame.Rect, label: str,
                       theme: Theme,
                       fill: tuple[int, int, int] = BEIGE_PANEL_HI,
                       outline: tuple[int, int, int] = INK,
                       text_color: tuple[int, int, int] = INK,
                       hovered: bool = False,
                       seed: int = 23) -> None:
    if hovered:
        rect = rect.inflate(6, 6)
        # Drop shadow lifts the button when hovered.
        shadow = rect.move(3, 4)
        pygame.draw.rect(surface, INK_SOFT, shadow, border_radius=24)
    draw_doodle_panel(surface, rect, fill=fill, outline=outline, radius=24, seed=seed)
    txt = theme.title_font.render(label, True, text_color)
    surface.blit(txt, txt.get_rect(center=rect.center))


def draw_doodle_text(surface: pygame.Surface, text: str, font: pygame.font.Font,
                     color: tuple[int, int, int], pos: tuple[int, int],
                     anchor: str = "center", shadow: bool = True) -> pygame.Rect:
    main = font.render(text, True, color)
    rect = main.get_rect(**{anchor: pos})
    if shadow:
        ghost = font.render(text, True, BEIGE_BG_DARK)
        surface.blit(ghost, rect.move(2, 3))
    surface.blit(main, rect)
    return rect


def draw_background(surface: pygame.Surface) -> None:
    """Soft beige vertical gradient — drawn once per frame as the base layer."""
    w, h = surface.get_size()
    top = BEIGE_PANEL_HI
    bot = BEIGE_BG_DARK
    for y in range(h):
        t = y / max(1, h - 1)
        r = int(top[0] + (bot[0] - top[0]) * t)
        g = int(top[1] + (bot[1] - top[1]) * t)
        b = int(top[2] + (bot[2] - top[2]) * t)
        pygame.draw.line(surface, (r, g, b), (0, y), (w, y))


def draw_remote_placeholder(surface: pygame.Surface, center: tuple[int, int],
                            theme: Theme, t: float) -> None:
    """Stylised cartoon remote that bobs gently. Stand-in until a real asset lands."""
    bob = math.sin(t * 1.6) * 8
    cx, cy = center[0], int(center[1] + bob)
    body = pygame.Rect(0, 0, 180, 260)
    body.center = (cx, cy)
    # Soft drop shadow.
    shadow = body.move(0, 14)
    pygame.draw.rect(surface, (180, 150, 120), shadow, border_radius=28)
    draw_doodle_panel(surface, body, fill=ACCENT_BLUE, outline=INK, radius=28, seed=99)
    # Mock OLED screen at the top.
    screen = pygame.Rect(0, 0, 130, 70)
    screen.midtop = (cx, body.top + 22)
    pygame.draw.rect(surface, (30, 30, 40), screen, border_radius=8)
    pygame.draw.rect(surface, INK, screen, 3, border_radius=8)
    note_glyph = theme.body_font.render("Music ON", True, (180, 240, 200))
    surface.blit(note_glyph, note_glyph.get_rect(center=screen.center))
    # Numpad-ish dots underneath.
    pad_top = screen.bottom + 18
    for row in range(4):
        for col in range(3):
            bx = body.left + 28 + col * 50
            by = pad_top + row * 32
            pygame.draw.circle(surface, BEIGE_PANEL_HI, (bx, by), 11)
            pygame.draw.circle(surface, INK, (bx, by), 11, 2)
