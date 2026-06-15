"""Run-at-startup toggle, cross-platform.

* Windows: per-user ``HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run``
  key (no admin needed).
* Linux (Raspberry Pi OS): an XDG autostart ``.desktop`` file in
  ``~/.config/autostart`` so the app launches in the user's desktop session at
  login. Combine with desktop auto-login (``raspi-config``) for boot-to-game.

When frozen (PyInstaller) the registered command is the executable itself;
otherwise it launches ``app.py`` with the current interpreter.
"""

from __future__ import annotations

import sys
from pathlib import Path

_VALUE_NAME = "LabcoinRemote"
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_DESKTOP_FILE = Path.home() / ".config" / "autostart" / "labcoin-remote.desktop"


def _is_windows() -> bool:
    return sys.platform == "win32"


def _is_linux() -> bool:
    return sys.platform.startswith("linux")


# ---------------------------------------------------------------- Windows

def _winreg():
    if not _is_windows():
        return None
    try:
        import winreg  # type: ignore
    except Exception:  # pragma: no cover
        return None
    return winreg


def _win_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}"'
    script = Path(__file__).resolve().parent / "app.py"
    pyexe = Path(sys.executable)
    pyw = pyexe.with_name("pythonw.exe")
    runner = pyw if pyw.exists() else pyexe
    return f'"{runner}" "{script}"'


def _win_is_enabled() -> bool:
    wr = _winreg()
    if wr is None:
        return False
    try:
        with wr.OpenKey(wr.HKEY_CURRENT_USER, _RUN_KEY) as key:
            value, _ = wr.QueryValueEx(key, _VALUE_NAME)
            return bool(value)
    except (FileNotFoundError, OSError):
        return False


def _win_enable() -> bool:
    wr = _winreg()
    if wr is None:
        return False
    try:
        with wr.CreateKey(wr.HKEY_CURRENT_USER, _RUN_KEY) as key:
            wr.SetValueEx(key, _VALUE_NAME, 0, wr.REG_SZ, _win_command())
        return True
    except OSError:
        return False


def _win_disable() -> bool:
    wr = _winreg()
    if wr is None:
        return False
    try:
        with wr.OpenKey(wr.HKEY_CURRENT_USER, _RUN_KEY, 0, wr.KEY_SET_VALUE) as key:
            wr.DeleteValue(key, _VALUE_NAME)
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


# ---------------------------------------------------------------- Linux

def _linux_command() -> str:
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).resolve())
    script = Path(__file__).resolve().parent / "app.py"
    return f'"{Path(sys.executable).resolve()}" "{script}"'


def _linux_is_enabled() -> bool:
    return _DESKTOP_FILE.is_file()


def _linux_enable() -> bool:
    try:
        _DESKTOP_FILE.parent.mkdir(parents=True, exist_ok=True)
        _DESKTOP_FILE.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Labcoin Remote\n"
            f"Exec={_linux_command()}\n"
            "Terminal=false\n"
            "X-GNOME-Autostart-enabled=true\n",
            encoding="utf-8",
        )
        return True
    except OSError:
        return False


def _linux_disable() -> bool:
    try:
        _DESKTOP_FILE.unlink()
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


# ---------------------------------------------------------------- public API

def is_supported() -> bool:
    if _is_windows():
        return _winreg() is not None
    return _is_linux()


def is_enabled() -> bool:
    if _is_windows():
        return _win_is_enabled()
    if _is_linux():
        return _linux_is_enabled()
    return False


def enable() -> bool:
    if _is_windows():
        return _win_enable()
    if _is_linux():
        return _linux_enable()
    return False


def disable() -> bool:
    if _is_windows():
        return _win_disable()
    if _is_linux():
        return _linux_disable()
    return False


def toggle() -> bool:
    """Flip the start-at-login state. Returns the new enabled state."""
    if is_enabled():
        disable()
        return False
    enable()
    return True
