"""Probe hardware encoders and create an edit-compatible H.264/AAC MP4."""
from __future__ import annotations

from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import time


class EncodingCancelled(Exception):
    pass


ENCODERS = {
    "copy": ("Remux · no re-encoding", []),
    "h264_nvenc": ("NVIDIA NVENC", ["-preset", "p4", "-rc", "vbr", "-cq", "18", "-b:v", "0"]),
    "h264_qsv": ("Intel Quick Sync", ["-preset", "medium", "-global_quality", "20", "-look_ahead", "0"]),
    "h264_amf": ("AMD AMF", ["-quality", "balanced", "-rc", "cqp", "-qp_i", "18", "-qp_p", "20"]),
    "libx264": ("CPU", ["-preset", "veryfast", "-crf", "18"]),
}


def _run(command, cancelled, progress=None, duration=0.0, timeout=None):
    """Drain progress in a reader thread; polling never waits for FFmpeg output."""
    if cancelled():
        raise EncodingCancelled()
    lines = queue.Queue()
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as errors:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=errors, text=True, encoding="utf-8", errors="replace",
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        def read():
            try:
                for line in process.stdout:
                    lines.put(line.strip())
            finally:
                process.stdout.close()
        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        started = time.monotonic()
        percent, speed = None, ""
        try:
            while process.poll() is None:
                if cancelled():
                    raise EncodingCancelled()
                if timeout and time.monotonic() - started > timeout:
                    raise subprocess.TimeoutExpired(command, timeout)
                try:
                    while True:
                        key, _, value = lines.get_nowait().partition("=")
                        if key == "out_time_us" and duration > 0:
                            try:
                                percent = min(99.9, max(0.0, float(value) / (duration * 10000)))
                            except ValueError:
                                pass
                        elif key == "speed":
                            speed = value
                        elif key == "progress" and progress:
                            progress(percent, speed)
                except queue.Empty:
                    pass
                time.sleep(0.1)
            reader.join(timeout=2)
            errors.seek(0)
            return process.returncode, errors.read()[-2000:]
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            reader.join(timeout=2)


def select_encoder(ffmpeg: Path, mode: str, cancelled, status=lambda text: None):
    if mode == "cpu":
        return "libx264"
    status("Checking GPU encoder…")
    for encoder in ("h264_nvenc", "h264_qsv", "h264_amf"):
        command = [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                   "color=c=black:s=320x180:r=25", "-frames:v", "2", "-an", "-c:v", encoder,
                   *ENCODERS[encoder][1], "-pix_fmt", "yuv420p", "-f", "null", "-"]
        try:
            code, _ = _run(command, cancelled, timeout=8)
            if code == 0:
                return encoder
        except (OSError, subprocess.TimeoutExpired):
            continue
    return "libx264"


def encode_mp4(ffmpeg: Path, source: Path, output: Path, duration: float,
               mode: str, cancelled, status, progress):
    encoder = "copy" if mode == "copy" else select_encoder(ffmpeg, mode, cancelled, status)
    candidates = [encoder] if encoder in {"libx264", "copy"} else [encoder, "libx264"]
    for candidate in candidates:
        label, options = ENCODERS[candidate]
        status(label)
        codec = (["-c:v", "copy", "-c:a", "copy"] if candidate == "copy" else
                 ["-c:v", candidate, *options, "-profile:v", "high", "-pix_fmt", "yuv420p",
                  "-fps_mode", "cfr", "-c:a", "aac", "-b:a", "192k", "-ar", "48000"])
        command = [str(ffmpeg), "-hide_banner", "-y", "-i", str(source),
                   "-map", "0:v:0", "-map", "0:a:0?", "-map_metadata", "0", "-sn", "-dn",
                   *codec,
                   "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(output)]
        code, error = _run(command, cancelled, progress, duration)
        if cancelled():
            raise EncodingCancelled()
        if code == 0:
            progress(100.0, "")
            return candidate
        # Only our explicitly named temporary output is removed on fallback.
        output.unlink(missing_ok=True)
    raise RuntimeError(f"FFmpeg conversion failed: {error.strip()}")
