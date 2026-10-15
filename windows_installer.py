"""Per-user Windows installer. Contains only the allowlisted frozen app payload."""
from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import messagebox, ttk
import zipfile
from ui_fonts import FONT_FAMILY, register_fonts
from online_download import DownloadCancelled, check_connection, download_payload, persian_number
from official_resources import extract_tools, load_resources

PRODUCT = "AIwithSaeed Downloader"
PRODUCT_ID = "AIwithSaeed.Downloader"
ROOT = Path(__file__).resolve().parent
DEFAULT_TARGET = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Programs" / PRODUCT

UNINSTALL = r'''
$ErrorActionPreference = 'Stop'
$target = [IO.Path]::GetFullPath($PSScriptRoot)
$marker = Join-Path $target 'installation.json'
if (-not (Test-Path -LiteralPath $marker)) { throw 'Installation marker is missing.' }
$info = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
if ($info.product -ne 'AIwithSaeed.Downloader') { throw 'Unexpected installation marker.' }
$exe = Join-Path $target 'AIwithSaeed-Downloader.exe'
$running = Get-Process -Name 'AIwithSaeed-Downloader' -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $exe }
if ($running) { Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show('Close AIwithSaeed Downloader first, then uninstall again.'); exit 1 }
$shell = New-Object -ComObject WScript.Shell
$links = @((Join-Path ([Environment]::GetFolderPath('Desktop')) 'AIwithSaeed Downloader.lnk'), (Join-Path ([Environment]::GetFolderPath('StartMenu')) 'Programs\AIwithSaeed Downloader.lnk'))
foreach ($link in $links) { if ((Test-Path -LiteralPath $link) -and ($shell.CreateShortcut($link).TargetPath -eq $exe)) { Remove-Item -LiteralPath $link -Force } }
$key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\AIwithSaeed.Downloader'
if ((Test-Path -LiteralPath $key) -and ((Get-ItemProperty -LiteralPath $key).InstallLocation -eq $target)) { Remove-Item -LiteralPath $key }
Remove-Item -LiteralPath $target -Recurse -Force
'''

REGISTER = r'''
$ErrorActionPreference = 'Stop'
$target = $env:AIWS_INSTALL_TARGET
$exe = Join-Path $target 'AIwithSaeed-Downloader.exe'
$shell = New-Object -ComObject WScript.Shell
$paths = @((Join-Path ([Environment]::GetFolderPath('StartMenu')) 'Programs\AIwithSaeed Downloader.lnk'))
if ($env:AIWS_DESKTOP_SHORTCUT -eq '1') { $paths += Join-Path ([Environment]::GetFolderPath('Desktop')) 'AIwithSaeed Downloader.lnk' }
foreach ($path in $paths) { $shortcut = $shell.CreateShortcut($path); $shortcut.TargetPath = $exe; $shortcut.WorkingDirectory = $target; $shortcut.IconLocation = "$exe,0"; $shortcut.Save() }
$key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\AIwithSaeed.Downloader'
New-Item -Path $key -Force | Out-Null
$values = @{DisplayName='AIwithSaeed Downloader'; DisplayVersion=$env:AIWS_INSTALL_VERSION; Publisher='AIwithSaeed'; InstallLocation=$target; DisplayIcon=$exe; URLInfoAbout='https://aiwithsaeed.com'; UninstallString=('powershell.exe -NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $target 'Uninstall.ps1') + '"')}
foreach ($name in $values.Keys) { New-ItemProperty -LiteralPath $key -Name $name -Value $values[$name] -PropertyType String -Force | Out-Null }
New-ItemProperty -LiteralPath $key -Name NoModify -Value 1 -PropertyType DWord -Force | Out-Null
New-ItemProperty -LiteralPath $key -Name NoRepair -Value 1 -PropertyType DWord -Force | Out-Null
'''


def install(target: Path, progress, desktop: bool = True, register: bool = True,
            status=None, cancel=None) -> None:
    status = status or (lambda text: None)
    target = target.resolve()
    if target.exists() and any(target.iterdir()):
        marker = target / "installation.json"
        if not marker.is_file() or json.loads(marker.read_text(encoding="utf-8")).get("product") != PRODUCT_ID:
            raise RuntimeError("The destination contains unrelated files. Choose an empty folder.")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenMutexW.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_wchar_p]
    kernel.OpenMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenMutexW(0x00100000, False, r"Local\AIwithSaeed.Downloader")
    if handle:
        kernel.CloseHandle(handle)
        raise RuntimeError("Close AIwithSaeed Downloader before installing or updating.")
    online = (ROOT / "official-resources.json").is_file()
    archives = {}
    if online:
        resources = load_resources(ROOT)
        cache = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "AIwithSaeed" / "InstallerCache"
        total = sum(resource["size"] for resource in resources)
        finished = 0
        for index, resource in enumerate(resources, 1):
            try:
                archives[resource["id"]] = download_payload(
                    resource, cache,
                    lambda value, base=finished, size=resource["size"]: progress((base + value * size) / total * 65),
                    lambda text, number=index: status(f"فایل {persian_number(number)} از {persian_number(len(resources))} — {text}"), cancel,
                )
            except DownloadCancelled:
                raise
            except Exception as exc:
                raise RuntimeError(f"{exc}\n\nنام فایل: {resource['label']}") from exc
            finished += resource["size"]
    payload = ROOT / "payload.zip"
    expected = (ROOT / "payload.sha256").read_text(encoding="ascii").strip()
    digest = hashlib.sha256()
    with payload.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != expected:
        raise RuntimeError("The download is damaged. Download the installer again.")
    if cancel and cancel.is_set():
        raise DownloadCancelled("دانلود متوقف شد. هر وقت خواستید، ادامه دهید.")
    status("در حال نصب برنامه…")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="aiwithsaeed-stage-", dir=target.parent))
    backup = None
    try:
        with zipfile.ZipFile(payload) as archive:
            members = archive.infolist()
            for index, member in enumerate(members):
                destination = (staging / member.filename).resolve()
                if not destination.is_relative_to(staging):
                    raise RuntimeError("Unsafe path in installer payload.")
                archive.extract(member, staging)
                progress((65 if online else 0) + (index + 1) / len(members) * (30 if online else 90))
        if not (staging / "AIwithSaeed-Downloader.exe").is_file():
            raise RuntimeError("The installer payload is incomplete.")
        manifest = json.loads((staging / "installation.json").read_text(encoding="utf-8"))
        if manifest.get("product") != PRODUCT_ID:
            raise RuntimeError("Unexpected installer payload.")
        if online:
            extract_tools(resources, archives, staging)
            manifest["official_resources"] = [
                {key: resource[key] for key in ("id", "version", "url", "sha256")}
                for resource in resources
            ]
            (staging / "installation.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        (staging / "Uninstall.ps1").write_text(UNINSTALL, encoding="utf-8-sig")
        if target.exists():
            backup = Path(tempfile.mkdtemp(prefix="aiwithsaeed-old-", dir=target.parent))
            backup.rmdir()
            target.rename(backup)
        try:
            staging.rename(target)
        except Exception:
            if backup:
                backup.rename(target)
                backup = None
            raise
        if register:
            environment = os.environ.copy()
            environment.update(AIWS_INSTALL_TARGET=str(target), AIWS_INSTALL_VERSION=manifest["version"],
                               AIWS_DESKTOP_SHORTCUT="1" if desktop else "0")
            encoded = base64.b64encode(REGISTER.encode("utf-16-le")).decode("ascii")
            subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                           env=environment, check=True, capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        progress(100)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        if backup and backup.exists():
            shutil.rmtree(backup)


def main() -> None:
    if "--test-install" in sys.argv:
        target = Path(sys.argv[sys.argv.index("--test-install") + 1])
        try:
            install(target, lambda value: None, register=False)
            target.with_suffix(".result.json").write_text('{"ok": true}', encoding="utf-8")
        except Exception as exc:
            target.with_suffix(".result.json").write_text(json.dumps({"ok": False, "error": str(exc)}), encoding="utf-8")
            raise SystemExit(1)
        return
    register_fonts(ROOT / "assets")
    online = (ROOT / "official-resources.json").is_file()
    resources = load_resources(ROOT) if online else []
    window = tk.Tk()
    window.title("نصب رایگان دانلودر | AIwithSaeed")
    window.geometry(f"760x{min(740, max(620, window.winfo_screenheight() - 100))}" if online else "700x530")
    window.resizable(False, False)
    window.configure(bg="#f5f5f7")
    footer = tk.Frame(window, bg="#f5f5f7")
    footer.pack(side="bottom", fill="x", padx=32, pady=12)
    font = (FONT_FAMILY, 13)
    tk.Label(window, text="نصب دانلودر", font=(FONT_FAMILY, 24, "bold"),
             bg="#f5f5f7", anchor="e").pack(fill="x", padx=32, pady=(18, 8))
    introduction = ("برای شروع، «شروع نصب» را بزنید.\n"
                    f"حدود {persian_number(f'{sum(item["size"] for item in resources) / 1048576:.0f}')} مگابایت دانلود می‌شود؛ نصب خودکار است.\n"
                    "اگر دانلود قطع شد، می‌توانید ادامه‌اش دهید."
                    if online else
                    "یک‌بار نصب کنید؛ سپس لینک ویدیو را بچسبانید و دانلود کنید.\n"
                    "ابزارهای لازم همراه برنامه هستند؛ نصب جداگانه لازم نیست.\n"
                    "کوکی و ربات تلگرام اختیاری هستند. بدون کد فعال‌سازی.")
    tk.Label(window, text=introduction,
             font=font, bg="#f5f5f7", justify="right", anchor="e").pack(fill="x", padx=32, pady=6)
    if online:
        tk.Label(window, text="برای نصب، اینترنت را وصل نگه دارید.\n"
                 "اگر اینترنت وصل است ولی دانلود شروع نمی‌شود، فیلترشکن را روشن کنید و دوباره امتحان کنید.\n"
                 "فیلترشکن باید برای کل ویندوز فعال باشد؛ افزونه مرورگر کافی نیست.",
                 font=(FONT_FAMILY, 11), bg="#eaf3ff", fg="#164269", justify="right", anchor="e",
                 padx=14, pady=8, wraplength=675).pack(fill="x", padx=32, pady=6)
    if not online:
        tk.Label(window, text="Free Windows app • Python, Node.js and FFmpeg included",
                 font=("Segoe UI", 10), bg="#f5f5f7", fg="#666").pack(pady=5)
    desktop = tk.BooleanVar(value=True)
    tk.Checkbutton(window, text="آیکون برنامه روی دسکتاپ باشد", variable=desktop, font=font,
                   bg="#f5f5f7", anchor="e").pack(fill="x", padx=32, pady=8)
    progress = ttk.Progressbar(footer, maximum=100)
    progress.pack(fill="x", pady=5)
    status = tk.Label(footer, text="آماده نصب", font=font, bg="#f5f5f7",
                      wraplength=690, justify="right", anchor="e", height=2 if online else 1)
    status.pack(fill="x", pady=5)
    actions = tk.Frame(footer, bg="#f5f5f7")
    actions.pack(fill="x")
    events = queue.Queue()
    busy = False
    finished = False
    cancel = threading.Event()

    def controls(enabled):
        button.configure(state="normal" if enabled else "disabled")
        if connection_button:
            connection_button.configure(state="normal" if enabled else "disabled")
        cancel_button.configure(state="disabled" if enabled else "normal")

    def test_connection():
        nonlocal busy
        busy = True
        controls(False)
        cancel_button.configure(state="disabled")
        status.configure(text="در حال بررسی اتصال…")
        def run():
            try:
                for resource in resources:
                    try:
                        check_connection(resource)
                    except Exception as exc:
                        raise RuntimeError(f"{exc}\n\nنام فایل: {resource['label']}") from exc
                events.put(("connection", "اتصال برقرار است. می‌توانید نصب را شروع کنید."))
            except Exception as exc:
                events.put(("error", str(exc)))
        threading.Thread(target=run, daemon=True).start()

    def start() -> None:
        nonlocal busy, finished
        if finished:
            subprocess.Popen([str(DEFAULT_TARGET / "AIwithSaeed-Downloader.exe")], cwd=DEFAULT_TARGET)
            window.destroy()
            return
        busy = True
        cancel.clear()
        controls(False)
        status.configure(text="در حال آماده‌سازی…")

        # Read Tk variables on the main thread, before starting the worker.
        selected = desktop.get()
        def run() -> None:
            try:
                install(DEFAULT_TARGET, lambda value: events.put(("progress", value)), selected,
                        status=lambda value: events.put(("status", value)), cancel=cancel)
                events.put(("done", None))
            except DownloadCancelled as exc:
                events.put(("cancelled", str(exc)))
            except Exception as exc:
                events.put(("error", str(exc)))
        threading.Thread(target=run, daemon=True).start()

    def poll() -> None:
        nonlocal busy, finished
        try:
            while True:
                event, value = events.get_nowait()
                if event == "progress":
                    progress["value"] = value
                elif event == "status":
                    status.configure(text=value)
                    if value.startswith("در حال نصب برنامه"):
                        cancel_button.configure(state="disabled")
                elif event == "connection":
                    busy = False
                    controls(True)
                    status.configure(text=value)
                elif event == "cancelled":
                    busy = False
                    controls(True)
                    status.configure(text=value)
                    button.configure(text="ادامه نصب")
                elif event == "done":
                    busy, finished = False, True
                    controls(True)
                    if connection_button:
                        connection_button.configure(state="disabled")
                    status.configure(text="نصب تمام شد. برنامه آماده است.")
                    button.configure(state="normal", text="باز کردن برنامه")
                else:
                    busy = False
                    controls(True)
                    button.configure(text="تلاش دوباره")
                    status.configure(text="نصب کامل نشد. پیام خطا را بررسی کنید و دوباره امتحان کنید.")
                    messagebox.showerror(PRODUCT, str(value), parent=window)
        except queue.Empty:
            pass
        window.after(80, poll)

    button = tk.Button(actions, text="شروع نصب", command=start, font=(FONT_FAMILY, 15, "bold"),
                       bg="#0071e3", fg="white", relief="flat", padx=32, pady=8)
    button.pack(side="right" if online else "top", pady=6)
    connection_button = None
    if online:
        connection_button = tk.Button(actions, text="بررسی اتصال", command=test_connection,
                                      font=font, relief="flat", bg="#e4e8ef", padx=18, pady=4)
        connection_button.pack(side="right", padx=12, pady=6)
    def cancel_download():
        cancel.set()
        status.configure(text="در حال توقف دانلود…")
    cancel_button = tk.Button(actions, text="توقف دانلود", command=cancel_download,
                              font=font, relief="flat", state="disabled")
    if online:
        cancel_button.pack(side="left", pady=6)
    window.protocol("WM_DELETE_WINDOW", lambda: None if busy else window.destroy())
    poll()
    window.mainloop()


if __name__ == "__main__":
    main()
