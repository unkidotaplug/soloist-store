from __future__ import annotations

import asyncio
import json
import mimetypes
import sys
import uuid
from contextlib import suppress
from html import escape
from typing import Any

from .config import Settings
from .cover import create_product_cover
from .database import Database
from .http import HttpError, request
from .models import Draft
from .pipeline import ProductPipeline, ScanResult
from .sources.taobao_browser import TaobaoBrowserSource
from .sources.telegram_channel import parse_channel_html


class TelegramAPIError(RuntimeError):
    pass


class TelegramAPI:
    def __init__(self, token: str) -> None:
        self.base_url = f"https://api.telegram.org/bot{token}"

    async def call(self, method: str, payload: dict[str, Any] | None = None) -> Any:
        body = payload or {}
        timeout = int(body.get("timeout", 0)) + 15
        response = await request(
            f"{self.base_url}/{method}",
            method="POST",
            json_body=body,
            timeout=max(30, timeout),
        )
        data = response.json()
        if not data.get("ok"):
            raise TelegramAPIError(str(data.get("description") or data))
        return data.get("result")

    async def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        parse_mode: str = "HTML",
    ) -> Any:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return await self.call("sendMessage", payload)

    async def call_multipart(
        self,
        method: str,
        fields: dict[str, Any],
        files: list[tuple[str, str, str, bytes]],
    ) -> Any:
        boundary = f"soloist-{uuid.uuid4().hex}"
        body = bytearray()
        for name, value in fields.items():
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
            body.extend(str(value).encode("utf-8"))
            body.extend(b"\r\n")
        for field_name, filename, content_type, content in files:
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(
                f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode()
            )
            body.extend(f"Content-Type: {content_type}\r\n\r\n".encode())
            body.extend(content)
            body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode())
        response = await request(
            f"{self.base_url}/{method}",
            method="POST",
            raw_body=bytes(body),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            timeout=90,
        )
        data = response.json()
        if not data.get("ok"):
            raise TelegramAPIError(str(data.get("description") or data))
        return data.get("result")

    @staticmethod
    def _file_ids(result: Any) -> list[str]:
        messages = result if isinstance(result, list) else [result]
        file_ids: list[str] = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            photos = message.get("photo") or []
            if isinstance(photos, list) and photos and isinstance(photos[-1], dict):
                file_id = str(photos[-1].get("file_id") or "")
                if file_id:
                    file_ids.append(file_id)
        return file_ids

    @staticmethod
    def _album_caption(post_html: str) -> str:
        title, separator, body = post_html.partition("\n\n")
        if separator and title.startswith("<b>") and title.endswith("</b>") and body:
            return body
        return post_html

    async def _send_media_references(self, chat_id: int, draft: Draft, media: list[str]) -> Any:
        caption = self._album_caption(draft.post_html)
        if len(media) == 1:
            return await self.call(
                "sendPhoto",
                {
                    "chat_id": chat_id,
                    "photo": media[0],
                    "caption": caption,
                    "parse_mode": "HTML",
                },
            )
        album = []
        for index, reference in enumerate(media):
            item: dict[str, Any] = {"type": "photo", "media": reference}
            if index == 0:
                item.update({"caption": caption, "parse_mode": "HTML"})
            album.append(item)
        return await self.call("sendMediaGroup", {"chat_id": chat_id, "media": album})

    async def _refresh_media(self, draft: Draft) -> list[str]:
        if draft.source != "telegram" or ":" not in draft.external_id:
            return []
        channel, message_id = draft.external_id.rsplit(":", 1)
        if not message_id.isdigit():
            return []
        response = await request(
            f"https://t.me/s/{channel}?before={int(message_id) + 1}",
            timeout=45,
        )
        for candidate in parse_channel_html(response.text(), channel, 30):
            if candidate.external_id == draft.external_id:
                return candidate.media[:10]
        return []

    async def send_draft(self, chat_id: int, draft: Draft) -> list[str]:
        media = draft.media[:10]
        if not media:
            await self.send_message(chat_id, draft.post_html)
            return []
        if all(not item.startswith(("http://", "https://")) for item in media):
            try:
                result = await self._send_media_references(chat_id, draft, media)
                return self._file_ids(result)
            except (TelegramAPIError, HttpError):
                refreshed = await self._refresh_media(draft)
                if not refreshed:
                    raise
                media = refreshed
        try:
            result = await self._upload_media(chat_id, draft, media)
            return self._file_ids(result)
        except (TelegramAPIError, HttpError):
            refreshed = await self._refresh_media(draft)
            if not refreshed or refreshed == media:
                raise
            result = await self._upload_media(chat_id, draft, refreshed)
            return self._file_ids(result)

    async def _upload_media(self, chat_id: int, draft: Draft, media: list[str]) -> Any:
        originals: list[tuple[str, str, str, bytes]] = []
        for index, url in enumerate(media[:9]):
            try:
                response = await request(url, timeout=45)
            except HttpError:
                continue
            content_type = response.headers.get("content-type", "image/jpeg").split(";", 1)[0]
            if not content_type.startswith("image/"):
                continue
            extension = mimetypes.guess_extension(content_type) or ".jpg"
            originals.append((f"photo{index}", f"photo{index}{extension}", content_type, response.body))
        if not originals:
            raise TelegramAPIError("No downloadable images")
        try:
            cover = create_product_cover(originals[0][3], draft.title)
        except Exception as exc:
            raise TelegramAPIError(f"Cover generation failed: {exc}") from exc
        files = [("cover", "soloist-cover.jpg", "image/jpeg", cover), *originals]
        caption = self._album_caption(draft.post_html)
        album: list[dict[str, str]] = []
        for index, (field_name, _, _, _) in enumerate(files):
            item = {"type": "photo", "media": f"attach://{field_name}"}
            if index == 0:
                item.update({"caption": caption, "parse_mode": "HTML"})
            album.append(item)
        return await self.call_multipart(
            "sendMediaGroup",
            {"chat_id": chat_id, "media": album},
            files,
        )


class SoloistBot:
    def __init__(self, settings: Settings, database: Database, pipeline: ProductPipeline) -> None:
        self.settings = settings
        self.database = database
        self.pipeline = pipeline
        self.offset = 0
        self.scan_lock = asyncio.Lock()
        self.taobao_login_task: asyncio.Task[None] | None = None

    async def run(self) -> None:
        api = TelegramAPI(self.settings.telegram_bot_token)
        scheduler = asyncio.create_task(self._scheduler(api))
        try:
            await self._poll(api)
        finally:
            scheduler.cancel()
            with suppress(asyncio.CancelledError):
                await scheduler

    async def _poll(self, api: TelegramAPI) -> None:
        while True:
            try:
                updates = await api.call(
                    "getUpdates",
                    {
                        "offset": self.offset,
                        "timeout": 25,
                        "allowed_updates": ["message", "callback_query"],
                    },
                )
                for update in updates:
                    self.offset = max(self.offset, int(update["update_id"]) + 1)
                    await self._handle_update(api, update)
            except (HttpError, asyncio.TimeoutError, TelegramAPIError):
                await asyncio.sleep(3)

    async def _scheduler(self, api: TelegramAPI) -> None:
        while True:
            await asyncio.sleep(max(60, self.settings.scan_interval_minutes * 60))
            if self.settings.telegram_admin_id:
                await self._deliver(api, self.database.pending(limit=20, undelivered_only=True))
                await self._scan_and_deliver(api, notify=False)

    async def _handle_update(self, api: TelegramAPI, update: dict[str, Any]) -> None:
        if "message" in update:
            await self._handle_message(api, update["message"])
        elif "callback_query" in update:
            await self._handle_callback(api, update["callback_query"])

    async def _handle_message(self, api: TelegramAPI, message: dict[str, Any]) -> None:
        chat_id = int(message.get("chat", {}).get("id", 0))
        user_id = int(message.get("from", {}).get("id", 0))
        text = str(message.get("text") or "").strip()
        command = text.split(maxsplit=1)[0].split("@", 1)[0].lower()

        if command in {"/start", "/whoami"}:
            if not self.settings.telegram_admin_id:
                await api.send_message(
                    chat_id,
                    f"Твой Telegram ID: <code>{user_id}</code>\n"
                    "Запиши его в <code>TELEGRAM_ADMIN_ID</code> и перезапусти агента.",
                )
            elif self._authorized(user_id):
                await api.send_message(chat_id, self._help_text())
            return
        if not self._authorized(user_id):
            return
        if command == "/help":
            await api.send_message(chat_id, self._help_text())
        elif command == "/scan":
            await api.send_message(chat_id, "Сканирую источники…")
            await self._scan_and_deliver(api, notify=True)
        elif command == "/queue":
            counts = self.database.counts()
            await api.send_message(
                chat_id,
                "Очередь:\n"
                f"Ожидают: <b>{counts['pending']}</b>\n"
                f"Готовы: <b>{counts['approved']}</b>\n"
                f"Пропущены: <b>{counts['rejected']}</b>",
            )
        elif command == "/pending":
            await self._deliver(api, self.database.pending(limit=10, undelivered_only=False))

    async def _handle_callback(self, api: TelegramAPI, query: dict[str, Any]) -> None:
        user_id = int(query.get("from", {}).get("id", 0))
        query_id = str(query.get("id") or "")
        if not self._authorized(user_id):
            await api.call("answerCallbackQuery", {"callback_query_id": query_id, "text": "Нет доступа"})
            return
        data = str(query.get("data") or "")
        action, _, raw_id = data.partition(":")
        if not raw_id.isdigit() or action not in {"approve", "reject"}:
            return
        draft_id = int(raw_id)
        status = "approved" if action == "approve" else "rejected"
        changed = self.database.set_status(draft_id, status)
        label = "Готово ✅" if status == "approved" else "Пропущено 🗑"
        await api.call(
            "answerCallbackQuery",
            {"callback_query_id": query_id, "text": label if changed else "Черновик не найден"},
        )
        message = query.get("message", {})
        if message.get("chat", {}).get("id") and message.get("message_id"):
            await api.call(
                "editMessageReplyMarkup",
                {
                    "chat_id": message["chat"]["id"],
                    "message_id": message["message_id"],
                    "reply_markup": {"inline_keyboard": []},
                },
            )

    async def _scan_and_deliver(self, api: TelegramAPI, notify: bool) -> ScanResult:
        if self.scan_lock.locked():
            if notify:
                await api.send_message(self.settings.telegram_admin_id, "Сканирование уже идет.")
            return ScanResult()
        async with self.scan_lock:
            result = await self.pipeline.scan()
            await self._deliver(api, result.drafts)
        if not notify:
            print(
                "scheduled scan: "
                f"fetched={result.fetched} drafts={len(result.drafts)} "
                f"seen={result.skipped_seen} rejected={result.rejected} "
                f"errors={len(result.errors)}",
                flush=True,
            )
        if notify:
            text = (
                f"Готово. Найдено: {result.fetched}; новых черновиков: {len(result.drafts)}; "
                f"дублей: {result.skipped_seen}; отсеяно: {result.rejected}."
            )
            if result.errors:
                text += "\nОшибки источников:\n" + "\n".join(result.errors)
            await api.send_message(self.settings.telegram_admin_id, text)
        return result

    async def _deliver(self, api: TelegramAPI, drafts: list[Draft]) -> None:
        if not self.settings.telegram_admin_id:
            return
        for draft in drafts:
            try:
                reusable_media = await api.send_draft(self.settings.telegram_admin_id, draft)
                if reusable_media:
                    self.database.update_media(draft.id, reusable_media)
                self.database.mark_delivered(draft.id)
            except (HttpError, TelegramAPIError) as exc:
                print(f"delivery failed for draft {draft.id}: {exc}", file=sys.stderr, flush=True)
                break

    async def _scan_taobao_and_deliver(self, api: TelegramAPI) -> None:
        if self.scan_lock.locked():
            await api.send_message(self.settings.telegram_admin_id, "Сканирование уже идет.")
            return
        async with self.scan_lock:
            result = await self.pipeline.scan_taobao()
            await self._deliver(api, result.drafts)
        text = (
            f"Taobao: найдено {result.fetched}; новых черновиков: {len(result.drafts)}; "
            f"дублей: {result.skipped_seen}; отсеяно: {result.rejected}."
        )
        if result.errors:
            text += "\nОшибки:\n" + "\n".join(result.errors)
        await api.send_message(self.settings.telegram_admin_id, text)

    async def _start_taobao_login(self, api: TelegramAPI, chat_id: int) -> None:
        if self.taobao_login_task and not self.taobao_login_task.done():
            await api.send_message(chat_id, "Окно авторизации Taobao уже открыто.")
            return
        await api.send_message(
            chat_id,
            "Открываю постоянное окно Google Chrome для Taobao. Войди в аккаунт и затем просто сверни окно — "
            "не закрывай его, пока нужен автоматический сбор.",
        )
        self.taobao_login_task = asyncio.create_task(self._run_taobao_login(api, chat_id))

    async def _run_taobao_login(self, api: TelegramAPI, chat_id: int) -> None:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "soloist_agent",
            "taobao-login",
            cwd=str(self.settings.project_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode == 0:
            await api.send_message(
                chat_id,
                "Окно Taobao открыто ✅\nВойди в аккаунт, не закрывай окно и отправь /taobao_test для проверки поиска.",
            )
            return
        detail = (stderr or stdout).decode("utf-8", errors="replace").strip()
        if detail:
            detail = f"\n<code>{escape(detail[-1200:])}</code>"
        await api.send_message(
            chat_id,
            "Окно Taobao не открылось. Запусти /taobao_login ещё раз."
            + detail,
        )

    async def _taobao_status(self, api: TelegramAPI, chat_id: int) -> None:
        await api.send_message(chat_id, "Проверяю сессию Taobao…")
        try:
            status = await TaobaoBrowserSource(self.settings).status()
        except Exception as exc:
            await api.send_message(chat_id, f"Taobao недоступен: {escape(str(exc))}")
            return
        suffix = f" Найдено карточек в тесте: {status.products_visible}." if status.authenticated else ""
        await api.send_message(chat_id, escape(status.message + suffix))

    async def _taobao_test(self, api: TelegramAPI, chat_id: int, keyword: str) -> None:
        keyword = keyword or (self.settings.keywords[0] if self.settings.keywords else "Rick Owens")
        await api.send_message(chat_id, f"Ищу в Taobao: <b>{escape(keyword)}</b>…")
        try:
            products = await TaobaoBrowserSource(self.settings).search(keyword, limit=5)
        except Exception as exc:
            await api.send_message(chat_id, f"Тест Taobao не прошёл: {escape(str(exc))}")
            return
        lines = [f"Taobao работает ✅ Найдено: <b>{len(products)}</b>"]
        for product in products:
            lines.append(
                f"\n• <b>{escape(product.title[:160])}</b>\n"
                f"{product.price} ¥ · <a href=\"{escape(product.source_url, quote=True)}\">открыть</a>"
            )
        await api.send_message(chat_id, "".join(lines))

    def _authorized(self, user_id: int) -> bool:
        return bool(self.settings.telegram_admin_id and user_id == self.settings.telegram_admin_id)

    @staticmethod
    def _help_text() -> str:
        return (
            "SOLOIST product agent\n\n"
            "/scan — проверить источники сейчас\n"
            "/queue — статистика очереди\n"
            "/pending — повторно прислать ожидающие посты\n"
            "/whoami — показать Telegram ID"
        )
