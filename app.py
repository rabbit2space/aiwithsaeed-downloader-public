from __future__ import annotations

import ctypes
import base64
import json
import logging
import os
import queue
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from PIL import Image

from download_config import (
    DownloadSettings,
    desktop_settings_for_url,
    format_bytes,
    premiere_streams_compatible,
    validate_proxy_url,
)
from queue_store import QueueStore
from ui_fonts import FONT_FAMILY, register_fonts

import tkinter as tk
from tkinter import filedialog, messagebox

from app_paths import (
    APP_DATA_DIR,
    APP_LOG_FILE,
    APP_NAME,
    BOT_LOG_FILE,
    BOT_TOKEN_FILE,
    INSTALL_DIR,
    QUEUE_DB,
    SITE_URL,
)

try:
    import customtkinter as ctk
except ImportError:
    ctk = None

try:
    from tkinterdnd2 import COPY, DND_FILES, DND_TEXT, TkinterDnD
except ImportError:
    COPY = "copy"
    DND_FILES = DND_TEXT = TkinterDnD = None

try:
    import winsound
except ImportError:
    winsound = None

try:
    import yt_dlp
except ImportError:
    yt_dlp = None


APP_VERSION = "4.6.1"
APP_DIR = INSTALL_DIR
ASSET_DIR = APP_DIR / "assets"
BRAND_LOGO_LIGHT_FILE = ASSET_DIR / "aiwithsaeed-logo-light.png"
BRAND_LOGO_DARK_FILE = ASSET_DIR / "aiwithsaeed-logo-dark.png"
BRAND_LOGO_FILE = BRAND_LOGO_LIGHT_FILE
BOT_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
BOT_ALLOWED_CHAT_ENV = "TELEGRAM_ALLOWED_CHAT_ID"
APP_MUTEX_NAME = r"Local\AIwithSaeed.Downloader"
ERROR_ALREADY_EXISTS = 183
LOGGER = logging.getLogger("aiwithsaeed.downloader")
MEDIA_EXTENSIONS = {
    ".3gp", ".aac", ".flac", ".m4a", ".m4v", ".mkv", ".mov", ".mp3",
    ".mp4", ".ogg", ".opus", ".wav", ".webm",
}

PAGE = ("#F5F5F7", "#0D0F12")
CARD = ("#FFFFFF", "#181A1F")
INK = ("#1D1D1F", "#F5F6F8")
MUTED = ("#86868B", "#A6A9B1")
LINE = ("#E7E7EA", "#30343C")
PILL = ("#F0F0F2", "#252830")
BLUE = "#0071E3"
BLUE_HOVER = "#0077ED"
CYAN = "#00A9CE"
GREEN = "#18A77A"
CORAL = "#FF6B6B"
DARK = "#111113"
DARK_2 = "#1C1C1E"


def configure_logging() -> None:
    """Keep useful diagnostics when the app is launched without a console."""
    if LOGGER.handlers:
        return
    LOGGER.setLevel(logging.INFO)
    try:
        handler = RotatingFileHandler(
            APP_LOG_FILE,
            maxBytes=1_000_000,
            backupCount=2,
            encoding="utf-8",
        )
    except OSError:
        return
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    )
    LOGGER.addHandler(handler)


def acquire_single_instance(name: str = APP_MUTEX_NAME) -> int | None:
    """Return a Windows mutex handle, or None when another app copy is running."""
    if sys.platform != "win32":
        return -1
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_bool
    ctypes.set_last_error(0)
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return None
    return int(handle)


def release_single_instance(handle: int | None) -> None:
    if sys.platform != "win32" or handle in (None, -1):
        return
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_bool
    kernel32.CloseHandle(ctypes.c_void_p(handle))


def existing_output_paths(value: str) -> list[Path]:
    """Return existing output files from a newline-delimited queue value."""
    paths: list[Path] = []
    for raw_path in value.splitlines():
        raw_path = raw_path.strip()
        if not raw_path:
            continue
        path = Path(raw_path)
        if path.is_file():
            paths.append(path)
    return paths


TEXT = {
    "en": {
        "tagline": "Save what matters.",
        "subtagline": "Videos, playlists, captions and audio — beautifully organized.",
        "links": "PASTE LINKS",
        "links_hint": "One YouTube or Instagram URL per line",
        "paste": "Paste",
        "clear": "Clear",
        "download": "Add to queue",
        "cancel": "Pause current",
        "format_card": "OUTPUT",
        "format": "Format",
        "quality": "Quality",
        "features": "KEEP THE DETAILS",
        "playlist": "Playlist / channel",
        "subtitles": "Available subtitles",
        "auto_subtitles": "Auto-generated captions",
        "subtitle_langs": "Subtitle languages",
        "thumbnail": "Thumbnail",
        "embed_thumbnail": "Embed thumbnail",
        "metadata": "Title and metadata",
        "description": "Description file",
        "completion_sound": "Sound when finished",
        "access": "ACCOUNT ACCESS",
        "browser": "Browser login",
        "cookie_file": "Cookies file",
        "choose": "Choose file",
        "cookie_optional": "Optional · Netscape cookies.txt",
        "proxy": "Download proxy · HTTP / SOCKS (optional)",
        "proxy_hint": "Optional · http://host:port or socks5://host:port",
        "destination": "DESTINATION",
        "save_to": "Download folder",
        "browse": "Browse",
        "open_folder": "Open folder",
        "activity": "ACTIVITY",
        "open_file_hint": "Double-click a completed item to open its file",
        "ready": "Ready when you are",
        "ready_detail": "Add one or more links above to begin.",
        "starting": "Preparing download…",
        "processing": "Finishing your media…",
        "cookie_retry": "YouTube authentication required",
        "retry_detail": "Retrying safely with Firefox cookies…",
        "privacy": "Download responsibly",
        "ffmpeg_ok": "FFmpeg ready",
        "ffmpeg_missing": "FFmpeg missing",
        "js_ok": "YouTube engine ready",
        "js_missing": "Deno / Node missing",
        "queue_empty": "Queue is empty",
        "select_all": "Select all",
        "clear_selection": "Clear",
        "selected_count": "{count} selected",
        "bulk_pause": "Pause",
        "bulk_resume": "Resume",
        "bulk_delete": "Delete",
        "pause_action": "Pause",
        "resume_action": "Resume",
        "delete_action": "Delete",
        "source_telegram": "Telegram",
        "source_desktop": "Desktop",
        "status_queued": "Queued",
        "status_downloading": "Downloading",
        "status_processing": "Processing",
        "status_expanding": "Reading playlist",
        "status_paused": "Paused",
        "status_completed": "Completed",
        "status_failed": "Failed",
        "status_cancelled": "Cancelled",
        "status_stopping": "Stopping",
        "queue_idle": "Queue is idle",
        "preparing_next": "Preparing next queue item…",
        "no_pending": "No pending downloads",
        "items_waiting": "{count} item(s) waiting",
        "dropped_added": "Added {count} dropped link(s)",
        "review_links": "Review the links, then add them to the queue",
        "queue_added": "Added {count} item(s) to queue",
        "one_at_time": "Downloads run one at a time",
        "playlists_detected": "{count} playlist link(s) detected",
        "downloading_current": "Downloading current item",
        "reading_playlist": "Reading complete playlist…",
        "playlist_added": "Added {count} playlist videos to queue",
        "playlist_each": "Each video will download separately, one at a time",
        "single_video": "Single video detected",
        "item_skipped": "Item skipped",
        "download_completed": "Download completed",
        "download_failed": "Download failed",
        "version": "DESKTOP DOWNLOADER",
        "setup_guide": "Setup guide",
    },
    "fa": {
        "select_all": "انتخاب همه",
        "clear_selection": "پاک کردن",
        "selected_count": "{count} انتخاب",
        "bulk_pause": "توقف",
        "bulk_resume": "ادامه",
        "bulk_delete": "حذف",
        "tagline": "هرچه مهم است ذخیره کن.",
        "subtagline": "ویدیو، پلی‌لیست، زیرنویس و صدا — مرتب و ساده.",
        "links": "لینک‌ها",
        "links_hint": "در هر خط یک لینک یوتیوب یا اینستاگرام وارد کنید",
        "paste": "چسباندن",
        "clear": "پاک کردن",
        "download": "افزودن به صف",
        "cancel": "توقف موقت",
        "format_card": "خروجی",
        "format": "فرمت",
        "quality": "کیفیت",
        "features": "جزئیات فایل",
        "playlist": "پلی‌لیست / کانال",
        "subtitles": "زیرنویس‌های موجود",
        "auto_subtitles": "زیرنویس خودکار",
        "subtitle_langs": "زبان زیرنویس",
        "thumbnail": "تصویر بندانگشتی",
        "embed_thumbnail": "قرار دادن تصویر روی فایل",
        "metadata": "عنوان و اطلاعات فایل",
        "description": "فایل توضیحات",
        "completion_sound": "پخش صدا پس از پایان",
        "access": "دسترسی حساب",
        "browser": "ورود از مرورگر",
        "cookie_file": "فایل کوکی",
        "choose": "انتخاب فایل",
        "cookie_optional": "اختیاری · فایل cookies.txt",
        "proxy": "پروکسی دانلود (اختیاری): HTTP / SOCKS",
        "proxy_hint": "اختیاری، برای نمونه: http://host:port، socks5://host:port",
        "destination": "محل ذخیره",
        "save_to": "پوشه دانلود",
        "browse": "انتخاب",
        "open_folder": "باز کردن پوشه",
        "activity": "وضعیت دانلود",
        "open_file_hint": "برای باز کردن فایل کامل‌شده، روی آن دوبار کلیک کنید",
        "ready": "آماده دانلود",
        "ready_detail": "برای شروع، یک یا چند لینک در بالا وارد کنید.",
        "starting": "در حال آماده‌سازی…",
        "processing": "در حال تکمیل فایل…",
        "cookie_retry": "احراز هویت یوتیوب لازم است",
        "retry_detail": "تلاش دوباره با کوکی‌های فایرفاکس…",
        "privacy": "مسئولانه دانلود کنید",
        "ffmpeg_ok": "آماده است: FFmpeg",
        "ffmpeg_missing": "نصب نیست: FFmpeg",
        "js_ok": "موتور یوتیوب آماده است",
        "js_missing": "نصب نیست: Deno / Node",
        "queue_empty": "صف دانلود خالی است",
        "pause_action": "توقف",
        "resume_action": "ادامه",
        "delete_action": "حذف",
        "source_telegram": "تلگرام",
        "source_desktop": "دسکتاپ",
        "status_queued": "در صف",
        "status_downloading": "در حال دانلود",
        "status_processing": "در حال پردازش",
        "status_expanding": "خواندن پلی‌لیست",
        "status_paused": "متوقف",
        "status_completed": "کامل",
        "status_failed": "ناموفق",
        "status_cancelled": "لغو شده",
        "status_stopping": "در حال توقف",
        "queue_idle": "صف غیرفعال است",
        "preparing_next": "آماده‌سازی مورد بعدی…",
        "no_pending": "دانلودی در انتظار نیست",
        "items_waiting": "{count} مورد در انتظار",
        "dropped_added": "{count} لینک رهاشده اضافه شد",
        "review_links": "لینک‌ها را بررسی و سپس به صف اضافه کنید",
        "queue_added": "{count} مورد به صف اضافه شد",
        "one_at_time": "دانلودها به‌ترتیب و یکی‌یکی انجام می‌شوند",
        "playlists_detected": "{count} لینک پلی‌لیست شناسایی شد",
        "downloading_current": "در حال دانلود مورد فعلی",
        "reading_playlist": "در حال خواندن کامل پلی‌لیست…",
        "playlist_added": "{count} ویدیوی پلی‌لیست به صف اضافه شد",
        "playlist_each": "هر ویدیو جداگانه و به‌ترتیب دانلود می‌شود",
        "single_video": "یک ویدیوی تکی شناسایی شد",
        "item_skipped": "این مورد رد شد",
        "download_completed": "دانلود کامل شد",
        "download_failed": "دانلود ناموفق بود",
        "version": "دانلودر دسکتاپ",
        "setup_guide": "راهنمای راه‌اندازی",
    },
}

GUIDE_TEXT = {
    "en": {
        "window": "Welcome to AIwithSaeed Downloader",
        "steps": ("WELCOME", "YOUTUBE LOGIN", "FIREFOX COOKIES", "COOKIE FILE", "TELEGRAM"),
        "titles": (
            "Free to use — no website login or activation",
            "Sign in to YouTube with Firefox",
            "Let the downloader read your Firefox session",
            "Create a durable YouTube cookies.txt (advanced)",
            "Connect your own private Telegram bot (optional)",
        ),
        "bodies": (
            "The app is free to use. Cookies and Telegram are optional.",
            "Try public videos without cookies first. YouTube cookies are mainly needed when YouTube asks "
            "you to sign in or for account-only content. yt-dlp warns that account use can result in a "
            "temporary or permanent ban, so use cookies only when necessary and prefer a separate account.\n\n"
            "1. Install Mozilla Firefox if needed.\n2. Open YouTube in Firefox and sign in.\n"
            "3. Play a normal video and confirm your profile picture appears.",
            "1. Close every Firefox window completely.\n"
            "2. Wait a few seconds so Firefox releases its cookie database.\n"
            "3. Click Use Firefox cookies below.\n"
            "4. The app asks yt-dlp to read Firefox locally; it never receives your YouTube password.\n"
            "5. If direct reading fails, use a fresh Netscape cookies.txt as the advanced fallback. "
            "Never share or upload that file because it can grant access to your session.",
            "1. Open one new Private Window in Firefox and sign in to YouTube.\n"
            "2. In that same tab, open https://www.youtube.com/robots.txt.\n"
            "3. Export only youtube.com cookies with a trusted local-only Firefox extension in Netscape format.\n"
            "4. Close the private window and never reopen that private session, so YouTube does not rotate the cookies.\n"
            "5. Select the exported file below. Never share it. Use the official yt-dlp guide if unsure.",
            "1. Open @BotFather in Telegram and send /newbot.\n"
            "2. Copy the new bot token below.\n"
            "3. Open your new bot and send /start.\n"
            "4. Click Detect chat ID, or paste your numeric chat ID.\n"
            "5. Save and start. The token is encrypted with Windows DPAPI and the bot accepts only your ID.",
        ),
        "open_youtube": "Open YouTube in Firefox",
        "get_firefox": "Install Firefox",
        "use_firefox": "Use Firefox cookies",
        "check_firefox": "Check Firefox login",
        "choose_cookie_file": "Choose cookies.txt (advanced)",
        "official_cookie_guide": "Open official yt-dlp cookie guide",
        "firefox_ready": "Firefox cookies found. Close Firefox before downloading.",
        "firefox_missing": "No Firefox login cookies were found. Sign in to YouTube in Firefox first.",
        "firefox_selected": "Firefox cookies selected for downloads.",
        "back": "Back",
        "next": "Next",
        "done": "Done",
        "token": "BotFather token",
        "chat_id": "Telegram chat ID",
        "detect": "Detect chat ID",
        "save": "Save & start bot",
        "disable": "Disable Telegram",
        "token_hint": "123456789:AA...",
        "chat_hint": "Send /start to your bot first",
        "saved": "Telegram is configured for this Windows user.",
        "disabled": "Telegram is disabled. Desktop downloads still work.",
        "detecting": "Checking messages sent to your bot…",
    },
    "fa": {
        "window": "راهنمای شروع کار",
        "steps": ("شروع", "ورود یوتیوب", "کوکی فایرفاکس", "فایل کوکی", "تلگرام"),
        "titles": (
            "آماده دانلودید؟",
            "ورود به یوتیوب با فایرفاکس",
            "استفاده از کوکی فایرفاکس",
            "روش جایگزین: فایل کوکی",
            "دانلود با ربات تلگرام (اختیاری)",
        ),
        "bodies": (
            "برنامه رایگان است و برای استفاده از آن نیازی به ثبت‌نام ندارید.",
            "اول بدون کوکی دانلود کنید. اگر یوتیوب از شما خواست وارد حساب شوید، این مراحل را انجام دهید:\n\n"
            "۱. فایرفاکس را نصب کنید، اگر روی کامپیوترتان نیست.\n"
            "۲. یوتیوب را در فایرفاکس باز کنید و وارد حساب شوید.\n"
            "۳. یک ویدیو پخش کنید و مطمئن شوید عکس حساب‌تان بالای صفحه دیده می‌شود.\n\n"
            "استفاده از کوکی ممکن است باعث محدودیت موقت یا دائمی حساب شود. فقط در صورت نیاز از آن استفاده کنید؛ بهتر است حساب جداگانه‌ای داشته باشید.",
            "۱. همه پنجره‌های فایرفاکس را ببندید و چند ثانیه صبر کنید.\n"
            "۲. دکمه «استفاده از کوکی فایرفاکس» را بزنید.\n"
            "۳. حالا دوباره دانلود را امتحان کنید.\n\n"
            "برنامه کوکی را از همین کامپیوتر می‌خواند؛ لازم نیست رمز حساب‌تان را اینجا وارد کنید.\n"
            "اگر این روش کار نکرد، در مرحله بعد فایل کوکی را انتخاب کنید.\n"
            "کوکی مثل کلید ورود به حساب شماست؛ آن را برای کسی نفرستید.",
            "اگر روش قبل کار نکرد، می‌توانید فایل کوکی را وارد کنید:\n\n"
            "۱. در فایرفاکس یک پنجره خصوصی باز کنید و وارد یوتیوب شوید.\n"
            "۲. در همان تب، این نشانی را باز کنید:\nhttps://www.youtube.com/robots.txt\n"
            "۳. با یک افزونه معتبر که کوکی‌ها را جایی نمی‌فرستد، فقط کوکی‌های یوتیوب را ذخیره کنید.\n"
            "فرمت فایل باید این باشد: Netscape\n"
            "۴. پنجره خصوصی را ببندید و دوباره از همان جلسه استفاده نکنید تا کوکی‌ها تغییر نکنند.\n"
            "۵. فایل را با دکمه زیر انتخاب کنید. آن را برای کسی نفرستید.\n\n"
            "اگر مطمئن نیستید، راهنمای کامل زیر را بخوانید.",
            "۱. در تلگرام ربات ساخت ربات را باز کنید: @BotFather\n"
            "دستور ساخت ربات را بفرستید و نام ربات‌تان را انتخاب کنید: /newbot\n"
            "۲. توکن ربات جدید را پایین وارد کنید.\n"
            "۳. ربات جدید را باز کنید و این دستور را بفرستید: /start\n"
            "۴. «پیدا کردن شناسه» را بزنید یا شناسه عددی چت‌تان را وارد کنید.\n"
            "۵. «راه‌اندازی ربات» را بزنید.\n\n"
            "توکن، کلید ربات شماست؛ آن را برای کسی نفرستید.\n"
            "توکن رمزگذاری‌شده ذخیره می‌شود و ربات فقط پیام‌های شما را می‌پذیرد.",
        ),
        "open_youtube": "باز کردن یوتیوب",
        "get_firefox": "نصب فایرفاکس",
        "use_firefox": "استفاده از کوکی فایرفاکس",
        "check_firefox": "بررسی ورود به حساب",
        "choose_cookie_file": "انتخاب فایل کوکی",
        "official_cookie_guide": "راهنمای کامل کوکی",
        "firefox_ready": "کوکی پیدا شد. پیش از دانلود، فایرفاکس را ببندید.",
        "firefox_missing": "کوکی پیدا نشد. اول در فایرفاکس وارد یوتیوب شوید.",
        "firefox_selected": "کوکی فایرفاکس برای دانلود فعال شد.",
        "back": "قبلی",
        "next": "بعدی",
        "done": "تمام",
        "token": "توکن ربات",
        "chat_id": "شناسه عددی چت تلگرام",
        "detect": "پیدا کردن شناسه",
        "save": "راه‌اندازی ربات",
        "disable": "غیرفعال‌کردن تلگرام",
        "token_hint": "123456789:AA...",
        "chat_hint": "ابتدا این دستور را برای ربات بفرستید: /start",
        "saved": "ربات آماده است. لینک ویدیو را برایش بفرستید.",
        "disabled": "ربات خاموش است. همچنان می‌توانید با خود برنامه دانلود کنید.",
        "detecting": "در حال پیدا کردن شناسه…",
    },
}

OPTIONS = {
    "mode": {
        "premiere": {"en": "Premiere MP4 · H.264", "fa": "پریمیر: MP4 · H.264"},
        "video": {"en": "Original best quality", "fa": "بهترین کیفیت اصلی"},
        "audio": {"en": "Audio only (MP3)", "fa": "فقط صدا (MP3)"},
    },
    "quality": {
        "best": {"en": "Best available", "fa": "بهترین کیفیت"},
        "2160": {"en": "2160p · 4K", "fa": "2160p · 4K"},
        "1440": {"en": "1440p · 2K", "fa": "1440p · 2K"},
        "1080": {"en": "1080p · Full HD", "fa": "1080p · Full HD"},
        "720": {"en": "720p · HD", "fa": "720p · HD"},
        "480": {"en": "480p", "fa": "480p"},
        "360": {"en": "360p", "fa": "360p"},
    },
    "browser": {
        "none": {"en": "No browser", "fa": "بدون مرورگر"},
        "chrome": {"en": "Chrome", "fa": "کروم"},
        "edge": {"en": "Edge", "fa": "اج"},
        "firefox": {"en": "Firefox", "fa": "فایرفاکس"},
        "brave": {"en": "Brave", "fa": "بریو"},
        "opera": {"en": "Opera", "fa": "اپرا"},
        "vivaldi": {"en": "Vivaldi", "fa": "ویوالدی"},
    },
}


class DownloadCancelled(Exception):
    pass


class DownloadLogger:
    def __init__(self) -> None:
        self.last_error = ""
        self.warnings: list[str] = []

    def debug(self, message: str) -> None:
        pass

    def info(self, message: str) -> None:
        pass

    def warning(self, message: str) -> None:
        self.warnings.append(message.strip())

    def error(self, message: str) -> None:
        self.last_error = message.replace("ERROR: ", "").strip()

    @staticmethod
    def is_cookie_access_message(message: str) -> bool:
        diagnostics = message.lower()
        return "cookie" in diagnostics and any(word in diagnostics for word in (
            "copy", "decrypt", "database", "keyring", "permission", "locked", "failed",
        ))

    @property
    def cookie_access_error(self) -> bool:
        return self.is_cookie_access_message(" ".join([self.last_error, *self.warnings]))

    @staticmethod
    def is_auth_message(message: str) -> bool:
        diagnostics = message.lower()
        return any(phrase in diagnostics for phrase in (
            "sign in to confirm you’re not a bot",
            "sign in to confirm you're not a bot",
            "cookies for the authentication",
            "login required",
            "authentication required",
        ))

    @property
    def auth_error(self) -> bool:
        diagnostics = " ".join([self.last_error, *self.warnings])
        return self.is_auth_message(diagnostics) or self.is_cookie_access_message(diagnostics)


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _data_blob(data: bytes) -> tuple[_DataBlob, Any]:
    buffer = ctypes.create_string_buffer(data)
    blob = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    return blob, buffer


def save_bot_token(token: str) -> None:
    """Encrypt the token for the current Windows account using DPAPI."""
    if sys.platform != "win32":
        raise OSError("Telegram token storage is supported on Windows only")
    source, source_buffer = _data_blob(token.encode("utf-8"))
    protected = _DataBlob()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(source), APP_NAME, None, None, None, 0x01, ctypes.byref(protected)
    ):
        raise ctypes.WinError()
    try:
        encrypted = ctypes.string_at(protected.pbData, protected.cbData)
        BOT_TOKEN_FILE.write_bytes(base64.urlsafe_b64encode(encrypted))
    finally:
        ctypes.windll.kernel32.LocalFree(protected.pbData)
        del source_buffer


def load_bot_token() -> str | None:
    """Decrypt a token saved by save_bot_token for the current Windows account."""
    if sys.platform != "win32" or not BOT_TOKEN_FILE.is_file():
        return None
    try:
        encrypted = base64.urlsafe_b64decode(BOT_TOKEN_FILE.read_bytes())
        source, source_buffer = _data_blob(encrypted)
        plain = _DataBlob()
        if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(source), None, None, None, None, 0x01, ctypes.byref(plain)
        ):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(plain.pbData, plain.cbData).decode("utf-8")
        finally:
            ctypes.windll.kernel32.LocalFree(plain.pbData)
            del source_buffer
    except (OSError, ValueError, UnicodeError):
        return None


def valid_bot_token(token: str) -> bool:
    value = token.strip()
    return bool(re.fullmatch(r"\d{6,12}:[A-Za-z0-9_-]{30,}", value))


def detect_telegram_chat_id(token: str, proxy: str = "", language: str = "en") -> int:
    """Find the most recent private chat that messaged the user's own bot."""
    fa = language == "fa"
    if not valid_bot_token(token):
        raise ValueError("یک توکن معتبر وارد کنید: BotFather" if fa else "Enter a valid BotFather token first.")
    url = f"https://api.telegram.org/bot{token.strip()}/getUpdates?timeout=0&limit=100"
    handlers: list[Any] = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(url, timeout=25) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        message = f"اتصال به تلگرام ممکن نشد: {exc}" if fa else f"Could not reach Telegram: {exc}"
        raise RuntimeError(message) from exc
    if not payload.get("ok"):
        description = payload.get("description")
        default = "تلگرام این توکن را نپذیرفت." if fa else "Telegram rejected this token."
        raise RuntimeError(f"{description}" if description else default)
    chat_ids: list[int] = []
    for update in payload.get("result", []):
        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat") or {}
        if chat.get("type") == "private" and isinstance(chat.get("id"), int):
            chat_ids.append(chat["id"])
    if not chat_ids:
        message = (
            "هیچ چت خصوصی پیدا نشد.\nربات جدید را باز کنید و این دستور را بفرستید: /start\nسپس دوباره امتحان کنید."
            if fa else
            "No private chat found. Open your new bot, send /start, then try again."
        )
        raise RuntimeError(message)
    return chat_ids[-1]


def register_local_fonts() -> None:
    register_fonts(ASSET_DIR)


def default_download_dir() -> Path:
    return Path.home() / "Downloads" / "AIwithSaeed"


def human_eta(seconds: float | int | None) -> str:
    if seconds is None:
        return "--:--"
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


BaseWindow = ctk.CTk if ctk else tk.Tk
BrandButtonBase = ctk.CTkButton if ctk else tk.Button


class _DndSupport(TkinterDnD.DnDWrapper if TkinterDnD else object):
    pass


def _theme_color(colors: str | tuple[str, str]) -> str:
    if isinstance(colors, tuple):
        return colors[1] if ctk.get_appearance_mode() == "Dark" else colors[0]
    return colors


class BrandLogo(BrandButtonBase):
    """The website logo at its original aspect ratio, with a small hover tip."""

    WIDTH = 68
    HEIGHT = 68
    IMAGE_SIZE = (64, 64)

    def __init__(self, parent: Any, command: Any) -> None:
        self.command = command
        self.logo_image: Any = None
        self.tooltip: Any = None
        self.tooltip_after: Any = None
        self._load_logo()
        super().__init__(
            parent,
            width=self.WIDTH,
            height=self.HEIGHT,
            corner_radius=0,
            border_width=0,
            border_spacing=0,
            bg_color="transparent",
            fg_color="transparent",
            hover=False,
            text="" if self.logo_image else "AIwithSaeed",
            text_color=INK,
            font=(FONT_FAMILY, 14, "bold"),
            image=self.logo_image,
            command=self.command,
            cursor="hand2",
        )
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<FocusIn>", self._focus_in)
        self.bind("<FocusOut>", self._focus_out)
        self.bind("<Return>", lambda _event: self.command())
        self.bind("<space>", lambda _event: self.command())

    def _load_logo(self) -> None:
        try:
            logos: list[Image.Image] = []
            for logo_file in (BRAND_LOGO_LIGHT_FILE, BRAND_LOGO_DARK_FILE):
                with Image.open(logo_file) as source:
                    logos.append(source.convert("RGBA"))
            self.logo_image = ctk.CTkImage(
                light_image=logos[0],
                dark_image=logos[1],
                size=self.IMAGE_SIZE,
            )
        except (OSError, ValueError):
            LOGGER.exception("Could not load the AIwithSaeed brand logo")

    def _enter(self, _event: Any) -> None:
        self.tooltip_after = self.after(350, self._show_tooltip)

    def _leave(self, _event: Any) -> None:
        if self.tooltip_after:
            self.after_cancel(self.tooltip_after)
            self.tooltip_after = None
        self._hide_tooltip()

    def _focus_in(self, _event: Any) -> None:
        self._show_tooltip()

    def _focus_out(self, _event: Any) -> None:
        self._hide_tooltip()

    def _show_tooltip(self) -> None:
        self.tooltip_after = None
        if self.tooltip and self.tooltip.winfo_exists():
            return
        self.tooltip = ctk.CTkToplevel(self)
        self.tooltip.withdraw()
        self.tooltip.overrideredirect(True)
        self.tooltip.attributes("-topmost", True)
        label = ctk.CTkLabel(
            self.tooltip, text="آموزش هوش مصنوعی", height=34,
            fg_color=("#FFFFFF", "#202329"), text_color=INK,
            corner_radius=10, font=(FONT_FAMILY, 12, "bold"),
        )
        label.pack(padx=1, pady=1)
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height() + 6
        self.tooltip.geometry(f"+{x}+{y}")
        self.tooltip.deiconify()

    def _hide_tooltip(self) -> None:
        if self.tooltip and self.tooltip.winfo_exists():
            self.tooltip.destroy()
        self.tooltip = None

    def redraw(self) -> None:
        self.configure(fg_color="transparent")


class DownloaderApp(BaseWindow, _DndSupport):
    def __init__(self) -> None:
        super().__init__()
        self.report_callback_exception = self._report_callback_exception
        self.dnd_available = False
        if TkinterDnD:
            try:
                self.TkdndVersion = TkinterDnD._require(self)
                self.dnd_available = True
            except tk.TclError:
                pass
        self.title(f"{APP_NAME} · Video Downloader")
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        window_width = min(1340, max(1060, screen_width - 80))
        window_height = min(980, max(720, screen_height - 90))
        left = max(0, (screen_width - window_width) // 2)
        top = max(0, (screen_height - window_height) // 2)
        self.geometry(f"{window_width}x{window_height}+{left}+{top}")
        self.minsize(min(1060, screen_width - 40), min(720, screen_height - 70))
        self.configure(fg_color=PAGE)
        try:
            self.attributes("-alpha", 0.0)
        except tk.TclError:
            pass

        self.language = "fa"
        self.translatable: list[tuple[Any, str]] = []
        self.option_controls: list[tuple[Any, str, tk.StringVar]] = []
        self.queue_rows: dict[int, dict[str, Any]] = {}
        self.queue_jobs_by_id: dict[int, dict[str, Any]] = {}
        self.selected_job_ids: set[int] = set()
        self.selection_vars: dict[int, tk.BooleanVar] = {}
        self.empty_queue_label: Any = None
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.cancel_event = threading.Event()
        self.job_store = QueueStore(QUEUE_DB)
        self.job_store.recover_interrupted()
        saved_language = self.job_store.get_preference("language", "fa")
        self.language = saved_language if saved_language in {"fa", "en"} else "fa"
        self.current_job_id: int | None = None
        self.current_control = ""
        self.last_control_check = 0.0
        self.last_progress_save = 0.0
        self.last_progress_event = 0.0
        self.output_candidates: set[Path] = set()
        self.queue_signature: tuple[Any, ...] | None = None
        self.progress_value = 0.0
        self.progress_target = 0.0
        self.progress_animating = False
        self.bot_process: subprocess.Popen[Any] | None = None
        self.bot_log_stream: Any = None
        self.bot_restart_attempts = 0
        self.bot_started_at = 0.0
        self.bot_failure_notified = False
        self.closing = False
        self.setup_window: Any = None
        self.setup_step = 0

        self.download_dir = tk.StringVar(value=str(default_download_dir()))
        self.mode = tk.StringVar(value="premiere")
        self.quality = tk.StringVar(value="best")
        saved_browser = self.job_store.get_preference("browser", "none")
        if saved_browser not in OPTIONS["browser"]:
            saved_browser = "none"
        saved_cookie = self.job_store.get_preference("cookie_file")
        if saved_cookie and not Path(saved_cookie).is_file():
            saved_cookie = ""
        self.browser = tk.StringVar(value=saved_browser)
        self.cookies_file = tk.StringVar(value=saved_cookie)
        self.proxy = tk.StringVar(
            value=self.job_store.get_preference("download_proxy")
        )
        self.completion_sound = tk.BooleanVar(
            value=self.job_store.get_preference("completion_sound", "1") != "0"
        )
        self.playlist = tk.BooleanVar(value=False)
        self.subtitles = tk.BooleanVar(value=False)
        self.auto_subtitles = tk.BooleanVar(value=False)
        self.subtitle_langs = tk.StringVar(value="en")
        self.thumbnail = tk.BooleanVar(value=True)
        self.embed_thumbnail = tk.BooleanVar(value=False)
        self.metadata = tk.BooleanVar(value=True)
        self.description = tk.BooleanVar(value=False)

        self._build_ui()
        self._configure_drop_target()
        self._set_language(self.language)
        self._sync_subtitle_controls()
        self.after(100, self._drain_events)
        self.after(40, lambda: self._fade_in(0.0))
        self.after(550, self._show_first_run_guide)
        self.after(900, self._start_telegram_bot)
        self.after(850, self._refresh_queue_view)
        self.after(900, self._ensure_queue_worker)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _font(self, size: int, weight: str = "normal") -> tuple[str, int, str]:
        if size <= 10:
            size += 4
        elif size <= 13:
            size += 3
        else:
            size += 2
        return FONT_FAMILY, size, weight

    def _text(self, key: str) -> str:
        return TEXT[self.language][key]

    def _translated(self, widget: Any, key: str) -> Any:
        self.translatable.append((widget, key))
        return widget

    def _card(self, parent: Any, color: Any = CARD, border: Any = LINE) -> Any:
        return ctk.CTkFrame(parent, fg_color=color, corner_radius=22, border_width=1, border_color=border)

    def _eyebrow(self, parent: Any, key: str, color: str = MUTED) -> Any:
        label = ctk.CTkLabel(parent, text="", text_color=color, font=self._font(11, "bold"), anchor="w")
        self._translated(label, key)
        return label

    def _build_ui(self) -> None:
        shell = ctk.CTkScrollableFrame(
            self, fg_color="transparent", corner_radius=0,
            scrollbar_button_color=("#D8D8DC", "#3A3E48"),
            scrollbar_button_hover_color=("#BFC0C5", "#50545E"),
        )
        self.shell = shell
        shell.pack(fill="both", expand=True, padx=32, pady=(20, 16))
        shell.grid_columnconfigure((0, 1, 2), weight=1, uniform="bento")
        shell.grid_rowconfigure(1, weight=0, minsize=222)
        shell.grid_rowconfigure(2, weight=0, minsize=264)
        shell.grid_rowconfigure(3, weight=1, minsize=324)

        self._build_header(shell)
        self._build_hero(shell)
        self._build_output(shell)
        self._build_features(shell)
        self._build_access(shell)
        self._build_destination(shell)
        self._build_activity(shell)
        self._build_footer(shell)

    def _build_header(self, parent: Any) -> None:
        header = ctk.CTkFrame(parent, fg_color="transparent", height=60)
        self.header = header
        header.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 14))
        header.grid_columnconfigure(1, weight=1)
        self.brand_logo = BrandLogo(header, lambda: webbrowser.open(SITE_URL))
        self.brand_logo.grid(row=0, column=0, rowspan=2, sticky="w")
        version = ctk.CTkLabel(header, text="", text_color=MUTED, font=self._font(10, "bold"), anchor="w")
        self.version_label = version
        version.grid(row=1, column=1, sticky="w", padx=(10, 0), pady=(0, 1))
        self._translated(version, "version")
        self.setup_button = self._translated(ctk.CTkButton(
            header, text="", width=138, height=38, corner_radius=19,
            fg_color=PILL, hover_color=LINE, text_color=INK,
            border_width=1, border_color=LINE, font=self._font(10, "bold"),
            command=self._open_setup_guide,
        ), "setup_guide")
        self.setup_button.grid(row=0, column=2, rowspan=2, sticky="e", padx=(0, 10))
        self.theme_switch = ctk.CTkSegmentedButton(
            header, values=["Light", "Dark"], command=self._theme_selected,
            width=150, height=38, corner_radius=19, fg_color=PILL,
            selected_color=BLUE, selected_hover_color=BLUE_HOVER,
            unselected_color=("#8E8E93", "#343740"),
            unselected_hover_color=("#77777D", "#424650"),
            text_color="#FFFFFF", font=self._font(10, "bold"),
        )
        self.theme_switch.grid(row=0, column=3, rowspan=2, sticky="e", padx=(0, 12))
        self.theme_switch.set(ctk.get_appearance_mode())
        self.language_switch = ctk.CTkSegmentedButton(
            header, values=["EN", "فا"], command=self._language_selected,
            width=124, height=38, corner_radius=19, fg_color=PILL,
            selected_color=BLUE, selected_hover_color=BLUE_HOVER,
            unselected_color=("#8E8E93", "#343740"),
            unselected_hover_color=("#77777D", "#424650"),
            text_color="#FFFFFF", font=self._font(12, "bold"),
        )
        self.language_switch.grid(row=0, column=4, rowspan=2, sticky="e")
        self.language_switch.set("EN")

    def _build_hero(self, parent: Any) -> None:
        hero = self._card(parent, DARK, DARK)
        self.hero_card = hero
        hero.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=(0, 8), pady=(0, 8))
        hero.grid_columnconfigure(0, weight=1)
        accent = ctk.CTkFrame(hero, height=5, fg_color=BLUE, corner_radius=3)
        accent.grid(row=0, column=0, sticky="ew", padx=24, pady=(18, 0))

        heading_row = ctk.CTkFrame(hero, fg_color="transparent")
        self.hero_heading_row = heading_row
        heading_row.grid(row=1, column=0, sticky="ew", padx=26, pady=(12, 8))
        heading_row.grid_columnconfigure(0, weight=1)
        title = ctk.CTkLabel(heading_row, text="", text_color="#FFFFFF", font=self._font(24, "bold"), anchor="w")
        self.hero_title = title
        title.grid(row=0, column=0, sticky="w")
        self._translated(title, "tagline")
        subtitle = ctk.CTkLabel(heading_row, text="", text_color="#A7A7AD", font=self._font(13), anchor="w")
        self.hero_subtitle = subtitle
        subtitle.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self._translated(subtitle, "subtagline")
        chips = ctk.CTkLabel(
            heading_row, text="YouTube   Instagram   Playlists", text_color="#A7CCFF",
            fg_color="#172A42", corner_radius=13, font=self._font(10, "bold"), width=206, height=32,
        )
        self.hero_chips = chips
        chips.grid(row=0, column=1, rowspan=2, sticky="e")

        self.url_text = ctk.CTkTextbox(
            hero, height=72, corner_radius=15, border_width=1, border_color="#333337",
            fg_color=DARK_2, text_color="#FFFFFF", font=self._font(13),
            scrollbar_button_color="#424247", scrollbar_button_hover_color="#56565C",
        )
        self.url_text.grid(row=2, column=0, sticky="ew", padx=26)
        self.url_text.bind("<KeyRelease>", self._sync_url_text_direction)

        actions = ctk.CTkFrame(hero, fg_color="transparent")
        self.hero_actions = actions
        actions.grid(row=3, column=0, sticky="ew", padx=26, pady=(12, 16))
        actions.grid_columnconfigure(2, weight=1)
        self.paste_button = self._translated(ctk.CTkButton(
            actions, text="", width=98, height=40, corner_radius=20, fg_color="#2B2B2F",
            hover_color="#3A3A3F", font=self._font(12, "bold"), command=self._paste,
        ), "paste")
        self.paste_button.grid(row=0, column=0, padx=(0, 9))
        self.clear_button = self._translated(ctk.CTkButton(
            actions, text="", width=90, height=40, corner_radius=20, fg_color="transparent",
            border_width=1, border_color="#414146", hover_color="#28282C",
            font=self._font(12, "bold"), command=self._clear_urls,
        ), "clear")
        self.clear_button.grid(row=0, column=1)
        self.cancel_button = self._translated(ctk.CTkButton(
            actions, text="", width=90, height=42, corner_radius=21, fg_color="#2B2B2F",
            hover_color="#3A3A3F", font=self._font(12, "bold"),
            command=self._cancel_download, state="disabled",
        ), "cancel")
        self.cancel_button.grid(row=0, column=3, padx=(10, 9))
        self.download_button = self._translated(ctk.CTkButton(
            actions, text="", width=172, height=42, corner_radius=21, fg_color=BLUE,
            hover_color=BLUE_HOVER, font=self._font(13, "bold"), command=self._start_download,
        ), "download")
        self.download_button.grid(row=0, column=4)

    def _build_output(self, parent: Any) -> None:
        card = self._card(parent)
        self.output_card = card
        card.grid(row=1, column=2, sticky="nsew", padx=(8, 0), pady=(0, 8))
        self._eyebrow(card, "format_card", BLUE).pack(anchor="w", padx=22, pady=(18, 6))
        self._option_row(card, "format", "mode", self.mode)
        self._option_row(card, "quality", "quality", self.quality)
        note = ctk.CTkLabel(
            card, text="Premiere-ready  ·  MP4  ·  4K", text_color=BLUE,
            fg_color=("#EAF4FF", "#172A42"),
            corner_radius=13, font=self._font(10, "bold"), width=206, height=30,
        )
        note.pack(anchor="w", padx=22, pady=(9, 14))

    def _option_row(self, parent: Any, label_key: str, group: str, variable: tk.StringVar) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=22, pady=6)
        label = ctk.CTkLabel(row, text="", text_color=INK, font=self._font(12, "bold"), anchor="w")
        label.pack(fill="x", pady=(0, 4))
        self._translated(label, label_key)
        menu = ctk.CTkOptionMenu(
            row, values=[""], height=38, corner_radius=12, fg_color=PILL,
            button_color=LINE, button_hover_color=("#DADADF", "#3A3E48"), text_color=INK,
            dropdown_fg_color=CARD, dropdown_hover_color=PILL,
            font=self._font(12), dropdown_font=self._font(12),
            command=lambda value, g=group, v=variable: self._option_selected(g, v, value),
        )
        menu.pack(fill="x")
        self.option_controls.append((menu, group, variable))

    def _build_features(self, parent: Any) -> None:
        card = self._card(parent)
        self.features_card = card
        card.grid(row=2, column=0, sticky="nsew", padx=(0, 8), pady=8)
        self._eyebrow(card, "features", CYAN).pack(anchor="w", padx=22, pady=(20, 12))
        grid = ctk.CTkFrame(card, fg_color="transparent")
        grid.pack(fill="both", expand=True, padx=18, pady=(0, 16))
        grid.grid_columnconfigure((0, 1), weight=1)
        checks = (
            ("playlist", self.playlist), ("thumbnail", self.thumbnail),
            ("subtitles", self.subtitles), ("auto_subtitles", self.auto_subtitles),
            ("embed_thumbnail", self.embed_thumbnail), ("metadata", self.metadata),
            ("description", self.description), ("completion_sound", self.completion_sound),
        )
        self.feature_checkboxes: list[Any] = []
        for index, (key, variable) in enumerate(checks):
            if key in {"subtitles", "auto_subtitles"}:
                command = self._sync_subtitle_controls
            elif key == "completion_sound":
                command = self._toggle_completion_sound
            else:
                command = None
            box = self._translated(ctk.CTkCheckBox(
                grid, text="", variable=variable, width=20, height=26, corner_radius=6,
                border_width=2, border_color=("#C8C8CD", "#626671"),
                fg_color=CYAN, hover_color="#0097B8",
                text_color=INK, font=self._font(11), command=command,
            ), key)
            box.grid(row=index // 2, column=index % 2, sticky="w", padx=8, pady=9)
            self.feature_checkboxes.append(box)
        lang_row = ctk.CTkFrame(grid, fg_color=PILL, corner_radius=12)
        self.subtitle_lang_row = lang_row
        lang_row.grid(row=4, column=0, columnspan=2, sticky="ew", padx=6, pady=(10, 0))
        label = ctk.CTkLabel(lang_row, text="", text_color=MUTED, font=self._font(10, "bold"), anchor="w")
        self.subtitle_lang_label = label
        label.pack(side="left", padx=13)
        self._translated(label, "subtitle_langs")
        self.lang_entry = ctk.CTkEntry(
            lang_row, textvariable=self.subtitle_langs, width=110, height=36, corner_radius=11,
            border_width=0, fg_color=CARD, text_color=INK, font=self._font(11), justify="center",
        )
        self.lang_entry.pack(side="right", padx=6, pady=6)

    def _build_access(self, parent: Any) -> None:
        card = self._card(parent)
        self.access_card = card
        card.grid(row=2, column=1, sticky="nsew", padx=8, pady=8)
        self._eyebrow(card, "access", GREEN).pack(anchor="w", padx=22, pady=(18, 6))
        self._option_row(card, "browser", "browser", self.browser)
        label = ctk.CTkLabel(card, text="", text_color=INK, font=self._font(12, "bold"), anchor="w")
        label.pack(fill="x", padx=22, pady=(6, 4))
        self._translated(label, "cookie_file")
        self.cookie_button = self._translated(ctk.CTkButton(
            card, text="", height=38, corner_radius=12, fg_color=PILL, hover_color=LINE,
            text_color=INK, font=self._font(11, "bold"), command=self._choose_cookies_file,
        ), "choose")
        self.cookie_button.pack(fill="x", padx=22, pady=(0, 8))
        proxy_label = ctk.CTkLabel(
            card, text="", text_color=INK, font=self._font(12, "bold"), anchor="w",
        )
        proxy_label.pack(fill="x", padx=22, pady=(4, 4))
        self._translated(proxy_label, "proxy")
        self.proxy_entry = ctk.CTkEntry(
            card, textvariable=self.proxy, height=40, corner_radius=12,
            border_width=0, fg_color=PILL, text_color=INK, font=self._font(10),
            placeholder_text="socks5://127.0.0.1:1080",
        )
        self.proxy_entry.pack(fill="x", padx=22, pady=(0, 14))
        self.proxy_entry.bind("<FocusOut>", self._persist_proxy)
        self.proxy_entry.bind("<Return>", self._persist_proxy)

    def _build_destination(self, parent: Any) -> None:
        card = self._card(parent)
        self.destination_card = card
        card.grid(row=2, column=2, sticky="nsew", padx=(8, 0), pady=8)
        self._eyebrow(card, "destination", CORAL).pack(anchor="w", padx=22, pady=(18, 10))
        label = ctk.CTkLabel(card, text="", text_color=INK, font=self._font(12, "bold"), anchor="w")
        label.pack(fill="x", padx=22, pady=(0, 7))
        self._translated(label, "save_to")
        self.folder_entry = ctk.CTkEntry(
            card, textvariable=self.download_dir, height=44, corner_radius=13,
            border_width=0, fg_color=PILL, text_color=INK, font=self._font(10),
        )
        self.folder_entry.pack(fill="x", padx=22)
        buttons = ctk.CTkFrame(card, fg_color="transparent")
        self.destination_buttons = buttons
        buttons.pack(fill="x", padx=22, pady=(14, 18))
        buttons.grid_columnconfigure((0, 1), weight=1)
        browse = self._translated(ctk.CTkButton(
            buttons, text="", height=40, corner_radius=13,
            fg_color=("#FFF0F0", "#3B2428"),
            hover_color=("#FFE3E3", "#513036"), text_color=("#D84C4C", "#FF8585"),
            font=self._font(11, "bold"),
            command=self._choose_folder,
        ), "browse")
        self.browse_button = browse
        browse.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        open_button = self._translated(ctk.CTkButton(
            buttons, text="", height=40, corner_radius=13, fg_color=PILL,
            hover_color=LINE, text_color=INK, font=self._font(11, "bold"),
            command=self._open_folder,
        ), "open_folder")
        self.open_folder_button = open_button
        open_button.grid(row=0, column=1, sticky="ew", padx=(6, 0))

    def _build_activity(self, parent: Any) -> None:
        card = self._card(parent)
        self.activity_card = card
        card.grid(row=3, column=0, columnspan=3, sticky="nsew", pady=(8, 0))
        card.grid_columnconfigure(0, weight=2, minsize=410)
        card.grid_columnconfigure(1, weight=3, minsize=590)
        card.grid_rowconfigure(2, weight=1)

        left = ctk.CTkFrame(card, fg_color="transparent")
        self.activity_status_panel = left
        left.grid(row=0, column=0, rowspan=3, sticky="nsew", padx=24, pady=22)
        left.grid_columnconfigure(0, weight=1)
        self.activity_eyebrow = self._eyebrow(left, "activity", BLUE)
        self.activity_eyebrow.grid(row=0, column=0, sticky="w")
        self.status_label = ctk.CTkLabel(
            left, text="", text_color=INK, font=self._font(20, "bold"), anchor="w",
        )
        self.status_label.grid(row=1, column=0, sticky="w", pady=(9, 3))
        self.detail_label = ctk.CTkLabel(
            left, text="", text_color=MUTED, font=self._font(11), anchor="w", wraplength=580,
        )
        self.detail_label.grid(row=2, column=0, sticky="w")
        self.speed_label = ctk.CTkLabel(left, text="", text_color=BLUE, font=self._font(10, "bold"), anchor="e")
        self.speed_label.grid(row=1, column=1, rowspan=2, sticky="e")
        self.progress = ctk.CTkProgressBar(
            left, height=10, corner_radius=5, fg_color=PILL, progress_color=BLUE,
        )
        self.progress.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(18, 0))
        self.progress.set(0)
        open_hint = ctk.CTkLabel(
            left, text="", text_color=MUTED, font=self._font(9), anchor="w",
        )
        self.open_file_hint = open_hint
        open_hint.grid(row=4, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self._translated(open_hint, "open_file_hint")

        queue_panel = ctk.CTkFrame(card, fg_color="transparent")
        self.queue_panel = queue_panel
        queue_panel.grid(row=0, column=1, rowspan=3, sticky="nsew", padx=(0, 20), pady=22)
        queue_panel.grid_columnconfigure(0, weight=1)
        queue_panel.grid_rowconfigure(1, weight=1)

        toolbar = ctk.CTkFrame(queue_panel, fg_color="transparent", height=40)
        self.queue_toolbar = toolbar
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self.selection_count_label = ctk.CTkLabel(
            toolbar, text="0 selected", text_color=MUTED, font=self._font(9, "bold"),
            width=88, anchor="w",
        )
        self.selection_count_label.pack(side="left", padx=(2, 6))
        self.select_all_button = ctk.CTkButton(
            toolbar, text=self._text("select_all"), width=92, height=34, corner_radius=10,
            fg_color=PILL, hover_color=LINE, text_color=INK, font=self._font(9, "bold"),
            command=self._select_all_queue_jobs,
        )
        self.select_all_button.pack(side="left", padx=3)
        self.clear_selection_button = ctk.CTkButton(
            toolbar, text=self._text("clear_selection"), width=86, height=34, corner_radius=10,
            fg_color=PILL, hover_color=LINE, text_color=INK, font=self._font(9, "bold"),
            command=self._clear_queue_selection,
        )
        self.clear_selection_button.pack(side="left", padx=3)
        self.bulk_delete_button = ctk.CTkButton(
            toolbar, text=self._text("bulk_delete"), width=84, height=34, corner_radius=10,
            fg_color=("#FFF0F0", "#3B2428"), hover_color=("#FFE0E0", "#513036"),
            text_color=("#D84C4C", "#FF8585"), font=self._font(9, "bold"),
            command=self._bulk_delete_selected, state="disabled",
        )
        self.bulk_delete_button.pack(side="right", padx=(4, 0))
        self.bulk_resume_button = ctk.CTkButton(
            toolbar, text=self._text("bulk_resume"), width=88, height=34, corner_radius=10,
            fg_color=GREEN, hover_color="#128866", font=self._font(9, "bold"),
            command=self._bulk_resume_selected, state="disabled",
        )
        self.bulk_resume_button.pack(side="right", padx=4)
        self.bulk_pause_button = ctk.CTkButton(
            toolbar, text=self._text("bulk_pause"), width=84, height=34, corner_radius=10,
            fg_color="#E8A126", hover_color="#CE8A18", font=self._font(9, "bold"),
            command=self._bulk_pause_selected, state="disabled",
        )
        self.bulk_pause_button.pack(side="right", padx=4)

        self.history = ctk.CTkScrollableFrame(
            queue_panel, fg_color=("#FAFAFB", "#121419"), corner_radius=15, border_width=1,
            border_color=LINE, height=260,
            scrollbar_button_color=("#D8D8DC", "#3A3E48"),
        )
        self.history.grid(row=1, column=0, sticky="nsew")

    def _build_footer(self, parent: Any) -> None:
        footer = ctk.CTkFrame(parent, fg_color="transparent", height=34)
        self.footer = footer
        footer.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(16, 0))
        footer.grid_columnconfigure(1, weight=1)
        ffmpeg_ready = self._media_tool("ffmpeg") is not None
        ff_key = "ffmpeg_ok" if ffmpeg_ready else "ffmpeg_missing"
        js_key = "js_ok" if self._javascript_runtime() else "js_missing"
        self.ffmpeg_pill = self._status_pill(footer, ff_key, GREEN if ffmpeg_ready else CORAL)
        self.ffmpeg_pill.grid(row=0, column=0, padx=(0, 8))
        self.js_pill = self._status_pill(footer, js_key, GREEN if self._javascript_runtime() else CORAL)
        self.js_pill.grid(row=0, column=1, sticky="w")
        privacy = ctk.CTkLabel(footer, text="", text_color=MUTED, font=self._font(9), anchor="e")
        self.privacy_label = privacy
        privacy.grid(row=0, column=2, sticky="e")
        self._translated(privacy, "privacy")

    def _status_pill(self, parent: Any, key: str, color: str) -> Any:
        frame = ctk.CTkFrame(parent, fg_color=PILL, corner_radius=12)
        dot = ctk.CTkLabel(frame, text="●", text_color=color, font=self._font(9), width=16)
        dot.pack(side="left", padx=(9, 0), pady=5)
        label = ctk.CTkLabel(frame, text="", text_color=MUTED, font=self._font(9, "bold"))
        label.pack(side="left", padx=(2, 10), pady=5)
        self._translated(label, key)
        return frame

    def _language_selected(self, value: str) -> None:
        self._set_language("fa" if value == "فا" else "en")

    def _theme_selected(self, value: str) -> None:
        mode = "dark" if value.lower() == "dark" else "light"
        ctk.set_appearance_mode(mode)
        self.job_store.set_preference("appearance_mode", mode)
        self.brand_logo.redraw()

    def _set_language(self, language: str) -> None:
        self.language = language
        self.job_store.set_preference("language", language)
        self.language_switch.set("فا" if language == "fa" else "EN")
        anchor = "e" if language == "fa" else "w"
        for widget, key in self.translatable:
            try:
                text = TEXT[language][key]
                if key == "version":
                    text = f"{text} · v{APP_VERSION}"
                widget.configure(text=text)
                if isinstance(widget, ctk.CTkLabel):
                    widget.configure(anchor=anchor)
                    if widget.winfo_manager() == "pack":
                        widget.pack_configure(anchor=anchor)
            except (tk.TclError, AttributeError):
                pass
        for menu, group, variable in self.option_controls:
            values = [data[language] for data in OPTIONS[group].values()]
            menu.configure(values=values)
            menu.set(OPTIONS[group][variable.get()][language])
        self.queue_signature = None
        if self.empty_queue_label is not None:
            self.empty_queue_label.configure(text=self._text("queue_empty"), anchor=anchor)
            self.empty_queue_label.pack_configure(anchor=anchor)
        if not self.worker or not self.worker.is_alive():
            self.status_label.configure(text=self._text("ready"), anchor=anchor)
            self.detail_label.configure(text=self._text("ready_detail"), anchor=anchor)
        if self.cookies_file.get():
            self.cookie_button.configure(text=Path(self.cookies_file.get()).name)
        for button, key in (
            (self.select_all_button, "select_all"),
            (self.clear_selection_button, "clear_selection"),
            (self.bulk_pause_button, "bulk_pause"),
            (self.bulk_resume_button, "bulk_resume"),
            (self.bulk_delete_button, "bulk_delete"),
        ):
            button.configure(text=self._text(key))
        self._apply_layout_direction(language == "fa")
        self._update_bulk_controls()
        if self.setup_window and self.setup_window.winfo_exists():
            self._render_setup_guide()

    def _apply_layout_direction(self, rtl: bool) -> None:
        edge = "e" if rtl else "w"

        for column in range(5):
            self.header.grid_columnconfigure(column, weight=0)
        self.header.grid_columnconfigure(3 if rtl else 1, weight=1)
        if rtl:
            self.brand_logo.grid_configure(column=4, sticky="e")
            self.version_label.grid_configure(column=3, sticky="e", padx=(0, 10))
            self.setup_button.grid_configure(column=2, sticky="w", padx=(8, 0))
            self.theme_switch.grid_configure(column=1, sticky="w", padx=(10, 0))
            self.language_switch.grid_configure(column=0, sticky="w")
        else:
            self.brand_logo.grid_configure(column=0, sticky="w")
            self.version_label.grid_configure(column=1, sticky="w", padx=(10, 0))
            self.setup_button.grid_configure(column=2, sticky="e", padx=(0, 8))
            self.theme_switch.grid_configure(column=3, sticky="e", padx=(0, 10))
            self.language_switch.grid_configure(column=4, sticky="e")

        if rtl:
            self.hero_card.grid_configure(column=1, columnspan=2, padx=(8, 0))
            self.output_card.grid_configure(column=0, padx=(0, 8))
            self.features_card.grid_configure(column=2, padx=(8, 0))
            self.access_card.grid_configure(column=1, padx=8)
            self.destination_card.grid_configure(column=0, padx=(0, 8))
        else:
            self.hero_card.grid_configure(column=0, columnspan=2, padx=(0, 8))
            self.output_card.grid_configure(column=2, padx=(8, 0))
            self.features_card.grid_configure(column=0, padx=(0, 8))
            self.access_card.grid_configure(column=1, padx=8)
            self.destination_card.grid_configure(column=2, padx=(8, 0))

        self.hero_heading_row.grid_columnconfigure(0, weight=0 if rtl else 1)
        self.hero_heading_row.grid_columnconfigure(1, weight=1 if rtl else 0)
        self.hero_title.grid_configure(column=1 if rtl else 0, sticky=edge)
        self.hero_subtitle.grid_configure(column=1 if rtl else 0, sticky=edge)
        self.hero_chips.grid_configure(column=0 if rtl else 1, sticky="w" if rtl else "e")
        self.hero_title.configure(anchor=edge)
        self.hero_subtitle.configure(anchor=edge)

        if rtl:
            self.paste_button.grid_configure(column=4, padx=(9, 0))
            self.clear_button.grid_configure(column=3)
            self.cancel_button.grid_configure(column=1, padx=(9, 10))
            self.download_button.grid_configure(column=0)
        else:
            self.paste_button.grid_configure(column=0, padx=(0, 9))
            self.clear_button.grid_configure(column=1)
            self.cancel_button.grid_configure(column=3, padx=(10, 9))
            self.download_button.grid_configure(column=4)

        for box in self.feature_checkboxes:
            box.grid_configure(sticky="e" if rtl else "w")
            if getattr(box, "_text_label", None) is not None:
                box.grid_columnconfigure(0, weight=1 if rtl else 0)
                box.grid_columnconfigure(2, weight=0 if rtl else 1)
                box._canvas.grid_configure(column=2 if rtl else 0, sticky="w" if rtl else "e")
                box._text_label.grid_configure(column=0 if rtl else 2, sticky="e" if rtl else "w")
                box._text_label.configure(
                    anchor="e" if rtl else "w",
                    justify=tk.RIGHT if rtl else tk.LEFT,
                )

        self.subtitle_lang_label.pack_forget()
        self.lang_entry.pack_forget()
        self.subtitle_lang_label.pack(side="right" if rtl else "left", padx=11)
        self.lang_entry.pack(side="left" if rtl else "right", padx=6, pady=6)

        if rtl:
            self.browse_button.grid_configure(column=1, padx=(6, 0))
            self.open_folder_button.grid_configure(column=0, padx=(0, 6))
            self.activity_card.grid_columnconfigure(0, weight=3, minsize=590)
            self.activity_card.grid_columnconfigure(1, weight=2, minsize=410)
            self.activity_status_panel.grid_configure(column=1, padx=22)
            self.activity_status_panel.grid_columnconfigure(0, weight=0)
            self.activity_status_panel.grid_columnconfigure(1, weight=1)
            self.queue_panel.grid_configure(column=0, padx=(18, 0))
            self.activity_eyebrow.grid_configure(column=1, sticky="e")
            self.status_label.grid_configure(column=1, sticky="e")
            self.detail_label.grid_configure(column=1, sticky="e")
            self.speed_label.grid_configure(column=0, sticky="w")
            self.open_file_hint.grid_configure(sticky="e")
        else:
            self.browse_button.grid_configure(column=0, padx=(0, 6))
            self.open_folder_button.grid_configure(column=1, padx=(6, 0))
            self.activity_card.grid_columnconfigure(0, weight=2, minsize=410)
            self.activity_card.grid_columnconfigure(1, weight=3, minsize=590)
            self.activity_status_panel.grid_configure(column=0, padx=22)
            self.activity_status_panel.grid_columnconfigure(0, weight=1)
            self.activity_status_panel.grid_columnconfigure(1, weight=0)
            self.queue_panel.grid_configure(column=1, padx=(0, 18))
            self.activity_eyebrow.grid_configure(column=0, sticky="w")
            self.status_label.grid_configure(column=0, sticky="w")
            self.detail_label.grid_configure(column=0, sticky="w")
            self.speed_label.grid_configure(column=1, sticky="e")
            self.open_file_hint.grid_configure(sticky="w")

        toolbar_widgets = (
            self.selection_count_label, self.select_all_button, self.clear_selection_button,
            self.bulk_delete_button, self.bulk_resume_button, self.bulk_pause_button,
        )
        for widget in toolbar_widgets:
            widget.pack_forget()
        if rtl:
            self.selection_count_label.pack(side="right", padx=(6, 2))
            self.select_all_button.pack(side="right", padx=3)
            self.clear_selection_button.pack(side="right", padx=3)
            self.bulk_delete_button.pack(side="left", padx=(0, 4))
            self.bulk_resume_button.pack(side="left", padx=4)
            self.bulk_pause_button.pack(side="left", padx=4)
        else:
            self.selection_count_label.pack(side="left", padx=(2, 6))
            self.select_all_button.pack(side="left", padx=3)
            self.clear_selection_button.pack(side="left", padx=3)
            self.bulk_delete_button.pack(side="right", padx=(4, 0))
            self.bulk_resume_button.pack(side="right", padx=4)
            self.bulk_pause_button.pack(side="right", padx=4)

        if rtl:
            self.ffmpeg_pill.grid_configure(column=2, padx=(8, 0))
            self.js_pill.grid_configure(column=1, sticky="e")
            self.privacy_label.grid_configure(column=0, sticky="w")
        else:
            self.ffmpeg_pill.grid_configure(column=0, padx=(0, 8))
            self.js_pill.grid_configure(column=1, sticky="w")
            self.privacy_label.grid_configure(column=2, sticky="e")

        textbox = getattr(self.url_text, "_textbox", None)
        if textbox is not None:
            textbox.tag_configure("direction", justify=tk.RIGHT if rtl else tk.LEFT)
            textbox.tag_add("direction", "1.0", "end")

    def _sync_url_text_direction(self, _event: Any = None) -> None:
        textbox = getattr(self.url_text, "_textbox", None)
        if textbox is not None:
            textbox.tag_configure("direction", justify=tk.RIGHT if self.language == "fa" else tk.LEFT)
            textbox.tag_add("direction", "1.0", "end")

    def _option_selected(self, group: str, variable: tk.StringVar, display: str) -> None:
        for option_id, labels in OPTIONS[group].items():
            if labels[self.language] == display:
                variable.set(option_id)
                if group == "browser":
                    self.job_store.set_preference("browser", option_id)
                return

    def _fade_in(self, opacity: float) -> None:
        try:
            self.attributes("-alpha", min(1.0, opacity))
            if opacity < 1:
                self.after(16, lambda: self._fade_in(opacity + 0.09))
        except tk.TclError:
            pass

    def _show_first_run_guide(self) -> None:
        if self.job_store.get_preference("onboarding_version") != "7":
            self._open_setup_guide()

    def _open_setup_guide(self) -> None:
        if self.setup_window and self.setup_window.winfo_exists():
            self.setup_window.lift()
            self.setup_window.focus_force()
            return
        self.setup_step = 0
        self.setup_window = ctk.CTkToplevel(self)
        self.setup_window.title(GUIDE_TEXT[self.language]["window"])
        self.setup_window.geometry("900x700")
        self.setup_window.minsize(840, 660)
        self.setup_window.transient(self)
        self.setup_window.grab_set()
        self.setup_window.protocol("WM_DELETE_WINDOW", self._complete_setup_guide)
        self._render_setup_guide()

    def _render_setup_guide(self) -> None:
        window = self.setup_window
        if not window or not window.winfo_exists():
            return
        for child in window.winfo_children():
            child.destroy()
        copy = GUIDE_TEXT[self.language]
        window.title(copy["window"])
        window.grid_columnconfigure(0, weight=1)
        window.grid_rowconfigure(2, weight=1)

        step_row = ctk.CTkFrame(window, fg_color="transparent")
        step_row.grid(row=0, column=0, sticky="ew", padx=34, pady=(26, 10))
        step_row.grid_columnconfigure((0, 1, 2, 3, 4), weight=1)
        for index, label in enumerate(copy["steps"]):
            active = index == self.setup_step
            display_column = len(copy["steps"]) - 1 - index if self.language == "fa" else index
            ctk.CTkLabel(
                step_row, text=f"{index + 1}  {label}", height=30, corner_radius=15,
                fg_color=BLUE if active else PILL,
                text_color="#FFFFFF" if active else MUTED,
                font=self._font(9, "bold"),
            ).grid(row=0, column=display_column, sticky="ew", padx=4)

        anchor = "e" if self.language == "fa" else "w"
        justify = "right" if self.language == "fa" else "left"
        title = ctk.CTkLabel(
            window, text=copy["titles"][self.setup_step], text_color=INK,
            font=self._font(22, "bold"), anchor=anchor, justify=justify,
        )
        title.grid(row=1, column=0, sticky="ew", padx=38, pady=(8, 4))

        content = self._card(window)
        content.grid(row=2, column=0, sticky="nsew", padx=34, pady=12)
        body = ctk.CTkLabel(
            content, text=copy["bodies"][self.setup_step], text_color=INK,
            font=self._font(13), anchor=anchor, justify=justify, wraplength=790,
        )
        body.pack(fill="x", padx=28, pady=(24, 16))

        if self.setup_step == 0:
            quick_start = (
                "1. Copy a video link.\n2. Paste it into the main window.\n"
                "3. Click Add to queue. Your file appears in the download folder.\n\n"
                "Try this first. Firefox cookies and Telegram are optional."
                if self.language == "en" else
                "۱. لینک ویدیو را کپی کنید.\n۲. در صفحه اصلی، دکمه چسباندن را بزنید.\n"
                "۳. افزودن به صف را بزنید؛ فایل در پوشه دانلود ذخیره می‌شود.\n\n"
                "ابتدا همین روش را امتحان کنید. کوکی و ربات تلگرام اختیاری هستند."
            )
            ctk.CTkLabel(
                content, text=quick_start, text_color=INK, font=self._font(13),
                anchor=anchor, justify=justify, wraplength=740,
            ).pack(fill="x", padx=28, pady=(0, 16))
            ctk.CTkLabel(
                content,
                text=("✓ No website login · No activation code" if self.language == "en" else "✓ بدون ورود به سایت · بدون کد فعال‌سازی"),
                text_color=GREEN, fg_color=("#EAF8F3", "#18342B"),
                corner_radius=12, height=42, font=self._font(11, "bold"),
            ).pack(fill="x", padx=28, pady=(4, 24))
        elif self.setup_step == 1:
            actions = ctk.CTkFrame(content, fg_color="transparent")
            actions.pack(fill="x", padx=28, pady=(4, 24))
            ctk.CTkButton(
                actions, text=copy["open_youtube"], height=42, corner_radius=14,
                fg_color=BLUE, hover_color=BLUE_HOVER, font=self._font(11, "bold"),
                command=lambda: self._open_in_firefox("https://www.youtube.com/"),
            ).pack(side="right" if self.language == "fa" else "left", padx=8)
            ctk.CTkButton(
                actions, text=copy["get_firefox"], height=42, corner_radius=14,
                fg_color=PILL, hover_color=LINE, text_color=INK, font=self._font(11, "bold"),
                command=lambda: webbrowser.open("https://www.mozilla.org/firefox/new/"),
            ).pack(side="right" if self.language == "fa" else "left", padx=8)
        elif self.setup_step == 2:
            warning = ctk.CTkLabel(
                content,
                text=("⚠  Never share cookies.txt" if self.language == "en" else "⚠  این فایل را هرگز به اشتراک نگذارید: cookies.txt"),
                text_color=("#A15C00", "#FFBE66"), fg_color=("#FFF4DE", "#3A2B17"),
                corner_radius=12, height=42, font=self._font(11, "bold"),
            )
            warning.pack(fill="x", padx=28, pady=(4, 12))
            actions = ctk.CTkFrame(content, fg_color="transparent")
            actions.pack(fill="x", padx=28, pady=(0, 8))
            ctk.CTkButton(
                actions, text=copy["use_firefox"], height=38, corner_radius=12,
                fg_color=GREEN, hover_color="#128866", font=self._font(10, "bold"),
                command=self._use_firefox_cookies,
            ).pack(side="right" if self.language == "fa" else "left", padx=6)
            ctk.CTkButton(
                actions, text=copy["check_firefox"], height=38, corner_radius=12,
                fg_color=PILL, hover_color=LINE, text_color=INK, font=self._font(10, "bold"),
                command=self._check_firefox_login,
            ).pack(side="right" if self.language == "fa" else "left", padx=6)
            ctk.CTkButton(
                actions, text=copy["choose_cookie_file"], height=38, corner_radius=12,
                fg_color=PILL, hover_color=LINE, text_color=INK, font=self._font(10, "bold"),
                command=self._choose_advanced_cookie_file,
            ).pack(side="right" if self.language == "fa" else "left", padx=6)
            self.firefox_setup_status = ctk.CTkLabel(
                content, text="", text_color=MUTED, anchor=anchor, font=self._font(10),
            )
            self.firefox_setup_status.pack(fill="x", padx=28, pady=(3, 18))
        elif self.setup_step == 3:
            warning = ctk.CTkLabel(
                content,
                text=("⚠  A cookies file can grant access to your account — keep it private"
                      if self.language == "en" else "⚠  فایل کوکی، کلید ورود به حساب شماست؛ آن را برای کسی نفرستید"),
                text_color=("#A15C00", "#FFBE66"), fg_color=("#FFF4DE", "#3A2B17"),
                corner_radius=12, height=42, font=self._font(11, "bold"),
            )
            warning.pack(fill="x", padx=28, pady=(4, 12))
            actions = ctk.CTkFrame(content, fg_color="transparent")
            actions.pack(fill="x", padx=28, pady=(0, 8))
            ctk.CTkButton(
                actions, text=copy["choose_cookie_file"], height=40, corner_radius=12,
                fg_color=GREEN, hover_color="#128866", font=self._font(10, "bold"),
                command=self._choose_advanced_cookie_file,
            ).pack(side="right" if self.language == "fa" else "left", padx=6)
            ctk.CTkButton(
                actions, text=copy["official_cookie_guide"], height=40, corner_radius=12,
                fg_color=PILL, hover_color=LINE, text_color=INK, font=self._font(10, "bold"),
                command=lambda: webbrowser.open("https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies"),
            ).pack(side="right" if self.language == "fa" else "left", padx=6)
            self.firefox_setup_status = ctk.CTkLabel(
                content, text="", text_color=MUTED, anchor=anchor, font=self._font(10),
            )
            self.firefox_setup_status.pack(fill="x", padx=28, pady=(3, 18))
        else:
            form = ctk.CTkFrame(content, fg_color="transparent")
            form.pack(fill="x", padx=28, pady=(0, 8))
            ctk.CTkLabel(form, text=copy["token"], text_color=INK, anchor=anchor,
                         font=self._font(11, "bold")).pack(fill="x", pady=(0, 3))
            self.telegram_token_entry = ctk.CTkEntry(
                form, height=38, corner_radius=11, show="•", placeholder_text=copy["token_hint"],
                fg_color=PILL, border_width=0, text_color=INK, font=self._font(11),
            )
            self.telegram_token_entry.pack(fill="x", pady=(0, 9))
            ctk.CTkLabel(form, text=copy["chat_id"], text_color=INK, anchor=anchor,
                         font=self._font(11, "bold")).pack(fill="x", pady=(0, 3))
            self.telegram_chat_entry = ctk.CTkEntry(
                form, height=38, corner_radius=11, placeholder_text=copy["chat_hint"],
                fg_color=PILL, border_width=0, text_color=INK, font=self._font(11),
            )
            saved_chat = self.job_store.get_preference("telegram_chat_id")
            if saved_chat:
                self.telegram_chat_entry.insert(0, saved_chat)
            self.telegram_chat_entry.pack(fill="x", pady=(0, 9))
            actions = ctk.CTkFrame(form, fg_color="transparent")
            actions.pack(fill="x")
            self.telegram_detect_button = ctk.CTkButton(
                actions, text=copy["detect"], height=36, corner_radius=11,
                fg_color=PILL, hover_color=LINE, text_color=INK, font=self._font(10, "bold"),
                command=self._detect_telegram_id,
            )
            self.telegram_detect_button.pack(side="right" if self.language == "fa" else "left", padx=6)
            ctk.CTkButton(
                actions, text=copy["save"], height=36, corner_radius=11,
                fg_color=GREEN, hover_color="#128866", font=self._font(10, "bold"),
                command=self._save_telegram_setup,
            ).pack(side="right" if self.language == "fa" else "left", padx=6)
            ctk.CTkButton(
                actions, text=copy["disable"], height=36, corner_radius=11,
                fg_color=("#FFF0F0", "#3B2428"), hover_color=("#FFE0E0", "#513036"),
                text_color=("#D84C4C", "#FF8585"), font=self._font(10, "bold"),
                command=self._disable_telegram_setup,
            ).pack(side="left" if self.language == "fa" else "right")
            self.telegram_setup_status = ctk.CTkLabel(
                form, text="", text_color=MUTED, anchor=anchor, font=self._font(9),
            )
            self.telegram_setup_status.pack(fill="x", pady=(8, 0))

        footer = ctk.CTkFrame(window, fg_color="transparent")
        footer.grid(row=3, column=0, sticky="ew", padx=34, pady=(4, 26))
        footer.grid_columnconfigure(1, weight=1)
        ctk.CTkButton(
            footer, text="Start downloading" if self.language == "en" else "شروع دانلود",
            width=150, height=38, corner_radius=12,
            fg_color=PILL, hover_color=LINE, text_color=INK, font=self._font(11, "bold"),
            command=self._complete_setup_guide,
        ).grid(row=0, column=1)
        back = ctk.CTkButton(
            footer, text=copy["back"], width=96, height=38, corner_radius=12,
            fg_color=PILL, hover_color=LINE, text_color=INK, font=self._font(11, "bold"),
            command=lambda: self._change_setup_step(-1),
            state="disabled" if self.setup_step == 0 else "normal",
        )
        back.grid(row=0, column=2 if self.language == "fa" else 0,
                  sticky="e" if self.language == "fa" else "w")
        next_text = copy["done"] if self.setup_step == 4 else copy["next"]
        ctk.CTkButton(
            footer, text=next_text, width=110, height=38, corner_radius=12,
            fg_color=BLUE, hover_color=BLUE_HOVER, font=self._font(11, "bold"),
            command=self._complete_setup_guide if self.setup_step == 4 else lambda: self._change_setup_step(1),
        ).grid(row=0, column=0 if self.language == "fa" else 2,
               sticky="w" if self.language == "fa" else "e")

    def _change_setup_step(self, direction: int) -> None:
        self.setup_step = max(0, min(4, self.setup_step + direction))
        self._render_setup_guide()

    def _complete_setup_guide(self) -> None:
        self.job_store.set_preference("onboarding_version", "7")
        if self.setup_window and self.setup_window.winfo_exists():
            self.setup_window.grab_release()
            self.setup_window.destroy()
        self.setup_window = None

    @staticmethod
    def _firefox_executable() -> Path | None:
        candidates: list[Path] = []
        located = shutil.which("firefox")
        if located:
            candidates.append(Path(located))
        for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            root = os.environ.get(variable)
            if root:
                candidates.append(Path(root) / "Mozilla Firefox" / "firefox.exe")
        return next((path for path in candidates if path.is_file()), None)

    def _open_in_firefox(self, url: str) -> None:
        executable = self._firefox_executable()
        if not executable:
            webbrowser.open("https://www.mozilla.org/firefox/new/")
            messagebox.showinfo(
                APP_NAME,
                ("Firefox was not found, so the official Firefox download page was opened."
                 if self.language == "en" else
                 "این مرورگر پیدا نشد و صفحه رسمی دانلود آن باز شد: Firefox"),
                parent=self.setup_window or self,
            )
            return
        try:
            subprocess.Popen(
                [str(executable), "-new-tab", url],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            message = (f"Could not open Firefox:\n{exc}" if self.language == "en" else
                       f"این مرورگر باز نشد: Firefox\n{exc}")
            messagebox.showerror(APP_NAME, message, parent=self.setup_window or self)

    @staticmethod
    def _has_firefox_login_cookies() -> bool:
        appdata = os.environ.get("APPDATA")
        if not appdata:
            return False
        profiles = Path(appdata) / "Mozilla" / "Firefox" / "Profiles"
        if not profiles.is_dir():
            return False
        auth_names = (
            "SAPISID", "APISID", "SID", "HSID", "SSID", "LOGIN_INFO",
            "__Secure-1PAPISID", "__Secure-3PAPISID",
        )
        placeholders = ",".join("?" for _ in auth_names)
        query = (
            "SELECT 1 FROM moz_cookies "
            "WHERE (host LIKE '%.youtube.com' OR host LIKE '%.google.com') "
            f"AND name IN ({placeholders}) LIMIT 1"
        )
        for path in profiles.glob("*/cookies.sqlite"):
            try:
                uri = path.resolve().as_uri() + "?mode=ro"
                connection = sqlite3.connect(uri, uri=True, timeout=1)
                try:
                    if connection.execute(query, auth_names).fetchone():
                        return True
                finally:
                    connection.close()
            except (OSError, sqlite3.Error):
                continue
        return False

    def _set_firefox_browser(self) -> None:
        self.browser.set("firefox")
        self.cookies_file.set("")
        self.job_store.set_preference("browser", "firefox")
        self.job_store.set_preference("cookie_file", "")
        self.cookie_button.configure(text=self._text("choose"))
        for menu, group, variable in self.option_controls:
            if group == "browser":
                variable.set("firefox")
                menu.set(OPTIONS["browser"]["firefox"][self.language])

    def _use_firefox_cookies(self) -> None:
        self._set_firefox_browser()
        key = "firefox_ready" if self._has_firefox_login_cookies() else "firefox_missing"
        color = GREEN if key == "firefox_ready" else CORAL
        self.firefox_setup_status.configure(text=GUIDE_TEXT[self.language][key], text_color=color)

    def _check_firefox_login(self) -> None:
        key = "firefox_ready" if self._has_firefox_login_cookies() else "firefox_missing"
        color = GREEN if key == "firefox_ready" else CORAL
        self.firefox_setup_status.configure(text=GUIDE_TEXT[self.language][key], text_color=color)

    def _choose_advanced_cookie_file(self) -> None:
        self._choose_cookies_file()
        if self.cookies_file.get():
            self.firefox_setup_status.configure(
                text=Path(self.cookies_file.get()).name, text_color=GREEN,
            )

    def _detect_telegram_id(self) -> None:
        token = self.telegram_token_entry.get().strip() or (load_bot_token() or "")
        copy = GUIDE_TEXT[self.language]
        self.telegram_setup_status.configure(text=copy["detecting"], text_color=MUTED)
        self.telegram_detect_button.configure(state="disabled")

        def worker() -> None:
            try:
                chat_id = detect_telegram_chat_id(token, self.proxy.get().strip(), self.language)
                result: tuple[bool, Any] = (True, chat_id)
            except Exception as exc:
                result = (False, str(exc))
            self.after(0, lambda: self._finish_telegram_detection(result))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_telegram_detection(self, result: tuple[bool, Any]) -> None:
        if not self.setup_window or not self.setup_window.winfo_exists() or self.setup_step != 4:
            return
        self.telegram_detect_button.configure(state="normal")
        if result[0]:
            self.telegram_chat_entry.delete(0, "end")
            self.telegram_chat_entry.insert(0, str(result[1]))
            chat_label = "✓ شناسه چت" if self.language == "fa" else "✓ Chat ID"
            self.telegram_setup_status.configure(text=f"{chat_label}: {result[1]}", text_color=GREEN)
        else:
            self.telegram_setup_status.configure(text=str(result[1]), text_color=CORAL)

    def _save_telegram_setup(self) -> None:
        token = self.telegram_token_entry.get().strip() or (load_bot_token() or "")
        chat_value = self.telegram_chat_entry.get().strip()
        if not valid_bot_token(token):
            self.telegram_setup_status.configure(
                text=("Enter a valid BotFather token." if self.language == "en" else
                      "یک توکن معتبر وارد کنید: BotFather"),
                text_color=CORAL,
            )
            return
        try:
            chat_id = int(chat_value)
            if chat_id <= 0:
                raise ValueError
        except ValueError:
            self.telegram_setup_status.configure(
                text=("Enter a positive numeric Telegram chat ID." if self.language == "en" else
                      "شناسه عددی و مثبت چت تلگرام را وارد کنید."),
                text_color=CORAL,
            )
            return
        try:
            save_bot_token(token)
        except OSError as exc:
            message = (f"Could not encrypt the token: {exc}" if self.language == "en" else
                       f"رمزگذاری توکن انجام نشد: {exc}")
            self.telegram_setup_status.configure(text=message, text_color=CORAL)
            return
        self.job_store.set_preference("telegram_chat_id", str(chat_id))
        self.job_store.set_preference("telegram_enabled", "1")
        self._stop_telegram_bot()
        self._start_telegram_bot()
        self.telegram_token_entry.delete(0, "end")
        self.telegram_setup_status.configure(text=GUIDE_TEXT[self.language]["saved"], text_color=GREEN)

    def _disable_telegram_setup(self) -> None:
        self.job_store.set_preference("telegram_enabled", "0")
        self.job_store.set_preference("telegram_chat_id", "")
        self._stop_telegram_bot()
        try:
            BOT_TOKEN_FILE.unlink(missing_ok=True)
        except OSError:
            pass
        self.telegram_token_entry.delete(0, "end")
        self.telegram_chat_entry.delete(0, "end")
        self.telegram_setup_status.configure(
            text=GUIDE_TEXT[self.language]["disabled"], text_color=MUTED,
        )

    def _paste(self) -> None:
        try:
            value = self.clipboard_get().strip()
        except tk.TclError:
            return
        self._insert_dropped_text(value)

    def _configure_drop_target(self) -> None:
        if not self.dnd_available:
            return
        self.drop_target_register(DND_TEXT, DND_FILES)
        self.dnd_bind("<<DropEnter>>", self._drop_enter)
        self.dnd_bind("<<DropLeave>>", self._drop_leave)
        self.dnd_bind("<<Drop>>", self._drop_links)

    def _drop_enter(self, _event: Any) -> str:
        self.url_text.configure(border_width=2, border_color=BLUE)
        return COPY

    def _drop_leave(self, _event: Any) -> str:
        self.url_text.configure(border_width=1, border_color="#333337")
        return COPY

    def _drop_links(self, event: Any) -> str:
        self._drop_leave(event)
        data = str(getattr(event, "data", "") or "")
        text_parts = [data]
        try:
            items = self.tk.splitlist(data)
        except tk.TclError:
            items = ()
        for item in items:
            path = Path(item)
            if path.is_file() and path.suffix.lower() == ".url":
                try:
                    text_parts.append(path.read_text(encoding="utf-8", errors="ignore"))
                except OSError:
                    pass
        self._insert_dropped_text("\n".join(text_parts))
        return COPY

    def _insert_dropped_text(self, value: str) -> None:
        urls = [
            match.rstrip(".,);]}'\"")
            for match in re.findall(r"https?://[^\s<>{}]+", value, re.IGNORECASE)
        ]
        if not urls:
            return
        existing_text = self.url_text.get("1.0", "end")
        existing = [
            match.rstrip(".,);]}'\"")
            for match in re.findall(r"https?://[^\s<>{}]+", existing_text, re.IGNORECASE)
        ]
        combined = list(dict.fromkeys([*existing, *urls]))
        self.url_text.delete("1.0", "end")
        self.url_text.insert("1.0", "\n".join(combined))
        self.status_label.configure(text=self._text("dropped_added").format(count=len(urls)))
        self.detail_label.configure(text=self._text("review_links"))

    def _clear_urls(self) -> None:
        self.url_text.delete("1.0", "end")

    def _choose_folder(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.download_dir.get() or str(Path.home()))
        if chosen:
            self.download_dir.set(chosen)

    def _open_folder(self) -> None:
        folder = Path(self.download_dir.get()).expanduser()
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)  # type: ignore[attr-defined]

    def _choose_cookies_file(self) -> None:
        chosen = filedialog.askopenfilename(
            title=("Choose a Netscape cookies file" if self.language == "en" else
                   "انتخاب فایل کوکی با فرمت Netscape"),
            filetypes=([("Cookies text file", "*.txt"), ("All files", "*.*")]
                       if self.language == "en" else
                       [("فایل متنی کوکی", "*.txt"), ("همه فایل‌ها", "*.*")]),
            parent=self.setup_window or self,
        )
        if chosen:
            self.cookies_file.set(chosen)
            self.cookie_button.configure(text=Path(chosen).name)
            self.job_store.set_preference("cookie_file", chosen)

    def _sync_subtitle_controls(self) -> None:
        state = "normal" if (self.subtitles.get() or self.auto_subtitles.get()) else "disabled"
        self.lang_entry.configure(state=state)

    def _toggle_completion_sound(self) -> None:
        self.job_store.set_preference(
            "completion_sound", "1" if self.completion_sound.get() else "0"
        )

    def _play_completion_sound(self) -> None:
        if not self.completion_sound.get() or winsound is None:
            return
        try:
            winsound.PlaySound(
                "SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC
            )
        except RuntimeError:
            pass

    def _persist_proxy(self, _event: Any = None) -> None:
        try:
            proxy = validate_proxy_url(self.proxy.get())
        except ValueError:
            self.proxy_entry.configure(border_width=1, border_color=CORAL)
            return
        self.proxy_entry.configure(border_width=0)
        self.proxy.set(proxy)
        self.job_store.set_preference("download_proxy", proxy)

    def _valid_urls(self) -> list[str]:
        raw = self.url_text.get("1.0", "end").splitlines()
        urls = [line.strip() for line in raw if line.strip()]
        if any(not url.lower().startswith(("http://", "https://")) for url in urls):
            raise ValueError("Every line must be a full http:// or https:// link.")
        return list(dict.fromkeys(urls))

    def _capture_settings(self) -> DownloadSettings:
        return DownloadSettings(
            target=Path(self.download_dir.get()).expanduser(), mode=self.mode.get(),
            quality=self.quality.get(), playlist=self.playlist.get(),
            subtitles=self.subtitles.get(), auto_subtitles=self.auto_subtitles.get(),
            subtitle_langs=self.subtitle_langs.get(), thumbnail=self.thumbnail.get(),
            embed_thumbnail=self.embed_thumbnail.get(), metadata=self.metadata.get(),
            description=self.description.get(), browser=self.browser.get(),
            cookie_file=self.cookies_file.get(), proxy=self.proxy.get().strip(),
        )

    def _start_download(self) -> None:
        if yt_dlp is None:
            messagebox.showerror(APP_NAME, "Dependencies are missing. Close the app and run setup.ps1.")
            return
        try:
            urls = self._valid_urls()
        except ValueError as exc:
            messagebox.showwarning(APP_NAME, str(exc))
            return
        if not urls:
            messagebox.showinfo(APP_NAME, self._text("ready_detail"))
            return
        settings = self._capture_settings()
        try:
            proxy = validate_proxy_url(settings.proxy)
        except ValueError as exc:
            messagebox.showerror(APP_NAME, str(exc))
            self.proxy_entry.focus_set()
            return
        self.job_store.set_preference("download_proxy", proxy)
        self.job_store.set_preference("browser", settings.browser)
        self.job_store.set_preference("cookie_file", settings.cookie_file)
        try:
            settings.target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Cannot use that download folder:\n{exc}")
            return
        if settings.cookie_file:
            cookie_path = Path(settings.cookie_file).expanduser()
            if not cookie_path.is_file():
                messagebox.showerror(APP_NAME, "The selected cookies file no longer exists.")
                return
            try:
                with cookie_path.open("r", encoding="utf-8-sig") as stream:
                    first_line = stream.readline().strip()
            except OSError as exc:
                messagebox.showerror(APP_NAME, f"Cannot read the selected cookies file:\n{exc}")
                return
            if first_line not in ("# Netscape HTTP Cookie File", "# HTTP Cookie File"):
                messagebox.showerror(APP_NAME, "Select a Netscape-format cookies.txt file.")
                return

        identifiers: list[int] = []
        playlist_count = 0
        for url in urls:
            payload = desktop_settings_for_url(settings, url)
            playlist_count += int(bool(payload["playlist"]))
            identifiers.extend(self.job_store.add_jobs([url], payload, source="desktop"))
        self._clear_urls()
        self.status_label.configure(text=self._text("queue_added").format(count=len(identifiers)))
        detail = self._text("one_at_time")
        if playlist_count:
            detail += " · " + self._text("playlists_detected").format(count=playlist_count)
        self.detail_label.configure(text=detail)
        self.queue_signature = None
        self._ensure_queue_worker()

    def _cancel_download(self) -> None:
        if self.current_job_id is not None:
            self._pause_queue_job(self.current_job_id)

    def _ensure_queue_worker(self, jobs: list[dict[str, Any]] | None = None) -> None:
        if self.worker and self.worker.is_alive():
            return
        jobs = jobs if jobs is not None else self.job_store.list_jobs()
        if any(job["status"] in {"downloading", "processing", "expanding"} for job in jobs):
            return
        if any(job["status"] == "queued" for job in jobs):
            self.worker = threading.Thread(target=self._download_worker, daemon=True)
            self.worker.start()

    @staticmethod
    def _javascript_runtime() -> tuple[str, str] | None:
        for name in ("node", "deno"):
            bundled = APP_DIR / "tools" / f"{name}.exe"
            if bundled.is_file():
                return name, str(bundled)
        for name in ("deno", "node"):
            if path := shutil.which(name):
                return name, path
        return None

    @staticmethod
    def _media_tool(name: str) -> Path | None:
        """Find FFmpeg tools even when WinGet's link is missing from PATH."""
        bundled = APP_DIR / "tools" / f"{name}.exe"
        if bundled.is_file():
            return bundled
        if resolved := shutil.which(name):
            return Path(resolved)
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            return None
        winget_root = Path(local_app_data) / "Microsoft" / "WinGet"
        linked = winget_root / "Links" / f"{name}.exe"
        if linked.is_file():
            return linked
        packages = winget_root / "Packages"
        try:
            matches = list(
                packages.glob(f"Gyan.FFmpeg_*/ffmpeg-*/bin/{name}.exe")
            )
        except OSError:
            return None
        return max(matches, key=lambda path: path.stat().st_mtime) if matches else None

    @staticmethod
    def _format_selector(settings: DownloadSettings) -> str:
        if settings.mode == "audio":
            return "bestaudio/best"
        height = "" if settings.quality == "best" else f"[height<={settings.quality}]"
        if settings.mode == "premiere":
            if settings.quality == "best":
                return "bestvideo*+bestaudio/best"
            exact_height = f"[height={settings.quality}]"
            h264_video = (
                "bestvideo[vcodec~='^(avc1|h264)'][ext=mp4]"
            )
            aac_audio = "bestaudio[acodec~='^(mp4a|aac)'][ext=m4a]"
            h264_combined = (
                "best[ext=mp4][vcodec~='^(avc1|h264)']"
                "[acodec~='^(mp4a|aac)']"
            )
            exact_fallback = (
                f"bestvideo*{exact_height}+bestaudio/"
                f"best{exact_height}"
            )
            return (
                f"{h264_video}{exact_height}+{aac_audio}/"
                f"{h264_combined}{exact_height}/"
                f"{exact_fallback}/"
                f"{h264_video}{height}+{aac_audio}/"
                f"{h264_combined}{height}/"
                f"bestvideo*{height}+bestaudio/best{height}/best"
            )
        if settings.quality == "best":
            return "bestvideo*+bestaudio/best"
        return f"bestvideo*{height}+bestaudio/best{height}/best"

    @staticmethod
    def _subtitle_languages(settings: DownloadSettings) -> list[str]:
        value = settings.subtitle_langs.strip()
        if not value or value.lower() == "all":
            return ["all"]
        return [part.strip() for part in value.split(",") if part.strip()]

    def _ydl_options(self, settings: DownloadSettings, logger: DownloadLogger | None = None,
                     use_cookies: bool = True) -> dict[str, Any]:
        processors: list[dict[str, Any]] = []
        if settings.mode == "audio":
            processors.append({"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "0"})
        if settings.metadata:
            processors.append({"key": "FFmpegMetadata", "add_metadata": True})
        if settings.embed_thumbnail:
            processors.append({"key": "EmbedThumbnail"})
        options: dict[str, Any] = {
            "format": self._format_selector(settings),
            "paths": {"home": str(settings.target)},
            "outtmpl": {"default": "%(playlist_title,channel|Collection)s/%(title)s [%(id)s].%(ext)s"},
            "noplaylist": not settings.playlist, "windowsfilenames": True, "continuedl": True,
            "retries": 10, "fragment_retries": 10, "concurrent_fragment_downloads": 4,
            "ignoreerrors": "only_download", "progress_hooks": [self._progress_hook],
            "postprocessor_hooks": [self._postprocessor_hook],
            "writethumbnail": settings.thumbnail or settings.embed_thumbnail,
            "writedescription": settings.description, "writesubtitles": settings.subtitles,
            "writeautomaticsub": settings.auto_subtitles,
            "subtitleslangs": self._subtitle_languages(settings), "subtitlesformat": "srt/best",
            "quiet": True, "no_warnings": False, "postprocessors": processors,
        }
        if logger:
            options["logger"] = logger
        if runtime := self._javascript_runtime():
            name, path = runtime
            options["js_runtimes"] = {name: {"path": path}}
        if ffmpeg := self._media_tool("ffmpeg"):
            options["ffmpeg_location"] = str(ffmpeg.parent)
        if settings.mode != "audio":
            options["merge_output_format"] = "mp4"
        if use_cookies and settings.cookie_file:
            options["cookiefile"] = settings.cookie_file
        elif use_cookies and settings.browser != "none":
            options["cookiesfrombrowser"] = (settings.browser,)
        if settings.proxy:
            options["proxy"] = settings.proxy
        return options

    def _probe_media(self, path: Path) -> dict[str, Any]:
        ffprobe = self._media_tool("ffprobe")
        if not ffprobe:
            raise RuntimeError(
                "FFprobe is required for Premiere compatibility. Run setup.ps1 to install FFmpeg."
            )
        result = subprocess.run(
            [
                str(ffprobe), "-v", "error", "-show_entries",
                "stream=codec_type,codec_name,pix_fmt", "-of", "json", str(path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Could not inspect the downloaded video: {result.stderr.strip() or 'FFprobe failed'}"
            )
        return json.loads(result.stdout)

    def _premiere_compatible_output(self, path: Path) -> Path:
        """Return an H.264/yuv420p + AAC MP4, transcoding only when needed."""
        if path.suffix.lower() == ".mp4" and premiere_streams_compatible(
            self._probe_media(path)
        ):
            return path
        ffmpeg = self._media_tool("ffmpeg")
        if not ffmpeg:
            raise RuntimeError(
                "FFmpeg is required for Premiere compatibility. Run setup.ps1 first."
            )

        final_path = path.with_suffix(".mp4")
        if final_path != path and final_path.exists():
            final_path = path.with_name(f"{path.stem} [Premiere].mp4")
        temporary = final_path.with_name(
            f".{final_path.stem}.premiere-{os.getpid()}.tmp.mp4"
        )
        if self.current_job_id is not None:
            self.job_store.update(
                self.current_job_id,
                status="processing",
                detail="Creating Premiere-compatible H.264 MP4",
            )
        self.events.put(("processing", "Creating Premiere-compatible MP4"))
        command = [
            str(ffmpeg), "-y", "-i", str(path),
            "-map", "0:v:0", "-map", "0:a:0?", "-map_metadata", "0",
            "-sn", "-dn", "-c:v", "libx264", "-preset", "medium",
            "-crf", "18", "-profile:v", "high", "-pix_fmt", "yuv420p",
            "-fps_mode", "cfr", "-c:a", "aac", "-b:a", "192k",
            "-ar", "48000", "-movflags", "+faststart", str(temporary),
        ]
        LOGGER.info("Transcoding incompatible media for Premiere: %s", path)
        try:
            with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as error_log:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=error_log,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                while process.poll() is None:
                    if self.cancel_event.wait(0.2):
                        process.terminate()
                        try:
                            process.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            process.kill()
                        raise DownloadCancelled()
                if process.returncode != 0:
                    error_log.seek(0)
                    details = error_log.read()[-2000:].strip()
                    raise RuntimeError(
                        f"FFmpeg could not create a Premiere-compatible MP4: {details}"
                    )
            if not premiere_streams_compatible(self._probe_media(temporary)):
                raise RuntimeError("The converted file failed the Premiere compatibility check.")
            temporary.replace(final_path)
            if path != final_path:
                path.unlink(missing_ok=True)
            return final_path
        finally:
            temporary.unlink(missing_ok=True)

    def _apply_shared_connection_settings(
        self, job_id: int, settings: DownloadSettings
    ) -> DownloadSettings:
        payload = settings.to_payload()
        # Connection credentials can change while a job waits in the queue. Use
        # the current shared preferences at start time, including empty values,
        # so removing a bad proxy/cookie also removes it from older queued jobs.
        shared_proxy = self.job_store.get_preference("download_proxy")
        shared_cookie = self.job_store.get_preference("cookie_file")
        shared_browser = self.job_store.get_preference("browser", "none")
        if shared_browser not in OPTIONS["browser"]:
            shared_browser = "none"
        if shared_cookie and Path(shared_cookie).is_file():
            current_cookie = shared_cookie
            current_browser = "none"
        else:
            current_cookie = ""
            current_browser = shared_browser
        payload["proxy"] = shared_proxy
        payload["cookie_file"] = current_cookie
        payload["browser"] = current_browser
        changed = any(
            (
                settings.proxy != shared_proxy,
                settings.cookie_file != current_cookie,
                settings.browser != current_browser,
            )
        )
        if changed:
            self.job_store.set_settings(job_id, payload)
            return DownloadSettings.from_payload(payload)
        return settings

    def _firefox_retry_settings(
        self, job_id: int, settings: DownloadSettings
    ) -> DownloadSettings | None:
        profiles = Path(os.environ.get("APPDATA", "")) / "Mozilla" / "Firefox" / "Profiles"
        if settings.browser == "firefox" or settings.cookie_file:
            return None
        try:
            has_firefox_cookies = (
                profiles.is_dir() and any(profiles.glob("*/cookies.sqlite"))
            )
        except OSError:
            has_firefox_cookies = False
        if not has_firefox_cookies:
            return None
        payload = settings.to_payload()
        payload["browser"] = "firefox"
        payload["cookie_file"] = ""
        self.job_store.set_settings(job_id, payload)
        self.job_store.set_preference("browser", "firefox")
        return DownloadSettings.from_payload(payload)

    def _download_worker(self) -> None:
        while job := self.job_store.claim_next():
            job_id = int(job["id"])
            url = str(job["url"])
            self.current_job_id = job_id
            self.current_control = ""
            self.cancel_event.clear()
            self.output_candidates.clear()
            started_at = time.time() - 1
            self.events.put(("job", {"id": job_id, "url": url}))
            try:
                settings = DownloadSettings.from_payload(self.job_store.settings(job))
                settings = self._apply_shared_connection_settings(job_id, settings)
                if settings.playlist:
                    self.job_store.update(
                        job_id, status="expanding", detail="Reading complete playlist…"
                    )
                    self.events.put(("playlist_expanding", url))
                    entries = self._playlist_entries(url, settings)
                    latest = self.job_store.get(job_id)
                    control = str(latest.get("control", "")) if latest else "remove"
                    if control == "remove":
                        self.job_store.delete(job_id)
                        continue
                    if control == "pause":
                        self.job_store.update(job_id, status="paused", control="", detail="Playlist paused")
                        continue
                    if entries is None:
                        single_payload = settings.to_payload()
                        single_payload["playlist"] = False
                        settings = DownloadSettings.from_payload(single_payload)
                        self.job_store.set_settings(job_id, single_payload)
                        self.job_store.update(
                            job_id, status="downloading", detail="Single video detected"
                        )
                        self.events.put(("single_video", url))
                    elif not entries:
                        raise RuntimeError("No downloadable videos were found in this playlist.")
                    else:
                        child_settings = settings.to_payload()
                        child_settings["playlist"] = False
                        identifiers = self.job_store.replace_with_entries(
                            job_id, entries, child_settings
                        )
                        self.events.put(("playlist_expanded", len(identifiers)))
                        continue
                logger = DownloadLogger()
                try:
                    with yt_dlp.YoutubeDL(self._ydl_options(settings, logger)) as ydl:
                        result = ydl.download([url])
                except Exception as first_error:
                    if self.cancel_event.is_set():
                        raise DownloadCancelled()
                    if not (
                        logger.auth_error
                        or DownloadLogger.is_auth_message(str(first_error))
                        or DownloadLogger.is_cookie_access_message(str(first_error))
                    ):
                        raise
                    logger.error(str(first_error))
                    result = 1
                if self.cancel_event.is_set():
                    raise DownloadCancelled()
                if result != 0 and logger.auth_error:
                    retry_settings = self._firefox_retry_settings(job_id, settings)
                    if retry_settings is None:
                        reason = self._clean_error(
                            f"YouTube authentication required. Cookie fix: {self._cookie_help(settings)}."
                        )
                        self.job_store.update(job_id, status="failed", error=reason)
                        self.events.put(("job_error", (url, reason)))
                        continue
                    self.events.put(("cookie_retry", None))
                    retry_logger = DownloadLogger()
                    try:
                        with yt_dlp.YoutubeDL(self._ydl_options(retry_settings, retry_logger)) as ydl:
                            result = ydl.download([url])
                    except Exception as retry_error:
                        if self.cancel_event.is_set():
                            raise DownloadCancelled()
                        reason = (
                            f"Firefox authentication failed. {self._cookie_help(retry_settings)}. "
                            f"YouTube reported: {retry_error}"
                        )
                        self.job_store.update(job_id, status="failed", error=self._clean_error(reason))
                        self.events.put(("job_error", (url, self._clean_error(reason))))
                        continue
                    if result != 0:
                        reason = retry_logger.last_error or logger.last_error or "Download failed"
                        reason = f"Firefox authentication failed. YouTube reported: {reason}"
                        self.job_store.update(job_id, status="failed", error=self._clean_error(reason))
                        self.events.put(("job_error", (url, self._clean_error(reason))))
                        continue
                    settings = retry_settings
                if result == 0:
                    files = self._completed_outputs(settings.target, started_at)
                    if settings.mode == "premiere":
                        files = [
                            self._premiere_compatible_output(path)
                            for path in files
                            if path.suffix.lower() not in {".mp3", ".aac", ".m4a", ".wav", ".flac", ".ogg", ".opus"}
                        ]
                    self.job_store.update(
                        job_id, status="completed", progress=100, detail="Ready",
                        file_path="\n".join(str(path) for path in files),
                        file_size=sum(path.stat().st_size for path in files if path.is_file()),
                    )
                    self.events.put(("job_done", url))
                else:
                    reason = self._clean_error(logger.last_error or "Download failed")
                    self.job_store.update(job_id, status="failed", error=reason)
                    self.events.put(("job_error", (url, reason)))
            except DownloadCancelled:
                action = self.current_control
                latest = self.job_store.get(job_id)
                if latest and latest.get("control"):
                    action = str(latest["control"])
                if action == "remove":
                    self.job_store.delete(job_id)
                else:
                    self.job_store.update(
                        job_id, status="paused", control="", detail="Paused; partial file kept"
                    )
            except Exception as exc:
                LOGGER.exception("Queue job %s failed", job_id)
                if self.cancel_event.is_set():
                    action = self.current_control
                    if action == "remove":
                        self.job_store.delete(job_id)
                    else:
                        self.job_store.update(job_id, status="paused", control="", detail="Paused")
                else:
                    reason = self._clean_error(str(exc))
                    self.job_store.update(job_id, status="failed", error=reason)
                    self.events.put(("job_error", (url, reason)))
            finally:
                self.current_job_id = None
                self.current_control = ""
                self.events.put(("queue_changed", None))
        self.events.put(("finished", False))

    def _playlist_entries(
        self, url: str, settings: DownloadSettings
    ) -> list[tuple[str, str]] | None:
        logger = DownloadLogger()
        options: dict[str, Any] = {
            "extract_flat": "in_playlist", "skip_download": True, "noplaylist": False,
            "lazy_playlist": False, "quiet": True, "no_warnings": False,
            "ignoreerrors": True, "logger": logger,
        }
        if runtime := self._javascript_runtime():
            name, path = runtime
            options["js_runtimes"] = {name: {"path": path}}
        if settings.cookie_file:
            options["cookiefile"] = settings.cookie_file
        elif settings.browser != "none":
            options["cookiesfrombrowser"] = (settings.browser,)
        if settings.proxy:
            options["proxy"] = settings.proxy
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
        raw_entries = (info or {}).get("entries")
        if raw_entries is None:
            return None
        entries: list[tuple[str, str]] = []
        seen: set[str] = set()
        for entry in raw_entries:
            if not entry:
                continue
            item_url = entry.get("webpage_url") or entry.get("original_url") or entry.get("url")
            if item_url and not str(item_url).lower().startswith(("http://", "https://")):
                if entry.get("id") and "youtube" in str(entry.get("extractor_key", "youtube")).lower():
                    item_url = f"https://www.youtube.com/watch?v={entry['id']}"
            if not item_url or not str(item_url).lower().startswith(("http://", "https://")):
                continue
            item_url = str(item_url)
            if item_url in seen:
                continue
            seen.add(item_url)
            entries.append((item_url, str(entry.get("title") or entry.get("id") or "Playlist video")))
        return entries

    def _completed_outputs(self, target: Path, started_at: float) -> list[Path]:
        expanded: set[Path] = set()
        for candidate in self.output_candidates:
            expanded.add(candidate)
            for suffix in MEDIA_EXTENSIONS:
                expanded.add(candidate.with_suffix(suffix))
        existing = [path for path in expanded if path.is_file()]
        if existing:
            return sorted(set(existing), key=lambda path: path.stat().st_mtime)
        try:
            files = [
                path for path in target.rglob("*")
                if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS
                and path.stat().st_mtime >= started_at
            ]
        except OSError:
            return []
        return sorted(set(files), key=lambda path: path.stat().st_mtime)

    @staticmethod
    def _cookie_help(settings: DownloadSettings) -> str:
        if settings.cookie_file:
            return "export a fresh cookies.txt file and select it again"
        if settings.browser == "firefox":
            return (
                "sign in to YouTube in Firefox, close Firefox completely, then Resume; "
                "if it still fails, export fresh youtube.com cookies as a Netscape cookies.txt file"
            )
        if settings.browser in {"chrome", "edge", "brave", "opera", "vivaldi"}:
            return f"close every {settings.browser.title()} process, or select Firefox / cookies.txt"
        return "sign in with the selected browser or choose a valid cookies.txt file"

    @staticmethod
    def _clean_error(message: str) -> str:
        message = message.replace("ERROR: ", "").strip()
        return message[:250] + ("…" if len(message) > 250 else "")

    def _progress_hook(self, data: dict[str, Any]) -> None:
        self._sync_job_control()
        if self.cancel_event.is_set():
            raise DownloadCancelled()
        info = data.get("info_dict") or {}
        title = info.get("title") or info.get("id") or "Media"
        if data.get("status") == "downloading":
            downloaded = data.get("downloaded_bytes", 0)
            total = data.get("total_bytes") or data.get("total_bytes_estimate")
            percent = downloaded / total * 100 if total else None
            now = time.monotonic()
            if self.current_job_id is not None and now - self.last_progress_save >= 0.5:
                self.job_store.update(
                    self.current_job_id, progress=percent, title=title,
                    detail=f"{format_bytes(downloaded)} / {format_bytes(total) if total else '?'}",
                )
                self.last_progress_save = now
            # yt-dlp may call this hook many times per second.  Limiting UI events
            # avoids an ever-growing Tk event backlog without reducing DB accuracy.
            if now - self.last_progress_event >= 0.1:
                self.events.put(("progress", {
                    "title": title, "percent": percent,
                    "downloaded": downloaded, "total": total,
                    "speed": data.get("speed"), "eta": data.get("eta"),
                }))
                self.last_progress_event = now
        elif data.get("status") == "finished":
            filename = data.get("filename") or info.get("filepath")
            if filename:
                self.output_candidates.add(Path(filename))
            if self.current_job_id is not None:
                self.job_store.update(self.current_job_id, status="processing", title=title, detail="Processing")
            self.events.put(("processing", title))
        elif data.get("status") == "error":
            self.events.put(("item_error", title))

    def _postprocessor_hook(self, data: dict[str, Any]) -> None:
        self._sync_job_control()
        if self.cancel_event.is_set():
            raise DownloadCancelled()
        if data.get("status") == "started":
            self.events.put(("processing", (data.get("info_dict") or {}).get("title", "Media")))
        info = data.get("info_dict") or {}
        filename = info.get("filepath") or info.get("_filename")
        if filename:
            self.output_candidates.add(Path(filename))

    def _sync_job_control(self) -> None:
        now = time.monotonic()
        if self.current_job_id is None or now - self.last_control_check < 0.5:
            return
        self.last_control_check = now
        job = self.job_store.get(self.current_job_id)
        if job and job.get("control") in {"pause", "remove"}:
            self.current_control = str(job["control"])
            self.cancel_event.set()

    def _set_progress(self, percent: float, immediate: bool = False) -> None:
        self.progress_target = max(0.0, min(1.0, percent / 100))
        if immediate:
            self.progress_value = self.progress_target
            self.progress.set(self.progress_value)
            return
        if not self.progress_animating:
            self.progress_animating = True
            self.after(16, self._animate_progress)

    def _animate_progress(self) -> None:
        distance = self.progress_target - self.progress_value
        if abs(distance) < 0.002:
            self.progress_value = self.progress_target
            self.progress.set(self.progress_value)
            self.progress_animating = False
            return
        self.progress_value += distance * 0.18
        self.progress.set(self.progress_value)
        self.after(16, self._animate_progress)

    def _drain_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "job":
                    self.status_label.configure(text=self._text("downloading_current"))
                    self.detail_label.configure(text=payload["url"])
                    self.cancel_button.configure(state="normal")
                elif event == "playlist_expanding":
                    self.status_label.configure(text=self._text("reading_playlist"))
                    self.detail_label.configure(text=str(payload))
                    self.queue_signature = None
                elif event == "playlist_expanded":
                    self.status_label.configure(text=self._text("playlist_added").format(count=payload))
                    self.detail_label.configure(text=self._text("playlist_each"))
                    self.queue_signature = None
                elif event == "single_video":
                    self.status_label.configure(text=self._text("single_video"))
                    self.detail_label.configure(text=str(payload))
                elif event == "cookie_retry":
                    self.status_label.configure(text=self._text("cookie_retry"))
                    self.detail_label.configure(text=self._text("retry_detail"))
                elif event == "progress":
                    self.detail_label.configure(text=payload["title"])
                    if payload["percent"] is not None:
                        self._set_progress(payload["percent"])
                    total = f" / {format_bytes(payload['total'])}" if payload["total"] else ""
                    speed = f"{format_bytes(payload['speed'])}/s" if payload["speed"] else ""
                    self.speed_label.configure(
                        text=f"{format_bytes(payload['downloaded'])}{total}   {speed}   ETA {human_eta(payload['eta'])}"
                    )
                elif event == "processing":
                    self.status_label.configure(text=self._text("processing"))
                    self.detail_label.configure(text=str(payload))
                    self.speed_label.configure(text="")
                elif event == "item_error":
                    self.status_label.configure(text=self._text("item_skipped"))
                    self.detail_label.configure(text=str(payload))
                elif event == "job_done":
                    self.status_label.configure(text=self._text("download_completed"))
                    self.detail_label.configure(text=str(payload))
                    self._play_completion_sound()
                elif event == "job_error":
                    _, reason = payload
                    self.status_label.configure(text=self._text("download_failed"))
                    self.detail_label.configure(text=str(reason))
                elif event == "queue_changed":
                    self.queue_signature = None
                elif event == "finished":
                    self.cancel_button.configure(state="disabled")
                    self.speed_label.configure(text="")
                    self.status_label.configure(text=self._text("queue_idle"))
                    self.detail_label.configure(text=self._text("ready_detail"))
        except queue.Empty:
            pass
        self.after(100, self._drain_events)

    def _clear_queue_rows(self) -> None:
        for widgets in self.queue_rows.values():
            widgets["row"].destroy()
        self.queue_rows.clear()
        self.selection_vars.clear()
        if self.empty_queue_label is not None:
            self.empty_queue_label.destroy()
            self.empty_queue_label = None

    def _set_queue_row_selected(self, job_id: int, selected: bool) -> None:
        widgets = self.queue_rows.get(job_id)
        if not widgets:
            return
        widgets["row"].configure(
            fg_color=("#EAF4FF", "#202A38") if selected else CARD,
        )
        variable = self.selection_vars.get(job_id)
        if variable is not None and variable.get() != selected:
            variable.set(selected)

    def _selection_changed(self, job_id: int) -> None:
        variable = self.selection_vars.get(job_id)
        if variable is not None and variable.get():
            self.selected_job_ids.add(job_id)
        else:
            self.selected_job_ids.discard(job_id)
        self._set_queue_row_selected(job_id, job_id in self.selected_job_ids)
        self._update_bulk_controls()

    def _select_all_queue_jobs(self) -> None:
        self.selected_job_ids = set(self.queue_jobs_by_id)
        for job_id in self.queue_jobs_by_id:
            self._set_queue_row_selected(job_id, True)
        self._update_bulk_controls()

    def _clear_queue_selection(self) -> None:
        selected = tuple(self.selected_job_ids)
        self.selected_job_ids.clear()
        for job_id in selected:
            self._set_queue_row_selected(job_id, False)
        self._update_bulk_controls()

    def _update_bulk_controls(self) -> None:
        selected_jobs = [
            self.queue_jobs_by_id[job_id]
            for job_id in self.selected_job_ids
            if job_id in self.queue_jobs_by_id
        ]
        count = len(selected_jobs)
        self.selection_count_label.configure(
            text=self._text("selected_count").format(count=count),
        )
        pause_statuses = {"queued", "downloading", "processing", "expanding"}
        resume_statuses = {"paused", "failed", "cancelled"}
        self.bulk_pause_button.configure(
            state="normal" if any(job["status"] in pause_statuses for job in selected_jobs) else "disabled",
        )
        self.bulk_resume_button.configure(
            state="normal" if any(job["status"] in resume_statuses for job in selected_jobs) else "disabled",
        )
        self.bulk_delete_button.configure(state="normal" if count else "disabled")

    def _bulk_pause_selected(self) -> None:
        changed = self.job_store.pause_many(self.selected_job_ids)
        if self.current_job_id in changed:
            self.current_control = "pause"
            self.cancel_event.set()
        self._clear_queue_selection()
        self.queue_signature = None

    def _bulk_resume_selected(self) -> None:
        self.job_store.resume_many(self.selected_job_ids)
        self._clear_queue_selection()
        self.queue_signature = None
        self._ensure_queue_worker()

    def _bulk_delete_selected(self) -> None:
        count = len(self.selected_job_ids)
        if not count:
            return
        if not messagebox.askyesno(
            APP_NAME,
            f"Delete {count} selected queue item{'s' if count != 1 else ''}?",
            parent=self,
        ):
            return
        result = self.job_store.remove_many(self.selected_job_ids)
        if self.current_job_id in result["stopping"]:
            self.current_control = "remove"
            self.cancel_event.set()
        self._clear_queue_selection()
        self.queue_signature = None

    def _refresh_queue_view(self) -> None:
        jobs = self.job_store.list_jobs(500)
        self.queue_jobs_by_id = {int(job["id"]): job for job in jobs}
        self.selected_job_ids.intersection_update(self.queue_jobs_by_id)
        signature = tuple(
            (job["id"], job["status"], job["control"], job["file_path"])
            for job in jobs
        )
        if signature != self.queue_signature:
            self.queue_signature = signature
            self._clear_queue_rows()
            if not jobs:
                self.empty_queue_label = ctk.CTkLabel(
                    self.history, text=self._text("queue_empty"), text_color=MUTED,
                    font=self._font(10),
                )
                self.empty_queue_label.pack(anchor="e" if self.language == "fa" else "w", padx=8, pady=8)
            for job in jobs:
                self._add_queue_row(job)
        else:
            for job in jobs:
                self._update_queue_row(job)
        self._update_bulk_controls()
        active = next(
            (job for job in jobs if job["status"] in {"downloading", "processing", "expanding"}),
            None,
        )
        self.cancel_button.configure(state="normal" if active else "disabled")
        if not active:
            queued = sum(job["status"] == "queued" for job in jobs)
            paused = sum(job["status"] == "paused" for job in jobs)
            completed = sum(job["status"] == "completed" for job in jobs)
            failed = sum(job["status"] == "failed" for job in jobs)
            if queued:
                self.status_label.configure(text=self._text("preparing_next"))
                self.detail_label.configure(text=self._text("items_waiting").format(count=queued))
            elif jobs:
                summary = [
                    f"{count} {label}" for count, label in (
                        (completed, self._text("status_completed")),
                        (paused, self._text("status_paused")),
                        (failed, self._text("status_failed")),
                    ) if count
                ]
                self.status_label.configure(text=self._text("queue_idle"))
                self.detail_label.configure(text=" · ".join(summary) or self._text("no_pending"))
            else:
                self.status_label.configure(text=self._text("ready"))
                self.detail_label.configure(text=self._text("ready_detail"))
        self._ensure_queue_worker(jobs)
        self.after(1000, self._refresh_queue_view)

    def _queue_row_values(self, job: dict[str, Any]) -> tuple[str, str, str]:
        status = str(job["status"])
        display_status = "stopping" if job["control"] == "remove" else status
        colors = {
            "queued": BLUE, "downloading": CYAN, "processing": CYAN, "expanding": BLUE,
            "paused": "#D99716", "completed": GREEN, "failed": CORAL,
            "cancelled": CORAL, "stopping": CORAL,
        }
        badge_text = self._text(f"status_{display_status}")
        if status == "completed" and str(job.get("file_path") or "").strip():
            badge_text += "  ↗"
        if job["progress"] is not None and status in {"downloading", "processing"}:
            badge_text += f" {job['progress']:.0f}%"
        source_key = "source_telegram" if job["source"] == "telegram" else "source_desktop"
        source = self._text(source_key)
        label_text = f"{source} · {job['title'] or job['url']}"
        return badge_text, colors.get(display_status, MUTED), label_text

    def _add_queue_row(self, job: dict[str, Any]) -> None:
        status = str(job["status"])
        display_status = "stopping" if job["control"] == "remove" else status
        badge_text, badge_color, label_text = self._queue_row_values(job)
        row = ctk.CTkFrame(self.history, fg_color=CARD, corner_radius=11, height=54)
        row.pack(fill="x", pady=6, padx=3)
        job_id = int(job["id"])
        remove = ctk.CTkButton(
            row, text=self._text("delete_action"), width=78, height=36, corner_radius=10,
            fg_color=("#FFF0F0", "#3B2428"),
            hover_color=("#FFE0E0", "#513036"),
            text_color=("#D84C4C", "#FF8585"), font=self._font(9, "bold"),
            command=lambda value=job_id: self._remove_queue_job(value),
            state="disabled" if display_status == "stopping" else "normal",
        )
        rtl = self.language == "fa"
        action_side = "left" if rtl else "right"
        content_side = "right" if rtl else "left"
        remove.pack(side=action_side, padx=(9, 6) if rtl else (6, 9), pady=9)
        if status in {"queued", "downloading", "processing", "expanding"} and display_status != "stopping":
            action = ctk.CTkButton(
                row, text=self._text("pause_action"), width=78, height=36, corner_radius=10, fg_color="#E8A126",
                hover_color="#CE8A18", font=self._font(9, "bold"),
                command=lambda value=job_id: self._pause_queue_job(value),
            )
            action.pack(side=action_side, padx=3, pady=9)
        elif status in {"paused", "failed", "cancelled"}:
            action = ctk.CTkButton(
                row, text=self._text("resume_action"), width=82, height=36, corner_radius=10, fg_color=GREEN,
                hover_color="#128866", font=self._font(9, "bold"),
                command=lambda value=job_id: self._resume_queue_job(value),
            )
            action.pack(side=action_side, padx=3, pady=9)
        selected = job_id in self.selected_job_ids
        selection = tk.BooleanVar(value=selected)
        checkbox = ctk.CTkCheckBox(
            row, text="", variable=selection, width=28, height=28,
            checkbox_width=22, checkbox_height=22, corner_radius=6,
            border_width=2, fg_color=BLUE, hover_color=BLUE_HOVER,
            command=lambda value=job_id: self._selection_changed(value),
        )
        checkbox.pack(side=content_side, padx=(3, 9) if rtl else (9, 3), pady=9)
        self.selection_vars[job_id] = selection
        badge = ctk.CTkLabel(
            row, text=badge_text, text_color=badge_color, fg_color=PILL,
            corner_radius=9, width=134, height=36, font=self._font(9, "bold"),
        )
        badge.pack(side=content_side, padx=(9, 3) if rtl else (3, 9), pady=9)
        label = ctk.CTkLabel(
            row, text=label_text, text_color=INK, font=self._font(10),
            anchor="e" if rtl else "w", justify="right" if rtl else "left", wraplength=470,
        )
        label.pack(side=content_side, fill="x", expand=True, pady=9)
        if status == "completed" and str(job.get("file_path") or "").strip():
            for clickable in (row, badge, label):
                clickable.configure(cursor="hand2")
                clickable.bind(
                    "<Double-Button-1>",
                    lambda _event, value=job_id: self._open_queue_item(value),
                    add="+",
                )
        self.queue_rows[job_id] = {
            "row": row, "checkbox": checkbox, "badge": badge, "label": label,
        }
        self._set_queue_row_selected(job_id, selected)

    def _update_queue_row(self, job: dict[str, Any]) -> None:
        widgets = self.queue_rows.get(int(job["id"]))
        if not widgets:
            return
        badge_text, badge_color, label_text = self._queue_row_values(job)
        widgets["badge"].configure(text=badge_text, text_color=badge_color)
        widgets["label"].configure(text=label_text)
        self._set_queue_row_selected(int(job["id"]), int(job["id"]) in self.selected_job_ids)

    def _pause_queue_job(self, job_id: int) -> None:
        if self.job_store.pause(job_id) and self.current_job_id == job_id:
            self.current_control = "pause"
            self.cancel_event.set()
        self.queue_signature = None

    def _resume_queue_job(self, job_id: int) -> None:
        self.job_store.resume(job_id)
        self.queue_signature = None
        self._ensure_queue_worker()

    def _remove_queue_job(self, job_id: int) -> None:
        result = self.job_store.remove(job_id)
        if result == "stopping" and self.current_job_id == job_id:
            self.current_control = "remove"
            self.cancel_event.set()
        self.queue_signature = None

    def _open_queue_item(self, job_id: int) -> None:
        job = self.job_store.get(job_id)
        if not job:
            return
        paths = existing_output_paths(str(job.get("file_path") or ""))
        if paths:
            try:
                os.startfile(str(paths[0]))  # type: ignore[attr-defined]
            except OSError as exc:
                messagebox.showerror(APP_NAME, f"Could not open the downloaded file:\n{exc}")
            return
        if job.get("status") == "completed":
            messagebox.showwarning(
                APP_NAME,
                "The download is marked complete, but its file is no longer at the saved location.",
            )

    def _report_callback_exception(
        self,
        exc_type: type[BaseException],
        exc_value: BaseException,
        traceback: Any,
    ) -> None:
        LOGGER.error(
            "Unhandled interface error",
            exc_info=(exc_type, exc_value, traceback),
        )
        try:
            messagebox.showerror(
                APP_NAME,
                f"Something went wrong in the interface.\n\n"
                f"{exc_value}\n\nDetails were saved to {APP_LOG_FILE.name}.",
                parent=self,
            )
        except tk.TclError:
            pass

    def _close_bot_log(self) -> None:
        if not self.bot_log_stream:
            return
        try:
            self.bot_log_stream.flush()
            self.bot_log_stream.close()
        except OSError:
            pass
        self.bot_log_stream = None

    def _stop_telegram_bot(self) -> None:
        process = self.bot_process
        self.bot_process = None
        if process and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                except OSError:
                    pass
        self._close_bot_log()

    def _start_telegram_bot(self) -> None:
        bot_script = APP_DIR / "bot.py"
        frozen = getattr(sys, "frozen", False)
        if self.closing or (not frozen and not bot_script.is_file()):
            return
        if self.job_store.get_preference("telegram_enabled") != "1":
            return
        if self.bot_process and self.bot_process.poll() is None:
            return
        self.bot_process = None
        self._close_bot_log()
        token = load_bot_token()
        chat_id = self.job_store.get_preference("telegram_chat_id")
        if not token or not valid_bot_token(token) or not chat_id.isdigit() or int(chat_id) <= 0:
            LOGGER.warning("Telegram is enabled but its per-user configuration is incomplete")
            return
        environment = os.environ.copy()
        environment[BOT_TOKEN_ENV] = token
        environment[BOT_ALLOWED_CHAT_ENV] = chat_id
        try:
            log_mode = "w" if BOT_LOG_FILE.exists() and BOT_LOG_FILE.stat().st_size > 1_000_000 else "a"
            self.bot_log_stream = BOT_LOG_FILE.open(log_mode, encoding="utf-8")
            self.bot_process = subprocess.Popen(
                [sys.executable, "--telegram-bot"] if frozen else [sys.executable, str(bot_script)],
                cwd=str(APP_DIR),
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=self.bot_log_stream,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self.bot_started_at = time.monotonic()
            LOGGER.info("Telegram bot process started (pid=%s)", self.bot_process.pid)
            self.after(2500, self._check_telegram_bot)
        except OSError as exc:
            self._close_bot_log()
            LOGGER.exception("Could not start Telegram bot")
            messagebox.showerror(APP_NAME, f"Could not start the Telegram bot:\n{exc}")

    def _check_telegram_bot(self) -> None:
        if self.closing or not self.bot_process:
            return
        return_code = self.bot_process.poll()
        if return_code is None:
            if time.monotonic() - self.bot_started_at >= 60:
                self.bot_restart_attempts = 0
                self.bot_failure_notified = False
            self.after(5000, self._check_telegram_bot)
            return

        LOGGER.warning("Telegram bot process exited with code %s", return_code)
        self.bot_process = None
        self._close_bot_log()
        if self.bot_restart_attempts < 3:
            self.bot_restart_attempts += 1
            delay_seconds = 3 * (2 ** (self.bot_restart_attempts - 1))
            LOGGER.info(
                "Restarting Telegram bot in %s seconds (attempt %s/3)",
                delay_seconds,
                self.bot_restart_attempts,
            )
            self.after(delay_seconds * 1000, self._start_telegram_bot)
            return

        if not self.bot_failure_notified:
            self.bot_failure_notified = True
            messagebox.showerror(
                APP_NAME,
                f"The Telegram bot stopped after 3 restart attempts. "
                f"Your saved token was kept.\n"
                f"Check the proxy and {BOT_LOG_FILE.name}, then restart the app.",
            )

    def _on_close(self) -> None:
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(APP_NAME, "A download is active. Cancel it and exit?"):
                return
            self.cancel_event.set()
        self.closing = True
        self._stop_telegram_bot()
        self.destroy()


def main() -> None:
    configure_logging()
    try:
        instance_handle = acquire_single_instance()
    except OSError:
        LOGGER.exception("Could not create the single-instance guard")
        instance_handle = -1
    if instance_handle is None:
        if sys.platform == "win32":
            ctypes.windll.user32.MessageBoxW(
                0,
                f"{APP_NAME} is already running.",
                APP_NAME,
                0x40,
            )
        return
    if ctk is None:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(APP_NAME, "The UI dependency is missing. Run setup.ps1, then start the app again.")
        root.destroy()
        release_single_instance(instance_handle)
        return
    try:
        LOGGER.info("Application %s starting", APP_VERSION)
        register_local_fonts()
        preferred_mode = QueueStore(QUEUE_DB).get_preference("appearance_mode", "light")
        ctk.set_appearance_mode(preferred_mode if preferred_mode in {"light", "dark"} else "light")
        ctk.set_default_color_theme("blue")
        DownloaderApp().mainloop()
    except Exception:
        LOGGER.exception("Fatal application error")
        raise
    finally:
        LOGGER.info("Application stopped")
        release_single_instance(instance_handle)


if __name__ == "__main__":
    main()
