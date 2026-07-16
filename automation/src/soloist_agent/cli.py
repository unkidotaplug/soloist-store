from __future__ import annotations

import argparse
import asyncio
import json
import sys
from decimal import Decimal

from .config import Settings
from .database import Database
from .models import ProductCandidate
from .pipeline import ProductPipeline
from .pricing import calculate_price
from .sources.taobao_browser import TaobaoBrowserSource
from .telegram_bot import SoloistBot, TelegramAPI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="soloist-agent", description="SOLOIST product agent")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("run", help="start Telegram bot and scheduled scans")
    subparsers.add_parser("scan", help="scan sources once without sending to Telegram")
    subparsers.add_parser("doctor", help="check configuration")
    subparsers.add_parser("list", help="list pending drafts")
    subparsers.add_parser("taobao-login", help="open the dedicated Taobao login browser")
    taobao_scan = subparsers.add_parser("taobao-scan", help="scan only Taobao")
    taobao_scan.add_argument("--deliver", action="store_true", help="send new drafts to Telegram")
    preview = subparsers.add_parser("preview", help="print one draft")
    preview.add_argument("draft_id", type=int)
    price = subparsers.add_parser("price", help="test the pricing formula")
    price.add_argument("amount", type=Decimal, help="source price: CNY for marketplace, RUB for telegram")
    price.add_argument("category", help="tshirt, sweater, jeans, shoes, super_heavy_shoes…")
    price.add_argument("--source", choices=["marketplace", "telegram"], default="marketplace")
    return parser


async def scan_once(settings: Settings, database: Database) -> int:
    result = await ProductPipeline(settings, database).scan()
    print(
        json.dumps(
            {
                "fetched": result.fetched,
                "new_drafts": len(result.drafts),
                "skipped_seen": result.skipped_seen,
                "rejected": result.rejected,
                "errors": result.errors,
                "draft_ids": [draft.id for draft in result.drafts],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if result.errors and not result.drafts else 0


async def taobao_scan_once(settings: Settings, database: Database, deliver: bool) -> int:
    result = await ProductPipeline(settings, database).scan_taobao()
    if deliver and settings.telegram_bot_token and settings.telegram_admin_id:
        api = TelegramAPI(settings.telegram_bot_token)
        for draft in result.drafts:
            await api.send_draft(settings.telegram_admin_id, draft)
            database.mark_delivered(draft.id)
    print(
        json.dumps(
            {
                "fetched": result.fetched,
                "new_drafts": len(result.drafts),
                "skipped_seen": result.skipped_seen,
                "rejected": result.rejected,
                "errors": result.errors,
                "draft_ids": [draft.id for draft in result.drafts],
                "delivered": bool(deliver and result.drafts),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if result.errors and not result.drafts else 0


def doctor(settings: Settings) -> int:
    checks = {
        "telegram_token": bool(settings.telegram_bot_token),
        "telegram_admin_id": bool(settings.telegram_admin_id),
        "telegram_source": settings.telegram_source_channel,
        "openai_ai": settings.ai_enabled,
        "taobao_browser": settings.taobao_browser_enabled,
        "taobao_api": settings.taobao_api_enabled,
        "pdd_api": settings.pdd_enabled,
        "database": str(settings.database_path),
        "keywords": len(settings.keywords),
    }
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    if not settings.telegram_bot_token:
        print("Добавь новый TELEGRAM_BOT_TOKEN в .env.", file=sys.stderr)
    if not settings.telegram_admin_id:
        print("TELEGRAM_ADMIN_ID не задан: запусти бота и отправь /whoami.", file=sys.stderr)
    return 0


def main() -> None:
    args = build_parser().parse_args()
    settings = Settings.from_env()
    database = Database(settings.database_path)
    try:
        if args.command == "doctor":
            raise SystemExit(doctor(settings))
        if args.command == "scan":
            raise SystemExit(asyncio.run(scan_once(settings, database)))
        if args.command == "run":
            if not settings.telegram_bot_token:
                raise SystemExit("TELEGRAM_BOT_TOKEN is required")
            pipeline = ProductPipeline(settings, database)
            asyncio.run(SoloistBot(settings, database, pipeline).run())
            return
        if args.command == "taobao-login":
            authenticated = asyncio.run(TaobaoBrowserSource(settings).login())
            print(json.dumps({"authenticated": authenticated}, ensure_ascii=False))
            raise SystemExit(0 if authenticated else 2)
        if args.command == "taobao-scan":
            raise SystemExit(asyncio.run(taobao_scan_once(settings, database, args.deliver)))
        if args.command == "list":
            for draft in database.pending(limit=50):
                print(f"#{draft.id} [{draft.source}] {draft.price.sale_price} ₽ — {draft.title}")
            return
        if args.command == "preview":
            draft = database.get_draft(args.draft_id)
            if not draft:
                raise SystemExit("Draft not found")
            print(draft.post_html)
            print("\nMEDIA\n" + "\n".join(draft.media))
            return
        if args.command == "price":
            candidate = ProductCandidate(
                source="telegram" if args.source == "telegram" else "taobao",
                external_id="price-demo",
                source_url="",
                title=args.category,
                price=args.amount,
                currency="RUB" if args.source == "telegram" else "CNY",
                category=args.category,
                super_heavy=args.category == "super_heavy_shoes",
            )
            print(json.dumps(calculate_price(candidate, settings).as_dict(), ensure_ascii=False, indent=2))
    finally:
        database.close()


if __name__ == "__main__":
    main()
