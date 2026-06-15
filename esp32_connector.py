"""Background ESP32 link for the Labcoin Music Remote GUI.

The GUI thread does not talk BLE / sockets directly. It owns one
`Esp32Connector`, calls `start()` once, and polls `poll_events()` each frame
to drain status updates and remote button presses produced on the worker
thread.

Connection lifecycle (mirrors `ESP32_folder/send_song.py`):

    1.  Scan for the BLE peripheral named "OLED-Music".
    2.  Write "SSID|PASSWORD" to the Wi-Fi characteristic.
    3.  Wait for the ESP to notify back "IP:<addr>:<port>" (or "ERR:...").
    4.  Open a TCP socket to that address. Forward "BTN:<n>" lines to the
        GUI as button events; echo a friendly label back so the OLED shows
        which physical key was pressed.

If the link drops at any point, the worker waits 15 s and tries again,
forever, until `stop()` is called.
"""

from __future__ import annotations

import asyncio
import queue
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import Optional

try:
    from bleak import BleakClient, BleakScanner  # type: ignore
    HAVE_BLEAK = True
except Exception:  # pragma: no cover - missing optional dep
    BleakClient = None  # type: ignore[assignment]
    BleakScanner = None  # type: ignore[assignment]
    HAVE_BLEAK = False


BLE_DEVICE_NAME = "OLED-Music"
BLE_CHAR_WIFI = "7a9e0b91-2d6e-4a7f-9e3c-5a0f64c2e011"
TCP_PORT = 3333
WIFI_NEG_TIMEOUT_S = 30.0

# Auto-reconnect, no human input. We hammer the link fast for the first
# SEARCH_MODE_AFTER consecutive failures, then ease into a slower "search mode"
# that runs forever until the remote shows up again. A short BLE scan (it
# returns instantly once the device is seen) lets failed tries cycle quickly so
# we can hit the target attempt rates.
FAST_ATTEMPTS_PER_MIN = 15
SEARCH_ATTEMPTS_PER_MIN = 5
SEARCH_MODE_AFTER = 30
BLE_SCAN_TIMEOUT_S = 3.0
# A session must stay up at least this long to count as a real connection; a
# connect-then-instantly-drop loop keeps counting as failures so search mode is
# still reached.
MIN_SESSION_S = 3.0

# Button index -> friendly name. Same mapping as send_song.py so the OLED
# echo screen stays consistent across both tools.
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

# Numpad-style buttons exposed to game logic. (button index -> digit 1..10).
# Digit 10 is treated as "0" / ten players in the player picker.
NUMPAD_BUTTONS = {
    9: 1,    # Numpad 1
    7: 2,    # Numpad 2
    6: 3,    # Numpad 3
    10: 4,   # Numpad 4
    8: 5,    # Numpad 5
    5: 6,    # Numpad 6
    11: 7,   # Numpad 7
    12: 8,   # Numpad 8
    4: 9,    # Numpad 9
    3: 10,   # Numpad 10
}


@dataclass
class Event:
    """Anything the worker thread wants the GUI to know about."""

    kind: str           # "status" | "error" | "connected" | "button" | "disconnected" | "volume"
    text: str = ""
    button: Optional[int] = None
    digit: Optional[int] = None  # populated for button events that map to a numpad digit
    volume: Optional[float] = None  # 0.0..1.0, populated for "volume" events


def _sanitize_field(value: str) -> str:
    """Strip the protocol's reserved characters from a user-supplied field.

    ``|`` separates fields and ``\\n`` terminates a message in the
    ESP32's wire format, so both are replaced.
    """

    return (
        str(value or "")
        .replace("|", "/")
        .replace("\r", " ")
        .replace("\n", " ")
        .strip()
    )


def _run(args: list[str]) -> str:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, check=False, timeout=8)
    except Exception:
        return ""
    return proc.stdout if proc.returncode == 0 else ""


def _parse_iface_field(text: str, key_name: str) -> str:
    target = key_name.strip().lower()
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key.strip().lower() == target:
            return value.strip()
    return ""


def _parse_ssid(text: str) -> str:
    for line in text.splitlines():
        if "SSID" not in line or "BSSID" in line:
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key.strip().upper().startswith("SSID"):
            return value.strip()
    return ""


@dataclass
class WifiInfo:
    ssid: str
    password: str
    band_ghz: float  # 0.0 = unknown, 2.4, or 5.0
    channel: int     # 0 = unknown
    radio_type: str


def detect_windows_wifi() -> WifiInfo:
    """Return the active Wi-Fi profile + estimated band from `netsh`."""
    iface = _run(["netsh", "wlan", "show", "interfaces"])
    ssid = _parse_ssid(iface)
    radio = _parse_iface_field(iface, "Radio type")
    channel_text = _parse_iface_field(iface, "Channel")
    try:
        channel = int(channel_text)
    except ValueError:
        channel = 0
    if 1 <= channel <= 14:
        band = 2.4
    elif channel >= 32:
        band = 5.0
    else:
        band = 0.0
    password = ""
    if ssid:
        prof = _run(["netsh", "wlan", "show", "profile", f"name={ssid}", "key=clear"])
        for line in prof.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            if key.strip().lower() == "key content":
                password = value.strip()
                break
    return WifiInfo(ssid=ssid, password=password, band_ghz=band, channel=channel, radio_type=radio)


def _band_from_channel(channel: int) -> float:
    if 1 <= channel <= 14:
        return 2.4
    if channel >= 32:
        return 5.0
    return 0.0


def _nmcli_active_field(field: str) -> str:
    """Return ``field`` for the currently-active Wi-Fi network from nmcli."""
    out = _run(["nmcli", "-t", "-f", f"ACTIVE,{field}", "dev", "wifi"])
    for line in out.splitlines():
        if line.startswith("yes:"):
            return line[4:].strip()
    return ""


def detect_linux_wifi() -> WifiInfo:
    """Active Wi-Fi profile on Linux (Raspberry Pi OS), via NetworkManager.

    SSID + channel come from ``nmcli``; the saved PSK is read with
    ``nmcli -s`` (works for the active desktop user; may need elevated rights
    on a headless setup — fall back to a manual override in that case).
    """
    ssid = _nmcli_active_field("SSID")
    if not ssid:
        ssid = _run(["iwgetid", "-r"]).strip()
    try:
        channel = int(_nmcli_active_field("CHAN") or "0")
    except ValueError:
        channel = 0
    password = ""
    if ssid:
        password = _run([
            "nmcli", "-s", "-g", "802-11-wireless-security.psk",
            "connection", "show", ssid,
        ]).strip()
    return WifiInfo(ssid=ssid, password=password,
                    band_ghz=_band_from_channel(channel),
                    channel=channel, radio_type="")


def detect_wifi() -> WifiInfo:
    """Active Wi-Fi profile for the current OS (Windows or Linux/Raspberry Pi)."""
    if sys.platform == "win32":
        return detect_windows_wifi()
    if sys.platform.startswith("linux"):
        return detect_linux_wifi()
    return WifiInfo(ssid="", password="", band_ghz=0.0, channel=0, radio_type="")


class Esp32Connector:
    """Owns the BLE+TCP worker. GUI calls `start()` then polls events each frame."""

    def __init__(self) -> None:
        self._events: "queue.Queue[Event]" = queue.Queue()
        self._stop = threading.Event()
        self._reconnect_now = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._tcp_lock = threading.Lock()
        self._tcp_sock: Optional[socket.socket] = None
        self._connected = False
        self._session_connected_at: Optional[float] = None
        # Optional manual Wi-Fi creds (used instead of OS auto-detect when set —
        # e.g. on a headless Pi where the PSK can't be read automatically).
        self._wifi_override: Optional[WifiInfo] = None

    # ---- public API used by the GUI ---------------------------------------

    @property
    def connected(self) -> bool:
        return self._connected

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="esp32-link")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._reconnect_now.set()
        with self._tcp_lock:
            sock = self._tcp_sock
            self._tcp_sock = None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        if self._thread:
            self._thread.join(timeout=2.0)

    def request_immediate_reconnect(self) -> None:
        self._reconnect_now.set()

    def set_wifi_credentials(self, ssid: str, password: str) -> None:
        """Override OS Wi-Fi auto-detection with explicit creds (or clear it).

        Pass an empty ``ssid`` to go back to auto-detecting. Useful on a
        headless Pi where the saved password can't be read without elevation.
        """
        if ssid:
            self._wifi_override = WifiInfo(
                ssid=ssid, password=password or "",
                band_ghz=0.0, channel=0, radio_type="manual")
        else:
            self._wifi_override = None

    def _send_line(self, line: bytes) -> bool:
        """Write one already-encoded line to the OLED. No-op when offline."""

        with self._tcp_lock:
            sock = self._tcp_sock
        if sock is None:
            return False
        try:
            sock.sendall(line)
            return True
        except OSError:
            return False

    def send_song(self, artist: str, title: str, hold_ms: int = 0) -> bool:
        """Push the now-playing panel to the OLED. No-op when offline.

        Sends ``SONG|artist|title|hold_ms`` (see the firmware protocol). The
        panel stays on the remote until the host pushes the next command, so it
        lasts as long as the clip actually plays. ``hold_ms`` (the real clip
        length) drives the countdown bar; ``0`` shows the panel with no bar.
        Returns ``True`` on a successful write.
        """

        artist_clean = _sanitize_field(artist) or "—"
        title_clean = _sanitize_field(title) or "—"
        hold = max(0, int(hold_ms))
        line = f"SONG|{artist_clean}|{title_clean}|{hold}\n".encode("utf-8")
        return self._send_line(line)

    def send_top3(self, rows: list[tuple[str, int]]) -> bool:
        """Push a Top-3 leaderboard (``RANK|label:score|...``) to the OLED.

        ``rows`` is ``(label, score)`` already sorted best-first; only the first
        three are shown. No-op when offline.
        """

        parts = ["RANK"]
        for label, score in rows[:3]:
            lab = _sanitize_field(label).replace(":", " ") or "?"
            parts.append(f"{lab}:{int(score)}")
        line = ("|".join(parts) + "\n").encode("utf-8")
        return self._send_line(line)

    def send_countdown(self, text: str) -> bool:
        """Push one big countdown glyph (``CD|text``) to the OLED, e.g. "3" or
        "GO!". Mirrors the PC's pre-round countdown. No-op when offline."""

        glyph = _sanitize_field(text) or "?"
        return self._send_line(f"CD|{glyph}\n".encode("utf-8"))

    def send_idle(self) -> bool:
        """Return the OLED to its idle logo (``IDLE``). No-op when offline."""

        return self._send_line(b"IDLE\n")

    def send_reset(self) -> bool:
        """Reboot the remote over the network (``RESET``) — same effect as its
        physical RESET button. Returns ``True`` if the command was sent (the
        link then drops while the ESP restarts). No-op when offline."""

        return self._send_line(b"RESET\n")

    def poll_events(self) -> list[Event]:
        out: list[Event] = []
        while True:
            try:
                out.append(self._events.get_nowait())
            except queue.Empty:
                break
        return out

    # ---- worker -----------------------------------------------------------

    def _emit(self, kind: str, text: str = "", button: Optional[int] = None,
              digit: Optional[int] = None, volume: Optional[float] = None) -> None:
        self._events.put(
            Event(kind=kind, text=text, button=button, digit=digit, volume=volume)
        )

    def _run_loop(self) -> None:
        if not HAVE_BLEAK:
            self._emit("error", "Python package 'bleak' is not installed.")
            return
        fail_count = 0
        while not self._stop.is_set():
            attempt_started = time.monotonic()
            self._reconnect_now.clear()
            self._session_connected_at = None
            try:
                asyncio.run(self._one_cycle())
                # _one_cycle returns once a session ended. Only count it as a
                # real success if the link actually stayed up — a connect-then-
                # instantly-drop loop must still escalate to search mode.
                started = self._session_connected_at
                if started is not None and (time.monotonic() - started) >= MIN_SESSION_S:
                    fail_count = 0
                else:
                    fail_count += 1
            except Exception as exc:  # noqa: BLE001
                self._emit("error", f"Connection error: {exc}")
                fail_count += 1
            self._connected = False
            self._emit("disconnected")
            if self._stop.is_set():
                break
            # Pace the next attempt to the target rate for the current mode, and
            # surface the search screen in lock-step with the slower rate.
            in_search = fail_count >= SEARCH_MODE_AFTER
            if in_search:
                self._emit("searching", text=str(fail_count))
            rate = SEARCH_ATTEMPTS_PER_MIN if in_search else FAST_ATTEMPTS_PER_MIN
            interval = 60.0 / float(max(1, rate))
            deadline = attempt_started + interval
            while not self._stop.is_set() and time.monotonic() < deadline:
                if self._reconnect_now.is_set():
                    self._reconnect_now.clear()
                    break
                time.sleep(0.1)

    async def _one_cycle(self) -> None:
        self._emit("status", "Reading Wi-Fi profile...")
        wifi = self._wifi_override or detect_wifi()
        if not wifi.ssid:
            raise RuntimeError("No active Wi-Fi connection on this PC.")
        if wifi.band_ghz == 5.0:
            self._emit("error", f"NET5GHZ:{wifi.ssid}:ch{wifi.channel}")
            raise RuntimeError("Need 2.4 GHz")

        self._emit("status", f"Scanning BLE for '{BLE_DEVICE_NAME}'...")
        device = await BleakScanner.find_device_by_name(  # type: ignore[union-attr]
            BLE_DEVICE_NAME, timeout=BLE_SCAN_TIMEOUT_S
        )
        if device is None:
            self._emit("error", "OUTOFRANGE")
            raise RuntimeError("Remote not in range.")

        self._emit("status", f"BLE found {device.address}, pairing...")
        result: dict[str, Optional[str]] = {"ip": None, "err": None}
        ready = asyncio.Event()

        def on_notify(_h: int, data: bytearray) -> None:
            msg = bytes(data).decode(errors="ignore").strip()
            if msg.startswith("IP:"):
                result["ip"] = msg[3:]
                ready.set()
            elif msg.startswith("ERR:"):
                result["err"] = msg
                ready.set()

        async with BleakClient(device) as client:  # type: ignore[union-attr]
            await client.start_notify(BLE_CHAR_WIFI, on_notify)
            payload = f"{wifi.ssid}|{wifi.password}".encode("utf-8")
            self._emit("status", f"Sending Wi-Fi creds for '{wifi.ssid}'...")
            await client.write_gatt_char(BLE_CHAR_WIFI, payload, response=True)
            try:
                await asyncio.wait_for(ready.wait(), timeout=WIFI_NEG_TIMEOUT_S)
            except asyncio.TimeoutError as exc:
                raise RuntimeError("ESP did not report Wi-Fi join in time.") from exc
            try:
                await client.stop_notify(BLE_CHAR_WIFI)
            except Exception:  # noqa: BLE001
                pass

        if result["err"]:
            raise RuntimeError(f"ESP error: {result['err']}")
        if not result["ip"]:
            raise RuntimeError("ESP did not return an IP.")

        host, _, port_str = result["ip"].partition(":")
        port = int(port_str) if port_str else TCP_PORT
        self._emit("status", f"Opening TCP {host}:{port}...")
        sock = socket.create_connection((host, port), timeout=10)
        sock.settimeout(None)
        with self._tcp_lock:
            self._tcp_sock = sock
        self._connected = True
        self._session_connected_at = time.monotonic()
        self._emit("connected", f"{host}:{port}")
        try:
            self._reader_loop(sock)
        finally:
            with self._tcp_lock:
                if self._tcp_sock is sock:
                    self._tcp_sock = None
            try:
                sock.close()
            except OSError:
                pass

    def _reader_loop(self, sock: socket.socket) -> None:
        buf = b""
        while not self._stop.is_set():
            try:
                chunk = sock.recv(256)
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while b"\n" in buf:
                line, _, buf = buf.partition(b"\n")
                text = line.decode(errors="ignore").strip()
                if not text:
                    continue
                self._dispatch(text, sock)

    def _dispatch(self, text: str, sock: socket.socket) -> None:
        # Volume knob updates from the ESP potentiometer (0..100 -> 0.0..1.0).
        if text.startswith("VOL:"):
            try:
                level = int(text[4:].strip())
            except ValueError:
                return
            level = max(0, min(100, level))
            self._emit("volume", volume=level / 100.0)
            return

        num_text = ""
        if text.startswith("BTN:"):
            num_text = text[4:].strip()
        elif text.startswith("DBG:"):
            payload = text[4:].strip()
            if payload.upper().startswith("BTN:"):
                num_text = payload[4:].strip()
        if not num_text:
            return
        try:
            num = int(num_text)
        except ValueError:
            return
        digit = NUMPAD_BUTTONS.get(num)
        self._emit("button", text=BUTTON_NAMES.get(num, f"Бутон {num}"),
                   button=num, digit=digit)
        # Note: we intentionally do NOT echo the button name back to the OLED.
        # That used to flash a "<button>|pressed" panel on every press; the
        # remote now stays on the song / leaderboard the host pushed.
