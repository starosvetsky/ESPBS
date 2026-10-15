"""Persistent, bounded source jobs. Replay after a crash is idempotent."""

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from .storage import Batch, utc_now
from .disk import require_space, LowDiskSpace, MIB


@contextmanager
def worker_lock(path):
    with open(path, 'a+b') as stream:
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            if os.fstat(stream.fileno()).st_size == 0:
                stream.write(b'0')
                stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise ValueError('Job is already running') from error
        else:
            import fcntl
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise ValueError('Job is already running') from error
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


class Job:
    def __init__(self, root, job_id):
        self.root = Path(root)
        self.id = str(UUID(job_id))
        self.path = self.root / 'jobs' / (self.id + '.sqlite3')
        if not self.path.exists():
            raise FileNotFoundError('Job not found: ' + self.id)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path.resolve().as_uri() + '?mode=rw', uri=True, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA synchronous=FULL')
            with db:
                yield db
        finally:
            db.close()

    @classmethod
    def create(cls, root, limit=3):
        from .eltex import CATALOG
        if not 1 <= limit <= 100:
            raise ValueError('Limit must be between 1 and 100')
        require_space(root, 256 * MIB)
        batch = Batch.create(root)
        directory = Path(root) / 'jobs'
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (batch.id + '.sqlite3')
        db = sqlite3.connect(path)
        try:
            with db:
                db.executescript('''
                    CREATE TABLE job (state TEXT, stop INTEGER, target INTEGER,
                                      created_at TEXT, updated_at TEXT, error TEXT);
                    CREATE TABLE pages (url TEXT PRIMARY KEY, done INTEGER DEFAULT 0);
                    CREATE TABLE items (seq INTEGER PRIMARY KEY, url TEXT UNIQUE,
                                        done INTEGER DEFAULT 0, outcome TEXT, quality TEXT);
                    CREATE TABLE events (seq INTEGER PRIMARY KEY, time TEXT, kind TEXT, detail TEXT);
                ''')
                db.execute("INSERT INTO job VALUES ('READY',0,?,?,?,NULL)", (limit, utc_now(), utc_now()))
                db.execute('INSERT INTO pages(url) VALUES (?)', (CATALOG,))
        finally:
            db.close()
        return cls(root, batch.id)

    def info(self):
        with self.db() as db:
            result = dict(db.execute('SELECT * FROM job').fetchone())
            result.update(id=self.id, batch_id=self.id,
                          discovered=db.execute('SELECT count(*) FROM items').fetchone()[0],
                          completed=db.execute('SELECT count(*) FROM items WHERE done=1').fetchone()[0])
            result['quality'] = {row[0]: row[1] for row in db.execute(
                'SELECT quality,count(*) FROM items WHERE done=1 GROUP BY quality')}
        return result

    def reconcile(self):
        """Turn an orphaned RUNNING marker into a visible failure.

        The database state is not proof that a worker is alive.  The lock is
        the authority and survives API restarts because the worker owns it.
        """
        result = self.info()
        if result['state'] != 'RUNNING':
            return result
        try:
            with worker_lock(self.path.with_suffix('.lock')):
                pass
        except ValueError:
            return result
        error = 'Worker process is no longer running; saved progress is available'
        with self.db() as db:
            db.execute("UPDATE job SET state='FAILED',error=?,updated_at=? WHERE state='RUNNING'",
                       (error, utc_now()))
        self.event('worker_lost', {'error': error}, None)
        return self.info()

    def stop(self):
        with self.db() as db:
            db.execute('UPDATE job SET stop=1')

    def stopped(self):
        with self.db() as db:
            return bool(db.execute('SELECT stop FROM job').fetchone()[0])

    def event(self, kind, detail, callback):
        event = {'time': utc_now(), 'job_id': self.id, 'kind': kind, **detail}
        with self.db() as db:
            db.execute('INSERT INTO events(time,kind,detail) VALUES (?,?,?)',
                       (event['time'], kind, json.dumps(detail, ensure_ascii=False)))
            db.execute('DELETE FROM events WHERE seq <= (SELECT coalesce(max(seq),0)-1000 FROM events)')
        if callback:
            callback(event)

    def events(self, after=0, limit=100):
        if after < 0 or not 1 <= limit <= 200:
            raise ValueError('Invalid event cursor or limit')
        with self.db() as db:
            rows = db.execute('SELECT * FROM events WHERE seq>? ORDER BY seq LIMIT ?',
                              (after, limit))
            result = []
            for row in rows:
                event = dict(row)
                event.update(json.loads(event.pop('detail')))
                result.append(event)
            return result

    def run(self, client=None, callback=None):
        from .eltex import Client, Stopped, listing, product
        with worker_lock(self.path.with_suffix('.lock')):
            batch = Batch(self.root, self.id)
            if self.info()['state'] == 'COMPLETED':
                return self.info()
            if batch.info()['state'] != 'OPEN':
                raise ValueError('Batch is sealed; create a new job')
            with self.db() as db:
                db.execute("UPDATE job SET state='RUNNING',stop=0,error=NULL,updated_at=?", (utc_now(),))
            owned = client is None
            client = client or Client(self.stopped)
            try:
                self.event('started', {}, callback)
                require_space(self.root, 256 * MIB)
                target = self.info()['target']
                while True:
                    if self.stopped():
                        raise Stopped()
                    with self.db() as db:
                        count = db.execute('SELECT count(*) FROM items').fetchone()[0]
                        page = db.execute('SELECT url FROM pages WHERE done=0 ORDER BY rowid LIMIT 1').fetchone()
                    if count >= target or not page:
                        break
                    with self.db() as db:
                        if db.execute('SELECT count(*) FROM pages WHERE done=1').fetchone()[0] >= 20:
                            raise ValueError('Discovery exceeded 20 pages; inspect source before resuming')
                    require_space(self.root, 256 * MIB)
                    urls, pages = listing(client.get(page[0]), page[0])
                    require_space(self.root, 256 * MIB)
                    with self.db() as db:
                        for url in urls:
                            if count >= target:
                                break
                            count += db.execute('INSERT OR IGNORE INTO items(url) VALUES (?)', (url,)).rowcount
                        for url in pages:
                            db.execute('INSERT OR IGNORE INTO pages(url) VALUES (?)', (url,))
                        db.execute('UPDATE pages SET done=1 WHERE url=?', (page[0],))
                    self.event('discovered', {'count': count}, callback)
                while True:
                    if self.stopped():
                        raise Stopped()
                    with self.db() as db:
                        item = db.execute('SELECT url FROM items WHERE done=0 ORDER BY seq LIMIT 1').fetchone()
                    if not item:
                        break
                    require_space(self.root, 256 * MIB)
                    record = product(client.get(item[0]), item[0])
                    require_space(self.root, 256 * MIB)
                    outcome = batch.add(record)
                    # A crash here replays this URL; Batch.add prevents duplicate rows.
                    with self.db() as db:
                        db.execute('UPDATE items SET done=1,outcome=?,quality=? WHERE url=?',
                                   (outcome, record['quality']['status'], item[0]))
                    self.event('saved', {'url': item[0], 'outcome': outcome,
                                        'completed': self.info()['completed']}, callback)
                state, error = 'COMPLETED', None
            except LowDiskSpace as exc:
                state, error = 'PAUSED_DISK', str(exc)
            except (Stopped, KeyboardInterrupt):
                state, error = 'STOPPED', None
            except Exception as exc:
                state, error = 'FAILED', str(exc)
            finally:
                if owned:
                    client.close()
            with self.db() as db:
                db.execute('UPDATE job SET state=?,error=?,updated_at=?', (state, error, utc_now()))
            self.event(state.lower(), {'error': error}, callback)
            return self.info()
