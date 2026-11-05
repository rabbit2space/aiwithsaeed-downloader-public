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
    collection_confirmed: bool = False
    encoder: str = "auto"
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
        target=target, mode=mode, quality=quality, playlist=playlist,
        collection_confirmed=playlist,
    ).to_payload()


def has_playlist_parameter(url: str) -> bool:
    """Return True when a video URL explicitly belongs to a playlist."""
    try:
        return bool(parse_qs(urlparse(url).query).get("list"))
    except (TypeError, ValueError):
        return False


def desktop_settings_for_url(settings: DownloadSettings, url: str) -> dict[str, Any]:
    """Preserve explicit scope; a copied list= parameter is not consent."""
    payload = settings.to_payload()
    payload["collection_confirmed"] = bool(settings.playlist)
    return payload


class CollectionScopeError(ValueError):
    pass


def download_single(ydl: Any, url: str) -> int:
    """Resolve metadata first and reject collections before downloading any media."""
    info = ydl.extract_info(url, download=False)
    if not info:
        return 1
    if "entries" in info or info.get("_type") in {"playlist", "multi_video", "compat_list"}:
        raise CollectionScopeError("This link opens a playlist or profile. Enable Playlist / channel explicitly to download the collection.")
    result = ydl.process_ie_result(info, download=True)
    return int(getattr(ydl, "_download_retcode", 0)) if result else 1


def is_collection_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    path = parsed.path.rstrip("/")
    if host in {"youtube.com", "music.youtube.com"}:
        return (not path or path == "/playlist" or path == "/feed" or path.startswith("/feed/")
                or path.startswith(("/@", "/channel/", "/c/", "/user/"))
                or path in {"/shorts", "/videos"}
                or (path == "/watch" and not parse_qs(parsed.query).get("v")))
    if host == "instagram.com":
        return not path.startswith(("/p/", "/reel/", "/reels/", "/tv/"))
    return False


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
