# -*- coding: utf-8 -*-
"""Bulgarian UI strings for Labcoin Music Remote."""

from __future__ import annotations

import re


WINDOW_TITLE = "Labcoin - музикално дистанционно"

STATUS_DEFAULT = "Натиснете СТАРТ, за да потърсите дистанционното."
STATUS_SEARCHING_BLE = "Търсене на дистанционното по BLE..."
STATUS_RETRYING = "Нов опит..."
STATUS_BUTTON_CHECK = "Натиснете произволен бутон за всяка осветена плочка."
STATUS_MAIN_MENU = "Натиснете броя играчи на дистанционното."
STATUS_ROUNDS = "Колко рунда? Натиснете число."

STATUS_5GHZ = "Свързани сте към 5 GHz мрежа."
STATUS_OOR = "Дистанционното не е в обсег - приближете го."
STATUS_LOST_LINK = "Изгубена връзка: {err}"
STATUS_CONNECTED = "Дистанционното е свързано ({addr})."
STATUS_DISCONNECTED = "Дистанционното се разкачи. Нов опит на всеки 15 сек..."

TITLE_WORDMARK = "LABCOIN"
TITLE_APP = "Музикално дистанционно"
SETUP_LINE1 = "Уверете се, че компютърът ви е в същата"
SETUP_LINE2 = "2,4 GHz Wi‑Fi мрежа като дистанционното."

# Short status-pill labels shown on every screen.
STATUS_PILL_OFFLINE    = "Дистанционното не е свързано"
STATUS_PILL_CONNECTING = "Свързване…"
STATUS_PILL_CONNECTED  = "Дистанционното е свързано"
STATUS_PILL_PROBLEM    = "Проблем с връзката"
ACTION_HINT_START      = "Старт"
ACTION_HINT_RELOAD     = "Презареди"
ACTION_HINT_CONTINUE   = "Напред"

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
OOR_BODY = "Приближете го - нов опит на всеки 15 сек."

CONNECTED_TITLE = "Дистанционното е свързано!"
CONNECTED_HINT = (
    "Натиснете почти произволен бутон на дистанционното, интервал (Space) "
    "или щракнете НАПРЕД, за да тествате бутоните."
)

BUTTON_CHECK_TITLE = "Проверка на бутоните"
BUTTON_CHECK_DONE = "Готово - продължете, когато сте готови."
BUTTON_CHECK_KEYS = (
    "Натиснете произволен бутон на дистанционното, Enter / интервал "
    "или докоснете НАПРЕД."
)
BUTTON_CHECK_PRESS = "Следващо: {label} - произволен бутон продължава."

MAIN_MENU_FALLBACK = "LABCOIN MUSIC"
MAIN_MENU_LINE1 = "НАТИСНЕТЕ БРОЯ ИГРАЧИ"
MAIN_MENU_LINE2 = (
    "от 1 до 10 - на дистанционното или на клавиатурата."
)

ROUND_TITLE = "Колко рунда?"
ROUND_HINT = "Натиснете число на дистанционното (или клавиатурата)."

PLAYING_TITLE = "Играта тече"
PLAYING_STATUS = "Слушайте - заглавието е на дисплея на дистанционното."
PLAYING_NOTE = (
    "Нумпад = сигнал (спира клипа)   •   Отметка = рунд и табло   •   Дръжте двете отметки ~2 с = грешка   •   Backspace = меню"
)
PLAYING_HINT_WAIT_REVEAL = (
    "Клип 1 свърши - натиснете Отметка за втори клип от същата песен."
)
PLAYING_HINT_CLIP2 = "Втори клип - имената са само на дистанционното."
PLAYING_HINT_WAIT_CONFIRM = (
    "Пауза за сигнал. Отметка = 1 т. · Двойна отметка = 2 т. (след това табло - пак Отметка за следващ рунд). "
    "Дръжте Отметка + Двойна отметка ~2 с за отмяна - музиката продължава, без точки."
)
PLAYING_HINT_WAIT_ADVANCE = (
    "Отметка за таблото - отново Отметка, когато лентите свършат, за следващия рунд."
)
PLAYING_HINT_GUESS = "По време на клип: нумпад 1-{n} = сигнал (спира звука - вижте лентата долу)."
PLAYING_BUZZ_LOCK = "Сигнал: играч {n}"
PLAYING_ROUND = "Рунд {n} от {total}"
PLAYING_NOW = "В момента"
PLAYING_NO_LIBRARY = (
    "Няма песни. Стартирайте `python -m present init`, за да изградите библиотеката."
)
PLAYING_AUDIO_ERROR = "Аудио системата не е налична - инсталирайте ffmpeg и опитайте отново."
PLAYING_REMOTE_OFFLINE = "Дистанционното е офлайн - звукът свири само на компютъра."
PLAYING_FINISHED = "Всички рундове изиграни - Отметка за връщане в менюто."

LEADERBOARD_TITLE = "Класация"
LEADERBOARD_PLAYER = "Играч {n}"
PLAYING_LEADERBOARD_HINT = (
    "Отметка или Enter за следващ рунд (след малко продължава и само)."
)
PLAYING_NEXT_IN = "Следващ рунд след {n} с"

# Rich wait-phase panel under the waveform.
WAIT_REVEAL_HEADING   = "Клип 1 свърши - какво следва?"
WAIT_REVEAL_REPLAY    = "Пусни втори клип"
WAIT_REVEAL_BUZZ      = "Или нумпад 1-{n}, за да отгатнеш"
WAIT_REVEAL_BUZZ_HINT = "Или избери играч, който иска да отговори"

WAIT_CONFIRM_HEADING = "Играч {n} натисна сигнала"
WAIT_CONFIRM_ONE     = "+ 1 точка"
WAIT_CONFIRM_TWO     = "+ 2 точки"
WAIT_CONFIRM_CANCEL  = "Отказ - продължи"
WAIT_CONFIRM_PICK    = "Грешен играч? Избери кой наистина отговори:"

WAIT_ADVANCE_HEADING = "Край на рунда"
WAIT_ADVANCE_NEXT    = "Към класацията"

# End-of-game podium screen.
WINNER_TITLE       = "Победител!"
WINNER_SUBTITLE    = "Играч {n} печели с {s} точки"
WINNER_BACK_BUTTON = "Към менюто"

TILE_OK = "ОК"
COUNTDOWN_GO = "ТРЪГНИ!"
VOLUME_HUD = "Звук {n}%"

# Search mode (after many failed reconnects) + run-at-startup toggle.
SEARCHING_TITLE = "Търсене на дистанционното"
SEARCHING_BODY = "Изключи се - приложението опитва автоматично."
STATUS_SEARCHING = "Търсене на дистанционното - свързване автоматично..."
STATUS_PILL_SEARCHING = "Търсене..."
AUTOSTART_ON = "Автостарт: ВКЛ"
AUTOSTART_OFF = "Автостарт: ИЗКЛ"
AUTOSTART_UNAVAILABLE = "Автостартът изисква Windows"

FB_FALLBACK_BUTTON = "Бутон {n}"

# Same indices as esp32_connector; Bulgarian labels for the GUI.
BUTTON_NAMES = {
    1: "Отметка",
    2: "Двойна отметка",
    3: "Нумпад 10",
    4: "Нумпад 9",
    5: "Нумпад 6",
    6: "Нумпад 3",
    7: "Нумпад 2",
    8: "Нумпад 5",
    9: "Нумпад 1",
    10: "Нумпад 4",
    11: "Нумпад 7",
    12: "Нумпад 8",
}


def players_phrase(n: int) -> str:
    if n == 1:
        return "1 играч - да играем!"
    return f"{n} играчи - да играем!"


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
