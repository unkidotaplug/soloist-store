from __future__ import annotations

import hashlib
import html
import time
from decimal import Decimal, InvalidOperation
from typing import Any

from ..config import Settings
from ..http import request
from ..models import ProductCandidate


def _sign(params: dict[str, str], secret: str) -> str:
    payload = secret + "".join(f"{key}{params[key]}" for key in sorted(params)) + secret
    return hashlib.md5(payload.encode("utf-8")).hexdigest().upper()


class PddSource:
    """Pinduoduo Open Platform adapter using pdd.ddk.goods.search."""

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
            "type": "pdd.ddk.goods.search",
            "client_id": self.settings.pdd_client_id,
            "timestamp": str(int(time.time())),
            "data_type": "JSON",
            "version": "V1",
            "keyword": keyword,
            "pid": self.settings.pdd_pid,
            "page": "1",
            "page_size": "20",
            "sort_type": "0",
            "with_coupon": "false",
        }
        params["sign"] = _sign(params, self.settings.pdd_client_secret)
        response = await request(
            self.settings.pdd_api_url,
            method="POST",
            form=params,
            timeout=self.settings.request_timeout_seconds,
        )
        payload = response.json()
        if payload.get("error_response"):
            error = payload["error_response"]
            raise RuntimeError(f"PDD API: {error.get('error_msg') or error}")
        rows = payload.get("goods_search_response", {}).get("goods_list", [])
        candidates = [candidate for row in rows if (candidate := self._candidate(row)) is not None]
        for candidate in candidates:
            candidate.raw["search_keyword"] = keyword
        return candidates

    def _candidate(self, row: dict[str, Any]) -> ProductCandidate | None:
        goods_id = str(row.get("goods_id") or row.get("goods_sign") or "").strip()
        price_fen = row.get("min_group_price") or row.get("min_normal_price")
        try:
            price = Decimal(str(price_fen)) / Decimal("100")
        except (InvalidOperation, TypeError):
            return None
        if not goods_id or price <= 0:
            return None
        gallery = row.get("goods_gallery_urls") or []
        if isinstance(gallery, str):
            gallery = [gallery]
        media = [
            str(row.get("goods_image_url") or ""),
            str(row.get("goods_thumbnail_url") or ""),
            *(str(item) for item in gallery),
        ]
        media = list(dict.fromkeys(html.unescape(item) for item in media if item))[:10]
        source_url = str(row.get("goods_detail_url") or "")
        if not source_url and str(row.get("goods_id") or "").isdigit():
            source_url = f"https://mobile.yangkeduo.com/goods.html?goods_id={row['goods_id']}"
        return ProductCandidate(
            source="pdd",
            external_id=goods_id,
            source_url=source_url,
            title=html.unescape(str(row.get("goods_name") or row.get("goods_desc") or "Товар Pinduoduo")),
            price=price,
            currency="CNY",
            description=html.unescape(str(row.get("goods_desc") or "")),
            category=str(row.get("category_name") or row.get("cat_id") or ""),
            sizes="Уточняйте у менеджера",
            media=media,
            raw={"mall_name": row.get("mall_name"), "sales_tip": row.get("sales_tip")},
        )
