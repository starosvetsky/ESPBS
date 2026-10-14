"""One durable SQLite file per collection batch; no network or GUI dependencies."""

import hashlib
import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def validate_text(value):
    """Reject characters that cannot be represented in XML 1.0 before committing."""
    for char in value:
        point = ord(char)
        if not (point in (9, 10, 13) or 0x20 <= point <= 0xD7FF
                or 0xE000 <= point <= 0xFFFD or 0x10000 <= point <= 0x10FFFF):
            raise ValueError("Record contains a character forbidden in XML 1.0")


def validate_value(value):
    if isinstance(value, str):
        validate_text(value)
    elif isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("Object keys must be strings")
            validate_text(key)
            validate_value(item)
    elif isinstance(value, list):
        for item in value:
            validate_value(item)
    elif value is not None and not isinstance(value, (bool, int, float)):
        raise ValueError("Only JSON-compatible values are supported")


class Batch:
    def __init__(self, root, batch_id):
        self.id = str(UUID(batch_id))
        self.path = Path(root) / "batches" / (self.id + ".sqlite3")
        if not self.path.is_file():
            raise FileNotFoundError(f"Batch not found: {self.id}")

    @classmethod
    def create(cls, root):
        batch_id = str(uuid4())
        directory = Path(root) / "batches"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (batch_id + ".sqlite3")
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            db.executescript("""
                CREATE TABLE batch (
                    id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('OPEN','SEALED','ARCHIVED')),
                    archived_at TEXT, archive_sha256 TEXT
                );
                CREATE TABLE records (
                    record_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL, external_id TEXT NOT NULL,
                    payload TEXT NOT NULL, content_sha256 TEXT NOT NULL,
                    collected_at TEXT NOT NULL,
                    UNIQUE(source, external_id)
                );
                PRAGMA user_version=1;
            """)
            db.execute("INSERT INTO batch(id,created_at,state) VALUES (?,?, 'OPEN')",
                       (batch_id, utc_now()))
        return cls(root, batch_id)

    @contextmanager
    def connection(self):
        # mode=rw prevents accidental creation of an empty database if a batch disappeared.
        db = sqlite3.connect(self.path.resolve().as_uri() + "?mode=rw", uri=True, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA synchronous=FULL")
            if db.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise ValueError("Unsupported batch database version")
            with db:
                yield db
        finally:
            db.close()

    def info(self):
        with self.connection() as db:
            result = dict(db.execute("SELECT * FROM batch WHERE id=?", (self.id,)).fetchone())
            result["record_count"] = db.execute("SELECT count(*) FROM records").fetchone()[0]
        return result

    def add(self, product):
        if not isinstance(product, dict):
            raise ValueError("Product must be an object")
        for field in ("source", "source_url", "name"):
            if not isinstance(product.get(field), str) or not product[field].strip():
                raise ValueError(f"Missing or invalid field: {field}")
        # Identity is source-local, not a claim of canonical product deduplication.
        external_id = product.get("external_id") or product["source_url"]
        if not isinstance(external_id, str):
            raise ValueError("external_id must be a string")
        validate_value(product)
        payload = canonical_json(product)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        source = product["source"]
        record_id = hashlib.sha256(canonical_json([source, external_id]).encode("utf-8")).hexdigest()
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            state = db.execute("SELECT state FROM batch WHERE id=?", (self.id,)).fetchone()[0]
            if state != "OPEN":
                raise ValueError("Batch is sealed; collect new results in a new batch")
            previous = db.execute("SELECT content_sha256 FROM records WHERE record_id=?", (record_id,)).fetchone()
            if previous and previous[0] == digest:
                return "unchanged"
            db.execute("""INSERT INTO records VALUES (?,?,?,?,?,?)
                ON CONFLICT(record_id) DO UPDATE SET payload=excluded.payload,
                content_sha256=excluded.content_sha256, collected_at=excluded.collected_at""",
                       (record_id, source, external_id, payload, digest, utc_now()))
            return "updated" if previous else "inserted"

    def seal(self):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM records LIMIT 1").fetchone():
                raise ValueError("Cannot export an empty batch")
            db.execute("UPDATE batch SET state='SEALED' WHERE id=? AND state='OPEN'", (self.id,))

    def records(self):
        with self.connection() as db:
            for row in db.execute("SELECT * FROM records ORDER BY record_id"):
                yield dict(row)

    def mark_archived(self, digest):
        with self.connection() as db:
            db.execute("UPDATE batch SET state='ARCHIVED', archived_at=COALESCE(archived_at,?), "
                       "archive_sha256=? WHERE id=? AND state IN ('SEALED','ARCHIVED')",
                       (utc_now(), digest, self.id))
