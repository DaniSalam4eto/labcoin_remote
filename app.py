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
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Optional

import pygame

import doodle
from doodle import (
    ACCENT_BLUE, ACCENT_GREEN, ACCENT_GREEN_D, ACCENT_RED, ACCENT_YELLOW,
    BEIGE_BG, BEIGE_BG_DARK, BEIGE_PANEL, BEIGE_PANEL_HI,
    INK, INK_SOFT,
    NoteFountain, Theme,
    build_note_palette, draw_background, draw_doodle_button,
    draw_doodle_panel, draw_doodle_text, draw_remote_placeholder,
    load_image_alpha, scale_to_height,
)
from esp32_connector import (
    BUTTON_NAMES, Esp32Connector, Event, NUMPAD_BUTTONS,
)

ROOT = Path(__file__).parent
LOGOS = ROOT / "logos"

WINDOW_SIZE = (980, 640)
FPS = 60

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
    status_text: str = "Press START to find the remote."
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
        pygame.display.set_caption("Labcoin Music Remote")
        self.screen = pygame.display.set_mode(WINDOW_SIZE, pygame.RESIZABLE)
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

    def set_screen(self, screen: Screen, *, status: Optional[str] = None) -> None:
        self.state.screen = screen
        if status is not None:
            self.state.status_text = status

    def go_fullscreen(self) -> None:
        if self.state.fullscreen:
            return
        info = pygame.display.Info()
        self.screen = pygame.display.set_mode(
            (info.current_w, info.current_h), pygame.FULLSCREEN
        )
        self.state.fullscreen = True
        self._refresh_fountain_areas()

    def go_windowed(self) -> None:
        if not self.state.fullscreen:
            return
        self.screen = pygame.display.set_mode(WINDOW_SIZE, pygame.RESIZABLE)
        self.state.fullscreen = False
        self._refresh_fountain_areas()

    # ------------------------------------------------------------------ events

    def handle_connector_events(self) -> None:
        for ev in self.connector.poll_events():
            self._handle_event(ev)

    def _handle_event(self, ev: Event) -> None:
        st = self.state
        if ev.kind == "status":
            if st.screen in (Screen.LOADING, Screen.OUT_OF_RANGE, Screen.BAND_5GHZ):
                st.status_text = ev.text
        elif ev.kind == "error":
            if ev.text.startswith("NET5GHZ:"):
                _, ssid, _ = (ev.text.split(":", 2) + ["", ""])[:3]
                st.last_5ghz_ssid = ssid
                self.set_screen(Screen.BAND_5GHZ,
                                status="You're on a 5 GHz network.")
            elif ev.text == "OUTOFRANGE":
                self.set_screen(Screen.OUT_OF_RANGE,
                                status="Remote isn't in range — bring it closer.")
            else:
                st.last_error = ev.text
                if st.screen in (Screen.LOADING, Screen.CONNECTED_OK,
                                  Screen.BUTTON_CHECK):
                    self.set_screen(Screen.OUT_OF_RANGE,
                                    status=f"Lost link: {ev.text}")
        elif ev.kind == "connected":
            self.set_screen(Screen.CONNECTED_OK,
                            status=f"Remote connected ({ev.text}).")
        elif ev.kind == "disconnected":
            if st.screen not in (Screen.SETUP, Screen.BAND_5GHZ):
                self.set_screen(Screen.OUT_OF_RANGE,
                                status="Remote disconnected. Retrying every 15 s...")
        elif ev.kind == "button":
            self._on_button(ev)

    def _on_button(self, ev: Event) -> None:
        st = self.state
        st.last_button_label = ev.text
        st.last_button_at = time.monotonic()
        if st.screen == Screen.BUTTON_CHECK:
            if ev.button is not None:
                st.button_check_done[ev.button] = True
                expected = BUTTON_CHECK_SEQUENCE[st.button_check_idx]
                if ev.button == expected:
                    st.button_check_idx += 1
                    if st.button_check_idx >= len(BUTTON_CHECK_SEQUENCE):
                        self._finish_button_check()
        elif st.screen == Screen.MAIN_MENU and ev.digit is not None:
            self._pick_player_count(ev.digit)
        elif st.screen == Screen.ROUND_SELECT and ev.digit is not None:
            self._pick_round_count(ev.digit)

    def _finish_button_check(self) -> None:
        self.go_fullscreen()
        self.set_screen(Screen.MAIN_MENU,
                        status="Press the number of players on the remote.")

    def _pick_player_count(self, n: int) -> None:
        self.state.player_count = n
        self.set_screen(Screen.ROUND_SELECT,
                        status="How many rounds? Press a number.")

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
                    self.screen = pygame.display.set_mode(event.size, pygame.RESIZABLE)
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
                expected = BUTTON_CHECK_SEQUENCE[st.button_check_idx]
                st.button_check_done[expected] = True
                st.button_check_idx += 1
                if st.button_check_idx >= len(BUTTON_CHECK_SEQUENCE):
                    self._finish_button_check()

    def _handle_click(self, pos: tuple[int, int]) -> None:
        st = self.state
        if st.screen == Screen.SETUP and self.start_button_rect.collidepoint(pos):
            self._start_connection()
        elif st.screen in (Screen.BAND_5GHZ, Screen.OUT_OF_RANGE) and \
                self.reload_button_rect.collidepoint(pos):
            self._reload()
        elif st.screen == Screen.CONNECTED_OK and self.skip_button_rect.collidepoint(pos):
            self._begin_button_check()

    def _start_connection(self) -> None:
        self.set_screen(Screen.LOADING,
                        status="Searching for the remote over BLE...")
        self.connector.start()

    def _reload(self) -> None:
        self.set_screen(Screen.LOADING, status="Retrying...")
        self.connector.request_immediate_reconnect()

    def _begin_button_check(self) -> None:
        self.state.button_check_idx = 0
        self.state.button_check_done = {}
        self.set_screen(Screen.BUTTON_CHECK,
                        status="Press the highlighted button on the remote.")

    # ------------------------------------------------------------------ update

    def _update(self, dt: float, t: float) -> None:
        self.left_notes.update(dt, t)
        self.right_notes.update(dt, t)
        st = self.state
        if st.screen == Screen.COUNTDOWN:
            elapsed = time.monotonic() - st.countdown_start
            if elapsed >= 11:
                self.set_screen(Screen.PLAYING,
                                status="GAME ON — listen on the remote!")

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
        rect = pygame.Rect(20, h - 50, w - 40, 36)
        draw_doodle_panel(self.screen, rect, fill=BEIGE_PANEL_HI,
                           outline=INK_SOFT, radius=18, seed=303)
        txt = self.theme.small_font.render(st.status_text, True, INK)
        self.screen.blit(txt, txt.get_rect(midleft=(rect.left + 16, rect.centery)))
        if st.last_button_label and (time.monotonic() - st.last_button_at) < 2.5:
            badge = self.theme.small_font.render(
                f"<- {st.last_button_label}", True, ACCENT_GREEN_D
            )
            self.screen.blit(badge,
                             badge.get_rect(midright=(rect.right - 16, rect.centery)))

    # ------------------ individual screens ---------------------------------

    def _draw_setup(self, t: float) -> None:
        cx, cy = self._center()
        panel = self._panel_rect(560, 360, dy=-30)
        draw_doodle_panel(self.screen, panel)
        draw_doodle_text(self.screen, "Labcoin Music Remote",
                          self.theme.title_font, INK,
                          (panel.centerx, panel.top + 60), anchor="center")
        draw_doodle_text(self.screen, "Setup",
                          self.theme.title_font, ACCENT_RED,
                          (panel.centerx, panel.top + 105), anchor="center")
        draw_doodle_text(self.screen, "Make sure your PC is on the same",
                          self.theme.body_font, INK_SOFT,
                          (panel.centerx, panel.top + 165), anchor="center")
        draw_doodle_text(self.screen, "2.4 GHz Wi-Fi as the remote.",
                          self.theme.body_font, INK_SOFT,
                          (panel.centerx, panel.top + 195), anchor="center")
        # START button.
        self.start_button_rect = pygame.Rect(0, 0, 240, 90)
        self.start_button_rect.center = (panel.centerx, panel.bottom - 70)
        mouse = pygame.mouse.get_pos()
        draw_doodle_button(self.screen, self.start_button_rect, "START",
                            self.theme,
                            fill=ACCENT_GREEN, text_color=(255, 250, 240),
                            hovered=self.start_button_rect.collidepoint(mouse),
                            seed=44)

    def _draw_loading(self, t: float) -> None:
        cx, cy = self._center()
        panel = self._panel_rect(520, 280, dy=-10)
        draw_doodle_panel(self.screen, panel)
        draw_doodle_text(self.screen, "Searching for the remote",
                          self.theme.title_font, INK,
                          (panel.centerx, panel.top + 70), anchor="center")
        # Spinner: three doodle dots that pulse.
        for i in range(3):
            scale = 1.0 + 0.5 * math.sin(t * 4 + i * 0.7)
            r = int(14 * scale)
            x = panel.centerx - 60 + i * 60
            y = panel.centery + 20
            color = [ACCENT_RED, ACCENT_BLUE, ACCENT_YELLOW][i]
            pygame.draw.circle(self.screen, color, (x, y), r)
            pygame.draw.circle(self.screen, INK, (x, y), r, 2)
        draw_doodle_text(self.screen, self.state.status_text,
                          self.theme.small_font, INK_SOFT,
                          (panel.centerx, panel.bottom - 40), anchor="center",
                          shadow=False)

    def _draw_warning_screen(self, title: str, lines: list[str], t: float,
                              accent: tuple[int, int, int]) -> None:
        panel = self._panel_rect(620, 360, dy=-20)
        draw_doodle_panel(self.screen, panel)
        draw_doodle_text(self.screen, title, self.theme.title_font, accent,
                          (panel.centerx, panel.top + 60), anchor="center")
        for i, line in enumerate(lines):
            draw_doodle_text(self.screen, line, self.theme.body_font, INK,
                              (panel.centerx, panel.top + 130 + i * 36),
                              anchor="center", shadow=False)
        self.reload_button_rect = pygame.Rect(0, 0, 220, 70)
        self.reload_button_rect.center = (panel.centerx, panel.bottom - 60)
        mouse = pygame.mouse.get_pos()
        draw_doodle_button(self.screen, self.reload_button_rect, "RELOAD",
                            self.theme, fill=accent, text_color=(255, 250, 240),
                            hovered=self.reload_button_rect.collidepoint(mouse),
                            seed=77)

    def _draw_band_5ghz(self, t: float) -> None:
        ssid_line = (f"You're on \"{self.state.last_5ghz_ssid}\"."
                     if self.state.last_5ghz_ssid
                     else "You're on a 5 GHz Wi-Fi.")
        self._draw_warning_screen(
            "Wrong Wi-Fi band!",
            [
                ssid_line,
                "Switch your PC to a 2.4 GHz network",
                "and press RELOAD.",
            ],
            t, accent=ACCENT_RED,
        )

    def _draw_out_of_range(self, t: float) -> None:
        cx, cy = self._center()
        panel = self._panel_rect(620, 420, dy=-20)
        draw_doodle_panel(self.screen, panel)
        draw_doodle_text(self.screen, "Remote isn't in range",
                          self.theme.title_font, ACCENT_RED,
                          (panel.centerx, panel.top + 56), anchor="center")
        # Floating remote placeholder.
        draw_remote_placeholder(self.screen,
                                  (panel.centerx, panel.centery + 10),
                                  self.theme, t)
        draw_doodle_text(self.screen, "Bring it closer — retrying every 15 s.",
                          self.theme.body_font, INK,
                          (panel.centerx, panel.bottom - 78), anchor="center",
                          shadow=False)
        self.reload_button_rect = pygame.Rect(0, 0, 220, 60)
        self.reload_button_rect.center = (panel.centerx, panel.bottom - 32)
        mouse = pygame.mouse.get_pos()
        draw_doodle_button(self.screen, self.reload_button_rect, "RETRY NOW",
                            self.theme, fill=ACCENT_BLUE,
                            text_color=(255, 250, 240),
                            hovered=self.reload_button_rect.collidepoint(mouse),
                            seed=121)

    def _draw_connected_ok(self, t: float) -> None:
        cx, cy = self._center()
        panel = self._panel_rect(620, 460, dy=-30)
        draw_doodle_panel(self.screen, panel)
        draw_doodle_text(self.screen, "Remote connected!",
                          self.theme.title_font, ACCENT_GREEN_D,
                          (panel.centerx, panel.top + 56), anchor="center")
        draw_remote_placeholder(self.screen,
                                  (panel.centerx, panel.centery - 10),
                                  self.theme, t)
        draw_doodle_text(self.screen,
                          "Press SPACE / click CONTINUE to test the buttons.",
                          self.theme.small_font, INK_SOFT,
                          (panel.centerx, panel.bottom - 80), anchor="center",
                          shadow=False)
        self.skip_button_rect = pygame.Rect(0, 0, 240, 60)
        self.skip_button_rect.center = (panel.centerx, panel.bottom - 36)
        mouse = pygame.mouse.get_pos()
        draw_doodle_button(self.screen, self.skip_button_rect, "CONTINUE",
                            self.theme, fill=ACCENT_GREEN,
                            text_color=(255, 250, 240),
                            hovered=self.skip_button_rect.collidepoint(mouse),
                            seed=180)

    def _draw_button_check(self, t: float) -> None:
        st = self.state
        w, h = self.screen.get_size()
        # Panel takes most of the (small / windowed) area.
        panel = self._panel_rect(min(w - 80, 760), min(h - 80, 540), dy=0)
        draw_doodle_panel(self.screen, panel)
        draw_doodle_text(self.screen, "Button Check",
                          self.theme.title_font, INK,
                          (panel.centerx, panel.top + 50), anchor="center")
        # Currently-expected prompt.
        if st.button_check_idx < len(BUTTON_CHECK_SEQUENCE):
            target_btn = BUTTON_CHECK_SEQUENCE[st.button_check_idx]
            target_name = BUTTON_NAMES.get(target_btn, f"Button {target_btn}")
            draw_doodle_text(self.screen, f"Press: {target_name}",
                              self.theme.body_font, ACCENT_RED,
                              (panel.centerx, panel.top + 95), anchor="center",
                              shadow=False)
        # Grid of rounded-cube tiles, one per ESP button.
        cols = 4
        rows = (len(BUTTON_CHECK_SEQUENCE) + cols - 1) // cols
        cell_w = (panel.width - 60) // cols
        cell_h = min(110, (panel.height - 180) // rows)
        grid_top = panel.top + 130
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
                ink = (255, 250, 240)
            elif current:
                pulse = 0.5 + 0.5 * math.sin(t * 5)
                fill = (int(BEIGE_PANEL_HI[0] - 30 * pulse),
                        int(BEIGE_PANEL_HI[1] - 30 * pulse),
                        int(BEIGE_PANEL_HI[2] - 50 * pulse))
                ink = INK
            else:
                fill = BEIGE_PANEL_HI
                ink = INK_SOFT
            draw_doodle_panel(self.screen, tile, fill=fill, radius=18,
                               seed=400 + btn)
            label = BUTTON_NAMES.get(btn, f"Button {btn}")
            txt = self.theme.small_font.render(label, True, ink)
            self.screen.blit(txt, txt.get_rect(center=tile.center))
            if done:
                check = self.theme.title_font.render("OK", True, (255, 250, 240))
                self.screen.blit(check,
                                  check.get_rect(midright=(tile.right - 12,
                                                            tile.top + 18)))

    def _draw_main_menu(self, t: float) -> None:
        w, h = self.screen.get_size()
        # Center logo.
        if self.game_logo:
            target_h = max(220, min(h // 2, 480))
            logo = scale_to_height(self.game_logo, target_h)
            self.screen.blit(logo, logo.get_rect(center=(w // 2, h // 2 - 30)))
        else:
            draw_doodle_text(self.screen, "LABCOIN MUSIC",
                              self.theme.huge_font, INK,
                              (w // 2, h // 2 - 30), anchor="center")
        # Bottom doodle banner.
        banner = pygame.Rect(0, 0, min(w - 120, 980), 120)
        banner.midbottom = (w // 2, h - 60)
        draw_doodle_panel(self.screen, banner, fill=BEIGE_PANEL_HI,
                           outline=INK, radius=28, seed=222)
        draw_doodle_text(self.screen, "To start the game,",
                          self.theme.title_font, INK,
                          (banner.centerx, banner.top + 38), anchor="center",
                          shadow=False)
        draw_doodle_text(self.screen, "press the number of players (1 - 10).",
                          self.theme.body_font, INK_SOFT,
                          (banner.centerx, banner.top + 84), anchor="center",
                          shadow=False)

    def _draw_round_select(self, t: float) -> None:
        w, h = self.screen.get_size()
        draw_doodle_text(self.screen,
                          f"{self.state.player_count} player"
                          + ("s" if self.state.player_count != 1 else "")
                          + " — let's play!",
                          self.theme.title_font, INK_SOFT,
                          (w // 2, h // 2 - 200), anchor="center")
        draw_doodle_text(self.screen, "How many rounds?",
                          self.theme.huge_font, ACCENT_RED,
                          (w // 2, h // 2 - 60), anchor="center")
        draw_doodle_text(self.screen, "Press a number on the remote (or your keyboard).",
                          self.theme.body_font, INK,
                          (w // 2, h // 2 + 80), anchor="center", shadow=False)
        # Doodle numpad sketch for visual reference.
        pad = pygame.Rect(0, 0, 360, 200)
        pad.center = (w // 2, h // 2 + 220)
        draw_doodle_panel(self.screen, pad, fill=BEIGE_PANEL_HI, radius=22, seed=311)
        for i, n in enumerate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]):
            row, col = divmod(i, 5)
            cx = pad.left + 36 + col * 64
            cy = pad.top + 56 + row * 80
            pygame.draw.circle(self.screen, BEIGE_PANEL, (cx, cy), 26)
            pygame.draw.circle(self.screen, INK, (cx, cy), 26, 2)
            label = self.theme.body_font.render(str(n if n < 10 else 0), True, INK)
            self.screen.blit(label, label.get_rect(center=(cx, cy)))

    def _draw_countdown(self, t: float) -> None:
        w, h = self.screen.get_size()
        elapsed = time.monotonic() - self.state.countdown_start
        remaining = max(0, 10 - int(elapsed))
        if remaining == 0:
            draw_doodle_text(self.screen, "GO!",
                              self.theme.huge_font, ACCENT_GREEN_D,
                              (w // 2, h // 2), anchor="center")
        else:
            # Pop animation: each new digit starts oversized and settles.
            scale = 1.0 + 0.4 * (1 - (elapsed - int(elapsed)))
            base = self.theme.huge_font.render(str(remaining), True, ACCENT_RED)
            target_w = max(1, int(base.get_width() * scale))
            target_h = max(1, int(base.get_height() * scale))
            big = pygame.transform.smoothscale(base, (target_w, target_h))
            self.screen.blit(big, big.get_rect(center=(w // 2, h // 2)))
        draw_doodle_text(self.screen,
                          f"{self.state.player_count} players  -  "
                          f"{self.state.round_count} rounds",
                          self.theme.body_font, INK,
                          (w // 2, h // 2 + 220), anchor="center", shadow=False)

    def _draw_playing(self, t: float) -> None:
        w, h = self.screen.get_size()
        draw_doodle_text(self.screen, "Game running",
                          self.theme.huge_font, ACCENT_GREEN_D,
                          (w // 2, h // 2 - 60), anchor="center")
        draw_doodle_text(self.screen,
                          f"{self.state.player_count} players  -  "
                          f"{self.state.round_count} rounds",
                          self.theme.title_font, INK,
                          (w // 2, h // 2 + 60), anchor="center", shadow=False)
        draw_doodle_text(self.screen, "(Round logic comes next — this is the wired-up shell.)",
                          self.theme.small_font, INK_SOFT,
                          (w // 2, h // 2 + 140), anchor="center", shadow=False)


def main() -> int:
    try:
        App().run()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
