from __future__ import annotations

import logging
import msvcrt
import sys
import tempfile
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
LOCK_PATH = Path(tempfile.gettempdir()) / "grok-manager.lock"

_lock_fh = None


def acquire_instance_lock() -> bool:
    global _lock_fh
    try:
        _lock_fh = open(LOCK_PATH, "w")
        msvcrt.locking(_lock_fh.fileno(), msvcrt.LK_NBLCK, 1)
        return True
    except (OSError, IOError):
        return False


def release_instance_lock() -> None:
    global _lock_fh
    if _lock_fh:
        try:
            msvcrt.locking(_lock_fh.fileno(), msvcrt.LK_UNLCK, 1)
            _lock_fh.close()
        except (OSError, IOError):
            pass
        _lock_fh = None


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    if not acquire_instance_lock():
        try:
            import customtkinter as ctk
            ctk.set_appearance_mode("dark")
            root = ctk.CTk()
            root.withdraw()
            from tkinter import messagebox
            messagebox.showwarning("Grok Manager", "Grok Manager is already running.")
            root.destroy()
        except Exception:
            pass
        sys.exit(1)

    from config import load_config
    from gui import GrokManagerApp

    config_path = APP_DIR / "config.yaml"
    config = load_config(config_path)
    app = GrokManagerApp(config)
    app.mainloop()


if __name__ == "__main__":
    main()
