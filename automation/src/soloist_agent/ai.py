from __future__ import annotations

import json
import re
import unicodedata

from .config import Settings
from .http import HttpError, request
from .models import NormalizedProduct, ProductCandidate
from .pricing import infer_category


RUSSIAN_TYPE_LABELS = {
    "tshirt": "Футболка",
    "longsleeve": "Лонгслив",
    "sweater": "Кофта",
    "jeans": "Джинсы",
    "shorts": "Шорты",
    "jacket": "Куртка",
    "shoes": "Обувь",
    "super_heavy_shoes": "Ботинки",
    "accessory": "Аксессуар",
}

ENGLISH_TYPE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bT[- ]?SHIRTS?\b|\bTEES?\b", "Футболка"),
    (r"\bLONG[- ]?SLEEVES?\b|\bLONG\b(?=\s*$)", "Лонгслив"),
    (r"\bHOODIES?\b", "Худи"),
    (r"\bSWEATSHIRTS?\b", "Кофта"),
    (r"\bSWEATERS?\b", "Свитер"),
    (r"\bCARDIGANS?\b", "Кардиган"),
    (r"\bPOLOS?\b", "Поло"),
    (r"\bSHIRTS?\b", "Рубашка"),
    (r"\bBOMBERS?\b", "Бомбер"),
    (r"\bJACKETS?\b", "Куртка"),
    (r"\bCOATS?\b", "Пальто"),
    (r"\bJEANS?\b|\bDENIMS?\b", "Джинсы"),
    (r"\bPANTS?\b|\bTROUSERS?\b", "Штаны"),
    (r"\bSHORTS?\b", "Шорты"),
    (r"\bVESTS?\b", "Жилет"),
    (r"\bSKIRTS?\b", "Юбка"),
    (r"\bDRESSES?\b", "Платье"),
    (r"\bBOOTS?\b", "Ботинки"),
    (r"\bSNEAKERS?\b", "Кроссовки"),
    (r"\bSHOES?\b", "Обувь"),
    (r"\bCAPS?\b", "Кепка"),
    (r"\bBEANIES?\b", "Шапка"),
    (r"\bHATS?\b", "Головной убор"),
    (r"\bBAGS?\b", "Сумка"),
    (r"\bWALLETS?\b", "Кошелёк"),
    (r"\bCHAINS?\b", "Цепь"),
    (r"\bNECKLACES?\b", "Ожерелье"),
    (r"\bBRACELETS?\b", "Браслет"),
    (r"\bSUNGLASSES?\b|\bGLASSES\b", "Очки"),
    (r"\bSCARVES?\b", "Шарф"),
    (r"\bGLOVES?\b", "Перчатки"),
)

ENGLISH_DESCRIPTOR_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b(\d+)\s+POCKETS?\b", r"с \1 карманами"),
    (r"\bFAUX[- ]?LEATHER\b", "из экокожи"),
    (r"\bLEATHER\b", "из кожи"),
    (r"\bDISTRESSED\b", "с потёртостями"),
    (r"\bOVERSIZED\b", "оверсайз"),
    (r"\bEMBROIDERED\b", "с вышивкой"),
    (r"\bPRINTED\b", "с принтом"),
    (r"\bCOTTON\b", "из хлопка"),
    (r"\bWOOL(?:LEN)?\b", "из шерсти"),
    (r"\bZIP(?:-?UP)?\b", "на молнии"),
)

BRAND_STOPWORDS = {"ARCHIVE", "TYPE"}
BRAND_ALIASES: tuple[tuple[str, str], ...] = (
    (r"\bERD\b", "ENFANTS RICHES DEPRIMES"),
)


def standardized_sizes(category: str) -> str:
    if category in {"shoes", "super_heavy_shoes"}:
        return "36-45"
    if category == "accessory":
        return "Уточняйте у менеджера"
    return "S-XXL"


def _fold_token(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(char for char in decomposed if not unicodedata.combining(char)).upper()


def _known_brand(title: str, keywords: list[str]) -> str:
    original_tokens = re.findall(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ]+", title)
    folded_tokens = [_fold_token(token) for token in original_tokens]
    for keyword in keywords:
        keyword_tokens = [_fold_token(token) for token in re.findall(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ]+", keyword)]
        if not keyword_tokens:
            continue
        width = len(keyword_tokens)
        for index in range(len(folded_tokens) - width + 1):
            if folded_tokens[index : index + width] == keyword_tokens:
                return " ".join(original_tokens[index : index + width])
    compact_title = "".join(folded_tokens)
    for keyword in keywords:
        compact_keyword = "".join(
            _fold_token(token) for token in re.findall(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ]+", keyword)
        )
        if compact_keyword and compact_keyword in compact_title:
            return keyword
    return ""


def sanitize_brand(value: str) -> str:
    tokens = re.findall(r"[0-9A-Za-zÀ-ÖØ-öø-ÿА-Яа-яЁё]+", value)
    clean = [token for token in tokens if _fold_token(token) not in BRAND_STOPWORDS]
    return " ".join(clean).strip()


def derive_brand(title: str, category: str, keywords: list[str]) -> str:
    for pattern, brand in BRAND_ALIASES:
        if re.search(pattern, title, flags=re.IGNORECASE):
            return brand
    known = _known_brand(title, keywords)
    if known:
        return sanitize_brand(known)
    remainder = localize_product_title(title, category)
    labels = tuple(RUSSIAN_TYPE_LABELS.values()) + tuple(
        dict.fromkeys(label for _, label in ENGLISH_TYPE_PATTERNS)
    )
    for label in labels:
        remainder = re.sub(rf"^{re.escape(label)}\s+", "", remainder, flags=re.IGNORECASE)
    return sanitize_brand(remainder)


def _translate_descriptors(value: str) -> str:
    translated = value
    for pattern, replacement in ENGLISH_DESCRIPTOR_PATTERNS:
        translated = re.sub(pattern, replacement, translated, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", translated).strip(" .,:;|—-")


def localize_product_title(title: str, category: str) -> str:
    """Translate product types/descriptors while preserving brand and model names."""
    normalized = re.sub(r"\s+", " ", title).strip(" .,:;|—-")
    russian_labels = tuple(RUSSIAN_TYPE_LABELS.values()) + tuple(
        dict.fromkeys(label for _, label in ENGLISH_TYPE_PATTERNS)
    )
    if normalized.lower().startswith(tuple(label.lower() for label in russian_labels)):
        return _translate_descriptors(normalized)
    for pattern, label in ENGLISH_TYPE_PATTERNS:
        if re.search(pattern, normalized, flags=re.IGNORECASE):
            remainder = re.sub(pattern, " ", normalized, flags=re.IGNORECASE)
            remainder = _translate_descriptors(remainder)
            return f"{label} {remainder}".strip()
    normalized = _translate_descriptors(normalized)
    label = RUSSIAN_TYPE_LABELS.get(category)
    if label and re.search(r"[A-Za-z]", normalized) and not re.search(r"[А-Яа-яЁё]", normalized):
        return f"{label} {normalized}"
    return normalized


def _clean_json(text: str) -> dict:
    value = text.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s*```$", "", value)
    return json.loads(value)


def _response_text(payload: dict) -> str:
    pieces: list[str] = []
    for item in payload.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                pieces.append(content["text"])
    return "\n".join(pieces)


def _boolean(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.strip().lower() in {"true", "yes", "1"}:
            return True
        if value.strip().lower() in {"false", "no", "0"}:
            return False
    return default


class ProductNormalizer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def normalize(
        self,
        candidate: ProductCandidate,
    ) -> NormalizedProduct:
        fallback = self.heuristic(candidate)
        if not self.settings.ai_enabled:
            return fallback
        try:
            return await self._with_ai(candidate, fallback)
        except (HttpError, TimeoutError, ValueError, KeyError, json.JSONDecodeError):
            return fallback

    def heuristic(self, candidate: ProductCandidate) -> NormalizedProduct:
        category = infer_category(candidate.title, candidate.category, candidate.super_heavy)
        brand = derive_brand(candidate.title, category, self.settings.keywords)
        searched_for = str(candidate.raw.get("search_keyword") or "")
        if candidate.source in {"taobao", "pdd"} and searched_for:
            brand = sanitize_brand(searched_for) or brand
        accepted = candidate.source == "telegram" or bool(brand or searched_for)
        title = re.sub(r"\s+", " ", candidate.title).strip(" .")[:180] or "Товар"
        title = localize_product_title(title, category)
        if candidate.source in {"taobao", "pdd"} and searched_for and re.search(r"[\u3400-\u9fff]", title):
            label = RUSSIAN_TYPE_LABELS.get(category, "Товар")
            title = f"{label} {sanitize_brand(searched_for)}".strip()
        return NormalizedProduct(
            accepted=accepted,
            title=title,
            brand=brand,
            category=category,
            sizes=standardized_sizes(category),
            super_heavy=category == "super_heavy_shoes" or candidate.super_heavy,
            reason="rule-based fallback",
        )

    async def _with_ai(
        self,
        candidate: ProductCandidate,
        fallback: NormalizedProduct,
    ) -> NormalizedProduct:
        product_json = json.dumps(candidate.as_dict(), ensure_ascii=False)
        theme = ", ".join(self.settings.keywords)
        instructions = (
            "Ты товарный редактор магазина дизайнерской dark/archive fashion одежды SOLOIST. "
            "Оцени релевантность товара, переведи и сократи название на русский, выдели бренд и категорию. "
            "Не выдумывай размеры, материалы, модель или бренд. Если размеров нет, верни "
            "'Уточняйте у менеджера'. super_heavy=true только для действительно очень тяжелой массивной обуви "
            "уровня Balenciaga Bulldozer. Верни только один JSON-объект без markdown: "
            '{"accepted":true,"title":"...","brand":"...","category":"tshirt|longsleeve|sweater|jeans|shorts|jacket|shoes|super_heavy_shoes|accessory|other",'
            '"sizes":"...","super_heavy":false,"reason":"..."}.'
        )
        body = {
            "model": self.settings.openai_model,
            "instructions": instructions,
            "input": f"Тематика/бренды: {theme}\nКарточка товара: {product_json}",
            "max_output_tokens": 600,
            "store": False,
        }
        headers = {
            "Authorization": f"Bearer {self.settings.openai_api_key}",
            "Content-Type": "application/json",
        }
        response = await request(
            f"{self.settings.openai_base_url}/responses",
            method="POST",
            json_body=body,
            headers=headers,
            timeout=self.settings.request_timeout_seconds + 30,
        )
        payload = response.json()
        data = _clean_json(_response_text(payload))
        category = str(data.get("category") or fallback.category)
        allowed = {
            "tshirt", "longsleeve", "sweater", "jeans", "shorts", "jacket",
            "shoes", "super_heavy_shoes", "accessory", "other",
        }
        if category not in allowed:
            category = fallback.category
        title = localize_product_title(str(data.get("title") or fallback.title).strip()[:180], category)
        ai_brand = sanitize_brand(str(data.get("brand") or ""))
        return NormalizedProduct(
            accepted=_boolean(data.get("accepted"), fallback.accepted),
            title=title,
            brand=(ai_brand or fallback.brand)[:100],
            category=category,
            sizes=standardized_sizes(category),
            super_heavy=_boolean(data.get("super_heavy"), fallback.super_heavy),
            reason=str(data.get("reason") or "AI")[:300],
        )
