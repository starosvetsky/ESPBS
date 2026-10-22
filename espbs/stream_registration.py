"""Initialize a pre-registered stream child; each database is transactional."""
import json
import sqlite3
from contextlib import closing, contextmanager
from uuid import UUID

from .jobs import Job
from .storage import utc_now


@contextmanager
def _reserved_db(final):
    # The history index only scans *.sqlite3. Do not publish an empty/half-built
    # job database if the process exits during schema creation.
    path = final if final.exists() else final.with_suffix('.pending')
    with closing(sqlite3.connect(path)) as db:
        yield db
    # Last SQLite close checkpoints WAL before the database name is published.
    if path != final:
        path.rename(final)


def _batch(root, child_id):
    directory = root / 'batches'
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (child_id + '.sqlite3')
    with _reserved_db(path) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA synchronous=FULL')
        with db:
            db.execute('BEGIN IMMEDIATE')
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables:
                if not {'batch', 'records'} <= tables or db.execute('PRAGMA user_version').fetchone()[0] != 1:
                    raise ValueError('Unexpected reserved batch schema')
                rows = db.execute('SELECT id FROM batch').fetchall()
                if rows != [(child_id,)]:
                    raise ValueError('Reserved batch identity mismatch')
                return
            db.execute("CREATE TABLE batch (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, "
                       "state TEXT NOT NULL CHECK(state IN ('OPEN','SEALED','ARCHIVED')), "
                       "archived_at TEXT, archive_sha256 TEXT)")
            db.execute('CREATE TABLE records (record_id TEXT PRIMARY KEY, source TEXT NOT NULL, '
                       'external_id TEXT NOT NULL, payload TEXT NOT NULL, content_sha256 TEXT NOT NULL, '
                       'collected_at TEXT NOT NULL, UNIQUE(source,external_id))')
            db.execute('PRAGMA user_version=1')
            db.execute("INSERT INTO batch VALUES (?,?,'OPEN',NULL,NULL)", (child_id, utc_now()))


def _job(root, child_id, config, count):
    directory = root / 'jobs'
    directory.mkdir(parents=True, exist_ok=True)
    with _reserved_db(directory / (child_id + '.sqlite3')) as db:
        db.execute('PRAGMA synchronous=FULL')
        with db:
            db.execute('BEGIN IMMEDIATE')
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables:
                if not {'job', 'pages', 'items', 'events', 'config', 'counters'} <= tables:
                    raise ValueError('Unexpected reserved job schema')
                values = db.execute('SELECT value FROM config').fetchall()
                if len(values) != 1 or json.loads(values[0][0]) != config:
                    raise ValueError('Reserved job configuration mismatch')
                values = db.execute('SELECT target FROM job').fetchall()
                if values != [(count,)]:
                    raise ValueError('Reserved job count mismatch')
                return
            for statement in (
                'CREATE TABLE job (state TEXT, stop INTEGER, target INTEGER, created_at TEXT, updated_at TEXT, error TEXT)',
                'CREATE TABLE pages (url TEXT PRIMARY KEY, done INTEGER DEFAULT 0)',
                'CREATE TABLE items (seq INTEGER PRIMARY KEY, url TEXT UNIQUE, done INTEGER DEFAULT 0, outcome TEXT, quality TEXT)',
                'CREATE TABLE events (seq INTEGER PRIMARY KEY, time TEXT, kind TEXT, detail TEXT)',
                'CREATE TABLE config (value TEXT NOT NULL)',
                'CREATE TABLE counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL)',
                'CREATE INDEX items_pending ON items(done,seq)',
                'CREATE INDEX pages_pending ON pages(done)',
            ):
                db.execute(statement)
            db.execute("INSERT INTO job VALUES ('PREPARING',0,?,?,?,NULL)", (count, utc_now(), utc_now()))
            db.execute('INSERT INTO config VALUES (?)', (json.dumps(config),))


def ensure_child(parent, saved):
    child_id = str(UUID(saved['child_id']))
    config = {'source': 'archive-part', 'parent_id': parent.id, 'start_url': '',
              'enrichment': 'none', 'photo_policy': parent.info().get('photo_policy', 'official'),
              'stream_range': {'after': saved['start_seq'], 'through': saved['end_seq']}}
    # A durable intent already owns this ID. Empty files from interrupted SQLite
    # initialization can be resumed; nonempty, mismatching databases are rejected.
    _batch(parent.root, child_id)
    _job(parent.root, child_id, config, saved['record_count'])
    child = Job(parent.root, child_id)
    from .job_index import register
    register(child)
    return child
