# Contributing / مشارکت

## فارسی

برای گزارش باگ، نسخه برنامه، نسخه ویندوز، مراحل تکرار مشکل و نتیجه مورد انتظار را بنویسید. اطلاعات حساس را از گزارش و تصویر حذف کنید. مشکلات امنیتی را طبق [راهنمای امنیت](SECURITY.md) گزارش دهید.

قبل از تغییرات بزرگ، یک Issue برای هماهنگی باز کنید. تغییرات رابط کاربری باید فارسی، انگلیسی و چیدمان راست‌به‌چپ را حفظ کنند. فایل شخصی، کوکی، توکن، خروجی ساخت یا فونت بدون مجوز به پروژه اضافه نکنید.

## English

For bug reports, include the app version, Windows version, reproduction steps,
expected behavior, and actual behavior. Redact personal information from screenshots
and logs. Follow [SECURITY.md](SECURITY.md) for vulnerabilities.

Discuss major changes in an issue first. Preserve both languages and Persian RTL
layout. Do not commit credentials, personal data, build outputs, or unlicensed fonts.

Install development dependencies in a virtual environment and run:

```powershell
python -m unittest discover -s tests -q
```

Keep pull requests focused and describe the checks you performed. Contributions
to original project code are submitted under the repository's MIT license.
Third-party assets must retain their original notices and licensing terms.
