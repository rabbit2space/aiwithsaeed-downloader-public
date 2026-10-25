"""Bundle our app; fetch supporting tools from pinned official publisher URLs."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

from official_resources import RESOURCES, extract_tools
from online_download import download_payload

ROOT = Path(__file__).resolve().parent


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def bundle(args: list[str], pyinstaller_path: str | None) -> None:
    bootstrap = "import sys; " + (f"sys.path.append({pyinstaller_path!r}); " if pyinstaller_path else "")
    subprocess.run([sys.executable, "-c", bootstrap + "from PyInstaller.__main__ import run; run(sys.argv[1:])", *args],
                   cwd=ROOT, check=True)


def zip_folder(folder: Path, target: Path) -> None:
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(folder.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() in {".db", ".log", ".dpapi"} or path.name.startswith("cookies") and path.suffix == ".txt":
                raise RuntimeError(f"Private runtime file in app bundle: {path.name}")
            archive.write(path, path.relative_to(folder))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pyinstaller-path", help="Optional offline directory containing the build tools")
    parser.add_argument("--portable", action="store_true", help="Also fetch official tools and create a self-contained portable ZIP")
    arguments = parser.parse_args()
    version = re.search(r'^APP_VERSION = "([\d.]+)"', (ROOT / "app.py").read_text(encoding="utf-8"), re.M)[1]
    work = ROOT / "build" / version
    work.mkdir(parents=True, exist_ok=True)
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    licenses = work / "licenses"
    licenses.mkdir(exist_ok=True)
    shutil.copy2(Path(sys.base_prefix) / "LICENSE.txt", licenses / "Python-LICENSE.txt")
    for notice in (ROOT / "licenses").glob("*.txt"):
        shutil.copy2(notice, licenses / notice.name)
    for component in (Path(sys.base_prefix) / "tcl").glob("*"):
        candidate = component / "license.terms"
        if candidate.is_file():
            shutil.copy2(candidate, licenses / f"{component.name}-LICENSE.txt")
    for distribution in importlib.metadata.distributions():
        for file in distribution.files or []:
            if any(part.lower().startswith(("license", "copying")) for part in file.parts):
                source = distribution.locate_file(file)
                if source.is_file():
                    target = licenses / distribution.metadata["Name"] / file.name
                    target.parent.mkdir(exist_ok=True)
                    shutil.copy2(source, target)
    from PIL import Image
    icon = work / "brand.ico"
    with Image.open(ROOT / "assets" / "aiwithsaeed-logo-light.png") as logo:
        logo.save(icon, format="ICO", sizes=[(32, 32), (48, 48), (128, 128), (256, 256)])
    common = ["--noconfirm", "--clean", "--windowed", "--noupx", "--icon", str(icon),
              "--specpath", str(work), "--workpath", str(work / "pyinstaller")]
    bundle([*common, "--onedir", "--name", "AIwithSaeed-Downloader", "--distpath", str(dist / f"Windows-v{version}"),
            "--collect-all", "customtkinter", "--collect-all", "tkinterdnd2",
            "--collect-all", "yt_dlp", "--collect-all", "yt_dlp_ejs", "--collect-all", "telegram",
            "--copy-metadata", "yt-dlp", "--add-data", f"{ROOT / 'assets'};assets",
            "--add-data", f"{licenses};licenses", str(ROOT / "launcher.pyw")], arguments.pyinstaller_path)
    core = dist / f"Windows-v{version}" / "AIwithSaeed-Downloader"
    web_fonts = core / "assets"
    web_fonts.mkdir(exist_ok=True)
    for name in ("Peyda-Regular.ttf", "Peyda-Bold.ttf", "Peyda-LICENSE-NOTICE.txt"):
        shutil.copy2(ROOT / "assets" / name, web_fonts / name)
    for name in ("QUICK-START-FA.html", "THIRD-PARTY.md", "LICENSE"):
        shutil.copy2(ROOT / name, core / name)
    dependencies = {name: importlib.metadata.version(name) for name in
                    ("yt-dlp", "yt-dlp-ejs", "certifi", "Pillow", "customtkinter", "tkinterdnd2", "python-telegram-bot")}
    manifest = {"product": "AIwithSaeed.Downloader", "version": version,
                "python": sys.version, "source_app_sha256": sha256(ROOT / "app.py"), "tools": "official downloads at install time"}
    manifest["dependencies"] = dependencies
    (core / "installation.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    payload = work / "payload.zip"
    zip_folder(core, payload)
    (work / "payload.sha256").write_text(sha256(payload), encoding="ascii")
    config = {"mode": "official-resources", "version": version, "resources": RESOURCES}
    resources_file = work / "official-resources.json"
    resources_file.write_text(json.dumps(config, indent=2), encoding="utf-8")
    shutil.copy2(resources_file, dist / f"official-resources-v{version}.json")
    font_data = []
    for name in ("Peyda-Regular.ttf", "Peyda-Bold.ttf", "Peyda-LICENSE-NOTICE.txt"):
        font_data.extend(["--add-data", f"{ROOT / 'assets' / name};assets"])
    online_name = f"AIwithSaeed-Downloader-v{version}-Online-Setup"
    bundle([*common, "--onefile", "--name", online_name, "--distpath", str(dist), *font_data,
            "--add-data", f"{payload};.", "--add-data", f"{work / 'payload.sha256'};.",
            "--add-data", f"{resources_file};.", str(ROOT / "windows_installer.py")], arguments.pyinstaller_path)
    artifacts = [dist / f"{online_name}.exe"]
    if arguments.portable:
        cache = ROOT / ".build-tools" / "official-cache"
        archives = {resource["id"]: download_payload(resource, cache, lambda value: None, lambda text: None) for resource in RESOURCES}
        portable_folder = work / "portable"
        shutil.copytree(core, portable_folder, dirs_exist_ok=True)
        extract_tools(RESOURCES, archives, portable_folder)
        target = dist / f"AIwithSaeed-Downloader-v{version}-Portable.zip"
        zip_folder(portable_folder, target)
        artifacts.append(target)
    (dist / f"SHA256SUMS-v{version}-Windows.txt").write_text(
        "".join(f"{sha256(path)}  {path.name}\n" for path in artifacts), encoding="ascii")
    print(f"Installer: {artifacts[0]}\nNo custom server or payload upload is required.")


if __name__ == "__main__":
    main()
