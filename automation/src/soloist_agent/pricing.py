from __future__ import annotations

import hashlib
import math
import random
import re
import unicodedata
from decimal import Decimal, ROUND_HALF_UP

from .config import Settings
from .models import PriceResult, ProductCandidate


CATEGORY_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("super_heavy_shoes", ("bulldozer", "бульдозер", "tractor boot", "platform boot", "超厚底")),
    ("tshirt", ("футболк", "t-shirt", "t shirt", "tee", "短袖", "半袖")),
    ("shoes", ("обув", "ботин", "кроссов", "сапог", "туфл", "лофер", "sneaker", "shoe", "boot", "鞋")),
    ("jeans", ("джинс", "брюк", "штан", "pants", "jeans", "denim", "牛仔裤", "长裤")),
    ("jacket", ("куртк", "бомбер", "пухов", "пальто", "jacket", "coat", "外套", "夹克")),
    ("sweater", ("кофт", "худи", "свит", "толстов", "hoodie", "sweater", "sweatshirt", "卫衣", "毛衣")),
    ("longsleeve", ("лонгслив", "longsleeve", "long sleeve", "长袖")),
    ("shorts", ("шорт", "shorts", "短裤")),
    ("accessory", ("сумк", "ремень", "цеп", "кольц", "очк", "bag", "belt", "chain", "ring", "配饰", "包")),
)


def infer_category(title: str, raw_category: str = "", super_heavy: bool = False) -> str:
    haystack = f"{title} {raw_category}".lower()
    if super_heavy:
        return "super_heavy_shoes"
    canonical = {category for category, _ in CATEGORY_ALIASES} | {"other"}
    normalized_raw = raw_category.strip().lower()
    if normalized_raw in canonical and normalized_raw != "other":
        return normalized_raw
    if re.search(r"\blong\b\s*$", title.strip(), flags=re.IGNORECASE):
        return "longsleeve"
    for category, aliases in CATEGORY_ALIASES:
        if any(alias in haystack for alias in aliases):
            return category
    return "other"


def retail_round_up(value: int | float | Decimal) -> int:
    """Round upward to a retail price ending in 490 or 990."""
    amount = int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if amount <= 490:
        return 490
    return 490 + 500 * math.ceil((amount - 490) / 500)


def _rng_for(candidate: ProductCandidate, namespace: str) -> random.Random:
    seed_material = f"{namespace}:{candidate.source}:{candidate.external_id}".encode("utf-8")
    seed = int.from_bytes(hashlib.sha256(seed_material).digest()[:8], "big")
    return random.Random(seed)


def _logistics(category: str, rng: random.Random) -> tuple[int, int]:
    if category == "tshirt":
        return rng.randrange(500, 601, 10), 1000
    if category == "longsleeve":
        return 800, 1300
    if category in {"sweater", "jeans"}:
        return 1000, 1600
    if category == "shorts":
        return 800, 1300
    if category == "jacket":
        return 1200, 2000
    if category == "shoes":
        return 1500, 2200
    if category == "super_heavy_shoes":
        return 2000, 2500
    if category == "accessory":
        return 500, 1000
    return 1000, 1500


def _competitor_discount(candidate: ProductCandidate, source_rub: int, settings: Settings) -> int:
    regular_discount = settings.competitor_cheaper_rub
    regular_price = source_rub - regular_discount
    if regular_price > settings.competitor_low_price_threshold_rub:
        return regular_discount
    low = min(settings.competitor_low_discount_min_rub, settings.competitor_low_discount_max_rub)
    high = max(settings.competitor_low_discount_min_rub, settings.competitor_low_discount_max_rub)
    if low == high:
        return low
    # Endpoints keep common competitor prices such as 3290 visually tidy: 3090 or 2990.
    return _rng_for(candidate, "competitor-discount").choice((low, high))


def _telegram_channel(candidate: ProductCandidate) -> str:
    raw_channel = str(candidate.raw.get("channel") or "").strip()
    if raw_channel:
        return raw_channel.lstrip("@").casefold()
    if ":" in candidate.external_id:
        return candidate.external_id.rsplit(":", 1)[0].strip().lstrip("@").casefold()
    return ""


def _old_price(candidate: ProductCandidate, sale_price: int, settings: Settings) -> tuple[int, int]:
    rng = _rng_for(candidate, "discount")
    target = rng.randint(settings.discount_min_percent, settings.discount_max_percent)
    for discount in range(target, settings.discount_min_percent - 1, -1):
        raw_old = Decimal(sale_price) / (Decimal("1") - Decimal(discount) / Decimal("100"))
        old_price = retail_round_up(raw_old)
        if old_price <= sale_price:
            old_price = retail_round_up(sale_price + 1)
        actual_discount = round((1 - sale_price / old_price) * 100)
        if settings.discount_min_percent <= actual_discount <= settings.discount_max_percent:
            return old_price, actual_discount
    old_price = retail_round_up(Decimal(sale_price) / Decimal("0.75"))
    return old_price, round((1 - sale_price / old_price) * 100)


def calculate_price(candidate: ProductCandidate, settings: Settings) -> PriceResult:
    category = infer_category(candidate.title, candidate.category, candidate.super_heavy)
    rng = _rng_for(candidate, "logistics")

    if candidate.source == "telegram":
        source_rub = int(candidate.price.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        if _telegram_channel(candidate) == "asphyxia_store":
            markup = settings.asphyxia_markup_rub
            unrounded = source_rub + markup
        else:
            competitor_discount = _competitor_discount(candidate, source_rub, settings)
            unrounded = max(1, source_rub - competitor_discount)
            markup = 0
        # Telegram shops already publish retail-rounded prices. Preserve the
        # exact channel-specific difference instead of rounding it away.
        sale_price = unrounded
        delivery = 0
        procurement = source_rub
    else:
        if candidate.currency != "CNY":
            raise ValueError(f"Marketplace price must be CNY, got {candidate.currency}")
        procurement_decimal = candidate.price * settings.yuan_rate * settings.procurement_multiplier
        procurement = int(procurement_decimal.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        delivery, markup = _logistics(category, rng)
        unrounded = procurement + delivery + markup
        sale_price = retail_round_up(unrounded)

    old_price, actual_discount = _old_price(candidate, sale_price, settings)
    return PriceResult(
        sale_price=sale_price,
        old_price=old_price,
        discount_percent=actual_discount,
        delivery=delivery,
        markup=markup,
        procurement_rub=procurement,
        unrounded_total=unrounded,
    )


def normalize_hashtag(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    clean = re.sub(r"[^0-9A-Za-zА-Яа-яЁё]+", "", plain)
    return clean[:64]
