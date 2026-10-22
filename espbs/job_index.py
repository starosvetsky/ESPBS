"""Small rebuildable index; mutable progress stays in each job database."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID


@contextmanager
def connection(root):
    Path(root).mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(Path(root) / 'job-index.sqlite3', timeout=30)
    try:
        with db:
            db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, created_at TEXT NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS jobs_created ON jobs(created_at DESC,id DESC)')
            yield db
    finally:
        db.close()


def register(job):
    with job.db() as source:
        created = source.execute('SELECT created_at FROM job').fetchone()[0]
    with connection(job.root) as db:
        db.execute('INSERT OR IGNORE INTO jobs VALUES (?,?)', (job.id, created))


def rebuild_missing(root):
    """Startup recovery, including old jobs and a crash before registration."""
    from .jobs import Job
    with connection(root) as db:
        for path in (Path(root) / 'jobs').glob('*.sqlite3'):
            if db.execute('SELECT 1 FROM jobs WHERE id=?', (path.stem,)).fetchone():
                continue
            job = Job(root, path.stem)
            with job.db() as source:
                created = source.execute('SELECT created_at FROM job').fetchone()[0]
            db.execute('INSERT OR IGNORE INTO jobs VALUES (?,?)', (job.id, created))


def page(root, after='', limit=25):
    from .jobs import Job
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('limit must be between 1 and 100')
    with connection(root) as db:
        if after:
            after = str(UUID(after))
            anchor = db.execute('SELECT created_at,id FROM jobs WHERE id=?', (after,)).fetchone()
            if anchor is None:
                raise ValueError('Unknown jobs cursor')
            rows = db.execute('SELECT id FROM jobs WHERE (created_at,id) < (?,?) '
                              'ORDER BY created_at DESC,id DESC LIMIT ?', (*anchor, limit + 1)).fetchall()
        else:
            rows = db.execute('SELECT id FROM jobs ORDER BY created_at DESC,id DESC LIMIT ?',
                              (limit + 1,)).fetchall()
    # No archive inspection or attachment hashing for sidebar refreshes.
    items = [Job(root, row[0]).reconcile() for row in rows[:limit]]
    more = len(rows) > limit
    return {'jobs': items, 'has_more': more,
            'next_cursor': items[-1]['id'] if more else None}
