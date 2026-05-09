# PRESENT — Top 200 Songs Clip Builder

Maintains a local library of 200 well-known songs from the last 24 months
(40% Bulgarian, 60% global mainstream) and produces four 5-second M4A clips
per song from positions evenly spaced across the middle of the track
(skipping the first and last 15 seconds).

Runs on Raspberry Pi OS or Windows. No API keys required — uses `yt-dlp`
plus public chart pages.

## Install

```bash
# Pi / Linux
sudo apt update && sudo apt install -y python3-venv ffmpeg
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Windows (PowerShell)
# Install ffmpeg via https://ffmpeg.org and ensure it is on PATH.
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Build the initial library

```bash
python -m present init
```

Expected output: ~200 folders under `data/songs/` with four `clip_*.m4a`
files plus `metadata.json` per folder, and a master `data/index.json`.

## Manage from the CLI

```bash
python -m present list
python -m present add "Artist Name" "Song Title" --origin bg
python -m present remove <song_id>
python -m present refresh
```

## Run the web service

```bash
python -m present serve --host 0.0.0.0 --port 8080
```

Open `http://<pi-ip>:8080`. Set `PRESENT_TOKEN=...` in the environment to
require an `X-Auth-Token` header on `POST` / `DELETE` operations.

### Cloudflare Tunnel

Bind the tunnel to `localhost:8080`. The `GET /` library view is publicly
readable; mutations require the auth token (set `PRESENT_TOKEN` in `.env`).

## systemd (Raspberry Pi auto-start)

```bash
sudo cp deploy/present.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now present
```

Edit the service file paths if your install lives somewhere other than
`/home/pi/PRESENT`.

## Layout

```
present/        # Python package (cli, server, charts, youtube, clipper, storage, pipeline, jobs)
data/
  index.json    # master list
  songs/<Artist_-_Title>/
    metadata.json
    clip_1.m4a
    clip_2.m4a
    clip_3.m4a
    clip_4.m4a
seed_songs.json # fallback list when chart scraping fails
deploy/         # systemd unit
```
