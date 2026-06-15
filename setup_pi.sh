#!/usr/bin/env bash
#
# One-shot setup for running Labcoin Remote on Raspberry Pi OS (the Pi becomes
# the game host the ESP32 remote connects to). Run from the repo root:
#
#     bash setup_pi.sh
#
# It installs system deps, creates a Python venv, installs the Python deps, and
# enables auto-start on desktop login.

set -e
cd "$(dirname "$0")"

echo "==> [1/5] System packages (ffmpeg, BlueZ, SDL/AVIF libs)..."
sudo apt-get update
sudo apt-get install -y \
    ffmpeg bluez python3-venv python3-pip \
    libsdl2-2.0-0 libsdl2-mixer-2.0-0 libsdl2-image-2.0-0 libavif-dev

echo "==> [2/5] Make sure Bluetooth is running (bleak needs BlueZ)..."
sudo systemctl enable --now bluetooth || true

echo "==> [3/5] Python virtual environment + dependencies..."
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
# pillow-avif-plugin is only for the .avif logo (it has a fallback), so don't
# let it fail the whole install on ARM.
./.venv/bin/python -m pip install -r requirements.txt \
    || ./.venv/bin/python -m pip install pygame bleak pillow yt-dlp flask

echo "==> [4/5] Enable auto-start on login..."
./.venv/bin/python -c "import autostart; print('   auto-start enabled:', autostart.enable())"

echo "==> [5/5] Done."
cat <<'EOF'

Run it now:
    ./.venv/bin/python app.py

Boot straight into the game (kiosk):
    sudo raspi-config  ->  System Options  ->  Boot / Auto Login
                       ->  "Desktop Autologin"
    then reboot. The app auto-starts on login.

If the remote never connects because the Wi-Fi password can't be read
automatically (headless / permission denied), set it once:
    nano ~/.config/LabcoinRemote/config.json
    # fill in "wifi_ssid" and "wifi_password", save, restart the app.

Toggle auto-start anytime from inside the app with Ctrl+O.
EOF
