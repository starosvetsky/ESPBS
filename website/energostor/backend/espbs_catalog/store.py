"""Derived catalog database: schema, streaming build and statistics.

The builder never writes to the parser's data.  It opens every batch
``mode=ro``, streams ``records`` row by row, and writes a brand-new SQLite
file next to the destination.  The destination is replaced with
``os.replace`` only when the whole build succeeded.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from . import taxonomy as tx
from .data import known_paths
from .textproc import (
    NAME_LIMIT,
    build_search_text,
    category_path_from_url,
    clean_attributes,
    clean_description,
    clean_documents,
    clean_images,
    dedupe_key,
    normalize_brand,
    normalize_mpn,
    plain_text,
    product_id_for_key,
    product_id_for_record,
    short_summary,
    slugify,
)

SCHEMA_VERSION = 3
BUILDER_VERSION = "1.0"

SCHEMA = """
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE parents (
    slug     TEXT PRIMARY KEY,
    title    TEXT NOT NULL,
    position INTEGER NOT NULL,
    products INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE children (
    slug     TEXT PRIMARY KEY,
    parent   TEXT NOT NULL,
    title    TEXT NOT NULL,
    position INTEGER NOT NULL,
    products INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE brands (
    slug     TEXT PRIMARY KEY,
    title    TEXT NOT NULL,
    products INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE products (
    id           TEXT PRIMARY KEY,
    dedupe_key   TEXT UNIQUE,
    brand        TEXT NOT NULL DEFAULT '',
    brand_slug   TEXT NOT NULL DEFAULT '',
    mpn          TEXT NOT NULL DEFAULT '',
    name         TEXT NOT NULL,
    parent       TEXT NOT NULL,
    child        TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    summary      TEXT NOT NULL DEFAULT '',
    attributes   TEXT NOT NULL DEFAULT '[]',
    images       TEXT NOT NULL DEFAULT '[]',
    documents    TEXT NOT NULL DEFAULT '[]',
    search       TEXT NOT NULL DEFAULT '',
    collected_ts REAL NOT NULL DEFAULT 0,
    collected_at TEXT NOT NULL DEFAULT '',
    has_images   INTEGER NOT NULL DEFAULT 0,
    has_docs     INTEGER NOT NULL DEFAULT 0,
    has_attrs    INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX products_brand  ON products(brand_slug);
CREATE INDEX products_child  ON products(child);
CREATE INDEX products_parent ON products(parent);
CREATE INDEX products_name   ON products(name COLLATE NOCASE);

-- Internal traceability.  Never selected by the public API.
CREATE TABLE audit_records (
    record_id    TEXT PRIMARY KEY,
    product_id   TEXT NOT NULL,
    source       TEXT NOT NULL DEFAULT '',
    collected_at TEXT NOT NULL DEFAULT '',
    outcome      TEXT NOT NULL
);

CREATE TABLE audit_batches (
    name       TEXT PRIMARY KEY,
    records    INTEGER NOT NULL,
    source     TEXT NOT NULL DEFAULT ''
);

CREATE INDEX audit_records_product ON audit_records(product_id);
"""

COLUMNS = (
    "id, dedupe_key, brand, brand_slug, mpn, name, parent, child, "
    "description, summary, attributes, images, documents, search, "
    "collected_ts, collected_at, has_images, has_docs, has_attrs"
)

UPSERT = f"""
INSERT INTO products ({COLUMNS}) VALUES ({",".join("?" * 19)})
ON CONFLICT(dedupe_key) DO UPDATE SET
    id=excluded.id, brand=excluded.brand, brand_slug=excluded.brand_slug,
    mpn=excluded.mpn, name=excluded.name, parent=excluded.parent,
    child=excluded.child, description=excluded.description,
    summary=excluded.summary, attributes=excluded.attributes,
    images=excluded.images, documents=excluded.documents, search=excluded.search,
    collected_ts=excluded.collected_ts, collected_at=excluded.collected_at,
    has_images=excluded.has_images, has_docs=excluded.has_docs,
    has_attrs=excluded.has_attrs
WHERE excluded.collected_ts > products.collected_ts
"""


@dataclass
class BuildStats:
    raw_records: int = 0
    inserted: int = 0
    updated: int = 0
    duplicates: int = 0
    skipped: int = 0
    batches: int = 0
    first_collected: str = ""
    last_collected: str = ""
    per_batch: dict[str, int] = field(default_factory=dict)

    @property
    def unique_products(self) -> int:
        return self.inserted


class BuildError(RuntimeError):
    """Raised when the source data cannot be turned into a catalog."""


# --------------------------------------------------------------------------
# Source access (read-only)
# --------------------------------------------------------------------------

def batch_files(source: Path) -> list[Path]:
    source = Path(source)
    if source.is_file():
        return [source]
    batches = source / "batches"
    if batches.is_dir():
        files = sorted(batches.glob("*.sqlite3"), key=_batch_order_key)
        if not files:
            raise BuildError(f"В {batches} нет файлов *.sqlite3")
        return files
    files = sorted(source.glob("*.sqlite3"), key=_batch_order_key)
    if not files:
        raise BuildError(f"В каталоге нет файлов *.sqlite3: {source}")
    return files


def _batch_order_key(path: Path) -> tuple[str, str]:
    """Oldest batch first; on equal timestamps the newest snapshot still wins."""
    created = ""
    try:
        conn = _connect_ro(path)
        try:
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='batch'"
            ).fetchone():
                row = conn.execute("SELECT created_at FROM batch LIMIT 1").fetchone()
                created = str(row[0]) if row and row[0] else ""
        finally:
            conn.close()
    except sqlite3.Error:
        created = ""
    return (created, path.name)


def _connect_ro(path: Path) -> sqlite3.Connection:
    uri = path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def iter_records(path: Path) -> Iterator[tuple[str, str, str]]:
    """Stream ``(record_id, payload, collected_at)`` without loading the batch."""
    conn = _connect_ro(path)
    try:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='records'"
        ).fetchone():
            raise BuildError(f"Нет таблицы records: {Path(path).name}")
        cursor = conn.execute("SELECT record_id, payload, collected_at FROM records")
        for row in cursor:
            yield row[0], row[1], row[2]
    finally:
        conn.close()


# --------------------------------------------------------------------------
# Row construction
# --------------------------------------------------------------------------

def parse_timestamp(value) -> tuple[float, str]:
    """ISO-8601 from the parser -> (epoch seconds, normalised ISO)."""
    if not isinstance(value, str) or not value:
        return 0.0, ""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return 0.0, ""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc)
    return moment.timestamp(), moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_row(payload: dict, collected_at: str, known: frozenset[str]) -> dict:
    """Project a raw payload onto the public row.  Never raises."""
    name = plain_text(payload.get("name"), NAME_LIMIT)
    brand = normalize_brand(payload.get("manufacturer") or payload.get("brand") or "")
    mpn = normalize_mpn(payload.get("mpn") or "")
    article = mpn or normalize_mpn(payload.get("article") or payload.get("sku") or "")
    description = clean_description(payload.get("description"))
    attributes = clean_attributes(payload.get("attributes"))
    images = clean_images(payload.get("images"))
    documents = clean_documents(payload.get("documents"))
    collected_ts, collected_iso = parse_timestamp(collected_at)

    path = ""
    category = payload.get("category")
    if isinstance(category, str) and category.strip():
        path = category.strip().strip("/").lower()
    if path not in known:
        path = category_path_from_url(payload.get("source_url", ""), known)

    child = None
    if path:
        candidate = tx.classify_path(path)
        # A path that is neither an audited category nor recognised by the
        # keyword rules says nothing about the product: fall through to the
        # brand/model rules instead of dumping it into "Прочее".
        if candidate and (candidate != tx.FALLBACK_CHILD or path in known):
            child = candidate
    if child is None:
        child, _reason = tx.classify_unbranded(brand, name, article, description)
    rubric = tx.rubric_for(child)

    key = dedupe_key(brand, mpn) if mpn else None

    return {
        "id": product_id_for_key(key) if key else None,
        "dedupe_key": key,
        "brand": brand,
        "brand_slug": slugify(brand) if brand else "",
        "mpn": article,
        "name": name,
        "parent": rubric.parent,
        "child": rubric.child,
        "description": description,
        "summary": short_summary(description),
        "attributes": attributes,
        "images": images,
        "documents": documents,
        "search": build_search_text(name, brand, article, description[:600]),
        "collected_ts": collected_ts,
        "collected_at": collected_iso,
        "has_images": 1 if images else 0,
        "has_docs": 1 if documents else 0,
        "has_attrs": 1 if attributes else 0,
    }


def _row_tuple(row: dict) -> tuple:
    return (
        row["id"], row["dedupe_key"], row["brand"], row["brand_slug"], row["mpn"],
        row["name"], row["parent"], row["child"], row["description"], row["summary"],
        json.dumps(row["attributes"], ensure_ascii=False),
        json.dumps(row["images"], ensure_ascii=False),
        json.dumps(row["documents"], ensure_ascii=False),
        row["search"], row["collected_ts"], row["collected_at"],
        row["has_images"], row["has_docs"], row["has_attrs"],
    )


# --------------------------------------------------------------------------
# Schema and build
# --------------------------------------------------------------------------

def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.executemany(
        "INSERT INTO parents(slug, title, position) VALUES (?,?,?)",
        [(slug, title, index) for index, (slug, title) in enumerate(tx.PARENTS)],
    )
    conn.executemany(
        "INSERT INTO children(slug, parent, title, position) VALUES (?,?,?,?)",
        [(slug, parent, title, index) for index, (slug, parent, title) in enumerate(tx.CHILDREN)],
    )
    conn.commit()


def build(
    source: Path,
    destination: Path,
    *,
    limit: int | None = None,
    max_bytes: int | None = None,
    log=None,
) -> BuildStats:
    """Build the derived database atomically.

    On any error the temporary file is removed and the destination is left
    exactly as it was.
    """
    source = Path(source)
    destination = Path(destination)
    if not source.exists():
        raise BuildError(f"Источник не найден: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)

    files = batch_files(source)
    if destination.resolve() in {p.resolve() for p in files}:
        raise BuildError("Destination must not overwrite a source batch")
    known = known_paths()
    tx.load_known_paths(known)

    temp = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    if temp.exists():
        temp.unlink()

    stats = BuildStats()
    started = time.time()
    conn = sqlite3.connect(temp)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=MEMORY")
        conn.execute("PRAGMA synchronous=OFF")
        create_schema(conn)
        conn.execute("BEGIN")

        for batch in files:
            count = 0
            for record_id, payload_text, collected_at in iter_records(batch):
                if limit is not None and stats.raw_records >= limit:
                    break
                stats.raw_records += 1
                count += 1
                if stats.raw_records % 2000 == 0:
                    _disk_guard(temp, max_bytes)
                    if log:
                        log(f"  обработано {stats.raw_records}")

                payload = _parse_payload(payload_text)
                if payload is None or not plain_text(payload.get("name")):
                    stats.skipped += 1
                    conn.execute(
                        "INSERT OR REPLACE INTO audit_records VALUES (?,?,?,?,?)",
                        (record_id, "", "", collected_at or "", "skipped"),
                    )
                    continue

                row = build_row(payload, collected_at, known)
                if not row["id"]:
                    row["id"] = product_id_for_record(record_id)

                outcome = _upsert(conn, row)
                if outcome == "inserted":
                    stats.inserted += 1
                elif outcome == "updated":
                    stats.updated += 1
                else:
                    stats.duplicates += 1

                conn.execute(
                    "INSERT OR REPLACE INTO audit_records VALUES (?,?,?,?,?)",
                    (
                        record_id,
                        row["id"],
                        plain_text(str(payload.get("source", "")), 100),
                        row["collected_at"],
                        outcome,
                    ),
                )
                if row["collected_at"]:
                    if not stats.first_collected or row["collected_at"] < stats.first_collected:
                        stats.first_collected = row["collected_at"]
                    if row["collected_at"] > stats.last_collected:
                        stats.last_collected = row["collected_at"]
            stats.batches += 1
            stats.per_batch[batch.name] = count
            conn.execute(
                "INSERT OR REPLACE INTO audit_batches VALUES (?,?,?)",
                (batch.name, count, ""),
            )
            if limit is not None and stats.raw_records >= limit:
                break

        _finalize(conn, stats, started)
        conn.commit()
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.close()

        _disk_guard(temp, max_bytes)
        try:
            with temp.open("r+b") as durable:
                os.fsync(durable.fileno())
            os.replace(temp, destination)
        except OSError as error:
            raise BuildError(
                f'Не удалось заменить {destination}: {error}. '
                'Если файл держит запущенный сервис (Windows), остановите его и повторите.'
            ) from error
        return stats
    except BaseException:
        try:
            conn.close()
        except sqlite3.Error:
            pass
        if temp.exists():
            try:
                temp.unlink()
            except OSError:
                pass
        raise


def _parse_payload(text) -> dict | None:
    if isinstance(text, (bytes, bytearray)):
        text = text.decode("utf-8", "replace")
    if not isinstance(text, str):
        return None
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


_MERGE_FIELDS = ("description", "attributes", "images", "documents")


def _upsert(conn: sqlite3.Connection, row: dict) -> str:
    # Repeated exact record IDs can safely merge even without MPN.
    if row['dedupe_key']:
        existing = conn.execute('SELECT * FROM products WHERE dedupe_key=?', (row['dedupe_key'],)).fetchone()
    else:
        existing = conn.execute('SELECT * FROM products WHERE id=?', (row['id'],)).fetchone()
    if existing is None:
        conn.execute(f"INSERT INTO products ({COLUMNS}) VALUES ({','.join('?' * 19)})", _row_tuple(row))
        return 'inserted'
    previous = dict(existing)
    for field in ('attributes', 'images', 'documents'):
        previous[field] = json.loads(previous[field])
    newer = row['collected_ts'] > previous['collected_ts']
    winner, other = (dict(row), previous) if newer else (previous, row)
    enriched = False
    for field in _MERGE_FIELDS:
        if not winner[field] and other[field]:
            winner[field] = other[field]
            enriched = True
    if not newer and not enriched:
        return 'duplicate'
    winner['summary'] = short_summary(winner['description'])
    winner['search'] = build_search_text(winner['name'], winner['brand'], winner['mpn'], winner['description'][:600])
    winner['has_images'] = int(bool(winner['images']))
    winner['has_docs'] = int(bool(winner['documents']))
    winner['has_attrs'] = int(bool(winner['attributes']))
    names = [c.strip() for c in COLUMNS.split(',')]
    conn.execute('UPDATE products SET ' + ','.join(c + '=?' for c in names) + ' WHERE id=?', _row_tuple(winner) + (existing['id'],))
    return 'updated'


def _disk_guard(temp: Path, max_bytes: int | None) -> None:
    if not max_bytes:
        return
    size = temp.stat().st_size if temp.exists() else 0
    if size > max_bytes:
        raise BuildError(f"Производная БД превысила лимит {max_bytes // (1024 * 1024)} МБ")


def _finalize(conn: sqlite3.Connection, stats: BuildStats, started: float) -> None:
    conn.execute(
        "UPDATE children SET products="
        "(SELECT COUNT(*) FROM products p WHERE p.child=children.slug)"
    )
    conn.execute(
        "UPDATE parents SET products="
        "(SELECT COUNT(*) FROM products p WHERE p.parent=parents.slug)"
    )
    conn.execute(
        "INSERT INTO brands(slug, title, products) "
        "SELECT brand_slug, brand, COUNT(*) FROM products "
        "WHERE brand_slug<>'' GROUP BY brand_slug"
    )

    total = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    stats.duplicates = stats.raw_records - stats.skipped - total
    with_images = conn.execute("SELECT COUNT(*) FROM products WHERE has_images=1").fetchone()[0]
    with_docs = conn.execute("SELECT COUNT(*) FROM products WHERE has_docs=1").fetchone()[0]
    with_attrs = conn.execute("SELECT COUNT(*) FROM products WHERE has_attrs=1").fetchone()[0]

    meta = {
        "schema_version": str(SCHEMA_VERSION),
        "builder_version": BUILDER_VERSION,
        "taxonomy_size": f"{len(tx.PARENTS)}/{len(tx.CHILDREN)}",
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "build_seconds": f"{time.time() - started:.1f}",
        "raw_records": str(stats.raw_records),
        "unique_products": str(total),
        "duplicates": str(stats.raw_records - stats.skipped - total),
        "skipped": str(stats.skipped),
        "batches": str(stats.batches),
        "products_with_images": str(with_images),
        "products_with_docs": str(with_docs),
        "products_with_attrs": str(with_attrs),
        "first_collected": stats.first_collected,
        "last_collected": stats.last_collected,
    }
    conn.executemany("INSERT INTO meta(key, value) VALUES (?,?)", meta.items())
    conn.execute("PRAGMA user_version=%d" % SCHEMA_VERSION)
    conn.execute("ANALYZE")
