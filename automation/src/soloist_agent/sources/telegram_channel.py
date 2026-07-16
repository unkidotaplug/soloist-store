from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from decimal import Decimal
from html.parser import HTMLParser
from urllib.parse import urljoin

from ..http import request
from ..models import ProductCandidate
from ..pricing import infer_category


PRICE_RE = re.compile(
    r"Цена\s*:?\s*([0-9][0-9 .]*)\s*₽\s*(?:([0-9][0-9 .]*)\s*₽?)?",
    re.IGNORECASE,
)
RUBLE_PRICE_RE = re.compile(
    r"(?<!\d)([0-9]{1,3}(?:[ .][0-9]{3})+|[0-9]{3,6})\s*₽",
    re.IGNORECASE,
)
SIZE_RE = re.compile(r"(?:Размеры?|Size)\s*:\s*([^\n]+)", re.IGNORECASE)
STYLE_URL_RE = re.compile(r"url\((?:['\"])?(.*?)(?:['\"])?\)", re.IGNORECASE)


def _money(value: str) -> int:
    return int(re.sub(r"\D", "", value))


def _clean_title(text: str) -> str:
    skip = (
        "все бирки",
        "размер",
        "цена",
        "сроки доставки",
        "отзывы",
        "условия заказа",
        "для заказа",
        "по всем вопросам",
    )
    for raw_line in text.splitlines():
        line = re.sub(r"^[^\wА-Яа-яЁё]+", "", raw_line).strip(" .:-—|#")
        if not line or len(line) < 3 or line.lower().startswith(skip):
            continue
        if re.search(r"[A-Za-zА-Яа-яЁё\u4e00-\u9fff]", line):
            return re.sub(r"\s+", " ", line)[:180]
    return "Товар"


def _normalize_media(media: list[str]) -> list[str]:
    result: list[str] = []
    for value in media:
        normalized = urljoin("https://t.me", value)
        if normalized not in result:
            result.append(normalized)
    return result[:10]


@dataclass(slots=True)
class _ParsedMessage:
    data_post: str
    text: list[str] = field(default_factory=list)
    media: list[str] = field(default_factory=list)
    source_url: str = ""


class _ChannelParser(HTMLParser):
    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.messages: list[_ParsedMessage] = []
        self.current: _ParsedMessage | None = None
        self.stack: list[tuple[str, bool, bool]] = []
        self.text_depth = 0

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = {key: value or "" for key, value in attrs_list}
        classes = set(attrs.get("class", "").split())
        is_root = False
        if self.current is None and attrs.get("data-post") and "tgme_widget_message" in classes:
            self.current = _ParsedMessage(attrs["data-post"])
            is_root = True
        enters_text = bool(self.current and "tgme_widget_message_text" in classes)
        if enters_text:
            self.text_depth += 1
        if self.current:
            style = attrs.get("style", "")
            is_media_node = bool(
                {"tgme_widget_message_photo_wrap", "tgme_widget_message_video_thumb"} & classes
            )
            if is_media_node:
                match = STYLE_URL_RE.search(style)
                if match:
                    self.current.media.append(html.unescape(match.group(1)))
            if tag == "video" and attrs.get("poster"):
                self.current.media.append(html.unescape(attrs["poster"]))
            if "tgme_widget_message_date" in classes and attrs.get("href"):
                self.current.source_url = attrs["href"]
            if tag == "br" and self.text_depth:
                self.current.text.append("\n")
        if tag not in self.VOID_TAGS:
            self.stack.append((tag, enters_text, is_root))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if not self.stack:
            return
        stack_tag, exits_text, is_root = self.stack.pop()
        if stack_tag != tag:
            return
        if exits_text:
            self.text_depth = max(0, self.text_depth - 1)
        if is_root and self.current:
            self.messages.append(self.current)
            self.current = None
            self.text_depth = 0

    def handle_data(self, data: str) -> None:
        if self.current and self.text_depth:
            self.current.text.append(data)


def parse_channel_html(document: str, channel: str, limit: int = 30) -> list[ProductCandidate]:
    parser = _ChannelParser()
    parser.feed(document)
    candidates: list[ProductCandidate] = []
    for message in parser.messages:
        data_post = message.data_post
        if not data_post or "/" not in data_post:
            continue
        text = re.sub(r"[ \t\r\f\v]+", " ", "".join(message.text))
        text = re.sub(r"\n\s*\n+", "\n", text).strip()
        price_match = PRICE_RE.search(text)
        if price_match is not None:
            price_values = [value for value in price_match.groups() if value]
        else:
            price_values = RUBLE_PRICE_RE.findall(text)
        prices = [_money(value) for value in price_values if _money(value) > 0]
        if not prices:
            continue
        sale_price = min(prices)
        sizes_match = SIZE_RE.search(text)
        sizes = sizes_match.group(1).strip(" .") if sizes_match else "Уточняйте у менеджера"
        title = _clean_title(text)
        message_id = data_post.rsplit("/", 1)[-1]
        external_id = f"{channel}:{message_id}"
        source_url = message.source_url or f"https://t.me/{channel}/{message_id}"
        candidates.append(
            ProductCandidate(
                source="telegram",
                external_id=external_id,
                source_url=str(source_url),
                title=title,
                price=Decimal(sale_price),
                currency="RUB",
                description=text,
                category=infer_category(title, text),
                sizes=sizes,
                media=_normalize_media(message.media),
                raw={"prices": prices, "channel": channel},
            )
        )

    def sort_key(item: ProductCandidate) -> tuple[int, str]:
        message_id = item.external_id.rsplit(":", 1)[-1]
        return (int(message_id) if message_id.isdigit() else 0, item.external_id)

    return sorted(candidates, key=sort_key, reverse=True)[:limit]


class TelegramChannelSource:
    def __init__(self, channel: str, timeout_seconds: int = 30, limit: int = 30) -> None:
        self.channel = channel.lstrip("@")
        self.timeout_seconds = timeout_seconds
        self.limit = limit

    async def fetch(self) -> list[ProductCandidate]:
        url = f"https://t.me/s/{self.channel}"
        response = await request(url, timeout=self.timeout_seconds)
        document = response.text()
        return parse_channel_html(document, self.channel, self.limit)
