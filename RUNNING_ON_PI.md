# Running Labcoin Remote on a Raspberry Pi

> **The Windows `.exe` does not run on a Raspberry Pi.** A `.exe` is a Windows
> program; the Pi runs Linux on an ARM chip, so double-clicking the `.exe` just
> asks you to "choose a command". On the Pi you run the app from its Python
> source instead (this folder), which now supports Linux.

## Quick start

Copy this whole project folder onto the Pi (USB stick, `git clone`, `scp`, …),
open a terminal in it, and run:

```bash
bash setup_pi.sh
```

That installs system packages (ffmpeg, BlueZ, SDL libs), creates a `.venv`,
installs the Python dependencies, and turns on auto-start at login.

Run it now:

```bash
./.venv/bin/python app.py
```

## Boot straight into the game (kiosk)

1. `sudo raspi-config` → **System Options** → **Boot / Auto Login** →
   **Desktop Autologin**.
2. Reboot.

The Pi logs into the desktop and the app auto-starts (via an XDG autostart entry
in `~/.config/autostart/labcoin-remote.desktop`). After the first connect +
button check, every boot goes straight into the game.

Toggle auto-start any time from inside the app with **Ctrl+O**.

## Wi-Fi password note (the one tricky bit)

The app reads the Pi's active Wi-Fi name + password and hands them to the remote
over BLE so the ESP can join the same network. It reads them with `nmcli`. In a
normal desktop session that works automatically. If it can't read the saved
password (headless box, permission denied), set it once:

```bash
nano ~/.config/LabcoinRemote/config.json
```

Fill in `"wifi_ssid"` and `"wifi_password"`, save, and restart the app. Those
take priority over auto-detection.

Remember: the ESP32 is **2.4 GHz only** — the Pi must be on a 2.4 GHz network
(the app warns you if it's on 5 GHz).

## Troubleshooting

- **No sound / clips don't play** — make sure `ffmpeg` is installed
  (`ffmpeg -version`) and the Pi's audio output is selected.
- **Remote never found over BLE** — Bluetooth must be on:
  `sudo systemctl enable --now bluetooth`, and the Pi must be reasonably close.
- **Window won't go fullscreen on Bookworm (Wayland)** — try running under X11,
  e.g. `SDL_VIDEODRIVER=x11 ./.venv/bin/python app.py`.
- **`pip` complains about an externally-managed environment** — that's why
  `setup_pi.sh` uses a `.venv`; always launch with `./.venv/bin/python app.py`.
