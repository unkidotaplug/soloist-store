from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import Draft, NormalizedProduct, PriceResult, ProductCandidate


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    source_url TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    outcome TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source, external_id)
);
CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL UNIQUE REFERENCES products(id),
    title TEXT NOT NULL,
    post_html TEXT NOT NULL,
    media_json TEXT NOT NULL,
    price_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    delivered_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_drafts_status ON drafts(status, id DESC);
"""


class Database:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)

    def close(self) -> None:
        self.connection.close()

    def seen(self, candidate: ProductCandidate) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM products WHERE source=? AND external_id=?",
            (candidate.source, candidate.external_id),
        ).fetchone()
        return row is not None

    def mark_rejected(self, candidate: ProductCandidate, reason: str) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO products(source, external_id, source_url, raw_json, outcome, reason) "
                "VALUES(?, ?, ?, ?, 'rejected', ?)",
                (
                    candidate.source,
                    candidate.external_id,
                    candidate.source_url,
                    json.dumps(candidate.as_dict(), ensure_ascii=False),
                    reason,
                ),
            )

    def create_draft(
        self,
        candidate: ProductCandidate,
        product: NormalizedProduct,
        price: PriceResult,
        post_html: str,
    ) -> Draft | None:
        try:
            with self.connection:
                cursor = self.connection.execute(
                    "INSERT INTO products(source, external_id, source_url, raw_json, outcome, reason) "
                    "VALUES(?, ?, ?, ?, 'accepted', ?)",
                    (
                        candidate.source,
                        candidate.external_id,
                        candidate.source_url,
                        json.dumps(candidate.as_dict(), ensure_ascii=False),
                        product.reason,
                    ),
                )
                product_id = int(cursor.lastrowid)
                draft_cursor = self.connection.execute(
                    "INSERT INTO drafts(product_id, title, post_html, media_json, price_json) VALUES(?, ?, ?, ?, ?)",
                    (
                        product_id,
                        product.title,
                        post_html,
                        json.dumps(candidate.media, ensure_ascii=False),
                        json.dumps(price.as_dict(), ensure_ascii=False),
                    ),
                )
                draft_id = int(draft_cursor.lastrowid)
        except sqlite3.IntegrityError:
            return None
        return Draft(
            id=draft_id,
            source=candidate.source,
            external_id=candidate.external_id,
            source_url=candidate.source_url,
            title=product.title,
            post_html=post_html,
            media=candidate.media,
            price=price,
        )

    def get_draft(self, draft_id: int) -> Draft | None:
        row = self.connection.execute(
            "SELECT d.*, p.source, p.external_id, p.source_url FROM drafts d "
            "JOIN products p ON p.id=d.product_id WHERE d.id=?",
            (draft_id,),
        ).fetchone()
        return self._draft(row) if row else None

    def pending(self, limit: int = 20, undelivered_only: bool = False) -> list[Draft]:
        delivered_clause = "AND d.delivered_at IS NULL" if undelivered_only else ""
        rows = self.connection.execute(
            f"SELECT d.*, p.source, p.external_id, p.source_url FROM drafts d "
            f"JOIN products p ON p.id=d.product_id WHERE d.status='pending' {delivered_clause} "
            "ORDER BY d.id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._draft(row) for row in rows]

    def set_status(self, draft_id: int, status: str) -> bool:
        if status not in {"pending", "approved", "rejected"}:
            raise ValueError("Invalid draft status")
        with self.connection:
            cursor = self.connection.execute("UPDATE drafts SET status=? WHERE id=?", (status, draft_id))
        return cursor.rowcount > 0

    def mark_delivered(self, draft_id: int) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE drafts SET delivered_at=CURRENT_TIMESTAMP WHERE id=?",
                (draft_id,),
            )

    def update_media(self, draft_id: int, media: list[str]) -> None:
        if not media:
            return
        with self.connection:
            self.connection.execute(
                "UPDATE drafts SET media_json=? WHERE id=?",
                (json.dumps(media, ensure_ascii=False), draft_id),
            )

    def counts(self) -> dict[str, int]:
        rows = self.connection.execute(
            "SELECT status, COUNT(*) AS amount FROM drafts GROUP BY status"
        ).fetchall()
        result = {"pending": 0, "approved": 0, "rejected": 0}
        result.update({str(row["status"]): int(row["amount"]) for row in rows})
        return result

    @staticmethod
    def _draft(row: sqlite3.Row) -> Draft:
        price = PriceResult(**json.loads(row["price_json"]))
        return Draft(
            id=int(row["id"]),
            source=str(row["source"]),
            external_id=str(row["external_id"]),
            source_url=str(row["source_url"]),
            title=str(row["title"]),
            post_html=str(row["post_html"]),
            media=json.loads(row["media_json"]),
            price=price,
            status=str(row["status"]),
        )
