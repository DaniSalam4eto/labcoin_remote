"""Small persistent config for the desktop app (per-user JSON file).

Stores whether first-run setup has been completed (so later launches auto-connect
and skip the setup screens) and whether the run-at-startup default has been
applied. Lives in ``%APPDATA%/LabcoinRemote/config.json`` on Windows.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_DEFAULTS: dict = {
    # First launch has applied the run-at-startup default (so we don't keep
    # re-enabling it after the user turns it off with Ctrl+O).
    "autostart_initialized": False,
    # User has connected + passed the button check at least once. After that,
    # launches auto-connect and skip straight into the game.
    "setup_completed": False,
}


def _config_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home())
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "LabcoinRemote"


_CONFIG_PATH = _config_dir() / "config.json"


def load() -> dict:
    """Return the saved config merged over defaults (never raises)."""
    out = dict(_DEFAULTS)
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            out.update(data)
    except (OSError, ValueError):
        pass
    return out


def save(cfg: dict) -> bool:
    """Persist ``cfg`` atomically. Returns True on success, False on any error."""
    try:
        _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CONFIG_PATH.with_name(_CONFIG_PATH.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
        os.replace(tmp, _CONFIG_PATH)
        return True
    except OSError:
        return False
