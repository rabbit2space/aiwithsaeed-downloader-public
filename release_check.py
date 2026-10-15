"""Offline packaged-app diagnostic; only runs when explicitly requested."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    import app
    import bot
    import yt_dlp
    from PIL import Image

    output = Path(sys.argv[sys.argv.index("--self-test") + 1]).resolve()
    result = {"version": app.APP_VERSION, "frozen": bool(getattr(sys, "frozen", False))}
    try:
        app.register_local_fonts()
        window = app.DownloaderApp()
        window._ensure_queue_worker = lambda *args: None
        window._start_telegram_bot = lambda: None
        window._set_language("fa")
        window.update()
        assert window.language == "fa"
        assert int(window.brand_logo.grid_info()["column"]) == 4
        window._open_setup_guide()
        for step in range(5):
            window.setup_step = step
            window._render_setup_guide()
            window.update()
            assert window.setup_window.winfo_exists()
        window._complete_setup_guide()
        window._set_language("en")
        window.update()
        assert int(window.brand_logo.grid_info()["column"]) == 0
        window._set_language("fa")
        for name in ("ffmpeg", "ffprobe"):
            path = app.DownloaderApp._media_tool(name)
            assert path is not None
            probe = subprocess.run([str(path), "-version"], capture_output=True, timeout=30,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            assert probe.returncode == 0, probe.stderr
            result[name] = probe.stdout.decode(errors="replace").splitlines()[0]
        name, path = app.DownloaderApp._javascript_runtime()
        probe = subprocess.run([path, "--version"], capture_output=True, timeout=30,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        assert probe.returncode == 0
        result[name] = probe.stdout.decode().strip()
        with Image.open(app.BRAND_LOGO_LIGHT_FILE) as logo:
            assert logo.width == logo.height
        result.update(ok=True, wizard_pages=5, rtl=True, dnd=window.dnd_available)
        window.destroy()
    except Exception:
        import traceback
        result.update(ok=False, error=traceback.format_exc())
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    raise SystemExit(0 if result["ok"] else 1)
