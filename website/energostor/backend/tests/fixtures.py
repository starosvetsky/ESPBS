"""Synthetic parser batches for tests and local smoke runs.

The real payload shape (see ``espbs/storage.py`` in the parser) is reproduced
here: a ``batch`` table and a ``records`` table with ``payload`` JSON.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

SCHEMA = """
CREATE TABLE batch (
    id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
    state TEXT NOT NULL, archived_at TEXT, archive_sha256 TEXT
);
CREATE TABLE records (
    record_id TEXT PRIMARY KEY,
    source TEXT NOT NULL, external_id TEXT NOT NULL,
    payload TEXT NOT NULL, content_sha256 TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    UNIQUE(source, external_id)
);
"""


def make_batch(
    path: Path,
    records: list[dict],
    created_at: str = "2026-01-01T00:00:00+00:00",
) -> Path:
    """Create one batch file in the parser's format."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT INTO batch(id, created_at, state) VALUES (?,?,'SEALED')",
            (str(uuid.uuid4()), created_at),
        )
        for index, record in enumerate(records):
            payload = dict(record["payload"])
            record_id = record.get("record_id") or f"{path.stem}-{index:05d}"
            conn.execute(
                "INSERT INTO records(record_id, source, external_id, payload, content_sha256, collected_at) "
                "VALUES (?,?,?,?,?,?)",
                (
                    record_id,
                    payload.get("source", "test"),
                    record_id,
                    json.dumps(payload, ensure_ascii=False),
                    "0" * 64,
                    record.get("collected_at", "2026-01-01T00:00:00Z"),
                ),
            )
        conn.commit()
    finally:
        conn.close()
    return path


def product(
    name: str,
    *,
    brand: str = "",
    mpn: str = "",
    url: str = "",
    description: str = "",
    attributes: dict | None = None,
    images: list | None = None,
    documents: list | None = None,
    source: str = "test-host",
    category: str = "",
    extra: dict | None = None,
) -> dict:
    """A payload shaped like the parser's ``universal.Adapter.product``."""
    payload = {
        "source": source,
        "source_url": url,
        "external_id": url or name,
        "name": name,
        "manufacturer": brand,
        "mpn": mpn,
        "description": description,
        "attributes": attributes or {},
        "images": images or [],
        "documents": documents or [],
        "offer": {"price_text": "12 000 в‚Ѕ", "currency": "RUB", "availability": "РІ РЅР°Р»РёС‡РёРё"},
        "provenance": {"parser": "test", "html_sha256": "deadbeef", "batch": "secret-batch"},
        "enrichment": {"status": "MATCHED", "source_url": "https://olnisa.ru/x"},
    }
    if category:
        payload["category"] = category
    if extra:
        payload.update(extra)
    return payload

