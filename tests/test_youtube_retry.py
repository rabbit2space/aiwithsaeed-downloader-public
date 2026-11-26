from pathlib import Path
import queue
import tempfile
import threading
import unittest
from unittest import mock

from app import DownloaderApp, DownloadLogger, DownloadCancelled
from download_config import DownloadSettings, CollectionScopeError, retry_youtube_without_cookies


class YouTubeRetryTests(unittest.TestCase):
    def setUp(self):
        self.worker = DownloaderApp.__new__(DownloaderApp)
        self.worker.cancel_event = threading.Event()
        self.worker.events = queue.Queue()
        self.worker.output_candidates = {Path("unfinished-original.mp4")}
        self.worker._javascript_runtime = lambda: None
        self.worker._media_tool = lambda _: None
        self.settings = DownloadSettings(Path("downloads"), browser="firefox", proxy="http://127.0.0.1:8080")
        self.url = "https://www.youtube.com/watch?v=example"
        self.logger = DownloadLogger()

    def test_only_authenticated_youtube_403_qualifies(self):
        self.assertTrue(retry_youtube_without_cookies(self.settings, self.url, "HTTP Error 403: Forbidden"))
        for url in ("https://instagram.com/reel/example", "https://youtube.com.example.org/watch?v=example"):
            self.assertFalse(retry_youtube_without_cookies(self.settings, url, "HTTP Error 403"))
        self.assertFalse(retry_youtube_without_cookies(DownloadSettings(Path("downloads")), self.url, "HTTP Error 403"))
        self.assertFalse(retry_youtube_without_cookies(self.settings, self.url, "HTTP Error 429"))

    def test_403_exception_reextracts_once_without_cookies_and_preserves_settings(self):
        with mock.patch("app.yt_dlp.YoutubeDL") as constructor, \
                mock.patch("app.download_single", side_effect=[RuntimeError("HTTP Error 403: Forbidden"), 0]) as download:
            result = self.worker._download_single_with_fallback(self.url, self.settings, self.logger)
        self.assertEqual(result, 0)
        self.assertEqual(download.call_count, 2)
        first, second = [call.args[0] for call in constructor.call_args_list]
        self.assertEqual(first["cookiesfrombrowser"], ("firefox",))
        self.assertNotIn("cookiesfrombrowser", second)
        self.assertNotIn("cookiefile", second)
        self.assertEqual(second["proxy"], self.settings.proxy)
        self.assertEqual(second["format"], first["format"])
        self.assertTrue(second["noplaylist"])
        self.assertEqual(self.settings.browser, "firefox")
        self.assertEqual(self.worker.output_candidates, set())
        self.assertEqual(self.worker.events.get_nowait()[0], "youtube_guest_retry")

    def test_logged_download_failure_also_retries_without_cookie_file(self):
        settings = DownloadSettings(Path("downloads"), cookie_file="private-cookies.txt")
        # Use a counter: the logger is deliberately cleared for the fresh attempt.
        calls = iter((1, 0))
        def download(*_):
            result = next(calls)
            if result:
                self.logger.error("unable to download video data: HTTP Error 403: Forbidden")
            return result
        with mock.patch("app.yt_dlp.YoutubeDL") as constructor, mock.patch("app.download_single", side_effect=download):
            self.assertEqual(self.worker._download_single_with_fallback(self.url, settings, self.logger), 0)
        self.assertEqual(constructor.call_count, 2)
        self.assertNotIn("cookiefile", constructor.call_args.args[0])
        self.assertEqual(self.logger.last_error, "")

    def test_failed_guest_attempt_does_not_loop_or_hide_failure(self):
        with mock.patch("app.yt_dlp.YoutubeDL") as constructor, \
                mock.patch("app.download_single", side_effect=RuntimeError("HTTP Error 403")):
            with self.assertRaisesRegex(RuntimeError, "403"):
                self.worker._download_single_with_fallback(self.url, self.settings, self.logger)
        self.assertEqual(constructor.call_count, 2)

    def test_missing_authenticated_formats_reextract_without_changing_quality(self):
        message = "[youtube] example: Requested format is not available. Use --list-formats"
        with mock.patch("app.yt_dlp.YoutubeDL") as constructor, \
                mock.patch("app.download_single", side_effect=[RuntimeError(message), 0]) as download:
            self.assertEqual(self.worker._download_single_with_fallback(self.url, self.settings, self.logger), 0)
        self.assertEqual(download.call_count, 2)
        original, guest = [call.args[0] for call in constructor.call_args_list]
        self.assertEqual(guest["format"], original["format"])
        self.assertNotIn("cookiesfrombrowser", guest)
        self.assertEqual(self.settings.quality, "best")

    def test_image_only_authenticated_metadata_qualifies_but_guest_does_not(self):
        message = "Only images are available for download. use --list-formats to see them"
        self.assertTrue(retry_youtube_without_cookies(self.settings, self.url, message))
        self.assertFalse(retry_youtube_without_cookies(DownloadSettings(Path("downloads")), self.url, message))
        self.assertFalse(retry_youtube_without_cookies(self.settings, "https://example.org/video", message))

    def test_missing_guest_formats_fail_once_instead_of_retrying_forever(self):
        settings = DownloadSettings(Path("downloads"))
        with mock.patch("app.yt_dlp.YoutubeDL") as constructor, \
                mock.patch("app.download_single", side_effect=RuntimeError("Requested format is not available")):
            with self.assertRaisesRegex(RuntimeError, "format"):
                self.worker._download_single_with_fallback(self.url, settings, self.logger)
        self.assertEqual(constructor.call_count, 1)

    def test_collection_scope_and_cancellation_are_never_retried(self):
        for error in (CollectionScopeError("HTTP Error 403"), DownloadCancelled()):
            with mock.patch("app.yt_dlp.YoutubeDL") as constructor, \
                    mock.patch("app.download_single", side_effect=error):
                with self.assertRaises(type(error)):
                    self.worker._download_single_with_fallback(self.url, self.settings, self.logger)
            self.assertEqual(constructor.call_count, 1)

    def test_thumbnail_alone_is_not_a_completed_media_output(self):
        with tempfile.TemporaryDirectory() as directory:
            thumbnail = Path(directory) / "cover.jpg"
            thumbnail.write_bytes(b"thumbnail")
            self.worker.output_candidates = {thumbnail}
            self.assertEqual(self.worker._completed_outputs(Path(directory), 0), [])

    def test_failed_queue_row_shows_reason(self):
        self.worker.language = "en"
        job = dict(status="failed", control="", file_path="", progress=None, source="desktop",
                   title="Example video", url=self.url, error="HTTP Error 403: Forbidden")
        _, _, label = self.worker._queue_row_values(job)
        self.assertIn("Example video", label)
        self.assertIn("403: Forbidden", label)
