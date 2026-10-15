"""Pinned HTTPS payload download with integrity checks and resumable local cache."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request


class DownloadProblem(RuntimeError):
    pass


class DownloadCancelled(DownloadProblem):
    pass


def persian_number(value):
    return str(value).translate(str.maketrans("0123456789.", "۰۱۲۳۴۵۶۷۸۹٫"))


class SecureRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        if urllib.parse.urlsplit(new_url).scheme != "https":
            raise DownloadProblem("تغییر مسیر ناامن سرور رد شد. از پشتیبانی سایت کمک بگیرید.")
        return super().redirect_request(request, fp, code, message, headers, new_url)


def open_request(request, timeout=15):
    # Re-read system proxy settings on each attempt, including after the user connects a VPN.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(), SecureRedirect())
    return opener.open(request, timeout=timeout)


def validate_config(config):
    url = urllib.parse.urlsplit(config.get("url", ""))
    if url.scheme != "https" or not url.hostname or url.username or url.password or url.fragment:
        raise DownloadProblem("نشانی دانلود معتبر نیست. نسخه نصب را دوباره از سایت دریافت کنید.")
    if not re.fullmatch(r"[a-f0-9]{64}", config.get("sha256", "")):
        raise DownloadProblem("اطلاعات بررسی فایل معتبر نیست.")
    size = config.get("size")
    if type(size) is not int or not 0 < size <= 2_000_000_000:
        raise DownloadProblem("اندازه فایل نصب معتبر نیست.")
    return config


def load_config(root):
    return validate_config(json.loads((root / "online-release.json").read_text(encoding="utf-8")))


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def explain_connection_error(error):
    if isinstance(error, DownloadProblem):
        return str(error)
    if isinstance(error, urllib.error.HTTPError):
        if error.code == 404:
            return "فایل این نسخه روی سرور پیدا نشد. مشکل انتشار فایل است؛ از پشتیبانی سایت کمک بگیرید."
        if error.code in (401, 403):
            return "سرور دسترسی به فایل را نپذیرفت. اتصال دیگری را امتحان کنید؛ اگر ادامه داشت به پشتیبانی سایت اطلاع دهید."
        return f"سرور دانلود خطا داد (کد {error.code}). کمی بعد دوباره امتحان کنید."
    return (
        "دانلود شروع نشد.\n"
        "اینترنت را بررسی کنید. اگر اینترنت وصل است، فیلترشکن ویندوز را روشن کنید و دوباره امتحان کنید.\n"
        "افزونه فیلترشکن مرورگر برای این برنامه کافی نیست."
    )


def check_connection(config, opener=None):
    validate_config(config)
    request = urllib.request.Request(config["url"], headers={"Range": "bytes=0-0", "Accept-Encoding": "identity"})
    try:
        with (opener or open_request)(request, timeout=12) as response:
            if "text/html" in response.headers.get("Content-Type", "").lower():
                raise DownloadProblem("سرور به‌جای فایل نصب یک صفحه وب فرستاد. از پشتیبانی سایت کمک بگیرید.")
            if response.status not in (200, 206):
                raise DownloadProblem("سرور پاسخ مناسب دانلود نداد.")
            if response.status == 206:
                if response.headers.get("Content-Range") != f"bytes 0-0/{config['size']}":
                    raise DownloadProblem("فایل روی سرور با این نسخه سازگار نیست. به پشتیبانی سایت اطلاع دهید.")
            elif int(response.headers.get("Content-Length", config["size"])) != config["size"]:
                raise DownloadProblem("اندازه فایل روی سرور با این نسخه سازگار نیست.")
            if not response.read(1):
                raise DownloadProblem("سرور فایل خالی برگرداند.")
        return "با اتصال فعلی می‌توانید دانلود کنید."
    except (OSError, ValueError, urllib.error.URLError, DownloadProblem) as exc:
        if isinstance(exc, urllib.error.HTTPError):
            exc.close()
        raise DownloadProblem(explain_connection_error(exc)) from exc


@contextmanager
def cache_lock(folder):
    folder.mkdir(parents=True, exist_ok=True)
    stream = (folder / "download.lock").open("a+b")
    locked = False
    try:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError as exc:
            raise DownloadProblem("یک پنجره نصب دیگر در حال دریافت فایل است. آن را ببندید و دوباره امتحان کنید.") from exc
        yield
    finally:
        if locked:
            stream.seek(0)
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_UN)
        stream.close()


def download_payload(config, cache_root, progress, status, cancel=None, opener=None):
    validate_config(config)
    folder = Path(cache_root) / config["sha256"]
    with cache_lock(folder):
        return _download(config, folder, progress, status, cancel, opener or open_request)


def _download(config, folder, progress, status, cancel, opener):
    complete = folder / "payload.zip"
    partial = folder / "payload.part"
    expected_size = config["size"]
    if complete.is_file():
        status("در حال بررسی فایل…")
        if complete.stat().st_size == expected_size and file_hash(complete) == config["sha256"]:
            progress(1.0)
            return complete
        complete.unlink()
    if partial.is_file() and partial.stat().st_size > expected_size:
        partial.unlink()
    offset = partial.stat().st_size if partial.exists() else 0
    if offset == expected_size:
        if file_hash(partial) == config["sha256"]:
            partial.replace(complete)
            progress(1.0)
            return complete
        partial.unlink()
        offset = 0
    if cancel and cancel.is_set():
        raise DownloadCancelled("دانلود متوقف شد. هر وقت خواستید، ادامه دهید.")
    headers = {"Accept-Encoding": "identity", "User-Agent": "AIwithSaeed-Installer/1"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    request = urllib.request.Request(config["url"], headers=headers)
    status("در حال اتصال…")
    try:
        with opener(request, timeout=15) as response:
            if "text/html" in response.headers.get("Content-Type", "").lower():
                raise DownloadProblem("سرور به‌جای فایل نصب یک صفحه وب فرستاد. از پشتیبانی سایت کمک بگیرید.")
            if response.status == 206:
                content_range = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
                if not content_range or tuple(map(int, content_range.groups())) != (offset, expected_size - 1, expected_size):
                    raise DownloadProblem("پاسخ ادامه دانلود معتبر نیست؛ فایل نصب بررسی نشد.")
            elif response.status == 200:
                offset = 0  # Server ignored Range: safely restart instead of appending duplicate bytes.
            else:
                raise DownloadProblem("سرور پاسخ مناسب دانلود نداد.")
            length = response.headers.get("Content-Length")
            if length is not None and int(length) != expected_size - offset:
                raise DownloadProblem("اندازه پاسخ سرور با فایل این نسخه سازگار نیست.")
            received = offset
            with partial.open("ab" if offset else "wb") as stream:
                while True:
                    if cancel and cancel.is_set():
                        raise DownloadCancelled("دانلود متوقف شد. هر وقت خواستید، ادامه دهید.")
                    block = response.read(256 * 1024)
                    if not block:
                        break
                    if received + len(block) > expected_size:
                        raise DownloadProblem("سرور داده بیشتری از فایل مورد انتظار ارسال کرد.")
                    stream.write(block)
                    received += len(block)
                    progress(received / expected_size)
                    status(f"{persian_number(f'{received / 1048576:.1f}')} از {persian_number(f'{expected_size / 1048576:.1f}')} مگابایت دانلود شد")
        if received != expected_size:
            raise DownloadProblem("دانلود قطع شد. اینترنت را بررسی کنید و دوباره امتحان کنید؛ دانلود از همان‌جا ادامه پیدا می‌کند.")
        status("در حال بررسی فایل…")
        if file_hash(partial) != config["sha256"]:
            partial.unlink()
            raise DownloadProblem("فایل دانلودشده خراب است. دوباره دانلود کنید.")
        partial.replace(complete)
        return complete
    except DownloadProblem:
        raise
    except (OSError, ValueError, urllib.error.URLError) as exc:
        if isinstance(exc, urllib.error.HTTPError):
            exc.close()
        raise DownloadProblem(explain_connection_error(exc)) from exc
