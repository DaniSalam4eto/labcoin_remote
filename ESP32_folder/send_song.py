"""
Companion script for oled_music_logo.ino.

Flow:
  1. You provide a Wi-Fi SSID + password (flags or interactive prompts).
  2. The script scans for a BLE device named "OLED-Music", connects, and
     writes "SSID|PASSWORD" to its Wi-Fi characteristic.
  3. The ESP32 joins your Wi-Fi and notifies its IP back as "IP:<addr>:<port>".
  4. The script opens a TCP socket to that address and drops into a prompt
     loop: type a singer name, then a song name, and it sends the pair to
     the ESP. Button presses from the ESP are also mapped to names and sent
     back to the OLED so the pressed button name appears for 10 s.

  During GPIO discovery firmware builds, the ESP may also send TCP lines
  prefixed with "DBG:" (for example the list of GPIOs being scanned, or
  which GPIO went low on a button press). This script prints those as
  "[dbg] ..." so you can map physical switches without opening Serial Monitor.

Install:
  pip install bleak

Run:
  python send_song.py
  python send_song.py --ssid MyNet --password secret
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import re
import socket
import subprocess
import sys
import threading

from bleak import BleakClient, BleakScanner

BLE_DEVICE_NAME = "OLED-Music"
BLE_CHAR_WIFI   = "7a9e0b91-2d6e-4a7f-9e3c-5a0f64c2e011"
TCP_PORT        = 3333

# Logical button index (1..N) -> GPIO on your wired remote, from the discovery
# session (GPIO35 omitted — input-only / needs external pull-up on ESP32).
GPIO_BY_BUTTON = [
    27, 2, 5, 17, 16, 4, 32, 18, 26, 25, 33, 13,
]
BUTTON_BY_GPIO = {g: i + 1 for i, g in enumerate(GPIO_BY_BUTTON)}

# Labels when ESP sends BTN:<n>. Numpad keys are ordered by your physical layout:
# 1st press (excluding checkmarks) → Numpad 1 … 10th → Numpad 10 (see remap note below).
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


def run_command(args: list[str]) -> str:
    proc = subprocess.run(args, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return ""
    return proc.stdout or ""


def parse_ssid_from_netsh(text: str) -> str:
    for line in text.splitlines():
        if "SSID" not in line or "BSSID" in line:
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key.strip().upper().startswith("SSID"):
            ssid = value.strip()
            if ssid:
                return ssid
    return ""


def parse_key_from_profile(text: str) -> str:
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key.strip().lower() == "key content":
            return value.strip()
    return ""


def detect_windows_wifi() -> tuple[str, str]:
    # Read active SSID and saved password from Windows Wi-Fi profiles.
    iface_out = run_command(["netsh", "wlan", "show", "interfaces"])
    ssid = parse_ssid_from_netsh(iface_out)
    if not ssid:
        return "", ""
    profile_out = run_command(["netsh", "wlan", "show", "profile", f"name={ssid}", "key=clear"])
    password = parse_key_from_profile(profile_out)
    return ssid, password


async def pair_and_get_ip(ssid: str, password: str) -> str:
    print(f"Scanning for BLE device '{BLE_DEVICE_NAME}'...")
    device = await BleakScanner.find_device_by_name(BLE_DEVICE_NAME, timeout=15.0)
    if device is None:
        raise RuntimeError(
            f"BLE device '{BLE_DEVICE_NAME}' not found. "
            "Is the ESP32 powered on and running the sketch?"
        )
    print(f"Found {device.address}. Connecting...")

    result: dict[str, str | None] = {"ip": None, "err": None}
    ready = asyncio.Event()

    def on_notify(_handle: int, data: bytearray) -> None:
        msg = bytes(data).decode(errors="ignore").strip()
        print(f"  ESP -> {msg}")
        if msg.startswith("IP:"):
            result["ip"] = msg[len("IP:"):]
            ready.set()
        elif msg.startswith("ERR:"):
            result["err"] = msg
            ready.set()

    async with BleakClient(device) as client:
        await client.start_notify(BLE_CHAR_WIFI, on_notify)
        payload = f"{ssid}|{password}".encode("utf-8")
        print("Sending Wi-Fi credentials over BLE...")
        await client.write_gatt_char(BLE_CHAR_WIFI, payload, response=True)
        try:
            await asyncio.wait_for(ready.wait(), timeout=25.0)
        except asyncio.TimeoutError:
            raise RuntimeError("ESP32 did not report a Wi-Fi connection in time.")
        await client.stop_notify(BLE_CHAR_WIFI)

    if result["err"]:
        err = result["err"]
        hints = {
            "ERR:wifi:1": "SSID not in range (WL_NO_SSID_AVAIL). Is the ESP near the 2.4GHz AP?",
            "ERR:wifi:4": "auth failed (WL_CONNECT_FAILED). Wrong password.",
            "ERR:wifi:6": "disconnected (WL_DISCONNECTED). Usually wrong password or flaky AP.",
        }
        hint = ""
        for k, v in hints.items():
            if err.startswith(k):
                hint = " — " + v
                break
        raise RuntimeError(f"ESP32 reported error: {err}{hint}")
    if not result["ip"]:
        raise RuntimeError("ESP32 did not return an IP.")
    return result["ip"]


def sanitize(value: str) -> str:
    # '|' is the field separator, '\n' ends the message. Replace both.
    return value.replace("|", "/").replace("\r", " ").replace("\n", " ").strip()


def button_name(num_text: str) -> tuple[int | None, str]:
    try:
        num = int(num_text)
    except ValueError:
        return None, f"Бутон {num_text}"
    return num, BUTTON_NAMES.get(num, f"Бутон {num}")


def send_button_name(sock: socket.socket, num_text: str) -> None:
    num, name = button_name(num_text)
    display_name = sanitize(name) or (f"Бутон {num}" if num is not None else "Бутон")
    line = f"{display_name}|pressed\n".encode("utf-8")
    try:
        sock.sendall(line)
    except OSError as e:
        print(f"\n[button {num_text} pressed: {display_name}; send failed: {e}]")
        return
    print(f"\n[button {num_text} pressed: {display_name}]")


def reader_loop(sock: socket.socket, stop: threading.Event) -> None:
    # Print incoming lines from the ESP32:
    #   - Normal mode: "BTN:<n>" for mapped logical buttons
    #   - Discovery mode: "DBG:..." for GPIO scan lists / raw GPIO edges
    buf = b""
    while not stop.is_set():
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
            if text.startswith("BTN:"):
                num = text[4:].strip()
                send_button_name(sock, num)
            elif text.startswith("DBG:"):
                payload = text[4:].strip()
                if payload.upper().startswith("SCANNING GPIOS:"):
                    pins = payload.split(":", 1)[1].strip()
                    print(f"\n[dbg] scanning GPIOs: {pins}")
                elif payload.upper().startswith("BTN:"):
                    num = payload[4:].strip()
                    send_button_name(sock, num)
                elif m := re.search(r"\bGPIO(\d+)\b", payload, flags=re.IGNORECASE):
                    gpio = int(m.group(1))
                    btn = BUTTON_BY_GPIO.get(gpio)
                    if btn is not None:
                        rest = payload[m.end() :].strip()
                        if rest:
                            print(f"\n[dbg] button {btn} — {rest}")
                        else:
                            print(f"\n[dbg] button {btn}")
                    else:
                        print(f"\n[dbg] {payload}")
                else:
                    print(f"\n[dbg] {payload}")
            else:
                print(f"\n[esp] {text}")
            sys.stdout.write("Singer: ")
            sys.stdout.flush()


def prompt_loop(ip_port: str) -> None:
    host, _, port_str = ip_port.partition(":")
    port = int(port_str) if port_str else TCP_PORT
    print(f"Connected to ESP at {host}:{port}. Ctrl-C to quit.\n")
    with socket.create_connection((host, port), timeout=10) as sock:
        sock.settimeout(None)
        stop = threading.Event()
        reader = threading.Thread(target=reader_loop, args=(sock, stop), daemon=True)
        reader.start()
        try:
            while True:
                try:
                    singer = sanitize(input("Singer: "))
                    if not singer:
                        continue
                    song = sanitize(input("Song:   "))
                    if not song:
                        continue
                except EOFError:
                    print()
                    return
                line = f"{singer}|{song}\n".encode("utf-8")
                sock.sendall(line)
                print(f"  -> sent ({len(line)} bytes)\n")
        finally:
            stop.set()


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Send Wi-Fi creds over BLE then song info over TCP "
                    "to the OLED music logo ESP32.",
    )
    ap.add_argument("--ssid", help="Wi-Fi SSID (auto-detect/prompt if omitted)")
    ap.add_argument("--password", help="Wi-Fi password (auto-detect/prompt if omitted)")
    args = ap.parse_args()

    auto_ssid, auto_password = detect_windows_wifi()
    if auto_ssid:
        print(f"Detected Wi-Fi SSID: {auto_ssid}")
        if auto_password:
            print("Detected Wi-Fi password from Windows profile.")
        else:
            print("Could not read Wi-Fi password from profile; will prompt.")

    ssid = args.ssid or auto_ssid or input("Wi-Fi SSID: ").strip()
    if not ssid:
        print("SSID is required.", file=sys.stderr)
        return 1
    password = args.password or auto_password
    if password is None:
        password = getpass.getpass("Wi-Fi password: ")

    try:
        ip_port = asyncio.run(pair_and_get_ip(ssid, password))
    except Exception as e:
        print(f"BLE / Wi-Fi setup failed: {e}", file=sys.stderr)
        return 1

    try:
        prompt_loop(ip_port)
    except KeyboardInterrupt:
        print("\nbye")
    except OSError as e:
        print(f"TCP error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
