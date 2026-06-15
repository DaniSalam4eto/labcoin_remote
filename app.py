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
import threading
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
    ACCENT_RED, ACCENT_YELLOW, GLASS_TINT, GLASS_TINT_DEEP,
    GLASS_TINT_SOFT, INK, INK_DIM, INK_SOFT,
    NoteFountain, PANEL_HI, PURPLE, STATUS_AMBER, STATUS_BLUE,
    STATUS_GREEN, STATUS_RED, Theme,
    build_note_palette, draw_action_hint, draw_background,
    draw_chunky_button, draw_crisp_label, draw_doodle_text,
    draw_glass_card, draw_pill_button,
    draw_remote_placeholder, draw_status_pill,
    invalidate_background_cache,
    load_image_alpha, make_main_menu_hint_fonts, scale_menu_logo,
    title_font_file,
)
from esp32_connector import Esp32Connector, Event, NUMPAD_BUTTONS
import strings_bg
import strings_en
import app_config
import autostart
from game_audio import (
    ClipPlayer,
    LibraryEmpty,
    SongPick,
    pick_random_song,
    pick_same_song_other_clip,
)

from bundle_paths import app_base_dir

ROOT = app_base_dir()
LOGOS = ROOT / "logos"


def _make_vr_varna_icon(size: int) -> Optional[pygame.Surface]:
    """Return the VR Varna window icon as a pygame surface.

    Loads ``logos/vr_varna.png`` if present; otherwise renders a clean
    programmatic mark (rounded dark badge with "VR" big + "VARNA" small in
    white) via Pillow at 2× and downsamples for sharp edges. The user can
    drop a real asset at ``logos/vr_varna.png`` to override it."""
    for name in ("vr_varna.png", "vrvarna.png", "VRVarna.png"):
        candidate = LOGOS / name
        if candidate.is_file():
            try:
                return pygame.image.load(str(candidate)).convert_alpha()
            except Exception:
                break
    try:
        from PIL import Image, ImageDraw, ImageFont  # type: ignore
    except Exception:
        return None
    ss = 2
    W = size * ss
    img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    radius = int(W * 0.22)
    draw.rounded_rectangle(
        (0, 0, W - 1, W - 1),
        radius=radius,
        fill=(16, 20, 30, 255),
    )
    # Tasteful thin white inner stroke so the badge has an edge.
    draw.rounded_rectangle(
        (1, 1, W - 2, W - 2),
        radius=radius,
        outline=(255, 255, 255, 90),
        width=max(1, ss),
    )
    # Try a clean sans-serif from Windows; fall back to PIL default.
    def _ttf(*names: str, px: int) -> Optional["ImageFont.FreeTypeFont"]:
        for n in names:
            try:
                return ImageFont.truetype(n, px)
            except Exception:
                continue
        return None
    big_font = _ttf("segoeuib.ttf", "seguisb.ttf", "arialbd.ttf",
                    "DejaVuSans-Bold.ttf", px=int(W * 0.42)) \
        or ImageFont.load_default()
    small_font = _ttf("segoeui.ttf", "calibri.ttf", "arial.ttf",
                      "DejaVuSans.ttf", px=int(W * 0.16)) \
        or ImageFont.load_default()
    # Big "VR" centered slightly above middle.
    vr_w, vr_h = draw.textbbox((0, 0), "VR", font=big_font)[2:]
    draw.text(
        ((W - vr_w) / 2, int(W * 0.16)),
        "VR",
        fill=(245, 247, 252, 255),
        font=big_font,
    )
    # Small "VARNA" beneath.
    var_w, var_h = draw.textbbox((0, 0), "VARNA", font=small_font)[2:]
    draw.text(
        ((W - var_w) / 2, int(W * 0.66)),
        "VARNA",
        fill=(170, 196, 230, 255),
        font=small_font,
    )
    img = img.resize((size, size), Image.LANCZOS)
    try:
        return pygame.image.frombytes(img.tobytes(), (size, size), "RGBA").convert_alpha()
    except Exception:
        return None


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

# Remote simultaneous hold heuristic (pulse refresh within this window ⇒ key "live").
REMOTE_PULSE_LIVENESS_S = 0.50
DUAL_CHECK_HOLD_NEED_S = 2.00
# Full-screen ranking after each round; host can skip early with Check / Enter.
LEADERBOARD_ANIM_S = 1.15
LEADERBOARD_ROW_STAGGER_S = 0.09
LEADERBOARD_AUTO_ADVANCE_S = 8.0
# After the second clip with nobody buzzing, the "round over" screen flows into
# the leaderboard on its own (host can still press Check to skip the wait).
WAIT_ADVANCE_AUTO_ADVANCE_S = 3.5
# When all rounds are done, the winner podium returns to the idle menu by itself.
WINNER_AUTO_RETURN_S = 12.0

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

# Numpad digit -> remote button index (inverse of NUMPAD_BUTTONS), so keyboard
# testing of the button check marks the same tile a remote press would.
DIGIT_TO_BUTTON = {digit: btn for btn, digit in NUMPAD_BUTTONS.items()}

# Remote: press check (button 1), then numpad 1 (button 9) within
# LANG_CHORD_WINDOW_S toggles UI language. Keyboard: hold ` (backtick) and
# press Numpad 1. Not active during the button-check screen.
LANG_TOGGLE_CHECK_BTN = 1
LANG_TOGGLE_NUMPAD1_BTN = 9
LANG_CHORD_WINDOW_S = 0.65
LANG_KEYBOARD_HOLD_KEYS = (pygame.K_BACKQUOTE,)


class Screen(Enum):
    SETUP = auto()
    LOADING = auto()
    BAND_5GHZ = auto()
    OUT_OF_RANGE = auto()
    SEARCHING = auto()
    WIFI_SETUP = auto()
    CONNECTED_OK = auto()
    BUTTON_CHECK = auto()
    MAIN_MENU = auto()
    ROUND_SELECT = auto()
    COUNTDOWN = auto()
    PLAYING = auto()


# Screens that are part of getting/keeping the link (vs. actually in the game).
CONNECTION_SCREENS = frozenset({
    Screen.SETUP, Screen.LOADING, Screen.BAND_5GHZ, Screen.OUT_OF_RANGE,
    Screen.SEARCHING, Screen.WIFI_SETUP, Screen.CONNECTED_OK, Screen.BUTTON_CHECK,
})

# If we haven't connected within this long, pop up the manual Wi-Fi entry form.
WIFI_PROMPT_AFTER_S = 30.0
GAME_SCREENS = frozenset({
    Screen.MAIN_MENU, Screen.ROUND_SELECT, Screen.COUNTDOWN, Screen.PLAYING,
})


class PlayingPhase(Enum):
    """Gameplay sub-state while :data:`Screen.PLAYING` is active."""

    CLIP_1 = auto()
    WAIT_REVEAL = auto()
    CLIP_2 = auto()
    WAIT_CONFIRM = auto()
    WAIT_ADVANCE = auto()
    LEADERBOARD = auto()


@dataclass
class AppState:
    screen: Screen = Screen.SETUP
    status_text: str = ""
    last_error: str = ""
    last_5ghz_ssid: str = ""
    button_check_idx: int = 0
    button_check_done: dict[int, bool] = field(default_factory=dict)
    player_count: int = 0
    round_count: int = 0
    countdown_start: float = 0.0
    last_countdown_label: str = ""  # last 3-2-1 glyph pushed to the remote OLED
    last_button_label: str = ""
    last_button_at: float = 0.0
    fullscreen: bool = False
    lang_check_armed_until: float = 0.0
    current_round: int = 0
    current_song: Optional[SongPick] = None
    round_started_at: float = 0.0
    play_error: str = ""
    recent_song_ids: list[str] = field(default_factory=list)
    rounds_finished: bool = False
    playing_phase: PlayingPhase = PlayingPhase.CLIP_1
    guessed_player: Optional[int] = None
    buzz_resume_phase: PlayingPhase = PlayingPhase.CLIP_1
    remote_btn_pulse_mono: dict[int, float] = field(default_factory=dict)
    dual_check_hold_accum_s: float = 0.0
    player_scores: list[int] = field(default_factory=lambda: [0] * 11)
    playback_ignore_until: float = 0.0
    leaderboard_started_at: float = 0.0
    wait_advance_started_at: float = 0.0  # entered the "round over" wait at this time
    rounds_finished_at: float = 0.0       # whole game finished at this time
    notice_text: str = ""           # transient top-center toast (autostart, etc.)
    notice_until: float = 0.0       # show the toast until this monotonic time
    search_attempts: int = 0        # failed reconnect attempts reported by the worker
    connect_started_at: float = 0.0  # when the current connect attempt sequence began
    wifi_prompt_shown: bool = False  # the manual Wi-Fi form was auto-shown already
    wifi_input_ssid: str = ""        # manual Wi-Fi entry: network name field
    wifi_input_password: str = ""    # manual Wi-Fi entry: password field
    wifi_input_field: int = 0        # which field is focused (0 = SSID, 1 = password)


class App:
    def __init__(self) -> None:
        # Pre-init the mixer for low-latency clip playback; init() honours it.
        try:
            pygame.mixer.pre_init(frequency=44100, size=-16, channels=2, buffer=512)
        except pygame.error:
            pass
        pygame.init()
        # Bulgarian is the default locale. Press Check + Numpad 1 on the
        # remote (or hold ` and tap Numpad 1 on the keyboard) to toggle to
        # English — see `_toggle_locale`.
        self.L = strings_bg
        # Window icon — drop the default pygame snake for the VR Varna mark.
        icon = _make_vr_varna_icon(64)
        if icon is not None:
            try:
                pygame.display.set_icon(icon)
            except pygame.error:
                pass
        pygame.display.set_caption(self.L.WINDOW_TITLE)
        self.screen = pygame.display.set_mode(WINDOW_SIZE, _WINDOW_FLAGS)
        self.clock = pygame.time.Clock()
        self.theme = Theme.make(rounded_display=self.L is strings_bg)
        self.state = AppState(status_text=self.L.STATUS_DEFAULT)
        self.connector = Esp32Connector()
        self.clip_player = ClipPlayer()

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
        # Clickable wait-phase action rows, repopulated each frame.
        self._wait_action_rects: list[tuple[pygame.Rect, str]] = []
        # Click target for the podium's back-to-menu button.
        self.winner_back_button_rect = pygame.Rect(0, 0, 0, 0)
        # Click targets for the manual Wi-Fi form (two fields + connect button).
        self.wifi_field_rects = [pygame.Rect(0, 0, 0, 0), pygame.Rect(0, 0, 0, 0)]
        self.wifi_connect_rect = pygame.Rect(0, 0, 0, 0)
        self._menu_logo_cache: tuple[tuple[int, int], pygame.Surface] | None = None

        # Persistent prefs (run-at-startup, first-setup-done).
        self.config = app_config.load()
        # First launch of the packaged app turns on run-at-startup by default
        # (the user disables it with Ctrl+O). Only the frozen .exe does this, and
        # only once, so we never re-enable it after they turn it off — and dev
        # runs never consume the "first run" flag meant for the .exe.
        # The extra `not is_enabled()` guard means that if the config write ever
        # failed but the registry entry persisted, we won't keep re-enabling
        # autostart on every launch (re-enabling after the user's Ctrl+O).
        if (getattr(sys, "frozen", False)
                and not self.config.get("autostart_initialized")
                and autostart.is_supported()
                and not autostart.is_enabled()):
            autostart.enable()
            self.config["autostart_initialized"] = True
            app_config.save(self.config)
        # Optional manual Wi-Fi creds (mainly for a headless Raspberry Pi where
        # the saved password can't be auto-read); blank = OS auto-detect.
        cfg_ssid = str(self.config.get("wifi_ssid") or "").strip()
        if cfg_ssid:
            self.connector.set_wifi_credentials(
                cfg_ssid, str(self.config.get("wifi_password") or ""))

        # Returning users (setup already done once) auto-connect on launch and
        # skip straight past the setup screens into the game.
        self._auto_connect_pending = bool(self.config.get("setup_completed"))

    # ------------------------------------------------------------------ helpers

    def _is_connection_screen(self, screen: "Screen | None" = None) -> bool:
        return (screen or self.state.screen) in CONNECTION_SCREENS

    def _is_game_screen(self, screen: "Screen | None" = None) -> bool:
        return (screen or self.state.screen) in GAME_SCREENS

    def _flash_notice(self, text: str, secs: float = 2.4) -> None:
        """Show a brief top-center toast (autostart toggles, etc.)."""
        self.state.notice_text = text
        self.state.notice_until = time.monotonic() + secs

    def _toggle_autostart(self) -> None:
        if not autostart.is_supported():
            self._flash_notice(self.L.AUTOSTART_UNAVAILABLE)
            return
        # The registry Run key is the source of truth, so just flip it.
        enabled = autostart.toggle()
        self._flash_notice(self.L.AUTOSTART_ON if enabled else self.L.AUTOSTART_OFF)

    def _mark_setup_completed(self) -> None:
        if not self.config.get("setup_completed"):
            self.config["setup_completed"] = True
            app_config.save(self.config)

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

    def _lang_toggle_allowed_screen(self) -> bool:
        return self.state.screen not in (Screen.BUTTON_CHECK, Screen.PLAYING)

    def _toggle_locale(self) -> None:
        self.L = strings_bg if self.L is strings_en else strings_en
        pygame.display.set_caption(self.L.WINDOW_TITLE)
        self.theme = Theme.make(rounded_display=self.L is strings_bg)
        self.state.lang_check_armed_until = 0.0

    def _keyboard_lang_hold_active(self) -> bool:
        return any(pygame.key.get_pressed()[k] for k in LANG_KEYBOARD_HOLD_KEYS)

    def _try_keyboard_lang_toggle(self, event: pygame.event.Event) -> bool:
        if not self._lang_toggle_allowed_screen():
            return False
        if event.key != pygame.K_KP1:
            return False
        if not self._keyboard_lang_hold_active():
            return False
        self._toggle_locale()
        return True

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
        prev = self.state.screen
        self.state.screen = screen
        if status is not None:
            self.state.status_text = status
        if screen == Screen.MAIN_MENU and prev != Screen.MAIN_MENU:
            # Back at the menu means no game is playing — send the remote to its
            # idle logo rather than leaving a stale song / leaderboard up.
            self.connector.send_idle()

    def _all_button_check_tiles_pressed(self) -> bool:
        st = self.state
        return all(st.button_check_done.get(btn, False) for btn in BUTTON_CHECK_SEQUENCE)

    def _button_check_can_continue(self) -> bool:
        """True only once every pad has actually been pressed (no skipping)."""
        st = self.state
        if st.screen != Screen.BUTTON_CHECK:
            return False
        return self._all_button_check_tiles_pressed()

    def _advance_button_check_highlight(self) -> None:
        """Move the highlight to the first tile that hasn't been pressed yet."""
        st = self.state
        while (st.button_check_idx < len(BUTTON_CHECK_SEQUENCE)
               and st.button_check_done.get(
                   BUTTON_CHECK_SEQUENCE[st.button_check_idx], False)):
            st.button_check_idx += 1

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
        invalidate_background_cache()
        self._refresh_fountain_areas()

    def go_windowed(self) -> None:
        if not self.state.fullscreen:
            return
        self.screen = pygame.display.set_mode(WINDOW_SIZE, _WINDOW_FLAGS)
        self.state.fullscreen = False
        self._menu_logo_cache = None
        invalidate_background_cache()
        self._refresh_fountain_areas()

    # ------------------------------------------------------------------ events

    def handle_connector_events(self) -> None:
        for ev in self.connector.poll_events():
            self._handle_event(ev)

    def _handle_event(self, ev: Event) -> None:
        st = self.state
        if ev.kind == "status":
            # SEARCHING keeps its dedicated "Searching for remote" line; the
            # other connection screens show live worker progress.
            if st.screen in (Screen.LOADING, Screen.OUT_OF_RANGE, Screen.BAND_5GHZ):
                st.status_text = self.L.translate_worker_status(ev.text)
        elif ev.kind == "error":
            if ev.text.startswith("NET5GHZ:"):
                _, ssid, _ = (ev.text.split(":", 2) + ["", ""])[:3]
                st.last_5ghz_ssid = ssid
                # Needs a human to switch Wi-Fi band; don't yank an active game.
                if not self._is_game_screen():
                    self.set_screen(Screen.BAND_5GHZ, status=self.L.STATUS_5GHZ)
            elif ev.text == "OUTOFRANGE":
                # The worker auto-retries; just keep a "looking" screen up while
                # we're in the connection flow (and not already searching). This
                # only fires when the Wi-Fi band is fine, so it also clears a
                # stale 5 GHz warning once the user has switched bands.
                if self._is_connection_screen() and st.screen not in (
                        Screen.SEARCHING, Screen.SETUP, Screen.WIFI_SETUP):
                    self.set_screen(Screen.LOADING, status=self.L.STATUS_OOR)
            else:
                st.last_error = ev.text
                # A mid-setup link error falls back to the connecting screen.
                if st.screen in (Screen.CONNECTED_OK, Screen.BUTTON_CHECK):
                    self.set_screen(
                        Screen.LOADING,
                        status=self.L.STATUS_LOST_LINK.format(
                            err=self.L.translate_connection_error(ev.text)))
        elif ev.kind == "searching":
            try:
                st.search_attempts = int(ev.text)
            except (ValueError, TypeError):
                st.search_attempts = 0
            # Show the dedicated search screen, but never interrupt a live game,
            # the Wi-Fi-band warning, or the manual Wi-Fi entry form.
            if self._is_connection_screen() and st.screen not in (
                    Screen.BAND_5GHZ, Screen.WIFI_SETUP):
                self.set_screen(Screen.SEARCHING, status=self.L.STATUS_SEARCHING)
        elif ev.kind == "connected":
            self._on_connected(ev)
        elif ev.kind == "disconnected":
            self._on_disconnected()
        elif ev.kind == "button":
            self._on_button(ev)
        # "volume" events are ignored on purpose: audio is fixed at 100%.

    def _on_connected(self, ev: Event) -> None:
        st = self.state
        # Reconnected mid-game: re-sync whatever the OLED should show, keep playing.
        if self._is_game_screen():
            self._resync_remote_display()
            return
        if self.config.get("setup_completed"):
            # Returning user: skip the button check, go straight into the game.
            self.go_fullscreen()
            self.set_screen(Screen.MAIN_MENU, status="")
        else:
            self.set_screen(Screen.CONNECTED_OK,
                            status=self.L.STATUS_CONNECTED.format(addr=ev.text))

    def _resync_remote_display(self) -> None:
        """Re-push whatever the OLED should be showing for the current game
        state, so a mid-game reconnect restores the remote display instead of
        leaving it stale until the next transition."""
        st = self.state
        if st.screen in (Screen.MAIN_MENU, Screen.ROUND_SELECT):
            self.connector.send_idle()
        elif st.screen == Screen.COUNTDOWN:
            if st.last_countdown_label:
                self.connector.send_countdown(st.last_countdown_label)
            else:
                self.connector.send_idle()
        elif st.screen == Screen.PLAYING:
            if st.rounds_finished or st.playing_phase == PlayingPhase.LEADERBOARD:
                self._push_leaderboard_remote()
            elif st.current_song is not None and not st.play_error:
                self.connector.send_song(st.current_song.artist,
                                          st.current_song.title)
            else:
                self.connector.send_idle()

    def _on_disconnected(self) -> None:
        st = self.state
        # In a live game we keep going; the worker reconnects in the background.
        if self._is_game_screen():
            return
        # On a connection screen, reflect "reconnecting" (the worker keeps
        # trying; the search screen takes over after enough failures). Leave the
        # manual Wi-Fi form up if the user is typing into it.
        if st.screen not in (Screen.SETUP, Screen.BAND_5GHZ, Screen.SEARCHING,
                             Screen.WIFI_SETUP):
            self.set_screen(Screen.LOADING, status=self.L.STATUS_DISCONNECTED)

    def _on_button(self, ev: Event) -> None:
        st = self.state
        if self._lang_toggle_allowed_screen():
            if ev.button == LANG_TOGGLE_CHECK_BTN:
                st.lang_check_armed_until = time.monotonic() + LANG_CHORD_WINDOW_S
            elif (
                ev.button == LANG_TOGGLE_NUMPAD1_BTN
                and ev.digit == 1
                and time.monotonic() < st.lang_check_armed_until
            ):
                self._toggle_locale()
                return
        if ev.button is not None:
            st.last_button_label = self.L.BUTTON_NAMES.get(
                ev.button, self.L.FB_FALLBACK_BUTTON.format(n=ev.button))
        else:
            st.last_button_label = ev.text
        st.last_button_at = time.monotonic()

        # Same as Space / clicking the main chunky button — remote-only path.
        if self._remote_activate_primary(ev):
            return

        if st.screen == Screen.BUTTON_CHECK:
            if ev.button is None:
                return
            if self._all_button_check_tiles_pressed():
                # Every tile verified: any remote button continues.
                self._finish_button_check()
                return
            # Only the button actually pressed marks its own tile, so you can't
            # skip ahead by mashing one button. Unmapped buttons are ignored.
            if (ev.button in BUTTON_CHECK_SEQUENCE
                    and not st.button_check_done.get(ev.button, False)):
                st.button_check_done[ev.button] = True
                self._advance_button_check_highlight()
            return

        if st.screen == Screen.MAIN_MENU and ev.digit is not None:
            self._pick_player_count(ev.digit)
        elif st.screen == Screen.ROUND_SELECT and ev.digit is not None:
            self._pick_round_count(ev.digit)
        elif st.screen == Screen.PLAYING:
            mono = time.monotonic()
            if ev.button is not None:
                st.remote_btn_pulse_mono[ev.button] = mono
            if st.rounds_finished:
                if ev.button == LANG_TOGGLE_CHECK_BTN:
                    self._end_game_and_return_to_menu()
                return
            if ev.digit is not None:
                # During the buzz pause a digit re-picks who gets the points;
                # otherwise it registers a fresh buzz-in.
                if st.playing_phase == PlayingPhase.WAIT_CONFIRM:
                    self._reselect_guess(ev.digit)
                else:
                    self._register_guess(ev.digit)
                return
            if ev.button == LANG_TOGGLE_CHECK_BTN:
                ph = st.playing_phase
                if ph == PlayingPhase.WAIT_REVEAL:
                    self._play_second_clip()
                elif ph == PlayingPhase.WAIT_CONFIRM:
                    self._confirm_buzz_scoring(1)
                elif ph == PlayingPhase.WAIT_ADVANCE:
                    self._finalize_round_go_next()
                elif ph == PlayingPhase.LEADERBOARD:
                    self._dismiss_leaderboard_and_next_round()
                return
            if ev.button == 2 and st.playing_phase == PlayingPhase.WAIT_CONFIRM:
                self._confirm_buzz_scoring(2)

    def _remote_activate_primary(self, ev: Event) -> bool:
        """Handle screens whose main control is Start / Reload / Continue.

        Any remote key counts except the language-chord arming key (checkmark),
        so chord stays: checkmark then numpad 1 within the window.
        """
        if ev.button is None:
            return False
        st = self.state
        if (
            self._lang_toggle_allowed_screen()
            and ev.button == LANG_TOGGLE_CHECK_BTN
        ):
            return False
        if st.screen == Screen.SETUP:
            self._start_connection()
            return True
        if st.screen in (Screen.BAND_5GHZ, Screen.OUT_OF_RANGE, Screen.SEARCHING):
            self._reload()
            return True
        if st.screen == Screen.CONNECTED_OK:
            self._begin_button_check()
            return True
        return False

    def _finish_button_check(self) -> None:
        # First completed setup: remember it so future launches auto-connect and
        # skip straight here.
        self._mark_setup_completed()
        self.go_fullscreen()
        self.set_screen(Screen.MAIN_MENU, status="")

    def _pick_player_count(self, n: int) -> None:
        self.state.player_count = n
        self.state.player_scores = [0] * 11
        self.set_screen(Screen.ROUND_SELECT,
                        status=self.L.STATUS_ROUNDS)

    def _pick_round_count(self, n: int) -> None:
        self.state.round_count = n
        self.state.current_round = 0
        self.state.current_song = None
        self.state.recent_song_ids = []
        self.state.rounds_finished = False
        self.state.play_error = ""
        self.state.playing_phase = PlayingPhase.CLIP_1
        self.state.guessed_player = None
        self.state.remote_btn_pulse_mono.clear()
        self.state.dual_check_hold_accum_s = 0.0
        self.state.player_scores = [0] * 11
        self.state.countdown_start = time.monotonic()
        self.state.last_countdown_label = ""
        self.set_screen(Screen.COUNTDOWN, status="")

    # ------------------------------------------------------------ game helpers

    def _playing_guess_allowed(self) -> bool:
        st = self.state
        if st.screen != Screen.PLAYING or st.rounds_finished or st.play_error:
            return False
        # Also allow buzzing during the pause after clip 1 (WAIT_REVEAL), so a
        # number can be picked for the player who answered there too.
        return st.playing_phase in (
            PlayingPhase.CLIP_1, PlayingPhase.CLIP_2, PlayingPhase.WAIT_REVEAL,
        )

    def _register_guess(self, digit: int) -> None:
        st = self.state
        if not self._playing_guess_allowed():
            return
        if digit < 1 or digit > st.player_count:
            return
        if st.guessed_player is not None:
            return
        st.guessed_player = digit
        st.buzz_resume_phase = st.playing_phase
        self.clip_player.buzz_pause()
        st.playing_phase = PlayingPhase.WAIT_CONFIRM
        st.dual_check_hold_accum_s = 0.0
        st.status_text = self.L.PLAYING_HINT_WAIT_CONFIRM

    def _reselect_guess(self, digit: int) -> None:
        """While paused for a buzz, change which player the points go to.

        Lets the host correct who actually answered without resuming the clip;
        the +1 / +2 buttons then award that player.
        """
        st = self.state
        if st.screen != Screen.PLAYING or st.playing_phase != PlayingPhase.WAIT_CONFIRM:
            return
        if digit < 1 or digit > st.player_count:
            return
        st.guessed_player = digit
        st.status_text = self.L.PLAYING_HINT_WAIT_CONFIRM

    def _leaderboard_ranked_pairs(self) -> list[tuple[int, int]]:
        pc = self.state.player_count
        pairs = [(p, self.state.player_scores[p]) for p in range(1, max(1, pc + 1))]
        pairs.sort(key=lambda x: (-x[1], x[0]))
        return pairs

    def _push_leaderboard_remote(self) -> None:
        """Push the current top-3 to the remote's OLED leaderboard screen."""
        if self.state.player_count <= 0:
            return
        pairs = self._leaderboard_ranked_pairs()  # already sorted best-first
        rows = [(f"P{player}", score) for player, score in pairs[:3]]
        self.connector.send_top3(rows)

    def _finalize_round_go_next(self) -> None:
        self._push_leaderboard_remote()
        st = self.state
        st.playing_phase = PlayingPhase.LEADERBOARD
        st.leaderboard_started_at = time.monotonic()
        st.status_text = self.L.PLAYING_LEADERBOARD_HINT

    def _dismiss_leaderboard_and_next_round(self) -> None:
        if self.state.playing_phase != PlayingPhase.LEADERBOARD:
            return
        self._start_next_round()

    def _apply_clip_pick(self, pick: SongPick) -> None:
        st = self.state
        st.current_song = pick

        ok = self.clip_player.play(pick.clip_path)
        if not ok:
            st.play_error = self.L.PLAYING_AUDIO_ERROR
            st.playback_ignore_until = 0.0
        else:
            st.play_error = ""
            st.playback_ignore_until = time.monotonic() + 0.22

        # Drive the OLED countdown with the clip's real length so the panel
        # stays up for exactly as long as the song plays (0 if playback failed).
        hold_ms = int(self.clip_player.current_length_s() * 1000) if ok else 0
        pushed = self.connector.send_song(pick.artist, pick.title, hold_ms=hold_ms)
        if pushed:
            st.status_text = self.L.PLAYING_STATUS
        else:
            st.status_text = self.L.PLAYING_REMOTE_OFFLINE

    def _play_second_clip(self) -> None:
        st = self.state
        song = st.current_song
        if song is None:
            self._enter_wait_advance()
            return
        try:
            clip_index, path = pick_same_song_other_clip(song.song_id, song.clip_index)
        except LibraryEmpty:
            self.clip_player.stop()
            self._enter_wait_advance()
            return

        pick = SongPick(
            song_id=song.song_id,
            artist=song.artist,
            title=song.title,
            origin=song.origin,
            clip_index=clip_index,
            clip_path=path,
        )
        st.playing_phase = PlayingPhase.CLIP_2
        self._apply_clip_pick(pick)
        hint = "" if st.play_error else self.L.PLAYING_HINT_CLIP2
        if hint:
            st.status_text = hint

    def _playback_check_pressed(self) -> None:
        st = self.state
        ph = st.playing_phase
        if ph == PlayingPhase.WAIT_REVEAL:
            self._play_second_clip()
        elif ph == PlayingPhase.WAIT_CONFIRM:
            self._confirm_buzz_scoring(1)
        elif ph == PlayingPhase.WAIT_ADVANCE:
            self._finalize_round_go_next()
        elif ph == PlayingPhase.LEADERBOARD:
            self._dismiss_leaderboard_and_next_round()

    def _confirm_buzz_scoring(self, points: int) -> None:
        st = self.state
        gp = st.guessed_player
        st.dual_check_hold_accum_s = 0.0
        if gp is not None and 1 <= gp < len(st.player_scores):
            st.player_scores[gp] += max(0, points)
        st.guessed_player = None
        self.clip_player.stop()
        self._finalize_round_go_next()

    def _void_buzz_false_alarm(self) -> None:
        """Host holds Check + Double check ~2 s — mistaken buzz; resume playback."""

        st = self.state
        st.dual_check_hold_accum_s = 0.0
        st.guessed_player = None
        rp = st.buzz_resume_phase
        self.clip_player.undo_buzz_pause()
        # If the buzz happened during the WAIT_REVEAL pause (between clips),
        # there is no audio to resume — return to that pause and restore its hint
        # (otherwise the stale "buzz-in" confirm text lingers).
        if rp == PlayingPhase.WAIT_REVEAL:
            st.playing_phase = PlayingPhase.WAIT_REVEAL
            st.status_text = " ".join([
                self.L.PLAYING_HINT_WAIT_REVEAL,
                self.L.PLAYING_HINT_GUESS.format(n=st.player_count),
            ])
            return
        if rp not in (PlayingPhase.CLIP_1, PlayingPhase.CLIP_2):
            return
        st.playing_phase = rp
        song = st.current_song
        if song is None:
            return
        pushed = self.connector.send_song(song.artist, song.title)
        if pushed:
            st.status_text = (
                self.L.PLAYING_HINT_CLIP2
                if rp == PlayingPhase.CLIP_2
                else self.L.PLAYING_STATUS
            )
        else:
            st.status_text = self.L.PLAYING_REMOTE_OFFLINE

    def _enter_wait_advance(self) -> None:
        """Enter the post-round 'round over' wait and stamp it, so `_update` can
        flow it into the leaderboard automatically."""
        st = self.state
        st.playing_phase = PlayingPhase.WAIT_ADVANCE
        st.wait_advance_started_at = time.monotonic()
        st.status_text = self.L.PLAYING_HINT_WAIT_ADVANCE

    def _advance_after_clip_finished(self) -> None:
        st = self.state
        ph = st.playing_phase
        if ph == PlayingPhase.CLIP_1:
            self.clip_player.stop()
            st.playing_phase = PlayingPhase.WAIT_REVEAL
            mix = []
            guess = self.L.PLAYING_HINT_GUESS.format(n=st.player_count)
            mix.append(self.L.PLAYING_HINT_WAIT_REVEAL)
            mix.append(guess)
            st.status_text = " ".join(mix)
        elif ph == PlayingPhase.CLIP_2:
            self.clip_player.stop()
            self._enter_wait_advance()

    def _playing_dual_check_hold(self, dt: float) -> None:
        """Hosts must hold physical Check + Double-check together (~2 s) to undo a buzz.

        Firmware should emit repeated pulses while switches are depressed; pulses
        are treated as alive for :data:`REMOTE_PULSE_LIVENESS_S`.
        On PC testing, use ``[`` and ``]``.
        """

        st = self.state
        if st.screen != Screen.PLAYING or st.playing_phase != PlayingPhase.WAIT_CONFIRM:
            return
        now = time.monotonic()
        liveness = REMOTE_PULSE_LIVENESS_S
        pulse1 = (now - st.remote_btn_pulse_mono.get(1, -1e9)) <= liveness
        pulse2 = (now - st.remote_btn_pulse_mono.get(2, -1e9)) <= liveness
        if pulse1 and pulse2:
            st.dual_check_hold_accum_s += dt
            if st.dual_check_hold_accum_s >= DUAL_CHECK_HOLD_NEED_S:
                self._void_buzz_false_alarm()
        else:
            st.dual_check_hold_accum_s = 0.0

    def _playing_pulse_brackets_keys(self) -> None:
        """Treat ``[` and ``]`` as simultaneous Check / Double-check for local testing."""

        st = self.state
        if st.screen != Screen.PLAYING or st.playing_phase != PlayingPhase.WAIT_CONFIRM:
            return
        keys = pygame.key.get_pressed()
        now = time.monotonic()
        if keys[pygame.K_LEFTBRACKET]:
            st.remote_btn_pulse_mono[1] = now
        if keys[pygame.K_RIGHTBRACKET]:
            st.remote_btn_pulse_mono[2] = now

    def _playing_poll_clip_end(self) -> None:
        st = self.state
        if st.screen != Screen.PLAYING:
            return
        if st.rounds_finished or st.play_error:
            return
        if time.monotonic() < st.playback_ignore_until:
            return
        if self.clip_player.buzz_paused():
            return
        if self.clip_player.is_playing():
            return
        ph = st.playing_phase
        if ph == PlayingPhase.CLIP_1 and st.current_song is not None:
            self._advance_after_clip_finished()
        elif ph == PlayingPhase.CLIP_2:
            self._advance_after_clip_finished()

    # ------------------------------------------------------------ game loop

    def _start_next_round(self) -> None:
        """Advance to another round entry: clip 1 of a freshly picked song."""
        st = self.state
        if st.current_round >= st.round_count and st.round_count > 0:
            st.rounds_finished = True
            st.rounds_finished_at = time.monotonic()
            self.clip_player.stop()
            st.current_song = None
            st.status_text = self.L.PLAYING_FINISHED
            return

        try:
            pick = pick_random_song(
                exclude_song_ids=tuple(st.recent_song_ids),
            )
        except LibraryEmpty:
            st.current_song = None
            st.play_error = self.L.PLAYING_NO_LIBRARY
            st.status_text = self.L.PLAYING_NO_LIBRARY
            st.playing_phase = PlayingPhase.CLIP_1
            return

        st.round_started_at = time.monotonic()
        st.current_round = max(1, st.current_round + 1)
        st.recent_song_ids.append(pick.song_id)
        if len(st.recent_song_ids) > 24:
            del st.recent_song_ids[: len(st.recent_song_ids) - 24]

        st.guessed_player = None
        st.remote_btn_pulse_mono.clear()
        st.dual_check_hold_accum_s = 0.0
        st.playing_phase = PlayingPhase.CLIP_1
        self._apply_clip_pick(pick)

    def _end_game_and_return_to_menu(self) -> None:
        self.clip_player.stop()
        self.state.current_song = None
        self.state.current_round = 0
        self.state.rounds_finished = False
        self.state.play_error = ""
        self.state.playing_phase = PlayingPhase.CLIP_1
        self.state.guessed_player = None
        self.state.remote_btn_pulse_mono.clear()
        self.state.dual_check_hold_accum_s = 0.0
        self.set_screen(Screen.MAIN_MENU, status="")

    # ------------------------------------------------------------------ frame

    def run(self) -> None:
        # Returning user: start connecting immediately, no SETUP screen.
        if self._auto_connect_pending:
            self._auto_connect_pending = False
            self._start_connection()
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
                    invalidate_background_cache()
                    self._refresh_fountain_areas()
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        # On the Wi-Fi form, Esc just backs out (don't quit the
                        # app over a mistyped password).
                        if self.state.screen == Screen.WIFI_SETUP:
                            self.set_screen(Screen.LOADING,
                                            status=self.L.STATUS_RETRYING)
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
        self.clip_player.close()
        pygame.quit()

    def _handle_keydown(self, event: pygame.event.Event) -> None:
        st = self.state
        # Ctrl+O toggles run-at-startup, anywhere.
        if event.key == pygame.K_o and (pygame.key.get_mods() & pygame.KMOD_CTRL):
            self._toggle_autostart()
            return
        # On the manual Wi-Fi form, every key is text entry (handled first so it
        # never triggers game/lang shortcuts).
        if st.screen == Screen.WIFI_SETUP:
            self._wifi_setup_keydown(event)
            return
        if self._try_keyboard_lang_toggle(event):
            return
        if event.key == pygame.K_RETURN or event.key == pygame.K_SPACE:
            if st.screen == Screen.SETUP:
                self._start_connection()
            elif st.screen in (Screen.BAND_5GHZ, Screen.OUT_OF_RANGE, Screen.SEARCHING):
                self._reload()
            elif st.screen == Screen.CONNECTED_OK:
                self._begin_button_check()
            elif st.screen == Screen.BUTTON_CHECK and self._button_check_can_continue():
                self._finish_button_check()
            elif st.screen == Screen.PLAYING:
                if st.rounds_finished:
                    self._end_game_and_return_to_menu()
                elif not st.play_error:
                    self._playback_check_pressed()
        elif event.key == pygame.K_F1 and st.screen == Screen.BUTTON_CHECK:
            # Dev shortcut: skip button check.
            self._finish_button_check()
        elif event.key == pygame.K_BACKSPACE and st.screen == Screen.PLAYING:
            self._end_game_and_return_to_menu()
        elif (
            event.key == pygame.K_F2
            and st.screen == Screen.PLAYING
            and st.playing_phase == PlayingPhase.WAIT_CONFIRM
            and not st.rounds_finished
        ):
            self._confirm_buzz_scoring(2)
        elif event.key in KEY_DIGIT_MAP:
            digit = KEY_DIGIT_MAP[event.key]
            if st.screen == Screen.MAIN_MENU:
                self._pick_player_count(digit)
            elif st.screen == Screen.ROUND_SELECT:
                self._pick_round_count(digit)
            elif st.screen == Screen.PLAYING:
                if not st.rounds_finished:
                    if st.playing_phase == PlayingPhase.WAIT_CONFIRM:
                        self._reselect_guess(digit)
                    else:
                        self._register_guess(digit)
            elif st.screen == Screen.BUTTON_CHECK:
                if self._all_button_check_tiles_pressed():
                    self._finish_button_check()
                    return
                # Strict, like the remote: a number marks only its own tile.
                btn = DIGIT_TO_BUTTON.get(digit)
                if (btn is not None and btn in BUTTON_CHECK_SEQUENCE
                        and not st.button_check_done.get(btn, False)):
                    st.button_check_done[btn] = True
                    self._advance_button_check_highlight()

    def _handle_click(self, pos: tuple[int, int]) -> None:
        st = self.state
        if st.screen == Screen.WIFI_SETUP:
            if self.wifi_connect_rect.collidepoint(pos):
                self._submit_wifi_form()
                return
            for i, rect in enumerate(self.wifi_field_rects):
                if rect.collidepoint(pos):
                    st.wifi_input_field = i
                    return
            return
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
        elif st.screen == Screen.PLAYING:
            # Winner-screen "Back to menu" button.
            if (st.rounds_finished
                    and self.winner_back_button_rect.width > 0
                    and self.winner_back_button_rect.collidepoint(pos)):
                self._end_game_and_return_to_menu()
                return
            # Clickable rows in the wait-phase action panel.
            for rect, action_id in self._wait_action_rects:
                if rect.collidepoint(pos):
                    self._dispatch_wait_action(action_id)
                    return

    def _dispatch_wait_action(self, action_id: str) -> None:
        """Run the host action attached to a wait-panel button click."""
        st = self.state
        if st.play_error or st.rounds_finished:
            return
        if action_id == "replay_clip2" \
                and st.playing_phase == PlayingPhase.WAIT_REVEAL:
            self._play_second_clip()
        elif action_id == "confirm1" \
                and st.playing_phase == PlayingPhase.WAIT_CONFIRM:
            self._confirm_buzz_scoring(1)
        elif action_id == "confirm2" \
                and st.playing_phase == PlayingPhase.WAIT_CONFIRM:
            self._confirm_buzz_scoring(2)
        elif action_id == "cancel_buzz" \
                and st.playing_phase == PlayingPhase.WAIT_CONFIRM:
            self._void_buzz_false_alarm()
        elif action_id == "open_scoreboard" \
                and st.playing_phase == PlayingPhase.WAIT_ADVANCE:
            self._finalize_round_go_next()
        elif action_id.startswith("buzz_player_"):
            # On-screen buzz-in — host clicks a player number to register
            # the buzz, same as that player tapping the physical numpad.
            try:
                digit = int(action_id[len("buzz_player_"):])
            except ValueError:
                return
            self._register_onscreen_buzz(digit)

    def _register_onscreen_buzz(self, digit: int) -> None:
        """Click-driven buzz. Mirrors :meth:`_register_guess` but is allowed
        during the WAIT_REVEAL pause too (since that's the only time the
        numpad is visible on-screen)."""
        st = self.state
        if st.screen != Screen.PLAYING or st.rounds_finished or st.play_error:
            return
        if digit < 1 or digit > st.player_count:
            return
        # Already paused for a buzz: clicking a player just re-picks who scores.
        if st.playing_phase == PlayingPhase.WAIT_CONFIRM:
            st.guessed_player = digit
            return
        if st.playing_phase not in (
            PlayingPhase.CLIP_1, PlayingPhase.CLIP_2, PlayingPhase.WAIT_REVEAL,
        ):
            return
        if st.guessed_player is not None:
            return
        st.guessed_player = digit
        st.buzz_resume_phase = st.playing_phase
        self.clip_player.buzz_pause()
        st.playing_phase = PlayingPhase.WAIT_CONFIRM
        st.dual_check_hold_accum_s = 0.0
        st.status_text = self.L.PLAYING_HINT_WAIT_CONFIRM

    def _start_connection(self) -> None:
        self.state.connect_started_at = time.monotonic()
        self.state.wifi_prompt_shown = False
        self.set_screen(Screen.LOADING,
                        status=self.L.STATUS_SEARCHING_BLE)
        self.connector.start()

    def _reload(self) -> None:
        self.set_screen(Screen.LOADING, status=self.L.STATUS_RETRYING)
        self.connector.request_immediate_reconnect()

    def _begin_button_check(self) -> None:
        self.state.button_check_idx = 0
        self.state.button_check_done = {}
        self.set_screen(Screen.BUTTON_CHECK,
                        status=self.L.STATUS_BUTTON_CHECK)

    # ------------------------------------------------------------------ update

    def _maybe_prompt_wifi(self) -> None:
        """If we still haven't connected after WIFI_PROMPT_AFTER_S, pop up the
        manual Wi-Fi entry form (the saved password often can't be read on a
        headless Pi, so let the user type it in)."""
        st = self.state
        if st.wifi_prompt_shown:
            return
        if st.screen not in (Screen.LOADING, Screen.SEARCHING, Screen.OUT_OF_RANGE):
            return
        if time.monotonic() - st.connect_started_at < WIFI_PROMPT_AFTER_S:
            return
        st.wifi_input_ssid = str(self.config.get("wifi_ssid") or "")
        st.wifi_input_password = str(self.config.get("wifi_password") or "")
        st.wifi_input_field = 0
        st.wifi_prompt_shown = True
        self.set_screen(Screen.WIFI_SETUP, status="")

    def _submit_wifi_form(self) -> None:
        """Use the typed Wi-Fi creds: hand them to the worker (sent to the remote
        over Bluetooth), persist them, and retry the connection now."""
        st = self.state
        ssid = st.wifi_input_ssid.strip()
        if not ssid:
            self._flash_notice(self.L.WIFI_NEED_SSID)
            return
        password = st.wifi_input_password
        self.connector.set_wifi_credentials(ssid, password)
        self.config["wifi_ssid"] = ssid
        self.config["wifi_password"] = password
        app_config.save(self.config)
        # Give the new creds a fresh window; re-show the form if they're wrong.
        st.connect_started_at = time.monotonic()
        st.wifi_prompt_shown = False
        self._flash_notice(self.L.WIFI_SAVED)
        self.set_screen(Screen.LOADING, status=self.L.STATUS_RETRYING)
        self.connector.request_immediate_reconnect()

    def _wifi_setup_keydown(self, event: pygame.event.Event) -> None:
        st = self.state
        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self._submit_wifi_form()
        elif event.key == pygame.K_TAB:
            st.wifi_input_field = 1 - st.wifi_input_field
        elif event.key in (pygame.K_UP, pygame.K_DOWN):
            st.wifi_input_field = 1 - st.wifi_input_field
        elif event.key == pygame.K_BACKSPACE:
            if st.wifi_input_field == 0:
                st.wifi_input_ssid = st.wifi_input_ssid[:-1]
            else:
                st.wifi_input_password = st.wifi_input_password[:-1]
        else:
            ch = event.unicode
            # Printable, no field/line separators (they'd break the BLE payload).
            if ch and ch.isprintable() and ch not in "|\r\n":
                if st.wifi_input_field == 0 and len(st.wifi_input_ssid) < 64:
                    st.wifi_input_ssid += ch
                elif st.wifi_input_field == 1 and len(st.wifi_input_password) < 64:
                    st.wifi_input_password += ch

    def _update(self, dt: float, t: float) -> None:
        st = self.state
        self._maybe_prompt_wifi()
        if st.screen == Screen.COUNTDOWN:
            elapsed = time.monotonic() - st.countdown_start
            # Mirror the on-screen number onto the remote OLED as it ticks. Use
            # an ASCII "GO!" (the OLED font has no Cyrillic) for the final beat.
            remaining = max(0, 10 - int(elapsed))
            oled_label = "GO!" if remaining == 0 else str(remaining)
            if oled_label != st.last_countdown_label:
                st.last_countdown_label = oled_label
                self.connector.send_countdown(oled_label)
            if elapsed >= 11:
                self.set_screen(Screen.PLAYING,
                                status=self.L.PLAYING_STATUS)
                self._start_next_round()
        elif st.screen == Screen.PLAYING:
            self._playing_dual_check_hold(dt)
            self._playing_pulse_brackets_keys()
            now = time.monotonic()
            # Whole game over: the podium returns to the idle menu on its own.
            if st.rounds_finished:
                if now - st.rounds_finished_at >= WINNER_AUTO_RETURN_S:
                    self._end_game_and_return_to_menu()
            # Round over with nobody buzzing: flow into the leaderboard by itself.
            elif st.playing_phase == PlayingPhase.WAIT_ADVANCE:
                if now - st.wait_advance_started_at >= WAIT_ADVANCE_AUTO_ADVANCE_S:
                    self._finalize_round_go_next()
            # Leaderboard shown: auto-start the next round.
            elif st.playing_phase == PlayingPhase.LEADERBOARD:
                if now - st.leaderboard_started_at >= LEADERBOARD_AUTO_ADVANCE_S:
                    self._dismiss_leaderboard_and_next_round()
            self._playing_poll_clip_end()

    # ------------------------------------------------------------------ draw

    def _draw(self, t: float) -> None:
        # Pure background — no notes, no starfield. Atmospheric color blobs
        # are baked into the cached background surface.
        draw_background(self.screen)

        st = self.state
        draw_fn = {
            Screen.SETUP: self._draw_setup,
            Screen.LOADING: self._draw_loading,
            Screen.BAND_5GHZ: self._draw_band_5ghz,
            Screen.OUT_OF_RANGE: self._draw_out_of_range,
            Screen.SEARCHING: self._draw_searching,
            Screen.WIFI_SETUP: self._draw_wifi_setup,
            Screen.CONNECTED_OK: self._draw_connected_ok,
            Screen.BUTTON_CHECK: self._draw_button_check,
            Screen.MAIN_MENU: self._draw_main_menu,
            Screen.ROUND_SELECT: self._draw_round_select,
            Screen.COUNTDOWN: self._draw_countdown,
            Screen.PLAYING: self._draw_playing,
        }[st.screen]
        draw_fn(t)
        self._draw_status_bar()
        self._draw_notice_hud()

    def _center(self) -> tuple[int, int]:
        w, h = self.screen.get_size()
        return w // 2, h // 2

    def _panel_rect(self, w: int, h: int, dy: int = 0) -> pygame.Rect:
        cx, cy = self._center()
        rect = pygame.Rect(0, 0, w, h)
        rect.center = (cx, cy + dy)
        return rect

    def _connection_status(self) -> tuple[str, str]:
        """Return (status, label) for the top-right connection pill."""
        st = self.state.screen
        if st == Screen.SETUP:
            return "offline", self.L.STATUS_PILL_OFFLINE
        if st in (Screen.LOADING, Screen.WIFI_SETUP):
            return "connecting", self.L.STATUS_PILL_CONNECTING
        if st == Screen.SEARCHING:
            return "connecting", self.L.STATUS_PILL_SEARCHING
        if st in (Screen.BAND_5GHZ, Screen.OUT_OF_RANGE):
            return "error", self.L.STATUS_PILL_PROBLEM
        return "connected", self.L.STATUS_PILL_CONNECTED

    def _draw_status_bar(self) -> None:
        """No-op. Removed at user request — the connection pill in the top-
        right of each card already surfaces the link state, and the primary
        button label tells the user what to do next."""
        return

    def _draw_notice_hud(self) -> None:
        """Brief top-center toast (e.g. the Ctrl+O run-at-startup state)."""
        st = self.state
        if not st.notice_text or time.monotonic() >= st.notice_until:
            return
        w, _h = self.screen.get_size()
        self._draw_glass_pill_chip((w // 2, 38), st.notice_text)

    # ------------------ individual screens ---------------------------------

    # ------------------ shared card shell ----------------------------------

    def _draw_card_shell(
        self,
        *,
        width: int,
        height: int,
        dy: int = 0,
        wordmark: bool = False,
        status: Optional[tuple[str, str]] = None,
        status_t: float = 0.0,
    ) -> pygame.Rect:
        """Layout-only "card" — no visible box anymore. Returns the rect
        the screen content should fit inside. The connection status pill
        floats in the top-right of the *screen*, not the card."""
        del wordmark  # the window icon is the brand; no card-corner wordmark
        panel = self._panel_rect(width, height, dy=dy)
        if status is not None:
            kind, label = status
            sw, _ = self.screen.get_size()
            draw_status_pill(
                self.screen,
                (sw - 24, 30),
                label,
                self.theme,
                status=kind,
                anchor="midright",
                t=status_t,
            )
        return panel

    def _hover(self, rect: pygame.Rect) -> bool:
        return rect.collidepoint(pygame.mouse.get_pos())

    # ------------------ setup / loading / connected ------------------------

    def _draw_setup(self, t: float) -> None:
        panel = self._draw_card_shell(
            width=640, height=460, dy=-10,
            status=self._connection_status(), status_t=t,
        )
        draw_doodle_text(self.screen, self.L.TITLE_APP,
                          self.theme.title_font, INK,
                          (panel.centerx, panel.top + 96), anchor="center",
                          shadow=False)
        draw_doodle_text(self.screen, self.L.SETUP_LINE1,
                          self.theme.body_font, INK_SOFT,
                          (panel.centerx, panel.top + 178), anchor="center",
                          shadow=False)
        draw_doodle_text(self.screen, self.L.SETUP_LINE2,
                          self.theme.body_font, INK_SOFT,
                          (panel.centerx, panel.top + 208), anchor="center",
                          shadow=False)
        self.start_button_rect = pygame.Rect(0, 0, 180, 48)
        self.start_button_rect.center = (panel.centerx, panel.bottom - 52)
        draw_pill_button(self.screen, self.start_button_rect, self.L.BTN_START,
                          self.theme, primary=True,
                          hovered=self._hover(self.start_button_rect))

    def _draw_loading(self, t: float) -> None:
        panel = self._draw_card_shell(
            width=560, height=320, dy=-10,
            status=self._connection_status(), status_t=t,
        )
        draw_doodle_text(self.screen, self.L.LOADING_TITLE,
                          self.theme.title_font, INK,
                          (panel.centerx, panel.top + 96), anchor="center",
                          shadow=False)
        # Three muted dots traveling in a wave — anti-aliased via PIL.
        from doodle import blit_smooth_circle
        for i in range(3):
            phase = t * 3.2 - i * 0.4
            t01 = 0.5 + 0.5 * math.sin(phase)
            r = 6 + int(2 * t01)
            x = panel.centerx - 36 + i * 36
            y = panel.centery + 18
            alpha = 80 + int(155 * t01)
            blit_smooth_circle(self.screen, (x, y), r, INK, alpha=alpha)

    def _draw_searching(self, t: float) -> None:
        """Shown after many failed reconnects: the worker keeps trying on its
        own at a slower rate; no action is required from the host."""
        panel = self._draw_card_shell(
            width=620, height=360, dy=-10,
            status=self._connection_status(), status_t=t,
        )
        draw_doodle_text(self.screen, self.L.SEARCHING_TITLE,
                          self.theme.title_font, INK,
                          (panel.centerx, panel.top + 92), anchor="center",
                          shadow=False)
        draw_doodle_text(self.screen, self.L.SEARCHING_BODY,
                          self.theme.body_font, INK_SOFT,
                          (panel.centerx, panel.top + 150), anchor="center",
                          shadow=False)
        from doodle import blit_smooth_circle
        for i in range(3):
            phase = t * 3.2 - i * 0.4
            t01 = 0.5 + 0.5 * math.sin(phase)
            r = 6 + int(2 * t01)
            x = panel.centerx - 36 + i * 36
            y = panel.bottom - 64
            alpha = 80 + int(155 * t01)
            blit_smooth_circle(self.screen, (x, y), r, INK, alpha=alpha)

    def _draw_wifi_setup(self, t: float) -> None:
        """Manual Wi-Fi entry: two typed fields + a Connect button. Shown when
        auto-detect couldn't read the password (common on a headless Pi)."""
        from doodle import _rounded_mask, _rounded_stroke
        st = self.state
        panel = self._draw_card_shell(
            width=640, height=420, dy=-6,
            status=self._connection_status(), status_t=t,
        )
        draw_doodle_text(self.screen, self.L.WIFI_SETUP_TITLE,
                          self.theme.title_font, INK,
                          (panel.centerx, panel.top + 64), anchor="center",
                          shadow=False)
        draw_doodle_text(self.screen, self.L.WIFI_SETUP_BODY,
                          self.theme.small_font, INK_SOFT,
                          (panel.centerx, panel.top + 104), anchor="center",
                          shadow=False)

        field_w = panel.width - 96
        field_h = 50
        fx = panel.centerx - field_w // 2
        labels = [self.L.WIFI_SETUP_SSID, self.L.WIFI_SETUP_PASSWORD]
        values = [st.wifi_input_ssid, st.wifi_input_password]
        ys = [panel.top + 150, panel.top + 232]
        blink = (int(t * 2) % 2 == 0)
        for i in range(2):
            label_y = ys[i]
            draw_doodle_text(self.screen, labels[i], self.theme.small_font,
                              INK_SOFT, (fx, label_y), anchor="topleft",
                              shadow=False)
            rect = pygame.Rect(fx, label_y + 26, field_w, field_h)
            self.wifi_field_rects[i] = rect
            active = (st.wifi_input_field == i)
            radius = 12
            mask = _rounded_mask(rect.size, radius)
            wash = pygame.Surface(rect.size, pygame.SRCALPHA)
            wash.fill((28, 32, 44, 150))
            wash.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
            self.screen.blit(wash, rect.topleft)
            stroke = (*STATUS_GREEN, 235) if active else (255, 255, 255, 70)
            self.screen.blit(
                _rounded_stroke(rect.size, radius, stroke, 2 if active else 1),
                rect.topleft)
            shown = values[i]
            cursor = "|" if (active and blink) else ""
            txt = self.theme.body_font.render(shown + cursor, True, INK)
            # Left-align, clipped to the field.
            clip = self.screen.get_clip()
            self.screen.set_clip(rect.inflate(-20, 0))
            self.screen.blit(txt, (rect.left + 14,
                                    rect.centery - txt.get_height() // 2))
            self.screen.set_clip(clip)

        # Connect button.
        btn = pygame.Rect(0, 0, 240, 50)
        btn.center = (panel.centerx, panel.bottom - 52)
        self.wifi_connect_rect = btn
        draw_pill_button(self.screen, btn, self.L.WIFI_SETUP_CONNECT, self.theme,
                          primary=True, hovered=self._hover(btn))
        draw_doodle_text(self.screen, self.L.WIFI_SETUP_HINT,
                          self.theme.small_font, INK_DIM,
                          (panel.centerx, panel.bottom - 16), anchor="center",
                          shadow=False)

    def _draw_warning_screen(self, title: str, lines: list[str], t: float,
                              accent: tuple[int, int, int]) -> None:
        panel = self._draw_card_shell(
            width=680, height=400, dy=-10,
            status=self._connection_status(), status_t=t,
        )
        draw_doodle_text(self.screen, title, self.theme.title_font, INK,
                          (panel.centerx, panel.top + 96), anchor="center",
                          shadow=False)
        del accent  # the small dot under the title was removed at user request
        for i, line in enumerate(lines):
            draw_doodle_text(self.screen, line, self.theme.body_font, INK_SOFT,
                              (panel.centerx, panel.top + 168 + i * 32),
                              anchor="center", shadow=False)
        self.reload_button_rect = pygame.Rect(0, 0, 180, 48)
        self.reload_button_rect.center = (panel.centerx, panel.bottom - 52)
        draw_pill_button(self.screen, self.reload_button_rect, self.L.BTN_RELOAD,
                          self.theme, primary=True,
                          hovered=self._hover(self.reload_button_rect))

    def _draw_band_5ghz(self, t: float) -> None:
        ssid_line = (self.L.WARN_WIFI_ON_SSID.format(ssid=self.state.last_5ghz_ssid)
                     if self.state.last_5ghz_ssid
                     else self.L.WARN_WIFI_ON_5GHZ)
        self._draw_warning_screen(
            self.L.WARN_WIFI_BAND,
            [
                ssid_line,
                self.L.WARN_WIFI_SWITCH,
                self.L.WARN_WIFI_RELOAD,
            ],
            t, accent=STATUS_AMBER,
        )

    def _draw_out_of_range(self, t: float) -> None:
        panel = self._draw_card_shell(
            width=660, height=520, dy=-10,
            status=self._connection_status(), status_t=t,
        )
        draw_doodle_text(self.screen, self.L.OOR_TITLE,
                          self.theme.title_font, INK,
                          (panel.centerx, panel.top + 96), anchor="center",
                          shadow=False)
        draw_doodle_text(self.screen, self.L.OOR_BODY,
                          self.theme.body_font, INK_SOFT,
                          (panel.centerx, panel.bottom - 108), anchor="center",
                          shadow=False)
        self.reload_button_rect = pygame.Rect(0, 0, 200, 48)
        self.reload_button_rect.center = (panel.centerx, panel.bottom - 48)
        draw_pill_button(self.screen, self.reload_button_rect,
                          self.L.BTN_RETRY_NOW, self.theme,
                          primary=True,
                          hovered=self._hover(self.reload_button_rect))

    def _draw_connected_ok(self, t: float) -> None:
        panel = self._draw_card_shell(
            width=660, height=540, dy=-10,
            status=self._connection_status(), status_t=t,
        )
        draw_doodle_text(self.screen, self.L.CONNECTED_TITLE,
                          self.theme.title_font, INK,
                          (panel.centerx, panel.top + 96), anchor="center",
                          shadow=False)
        draw_doodle_text(self.screen, self.L.CONNECTED_HINT,
                          self.theme.small_font, INK_SOFT,
                          (panel.centerx, panel.bottom - 108), anchor="center",
                          shadow=False)
        self.skip_button_rect = pygame.Rect(0, 0, 200, 48)
        self.skip_button_rect.center = (panel.centerx, panel.bottom - 48)
        draw_pill_button(self.screen, self.skip_button_rect,
                          self.L.BTN_CONTINUE, self.theme,
                          primary=True,
                          hovered=self._hover(self.skip_button_rect))

    def _draw_button_check(self, t: float) -> None:
        st = self.state
        w, h = self.screen.get_size()
        can_continue = self._button_check_can_continue()
        panel = self._draw_card_shell(
            width=min(w - 96, 820), height=min(h - 132, 560),
            dy=-12,
            status=self._connection_status(), status_t=t,
        )
        draw_doodle_text(self.screen, self.L.BUTTON_CHECK_TITLE,
                          self.theme.title_font, INK,
                          (panel.centerx, panel.top + 78), anchor="center",
                          shadow=False)
        if can_continue:
            draw_doodle_text(self.screen, self.L.BUTTON_CHECK_DONE,
                              self.theme.body_font, STATUS_GREEN,
                              (panel.centerx, panel.top + 120), anchor="center",
                              shadow=False)
            draw_doodle_text(self.screen, self.L.BUTTON_CHECK_KEYS,
                              self.theme.small_font, INK_SOFT,
                              (panel.centerx, panel.top + 150), anchor="center",
                              shadow=False)
        elif st.button_check_idx < len(BUTTON_CHECK_SEQUENCE):
            target_btn = BUTTON_CHECK_SEQUENCE[st.button_check_idx]
            target_name = self.L.BUTTON_NAMES.get(
                target_btn, self.L.FB_FALLBACK_BUTTON.format(n=target_btn))
            draw_doodle_text(self.screen,
                              self.L.BUTTON_CHECK_PRESS.format(label=target_name),
                              self.theme.body_font, INK_SOFT,
                              (panel.centerx, panel.top + 120), anchor="center",
                              shadow=False)
        cols = 4
        rows = (len(BUTTON_CHECK_SEQUENCE) + cols - 1) // cols
        cell_w = (panel.width - 60) // cols
        bottom_reserve = 130 if can_continue else 170
        cell_h = min(95 if can_continue else 110,
                     (panel.height - bottom_reserve) // rows)
        grid_top = panel.top + (158 if can_continue else 156)
        for i, btn in enumerate(BUTTON_CHECK_SEQUENCE):
            r = i // cols
            c = i % cols
            tile = pygame.Rect(0, 0, cell_w - 16, cell_h - 16)
            tile.topleft = (panel.left + 30 + c * cell_w + 8,
                             grid_top + r * cell_h + 8)
            done = st.button_check_done.get(btn, False)
            current = (i == st.button_check_idx)
            self._draw_glass_tile(
                tile,
                label=self.L.BUTTON_NAMES.get(
                    btn, self.L.FB_FALLBACK_BUTTON.format(n=btn)),
                accent=STATUS_GREEN if done else (STATUS_BLUE if current else None),
                active=current and not done,
                done=done,
                t=t,
            )
        if can_continue:
            self.button_check_continue_rect = pygame.Rect(0, 0, 200, 48)
            self.button_check_continue_rect.midbottom = (
                panel.centerx, panel.bottom - 20)
            draw_pill_button(
                self.screen, self.button_check_continue_rect,
                self.L.BTN_CONTINUE, self.theme,
                primary=True,
                hovered=self._hover(self.button_check_continue_rect),
            )

    def _draw_glass_tile(self, tile: pygame.Rect, *,
                          label: str,
                          accent: Optional[tuple[int, int, int]] = None,
                          active: bool = False,
                          done: bool = False,
                          t: float = 0.0,
                          font: Optional[pygame.font.Font] = None) -> None:
        """Frosted-glass rounded tile with anti-aliased corners + optional
        accent highlight for done / active states."""
        from doodle import _rounded_mask, _rounded_stroke
        radius = max(14, tile.height // 4)
        draw_glass_card(self.screen, tile, radius=radius,
                         tint=GLASS_TINT_SOFT,
                         stroke=(255, 255, 255, 36),
                         spotlight=False, shadow=False)
        if accent is not None:
            mask = _rounded_mask(tile.size, radius)
            wash = pygame.Surface(tile.size, pygame.SRCALPHA)
            base_alpha = 56 if done else (
                int(30 + 24 * (0.5 + 0.5 * math.sin(t * 4.5))) if active else 22
            )
            wash.fill((*accent, base_alpha))
            wash.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
            self.screen.blit(wash, tile.topleft)
            stroke_alpha = 200 if done else (170 if active else 120)
            self.screen.blit(
                _rounded_stroke(tile.size, radius,
                                  (*accent, stroke_alpha), width=2),
                tile.topleft,
            )
        font = font or self.theme.small_font
        txt = font.render(label, True, INK)
        self.screen.blit(txt, txt.get_rect(center=tile.center))
        if done:
            badge_r = 11
            bx = tile.right - badge_r - 10
            by = tile.top + badge_r + 10
            # Anti-aliased filled circle using a temporary surface.
            badge_sz = (badge_r * 2 + 4, badge_r * 2 + 4)
            badge_surf = pygame.Surface(badge_sz, pygame.SRCALPHA)
            try:
                from PIL import Image, ImageDraw
                img = Image.new("RGBA", (badge_sz[0] * 2, badge_sz[1] * 2),
                                (0, 0, 0, 0))
                ImageDraw.Draw(img).ellipse(
                    (2 * 2, 2 * 2,
                     (badge_sz[0] - 2) * 2, (badge_sz[1] - 2) * 2),
                    fill=(*STATUS_GREEN, 255),
                )
                img = img.resize(badge_sz, Image.LANCZOS)
                badge_surf = pygame.image.frombytes(
                    img.tobytes(), badge_sz, "RGBA").convert_alpha()
            except Exception:
                pygame.draw.circle(badge_surf, STATUS_GREEN,
                                   (badge_sz[0] // 2, badge_sz[1] // 2),
                                   badge_r)
            self.screen.blit(badge_surf, (bx - badge_sz[0] // 2,
                                            by - badge_sz[1] // 2))
            pygame.draw.lines(
                self.screen,
                (14, 30, 22),
                False,
                [
                    (bx - 5, by + 1),
                    (bx - 1, by + 5),
                    (bx + 6, by - 4),
                ],
                3,
            )

    # Kept for compatibility — round-select tile pad. Wraps the glass tile.
    def _draw_tile_with_font(self, tile: pygame.Rect,
                              fill: tuple[int, int, int],
                              label_color: tuple[int, int, int],
                              label: str,
                              font: pygame.font.Font) -> None:
        del label_color
        self._draw_glass_tile(tile, label=label, accent=fill, font=font)

    def _draw_tile(self, tile: pygame.Rect,
                    fill: tuple[int, int, int],
                    label_color: tuple[int, int, int],
                    label: str, done: bool) -> None:
        del label_color
        self._draw_glass_tile(tile, label=label, accent=fill, done=done)

    def _draw_main_menu(self, t: float) -> None:
        w, h = self.screen.get_size()
        # Small status pill in the top-right — like the console UI overlays
        # that show what's online without stealing focus.
        kind, label = self._connection_status()
        draw_status_pill(self.screen, (w - 24, 30), label, self.theme,
                          status=kind, t=t, anchor="midright")

        banner_reserve = 160
        max_logo_w = max(160, min(380, int(w * 0.38)))
        max_logo_h = max(120, min(200, int((h - banner_reserve) * 0.30)))
        logo = self._scaled_menu_logo(max_logo_w, max_logo_h)
        logo_cy = h // 2 - max(56, min(110, h // 14))

        if logo is not None:
            lr = logo.get_rect(center=(w // 2, logo_cy))
            self.screen.blit(logo, lr)
            hints_top = lr.bottom + 14
        elif not self.game_logo:
            draw_doodle_text(self.screen, self.L.MAIN_MENU_FALLBACK,
                              self.theme.huge_font, INK,
                              (w // 2, logo_cy), anchor="center")
            hints_top = logo_cy + self.theme.huge_font.get_height() // 2 + 14
        else:
            hints_top = logo_cy + 48

        hint_head, hint_sub = make_main_menu_hint_fonts(
            w, h, rounded_display=self.L is strings_bg)
        cx = w // 2
        r1 = draw_crisp_label(self.screen, hint_head, self.L.MAIN_MENU_LINE1,
                               INK, (cx, hints_top), anchor="midtop")
        draw_crisp_label(self.screen, hint_sub, self.L.MAIN_MENU_LINE2,
                          INK_SOFT, (cx, r1.bottom + 6), anchor="midtop")

    def _draw_round_select(self, t: float) -> None:
        w, h = self.screen.get_size()
        rd = self.L is strings_bg
        head_size = max(56, min(96, w // 14))
        face_heavy = title_font_file(rounded_display=rd)
        head_font = pygame.font.Font(face_heavy, head_size) if face_heavy else pygame.font.Font(None, head_size)
        head_font.set_bold(False)

        # Small status pill in the corner, same as main menu.
        kind, label = self._connection_status()
        draw_status_pill(self.screen, (w - 24, 30), label, self.theme,
                          status=kind, t=t, anchor="midright")

        # Small "n players" chip above the headline.
        self._draw_glass_pill_chip(
            (w // 2, 80),
            self.L.players_phrase(self.state.player_count),
        )

        draw_doodle_text(self.screen, self.L.ROUND_TITLE,
                          head_font, INK,
                          (w // 2, 168), anchor="center", shadow=False)
        draw_doodle_text(self.screen, self.L.ROUND_HINT,
                          self.theme.body_font, INK_SOFT,
                          (w // 2, 168 + head_size // 2 + 50),
                          anchor="center", shadow=False)
        # 5×2 number pad — frosted glass tiles, no chunky 3D.
        pad_cols, pad_rows = 5, 2
        avail_top = 168 + head_size // 2 + 90
        avail_bottom = h - 90
        avail_w = w - 120
        cell = max(56, min(120,
                            min(avail_w // (pad_cols + 1),
                                (avail_bottom - avail_top) // (pad_rows + 1) * 2)))
        gap = max(10, cell // 7)
        pad_w = pad_cols * cell + (pad_cols - 1) * gap
        pad_h = pad_rows * cell + (pad_rows - 1) * gap
        pad_left = w // 2 - pad_w // 2
        pad_top = (avail_top + avail_bottom) // 2 - pad_h // 2
        digit_face = title_font_file(rounded_display=rd)
        digit_font = pygame.font.Font(digit_face, max(30, cell // 2)) if digit_face else pygame.font.Font(
            None, max(30, cell // 2))
        digit_font.set_bold(False)
        for i, n in enumerate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]):
            row, col = divmod(i, pad_cols)
            tile = pygame.Rect(0, 0, cell, cell)
            tile.topleft = (pad_left + col * (cell + gap),
                             pad_top + row * (cell + gap))
            self._draw_glass_tile(
                tile,
                label=str(n if n < 10 else 0),
                accent=None,
                font=digit_font,
            )

    def _draw_countdown(self, t: float) -> None:
        w, h = self.screen.get_size()
        elapsed = time.monotonic() - self.state.countdown_start
        remaining = max(0, 10 - int(elapsed))
        cx, cy = w // 2, h // 2
        # White throughout — no per-digit color cycle.
        color = INK
        label = self.L.COUNTDOWN_GO if remaining == 0 else str(remaining)
        scale = 1.0 + 0.35 * (1 - (elapsed - int(elapsed)))
        base = self.theme.huge_font.render(label, True, color)
        target_w = max(1, int(base.get_width() * scale))
        target_h = max(1, int(base.get_height() * scale))
        big = pygame.transform.smoothscale(base, (target_w, target_h))
        # Single soft glow pass — quieter than the previous triple neon halo.
        ghost = pygame.transform.smoothscale(
            base, (target_w + 28, target_h + 28),
        ).copy()
        ghost.set_alpha(45)
        self.screen.blit(ghost, ghost.get_rect(center=(cx, cy)))
        self.screen.blit(big, big.get_rect(center=(cx, cy)))
        draw_doodle_text(self.screen,
                          self.L.rounds_count_bg(self.state.player_count,
                                             self.state.round_count),
                          self.theme.body_font, INK_SOFT,
                          (cx, cy + 220), anchor="center", shadow=False)

    @staticmethod
    def _smoothstep01(x: float) -> float:
        x = max(0.0, min(1.0, x))
        return x * x * (3.0 - 2.0 * x)

    def _draw_leaderboard_phase(self, t: float) -> None:
        """Full-screen ranking between rounds. Monochrome — no rainbow."""
        from doodle import _rounded_mask, _rounded_stroke

        w, h = self.screen.get_size()
        st = self.state
        elapsed = time.monotonic() - st.leaderboard_started_at
        pairs = self._leaderboard_ranked_pairs()
        max_pts = max((s for _, s in pairs), default=1)

        draw_doodle_text(
            self.screen,
            self.L.LEADERBOARD_TITLE,
            self.theme.title_font,
            INK,
            (w // 2, 52),
            anchor="center",
            shadow=False,
        )
        if st.round_count:
            round_label = self.L.PLAYING_ROUND.format(
                n=max(1, st.current_round), total=st.round_count
            )
            draw_doodle_text(
                self.screen,
                round_label,
                self.theme.body_font,
                INK_SOFT,
                (w // 2, 102),
                anchor="center",
                shadow=False,
            )

        # "Next round in N s" — counts down toward auto-advance.
        remaining = max(0, int(math.ceil(
            LEADERBOARD_AUTO_ADVANCE_S - elapsed
        )))
        if remaining > 0:
            self._draw_glass_pill_chip(
                (w // 2, 146),
                self.L.PLAYING_NEXT_IN.format(n=remaining),
            )

        bar_left = max(80, w // 12)
        bar_right_margin = 40
        bar_w_max = w - bar_left - bar_right_margin
        n = len(pairs)
        row_h = max(30, min(52, (h - 280) // max(n, 1)))
        gap = max(8, row_h // 6)
        total_h = n * (row_h + gap) - gap
        start_y = (h - total_h) // 2 + 56

        row_radius = max(10, row_h // 3)

        for i, (player, score) in enumerate(pairs):
            stagger = i * LEADERBOARD_ROW_STAGGER_S
            raw_p = (elapsed - stagger) / LEADERBOARD_ANIM_S
            prog = self._smoothstep01(raw_p)

            y = start_y + i * (row_h + gap)
            row_rect = pygame.Rect(bar_left, y, bar_w_max, row_h)

            # Row body — glass mask + dark wash + hairline stroke. No color.
            mask = _rounded_mask(row_rect.size, row_radius)
            wash = pygame.Surface(row_rect.size, pygame.SRCALPHA)
            wash.fill((22, 26, 36, 130))
            wash.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
            self.screen.blit(wash, row_rect.topleft)
            self.screen.blit(
                _rounded_stroke(row_rect.size, row_radius,
                                  (255, 255, 255, 50), 1),
                row_rect.topleft,
            )

            # Fill bar — soft white, only its width signals the score.
            fill_w = int(row_rect.width * (score / max_pts) * prog)
            if fill_w > 4:
                fr = pygame.Rect(row_rect.left, row_rect.top,
                                  fill_w, row_rect.height)
                fr_mask = _rounded_mask(fr.size, row_radius)
                fill_surf = pygame.Surface(fr.size, pygame.SRCALPHA)
                fill_surf.fill((255, 255, 255, 38))
                fill_surf.blit(fr_mask, (0, 0),
                                special_flags=pygame.BLEND_RGBA_MIN)
                self.screen.blit(fill_surf, fr.topleft)

            # Rank pill — same glass treatment, no per-rank color.
            rk_surf = self.theme.small_font.render(str(i + 1), True, INK)
            pill_w = max(46, rk_surf.get_width() + 20)
            pill_h = row_h - 8
            pill = pygame.Rect(0, 0, pill_w, pill_h)
            pill.centery = row_rect.centery
            pill.right = bar_left - 10
            p_mask = _rounded_mask(pill.size, pill_h // 2)
            p_wash = pygame.Surface(pill.size, pygame.SRCALPHA)
            p_wash.fill((22, 26, 36, 150))
            p_wash.blit(p_mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
            self.screen.blit(p_wash, pill.topleft)
            self.screen.blit(
                _rounded_stroke(pill.size, pill_h // 2,
                                  (255, 255, 255, 70), 1),
                pill.topleft,
            )
            self.screen.blit(rk_surf, rk_surf.get_rect(center=pill.center))

            label = self.L.LEADERBOARD_PLAYER.format(n=player)
            lbl = self.theme.body_font.render(label, True, INK)
            self.screen.blit(
                lbl,
                (row_rect.left + 14, row_rect.centery - lbl.get_height() // 2),
            )

            pts_txt = self.theme.body_font.render(str(score), True, INK_SOFT)
            self.screen.blit(
                pts_txt,
                pts_txt.get_rect(midright=(row_rect.right - 12, row_rect.centery)),
            )

    # ----------------------- playing-screen helpers ------------------------

    def _draw_winner_podium(self, t: float) -> None:
        """Kahoot-style end-of-game podium: gold/silver/bronze columns + a
        ranked list of also-rans, plus a 'Back to menu' pill button."""
        from doodle import _rounded_mask, _rounded_stroke, blit_smooth_circle
        w, h = self.screen.get_size()
        pairs = self._leaderboard_ranked_pairs()  # already sorted desc

        # Headline.
        draw_doodle_text(self.screen, self.L.WINNER_TITLE,
                          self.theme.huge_font, INK,
                          (w // 2, 90), anchor="center", shadow=False)
        if pairs:
            top_player, top_score = pairs[0]
            sub = self.L.WINNER_SUBTITLE.format(n=top_player, s=top_score)
            draw_doodle_text(self.screen, sub, self.theme.body_font,
                              INK_SOFT, (w // 2, 168),
                              anchor="center", shadow=False)

        # Podium geometry — center 1st, left 2nd, right 3rd.
        podium_cy = h // 2 + 140
        column_w = max(140, min(220, w // 6))
        gap = max(20, column_w // 6)
        max_pts = max(s for _, s in pairs) if pairs else 1
        max_pts = max(1, max_pts)
        # Heights: relative to score, with a minimum so empty columns are
        # still visible. 1st always tallest because it has the highest score.
        max_col_h = max(160, min(320, h // 3))
        min_col_h = max(80, max_col_h // 3)

        # Slight animated grow-in: first 0.6 s of the screen.
        grow_t = self._smoothstep01(min(1.0, max(0.0,
            (time.monotonic() - self.state.round_started_at) / 0.6)))

        center_x = w // 2
        layout_order = [1, 0, 2]  # draw 2nd, 1st, 3rd left→right
        positions = {
            0: (center_x,                      "gold"),
            1: (center_x - column_w - gap,     "silver"),
            2: (center_x + column_w + gap,     "bronze"),
        }
        accent_map = {
            "gold":   (255, 196, 76),
            "silver": (190, 200, 220),
            "bronze": (205, 138, 80),
        }
        accent_alpha = 38

        for rank_idx in layout_order:
            if rank_idx >= len(pairs):
                continue
            player, score = pairs[rank_idx]
            cx, tier = positions[rank_idx]
            accent = accent_map[tier]
            score_ratio = score / max_pts
            col_h = int((min_col_h
                          + (max_col_h - min_col_h) * score_ratio)
                         * grow_t)
            col_top = podium_cy - col_h // 2
            col_rect = pygame.Rect(cx - column_w // 2, col_top,
                                    column_w, col_h)
            radius = 22
            if col_rect.height <= 4:
                continue
            mask = _rounded_mask(col_rect.size, radius)
            # Base glass wash + faint accent tint so each tier reads slightly.
            wash = pygame.Surface(col_rect.size, pygame.SRCALPHA)
            wash.fill((28, 32, 44, 110))
            wash.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
            self.screen.blit(wash, col_rect.topleft)
            tint = pygame.Surface(col_rect.size, pygame.SRCALPHA)
            tint.fill((*accent, accent_alpha))
            tint.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
            self.screen.blit(tint, col_rect.topleft)
            self.screen.blit(
                _rounded_stroke(col_rect.size, radius,
                                  (*accent, 180), 1),
                col_rect.topleft,
            )

            # Medal disc + rank number sitting *above* the column.
            badge_r = 32
            badge_cx = cx
            badge_cy = col_top - badge_r - 10
            blit_smooth_circle(self.screen, (badge_cx, badge_cy),
                               badge_r, accent)
            blit_smooth_circle(self.screen, (badge_cx, badge_cy),
                               badge_r - 4, (22, 24, 32), alpha=200)
            rank_num = self.theme.title_font.render(
                str(rank_idx + 1), True, accent,
            )
            self.screen.blit(rank_num,
                              rank_num.get_rect(center=(badge_cx, badge_cy)))

            # Player label + score inside the column, anchored to the bottom.
            label = self.L.LEADERBOARD_PLAYER.format(n=player)
            lbl = self.theme.body_font.render(label, True, INK)
            self.screen.blit(lbl, lbl.get_rect(
                midbottom=(cx, col_rect.bottom - 56),
            ))
            score_surf = self.theme.title_font.render(str(score), True, INK)
            self.screen.blit(score_surf, score_surf.get_rect(
                midbottom=(cx, col_rect.bottom - 18),
            ))

        # Back-to-menu pill button.
        btn_rect = pygame.Rect(0, 0, 220, 50)
        btn_rect.center = (w // 2, h - 56)
        draw_pill_button(self.screen, btn_rect, self.L.WINNER_BACK_BUTTON,
                          self.theme, primary=True,
                          hovered=self._hover(btn_rect))
        self.winner_back_button_rect = btn_rect

    def _draw_playing_action_panel(self, top_y: int, t: float) -> None:
        """Kahoot-style action area under the waveform.

        Lays out big tappable controls — primary pill buttons for host
        actions and a row of circular player-number buttons for on-screen
        buzz-in. Every interactive element gets recorded into
        ``self._wait_action_rects`` for `_handle_click`."""
        st = self.state
        ph = st.playing_phase
        # Reset click targets every frame.
        self._wait_action_rects: list[tuple[pygame.Rect, str]] = []
        if ph not in (PlayingPhase.WAIT_REVEAL,
                      PlayingPhase.WAIT_CONFIRM,
                      PlayingPhase.WAIT_ADVANCE):
            return

        w, _h = self.screen.get_size()
        mouse = pygame.mouse.get_pos()

        # ---- Heading -----------------------------------------------------
        if ph == PlayingPhase.WAIT_CONFIRM and st.guessed_player is not None:
            heading = self.L.WAIT_CONFIRM_HEADING.format(n=st.guessed_player)
        elif ph == PlayingPhase.WAIT_REVEAL:
            heading = self.L.WAIT_REVEAL_HEADING
        else:  # WAIT_ADVANCE
            heading = self.L.WAIT_ADVANCE_HEADING

        head_surf = self.theme.title_font.render(heading, True, INK)
        head_rect = head_surf.get_rect(midtop=(w // 2, top_y))
        self.screen.blit(head_surf, head_rect)

        # ---- Action controls --------------------------------------------
        # Heights / gaps shared across the three layouts.
        btn_h = 56
        btn_radius = btn_h // 2
        btn_gap = 16
        row_y = head_rect.bottom + 28

        def _record(rect: pygame.Rect, action_id: str) -> None:
            self._wait_action_rects.append((rect, action_id))

        def _primary_button(label: str, action_id: str,
                              center: tuple[int, int],
                              width: int) -> pygame.Rect:
            rect = pygame.Rect(0, 0, width, btn_h)
            rect.center = center
            draw_pill_button(
                self.screen, rect, label, self.theme,
                primary=True, hovered=rect.collidepoint(mouse),
            )
            _record(rect, action_id)
            return rect

        if ph == PlayingPhase.WAIT_REVEAL:
            # Big primary button to replay (second clip), then a sub-label
            # and a row of clickable player numbers for buzz-in.
            replay_w = max(220, self.theme.body_font.size(
                self.L.WAIT_REVEAL_REPLAY)[0] + 80)
            _primary_button(
                self.L.WAIT_REVEAL_REPLAY, "replay_clip2",
                (w // 2, row_y + btn_h // 2), replay_w,
            )
            sub_y = row_y + btn_h + 18
            sub = self.theme.small_font.render(
                self.L.WAIT_REVEAL_BUZZ_HINT, True, INK_SOFT,
            )
            self.screen.blit(sub, sub.get_rect(midtop=(w // 2, sub_y)))
            num_y = sub_y + sub.get_height() + 18
            self._draw_player_numpad(
                top_y=num_y,
                player_count=st.player_count,
                record=_record,
            )

        elif ph == PlayingPhase.WAIT_CONFIRM and st.guessed_player is not None:
            # Three side-by-side primary buttons.
            labels = [
                (self.L.WAIT_CONFIRM_ONE,    "confirm1"),
                (self.L.WAIT_CONFIRM_TWO,    "confirm2"),
                (self.L.WAIT_CONFIRM_CANCEL, "cancel_buzz"),
            ]
            widths = [
                max(160, self.theme.body_font.size(lbl)[0] + 56)
                for lbl, _ in labels
            ]
            total_w = sum(widths) + btn_gap * (len(labels) - 1)
            left = w // 2 - total_w // 2
            cy = row_y + btn_h // 2
            for (lbl, aid), bw in zip(labels, widths):
                _primary_button(lbl, aid, (left + bw // 2, cy), bw)
                left += bw + btn_gap
            # Re-pick who actually answered (any player, highlighted green); the
            # +1 / +2 buttons above then award that player. Works even while the
            # music is paused.
            sub_y = cy + btn_h // 2 + 18
            sub = self.theme.small_font.render(
                self.L.WAIT_CONFIRM_PICK, True, INK_SOFT,
            )
            self.screen.blit(sub, sub.get_rect(midtop=(w // 2, sub_y)))
            self._draw_player_numpad(
                top_y=sub_y + sub.get_height() + 16,
                player_count=st.player_count,
                record=_record,
                selected=st.guessed_player,
            )

        else:  # WAIT_ADVANCE
            advance_w = max(240, self.theme.body_font.size(
                self.L.WAIT_ADVANCE_NEXT)[0] + 80)
            _primary_button(
                self.L.WAIT_ADVANCE_NEXT, "open_scoreboard",
                (w // 2, row_y + btn_h // 2), advance_w,
            )

    def _draw_player_numpad(
        self, *,
        top_y: int,
        player_count: int,
        record,
        selected: Optional[int] = None,
    ) -> None:
        """Row (or two) of circular player-number buttons. Clicking one
        registers an on-screen buzz-in as if the player hit the numpad.
        ``top_y`` is the top edge of the numpad block. ``selected`` (if given)
        is drawn with a green highlight — used during the buzz pause to show
        which player will receive the points."""
        from doodle import _rounded_mask, _rounded_stroke
        w, _h = self.screen.get_size()
        mouse = pygame.mouse.get_pos()
        n = max(1, min(player_count, 10))
        diam = 64
        gap = 14
        # Wrap onto two rows when more than 5 players so circles don't shrink.
        per_row = n if n <= 5 else (n + 1) // 2
        row1_n = per_row
        row2_n = n - row1_n
        def _row_layout(count: int, y: int) -> list[tuple[int, int, int]]:
            total = count * diam + (count - 1) * gap
            x0 = w // 2 - total // 2
            return [
                (i, x0 + i * (diam + gap) + diam // 2, y)
                for i in range(count)
            ]
        rows = []
        if row2_n == 0:
            rows.append(_row_layout(row1_n, top_y + diam // 2))
        else:
            rows.append(_row_layout(row1_n, top_y + diam // 2))
            rows.append(_row_layout(row2_n,
                                       top_y + diam + gap + diam // 2))

        player_idx = 1
        for row in rows:
            for _i, cx, cy in row:
                rect = pygame.Rect(0, 0, diam, diam)
                rect.center = (cx, cy)
                hovered = rect.collidepoint(mouse)
                is_sel = (selected is not None and player_idx == selected)
                radius = diam // 2
                mask = _rounded_mask(rect.size, radius)
                # Frosted disc — green when selected, lighter on hover.
                fill = pygame.Surface(rect.size, pygame.SRCALPHA)
                if is_sel:
                    fill.fill((*STATUS_GREEN, 110))
                else:
                    fill.fill((255, 255, 255, 36 if hovered else 22))
                fill.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
                self.screen.blit(fill, rect.topleft)
                stroke_col = ((*STATUS_GREEN, 235) if is_sel
                              else (255, 255, 255, 170 if hovered else 110))
                self.screen.blit(
                    _rounded_stroke(rect.size, radius, stroke_col,
                                      2 if is_sel else 1),
                    rect.topleft,
                )
                lbl = self.theme.title_font.render(
                    str(player_idx), True, INK,
                )
                self.screen.blit(lbl, lbl.get_rect(center=rect.center))
                record(rect, f"buzz_player_{player_idx}")
                player_idx += 1

    def _draw_glass_pill_chip(self, center: tuple[int, int], label: str,
                                color: tuple[int, int, int] = INK) -> pygame.Rect:
        """Small glassy pill — anti-aliased, with the frosted-bg crop inside."""
        from doodle import _rounded_mask, _rounded_stroke, _blurred_background
        font = self.theme.body_font
        lbl = font.render(label, True, color)
        pad_x, pad_y = 18, 8
        w = lbl.get_width() + pad_x * 2
        h = lbl.get_height() + pad_y * 2
        rect = pygame.Rect(0, 0, w, h)
        rect.center = center
        radius = h // 2
        mask = _rounded_mask((w, h), radius)
        blurred = _blurred_background(self.screen.get_size())
        crop = pygame.Surface((w, h), pygame.SRCALPHA)
        crop.blit(blurred, (-rect.left, -rect.top))
        crop.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
        self.screen.blit(crop, rect.topleft)
        wash = pygame.Surface((w, h), pygame.SRCALPHA)
        wash.fill((22, 26, 36, 130))
        wash.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
        self.screen.blit(wash, rect.topleft)
        self.screen.blit(_rounded_stroke((w, h), radius,
                                            (255, 255, 255, 60), 1),
                          rect.topleft)
        self.screen.blit(lbl, lbl.get_rect(center=rect.center))
        return rect

    def _draw_playing(self, t: float) -> None:
        w, h = self.screen.get_size()
        st = self.state

        if st.play_error:
            draw_doodle_text(self.screen, self.L.PLAYING_TITLE,
                              self.theme.huge_font, INK,
                              (w // 2, h // 2 - 90), anchor="center")
            draw_doodle_text(self.screen, st.play_error,
                              self.theme.body_font, INK_SOFT,
                              (w // 2, h // 2 + 20), anchor="center", shadow=False)
            return

        if st.playing_phase == PlayingPhase.LEADERBOARD:
            self._draw_leaderboard_phase(t)
            return

        if st.rounds_finished:
            self._draw_winner_podium(t)
            return

        # Round counter — frosted pill at the top center.
        if st.round_count:
            round_idx = max(1, st.current_round)
            round_label = self.L.PLAYING_ROUND.format(n=round_idx, total=st.round_count)
            self._draw_glass_pill_chip((w // 2, 56), round_label, color=INK)

        playing = self.clip_player.is_playing() and not self.clip_player.buzz_paused()
        pulse_rate = 4.4 if playing else 1.1
        idle_amp = 0.22
        bar_count = max(28, min(64, w // 16))
        levels, audio_synced = self.clip_player.get_visual_levels(bar_count)

        bar_w = max(4, (w - 200) // (bar_count * 2))
        gap = max(3, bar_w // 2)
        total_w = bar_count * bar_w + (bar_count - 1) * gap
        bx = w // 2 - total_w // 2
        # During wait phases the action area takes the bottom half, so the
        # waveform moves up to leave room for the buttons / numpad.
        in_wait = st.playing_phase in (
            PlayingPhase.WAIT_REVEAL,
            PlayingPhase.WAIT_CONFIRM,
            PlayingPhase.WAIT_ADVANCE,
        )
        by = (h // 2 - 80) if in_wait else (h // 2 + 50)
        max_h = min(220, int(h * 0.36))

        # Single off-white tonal waveform sitting on the background.
        bar_color = (240, 244, 252)
        for i in range(bar_count):
            if audio_synced and i < len(levels):
                norm = float(levels[i])
            else:
                phase = t * pulse_rate + i * 0.45
                norm = (0.5 + 0.5 * math.sin(phase)) * idle_amp
            height = max(6, int(10 + (max_h - 10) * norm))
            x = bx + i * (bar_w + gap)
            slab = pygame.Rect(x, by - height, bar_w, height)
            radius = max(2, bar_w // 2)
            pygame.draw.rect(self.screen, bar_color, slab, border_radius=radius)

        # Rich action area beneath the waveform — only during wait phases.
        # Anchored relative to the (moved-up) waveform so the buttons /
        # numpad never collide with the bars.
        self._draw_playing_action_panel(by + 70, t)


PRESENT_PORT = 8090


def _start_present_server_background() -> None:
    """Run the PRESENT song-library web UI on the LAN (see PRESENT.md)."""

    def _serve() -> None:
        try:
            from present.server import run as present_run
        except ImportError as exc:
            print(
                f"PRESENT web UI not started (missing dependency): {exc}",
                file=sys.stderr,
            )
            return
        try:
            present_run(host="0.0.0.0", port=PRESENT_PORT, debug=False)
        except OSError as exc:
            print(
                f"PRESENT web UI not started (port {PRESENT_PORT}): {exc}",
                file=sys.stderr,
            )
        except Exception as exc:  # noqa: BLE001 — keep pygame running
            print(f"PRESENT web UI stopped: {exc}", file=sys.stderr)

    threading.Thread(
        target=_serve,
        name="present-serve",
        daemon=True,
    ).start()
    print(
        f"PRESENT library: http://127.0.0.1:{PRESENT_PORT}/ "
        f"(LAN: http://<this-PC-ip>:{PRESENT_PORT}/)",
        flush=True,
    )


def main() -> int:
    try:
        _start_present_server_background()
        App().run()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
