from __future__ import annotations

import os
import sys
from pathlib import Path


APP_BRAND = "AIwithSaeed"
APP_NAME = "AIwithSaeed Downloader"
APP_SLUG = "aiwithsaeed-downloader"
SITE_URL = "https://aiwithsaeed.com"

INSTALL_DIR = Path(__file__).resolve().parent


def user_data_dir() -> Path:
    """Return a private, per-Windows-user directory for mutable app data."""
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return root / APP_BRAND / "Downloader"
    root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / APP_SLUG


APP_DATA_DIR = user_data_dir()
APP_DATA_DIR.mkdir(parents=True, exist_ok=True)

QUEUE_DB = APP_DATA_DIR / "downloads.db"
BOT_TOKEN_FILE = APP_DATA_DIR / "telegram-token.dpapi"
BOT_LOG_FILE = APP_DATA_DIR / "telegram-bot.log"
APP_LOG_FILE = APP_DATA_DIR / "desktop-app.log"
STARTUP_LOG_FILE = APP_DATA_DIR / "startup-error.log"
