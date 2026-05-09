# -*- coding: utf-8 -*-
"""Bulgarian UI strings for Labcoin Music Remote."""

from __future__ import annotations

import re


WINDOW_TITLE = "Labcoin — музикално дистанционно"

STATUS_DEFAULT = "Натиснете СТАРТ, за да потърсите дистанционното."
STATUS_SEARCHING_BLE = "Търсене на дистанционното по BLE..."
STATUS_RETRYING = "Нов опит..."
STATUS_BUTTON_CHECK = "Натиснете осветения бутон на дистанционното."
STATUS_MAIN_MENU = "Натиснете броя играчи на дистанционното."
STATUS_ROUNDS = "Колко рунда? Натиснете число."

STATUS_5GHZ = "Свързани сте към 5 GHz мрежа."
STATUS_OOR = "Дистанционното не е в обсег — приближете го."
STATUS_LOST_LINK = "Изгубена връзка: {err}"
STATUS_CONNECTED = "Дистанционното е свързано ({addr})."
STATUS_DISCONNECTED = "Дистанционното се разкачи. Нов опит на всеки 15 сек..."

TITLE_WORDMARK = "LABCOIN"
TITLE_APP = "Музикално дистанционно"
SETUP_LINE1 = "Уверете се, че компютърът ви е в същата"
SETUP_LINE2 = "2,4 GHz Wi‑Fi мрежа като дистанционното."

BTN_START = "СТАРТ"
BTN_RELOAD = "ПРЕЗАРЕДИ"
BTN_RETRY_NOW = "ОПИТ ОТНОВО"
BTN_CONTINUE = "НАПРЕД"

LOADING_TITLE = "Търсене на дистанционното"

WARN_WIFI_BAND = "Грешна Wi‑Fi лента!"
WARN_WIFI_SWITCH = "Преминете компютъра към 2,4 GHz мрежа"
WARN_WIFI_RELOAD = "и натиснете ПРЕЗАРЕДИ."
WARN_WIFI_ON_SSID = 'Свързани сте към "{ssid}".'
WARN_WIFI_ON_5GHZ = "Свързани сте към 5 GHz Wi‑Fi."

OOR_TITLE = "Дистанционното не е в обсег"
OOR_BODY = "Приближете го — нов опит на всеки 15 сек."

CONNECTED_TITLE = "Дистанционното е свързано!"
CONNECTED_HINT = (
    "Натиснете интервал (Space) или щракнете НАПРЕД, за да тествате бутоните."
)

BUTTON_CHECK_TITLE = "Проверка на бутоните"
BUTTON_CHECK_DONE = "Готово — продължете, когато сте готови."
BUTTON_CHECK_KEYS = (
    "Натиснете Enter / интервал или докоснете НАПРЕД."
)
BUTTON_CHECK_PRESS = "Натиснете: {label}"

MAIN_MENU_FALLBACK = "LABCOIN MUSIC"
MAIN_MENU_LINE1 = "НАТИСНЕТЕ БРОЯ ИГРАЧИ"
MAIN_MENU_LINE2 = (
    "от 1 до 10 — на дистанционното или на клавиатурата."
)

ROUND_TITLE = "Колко рунда?"
ROUND_HINT = "Натиснете число на дистанционното (или клавиатурата)."

PLAYING_TITLE = "Играта тече"
PLAYING_STATUS = "Играта започна — слушайте дистанционното!"
PLAYING_NOTE = (
    "(Логиката за рундове идва следваща — това е свързаната обвивка.)"
)

TILE_OK = "ОК"
COUNTDOWN_GO = "ТРЪГНИ!"

FB_FALLBACK_BUTTON = "Бутон {n}"


def players_phrase(n: int) -> str:
    if n == 1:
        return "1 играч — да играем!"
    return f"{n} играчи — да играем!"


def rounds_count_bg(p: int, r: int) -> str:
    pw = "играч" if p == 1 else "играчи"
    rw = "рунд" if r == 1 else "рунда"
    return f"{p} {pw}  •  {r} {rw}"


def translate_connection_error(text: str) -> str:
    """Bulgarian user-visible wording for connector ``error`` events."""
    if text.startswith("Python package 'bleak'"):
        return 'Липсва Python пакетът "bleak".'
    if text.startswith("Connection error:"):
        rest = text.split(":", 1)[1].strip()
        return f"Грешка при свързване: {rest}"
    return text


def translate_worker_status(text: str) -> str:
    """Turn backend worker English lines into Bulgarian."""
    if text.startswith("Reading Wi-Fi profile"):
        return "Четене на Wi‑Fi профил..."
    if text.startswith("Scanning BLE for"):
        return 'Търсене по BLE за "OLED-Music"...'
    m = re.match(r"BLE found (.+), pairing", text)
    if m:
        return f"Намерено BLE устройство {m.group(1)}, свързване..."
    m = re.match(r"Sending Wi-Fi creds for '(.+)'", text)
    if m:
        return f'Изпращане на Wi‑Fi данни за "{m.group(1)}"...'
    m = re.match(r"Opening TCP (.+)", text)
    if m:
        return f"Отваряне на TCP {m.group(1)}..."
    return text
