# AIwithSaeed Downloader

[فارسی](README.md) · English

A bilingual Windows desktop downloader for media you are authorized to save from YouTube, Instagram, and other sites supported by yt-dlp.

Website: [aiwithsaeed.com](https://aiwithsaeed.com)

[Download for Windows](https://github.com/rabbit2space/aiwithsaeed-downloader-public/releases/latest) · [Changelog](CHANGELOG.md)

## Privacy-first public release

- The app does not send links, files, passwords, cookies, logs, or Telegram credentials to AIwithSaeed.
- Mutable data is stored per Windows user in `%LOCALAPPDATA%\AIwithSaeed\Downloader`, outside the installation folder.
- Telegram is disabled by default. There is no built-in token, user ID, chat ID, proxy, or personal account.
- A BotFather token is encrypted for the current Windows account with Windows DPAPI.
- The Telegram bot accepts commands only from the numeric chat ID configured by that user.
- Cookie files remain local. Users should never upload, email, or share `cookies.txt`.

## Install on Windows

For visitors downloading the ready-to-install edition (Windows 10/11, x64):

1. Download the installer from this repository's **Releases** page. GitHub's **Code → Download ZIP** contains source code, not the Windows installer.
2. Open it, optionally click **بررسی اتصال**, then click **شروع نصب**. Setup downloads approximately 139 MiB of supporting tools directly from official publisher resources.
3. Click **باز کردن برنامه**. Future launches use the desktop/Start menu shortcut.
4. Paste a video link and click **افزودن به صف**. Use **باز کردن پوشه** to find the file.

Our app and Python are inside the installer. Node.js is downloaded from nodejs.org;
FFmpeg/FFprobe come from Gyan Doshi's Windows builds, linked by the FFmpeg project.
No custom server, separately hosted app payload or website API is required. No separate Python installation,
terminal commands, activation, or website login is required inside the app.
Cookies and Telegram are optional; **شروع دانلود** skips the advanced setup pages.
See `QUICK-START-FA.html` for step-by-step Persian instructions.

An optional `-Portable.zip` build also includes these tools; it is not included in every release. Extract the entire ZIP and
open `AIwithSaeed-Downloader.exe`; keep its `_internal` folder beside it.
Internet access is still required to download online media.
The installer adds an entry in Windows Installed apps; uninstall preserves the
user's downloads, queue and settings.

### Internet and VPN guidance for Iran

The installer tests both official tool download URLs with the current connection.
It cannot reliably determine whether a VPN is running or prove that a failure is censorship.
If access works, no connection change is needed for installation. If access fails,
check the internet and, if needed, connect a system-wide Windows VPN and retry.
A browser-only VPN extension does not affect this installer. During an international
internet outage, a VPN may not restore access. YouTube and Telegram access are
separate from the install-server check and may still require a suitable connection.

Downloads are pinned to each publisher archive's HTTPS URL, size and SHA-256. Interrupted
downloads remain under `%LOCALAPPDATA%\AIwithSaeed\InstallerCache`; Retry resumes
them when the server supports Range requests. A server that ignores Range safely
restarts the download. Completed verified downloads are reused without downloading again.
The app core is embedded so it can be distributed as a single installer without hosting a separate custom payload.

### Official download sources

- Node.js 22.20.0 x64 ZIP: `https://nodejs.org/dist/v22.20.0/node-v22.20.0-win-x64.zip`
- FFmpeg 8.1.2 essentials ZIP: `https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-8.1.2-essentials_build.zip`

`official_resources.py` records publisher checksums and the exact archive members
to install. Only Node, FFmpeg, FFprobe and their notices are extracted. Package
scripts, npm tools and ffplay are not installed. The app uses private tool copies
and does not alter system PATH or require administrator access.

### Developers / source ZIP

1. Extract the ZIP to a normal folder.
2. Install Python 3.10 or newer from [python.org](https://www.python.org/downloads/windows/) and enable **Add Python to PATH**.
3. Double-click `run.bat`.
4. The first run creates an isolated Python environment and installs the listed open-source dependencies.
5. Setup can optionally install Deno and FFmpeg through Windows Package Manager.

FFmpeg is required for merging the best video and audio, MP3 conversion, Premiere compatibility, and media embedding. Deno or Node.js is required for current YouTube JavaScript challenges.

## First-run guide

The app opens a five-step Persian tutorial on first launch. Persian is the default language and the complete interface, including the popup and queue, uses a right-to-left layout. Open the guide again at any time with **راهنمای راه‌اندازی** in the header.

The public download is free. The desktop app never asks for a website login, account, activation code, or license key. Website publication is managed separately from this repository.

### Cookies and browser login

Try public media without cookies first. A signed-in browser session is mainly needed when YouTube requests login, applies an anti-bot check, or restricts content to an account. yt-dlp warns that using an account may lead to a temporary or permanent account ban, so use cookies only when necessary and preferably use a separate account.

The first-run popup walks users through this recommended flow:

1. Install Firefox if needed.
2. Use the popup button to open YouTube in Firefox and sign in.
3. Play a normal video and confirm the YouTube profile picture appears.
4. Close every Firefox window and background process.
5. Click **Use Firefox cookies** in the popup.
6. Retry the download.

Advanced durable-cookie flow (only if direct Firefox reading does not work):

1. Open one new Firefox Private Window and sign in to YouTube.
2. In that same tab, visit `https://www.youtube.com/robots.txt`.
3. With a trusted local-only Firefox extension, export only `youtube.com` cookies in Netscape format.
4. Close that Private Window and never reopen its session, so YouTube does not rotate those cookies.
5. Select the exported file on the popup's **فایل کوکی** page. Delete or replace it when it is no longer needed.

Treat `cookies.txt` like a password. Anyone who receives it may be able to use the signed-in session. Never upload or share it. The app never asks for a website password. See yt-dlp's [official YouTube cookie instructions](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies).

### Personal Telegram bot

1. Open the official [@BotFather](https://t.me/BotFather) account and send `/newbot`.
2. Copy the new bot token into **Setup guide → Telegram**.
3. Open the new bot and send `/start`.
4. Click **Detect chat ID**. You may instead paste your positive numeric private-chat ID.
5. Click **Save & start bot**.

The desktop app must stay open because it owns the download worker. Telegram adds and controls queue items. Files below Telegram's configured 50 MiB delivery limit are sent to the private chat; larger files remain on the computer.

If a token is ever exposed in a chat, screenshot, repository, or public file, revoke it immediately with BotFather and create a replacement.

## Main features

- Videos, playlists, channel/profile URLs, and multi-link queues
- Premiere-ready H.264/AAC MP4, original best quality, and MP3
- Resolution selection up to 4K
- Manual and automatic subtitles
- Thumbnails, metadata, descriptions, progress, speed, ETA, pause, resume, and cancellation
- Persian-first RTL interface with optional English
- Optional HTTP(S) and SOCKS proxy
- Optional private Telegram control bot

## Responsible use

AIwithSaeed Downloader does not bypass DRM, paywalls, private-access controls, geo/security controls, or platform permissions. Download only media you own or are authorized to save, and follow copyright law and each platform's terms.

## License and credits

Original project code is licensed under the [MIT License](LICENSE), with attribution
to AIwithSaeed. Third-party software and fonts retain their own licenses; the MIT
grant does not relicense Peyda, Vazirmatn, or bundled dependencies.

The app uses [yt-dlp](https://github.com/yt-dlp/yt-dlp). The Persian interface,
installer and guide use Peyda Regular and Bold. Peyda is proprietary; app embedding
is distributed with permission confirmed by the project owner. Reuse of the font
outside this app requires the applicable Fontiran permission.
See `assets/Peyda-LICENSE-NOTICE.txt` and https://fontiran.com/fonts/peyda.
The retained Vazirmatn assets are separately covered by `assets/OFL.txt`;
that open-font license does not apply to Peyda.

## Build the Windows installer

On a Windows x64 build machine, use Python 3.14 (the version used for this release)
and install `requirements.txt` and `requirements-build.txt` into a dedicated
Python virtual environment. Then run:

```powershell
.\.venv\Scripts\python.exe build-windows.py
```

Outputs: a per-user online installer with our app embedded, a transparent official
resource manifest, and versioned checksums under `dist`. There are no custom-server
files to upload. Use `--portable` to additionally fetch the official tools and create
a self-contained portable ZIP.
The build copies explicit app assets and tools, never the
development database, logs, cookies, token, `.venv`, or private handoff notes.
The installer uses Python/Tk and does not require a separate installer compiler.
Build updates with a fresh yt-dlp environment when extraction changes. Rebuild and
redistribute to update the frozen runtime; the installed app does not run pip.
See `THIRD-PARTY.md` for redistribution notices and source information.

## Contributing and security

Read [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).
Run the existing tests with `python -m unittest discover -s tests -q`.
Never attach cookies, tokens, databases, or unredacted logs to a public issue.
