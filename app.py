"""Labcoin Music Remote — desktop companion.

Run with `python app.py`. The app walks the user through:

    Setup screen  ->  loading  ->  one of {5GHz error, out-of-range, connected}
                  ->  button check  ->  fullscreen main menu (player count)
                  ->  round picker  ->  countdown  ->  game placeholder.

The actual radio link to the ESP32 lives in `esp32_connector.py` so
nothing here ever blocks on BLE / sockets.
"""

from __future__ import annotations

import math
import sys
import time
import ctypes
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Optional

import pygame

import doodle
from doodle import (
    ACCENT_BLUE, ACCENT_CYAN, ACCENT_GREEN, ACCENT_PINK,
    ACCENT_RED, ACCENT_YELLOW, INK, INK_DIM, INK_SOFT,
    NoteFountain, PANEL_FILL, PANEL_HI, PURPLE, Theme,
    build_note_palette, draw_background, draw_chunky_button,
    draw_crisp_label, draw_doodle_panel, draw_doodle_text,
    draw_remote_placeholder,
    load_image_alpha, make_main_menu_hint_fonts, scale_menu_logo,
)
from esp32_connector import (
    BUTTON_NAMES, Esp32Connector, Event, NUMPAD_BUTTONS,
)
import strings_bg as BG

ROOT = Path(__file__).parent
LOGOS = ROOT / "logos"

WINDOW_SIZE = (980, 640)
# Borderless window (no title bar). Keep RESIZABLE so edges can still resize on Windows.
_WINDOW_FLAGS = pygame.NOFRAME | pygame.RESIZABLE
FPS = 60


def _primary_monitor_size_px() -> tuple[int, int]:
    """Physical primary-monitor size for real fullscreen.

    ``pygame.display.Info().current_w/h`` often report the *current window*
    size (e.g. 980×640), not the desktop — using that for ``FULLSCREEN`` is
    what made the \"fullscreen\" look like a small square stretched wrong.

    Prefer SDL's desktop list (accurate once pygame is initialised); then Win32
    metrics as a fallback.
    """
    try:
        sizes = pygame.display.get_desktop_sizes()
        if sizes:
            w, h = int(sizes[0][0]), int(sizes[0][1])
            if w > 160 and h > 160:
                return w, h
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            user32 = ctypes.windll.user32
            w = int(user32.GetSystemMetrics(0))  # SM_CXSCREEN
            h = int(user32.GetSystemMetrics(1))  # SM_CYSCREEN
            if w > 160 and h > 160:
                return w, h
        except Exception:
            pass
    info = pygame.display.Info()
    if info.current_w > 0 and info.current_h > 0:
        return info.current_w, info.current_h
    return 1920, 1080

# Order the on-screen button check walks the user through.
# Maps to ESP button index. Mirrors send_song.py's BUTTON_NAMES.
BUTTON_CHECK_SEQUENCE = [
    1,   # Checkmark
    2,   # Double checkmark
    9,   # Numpad 1
    7,   # Numpad 2
    6,   # Numpad 3
    10,  # Numpad 4
    8,   # Numpad 5
    5,   # Numpad 6
    11,  # Numpad 7
    12,  # Numpad 8
    4,   # Numpad 9
    3,   # Numpad 10
]

# Pygame keyboard equivalents so the GUI is testable without the remote.
KEY_DIGIT_MAP = {
    pygame.K_KP1: 1, pygame.K_1: 1,
    pygame.K_KP2: 2, pygame.K_2: 2,
    pygame.K_KP3: 3, pygame.K_3: 3,
    pygame.K_KP4: 4, pygame.K_4: 4,
    pygame.K_KP5: 5, pygame.K_5: 5,
    pygame.K_KP6: 6, pygame.K_6: 6,
    pygame.K_KP7: 7, pygame.K_7: 7,
    pygame.K_KP8: 8, pygame.K_8: 8,
    pygame.K_KP9: 9, pygame.K_9: 9,
    pygame.K_KP0: 10, pygame.K_0: 10,
}


class Screen(Enum):
    SETUP = auto()
    LOADING = auto()
    BAND_5GHZ = auto()
    OUT_OF_RANGE = auto()
    CONNECTED_OK = auto()
    BUTTON_CHECK = auto()
    MAIN_MENU = auto()
    ROUND_SELECT = auto()
    COUNTDOWN = auto()
    PLAYING = auto()


@dataclass
class AppState:
    screen: Screen = Screen.SETUP
    status_text: str = BG.STATUS_DEFAULT
    last_error: str = ""
    last_5ghz_ssid: str = ""
    button_check_idx: int = 0
    button_check_done: dict[int, bool] = field(default_factory=dict)
    player_count: int = 0
    round_count: int = 0
    countdown_start: float = 0.0
    last_button_label: str = ""
    last_button_at: float = 0.0
    fullscreen: bool = False


class App:
    def __init__(self) -> None:
        pygame.init()
        pygame.display.set_caption(BG.WINDOW_TITLE)
        self.screen = pygame.display.set_mode(WINDOW_SIZE, _WINDOW_FLAGS)
        self.clock = pygame.time.Clock()
        self.theme = Theme.make()
        self.state = AppState()
        self.connector = Esp32Connector()

        # Load the game logo + note PNGs.
        self.game_logo = load_image_alpha(LOGOS / "gamelogo.avif")
        if self.game_logo is None:
            # Fall back to one of the note PNGs scaled big if AVIF is missing.
            for name in ("8thNote.svg.png", "Doublecroche3.svg.png"):
                cand = load_image_alpha(LOGOS / name)
                if cand is not None:
                    self.game_logo = cand
                    break
        note_paths = [
            LOGOS / "8thNote.svg.png",
            LOGOS / "Blanche3.svg.png",
            LOGOS / "Doublecroche3.svg.png",
            LOGOS / "Dotted_32nd_note_with_upward_stem.svg.png",
        ]
        self.note_palette = build_note_palette(note_paths)
        if not self.note_palette:
            print("WARN: no music-note PNGs found in logos/ — sides will be empty.",
                  file=sys.stderr)
        self.left_notes = self._make_fountain("left")
        self.right_notes = self._make_fountain("right")

        self.start_time = time.monotonic()
        self.start_button_rect = pygame.Rect(0, 0, 240, 90)
        self.reload_button_rect = pygame.Rect(0, 0, 220, 80)
        self.skip_button_rect = pygame.Rect(0, 0, 220, 60)
        self.button_check_continue_rect = pygame.Rect(0, 0, 280, 72)
        self._menu_logo_cache: tuple[tuple[int, int], pygame.Surface] | None = None

    # ------------------------------------------------------------------ helpers

    def _make_fountain(self, side: str) -> NoteFountain:
        w, h = self.screen.get_size()
        margin = 110
        if side == "left":
            area = pygame.Rect(0, 0, margin, h)
        else:
            area = pygame.Rect(w - margin, 0, margin, h)
        if not self.note_palette:
            return NoteFountain([], side, area, density=0)
        return NoteFountain(self.note_palette, side, area,
                            density=10 if w >= 1100 else 7)

    def _refresh_fountain_areas(self) -> None:
        w, h = self.screen.get_size()
        margin = 130 if w >= 1100 else 110
        self.left_notes.resize(pygame.Rect(0, 0, margin, h))
        self.right_notes.resize(pygame.Rect(w - margin, 0, margin, h))

    def _scaled_menu_logo(self, max_w: int, max_h: int) -> Optional[pygame.Surface]:
        if self.game_logo is None:
            return None
        key = (max_w, max_h)
        if self._menu_logo_cache and self._menu_logo_cache[0] == key:
            return self._menu_logo_cache[1]
        scaled = scale_menu_logo(self.game_logo, max_w, max_h)
        self._menu_logo_cache = (key, scaled)
        return scaled

    def set_screen(self, screen: Screen, *, status: Optional[str] = None) -> None:
        self.state.screen = screen
        if status is not None:
            self.state.status_text = status

    def _all_button_check_tiles_pressed(self) -> bool:
        st = self.state
        return all(st.button_check_done.get(btn, False) for btn in BUTTON_CHECK_SEQUENCE)

    def _button_check_can_continue(self) -> bool:
        """True when the ordered walk is finished or every pad was hit at least once."""
        st = self.state
        if st.screen != Screen.BUTTON_CHECK:
            return False
        return (
            st.button_check_idx >= len(BUTTON_CHECK_SEQUENCE)
            or self._all_button_check_tiles_pressed()
        )

    def go_fullscreen(self) -> None:
        if self.state.fullscreen:
            return
        w, h = _primary_monitor_size_px()
        # Explicit desktop resolution + exclusive fullscreen (not the tiny window size).
        self.screen = pygame.display.set_mode(
            (w, h), pygame.FULLSCREEN | pygame.DOUBLEBUF
        )
        self.state.fullscreen = True
        self._menu_logo_cache = None
        self._refresh_fountain_areas()

    def go_windowed(self) -> None:
        if not self.state.fullscreen:
            return
        self.screen = pygame.display.set_mode(WINDOW_SIZE, _WINDOW_FLAGS)
        self.state.fullscreen = False
        self._menu_logo_cache = None
        self._refresh_fountain_areas()

    # ------------------------------------------------------------------ events

    def handle_connector_events(self) -> None:
        for ev in self.connector.poll_events():
            self._handle_event(ev)

    def _handle_event(self, ev: Event) -> None:
        st = self.state
        if ev.kind == "status":
            if st.screen in (Screen.LOADING, Screen.OUT_OF_RANGE, Screen.BAND_5GHZ):
                st.status_text = BG.translate_worker_status(ev.text)
        elif ev.kind == "error":
            if ev.text.startswith("NET5GHZ:"):
                _, ssid, _ = (ev.text.split(":", 2) + ["", ""])[:3]
                st.last_5ghz_ssid = ssid
                self.set_screen(Screen.BAND_5GHZ,
                                status=BG.STATUS_5GHZ)
            elif ev.text == "OUTOFRANGE":
                self.set_screen(Screen.OUT_OF_RANGE,
                                status=BG.STATUS_OOR)
            else:
                st.last_error = ev.text
                if st.screen in (Screen.LOADING, Screen.CONNECTED_OK,
                                  Screen.BUTTON_CHECK):
                    self.set_screen(Screen.OUT_OF_RANGE,
                                    status=BG.STATUS_LOST_LINK.format(
                                        err=BG.translate_connection_error(ev.text)))
        elif ev.kind == "connected":
            self.set_screen(Screen.CONNECTED_OK,
                            status=BG.STATUS_CONNECTED.format(addr=ev.text))
        elif ev.kind == "disconnected":
            if st.screen not in (Screen.SETUP, Screen.BAND_5GHZ):
                self.set_screen(Screen.OUT_OF_RANGE,
                                status=BG.STATUS_DISCONNECTED)
        elif ev.kind == "button":
            self._on_button(ev)

    def _on_button(self, ev: Event) -> None:
        st = self.state
        st.last_button_label = ev.text
        st.last_button_at = time.monotonic()
        if st.screen == Screen.BUTTON_CHECK:
            if ev.button is not None:
                st.button_check_done[ev.button] = True
                if st.button_check_idx < len(BUTTON_CHECK_SEQUENCE):
                    expected = BUTTON_CHECK_SEQUENCE[st.button_check_idx]
                    if ev.button == expected:
                        st.button_check_idx += 1
        elif st.screen == Screen.MAIN_MENU and ev.digit is not None:
            self._pick_player_count(ev.digit)
        elif st.screen == Screen.ROUND_SELECT and ev.digit is not None:
            self._pick_round_count(ev.digit)

    def _finish_button_check(self) -> None:
        self.go_fullscreen()
        self.set_screen(Screen.MAIN_MENU, status="")

    def _pick_player_count(self, n: int) -> None:
        self.state.player_count = n
        self.set_screen(Screen.ROUND_SELECT,
                        status=BG.STATUS_ROUNDS)

    def _pick_round_count(self, n: int) -> None:
        self.state.round_count = n
        self.state.countdown_start = time.monotonic()
        self.set_screen(Screen.COUNTDOWN, status="")

    # ------------------------------------------------------------------ frame

    def run(self) -> None:
        running = True
        while running:
            dt = self.clock.tick(FPS) / 1000.0
            t = time.monotonic() - self.start_time
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.VIDEORESIZE and not self.state.fullscreen:
                    self.screen = pygame.display.set_mode(event.size, _WINDOW_FLAGS)
                    self._menu_logo_cache = None
                    self._refresh_fountain_areas()
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        if self.state.fullscreen:
                            running = False
                        else:
                            running = False
                    elif event.key == pygame.K_F11:
                        if self.state.fullscreen:
                            self.go_windowed()
                        else:
                            self.go_fullscreen()
                    else:
                        self._handle_keydown(event)
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    self._handle_click(event.pos)

            self.handle_connector_events()
            self._update(dt, t)
            self._draw(t)
            pygame.display.flip()

        self.connector.stop()
        pygame.quit()

    def _handle_keydown(self, event: pygame.event.Event) -> None:
        st = self.state
        if event.key == pygame.K_RETURN or event.key == pygame.K_SPACE:
            if st.screen == Screen.SETUP:
                self._start_connection()
            elif st.screen in (Screen.BAND_5GHZ, Screen.OUT_OF_RANGE):
                self._reload()
            elif st.screen == Screen.CONNECTED_OK:
                self._begin_button_check()
            elif st.screen == Screen.BUTTON_CHECK and self._button_check_can_continue():
                self._finish_button_check()
        elif event.key == pygame.K_F1 and st.screen == Screen.BUTTON_CHECK:
            # Dev shortcut: skip button check.
            self._finish_button_check()
        elif event.key in KEY_DIGIT_MAP:
            digit = KEY_DIGIT_MAP[event.key]
            if st.screen == Screen.MAIN_MENU:
                self._pick_player_count(digit)
            elif st.screen == Screen.ROUND_SELECT:
                self._pick_round_count(digit)
            elif st.screen == Screen.BUTTON_CHECK:
                # Allow keyboard to step through during testing without remote.
                if st.button_check_idx >= len(BUTTON_CHECK_SEQUENCE):
                    return
                expected = BUTTON_CHECK_SEQUENCE[st.button_check_idx]
                st.button_check_done[expected] = True
                st.button_check_idx += 1

    def _handle_click(self, pos: tuple[int, int]) -> None:
        st = self.state
        if st.screen == Screen.SETUP and self.start_button_rect.collidepoint(pos):
            self._start_connection()
        elif st.screen in (Screen.BAND_5GHZ, Screen.OUT_OF_RANGE) and \
                self.reload_button_rect.collidepoint(pos):
            self._reload()
        elif st.screen == Screen.CONNECTED_OK and self.skip_button_rect.collidepoint(pos):
            self._begin_button_check()
        elif st.screen == Screen.BUTTON_CHECK \
                and self.button_check_continue_rect.collidepoint(pos) \
                and self._button_check_can_continue():
            self._finish_button_check()

    def _start_connection(self) -> None:
        self.set_screen(Screen.LOADING,
                        status=BG.STATUS_SEARCHING_BLE)
        self.connector.start()

    def _reload(self) -> None:
        self.set_screen(Screen.LOADING, status=BG.STATUS_RETRYING)
        self.connector.request_immediate_reconnect()

    def _begin_button_check(self) -> None:
        self.state.button_check_idx = 0
        self.state.button_check_done = {}
        self.set_screen(Screen.BUTTON_CHECK,
                        status=BG.STATUS_BUTTON_CHECK)

    # ------------------------------------------------------------------ update

    def _update(self, dt: float, t: float) -> None:
        self.left_notes.update(dt, t)
        self.right_notes.update(dt, t)
        st = self.state
        if st.screen == Screen.COUNTDOWN:
            elapsed = time.monotonic() - st.countdown_start
            if elapsed >= 11:
                self.set_screen(Screen.PLAYING,
                                status=BG.PLAYING_STATUS)

    # ------------------------------------------------------------------ draw

    def _draw(self, t: float) -> None:
        draw_background(self.screen)
        self.left_notes.draw(self.screen, t)
        self.right_notes.draw(self.screen, t)

        st = self.state
        draw_fn = {
            Screen.SETUP: self._draw_setup,
            Screen.LOADING: self._draw_loading,
            Screen.BAND_5GHZ: self._draw_band_5ghz,
            Screen.OUT_OF_RANGE: self._draw_out_of_range,
            Screen.CONNECTED_OK: self._draw_connected_ok,
            Screen.BUTTON_CHECK: self._draw_button_check,
            Screen.MAIN_MENU: self._draw_main_menu,
            Screen.ROUND_SELECT: self._draw_round_select,
            Screen.COUNTDOWN: self._draw_countdown,
            Screen.PLAYING: self._draw_playing,
        }[st.screen]
        draw_fn(t)
        self._draw_status_bar()

    def _center(self) -> tuple[int, int]:
        w, h = self.screen.get_size()
        return w // 2, h // 2

    def _panel_rect(self, w: int, h: int, dy: int = 0) -> pygame.Rect:
        cx, cy = self._center()
        rect = pygame.Rect(0, 0, w, h)
        rect.center = (cx, cy + dy)
        return rect

    def _draw_status_bar(self) -> None:
        st = self.state
        if not st.status_text:
            return
        w, h = self.screen.get_size()
        y = h - 42
        txt_surf = self.theme.small_font.render(st.status_text, True, INK)
        txt_rect = txt_surf.get_rect(center=(w // 2, y))
        self.screen.blit(txt_surf, txt_rect)
        if st.last_button_label and (time.monotonic() - st.last_button_at) < 2.5:
            badge = self.theme.small_font.render(
                f"→ {st.last_button_label}", True, ACCENT_CYAN
            )
            self.screen.blit(badge,
                             badge.get_rect(midright=(w - 22, y)))

    # ------------------ individual screens ---------------------------------

    def _draw_setup(self, t: float) -> None:
        cx, cy = self._center()
        panel = self._panel_rect(620, 420, dy=-20)
        draw_doodle_panel(self.screen, panel, fill=PANEL_FILL,
                           outline=PURPLE, radius=28)
        # Wordmark above the headline.
        draw_doodle_text(self.screen, BG.TITLE_WORDMARK,
                          self.theme.body_font, ACCENT_CYAN,
                          (panel.centerx, panel.top + 44), anchor="center",
                          shadow=False)
        draw_doodle_text(self.screen, BG.TITLE_APP,
                          self.theme.title_font, INK,
                          (panel.centerx, panel.top + 90), anchor="center")
        # Underline accent.
        ul = pygame.Rect(0, 0, 110, 5)
        ul.center = (panel.centerx, panel.top + 122)
        pygame.draw.rect(self.screen, ACCENT_PINK, ul, border_radius=3)
        draw_doodle_text(self.screen, BG.SETUP_LINE1,
                          self.theme.body_font, INK_SOFT,
                          (panel.centerx, panel.top + 175), anchor="center",
                          shadow=False)
        draw_doodle_text(self.screen, BG.SETUP_LINE2,
                          self.theme.body_font, INK_SOFT,
                          (panel.centerx, panel.top + 205), anchor="center",
                          shadow=False)
        self.start_button_rect = pygame.Rect(0, 0, 260, 88)
        self.start_button_rect.center = (panel.centerx, panel.bottom - 80)
        mouse = pygame.mouse.get_pos()
        draw_chunky_button(self.screen, self.start_button_rect, BG.BTN_START,
                            self.theme, fill=ACCENT_GREEN,
                            text_color=(15, 25, 30),
                            hovered=self.start_button_rect.collidepoint(mouse))

    def _draw_loading(self, t: float) -> None:
        cx, cy = self._center()
        panel = self._panel_rect(560, 320, dy=-10)
        draw_doodle_panel(self.screen, panel, fill=PANEL_FILL,
                           outline=PURPLE, radius=28)
        draw_doodle_text(self.screen, BG.LOADING_TITLE,
                          self.theme.title_font, INK,
                          (panel.centerx, panel.top + 72), anchor="center")
        # Five neon dots traveling in a wave.
        colors = [ACCENT_PINK, ACCENT_CYAN, ACCENT_YELLOW, ACCENT_GREEN, PURPLE]
        for i, color in enumerate(colors):
            phase = t * 4 - i * 0.6
            scale = 0.7 + 0.6 * (0.5 + 0.5 * math.sin(phase))
            r = int(11 * scale)
            x = panel.centerx - 96 + i * 48
            y = panel.centery + 18 + int(math.sin(phase) * 6)
            pygame.draw.circle(self.screen, (0, 0, 0, 80), (x + 2, y + 3), r)
            pygame.draw.circle(self.screen, color, (x, y), r)
            pygame.draw.circle(self.screen, (255, 255, 255), (x - r // 3, y - r // 3),
                               max(1, r // 3))

    def _draw_warning_screen(self, title: str, lines: list[str], t: float,
                              accent: tuple[int, int, int]) -> None:
        panel = self._panel_rect(660, 380, dy=-20)
        draw_doodle_panel(self.screen, panel, fill=PANEL_FILL,
                           outline=accent, radius=28)
        draw_doodle_text(self.screen, title, self.theme.title_font, accent,
                          (panel.centerx, panel.top + 64), anchor="center")
        ul = pygame.Rect(0, 0, 90, 5)
        ul.center = (panel.centerx, panel.top + 96)
        pygame.draw.rect(self.screen, accent, ul, border_radius=3)
        for i, line in enumerate(lines):
            draw_doodle_text(self.screen, line, self.theme.body_font, INK,
                              (panel.centerx, panel.top + 140 + i * 36),
                              anchor="center", shadow=False)
        self.reload_button_rect = pygame.Rect(0, 0, 230, 74)
        self.reload_button_rect.center = (panel.centerx, panel.bottom - 64)
        mouse = pygame.mouse.get_pos()
        draw_chunky_button(self.screen, self.reload_button_rect, BG.BTN_RELOAD,
                            self.theme, fill=accent, text_color=(20, 20, 30),
                            hovered=self.reload_button_rect.collidepoint(mouse))

    def _draw_band_5ghz(self, t: float) -> None:
        ssid_line = (BG.WARN_WIFI_ON_SSID.format(ssid=self.state.last_5ghz_ssid)
                     if self.state.last_5ghz_ssid
                     else BG.WARN_WIFI_ON_5GHZ)
        self._draw_warning_screen(
            BG.WARN_WIFI_BAND,
            [
                ssid_line,
                BG.WARN_WIFI_SWITCH,
                BG.WARN_WIFI_RELOAD,
            ],
            t, accent=ACCENT_PINK,
        )

    def _draw_out_of_range(self, t: float) -> None:
        cx, cy = self._center()
        panel = self._panel_rect(660, 540, dy=-10)
        draw_doodle_panel(self.screen, panel, fill=PANEL_FILL,
                           outline=ACCENT_PINK, radius=28)
        draw_doodle_text(self.screen, BG.OOR_TITLE,
                          self.theme.title_font, ACCENT_PINK,
                          (panel.centerx, panel.top + 50), anchor="center")
        ul = pygame.Rect(0, 0, 110, 5)
        ul.center = (panel.centerx, panel.top + 82)
        pygame.draw.rect(self.screen, ACCENT_PINK, ul, border_radius=3)
        # Move the controller well below the title so the antenna clears it.
        draw_remote_placeholder(self.screen,
                                  (panel.centerx, panel.centery + 40),
                                  self.theme, t, scale=0.6,
                                  include_numpad=False)
        draw_doodle_text(self.screen, BG.OOR_BODY,
                          self.theme.body_font, INK_SOFT,
                          (panel.centerx, panel.bottom - 96), anchor="center",
                          shadow=False)
        self.reload_button_rect = pygame.Rect(0, 0, 240, 64)
        self.reload_button_rect.center = (panel.centerx, panel.bottom - 46)
        mouse = pygame.mouse.get_pos()
        draw_chunky_button(self.screen, self.reload_button_rect, BG.BTN_RETRY_NOW,
                            self.theme, fill=ACCENT_CYAN,
                            text_color=(15, 25, 30),
                            hovered=self.reload_button_rect.collidepoint(mouse))

    def _draw_connected_ok(self, t: float) -> None:
        cx, cy = self._center()
        panel = self._panel_rect(660, 560, dy=-20)
        draw_doodle_panel(self.screen, panel, fill=PANEL_FILL,
                           outline=ACCENT_GREEN, radius=28)
        draw_doodle_text(self.screen, BG.CONNECTED_TITLE,
                          self.theme.title_font, ACCENT_GREEN,
                          (panel.centerx, panel.top + 50), anchor="center")
        ul = pygame.Rect(0, 0, 90, 5)
        ul.center = (panel.centerx, panel.top + 82)
        pygame.draw.rect(self.screen, ACCENT_GREEN, ul, border_radius=3)
        # Drop the controller well below the title so the antenna doesn't graze it.
        draw_remote_placeholder(self.screen,
                                  (panel.centerx, panel.centery + 30),
                                  self.theme, t, scale=0.7)
        draw_doodle_text(self.screen,
                          BG.CONNECTED_HINT,
                          self.theme.small_font, INK_SOFT,
                          (panel.centerx, panel.bottom - 96), anchor="center",
                          shadow=False)
        self.skip_button_rect = pygame.Rect(0, 0, 250, 64)
        self.skip_button_rect.center = (panel.centerx, panel.bottom - 46)
        mouse = pygame.mouse.get_pos()
        draw_chunky_button(self.screen, self.skip_button_rect, BG.BTN_CONTINUE,
                            self.theme, fill=ACCENT_GREEN,
                            text_color=(15, 30, 25),
                            hovered=self.skip_button_rect.collidepoint(mouse))

    def _draw_button_check(self, t: float) -> None:
        st = self.state
        w, h = self.screen.get_size()
        can_continue = self._button_check_can_continue()
        panel = self._panel_rect(min(w - 80, 800), min(h - 80, 560), dy=0)
        draw_doodle_panel(self.screen, panel, fill=PANEL_FILL,
                           outline=PURPLE, radius=28)
        draw_doodle_text(self.screen, BG.BUTTON_CHECK_TITLE,
                          self.theme.title_font, INK,
                          (panel.centerx, panel.top + 50), anchor="center")
        if can_continue:
            draw_doodle_text(self.screen, BG.BUTTON_CHECK_DONE,
                              self.theme.body_font, ACCENT_GREEN,
                              (panel.centerx, panel.top + 95), anchor="center",
                              shadow=False)
            draw_doodle_text(self.screen, BG.BUTTON_CHECK_KEYS,
                              self.theme.small_font, INK_SOFT,
                              (panel.centerx, panel.top + 126), anchor="center",
                              shadow=False)
        elif st.button_check_idx < len(BUTTON_CHECK_SEQUENCE):
            target_btn = BUTTON_CHECK_SEQUENCE[st.button_check_idx]
            target_name = BUTTON_NAMES.get(
                target_btn, BG.FB_FALLBACK_BUTTON.format(n=target_btn))
            draw_doodle_text(self.screen, BG.BUTTON_CHECK_PRESS.format(label=target_name),
                              self.theme.body_font, ACCENT_PINK,
                              (panel.centerx, panel.top + 95), anchor="center",
                              shadow=False)
        cols = 4
        rows = (len(BUTTON_CHECK_SEQUENCE) + cols - 1) // cols
        cell_w = (panel.width - 60) // cols
        bottom_reserve = 130 if can_continue else 180
        cell_h = min(95 if can_continue else 110,
                     (panel.height - bottom_reserve) // rows)
        grid_top = panel.top + 138 if can_continue else panel.top + 130
        for i, btn in enumerate(BUTTON_CHECK_SEQUENCE):
            r = i // cols
            c = i % cols
            tile = pygame.Rect(0, 0, cell_w - 16, cell_h - 16)
            tile.topleft = (panel.left + 30 + c * cell_w + 8,
                             grid_top + r * cell_h + 8)
            done = st.button_check_done.get(btn, False)
            current = (i == st.button_check_idx)
            if done:
                fill = ACCENT_GREEN
                ink = (15, 30, 25)
            elif current:
                pulse = 0.5 + 0.5 * math.sin(t * 5)
                base = ACCENT_CYAN
                fill = (int(base[0] * (0.55 + 0.45 * pulse)),
                        int(base[1] * (0.55 + 0.45 * pulse)),
                        int(base[2] * (0.55 + 0.45 * pulse)))
                ink = (15, 25, 30)
            else:
                fill = PANEL_HI
                ink = INK_SOFT
            self._draw_tile(tile, fill, label_color=ink,
                              label=BUTTON_NAMES.get(btn, BG.FB_FALLBACK_BUTTON.format(n=btn)),
                              done=done)
        if can_continue:
            self.button_check_continue_rect = pygame.Rect(0, 0, 290, 72)
            self.button_check_continue_rect.midbottom = (
                panel.centerx, panel.bottom - 24)
            mouse = pygame.mouse.get_pos()
            draw_chunky_button(
                self.screen, self.button_check_continue_rect, BG.BTN_CONTINUE,
                self.theme, fill=ACCENT_GREEN, text_color=(15, 30, 25),
                hovered=self.button_check_continue_rect.collidepoint(mouse),
            )

    def _draw_tile_with_font(self, tile: pygame.Rect,
                              fill: tuple[int, int, int],
                              label_color: tuple[int, int, int],
                              label: str,
                              font: pygame.font.Font) -> None:
        base = doodle._shade(fill, 0.55)
        pygame.draw.rect(self.screen, base, tile.move(0, 6), border_radius=14)
        pygame.draw.rect(self.screen, fill, tile, border_radius=14)
        pygame.draw.rect(self.screen, doodle._shade(fill, 0.4), tile,
                          width=2, border_radius=14)
        hl = pygame.Rect(tile.left + 6, tile.top + 4,
                         tile.width - 12, max(4, tile.height // 4))
        hl_surf = pygame.Surface(hl.size, pygame.SRCALPHA)
        pygame.draw.rect(hl_surf, (255, 255, 255, 55),
                          pygame.Rect(0, 0, hl.width, hl.height),
                          border_radius=12)
        self.screen.blit(hl_surf, hl.topleft)
        txt = font.render(label, True, label_color)
        self.screen.blit(txt, txt.get_rect(center=tile.center))

    def _draw_tile(self, tile: pygame.Rect,
                    fill: tuple[int, int, int],
                    label_color: tuple[int, int, int],
                    label: str, done: bool) -> None:
        """Chunky 3D-feeling tile (matches the in-app button language)."""
        base = doodle._shade(fill, 0.55)
        pygame.draw.rect(self.screen, base, tile.move(0, 6), border_radius=14)
        pygame.draw.rect(self.screen, fill, tile, border_radius=14)
        pygame.draw.rect(self.screen, doodle._shade(fill, 0.4), tile,
                          width=2, border_radius=14)
        # Top highlight.
        hl = pygame.Rect(tile.left + 6, tile.top + 4,
                         tile.width - 12, max(4, tile.height // 4))
        hl_surf = pygame.Surface(hl.size, pygame.SRCALPHA)
        pygame.draw.rect(hl_surf, (255, 255, 255, 55),
                          pygame.Rect(0, 0, hl.width, hl.height),
                          border_radius=12)
        self.screen.blit(hl_surf, hl.topleft)
        txt = self.theme.small_font.render(label, True, label_color)
        self.screen.blit(txt, txt.get_rect(center=tile.center))
        if done:
            check = self.theme.title_font.render(BG.TILE_OK, True, (15, 30, 25))
            self.screen.blit(check,
                               check.get_rect(midright=(tile.right - 12,
                                                          tile.top + 18)))

    def _draw_main_menu(self, t: float) -> None:
        w, h = self.screen.get_size()
        banner_reserve = 160
        max_logo_w = max(160, min(380, int(w * 0.38)))
        max_logo_h = max(120, min(200, int((h - banner_reserve) * 0.30)))
        logo = self._scaled_menu_logo(max_logo_w, max_logo_h)
        # Anchor logo slightly above centre so hints fit comfortably underneath.
        logo_cy = h // 2 - max(56, min(110, h // 14))

        if logo is not None:
            lr = logo.get_rect(center=(w // 2, logo_cy))
            self.screen.blit(logo, lr)
            hints_top = lr.bottom + 14
        elif not self.game_logo:
            draw_doodle_text(self.screen, BG.MAIN_MENU_FALLBACK,
                              self.theme.huge_font, INK,
                              (w // 2, logo_cy), anchor="center")
            hints_top = logo_cy + self.theme.huge_font.get_height() // 2 + 14
        else:
            hints_top = logo_cy + 48

        hint_head, hint_sub = make_main_menu_hint_fonts(w, h)
        cx = w // 2
        r1 = draw_crisp_label(self.screen, hint_head, BG.MAIN_MENU_LINE1,
                               INK, (cx, hints_top), anchor="midtop")
        draw_crisp_label(self.screen, hint_sub, BG.MAIN_MENU_LINE2,
                          INK_SOFT, (cx, r1.bottom + 6), anchor="midtop")

    def _draw_round_select(self, t: float) -> None:
        w, h = self.screen.get_size()
        head_size = max(56, min(96, w // 14))
        head_font = pygame.font.Font(pygame.font.match_font(
            "segoe ui,segoeui,nunitoblack,nunito,poppins,segoeuiblack,segoeui,arial"
        ), head_size)
        head_font.set_bold(True)
        draw_doodle_text(self.screen,
                          BG.players_phrase(self.state.player_count),
                          self.theme.title_font, ACCENT_CYAN,
                          (w // 2, 90), anchor="center", shadow=False)
        draw_doodle_text(self.screen, BG.ROUND_TITLE,
                          head_font, INK,
                          (w // 2, 170), anchor="center")
        ul = pygame.Rect(0, 0, 200, 6)
        ul.center = (w // 2, 170 + head_size // 2 + 14)
        pygame.draw.rect(self.screen, ACCENT_PINK, ul, border_radius=3)
        draw_doodle_text(self.screen, BG.ROUND_HINT,
                          self.theme.body_font, INK_SOFT,
                          (w // 2, ul.bottom + 32), anchor="center", shadow=False)
        # Chunky 5×2 number pad sized to fit the available area.
        pad_cols, pad_rows = 5, 2
        avail_top = ul.bottom + 70
        avail_bottom = h - 90  # leave space for the status bar
        avail_w = w - 120
        cell = max(56, min(110,
                            min(avail_w // (pad_cols + 1),
                                (avail_bottom - avail_top) // (pad_rows + 1) * 2)))
        gap = max(8, cell // 9)
        pad_w = pad_cols * cell + (pad_cols - 1) * gap
        pad_h = pad_rows * cell + (pad_rows - 1) * gap
        pad_left = w // 2 - pad_w // 2
        pad_top = (avail_top + avail_bottom) // 2 - pad_h // 2
        accents = [ACCENT_PINK, ACCENT_CYAN, ACCENT_YELLOW, ACCENT_GREEN, PURPLE,
                   ACCENT_BLUE, (255, 159, 67), ACCENT_RED,
                   ACCENT_PINK, ACCENT_CYAN]
        digit_font = pygame.font.Font(pygame.font.match_font(
            "segoe ui,segoeui,nunitoblack,nunito,poppins,segoeuiblack,segoeui,arial"
        ),
            max(28, cell // 2))
        digit_font.set_bold(True)
        for i, n in enumerate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]):
            row, col = divmod(i, pad_cols)
            tile = pygame.Rect(0, 0, cell, cell)
            tile.topleft = (pad_left + col * (cell + gap),
                             pad_top + row * (cell + gap))
            color = accents[i % len(accents)]
            self._draw_tile_with_font(tile, color, label_color=(15, 25, 30),
                                       label=str(n if n < 10 else 0),
                                       font=digit_font)

    def _draw_countdown(self, t: float) -> None:
        w, h = self.screen.get_size()
        elapsed = time.monotonic() - self.state.countdown_start
        remaining = max(0, 10 - int(elapsed))
        accents = [ACCENT_PINK, ACCENT_CYAN, ACCENT_YELLOW,
                   ACCENT_GREEN, PURPLE, ACCENT_BLUE]
        cx, cy = w // 2, h // 2
        if remaining == 0:
            color = ACCENT_GREEN
            label = BG.COUNTDOWN_GO
        else:
            color = accents[(10 - remaining) % len(accents)]
            label = str(remaining)
        scale = 1.0 + 0.45 * (1 - (elapsed - int(elapsed)))
        base = self.theme.huge_font.render(label, True, color)
        target_w = max(1, int(base.get_width() * scale))
        target_h = max(1, int(base.get_height() * scale))
        big = pygame.transform.smoothscale(base, (target_w, target_h))
        # Multi-pass glow: render the same text in successive translucent
        # layers offset around the center for a chunky neon halo, no big halo
        # ellipse competing with the digit.
        glow_layers = [
            (28, 30),
            (18, 60),
            (10, 110),
        ]
        for offset, alpha in glow_layers:
            ghost = pygame.transform.smoothscale(base,
                (target_w + offset * 2, target_h + offset * 2))
            ghost = ghost.copy()
            ghost.set_alpha(alpha)
            self.screen.blit(ghost, ghost.get_rect(center=(cx, cy)))
        self.screen.blit(big, big.get_rect(center=(cx, cy)))
        draw_doodle_text(self.screen,
                          BG.rounds_count_bg(self.state.player_count,
                                             self.state.round_count),
                          self.theme.body_font, INK_SOFT,
                          (cx, cy + 220), anchor="center", shadow=False)

    def _draw_playing(self, t: float) -> None:
        w, h = self.screen.get_size()
        draw_doodle_text(self.screen, BG.PLAYING_TITLE,
                          self.theme.huge_font, ACCENT_GREEN,
                          (w // 2, h // 2 - 60), anchor="center")
        draw_doodle_text(self.screen,
                          BG.rounds_count_bg(self.state.player_count,
                                               self.state.round_count),
                          self.theme.title_font, INK,
                          (w // 2, h // 2 + 60), anchor="center", shadow=False)
        draw_doodle_text(self.screen, BG.PLAYING_NOTE,
                          self.theme.small_font, INK_DIM,
                          (w // 2, h // 2 + 140), anchor="center", shadow=False)


def main() -> int:
    try:
        App().run()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
