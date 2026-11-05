import ctypes
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from job_runner import run_isolated_job


def windows_alive(pid):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    code = ctypes.c_ulong()
    try:
        return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
    finally:
        kernel.CloseHandle(handle)


class IsolatedWorkerTests(unittest.TestCase):
    def test_unicode_events_round_trip_without_stdout(self):
        with tempfile.TemporaryDirectory() as directory:
            events = []
            script = ("import json,sys; from pathlib import Path; "
                      "Path(sys.argv[1]).write_text(json.dumps(['processing','تبدیل ویدیو'])+'\\n',encoding='ascii')")
            code, action = run_isolated_job(1, Path(directory), events.append, lambda: "",
                                           command=lambda _, path: [sys.executable, "-c", script, str(path)])
            self.assertEqual(code, 0)
            self.assertEqual(events, [("processing", "تبدیل ویدیو")])

    def test_cancel_stalled_job_needs_no_progress_callback(self):
        with tempfile.TemporaryDirectory() as directory:
            started = time.monotonic()
            command = [sys.executable, "-c", "import time; time.sleep(60)"]
            code, action = run_isolated_job(1, Path(directory), lambda _: None,
                                           lambda: "pause" if time.monotonic() - started > 0.4 else "",
                                           command=command)
            self.assertEqual(action, "pause")
            self.assertIsNotNone(code)
            self.assertLess(time.monotonic() - started, 5)
            self.assertEqual(list(Path(directory).iterdir()), [])

    @unittest.skipUnless(sys.platform == "win32", "Windows process-tree guarantee")
    def test_remove_stops_blocked_grandchild_too(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pid_file = root / "grandchild.pid"
            script = ("import subprocess,sys,time; from pathlib import Path; "
                      "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']); "
                      "Path(sys.argv[1]).write_text(str(p.pid)); time.sleep(60)")
            started = time.monotonic()
            def control():
                return "remove" if pid_file.exists() or time.monotonic() - started > 6 else ""
            code, action = run_isolated_job(1, root, lambda _: None, control,
                                           command=[sys.executable, "-c", script, str(pid_file)])
            self.assertEqual(action, "remove")
            self.assertTrue(pid_file.exists(), "Child never reached subprocess phase")
            pid = int(pid_file.read_text())
            deadline = time.monotonic() + 2
            while windows_alive(pid) and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertFalse(windows_alive(pid), "Descendant survived job cancellation")

    def test_crashed_worker_exits_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as directory:
            code, action = run_isolated_job(1, Path(directory), lambda _: None, lambda: "",
                                           command=[sys.executable, "-c", "raise SystemExit(7)"])
            self.assertEqual(code, 7)
            self.assertEqual(action, "")
            self.assertEqual(list(Path(directory).iterdir()), [])
