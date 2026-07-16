from __future__ import annotations

import re
from html import escape

from .models import NormalizedProduct, PriceResult
from .pricing import normalize_hashtag


CATEGORY_LABELS = {
    "tshirt": "Футболка",
    "longsleeve": "Лонгслив",
    "sweater": "Кофта",
    "jeans": "Джинсы",
    "shorts": "Шорты",
    "jacket": "Куртка",
    "shoes": "Обувь",
    "super_heavy_shoes": "Ботинки",
    "accessory": "Аксессуар",
    "other": "Одежда",
}

TITLE_HASHTAGS: tuple[tuple[str, str], ...] = (
    (r"^Футболка\b", "Футболка"),
    (r"^Лонгслив\b", "Лонгслив"),
    (r"^Худи\b", "Худи"),
    (r"^Зипхуди\b", "Зипхуди"),
    (r"^Кофта\b", "Кофта"),
    (r"^Свитер\b", "Свитер"),
    (r"^Кардиган\b", "Кофта"),
    (r"^Поло\b", "Поло"),
    (r"^Рубашка\b", "Рубашка"),
    (r"^Бомбер\b", "Бомбер"),
    (r"^Куртка\b", "Куртка"),
    (r"^Пальто\b", "Пальто"),
    (r"^Джинсы\b", "Джинсы"),
    (r"^(?:Штаны|Брюки)\b", "Штаны"),
    (r"^Шорты\b", "Шорты"),
    (r"^Ботинки\b", "Ботинки"),
    (r"^Кроссовки\b", "Кроссовки"),
    (r"^Обувь\b", "Обувь"),
    (r"^Кепка\b", "Кепка"),
    (r"^Шапка\b", "Шапка"),
    (r"^Шарф\b", "Шарф"),
    (r"^Перчатки\b", "Перчатки"),
    (r"^Сумка\b", "Сумка"),
    (r"^Кошел[её]к\b", "Кошелек"),
    (r"^(?:Цепь|Ожерелье)\b", "Цепь"),
    (r"^Браслет\b", "Браслет"),
    (r"^Очки\b", "Очки"),
)

# Exact spellings already used in @soloist_store. Keys are normalized and casefolded.
BRAND_HASHTAGS = {
    "rickowens": "RickOwens",
    "balenciaga": "Balenciaga",
    "enfantsrichesdeprimes": "ENFANTSRICHESDEPRIMES",
    "undercover": "Undercover",
    "ifsixwasnine": "IfSixWasNine",
    "lgb": "LGB",
    "numbernine": "NumberNine",
    "hystericglamour": "HystericGlamour",
    "chromehearts": "ChromeHearts",
    "14thaddiction": "14THADDICTION",
    "jadedlondon": "JadedLondon",
    "martinerose": "MartineRose",
    "maisonmargiela": "MaisonMargiela",
    "anndemeulemeester": "ANNDEMEULEMEESTER",
    "palyhollywood": "PALYHOLLYWOOD",
    "grailzproject": "GRAILZPROJECT",
    "rafsimons": "RafSimons",
    "saintlaurent": "SaintLaurent",
    "acnestudios": "AcneStudios",
    "viviennewestwood": "VivienneWestwood",
    "borisbidjansaberi": "BorisBidjan",
    "carlchristianpoell": "carlchristianpoell",
    "maisonmiharayasuhiro": "MaisonMihara",
    "thugclub": "ThugClub",
    "vetements": "Vetements",
}


def _category_hashtag(product: NormalizedProduct) -> str:
    for pattern, hashtag in TITLE_HASHTAGS:
        if re.search(pattern, product.title, flags=re.IGNORECASE):
            return hashtag
    return CATEGORY_LABELS.get(product.category, "Одежда")


def _brand_hashtag(brand: str) -> str:
    without_noise = re.sub(r"\b(?:ARCHIVE|TYPE)\b", "", brand, flags=re.IGNORECASE)
    normalized = normalize_hashtag(without_noise)
    folded = normalized.casefold()
    exact = BRAND_HASHTAGS.get(folded)
    if exact:
        return exact
    # Normalizers may occasionally include a model after the brand. Match the
    # longest known catalog key at the beginning and never leak that model into the tag.
    for key in sorted(BRAND_HASHTAGS, key=len, reverse=True):
        if folded.startswith(key):
            return BRAND_HASHTAGS[key]
    return normalized


def render_post(product: NormalizedProduct, price: PriceResult) -> str:
    title = escape(product.title)
    sizes = escape(product.sizes or "Уточняйте у менеджера")
    hashtags = [normalize_hashtag(_category_hashtag(product))]
    if product.brand:
        hashtags.append(_brand_hashtag(product.brand))
    tag_line = " ".join(f"#{tag}" for tag in hashtags if tag)
    return (
        f"<b>{title}</b>\n\n"
        f"Размеры: {sizes}\n\n"
        f"Цена: <b>{price.sale_price}₽</b> <s>{price.old_price}₽</s>\n\n"
        "<blockquote>Товар поставляется 1в1 к оригиналу, все бирки и гравировки присутствуют.\n\n"
        "Достанем почти любую вашу расцветку, узнавайте подробности у менеджера.\n\n"
        "Доставка до вашего города доступна любой почтой. Доп.фото и наличие уточняйте у менеджера.</blockquote>\n\n"
        '<b><a href="https://t.me/soloist_store/392">УСЛОВИЯ ЗАКАЗА</a> | '
        '<a href="https://t.me/soloist_chat">ЧАТ</a> | '
        '<a href="https://t.me/soloist_store/430">РЕФЕРАЛЬНАЯ СИСТЕМА</a> | '
        '<a href="https://t.me/+0rO9_6De0eE0YjIy">НАЛИЧИЕ</a> | '
        '<a href="https://t.me/otzivi_soloist">ОТЗЫВЫ</a></b>\n\n'
        '<b>По заказу писать <a href="https://t.me/USERSOLOIST">MANAGER</a></b>\n\n'
        f"{tag_line}"
    )
