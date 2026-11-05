"""Supervise one download process so blocked extractors cannot trap the queue."""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time


class ProcessTree:
    """Own only this child's process tree, including any FFmpeg/JS subprocesses."""
    def __init__(self, process):
        self.process = process
        self.job = None
        if sys.platform != "win32":
            return
        from ctypes import wintypes
        class Basic(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                        ("flags", wintypes.DWORD), ("min_ws", ctypes.c_size_t),
                        ("max_ws", ctypes.c_size_t), ("active", wintypes.DWORD),
                        ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                        ("scheduling", wintypes.DWORD)]
        class Extended(ctypes.Structure):
            _fields_ = [("basic", Basic), ("io", ctypes.c_uint64 * 6),
                        ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                        ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        kernel.CreateJobObjectW.restype = ctypes.c_void_p
        kernel.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        kernel.TerminateJobObject.argtypes = [ctypes.c_void_p, wintypes.UINT]
        kernel.QueryInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p,
                                                     wintypes.DWORD, ctypes.c_void_p]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.CreateJobObjectW(None, None)
        if handle:
            limits = Extended()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if (kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits))
                    and kernel.AssignProcessToJobObject(handle, int(process._handle))):
                self.job, self.kernel = handle, kernel
            else:
                kernel.CloseHandle(handle)

    def stop(self):
        if self.job:
            self.kernel.TerminateJobObject(self.job, 1)
        elif sys.platform == "win32" and self.process.poll() is None:
            try:
                subprocess.run(["taskkill.exe", "/PID", str(self.process.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except (OSError, subprocess.TimeoutExpired):
                self.process.kill()
        elif sys.platform != "win32":
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=3)
        self._wait_empty()

    def _wait_empty(self):
        if not self.job:
            return
        class Accounting(ctypes.Structure):
            _fields_ = [("times", ctypes.c_int64 * 4), ("faults", ctypes.c_uint32),
                        ("total", ctypes.c_uint32), ("active", ctypes.c_uint32),
                        ("terminated", ctypes.c_uint32)]
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            accounting = Accounting()
            if (not self.kernel.QueryInformationJobObject(self.job, 1, ctypes.byref(accounting),
                                                          ctypes.sizeof(accounting), None)
                    or accounting.active == 0):
                break
            time.sleep(0.02)

    def close(self):
        if self.job:
            self.kernel.TerminateJobObject(self.job, 1)
            self._wait_empty()
            self.kernel.CloseHandle(self.job)
            self.job = None


def run_isolated_job(job_id, data_root: Path, on_event, control, command=None):
    """Return (exit_code, requested_control) after the entire child tree exits."""
    requested = control()
    if requested:
        return 0, requested
    with tempfile.TemporaryDirectory(prefix="worker-", dir=data_root, ignore_cleanup_errors=True) as directory:
        events_path = Path(directory) / "events.jsonl"
        events_path.touch()
        if callable(command):
            command = command(job_id, events_path)
        elif command is None:
            command = ([sys.executable] if getattr(sys, "frozen", False) else
                       [sys.executable, str(Path(__file__).with_name("launcher.pyw"))])
            command += ["--download-job", str(job_id), str(events_path)]
        with (Path(directory) / "stderr.log").open("wb") as errors:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=errors, start_new_session=sys.platform != "win32",
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            tree = None
            requested = ""
            try:
                tree = ProcessTree(process)
                with events_path.open(encoding="utf-8") as stream:
                    pending = ""
                    while True:
                        pending += stream.read()
                        while "\n" in pending:
                            line, pending = pending.split("\n", 1)
                            if line:
                                event, payload = json.loads(line)
                                on_event((event, payload))
                        requested = control() or ""
                        if requested:
                            tree.stop()
                            break
                        if process.poll() is not None:
                            # Drain events written immediately before exit.
                            for line in (pending + stream.read()).splitlines():
                                if line:
                                    event, payload = json.loads(line)
                                    on_event((event, payload))
                            break
                        time.sleep(0.1)
                return process.returncode, requested
            finally:
                if process.poll() is None:
                    if tree:
                        tree.stop()
                    else:
                        process.kill()
                        process.wait(timeout=3)
                if tree:
                    tree.close()
