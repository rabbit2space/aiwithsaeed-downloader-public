import asyncio
import importlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from app import DownloaderApp
from download_config import DownloadSettings
from queue_store import QueueStore


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        with mock.patch("queue_store.QueueStore"):
            self.bot = importlib.import_module("bot")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = QueueStore(self.root / "queue.db")
        self.store_patch = mock.patch.object(self.bot, "STORE", self.store)
        self.store_patch.start()
        self.addCleanup(self.store_patch.stop)
        self.application = SimpleNamespace(bot=SimpleNamespace(
            send_message=mock.AsyncMock(), send_document=mock.AsyncMock()))

    def completed(self, *names):
        files = []
        for name in names:
            path = self.root / name
            path.write_bytes(b"video")
            files.append(path)
        job_id = self.store.add_jobs(["https://example.org/video"],
            DownloadSettings(self.root).to_payload(), source="telegram", chat_id=42)[0]
        self.store.update(job_id, status="completed", file_path="\n".join(map(str, files)))
        return job_id, files

    async def one_cycle(self):
        with mock.patch.object(self.bot, "allowed_chat_id", return_value=42), \
                mock.patch.object(self.bot.asyncio, "sleep", new=mock.AsyncMock(side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError):
                await self.bot.delivery_loop(self.application)

    async def test_uploads_default_off_and_file_stays_on_pc(self):
        job_id, files = self.completed("video.mp4")
        await self.one_cycle()
        self.application.bot.send_document.assert_not_awaited()
        messages = [c.kwargs["text"] for c in self.application.bot.send_message.await_args_list]
        self.assertTrue(any(str(files[0]) in message for message in messages))
        self.assertTrue(any("خاموش" in message for message in messages))
        self.assertEqual(files[0].read_bytes(), b"video")
        self.assertEqual(self.store.get(job_id)["delivered"], 1)

    async def test_enabled_uploads_only_files_below_limit(self):
        self.store.set_preference("telegram_uploads", "1")
        _, files = self.completed("small.mp4", "large.mp4")
        files[1].write_bytes(b"1234567890")
        with mock.patch.object(self.bot, "TELEGRAM_FILE_LIMIT", 10):
            await self.one_cycle()
        self.application.bot.send_document.assert_awaited_once()
        self.assertEqual(self.application.bot.send_document.await_args.kwargs["filename"], "small.mp4")
        self.assertTrue(any("Too large" in c.kwargs["text"] and str(files[1]) in c.kwargs["text"]
                            for c in self.application.bot.send_message.await_args_list))

    async def test_disable_between_files_applies_without_bot_restart(self):
        self.store.set_preference("telegram_uploads", "1")
        _, files = self.completed("first.mp4", "second.mp4")
        async def disable_uploads(**kwargs):
            self.store.set_preference("telegram_uploads", "0")
        self.application.bot.send_document.side_effect = disable_uploads
        await self.one_cycle()
        self.application.bot.send_document.assert_awaited_once()
        self.assertTrue(any(str(files[1]) in c.kwargs["text"]
                            for c in self.application.bot.send_message.await_args_list))

    async def test_reenabling_does_not_upload_past_local_completions(self):
        self.completed("video.mp4")
        await self.one_cycle()
        self.application.bot.send_message.reset_mock()
        self.store.set_preference("telegram_uploads", "1")
        await self.one_cycle()
        self.application.bot.send_document.assert_not_awaited()
        self.application.bot.send_message.assert_not_awaited()

    async def test_notifications_and_english_local_path_remain_enabled(self):
        self.store.set_preference("language", "en")
        self.completed("video.mp4")
        await self.one_cycle()
        self.assertTrue(any("uploads are off" in c.kwargs["text"]
                            for c in self.application.bot.send_message.await_args_list))

    def test_app_switch_persists_for_other_processes_and_restarts(self):
        switch = SimpleNamespace(job_store=self.store, telegram_uploads=SimpleNamespace(get=lambda: True))
        DownloaderApp._toggle_telegram_uploads(switch)
        self.assertEqual(QueueStore(self.store.path).get_preference("telegram_uploads", "0"), "1")
        switch.telegram_uploads.get = lambda: False
        DownloaderApp._toggle_telegram_uploads(switch)
        self.assertEqual(QueueStore(self.store.path).get_preference("telegram_uploads", "1"), "0")
