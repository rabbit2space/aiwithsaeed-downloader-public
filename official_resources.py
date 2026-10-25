"""Versioned publisher downloads; no custom hosting or remote executable scripts."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import zipfile

from online_download import DownloadProblem, validate_config

# SHA-256 values published by Node.js and Gyan Doshi, the Windows build provider
# linked by FFmpeg. Keep URLs, versions, sizes and hashes together when updating.
RESOURCES = [
    {
        "id": "node", "label": "Node.js", "version": "24.22.1",
        "url": "https://nodejs.org/dist/v24.22.1/node-v24.22.1-win-x64.zip",
        "size": 37748064,
        "sha256": "d2046d28c2c3dcd211ac5145c0bf30e2047ef9dfb306693c8c6e2eccd8b95fa5",
        "members": {
            "node-v24.22.1-win-x64/node.exe": "_internal/tools/node.exe",
            "node-v24.22.1-win-x64/LICENSE": "_internal/licenses/Node-LICENSE.txt",
        },
    },
    {
        "id": "ffmpeg", "label": "FFmpeg", "version": "9.0.2-essentials",
        "url": "https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-9.0.2-essentials_build.zip",
        "size": 114768076,
        "sha256": "60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba",
        "members": {
            "ffmpeg-9.0.2-essentials_build/bin/ffmpeg.exe": "_internal/tools/ffmpeg.exe",
            "ffmpeg-9.0.2-essentials_build/bin/ffprobe.exe": "_internal/tools/ffprobe.exe",
            "ffmpeg-9.0.2-essentials_build/LICENSE": "_internal/licenses/FFmpeg-LICENSE.txt",
            "ffmpeg-9.0.2-essentials_build/README.txt": "_internal/licenses/FFmpeg-provider-README.txt",
        },
    },
]


def load_resources(root: Path) -> list[dict]:
    config = json.loads((root / "official-resources.json").read_text(encoding="utf-8"))
    resources = config.get("resources")
    if config.get("mode") != "official-resources" or not isinstance(resources, list):
        raise DownloadProblem("اطلاعات منابع رسمی نصب معتبر نیست.")
    if [item.get("id") for item in resources] != ["node", "ffmpeg"]:
        raise DownloadProblem("فهرست ابزارهای مورد نیاز کامل نیست.")
    for resource in resources:
        validate_config(resource)
        # Extract only these fixed destinations, never arbitrary paths from the network.
        expected = next(item for item in RESOURCES if item["id"] == resource["id"])
        if any(resource.get(key) != expected[key] for key in ("members", "url", "size", "sha256")):
            raise DownloadProblem("فهرست فایل‌های ابزار نصب معتبر نیست.")
    return resources


def extract_tools(resources, archives, destination: Path) -> None:
    destination = destination.resolve()
    for resource in resources:
        with zipfile.ZipFile(archives[resource["id"]]) as archive:
            for source, relative in resource["members"].items():
                target = (destination / relative).resolve()
                if not target.is_relative_to(destination):
                    raise DownloadProblem("مسیر فایل ابزار ناامن است.")
                try:
                    info = archive.getinfo(source)
                except KeyError as exc:
                    raise DownloadProblem("فایل لازم در بسته ابزار پیدا نشد. دریافت و نصب متوقف شد.") from exc
                if info.is_dir() or info.file_size > 512 * 1024 * 1024:
                    raise DownloadProblem("فایل ابزار معتبر نیست.")
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as input_stream, target.open("wb") as output_stream:
                    shutil.copyfileobj(input_stream, output_stream, 1024 * 1024)
