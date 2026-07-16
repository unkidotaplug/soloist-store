from __future__ import annotations

from dataclasses import dataclass, field

from .ai import ProductNormalizer
from .config import Settings
from .database import Database
from .models import Draft, ProductCandidate
from .posts import render_post
from .pricing import calculate_price
from .sources import PddSource, TaobaoBrowserSource, TaobaoSource, TelegramChannelSource


@dataclass(slots=True)
class ScanResult:
    drafts: list[Draft] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    fetched: int = 0
    skipped_seen: int = 0
    rejected: int = 0


def _round_robin(batches: list[list[ProductCandidate]]) -> list[ProductCandidate]:
    result: list[ProductCandidate] = []
    for index in range(max((len(batch) for batch in batches), default=0)):
        for batch in batches:
            if index < len(batch):
                result.append(batch[index])
    return result


class ProductPipeline:
    def __init__(self, settings: Settings, database: Database) -> None:
        self.settings = settings
        self.database = database
        self.normalizer = ProductNormalizer(settings)

    async def scan(self) -> ScanResult:
        result = ScanResult()
        source_candidates = await self._fetch_sources(result)
        await self._create_drafts(source_candidates, result)
        return result

    async def scan_taobao(self) -> ScanResult:
        result = ScanResult()
        try:
            candidates = await TaobaoBrowserSource(self.settings).fetch()
            result.fetched = len(candidates)
        except Exception as exc:
            result.errors.append(f"Taobao browser: {exc}")
            return result
        await self._create_drafts(candidates, result)
        return result

    async def _create_drafts(
        self,
        source_candidates: list[ProductCandidate],
        result: ScanResult,
    ) -> None:
        for candidate in source_candidates:
            if len(result.drafts) >= self.settings.max_new_drafts_per_scan:
                break
            if self.database.seen(candidate):
                result.skipped_seen += 1
                continue
            normalized = await self.normalizer.normalize(candidate)
            if not normalized.accepted:
                self.database.mark_rejected(candidate, normalized.reason)
                result.rejected += 1
                continue
            candidate.category = normalized.category
            candidate.super_heavy = normalized.super_heavy
            price = calculate_price(candidate, self.settings)
            post_html = render_post(normalized, price)
            draft = self.database.create_draft(candidate, normalized, price, post_html)
            if draft is not None:
                result.drafts.append(draft)

    async def _fetch_sources(
        self,
        result: ScanResult,
    ) -> list[ProductCandidate]:
        sources: list[tuple[str, object]] = [
            (
                f"Telegram @{channel}",
                TelegramChannelSource(
                    channel,
                    self.settings.request_timeout_seconds,
                    self.settings.source_page_limit,
                ),
            )
            for channel in self.settings.telegram_source_channels
        ]
        if self.settings.taobao_browser_enabled:
            sources.append(("Taobao browser", TaobaoBrowserSource(self.settings)))
        elif self.settings.taobao_api_enabled:
            sources.append(("Taobao", TaobaoSource(self.settings)))
        if self.settings.pdd_enabled:
            sources.append(("Pinduoduo", PddSource(self.settings)))

        candidate_batches: list[list[ProductCandidate]] = []
        for label, source in sources:
            try:
                candidates = await source.fetch()  # type: ignore[attr-defined]
                result.fetched += len(candidates)
                candidate_batches.append(candidates)
            except Exception as exc:  # one broken source must not stop the queue
                result.errors.append(f"{label}: {exc}")
        return _round_robin(candidate_batches)
