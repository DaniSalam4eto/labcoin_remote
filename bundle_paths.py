"""Locate the app install / repo root (development vs PyInstaller frozen build)."""

from __future__ import annotations

import sys
from pathlib import Path


def app_base_dir() -> Path:
    """Directory holding the bundled ``data``/``fonts``/``logos``.

    In dev that's the folder with ``app.py``. When frozen we look next to the
    ``.exe`` first (so data dropped beside it wins), then fall back to
    PyInstaller's bundle dir ``sys._MEIPASS`` — which is where ``LabcoinRemote.spec``
    actually lands the data in a PyInstaller 6.x onedir build (``_internal``).
    """

    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        meipass = getattr(sys, "_MEIPASS", None)
        if (exe_dir / "data").exists() or not meipass:
            return exe_dir
        return Path(meipass)
    return Path(__file__).resolve().parent
