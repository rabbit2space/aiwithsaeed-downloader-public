# Third-party software and fonts

The Windows bundle includes Python, Tcl/Tk, yt-dlp and its dependencies,
CustomTkinter, Pillow, tkinterdnd2, python-telegram-bot, Node.js, FFmpeg,
FFprobe, and the Peyda and retained Vazirmatn fonts. Their license texts are in
`_internal/licenses`, Python's bundled license files, and `assets/OFL.txt`.

Original AIwithSaeed code is covered by the root MIT `LICENSE`. That grant does
not apply to third-party software, fonts, or their trademarks.

Peyda is proprietary and is not covered by `OFL.txt` or the project MIT license.
The project owner has confirmed permission to redistribute it with this app.
See `assets/Peyda-LICENSE-NOTICE.txt` and https://fontiran.com/fonts/peyda.

Node.js source and licenses: https://nodejs.org/en/about/previous-releases

FFmpeg build provider: https://www.gyan.dev/ffmpeg/builds/
FFmpeg source: https://ffmpeg.org/download.html
The pinned versions and download hashes are recorded in `official_resources.py`.
The online installer retains the publisher notices next to the downloaded tools.
These FFmpeg builds are GPL; preserve their
notices and provide the corresponding source when redistributing them.

yt-dlp source: https://github.com/yt-dlp/yt-dlp
CustomTkinter source: https://github.com/TomSchimansky/CustomTkinter
python-telegram-bot source: https://github.com/python-telegram-bot/python-telegram-bot
Python source and license: https://www.python.org/downloads/source/

The installer and application currently do not have a publisher signature.
The release checksum identifies the exact file provided by AIwithSaeed.

In version 4.5's online installer, our app and Python are embedded. Node.js and
the Gyan FFmpeg essentials archive are fetched directly from their official
versioned download locations during installation, with publisher SHA-256/size
verification. Their LICENSE/README notices are retained in the installed app.
This edition does not need or contact a custom AIwithSaeed installation server.
Any optional self-contained portable build still redistributes those binaries.
