from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse, urlsplit


@dataclass(frozen=True)
class DownloadSettings:
    target: Path
    mode: str = "premiere"
    quality: str = "best"
    playlist: bool = False
    subtitles: bool = False
    auto_subtitles: bool = False
    subtitle_langs: str = "en"
    thumbnail: bool = False
    embed_thumbnail: bool = False
    metadata: bool = True
    description: bool = False
    browser: str = "none"
    cookie_file: str = ""
    proxy: str = ""

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["target"] = str(self.target)
        return payload

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "DownloadSettings":
        if not isinstance(payload, dict):
            raise ValueError("Download settings must be an object.")
        allowed = {field.name for field in fields(cls)}
        # Ignore fields written by a newer app version so rolling back does not
        # strand existing queue items. Missing optional fields use dataclass defaults.
        values = {key: value for key, value in payload.items() if key in allowed}
        target = values.get("target")
        if not isinstance(target, (str, Path)) or not str(target).strip():
            raise ValueError("Download settings are missing a destination folder.")
        values["target"] = Path(target)
        return cls(**values)


def bot_download_settings(target: Path, mode: str, quality: str, playlist: bool) -> dict[str, Any]:
    return DownloadSettings(
        target=target, mode=mode, quality=quality, playlist=playlist
    ).to_payload()


def has_playlist_parameter(url: str) -> bool:
    """Return True when a video URL explicitly belongs to a playlist."""
    try:
        return bool(parse_qs(urlparse(url).query).get("list"))
    except (TypeError, ValueError):
        return False


def desktop_settings_for_url(settings: DownloadSettings, url: str) -> dict[str, Any]:
    """Apply desktop settings while automatically honoring explicit playlist URLs."""
    payload = settings.to_payload()
    if has_playlist_parameter(url):
        payload["playlist"] = True
    return payload


SUPPORTED_PROXY_SCHEMES = {
    "http", "https", "socks4", "socks4a", "socks5", "socks5h",
}


def validate_proxy_url(value: str) -> str:
    """Validate an optional yt-dlp HTTP(S) or SOCKS proxy URL."""
    proxy = value.strip()
    if not proxy:
        return ""
    if any(character.isspace() for character in proxy):
        raise ValueError("Proxy URL cannot contain spaces.")
    try:
        parsed = urlsplit(proxy)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Proxy URL contains an invalid port or address.") from exc
    if parsed.scheme.lower() not in SUPPORTED_PROXY_SCHEMES:
        raise ValueError(
            "Proxy must start with http://, https://, socks4://, or socks5://."
        )
    if not parsed.hostname:
        raise ValueError("Proxy URL must include a hostname or IP address.")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("Proxy URL should contain only the server address and optional login.")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Proxy port must be between 1 and 65535.")
    return proxy


def format_bytes(value: float | int | None) -> str:
    if not value:
        return "0 B"
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TiB"


def premiere_streams_compatible(probe: dict[str, Any]) -> bool:
    """Return whether ffprobe output describes an edit-safe Premiere MP4."""
    streams = probe.get("streams") or []
    video = next(
        (stream for stream in streams if stream.get("codec_type") == "video"),
        None,
    )
    audio = next(
        (stream for stream in streams if stream.get("codec_type") == "audio"),
        None,
    )
    if not video or video.get("codec_name") != "h264":
        return False
    if video.get("pix_fmt") not in {"yuv420p", "yuvj420p"}:
        return False
    return audio is None or audio.get("codec_name") == "aac"
