"""Persistent source identities and latest observations; batches remain snapshots."""
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from .storage import canonical_json, utc_now


class Catalog:
    def __init__(self, root):
        self.path = Path(root) / 'catalog.sqlite3'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS products (id TEXT PRIMARY KEY, source TEXT NOT NULL, external_id TEXT NOT NULL, payload TEXT, batch_id TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(source,external_id))')
            db.execute('CREATE INDEX IF NOT EXISTS products_batch ON products(batch_id)')

    def add(self, product, batch_id):
        source = product['source']
        external = product.get('external_id') or product['source_url']
        identity = hashlib.sha256(canonical_json([source, external]).encode()).hexdigest()
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute('INSERT INTO products VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,batch_id=excluded.batch_id,updated_at=excluded.updated_at',
                       (identity, source, external, canonical_json(product), batch_id, utc_now()))
        return identity

    def products(self, after='', limit=50):
        if not isinstance(after, str) or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('Invalid catalog cursor or limit')
        with closing(sqlite3.connect(self.path, timeout=10)) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute('SELECT * FROM products WHERE id>? ORDER BY id LIMIT ?', (after, limit))
            return [{**dict(row), 'payload': json.loads(row['payload']) if row['payload'] else None} for row in rows]

    def release(self, batch_id):
        # Keep stable IDs but free content owned by a deliberately cleaned batch.
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute('UPDATE products SET payload=NULL WHERE batch_id=?', (batch_id,))
        with closing(sqlite3.connect(self.path, timeout=10)) as db:
            db.execute('VACUUM')
