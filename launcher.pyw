from __future__ import annotations

import ctypes
import sys
import traceback
from datetime import datetime

from app_paths import APP_NAME, STARTUP_LOG_FILE



def launch() -> None:
    try:
        if "--download-job" in sys.argv:
            from download_job import main
            main()
            return
        if "--telegram-bot" in sys.argv:
            from bot import main
            main()
            return
        if "--self-test" in sys.argv:
            from release_check import main
            main()
            return
        from app import main

        main()
    except Exception:
        details = traceback.format_exc()
        try:
            with STARTUP_LOG_FILE.open("a", encoding="utf-8") as stream:
                stream.write(f"\n{datetime.now().isoformat(timespec='seconds')}\n{details}")
        except OSError:
            pass
        if "--download-job" in sys.argv:
            raise SystemExit(1)
        ctypes.windll.user32.MessageBoxW(
            0,
            f"{APP_NAME} could not start.\n\n"
            f"Technical details were saved to:\n{STARTUP_LOG_FILE}",
            f"{APP_NAME} startup error",
            0x10,
        )


if __name__ == "__main__":
    launch()
