from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from download_config import bot_download_settings, format_bytes, has_playlist_parameter, is_collection_url
from queue_store import QueueStore
from app_paths import APP_NAME, QUEUE_DB


BOT_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
ALLOWED_CHAT_ENV = "TELEGRAM_ALLOWED_CHAT_ID"
TELEGRAM_FILE_LIMIT = 50 * 1024 * 1024
MAX_URLS_PER_MESSAGE = 25
URL_RE = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
STORE = QueueStore(QUEUE_DB)


def allowed_chat_id() -> int:
    raw = os.environ.get(ALLOWED_CHAT_ENV, "").strip()
    if not raw:
        raise RuntimeError(f"{ALLOWED_CHAT_ENV} is required")
    try:
        chat_id = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{ALLOWED_CHAT_ENV} must be a numeric Telegram chat ID") from exc
    if chat_id <= 0:
        raise RuntimeError(f"{ALLOWED_CHAT_ENV} must be a positive Telegram chat ID")
    return chat_id


def is_authorized(update: Update) -> bool:
    return bool(update.effective_chat and update.effective_chat.id == allowed_chat_id())


async def reject_unauthorized(update: Update) -> bool:
    if is_authorized(update):
        return False
    if update.callback_query:
        await update.callback_query.answer("This bot is private.", show_alert=True)
    elif update.effective_message:
        await update.effective_message.reply_text("This bot is private.")
    return True


def download_root() -> Path:
    configured = os.environ.get("TELEGRAM_DOWNLOAD_DIR")
    return Path(configured).expanduser() if configured else Path.home() / "Downloads" / "AIwithSaeed" / "Telegram"


def job_settings(mode: str, quality: str, playlist: bool = False) -> dict[str, Any]:
    payload = bot_download_settings(download_root(), mode, quality, playlist)
    payload["proxy"] = STORE.get_preference("download_proxy")
    payload["encoder"] = STORE.get_preference("video_encoder", "auto")
    cookie_file = STORE.get_preference("cookie_file")
    browser = STORE.get_preference("browser", "none")
    if cookie_file and Path(cookie_file).is_file():
        payload["cookie_file"] = cookie_file
    elif browser:
        payload["browser"] = browser
    return payload


def choice_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Premiere MP4 · Best", callback_data="get:premiere:best"),
            InlineKeyboardButton("Premiere · 1080p", callback_data="get:premiere:1080"),
        ],
        [
            InlineKeyboardButton("Premiere · 720p", callback_data="get:premiere:720"),
            InlineKeyboardButton("MP3", callback_data="get:audio:best"),
        ],
    ])


def playlist_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📚 Download full playlist", callback_data="scope:playlist"),
        InlineKeyboardButton("🎬 Only this video", callback_data="scope:single"),
    ]])


def queue_text_and_keyboard() -> tuple[str, InlineKeyboardMarkup | None]:
    jobs = STORE.list_jobs(20)
    if not jobs:
        return "📭 Queue is empty\n\nSend one or more links to add downloads.", None
    counts: dict[str, int] = {}
    for item_number, job in enumerate(jobs, 1):
        counts[str(job["status"])] = counts.get(str(job["status"]), 0) + 1
    summary = " · ".join(f"{name} {value}" for name, value in counts.items())
    lines = [f"📥 Shared download queue\n{summary}\n⚙️ One item downloads at a time"]
    buttons: list[list[InlineKeyboardButton]] = []
    for job in jobs:
        status = str(job["status"])
        progress = ""
        if status in {"downloading", "processing"} and job["progress"] is not None:
            progress = f" {job['progress']:.0f}%"
        title = job["title"] or job["url"]
        if len(title) > 55:
            title = title[:52] + "…"
        origin = "TG" if job["source"] == "telegram" else "PC"
        icons = {
            "queued": "⏳", "downloading": "⬇️", "processing": "⚙️", "expanding": "📚",
            "paused": "⏸️",
            "completed": "✅", "failed": "❌", "cancelled": "🚫",
        }
        lines.append(f"{icons.get(status, '•')} {item_number}. [{origin}] {status.upper()}{progress}\n{title}")
        job_id = int(job["id"])
        row: list[InlineKeyboardButton] = []
        if status in {"queued", "downloading", "processing", "expanding"}:
            row.append(InlineKeyboardButton(f"⏸ Pause {item_number}", callback_data=f"job:pause:{job_id}"))
        elif status in {"paused", "failed", "cancelled"}:
            row.append(InlineKeyboardButton(f"▶️ Resume {item_number}", callback_data=f"job:resume:{job_id}"))
        row.append(InlineKeyboardButton(f"🗑 Delete {item_number}", callback_data=f"job:remove:{job_id}"))
        buttons.append(row)
    buttons.append([InlineKeyboardButton("🔄 Refresh queue", callback_data="queue:refresh")])
    return "\n\n".join(lines), InlineKeyboardMarkup(buttons)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_unauthorized(update):
        return
    await update.effective_message.reply_text(
        "👋 Send one or several video or playlist links in one message.\n\n"
        "📥 They will appear immediately in the desktop queue.\n"
        "1️⃣ The app downloads one item at a time.\n"
        "🎛 Use /queue to pause, resume, delete, and refresh jobs.\n"
        "📦 Files below 50 MiB are sent here; larger files stay on your computer.\n\n"
        "Keep the desktop app open while downloading."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_unauthorized(update):
        return
    await update.effective_message.reply_text(
        "📋 /queue — shared queue and controls\n"
        "🔎 /status — queue status\n"
        "⏸ /cancel — pause the active item\n\n"
        "You can send up to 25 URLs in one message. Playlist links offer full-playlist or single-video mode."
    )


async def queue_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_unauthorized(update):
        return
    text, keyboard = queue_text_and_keyboard()
    await update.effective_message.reply_text(text, reply_markup=keyboard)


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_unauthorized(update):
        return
    active = next(
        (
            job for job in STORE.list_jobs()
            if job["status"] in {"downloading", "processing", "expanding"}
        ),
        None,
    )
    if not active:
        await update.effective_message.reply_text("ℹ️ No download is active.")
        return
    STORE.pause(int(active["id"]))
    await update.effective_message.reply_text("⏸ Pausing the current queue item…")


async def receive_urls(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_unauthorized(update):
        return
    matches = [value.rstrip(".,);]") for value in URL_RE.findall(update.effective_message.text or "")]
    urls = list(dict.fromkeys(matches))
    if not urls:
        await update.effective_message.reply_text("⚠️ Send at least one full http:// or https:// URL.")
        return
    if len(urls) > MAX_URLS_PER_MESSAGE:
        await update.effective_message.reply_text(f"Send no more than {MAX_URLS_PER_MESSAGE} URLs at once.")
        return
    context.chat_data["pending_urls"] = urls
    context.chat_data["pending_playlist"] = False
    context.chat_data["pending_needs_scope"] = any(has_playlist_parameter(url) or is_collection_url(url) for url in urls)
    context.chat_data.pop("pending_message_id", None)
    if context.chat_data["pending_needs_scope"]:
        selection_message = await update.effective_message.reply_text(
            f"📚 Playlist detected in {len(urls)} submitted link{'s' if len(urls) != 1 else ''}.\n"
            "What should I download?",
            reply_markup=playlist_keyboard(),
        )
    else:
        context.chat_data["pending_playlist"] = False
        selection_message = await update.effective_message.reply_text(
            f"🎚 Choose one format for {len(urls)} queue item{'s' if len(urls) != 1 else ''}:",
            reply_markup=choice_keyboard(),
        )
    context.chat_data["pending_message_id"] = selection_message.message_id


async def choose_scope(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_unauthorized(update):
        return
    query = update.callback_query
    await query.answer()
    if (not context.chat_data.get("pending_urls")
            or context.chat_data.get("pending_message_id") != query.message.message_id):
        await query.edit_message_text("⌛ This choice expired. Send the links again.")
        return
    context.chat_data["pending_playlist"] = query.data == "scope:playlist"
    context.chat_data["pending_needs_scope"] = False
    scope = "full playlist" if context.chat_data["pending_playlist"] else "single video"
    await query.edit_message_text(
        f"✅ Scope: {scope}\n\n🎚 Now choose the output format:", reply_markup=choice_keyboard()
    )


async def choose_download(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_unauthorized(update):
        return
    query = update.callback_query
    await query.answer()
    if (context.chat_data.get("pending_message_id") != query.message.message_id
            or context.chat_data.get("pending_needs_scope")):
        await query.edit_message_text("⌛ This choice expired. Use the current selection message.")
        return
    urls = context.chat_data.pop("pending_urls", None)
    if not urls:
        await query.edit_message_text("⌛ This choice expired. Send the URLs again.")
        return
    _, mode, quality = query.data.split(":", 2)
    playlist = bool(context.chat_data.pop("pending_playlist", False))
    identifiers = STORE.add_jobs(
        urls, job_settings(mode, quality, playlist), source="telegram", chat_id=update.effective_chat.id
    )
    scope = "full playlist" if playlist else "single video"
    await query.edit_message_text(
        f"✅ Added to the shared desktop queue\n\n"
        f"Items added: {len(identifiers)}\n"
        f"Mode: {mode.upper()} · {quality} · {scope}\n"
        f"Position: after {sum(job['status'] in {'queued', 'downloading', 'processing', 'expanding'} for job in STORE.list_jobs()) - len(identifiers)} existing active/queued item(s)\n\n"
        "Use /queue to manage downloads."
    )


async def job_control(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_unauthorized(update):
        return
    query = update.callback_query
    _, action, raw_id = query.data.split(":", 2)
    job_id = int(raw_id)
    if action == "pause":
        changed = STORE.pause(job_id)
        answer = "⏸ Pause requested." if changed else "That item cannot be paused."
    elif action == "resume":
        changed = STORE.resume(job_id)
        answer = "▶️ Returned to queue." if changed else "That item cannot be resumed."
    else:
        result = STORE.remove(job_id)
        if result == "stopping":
            answer = "🗑 Stopping and deleting from the queue."
        elif result == "removed":
            answer = "🗑 Deleted from the queue."
        else:
            answer = "That queue item no longer exists."
    await query.answer(answer)
    text, keyboard = queue_text_and_keyboard()
    try:
        await query.edit_message_text(text, reply_markup=keyboard)
    except TelegramError:
        pass


async def refresh_queue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_unauthorized(update):
        return
    query = update.callback_query
    await query.answer("Queue refreshed.")
    text, keyboard = queue_text_and_keyboard()
    try:
        await query.edit_message_text(text, reply_markup=keyboard)
    except TelegramError:
        pass


async def delivery_loop(application: Application) -> None:
    chat_id = allowed_chat_id()
    while True:
        try:
            for job in STORE.terminal_notifications(chat_id):
                job_id = int(job["id"])
                if job["status"] == "completed":
                    paths = [
                        Path(value) for value in str(job["file_path"]).splitlines() if value.strip()
                    ]
                    existing = [path for path in paths if path.is_file()]
                    if existing:
                        await application.bot.send_message(
                            chat_id=chat_id,
                            text=f"✅ Download finished · {len(existing)} file{'s' if len(existing) != 1 else ''}",
                        )
                        for index, path in enumerate(existing, 1):
                            size = path.stat().st_size
                            label = f"{index}/{len(existing)}" if len(existing) > 1 else "Ready"
                            if size < TELEGRAM_FILE_LIMIT:
                                with path.open("rb") as stream:
                                    await application.bot.send_document(
                                        chat_id=chat_id, document=stream, filename=path.name,
                                        caption=f"✅ Download ready · {label} · {format_bytes(size)}",
                                        read_timeout=300, write_timeout=300,
                                    )
                            else:
                                await application.bot.send_message(
                                    chat_id=chat_id,
                                    text=(
                                        f"💻 Download ready · {label} · {format_bytes(size)}\n"
                                        f"Too large for Telegram; ready on your computer:\n{path}"
                                    ),
                                )
                    else:
                        await application.bot.send_message(
                            chat_id=chat_id,
                            text="⚠️ Download completed, but its final file was not located.",
                        )
                elif job["status"] == "failed":
                    await application.bot.send_message(
                        chat_id=chat_id, text=f"❌ Download failed:\n{job['error'] or 'Unknown error'}"
                    )
                else:
                    await application.bot.send_message(chat_id=chat_id, text="🚫 Download was cancelled.")
                STORE.update(job_id, delivered=1)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("Queue delivery monitor failed")
        await asyncio.sleep(2)


async def post_init(application: Application) -> None:
    application.bot_data["delivery_task"] = asyncio.create_task(
        delivery_loop(application), name="queue-delivery"
    )


async def post_shutdown(application: Application) -> None:
    task = application.bot_data.get("delivery_task")
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logging.exception("Unhandled bot error", exc_info=context.error)


def main() -> None:
    token = os.environ.get(BOT_TOKEN_ENV)
    if not token:
        raise SystemExit(f"{BOT_TOKEN_ENV} is not set")
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    builder = Application.builder().token(token)
    proxy = STORE.get_preference("download_proxy")
    if proxy:
        logging.info("Telegram API proxy enabled (%s)", proxy.split(":", 1)[0].upper())
        builder = builder.request(HTTPXRequest(
            connection_pool_size=8,
            read_timeout=300,
            write_timeout=300,
            connect_timeout=30,
            media_write_timeout=300,
            proxy=proxy,
        )).get_updates_request(HTTPXRequest(
            connection_pool_size=1,
            read_timeout=310,
            write_timeout=300,
            connect_timeout=30,
            proxy=proxy,
        ))
    else:
        builder = builder.read_timeout(300).write_timeout(300).connect_timeout(30)
    application = builder.post_init(post_init).post_shutdown(post_shutdown).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("queue", queue_command))
    application.add_handler(CommandHandler("status", queue_command))
    application.add_handler(CommandHandler("cancel", cancel_command))
    application.add_handler(CallbackQueryHandler(choose_scope, pattern=r"^scope:"))
    application.add_handler(CallbackQueryHandler(choose_download, pattern=r"^get:"))
    application.add_handler(CallbackQueryHandler(job_control, pattern=r"^job:"))
    application.add_handler(CallbackQueryHandler(refresh_queue, pattern=r"^queue:refresh$"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_urls))
    application.add_error_handler(error_handler)
    # Keep messages Telegram received while the desktop app was closed.  The private
    # bot can then add those links to the shared queue as soon as the app starts.
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)


if __name__ == "__main__":
    main()
