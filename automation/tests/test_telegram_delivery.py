import unittest

from soloist_agent.models import Draft, PriceResult
from soloist_agent.telegram_bot import TelegramAPI, TelegramAPIError


class RecordingTelegramAPI(TelegramAPI):
    def __init__(self) -> None:
        super().__init__("test-token")
        self.calls: list[tuple[str, dict]] = []

    async def call(self, method: str, payload: dict | None = None):
        self.calls.append((method, payload or {}))
        return {"message_id": 1}


class RefreshingTelegramAPI(RecordingTelegramAPI):
    def __init__(self) -> None:
        super().__init__()
        self.refreshed = False

    async def call(self, method: str, payload: dict | None = None):
        body = payload or {}
        self.calls.append((method, body))
        if not self.refreshed:
            raise TelegramAPIError("failed to get HTTP URL content")
        return [
            {"photo": [{"file_id": "small"}, {"file_id": "permanent-file-id"}]}
        ]

    async def _refresh_media(self, draft: Draft) -> list[str]:
        self.refreshed = True
        return ["https://fresh.example/one.jpg", "https://fresh.example/two.jpg"]


class BrokenTelegramAPI(RecordingTelegramAPI):
    async def call(self, method: str, payload: dict | None = None):
        self.calls.append((method, payload or {}))
        raise TelegramAPIError("broken media")

    async def _refresh_media(self, draft: Draft) -> list[str]:
        return []

    async def _upload_media(self, chat_id: int, draft: Draft, media: list[str]):
        raise TelegramAPIError("upload failed")


class TelegramDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_draft_has_no_internal_breakdown_or_number(self) -> None:
        api = RecordingTelegramAPI()
        draft = Draft(
            id=42,
            source="telegram",
            external_id="ikarushop:4993",
            source_url="https://t.me/ikarushop/4993",
            title="Худи PALY HOLLYWOOD",
            post_html="<b>Худи PALY HOLLYWOOD</b>",
            media=["https://cdn.example/photo.jpg"],
            price=PriceResult(4490, 8990, 50, 0, 0, 4400, 4400),
        )

        await api.send_draft(123, draft)

        self.assertEqual([method for method, _ in api.calls], ["sendPhoto"])
        self.assertEqual(api.calls[0][1]["caption"], "<b>Худи PALY HOLLYWOOD</b>")
        self.assertTrue(api.calls[0][1]["show_caption_above_media"])
        self.assertNotIn("Черновик", str(api.calls))
        self.assertNotIn("#42", str(api.calls))

    async def test_title_is_above_original_media_and_old_body_follows_it(self) -> None:
        api = RecordingTelegramAPI()
        draft = Draft(
            id=43,
            source="telegram",
            external_id="ikarushop:4994",
            source_url="https://t.me/ikarushop/4994",
            title="Куртка Rick Owens",
            post_html=(
                "<b>Куртка Rick Owens</b>\n\n"
                "Размеры: S-XXL\n\nЦена: <b>4490₽</b> <s>7990₽</s>\n\n"
                "<blockquote>Описание</blockquote>"
            ),
            media=["https://cdn.example/original.jpg"],
            price=PriceResult(4490, 7990, 44, 0, 0, 4990, 4490),
        )

        await api.send_draft(123, draft)

        self.assertEqual([method for method, _ in api.calls], ["sendPhoto", "sendMessage"])
        self.assertEqual(api.calls[0][1]["photo"], "https://cdn.example/original.jpg")
        self.assertEqual(api.calls[0][1]["caption"], "<b>Куртка Rick Owens</b>")
        self.assertTrue(api.calls[0][1]["show_caption_above_media"])
        self.assertTrue(api.calls[1][1]["text"].startswith("Размеры: S-XXL"))
        self.assertNotIn("Куртка Rick Owens", api.calls[1][1]["text"])

    async def test_expired_urls_are_refreshed_and_file_ids_are_returned(self) -> None:
        api = RefreshingTelegramAPI()
        draft = Draft(
            id=8,
            source="telegram",
            external_id="ikarushop:5006",
            source_url="https://t.me/ikarushop/5006",
            title="Кофта Undercover",
            post_html="<b>Кофта Undercover</b>",
            media=["https://expired.example/photo.jpg"],
            price=PriceResult(4490, 7990, 44, 0, 0, 4990, 4490),
        )

        file_ids = await api.send_draft(123, draft)

        self.assertEqual(file_ids, ["permanent-file-id"])
        self.assertEqual(api.calls[-1][0], "sendMediaGroup")
        self.assertTrue(
            all(item["show_caption_above_media"] for item in api.calls[-1][1]["media"])
        )
        self.assertNotIn("Фото:", str(api.calls))

    async def test_total_media_failure_never_sends_raw_urls_as_text(self) -> None:
        api = BrokenTelegramAPI()
        draft = Draft(
            id=8,
            source="telegram",
            external_id="ikarushop:5006",
            source_url="https://t.me/ikarushop/5006",
            title="Кофта Undercover",
            post_html="<b>Кофта Undercover</b>",
            media=["https://expired.example/photo.jpg"],
            price=PriceResult(4490, 7990, 44, 0, 0, 4990, 4490),
        )

        with self.assertRaises(TelegramAPIError):
            await api.send_draft(123, draft)

        self.assertNotIn("sendMessage", [method for method, _ in api.calls])
        self.assertNotIn("Фото:", str(api.calls))


if __name__ == "__main__":
    unittest.main()
