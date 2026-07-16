from __future__ import annotations

import asyncio
import fcntl
import os
import re
import time
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote_plus, urlsplit

from ..config import Settings
from ..http import HttpError, request
from ..image_quality import ImageInspectionUnavailable, inspect_image_bytes
from ..models import ProductCandidate


LOGIN_URL = (
    "https://login.taobao.com/member/login.jhtml?redirectURL="
    "https%3A%2F%2Fs.taobao.com%2Fsearch%3Fq%3DRick%2BOwens"
)
SEARCH_URL = "https://s.taobao.com/search?q={keyword}"
CHROME_BINARY = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
CHROME_DEBUG_PORT = 9225
NON_PRODUCT_TERMS = (
    "素材",
    "图集",
    "图片包",
    "设计图",
    "图纸",
    "壁纸",
    "电子版",
    "电子资料",
    "教程",
    "参考图",
    "digital download",
    "reference image",
    "钥匙扣",
    "改色服务",
    "做旧服务",
    "正品专拍",
)
MODEL_TITLE_NOISE = (
    "rick owens",
    "balenciaga",
    "自主",
    "高街",
    "时尚",
    "百搭",
    "男女",
    "同款",
    "现货",
    "正品",
    "纯原",
    "复古",
    "做旧",
    "板鞋",
    "top-level",
    "top level",
)
MODEL_FEATURES = {
    "dunk": ("dunk",),
    "big_hook": ("大钩子",),
    "triangle": ("倒三角",),
    "high_top": ("高帮", "高筒"),
    "low_top": ("低帮",),
    "thick_sole": ("厚底",),
    "vibe": ("vibe", "元年"),
    "luxor": ("luxor",),
    "jumbo_lace": ("jumbo lace", "jumbolace", "粗鞋带"),
    "trailgrip": ("trailgrip",),
}


class TaobaoBrowserError(RuntimeError):
    pass


class TaobaoLoginRequired(TaobaoBrowserError):
    pass


class TaobaoVerificationRequired(TaobaoBrowserError):
    pass


class TaobaoBrowserBusy(TaobaoBrowserError):
    pass


@dataclass(slots=True)
class TaobaoBrowserStatus:
    authenticated: bool
    message: str
    products_visible: int = 0


EXTRACT_PRODUCTS = r"""
(limit) => {
  const productPattern = /(?:item\.taobao\.com\/item\.htm|detail\.tmall\.com\/item\.htm)/i;
  const candidates = [];
  const seen = new Set();

  const absoluteUrl = (value) => {
    if (!value) return "";
    if (value.startsWith("//")) return `https:${value}`;
    try { return new URL(value, location.href).href; } catch (_) { return value; }
  };

  const itemId = (href) => {
    try {
      const url = new URL(href, location.href);
      return url.searchParams.get("id") || url.searchParams.get("itemId") || "";
    } catch (_) {
      const match = String(href).match(/[?&](?:id|itemId)=(\d+)/i);
      return match ? match[1] : "";
    }
  };

  for (const anchor of document.querySelectorAll("a[href]")) {
    const href = absoluteUrl(anchor.getAttribute("href") || anchor.href || "");
    if (!productPattern.test(href)) continue;
    const id = itemId(href);
    if (!id || seen.has(id)) continue;

    let node = anchor;
    let card = anchor;
    for (let depth = 0; depth < 8 && node; depth += 1, node = node.parentElement) {
      const text = (node.innerText || "").trim();
      if (node.querySelector?.("img") && text.length >= 10) card = node;
      if (node.querySelector?.("img") && /[¥￥]\s*\d/.test(text)) {
        card = node;
        break;
      }
    }

    const text = (card.innerText || anchor.innerText || "").replace(/\s+/g, " ").trim();
    const priceMatch = text.match(/[¥￥]\s*(\d+(?:\.\d{1,2})?)/);
    if (!priceMatch) continue;

    const images = [];
    for (const image of card.querySelectorAll("img")) {
      const src = absoluteUrl(
        image.currentSrc || image.getAttribute("src") || image.getAttribute("data-src") ||
        image.getAttribute("data-ks-lazyload") || ""
      );
      if (src && /alicdn|tbcdn|taobaocdn/i.test(src) && !images.includes(src)) images.push(src);
    }

    const imageAlt = card.querySelector("img[alt]")?.getAttribute("alt") || "";
    const titled = anchor.getAttribute("title") || card.querySelector("[title]")?.getAttribute("title") || "";
    const lines = (card.innerText || "").split(/\n+/).map((line) => line.trim()).filter(Boolean);
    const lineTitle = lines
      .filter((line) => !/[¥￥]\s*\d/.test(line) && !/^(已售|付款|评价|广告)/.test(line))
      .sort((a, b) => b.length - a.length)[0] || "";
    const title = (titled || imageAlt || lineTitle || anchor.innerText || "Товар Taobao")
      .replace(/\s+/g, " ").trim();

    seen.add(id);
    candidates.push({
      external_id: id,
      source_url: href,
      title,
      price: priceMatch[1],
      media: images.slice(0, 10),
    });
    if (candidates.length >= limit) break;
  }
  return candidates;
}
"""


EXTRACT_DETAIL = r"""
() => {
  const absoluteUrl = (value) => {
    if (!value) return "";
    if (value.startsWith("//")) return `https:${value}`;
    try { return new URL(value, location.href).href; } catch (_) { return value; }
  };
  const media = [];
  for (const image of document.images) {
    const src = absoluteUrl(
      image.currentSrc || image.getAttribute("src") || image.getAttribute("data-src") ||
      image.getAttribute("data-ks-lazyload") || ""
    );
    const width = Number(image.naturalWidth || 0);
    const height = Number(image.naturalHeight || 0);
    const ratio = height ? width / height : 0;
    if (!src || !/alicdn|tbcdn|taobaocdn/i.test(src)) continue;
    if (width < 600 || height < 600 || ratio < 0.55 || ratio > 1.65) continue;
    if (/avatar|icon|logo|sprite/i.test(src)) continue;
    if (!media.includes(src)) media.push(src);
  }
  return {
    title: (document.querySelector("h1")?.innerText || document.title || "").replace(/\s+/g, " ").trim(),
    body: (document.body?.innerText || "").slice(0, 8000),
    media: media.slice(0, 30),
  };
}
"""


def _normalized_model_title(title: str) -> str:
    value = title.casefold()
    for term in MODEL_TITLE_NOISE:
        value = value.replace(term, "")
    return re.sub(r"[^a-z0-9\u3400-\u9fff]+", "", value)


def _model_features(title: str) -> set[str]:
    normalized = title.casefold()
    return {
        feature
        for feature, markers in MODEL_FEATURES.items()
        if any(marker in normalized for marker in markers)
    }


def _same_model(left: ProductCandidate, right: ProductCandidate) -> bool:
    if left.raw.get("search_keyword") != right.raw.get("search_keyword"):
        return False
    left_title = _normalized_model_title(left.title)
    right_title = _normalized_model_title(right.title)
    if not left_title or not right_title:
        return False
    if left_title == right_title:
        return True
    left_features = _model_features(left.title)
    right_features = _model_features(right.title)
    if ("high_top" in left_features and "low_top" in right_features) or (
        "low_top" in left_features and "high_top" in right_features
    ):
        return False
    shared_features = left_features & right_features
    if len(shared_features) >= 2 and shared_features & {"dunk", "big_hook", "triangle", "luxor"}:
        return True
    shorter, longer = sorted((left_title, right_title), key=len)
    if len(shorter) >= 16 and shorter in longer and len(shorter) / len(longer) >= 0.72:
        return True
    return SequenceMatcher(None, left_title, right_title).ratio() >= 0.82


def _group_same_models(candidates: list[ProductCandidate]) -> list[list[ProductCandidate]]:
    groups: list[list[ProductCandidate]] = []
    for candidate in candidates:
        for group in groups:
            if _same_model(candidate, group[0]):
                group.append(candidate)
                break
        else:
            groups.append([candidate])
    for group in groups:
        group.sort(key=lambda item: (item.price, item.external_id))
    return groups


@contextmanager
def _profile_lock(profile: Path) -> Iterator[None]:
    profile.parent.mkdir(parents=True, exist_ok=True)
    lock_path = profile.parent / f".{profile.name}.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise TaobaoBrowserBusy(
                "Профиль Taobao уже используется. Закрой окно авторизации или дождись текущего сканирования."
            ) from exc
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


class TaobaoBrowserSource:
    """Search Taobao through a dedicated, locally persisted Chrome profile."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.profile = settings.taobao_browser_profile

    async def fetch(self) -> list[ProductCandidate]:
        keywords = self._rotated_keywords()
        if not keywords:
            return []
        per_keyword = max(
            12,
            min(24, self.settings.source_page_limit // max(1, len(keywords)) + 1),
        )
        with _profile_lock(self.profile):
            playwright, browser, context = await self._launch_search(
                headless=self.settings.taobao_browser_headless
            )
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                products: list[ProductCandidate] = []
                for index, keyword in enumerate(keywords):
                    try:
                        rows = await self._search_rows(page, keyword, per_keyword)
                    except TaobaoVerificationRequired:
                        if not products:
                            raise
                        break
                    keyword_candidates = self._rows_to_candidates(rows, keyword)
                    products.extend(keyword_candidates)
                    if index == 0 and keyword_candidates:
                        refinement = self._refinement_query(keyword_candidates[0].title)
                        if refinement and refinement.casefold() != keyword.casefold():
                            await asyncio.sleep(max(3, self.settings.taobao_search_delay_seconds))
                            try:
                                refined_rows = await self._search_rows(page, refinement, per_keyword)
                            except TaobaoVerificationRequired:
                                refined_rows = []
                            products.extend(self._rows_to_candidates(refined_rows, keyword))
                    if len(products) >= self.settings.source_page_limit:
                        break
                    if index + 1 < len(keywords):
                        await asyncio.sleep(max(3, self.settings.taobao_search_delay_seconds))

                unique: dict[str, ProductCandidate] = {}
                for product in products:
                    unique.setdefault(product.external_id, product)
                selected = await self._select_best_listings(
                    page,
                    list(unique.values()),
                    self.settings.source_page_limit,
                )
            finally:
                await self._close_search(playwright, browser)
        return selected

    async def search(self, keyword: str, limit: int = 5) -> list[ProductCandidate]:
        with _profile_lock(self.profile):
            playwright, browser, context = await self._launch_search(
                headless=self.settings.taobao_browser_headless
            )
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                search_limit = max(16, min(30, limit * 4))
                rows = await self._search_rows(page, keyword, search_limit)
                candidates = self._rows_to_candidates(rows, keyword)
                if candidates:
                    refinement = self._refinement_query(candidates[0].title)
                    if refinement and refinement.casefold() != keyword.casefold():
                        await asyncio.sleep(max(3, self.settings.taobao_search_delay_seconds))
                        try:
                            refined_rows = await self._search_rows(page, refinement, search_limit)
                        except TaobaoVerificationRequired:
                            refined_rows = []
                        candidates.extend(self._rows_to_candidates(refined_rows, keyword))
                return await self._select_best_listings(page, candidates, limit)
            finally:
                await self._close_search(playwright, browser)

    async def status(self) -> TaobaoBrowserStatus:
        keyword = self.settings.keywords[0] if self.settings.keywords else "Rick Owens"
        try:
            with _profile_lock(self.profile):
                playwright, browser, context = await self._launch_search(
                    headless=self.settings.taobao_browser_headless
                )
                try:
                    page = context.pages[0] if context.pages else await context.new_page()
                    rows = await self._search_rows(page, keyword, 3)
                    products = self._rows_to_candidates(rows, keyword)
                finally:
                    await self._close_search(playwright, browser)
        except TaobaoLoginRequired:
            return TaobaoBrowserStatus(False, "Требуется вход в Taobao.")
        except TaobaoVerificationRequired:
            return TaobaoBrowserStatus(False, "Taobao просит пройти проверку или капчу.")
        return TaobaoBrowserStatus(
            True,
            "Сессия активна, поиск Taobao работает.",
            products_visible=len(products),
        )

    async def login(self) -> bool:
        with _profile_lock(self.profile):
            if not CHROME_BINARY.exists():
                raise TaobaoBrowserError("Google Chrome не найден в папке Applications.")
            process = await self._ensure_chrome(LOGIN_URL)
            if process is None:
                playwright = await self._playwright()
                try:
                    browser = await playwright.chromium.connect_over_cdp(
                        f"http://127.0.0.1:{CHROME_DEBUG_PORT}"
                    )
                    context = browser.contexts[0]
                    page = context.pages[0] if context.pages else await context.new_page()
                    await page.goto(LOGIN_URL, wait_until="domcontentloaded")
                finally:
                    await playwright.stop()
            return True

    async def _playwright(self) -> Any:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise TaobaoBrowserError(
                "Не установлен Playwright. Выполни: python3 -m pip install playwright"
            ) from exc

        self.profile.mkdir(parents=True, exist_ok=True)
        self.profile.chmod(0o700)
        return await async_playwright().start()

    async def _ensure_chrome(self, start_url: str) -> Any | None:
        endpoint = f"http://127.0.0.1:{CHROME_DEBUG_PORT}"
        try:
            await request(f"{endpoint}/json/version", timeout=1)
            return None
        except HttpError:
            pass

        arguments = [
            str(CHROME_BINARY),
            f"--user-data-dir={self.profile}",
            f"--remote-debugging-port={CHROME_DEBUG_PORT}",
            "--remote-debugging-address=127.0.0.1",
            "--no-first-run",
            "--no-default-browser-check",
            "--window-size=1440,1100",
            start_url,
        ]
        process = await asyncio.create_subprocess_exec(
            *arguments,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        for _ in range(30):
            try:
                await request(f"{endpoint}/json/version", timeout=1)
                return process
            except HttpError:
                if process.returncode is not None:
                    raise TaobaoBrowserError("Обычный Chrome с профилем Taobao не запустился.")
                await asyncio.sleep(0.5)
        process.terminate()
        with suppress(ProcessLookupError):
            await process.wait()
        raise TaobaoBrowserError("Chrome не открыл локальный канал для парсинга Taobao.")

    async def _launch_search(self, headless: bool) -> tuple[Any, Any, Any]:
        del headless  # Taobao rejects automated/headless login; the dedicated Chrome stays visible.
        await self._ensure_chrome("about:blank")
        endpoint = f"http://127.0.0.1:{CHROME_DEBUG_PORT}"
        playwright = await self._playwright()
        try:
            browser = await playwright.chromium.connect_over_cdp(endpoint)
            context = browser.contexts[0]
        except Exception:
            await playwright.stop()
            raise
        context.set_default_timeout(self.settings.taobao_browser_timeout_seconds * 1000)
        return playwright, browser, context

    @staticmethod
    async def _close_search(playwright: Any, browser: Any) -> None:
        del browser  # stopping the client disconnects without closing the dedicated Chrome.
        await playwright.stop()

    async def _search_rows(self, page: Any, keyword: str, limit: int) -> list[dict[str, Any]]:
        url = SEARCH_URL.format(keyword=quote_plus(keyword))
        try:
            await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self.settings.taobao_browser_timeout_seconds * 1000,
            )
        except Exception as exc:
            if "Timeout" not in type(exc).__name__:
                raise
        await page.wait_for_timeout(2500)

        if await self._verification_required(page):
            raise TaobaoVerificationRequired(
                "Taobao показал проверку. Выполни /taobao_login и пройди её в открывшемся окне."
            )
        if await self._login_required(page):
            raise TaobaoLoginRequired("Сессия Taobao не активна. Выполни /taobao_login.")

        for _ in range(2):
            await page.evaluate("window.scrollBy(0, Math.max(700, window.innerHeight * 0.8))")
            await page.wait_for_timeout(900)
        rows = await page.evaluate(EXTRACT_PRODUCTS, limit)
        if not isinstance(rows, list) or not rows:
            raise TaobaoBrowserError(
                "Taobao открылся, но карточки товаров не найдены. Возможно, площадка изменила страницу."
            )
        return [row for row in rows if isinstance(row, dict)]

    async def _login_required(self, page: Any) -> bool:
        url = str(page.url).lower()
        if "login.taobao.com" in url or "login.tmall.com" in url:
            return True
        body = await self._body_text(page)
        return "亲，请登录" in body or ("扫码登录" in body and "密码登录" in body)

    async def _verification_required(self, page: Any) -> bool:
        url = str(page.url).lower()
        if any(marker in url for marker in ("punish", "captcha", "sec.taobao.com")):
            return True
        body = await self._body_text(page)
        normalized = body.casefold()
        return any(
            marker in normalized
            for marker in (
                "拖动滑块",
                "访问被拒绝",
                "安全验证",
                "unusual traffic",
                "detected unusual traffic",
                "проведите вправо",
            )
        )

    @staticmethod
    async def _body_text(page: Any) -> str:
        try:
            return (await page.locator("body").inner_text(timeout=5000))[:12000]
        except Exception:
            return ""

    def _rows_to_candidates(
        self,
        rows: list[dict[str, Any]],
        keyword: str,
    ) -> list[ProductCandidate]:
        candidates: list[ProductCandidate] = []
        for row in rows:
            candidate = self._candidate(row, keyword)
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    async def _select_best_listings(
        self,
        search_page: Any,
        candidates: list[ProductCandidate],
        limit: int,
    ) -> list[ProductCandidate]:
        groups = _group_same_models(candidates)
        selected: list[ProductCandidate] = []
        checked = 0
        max_checks = max(1, self.settings.taobao_detail_candidates_per_scan)
        detail_page = await search_page.context.new_page()
        try:
            for group in groups:
                if len(selected) >= limit or checked >= max_checks:
                    break
                for candidate in group:
                    if checked >= max_checks:
                        break
                    checked += 1
                    enriched = await self._enrich_from_detail(detail_page, candidate)
                    if enriched is not None:
                        enriched.raw["compared_listing_prices_cny"] = [
                            str(item.price) for item in group
                        ]
                        enriched.raw["same_model_listings"] = len(group)
                        selected.append(enriched)
                        break
                    await asyncio.sleep(1.5)
        finally:
            await detail_page.close()
        return selected

    async def _enrich_from_detail(
        self,
        page: Any,
        candidate: ProductCandidate,
    ) -> ProductCandidate | None:
        try:
            await page.goto(
                candidate.source_url,
                wait_until="domcontentloaded",
                timeout=self.settings.taobao_browser_timeout_seconds * 1000,
            )
        except Exception as exc:
            if "Timeout" not in type(exc).__name__:
                return None
        await page.wait_for_timeout(2200)
        if await self._verification_required(page) or await self._login_required(page):
            return None
        for _ in range(4):
            await page.evaluate("window.scrollBy(0, Math.max(850, window.innerHeight * 0.9))")
            await page.wait_for_timeout(550)
        detail = await page.evaluate(EXTRACT_DETAIL)
        if not isinstance(detail, dict):
            return None
        gallery = self._detail_media(detail.get("media") or [], candidate.media)
        clean_media, rejection = await self._clean_media(gallery)
        if len(clean_media) < max(1, self.settings.taobao_min_clean_images):
            candidate.raw["image_rejection"] = rejection or "not_enough_clean_images"
            return None
        candidate.raw["search_cover"] = list(candidate.media)
        candidate.raw["detail_title"] = str(detail.get("title") or "")[:500]
        candidate.raw["clean_image_count"] = len(clean_media)
        candidate.media = clean_media[:8]
        return candidate

    @staticmethod
    def _detail_media(raw_media: list[Any], search_media: list[str]) -> list[str]:
        search_keys = {_media_key(url) for url in search_media}
        prepared = [str(raw_url or "").strip() for raw_url in raw_media]
        owner_counts: dict[str, int] = {}
        for url in prepared:
            owner_match = re.search(r"!!(\d{7,})", url)
            if owner_match and not owner_match.group(1).startswith("600000"):
                owner = owner_match.group(1)
                owner_counts[owner] = owner_counts.get(owner, 0) + 1
        dominant_owner = max(owner_counts, key=owner_counts.get) if owner_counts else ""
        media: list[str] = []
        seen: set[str] = set()
        for url in prepared:
            if url.startswith("//"):
                url = f"https:{url}"
            owner_match = re.search(r"!!(\d{7,})", url)
            if dominant_owner and (
                not owner_match or owner_match.group(1) != dominant_owner
            ):
                continue
            key = _media_key(url)
            if not url or not key or key in search_keys or key in seen:
                continue
            seen.add(key)
            media.append(url)
        return media[:12]

    async def _clean_media(self, gallery: list[str]) -> tuple[list[str], str]:
        clean: list[str] = []
        last_rejection = ""
        required = max(1, self.settings.taobao_min_clean_images)
        for url in gallery[:10]:
            try:
                response = await request(
                    url,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                            "AppleWebKit/537.36 Chrome/150 Safari/537.36"
                        ),
                        "Referer": "https://item.taobao.com/",
                    },
                    timeout=self.settings.request_timeout_seconds,
                )
                if len(response.body) > 18_000_000:
                    last_rejection = "image_too_large"
                    continue
                reason = await asyncio.to_thread(inspect_image_bytes, response.body)
            except (HttpError, ValueError, ImageInspectionUnavailable):
                last_rejection = "image_check_failed"
                continue
            if reason:
                last_rejection = reason
                if reason.startswith("watermark:"):
                    return [], reason
                continue
            clean.append(url)
            if len(clean) >= required:
                break
        return clean, last_rejection

    @staticmethod
    def _candidate(row: dict[str, Any], keyword: str) -> ProductCandidate | None:
        try:
            price = Decimal(str(row.get("price") or ""))
        except (InvalidOperation, TypeError):
            return None
        external_id = re.sub(r"\D", "", str(row.get("external_id") or ""))
        source_url = str(row.get("source_url") or "").strip()
        if not external_id or not source_url or price <= 0:
            return None
        media = []
        for raw_url in row.get("media") or []:
            url = str(raw_url or "").strip()
            if url.startswith("//"):
                url = f"https:{url}"
            if url and url not in media:
                media.append(url)
        title = re.sub(r"\s+", " ", str(row.get("title") or "Товар Taobao")).strip()
        if any(term in title.lower() for term in NON_PRODUCT_TERMS):
            return None
        return ProductCandidate(
            source="taobao",
            external_id=external_id,
            source_url=source_url,
            title=title,
            price=price,
            currency="CNY",
            category="",
            sizes="S-XXL",
            media=media[:10],
            raw={"search_keyword": keyword, "browser_profile": True},
        )

    def _rotated_keywords(self) -> list[str]:
        keywords = list(dict.fromkeys(self.settings.keywords))
        limit = max(1, min(len(keywords), self.settings.taobao_keywords_per_scan))
        if len(keywords) < 2:
            return keywords[:limit]
        rotation = int(time.time() // max(3600, self.settings.scan_interval_minutes * 60)) % len(keywords)
        rotated = keywords[rotation:] + keywords[:rotation]
        return rotated[:limit]

    @staticmethod
    def _refinement_query(title: str) -> str:
        value = re.sub(r"\s+", " ", title).strip()
        for term in ("自主", "牛皮", "高街", "时尚", "百搭", "男女同款", "现货", "正品"):
            value = value.replace(term, "")
        return re.sub(r"\s+", " ", value).strip()[:72]


def _media_key(url: str) -> str:
    if not url:
        return ""
    parsed = urlsplit(url)
    filename = parsed.path.rsplit("/", 1)[-1]
    filename = re.sub(r"\.(?:jpe?g|png|webp).*$", "", filename, flags=re.I)
    return filename.casefold()
