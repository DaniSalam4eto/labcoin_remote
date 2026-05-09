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
RECONNECT_DELAY_S = 15.0
BLE_SCAN_TIMEOUT_S = 12.0
WIFI_NEG_TIMEOUT_S = 30.0

# Button index -> friendly name. Same mapping as send_song.py so the OLED
# echo screen stays consistent across both tools.
BUTTON_NAMES = {
    1: "Checkmark",
    2: "Double checkmark",
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

    kind: str           # "status" | "error" | "connected" | "button" | "disconnected"
    text: str = ""
    button: Optional[int] = None
    digit: Optional[int] = None  # populated for button events that map to a numpad digit


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
              digit: Optional[int] = None) -> None:
        self._events.put(Event(kind=kind, text=text, button=button, digit=digit))

    def _run_loop(self) -> None:
        if not HAVE_BLEAK:
            self._emit("error", "Python package 'bleak' is not installed.")
            return
        backoff_until = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            if now < backoff_until and not self._reconnect_now.is_set():
                time.sleep(0.2)
                continue
            self._reconnect_now.clear()
            try:
                asyncio.run(self._one_cycle())
            except Exception as exc:  # noqa: BLE001
                self._emit("error", f"Connection error: {exc}")
            self._connected = False
            self._emit("disconnected")
            backoff_until = time.monotonic() + RECONNECT_DELAY_S

    async def _one_cycle(self) -> None:
        self._emit("status", "Reading Wi-Fi profile...")
        wifi = detect_windows_wifi()
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
        self._emit("button", text=BUTTON_NAMES.get(num, f"Button {num}"),
                   button=num, digit=digit)

        # Echo a friendly name back to the OLED (matches send_song.py behavior).
        name = BUTTON_NAMES.get(num, f"Button {num}")
        try:
            sock.sendall(f"{name}|pressed\n".encode("utf-8"))
        except OSError:
            pass
