from __future__ import annotations

from contextlib import closing
import tempfile
import unittest
import uuid
import sqlite3
import queue
import threading
from pathlib import Path
import sys
from unittest import mock

from download_config import (
    DownloadSettings,
    bot_download_settings,
    desktop_settings_for_url,
    format_bytes,
    has_playlist_parameter,
    premiere_streams_compatible,
    validate_proxy_url,
)
from queue_store import QueueStore
from app import (
    APP_VERSION,
    BRAND_LOGO_DARK_FILE,
    BRAND_LOGO_LIGHT_FILE,
    DownloadLogger,
    acquire_single_instance,
    existing_output_paths,
    release_single_instance,
    DownloaderApp,
    GUIDE_TEXT,
    valid_bot_token,
)


class DownloadSettingsTests(unittest.TestCase):
    def test_video_defaults_to_premiere_compatible_mode(self) -> None:
        settings = DownloadSettings(target=Path("D:/Downloads"))
        self.assertEqual(settings.mode, "premiere")

    def test_payload_round_trip(self) -> None:
        original = DownloadSettings(
            target=Path("D:/Downloads"), quality="1080", playlist=True,
            subtitles=True, thumbnail=True, proxy="socks5://127.0.0.1:1080",
        )
        self.assertEqual(DownloadSettings.from_payload(original.to_payload()), original)

    def test_payload_is_backward_and_forward_compatible(self) -> None:
        settings = DownloadSettings.from_payload({
            "target": "D:/Downloads",
            "quality": "720",
            "future_option": "ignored by this version",
        })
        self.assertEqual(settings.target, Path("D:/Downloads"))
        self.assertEqual(settings.quality, "720")
        self.assertEqual(settings.mode, "premiere")

        with self.assertRaisesRegex(ValueError, "destination folder"):
            DownloadSettings.from_payload({"quality": "720"})

    def test_bot_defaults_are_minimal(self) -> None:
        payload = bot_download_settings(Path("D:/Downloads"), "audio", "best", False)
        settings = DownloadSettings.from_payload(payload)
        self.assertEqual(settings.mode, "audio")
        self.assertFalse(settings.playlist)
        self.assertFalse(settings.thumbnail)
        self.assertEqual(settings.proxy, "")

    def test_format_bytes(self) -> None:
        self.assertEqual(format_bytes(50 * 1024 * 1024), "50.0 MiB")

    def test_premiere_format_selector_prefers_h264_and_aac(self) -> None:
        settings = DownloadSettings(target=Path("D:/Downloads"), quality="1080")
        selector = DownloaderApp._format_selector(settings)
        self.assertIn("avc1|h264", selector)
        self.assertIn("mp4a|aac", selector)
        self.assertIn("height<=1080", selector)

    def test_premiere_best_keeps_best_resolution_for_verified_conversion(self) -> None:
        settings = DownloadSettings(target=Path("D:/Downloads"), quality="best")
        self.assertEqual(
            DownloaderApp._format_selector(settings),
            "bestvideo*+bestaudio/best",
        )

    def test_premiere_4k_does_not_silently_fall_back_to_1080p(self) -> None:
        settings = DownloadSettings(target=Path("D:/Downloads"), quality="2160")
        selector = DownloaderApp._format_selector(settings)
        unrestricted_4k = "bestvideo*[height=2160]+bestaudio"
        h264_lower = "bestvideo[vcodec~='^(avc1|h264)'][ext=mp4][height<=2160]"
        self.assertIn(unrestricted_4k, selector)
        self.assertLess(selector.index(unrestricted_4k), selector.index(h264_lower))

    def test_premiere_stream_compatibility(self) -> None:
        compatible = {
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p"},
                {"codec_type": "audio", "codec_name": "aac"},
            ]
        }
        self.assertTrue(premiere_streams_compatible(compatible))
        for video_codec, audio_codec in (("av1", "opus"), ("vp9", "aac")):
            with self.subTest(video=video_codec, audio=audio_codec):
                self.assertFalse(premiere_streams_compatible({
                    "streams": [
                        {"codec_type": "video", "codec_name": video_codec, "pix_fmt": "yuv420p"},
                        {"codec_type": "audio", "codec_name": audio_codec},
                    ]
                }))

    def test_mixed_desktop_urls_detect_playlist_independently(self) -> None:
        settings = DownloadSettings(target=Path("D:/Downloads"), playlist=False)
        solo = "https://www.youtube.com/watch?v=i4reL-_DULU"
        playlist = (
            "http://www.youtube.com/watch?v=fcnDmrtj6Sk"
            "&list=PLCGIzmTE4d0iEaFQtwd8Q0tAu56U_V2L9"
        )
        self.assertFalse(has_playlist_parameter(solo))
        self.assertTrue(has_playlist_parameter(playlist))
        self.assertFalse(desktop_settings_for_url(settings, solo)["playlist"])
        self.assertTrue(desktop_settings_for_url(settings, playlist)["playlist"])

    def test_proxy_validation(self) -> None:
        self.assertEqual(validate_proxy_url(""), "")
        self.assertEqual(
            validate_proxy_url(" socks5://user:pass@127.0.0.1:1080 "),
            "socks5://user:pass@127.0.0.1:1080",
        )
        self.assertEqual(
            validate_proxy_url("http://proxy.example:8080"),
            "http://proxy.example:8080",
        )
        for invalid in ("proxy.example:8080", "ftp://proxy.example", "socks5://:1080"):
            with self.subTest(proxy=invalid):
                with self.assertRaises(ValueError):
                    validate_proxy_url(invalid)

    def test_youtube_bot_challenge_is_an_authentication_error(self) -> None:
        message = (
            "[youtube] video: Sign in to confirm you’re not a bot. "
            "Use --cookies-from-browser or --cookies for the authentication."
        )
        self.assertTrue(DownloadLogger.is_auth_message(message))

    def test_firefox_auth_help_is_actionable(self) -> None:
        settings = DownloadSettings(target=Path("D:/Downloads"), browser="firefox")
        help_text = DownloaderApp._cookie_help(settings)
        self.assertIn("sign in to YouTube in Firefox", help_text)
        self.assertIn("cookies.txt", help_text)

    def test_existing_output_paths_filters_missing_files(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            existing = Path(folder) / "video.mp4"
            existing.touch()
            missing = Path(folder) / "missing.mp4"
            self.assertEqual(
                existing_output_paths(f"{existing}\n{missing}\n"),
                [existing],
            )

    def test_public_brand_logos_are_square_and_match_live_site_assets(self) -> None:
        from PIL import Image

        for logo_path in (BRAND_LOGO_LIGHT_FILE, BRAND_LOGO_DARK_FILE):
            with self.subTest(logo=logo_path.name), Image.open(logo_path) as logo:
                self.assertEqual(logo.width, logo.height)
                self.assertGreaterEqual(logo.width, 1000)

    def test_onboarding_is_complete_and_never_requires_a_website_account(self) -> None:
        self.assertEqual(APP_VERSION, "4.6.1")
        for language, copy in GUIDE_TEXT.items():
            with self.subTest(language=language):
                self.assertEqual(len(copy["steps"]), 5)
                self.assertEqual(len(copy["titles"]), 5)
                self.assertEqual(len(copy["bodies"]), 5)
                text = str(copy).lower()
                self.assertNotIn("create free account", text)
                self.assertNotIn("activation code required", text)
                self.assertIn("robots.txt", text)

    def test_firefox_cookie_check_requires_a_youtube_login_cookie(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder) / "Mozilla" / "Firefox" / "Profiles" / "public.default"
            profile.mkdir(parents=True)
            database = profile / "cookies.sqlite"
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("CREATE TABLE moz_cookies (host TEXT, name TEXT)")
                connection.execute(
                    "INSERT INTO moz_cookies (host, name) VALUES (?, ?)",
                    (".youtube.com", "PREF"),
                )
                connection.commit()
            with mock.patch.dict("os.environ", {"APPDATA": folder}):
                self.assertFalse(DownloaderApp._has_firefox_login_cookies())
                with closing(sqlite3.connect(database)) as connection:
                    connection.execute(
                        "INSERT INTO moz_cookies (host, name) VALUES (?, ?)",
                        (".youtube.com", "SAPISID"),
                    )
                    connection.commit()
                self.assertTrue(DownloaderApp._has_firefox_login_cookies())

    def test_bot_token_validation_rejects_placeholders(self) -> None:
        self.assertTrue(valid_bot_token("123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdef"))
        for invalid in ("", "paste-token-here", "123:short", "6124743404"):
            with self.subTest(token=invalid):
                self.assertFalse(valid_bot_token(invalid))

    @unittest.skipUnless(sys.platform == "win32", "Windows named mutex")
    def test_single_instance_guard(self) -> None:
        name = rf"Local\AIwithSaeed.Downloader.Test.{uuid.uuid4()}"
        first = acquire_single_instance(name)
        self.assertIsNotNone(first)
        try:
            self.assertIsNone(acquire_single_instance(name))
        finally:
            release_single_instance(first)
        replacement = acquire_single_instance(name)
        self.assertIsNotNone(replacement)
        release_single_instance(replacement)


class QueueStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = QueueStore(Path(self.temp.name) / "queue.db")
        self.settings = DownloadSettings(target=Path("D:/Downloads")).to_payload()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_playlist_expansion_preserves_position(self) -> None:
        first, playlist, last = self.store.add_jobs(
            ["first", "playlist", "last"], self.settings
        )
        child_settings = dict(self.settings, playlist=False)
        children = self.store.replace_with_entries(
            playlist,
            [("video-1", "Video 1"), ("video-2", "Video 2"), ("video-3", "Video 3")],
            child_settings,
        )
        self.assertEqual(len(children), 3)
        self.assertEqual(
            [job["url"] for job in self.store.list_jobs()],
            ["first", "video-1", "video-2", "video-3", "last"],
        )
        self.assertEqual(first, self.store.claim_next()["id"])

    def test_pause_resume_and_delete(self) -> None:
        queued, active = self.store.add_jobs(["queued", "active"], self.settings)
        self.assertTrue(self.store.pause(queued))
        self.assertEqual(self.store.get(queued)["status"], "paused")
        self.assertTrue(self.store.resume(queued))
        self.store.update(active, status="downloading")
        self.assertEqual(self.store.remove(active), "stopping")
        self.assertEqual(self.store.get(active)["control"], "remove")
        self.assertEqual(self.store.remove(queued), "removed")
        self.assertIsNone(self.store.get(queued))

    def test_bulk_pause_resume_and_delete(self) -> None:
        queued, active, paused, failed, completed = self.store.add_jobs(
            ["queued", "active", "paused", "failed", "completed"], self.settings
        )
        self.store.update(active, status="downloading")
        self.store.update(paused, status="paused")
        self.store.update(failed, status="failed", error="network")
        self.store.update(completed, status="completed")

        changed = self.store.pause_many([queued, active, completed, queued])
        self.assertEqual(set(changed), {queued, active})
        self.assertEqual(self.store.get(queued)["status"], "paused")
        self.assertEqual(self.store.get(active)["control"], "pause")
        self.assertEqual(self.store.get(completed)["status"], "completed")

        resumed = self.store.resume_many([queued, paused, failed, completed])
        self.assertEqual(set(resumed), {queued, paused, failed})
        for job_id in (queued, paused, failed):
            self.assertEqual(self.store.get(job_id)["status"], "queued")

        result = self.store.remove_many([active, queued, completed])
        self.assertEqual(result["stopping"], [active])
        self.assertEqual(set(result["removed"]), {queued, completed})
        self.assertEqual(self.store.get(active)["control"], "remove")
        self.assertIsNone(self.store.get(queued))
        self.assertIsNone(self.store.get(completed))

    def test_corrupt_database_is_preserved_and_rebuilt(self) -> None:
        broken_path = Path(self.temp.name) / "broken.db"
        broken_path.write_bytes(b"SQLite format 3\0truncated")

        recovered = QueueStore(broken_path)

        self.assertIsNotNone(recovered.recovery_backup)
        self.assertTrue(recovered.recovery_backup.is_file())
        self.assertEqual(
            recovered.get_preference("appearance_mode", "light"),
            "light",
        )
        self.assertEqual(recovered.list_jobs(), [])

    def test_temporary_database_lock_is_not_treated_as_corruption(self) -> None:
        locked_path = Path(self.temp.name) / "locked.db"
        locked_path.write_bytes(b"healthy-placeholder")
        with mock.patch.object(
            QueueStore,
            "_initialize",
            side_effect=sqlite3.OperationalError("database is locked"),
        ):
            with self.assertRaisesRegex(sqlite3.OperationalError, "locked"):
                QueueStore(locked_path)
        self.assertEqual(locked_path.read_bytes(), b"healthy-placeholder")
        self.assertEqual(list(locked_path.parent.glob("locked.corrupt-*")), [])

    def test_shared_preference_round_trip(self) -> None:
        self.assertEqual(self.store.get_preference("download_proxy"), "")
        self.store.set_preference("download_proxy", "socks5://127.0.0.1:1080")
        self.assertEqual(
            self.store.get_preference("download_proxy"),
            "socks5://127.0.0.1:1080",
        )

    def test_waiting_job_uses_current_connection_preferences(self) -> None:
        stale = DownloadSettings(
            target=Path("D:/Downloads"),
            proxy="http://old-proxy.example:8080",
            browser="chrome",
        )
        job_id = self.store.add_jobs(["video"], stale.to_payload())[0]
        self.store.set_preference("download_proxy", "")
        self.store.set_preference("browser", "firefox")
        self.store.set_preference("cookie_file", "")

        worker = DownloaderApp.__new__(DownloaderApp)
        worker.job_store = self.store
        updated = worker._apply_shared_connection_settings(job_id, stale)

        self.assertEqual(updated.proxy, "")
        self.assertEqual(updated.browser, "firefox")
        self.assertEqual(updated.cookie_file, "")
        saved = DownloadSettings.from_payload(self.store.settings(self.store.get(job_id)))
        self.assertEqual(saved, updated)

    def test_playlist_setting_can_fall_back_to_single_video(self) -> None:
        settings = dict(self.settings, playlist=True)
        job_id = self.store.add_jobs(["single-video"], settings)[0]
        settings["playlist"] = False
        self.store.set_settings(job_id, settings)
        saved = self.store.settings(self.store.get(job_id))
        self.assertFalse(saved["playlist"])

    def test_interrupted_jobs_are_recovered_without_unpausing_user_jobs(self) -> None:
        downloading, processing, paused = self.store.add_jobs(
            ["downloading", "processing", "paused"], self.settings
        )
        self.store.update(downloading, status="downloading", control="pause")
        self.store.update(processing, status="processing", control="remove")
        self.store.update(paused, status="paused", control="")

        self.store.recover_interrupted()

        for job_id in (downloading, processing):
            job = self.store.get(job_id)
            self.assertEqual(job["status"], "queued")
            self.assertEqual(job["control"], "")
            self.assertEqual(job["detail"], "Resuming after restart")
        self.assertEqual(self.store.get(paused)["status"], "paused")

    def test_invalid_job_settings_fail_cleanly_without_stranding_worker(self) -> None:
        job_id = self.store.add_jobs(["https://example.com/video"], self.settings)[0]
        self.store.set_settings(job_id, {})

        worker = DownloaderApp.__new__(DownloaderApp)
        worker.job_store = self.store
        worker.current_job_id = None
        worker.current_control = ""
        worker.cancel_event = threading.Event()
        worker.output_candidates = set()
        worker.events = queue.Queue()
        with mock.patch("app.LOGGER.exception"):
            worker._download_worker()

        job = self.store.get(job_id)
        self.assertEqual(job["status"], "failed")
        self.assertIn("destination folder", job["error"])
        self.assertIsNone(worker.current_job_id)


if __name__ == "__main__":
    unittest.main()
