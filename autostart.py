"""Run-at-startup toggle for Windows, via the per-user Run registry key.

Uses ``HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run`` so no admin
rights are needed. When the app is a frozen PyInstaller build the registered
command is the ``.exe`` itself; in development it launches ``app.py`` with
``pythonw`` so no console window flashes at boot.
"""

from __future__ import annotations

import sys
from pathlib import Path

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "LabcoinRemote"


def _winreg():
    """Return the ``winreg`` module, or ``None`` off Windows."""
    if sys.platform != "win32":
        return None
    try:
        import winreg  # type: ignore
    except Exception:  # pragma: no cover - non-Windows
        return None
    return winreg


def is_supported() -> bool:
    return _winreg() is not None


def _launch_command() -> str:
    """The command line to register so the app starts at login."""
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}"'
    # Development: run app.py with the windowless interpreter when available.
    script = Path(__file__).resolve().parent / "app.py"
    pyexe = Path(sys.executable)
    pyw = pyexe.with_name("pythonw.exe")
    runner = pyw if pyw.exists() else pyexe
    return f'"{runner}" "{script}"'


def is_enabled() -> bool:
    wr = _winreg()
    if wr is None:
        return False
    try:
        with wr.OpenKey(wr.HKEY_CURRENT_USER, _RUN_KEY) as key:
            value, _ = wr.QueryValueEx(key, _VALUE_NAME)
            return bool(value)
    except FileNotFoundError:
        return False
    except OSError:
        return False


def enable() -> bool:
    """Register the app to start at login. Returns True on success."""
    wr = _winreg()
    if wr is None:
        return False
    try:
        with wr.CreateKey(wr.HKEY_CURRENT_USER, _RUN_KEY) as key:
            wr.SetValueEx(key, _VALUE_NAME, 0, wr.REG_SZ, _launch_command())
        return True
    except OSError:
        return False


def disable() -> bool:
    """Remove the start-at-login entry. Returns True if it is now absent."""
    wr = _winreg()
    if wr is None:
        return False
    try:
        with wr.OpenKey(wr.HKEY_CURRENT_USER, _RUN_KEY, 0, wr.KEY_SET_VALUE) as key:
            wr.DeleteValue(key, _VALUE_NAME)
        return True
    except FileNotFoundError:
        return True  # already gone
    except OSError:
        return False


def toggle() -> bool:
    """Flip the start-at-login state. Returns the new enabled state."""
    if is_enabled():
        disable()
        return False
    enable()
    return True
