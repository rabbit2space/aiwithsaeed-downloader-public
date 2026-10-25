# Changelog / تغییرات

## 4.6.1 — 2026-10-25

- کوتاه‌شدن متن راهنمای شروع کار و فوتر برنامه و هماهنگی توضیحات فارسی و انگلیسی گیت‌هاب
- Simplify the welcome guide, app footer, and Persian/English repository copy.

## 4.6.0 — 2026-10-25

### فارسی

- به‌روزرسانی ابزار دانلود به نسخه ۲۰۲۶٫۱۰٫۲۱
- به‌روزرسانی پایتون همراه برنامه به نسخه ۳.۱۴.۹
- به‌روزرسانی ابزارهای نصب به Node.js 24.22.1 و FFmpeg 9.0.2
- به‌روزرسانی گواهی‌های اتصال امن، پردازش تصویر و کشیدن و رهاکردن فایل
- بازنویسی معرفی فارسی و انگلیسی پروژه و اضافه‌شدن تصاویر واقعی برنامه
- اصلاح جهت متن صف خالی در فارسی و تغییر فوری آن هنگام عوض‌کردن زبان

### English

- Update yt-dlp to 2026.10.21 and require the current certifi certificate bundle.
- Bundle Python 3.14.9 with Tcl/Tk 9.0.4 from the verified python-build-standalone runtime.
- Update the pinned official tools to Node.js 24.22.1 LTS and FFmpeg 9.0.2.
- Update Pillow to 13.0.0 and tkinterdnd2 to 0.6.4. Source installs now require Python 3.11 or later.
- Refresh both READMEs with actual app screenshots and shorter installation instructions.
- Align the empty queue message correctly in Persian and translate it immediately when switching languages.
- Keep the established CustomTkinter 5 interface rather than introducing a major UI framework migration.

## 4.5.1 — 2026-10-15

### فارسی

- اولین انتشار این مخزن عمومی، با مستندات فارسی و انگلیسی
- متن‌های روان‌تر برای نصب، پیام‌های اتصال و راهنمای شروع کار
- فونت Peyda، رابط راست‌به‌چپ و راهنمای پنج‌مرحله‌ای
- نصب آنلاین با دریافت ابزارها از منابع رسمی و بررسی SHA-256
- کوکی فایرفاکس و ربات تلگرام اختیاری؛ بدون ورود به سایت یا کد فعال‌سازی
- کد اصلی با مجوز MIT؛ مجوزهای مستقل برای ابزارها و فونت‌ها

### English

- First release in this public repository, with Persian and English documentation.
- Clearer Persian installer copy, connection messages, and onboarding.
- Peyda typography, RTL interface, and five-step setup guide.
- Online installer fetches supporting tools from pinned official sources with SHA-256 verification.
- Optional Firefox cookies and personal Telegram bot; no website login or activation.
- MIT license for original code, with separate notices for dependencies and fonts.

The Windows installer is unsigned. Source tests and a packaged-app smoke test
were run locally before publication. Network access varies by provider and region.
