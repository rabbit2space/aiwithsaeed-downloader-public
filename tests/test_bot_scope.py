import importlib
from types import SimpleNamespace
import unittest
from unittest import mock


class BotScopeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Do not open a developer's real Telegram queue during import.
        with mock.patch("queue_store.QueueStore"):
            self.bot = importlib.import_module("bot")

    def update(self, message_id):
        query = SimpleNamespace(message=SimpleNamespace(message_id=message_id),
                                answer=mock.AsyncMock(), edit_message_text=mock.AsyncMock(),
                                data="get:video:best")
        return SimpleNamespace(callback_query=query, effective_chat=SimpleNamespace(id=1))

    async def test_old_format_button_cannot_start_new_pending_links(self):
        context = SimpleNamespace(chat_data={"pending_urls": ["new-link"],
                                             "pending_message_id": 20, "pending_playlist": True})
        with mock.patch.object(self.bot, "reject_unauthorized", new=mock.AsyncMock(return_value=False)), mock.patch.object(self.bot, "STORE") as store:
            await self.bot.choose_download(self.update(19), context)
        store.add_jobs.assert_not_called()
        self.assertEqual(context.chat_data["pending_urls"], ["new-link"])

    async def test_format_button_cannot_skip_collection_question(self):
        context = SimpleNamespace(chat_data={"pending_urls": ["collection"],
                                             "pending_message_id": 20, "pending_needs_scope": True})
        with mock.patch.object(self.bot, "reject_unauthorized", new=mock.AsyncMock(return_value=False)), mock.patch.object(self.bot, "STORE") as store:
            await self.bot.choose_download(self.update(20), context)
        store.add_jobs.assert_not_called()

    async def test_new_links_reset_previous_playlist_choice(self):
        update = SimpleNamespace(effective_message=SimpleNamespace(
            text="https://youtube.com/watch?v=abc&list=collection",
            reply_text=mock.AsyncMock(return_value=SimpleNamespace(message_id=21))))
        context = SimpleNamespace(chat_data={"pending_playlist": True, "pending_message_id": 20})
        with mock.patch.object(self.bot, "reject_unauthorized", new=mock.AsyncMock(return_value=False)):
            await self.bot.receive_urls(update, context)
        self.assertFalse(context.chat_data["pending_playlist"])
        self.assertTrue(context.chat_data["pending_needs_scope"])
        self.assertEqual(context.chat_data["pending_message_id"], 21)
