"""Cross-process domain gate. State is shared by all clients in a data root."""
import hashlib
import sqlite3
import time
from contextlib import contextmanager, closing, ExitStack
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit


class SourceBlocked(ValueError):
    pass


class Traffic:
    def __init__(self, root):
        self.root = Path(root)
        self.directory = self.root / 'traffic'
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / 'state.sqlite3'
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS domains (host TEXT PRIMARY KEY, next_at REAL NOT NULL DEFAULT 0, blocked_until REAL NOT NULL DEFAULT 0, reason TEXT NOT NULL DEFAULT \'\')')

    @contextmanager
    def request(self, url, delay, stopped):
        from .jobs import worker_lock
        from .eltex import Stopped
        host = urlsplit(url).hostname.lower()
        lock = self.directory / (hashlib.sha256(host.encode()).hexdigest() + '.lock')
        with ExitStack() as stack:
            while True:
                if stopped():
                    raise Stopped()
                try:
                    stack.enter_context(worker_lock(lock))
                    break
                except ValueError:
                    time.sleep(.1)
            with closing(sqlite3.connect(self.path, timeout=10)) as db:
                with db:
                    db.execute('INSERT OR IGNORE INTO domains(host) VALUES (?)', (host,))
                next_at, until, reason = db.execute('SELECT next_at,blocked_until,reason FROM domains WHERE host=?', (host,)).fetchone()
                if until == -1 or until > time.time():
                    raise SourceBlocked(f'{host}: {reason}; запреты источника не обходятся')
                while time.time() < next_at:
                    if stopped():
                        raise Stopped()
                    time.sleep(max(.001, min(.1, next_at - time.time())))
                if stopped():
                    raise Stopped()
                with db:
                    db.execute('UPDATE domains SET next_at=? WHERE host=?', (time.time() + max(2, delay), host))
                # Keep the lock through response consumption and error recording.
                try:
                    yield
                finally:
                    with db:
                        db.execute('UPDATE domains SET next_at=? WHERE host=?', (time.time() + max(2, delay), host))

    def response(self, url, status, retry_after=None):
        if status not in (403, 429):
            return
        until = -1
        if status == 429:
            until = time.time() + 3600
            if isinstance(retry_after, str):
                try:
                    seconds = int(retry_after)
                    until = time.time() + max(2, seconds)
                except ValueError:
                    try:
                        until = max(time.time() + 2, parsedate_to_datetime(retry_after).timestamp())
                    except (ValueError, TypeError, OverflowError):
                        pass
        host = urlsplit(url).hostname.lower()
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute('INSERT INTO domains(host,blocked_until,reason) VALUES (?,?,?) ON CONFLICT(host) DO UPDATE SET blocked_until=excluded.blocked_until,reason=excluded.reason',
                       (host, until, f'HTTP {status}'))
        raise SourceBlocked(f'{host}: HTTP {status}; сбор остановлен для всех заданий')

    def status(self):
        with closing(sqlite3.connect(self.path, timeout=10)) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute('SELECT * FROM domains ORDER BY host')]
