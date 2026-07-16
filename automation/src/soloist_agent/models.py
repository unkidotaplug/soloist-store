from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any, Literal

SourceName = Literal["telegram", "taobao", "pdd"]
Currency = Literal["RUB", "CNY"]


@dataclass(slots=True)
class ProductCandidate:
    source: SourceName
    external_id: str
    source_url: str
    title: str
    price: Decimal
    currency: Currency
    description: str = ""
    brand: str = ""
    category: str = ""
    sizes: str = ""
    media: list[str] = field(default_factory=list)
    super_heavy: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["price"] = str(self.price)
        return value


@dataclass(slots=True)
class NormalizedProduct:
    accepted: bool
    title: str
    brand: str
    category: str
    sizes: str
    super_heavy: bool
    reason: str = ""


@dataclass(slots=True)
class PriceResult:
    sale_price: int
    old_price: int
    discount_percent: int
    delivery: int
    markup: int
    procurement_rub: int
    unrounded_total: int

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(slots=True)
class Draft:
    id: int
    source: str
    external_id: str
    source_url: str
    title: str
    post_html: str
    media: list[str]
    price: PriceResult
    status: str = "pending"
