from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from ..config import Settings
from ..http import request
from ..models import ProductCandidate


def _sign(params: dict[str, str], secret: str) -> str:
    payload = secret + "".join(f"{key}{params[key]}" for key in sorted(params)) + secret
    return hashlib.md5(payload.encode("utf-8")).hexdigest().upper()


def _url(value: str) -> str:
    value = html.unescape(value or "")
    return f"https:{value}" if value.startswith("//") else value


def _plain(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html.unescape(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def _small_images(raw: Any) -> list[str]:
    if isinstance(raw, dict):
        raw = raw.get("string", [])
    if isinstance(raw, str):
        raw = [raw]
    return [_url(str(item)) for item in raw or [] if item]


class TaobaoSource:
    """Taobao Alliance/Open Platform adapter using tbk.dg.material.optional."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def fetch(self) -> list[ProductCandidate]:
        products: list[ProductCandidate] = []
        for keyword in self.settings.keywords:
            products.extend(await self._search(keyword))
            if len(products) >= self.settings.source_page_limit:
                break
        unique: dict[str, ProductCandidate] = {}
        for product in products:
            unique.setdefault(product.external_id, product)
        return list(unique.values())[: self.settings.source_page_limit]

    async def _search(self, keyword: str) -> list[ProductCandidate]:
        params = {
            "method": "taobao.tbk.dg.material.optional",
            "app_key": self.settings.taobao_app_key,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "format": "json",
            "v": "2.0",
            "sign_method": "md5",
            "q": keyword,
            "adzone_id": self.settings.taobao_adzone_id,
            "page_no": "1",
            "page_size": "20",
            "platform": "2",
        }
        if self.settings.taobao_session:
            params["session"] = self.settings.taobao_session
        params["sign"] = _sign(params, self.settings.taobao_app_secret)
        response = await request(
            self.settings.taobao_api_url,
            method="POST",
            form=params,
            timeout=self.settings.request_timeout_seconds,
        )
        payload = response.json()
        if payload.get("error_response"):
            error = payload["error_response"]
            raise RuntimeError(f"Taobao API: {error.get('sub_msg') or error.get('msg') or error}")
        rows = (
            payload.get("tbk_dg_material_optional_response", {})
            .get("result_list", {})
            .get("map_data", [])
        )
        candidates = [candidate for row in rows if (candidate := self._candidate(row)) is not None]
        for candidate in candidates:
            candidate.raw["search_keyword"] = keyword
        return candidates

    def _candidate(self, row: dict[str, Any]) -> ProductCandidate | None:
        price_value = row.get("zk_final_price") or row.get("reserve_price")
        try:
            price = Decimal(str(price_value))
        except (InvalidOperation, TypeError):
            return None
        external_id = str(row.get("num_iid") or row.get("item_id") or "").strip()
        if not external_id or price <= 0:
            return None
        media = [_url(str(row.get("pict_url") or "")), *_small_images(row.get("small_images"))]
        media = list(dict.fromkeys(item for item in media if item))[:10]
        source_url = _url(str(row.get("item_url") or row.get("click_url") or ""))
        if not source_url:
            source_url = f"https://item.taobao.com/item.htm?id={external_id}"
        return ProductCandidate(
            source="taobao",
            external_id=external_id,
            source_url=source_url,
            title=_plain(str(row.get("title") or row.get("short_title") or "Товар Taobao")),
            price=price,
            currency="CNY",
            category=str(row.get("category_name") or row.get("level_one_category_name") or ""),
            sizes="Уточняйте у менеджера",
            media=media,
            raw={"volume": row.get("volume"), "seller_id": row.get("seller_id")},
        )
