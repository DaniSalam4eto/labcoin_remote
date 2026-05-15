# -*- coding: utf-8 -*-
"""English UI strings for Labcoin Music Remote."""

from __future__ import annotations

import re

WINDOW_TITLE = "Labcoin — music remote"

STATUS_DEFAULT = "Press START to look for the remote."
STATUS_SEARCHING_BLE = "Searching for the remote over BLE..."
STATUS_RETRYING = "Trying again..."
STATUS_BUTTON_CHECK = "Press any remote button once per highlighted tile."
STATUS_MAIN_MENU = "Press the number of players on the remote."
STATUS_ROUNDS = "How many rounds? Press a number."

STATUS_5GHZ = "You are on a 5 GHz network."
STATUS_OOR = "The remote is out of range — move it closer."
STATUS_LOST_LINK = "Lost link: {err}"
STATUS_CONNECTED = "Remote connected ({addr})."
STATUS_DISCONNECTED = "Remote disconnected. Retrying every 15 seconds..."

TITLE_WORDMARK = "LABCOIN"
TITLE_APP = "Music remote"
SETUP_LINE1 = "Make sure this computer is on the same"
SETUP_LINE2 = "2.4 GHz Wi‑Fi network as the remote."

BTN_START = "START"
BTN_RELOAD = "RELOAD"
BTN_RETRY_NOW = "TRY AGAIN"
BTN_CONTINUE = "CONTINUE"

LOADING_TITLE = "Looking for the remote"

WARN_WIFI_BAND = "Wrong Wi‑Fi band!"
WARN_WIFI_SWITCH = "Switch this computer to a 2.4 GHz network"
WARN_WIFI_RELOAD = "then press RELOAD."
WARN_WIFI_ON_SSID = 'You are on "{ssid}".'
WARN_WIFI_ON_5GHZ = "You are on 5 GHz Wi‑Fi."

OOR_TITLE = "Remote out of range"
OOR_BODY = "Move it closer — retrying every 15 seconds."

CONNECTED_TITLE = "Remote connected!"
CONNECTED_HINT = (
    "Press almost any remote button, Space, or click CONTINUE to test the buttons."
)

BUTTON_CHECK_TITLE = "Button check"
BUTTON_CHECK_DONE = "All set — continue when you are ready."
BUTTON_CHECK_KEYS = (
    "Press any remote button, Enter / Space, or tap CONTINUE."
)
BUTTON_CHECK_PRESS = "Next: {label} — any remote button advances."

MAIN_MENU_FALLBACK = "LABCOIN MUSIC"
MAIN_MENU_LINE1 = "PRESS THE NUMBER OF PLAYERS"
MAIN_MENU_LINE2 = (
    "from 1 to 10 — on the remote or the keyboard."
)

ROUND_TITLE = "How many rounds?"
ROUND_HINT = "Press a number on the remote (or keyboard)."

PLAYING_TITLE = "Game on"
PLAYING_STATUS = "Listen — the title is on the remote display."
PLAYING_NOTE = (
    "Numpad = buzz (stops clip)   •   Check advances rounds & scoreboard   •   Hold both checks ~2 s = mis-buzz   •   Backspace = menu"
)
PLAYING_HINT_WAIT_REVEAL = (
    "Clip 1 done — press Check on the remote for another clip from this song."
)
PLAYING_HINT_CLIP2 = "Second clip — names stay on the remote only."
PLAYING_HINT_WAIT_CONFIRM = (
    "Paused for a buzz-in. Check = 1 pt · Double check = 2 pts (then podium — Check again for next round). "
    "Hold Check + Double check together ~2 s to cancel — music continues, no points."
)
PLAYING_HINT_WAIT_ADVANCE = (
    "Press Check for this scoreboard — press Check again when the big bars finish "
    "to start the next round."
)
PLAYING_HINT_GUESS = "While a clip plays: numpad 1–{n} buzzes in (stops playback — see status line)."
PLAYING_BUZZ_LOCK = "Buzz-in: player {n}"
PLAYING_ROUND = "Round {n} of {total}"
PLAYING_NOW = "Now playing"
PLAYING_NO_LIBRARY = (
    "No songs found. Run `python -m present init` to build the library."
)
PLAYING_AUDIO_ERROR = "Audio engine unavailable — install ffmpeg and retry."
PLAYING_REMOTE_OFFLINE = "Remote offline — clip is playing on this PC only."
PLAYING_FINISHED = "All rounds played — press Check to return to the menu."

LEADERBOARD_TITLE = "Leaderboard"
LEADERBOARD_PLAYER = "Player {n}"
PLAYING_LEADERBOARD_HINT = (
    "Press Check or Enter for the next round (continues automatically after a few seconds)."
)

TILE_OK = "OK"
COUNTDOWN_GO = "GO!"

FB_FALLBACK_BUTTON = "Button {n}"

# Matches esp32_connector button indices; English labels for the GUI.
BUTTON_NAMES = {
    1: "Check",
    2: "Double check",
    3: "Numpad 10",
    4: "Numpad 9",
    5: "Numpad 6",
    6: "Numpad 3",
    7: "Numpad 2",
    8: "Numpad 5",
    9: "Numpad 1",
    10: "Numpad 4",
    11: "Numpad 7",
    12: "Numpad 8",
}


def players_phrase(n: int) -> str:
    if n == 1:
        return "1 player — let's play!"
    return f"{n} players — let's play!"


def rounds_count_bg(p: int, r: int) -> str:
    pw = "player" if p == 1 else "players"
    rw = "round" if r == 1 else "rounds"
    return f"{p} {pw}  •  {r} {rw}"


def translate_connection_error(text: str) -> str:
    if text.startswith("Python package 'bleak'"):
        return 'Missing Python package "bleak".'
    if text.startswith("Connection error:"):
        rest = text.split(":", 1)[1].strip()
        return f"Connection error: {rest}"
    return text


def translate_worker_status(text: str) -> str:
    if text.startswith("Reading Wi-Fi profile"):
        return "Reading Wi‑Fi profile..."
    if text.startswith("Scanning BLE for"):
        return 'Scanning BLE for "OLED-Music"...'
    m = re.match(r"BLE found (.+), pairing", text)
    if m:
        return f"BLE device {m.group(1)} found, pairing..."
    m = re.match(r"Sending Wi-Fi creds for '(.+)'", text)
    if m:
        return f'Sending Wi‑Fi credentials for "{m.group(1)}"...'
    m = re.match(r"Opening TCP (.+)", text)
    if m:
        return f"Opening TCP {m.group(1)}..."
    return text
