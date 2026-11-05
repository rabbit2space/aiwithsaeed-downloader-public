from copy import deepcopy
from pathlib import Path
import queue
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

from app import DownloaderApp
from download_config import DownloadSettings, desktop_settings_for_url, download_single, is_collection_url
from queue_store import QueueStore


class ScopeTests(unittest.TestCase):
    def test_collection_is_an_explicit_choice(self):
        url = "https://www.youtube.com/watch?v=video&list=unrelated-mix"
        for consent in (False, True):
            payload = desktop_settings_for_url(DownloadSettings(Path("downloads"), playlist=consent), url)
            self.assertEqual(payload["playlist"], consent)
            self.assertEqual(payload["collection_confirmed"], consent)

    def test_collection_pages_are_not_single_videos(self):
        for url in ("https://youtube.com/@example/videos", "https://youtube.com/playlist?list=abc",
                    "https://youtube.com/channel/abc", "https://instagram.com/example/"):
            with self.subTest(url=url):
                self.assertTrue(is_collection_url(url))
        for url in ("https://youtube.com/watch?v=abc&list=xyz", "https://youtu.be/abc",
                    "https://youtube.com/shorts/abc", "https://instagram.com/reel/abc/"):
            with self.subTest(url=url):
                self.assertFalse(is_collection_url(url))

    def test_unexpected_collection_downloads_nothing(self):
        for kind in ("playlist", "multi_video"):
            ydl = SimpleNamespace(extract_info=mock.Mock(return_value={"_type": kind, "entries": iter([{}])}),
                                  process_ie_result=mock.Mock())
            with self.assertRaisesRegex(ValueError, "collection"):
                download_single(ydl, "https://example.org/page")
            ydl.extract_info.assert_called_once_with("https://example.org/page", download=False)
            ydl.process_ie_result.assert_not_called()

    def test_single_video_uses_resolved_metadata(self):
        info = {"id": "one-video", "url": "https://example.org/media.mp4"}
        ydl = SimpleNamespace(extract_info=mock.Mock(return_value=info),
                              process_ie_result=mock.Mock(return_value=info), _download_retcode=0)
        self.assertEqual(download_single(ydl, "https://example.org/watch"), 0)
        ydl.process_ie_result.assert_called_once_with(info, download=True)


class QueueSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = QueueStore(self.root / "queue.db")

    def tearDown(self):
        self.temp.cleanup()

    def worker(self):
        worker = DownloaderApp.__new__(DownloaderApp)
        worker.job_store = self.store
        worker.events = queue.Queue()
        worker.cancel_event = threading.Event()
        worker.output_candidates = set()
        worker.current_job_id, worker.current_control = None, ""
        worker.closing = False
        return worker

    def test_old_automatic_playlist_jobs_wait_for_consent(self):
        payload = DownloadSettings(self.root, playlist=True).to_payload()
        job_id = self.store.add_jobs(["https://youtube.com/watch?v=abc&list=xyz"], payload)[0]
        worker = self.worker()
        with mock.patch.object(DownloaderApp, "_playlist_entries") as extract:
            worker._run_claimed_job(self.store.claim_next())
        extract.assert_not_called()
        self.assertEqual(self.store.get(job_id)["status"], "paused")

    def test_upgrade_pauses_legacy_pending_items_once_without_deleting_them(self):
        payload = DownloadSettings(self.root).to_payload()
        first, second = self.store.add_jobs(["old-expanded-child", "old-manual-item"], payload)
        self.store.recover_interrupted()
        self.assertEqual(self.store.get(first)["status"], "paused")
        self.assertEqual(self.store.get(second)["status"], "paused")
        self.store.resume(first)
        self.store.recover_interrupted()
        self.assertEqual(self.store.get(first)["status"], "queued")
        self.assertEqual(self.store.get(second)["status"], "paused")

    def test_remove_during_expansion_cannot_create_children(self):
        payload = DownloadSettings(self.root, playlist=True, collection_confirmed=True).to_payload()
        job_id = self.store.add_jobs(["collection"], payload)[0]
        self.store.claim_next()
        self.store.update(job_id, status="expanding")
        self.store.remove(job_id)
        self.assertEqual(self.store.replace_with_entries(job_id, [("video", "title")], payload), [])
        self.assertEqual(len(self.store.list_jobs()), 1)
        self.assertEqual(self.store.get(job_id)["control"], "remove")

    def test_pause_during_expansion_cannot_create_children(self):
        payload = DownloadSettings(self.root, playlist=True, collection_confirmed=True).to_payload()
        job_id = self.store.add_jobs(["collection"], payload)[0]
        self.store.claim_next()
        self.store.pause(job_id)
        self.assertEqual(self.store.replace_with_entries(job_id, [("video", "title")], payload), [])

    def test_unrelated_recent_files_are_never_selected_for_conversion(self):
        unrelated = self.root / "unrelated.mp4"
        unrelated.write_bytes(b"unrelated")
        worker = self.worker()
        self.assertEqual(worker._completed_outputs(self.root, 0), [])
        owned = self.root / "owned.mp4"
        owned.write_bytes(b"owned")
        worker.output_candidates.add(owned)
        self.assertEqual(worker._completed_outputs(self.root, 0), [owned])

    def test_worker_failure_does_not_block_following_job(self):
        payload = DownloadSettings(self.root).to_payload()
        first, second = self.store.add_jobs(["first", "second"], payload)
        worker = self.worker()
        def run(job_id, *args):
            if job_id == first:
                return 7, ""
            self.store.update(job_id, status="completed")
            return 0, ""
        with mock.patch("job_runner.run_isolated_job", side_effect=run):
            worker._download_worker()
        self.assertEqual(self.store.get(first)["status"], "failed")
        self.assertEqual(self.store.get(second)["status"], "completed")

    def test_external_remove_is_finalized_then_next_job_runs(self):
        payload = DownloadSettings(self.root).to_payload()
        first, second = self.store.add_jobs(["first", "second"], payload)
        worker = self.worker()
        def run(job_id, data_root, event, control):
            if job_id == first:
                self.store.remove(job_id)  # Same control path used by Telegram.
                self.assertEqual(control(), "remove")
                return 1, "remove"
            self.store.update(job_id, status="completed")
            return 0, ""
        with mock.patch("job_runner.run_isolated_job", side_effect=run):
            worker._download_worker()
        self.assertIsNone(self.store.get(first))
        self.assertEqual(self.store.get(second)["status"], "completed")

    def test_cancel_cleans_only_reported_conversion_temporaries(self):
        payload = DownloadSettings(self.root).to_payload()
        job_id = self.store.add_jobs(["video"], payload)[0]
        temporary = self.root / ".video.premiere-123.tmp.mp4"
        original = self.root / "video.mp4"
        temporary.write_bytes(b"partial render")
        original.write_bytes(b"original")
        worker = self.worker()
        def run(identifier, data_root, event, control):
            event(("render_temp", str(temporary)))
            event(("render_temp", str(original)))
            self.store.remove(identifier)
            return 1, "remove"
        with mock.patch("job_runner.run_isolated_job", side_effect=run):
            worker._download_worker()
        self.assertIsNone(self.store.get(job_id))
        self.assertFalse(temporary.exists())
        self.assertEqual(original.read_bytes(), b"original")
