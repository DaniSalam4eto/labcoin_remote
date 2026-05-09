# Labcoin Music Remote

Cartoon-doodle desktop companion for the Labcoin Music ESP32 remote.

It boots into a small beige window with floating colored music notes,
finds the remote over BLE, hands off Wi-Fi credentials, opens a TCP
socket, walks the user through a button check, then jumps into a
fullscreen game menu driven by the remote's number pad.

## Layout

```
.
├── app.py              # Pygame UI + state machine for every screen
├── doodle.py           # Beige theme, doodle drawing helpers, floating notes
├── esp32_connector.py  # Background BLE + Wi-Fi + TCP link to the remote
├── requirements.txt
├── ESP32_folder/       # Original ESP32 firmware + bring-up companion
│   ├── oled_music_logo.ino
│   ├── note_v3.h
│   ├── qr_manual_bitmap.h
│   └── send_song.py
└── logos/              # Game logo + music-note PNGs used by the UI
```

## Install

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run

```powershell
python app.py
```

`F11` toggles fullscreen, `Esc` quits. The number-pad keys on your
keyboard mirror the remote's number pad so screens past the button
check are testable without the hardware.

## Flow

1. **Setup** screen — START button, music notes drift up either edge.
2. **Loading** — scans for BLE peripheral `OLED-Music`.
3. One of:
   * **Wrong band** — your PC is on 5 GHz Wi-Fi. Switch and reload.
   * **Out of range** — remote not found. Auto-retry every 15 s.
   * **Connected** — remote bobs gently in a doodle illustration.
4. **Button check** — sequentially prompts each remote button; each
   tile turns green once pressed.
5. **Main menu** (fullscreen) — game logo center, "press the number of
   players" prompt at the bottom.
6. **Round picker** — same numpad input picks rounds.
7. **Countdown** — 10 → GO! → game placeholder.

## Auto-reconnect

If the remote drops at any point, `Esp32Connector` waits 15 seconds
and runs the whole BLE → Wi-Fi → TCP handshake again. Calling RELOAD
on either error screen short-circuits that delay.

## Building a Windows .exe (later)

```powershell
pip install pyinstaller
pyinstaller --noconfirm --windowed --name LabcoinMusicRemote ^
            --add-data "logos;logos" app.py
```

The `logos/` folder must ship next to the binary; `app.py` resolves it
relative to its own location.
