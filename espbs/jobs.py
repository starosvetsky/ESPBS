"""Persistent, bounded source jobs. Replay after a crash is idempotent."""

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from .storage import Batch, utc_now
from .disk import require_space, LowDiskSpace, MIB

def counters(db):
    if db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='counters'").fetchone():
        return dict(db.execute('SELECT name,value FROM counters'))
    return None


def increment(db, name, amount=1):
    if counters(db) is not None:
        db.execute('INSERT INTO counters VALUES (?,?) ON CONFLICT(name) DO UPDATE SET value=value+excluded.value',
                   (name, amount))


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
    def create(cls, root, limit=3, source='eltex', start_url='', enrichment=None, selectors=None, auto_enrich=False, photo_policy='official'):
        from .sources import configuration
        if source == 'auto':
            from .directory import detect
            config = detect(root, start_url, selectors)
        else:
            config = configuration(source, start_url, enrichment)
        if auto_enrich:
            config['auto_enrich'] = True
        if limit is not None and (type(limit) is not int or not 1 <= limit <= 9223372036854775807):
            raise ValueError('Лимит должен быть положительным целым числом или null (весь каталог)')
        if photo_policy not in ('store', 'official', 'fallback', 'none'):
            raise ValueError('Неизвестный режим фотографий')
        config['photo_policy'] = photo_policy
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
                    CREATE TABLE config (value TEXT NOT NULL);
                    CREATE TABLE counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL);
                    CREATE INDEX items_pending ON items(done,seq);
                    CREATE INDEX pages_pending ON pages(done);
                ''')
                db.execute("INSERT INTO job VALUES ('READY',0,?,?,?,NULL)", (limit, utc_now(), utc_now()))
                db.execute('INSERT INTO config VALUES (?)', (json.dumps(config),))
                db.execute('INSERT INTO pages(url) VALUES (?)', (config['start_url'],))
        finally:
            db.close()
        return cls(root, batch.id)

    @classmethod
    def create_enrichment(cls, parent):
        """Snapshot a bounded finished batch so later cleanup cannot break replay."""
        from .retention import receipt
        batch = Batch(parent.root, parent.id)
        with worker_lock(batch.path.with_suffix('.maintenance.lock')), worker_lock(parent.path.with_suffix('.lock')):
            if parent.info()['state'] != 'COMPLETED':
                raise ValueError('Сначала завершите исходное задание')
            retained = receipt(parent)
            if retained and retained['state'] in ('CLEANING', 'CLEANED'):
                raise ValueError('Исходная партия уже очищается или очищена')
            count = batch.info()['record_count']
            if count < 1:
                raise ValueError('Для обогащения нужна непустая партия')
            require_space(parent.root, 256 * MIB + batch.path.stat().st_size * 2)
            child = cls.create(parent.root, count)
            config = {'source': 'enrichment', 'enrichment': 'directory', 'parent_id': parent.id,
                      'start_url': '', 'snapshot_ready': count <= 100,
                      'photo_policy': parent.info().get('photo_policy', 'official')}
            with child.db() as db:
                db.execute('UPDATE config SET value=?', (json.dumps(config),))
                db.execute('DELETE FROM pages')
                db.execute('CREATE TABLE inputs (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
                if count <= 100:
                    for row in batch.records():
                        db.execute('INSERT INTO inputs VALUES (?,?)', (row['record_id'], row['payload']))
                        db.execute('INSERT INTO items(url) VALUES (?)', (row['record_id'],))
                    increment(db, 'discovered', count)
            if count > 100:
                with parent.db() as db:
                    db.execute('CREATE TABLE IF NOT EXISTS dependents (id TEXT PRIMARY KEY, ready INTEGER)')
                    db.execute('INSERT INTO dependents VALUES (?,0)', (child.id,))
            return child

    def snapshot(self, config, callback):
        """Copy large input queues in restartable chunks inside the worker."""
        if config.get('snapshot_ready', True):
            return
        parent = Job(self.root, config['parent_id'])
        batch = Batch(self.root, parent.id)
        with worker_lock(batch.path.with_suffix('.maintenance.lock')), worker_lock(parent.path.with_suffix('.lock')):
            cursor = config.get('snapshot_cursor', '')
            while True:
                if self.stopped():
                    from .eltex import Stopped
                    raise Stopped()
                require_space(self.root, 256 * MIB)
                rows = batch.products(cursor, 100)
                if not rows:
                    break
                cursor = rows[-1]['cursor']
                config['snapshot_cursor'] = cursor
                with self.db() as db:
                    for row in rows:
                        db.execute('INSERT OR IGNORE INTO inputs VALUES (?,?)',
                                   (row['cursor'], json.dumps(row['product'], ensure_ascii=False)))
                        added = db.execute('INSERT OR IGNORE INTO items(url) VALUES (?)', (row['cursor'],)).rowcount
                        increment(db, 'discovered', added)
                    db.execute('UPDATE config SET value=?', (json.dumps(config),))
                self.event('snapshot', {'copied': self.info()['discovered']}, callback)
            # Mark the dependency released first: the complete inputs snapshot is
            # already durable. A retry can finish even if the parent is cleaned.
            with parent.db() as db:
                db.execute('UPDATE dependents SET ready=1 WHERE id=?', (self.id,))
            config['snapshot_ready'] = True
            with self.db() as db:
                db.execute('UPDATE config SET value=?', (json.dumps(config),))

    def info(self):
        with self.db() as db:
            result = dict(db.execute('SELECT * FROM job').fetchone())
            progress = counters(db)
            result.update(id=self.id, batch_id=self.id)
            if progress is not None:
                result.update(discovered=progress.get('discovered',0), completed=progress.get('completed',0),
                              quality={k[8:]:v for k,v in progress.items() if k.startswith('quality:')},
                              enrichment_counts={k[11:]:v for k,v in progress.items() if k.startswith('enrichment:')})
            else:
                result.update(discovered=db.execute('SELECT count(*) FROM items').fetchone()[0],
                              completed=db.execute('SELECT count(*) FROM items WHERE done=1').fetchone()[0])
                result['quality'] = {row[0]: row[1] for row in db.execute(
                    'SELECT quality,count(*) FROM items WHERE done=1 GROUP BY quality')}
            if db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='config'").fetchone():
                result.update(json.loads(db.execute('SELECT value FROM config').fetchone()[0]))
            else:
                from .eltex import CATALOG
                result.update(source='eltex', start_url=CATALOG, enrichment='none')
        if result['source'] == 'enrichment' and progress is None:
            with Batch(self.root, self.id).connection() as db:
                result['enrichment_counts'] = {row[0]: row[1] for row in db.execute(
                    "SELECT json_extract(payload,'$.enrichment.status'),count(*) FROM records GROUP BY 1")}
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

    def run(self, client=None, callback=None, official_client=None):
        from . import eltex, olnisa
        from .eltex import Stopped
        from .sources import enrich, official_images
        config = self.info()
        from .universal import Adapter, Client as PublicClient
        from .directory import Enricher
        adapter = {'eltex': eltex, 'olnisa': olnisa}.get(config['source']) or Adapter(config.get('selectors'))
        with worker_lock(self.path.with_suffix('.lock')):
            batch = Batch(self.root, self.id)
            if self.info()['state'] == 'COMPLETED':
                return self.info()
            if batch.info()['state'] != 'OPEN':
                raise ValueError('Batch is sealed; create a new job')
            with self.db() as db:
                db.execute("UPDATE job SET state='RUNNING',stop=0,error=NULL,updated_at=?", (utc_now(),))
            owned = client is None
            client = client or (PublicClient(config['start_url'], self.stopped, root=self.root) if config['source'] == 'generic'
                                else None if config['source'] == 'enrichment' else adapter.Client(self.stopped, root=self.root))
            enricher = Enricher(self.root, self.stopped) if config['source'] == 'enrichment' else None
            official_owned = official_client is None
            if config['enrichment'] == 'eltex':
                official_client = official_client or eltex.Client(self.stopped, root=self.root)
            try:
                self.event('started', {}, callback)
                require_space(self.root, 256 * MIB)
                from .catalog import Catalog
                catalog = Catalog(self.root)
                if enricher:
                    # Store only configuration fields when checkpointing inputs.
                    with self.db() as db:
                        snapshot_config = json.loads(db.execute('SELECT value FROM config').fetchone()[0])
                    self.snapshot(snapshot_config, callback)
                target = self.info()['target']
                while True:
                    while True:
                        if self.stopped():
                            raise Stopped()
                        with self.db() as db:
                            progress = counters(db)
                            count = progress.get('discovered',0) if progress is not None else db.execute('SELECT count(*) FROM items').fetchone()[0]
                            page = db.execute('SELECT url FROM pages WHERE done=0 ORDER BY rowid LIMIT 1').fetchone()
                        if (target is not None and count >= target) or not page or count - (progress.get('completed', 0) if progress is not None else self.info()['completed']) >= 500:
                            break
                        with self.db() as db:
                            visited = progress.get('pages',0) if progress is not None else db.execute('SELECT count(*) FROM pages WHERE done=1').fetchone()[0]
                            if visited >= 100_000:
                                raise ValueError('Проверено 100 000 страниц каталога; проверьте пагинацию')
                        require_space(self.root, 256 * MIB)
                        html = client.get(page[0])
                        final_page = getattr(client, 'last_url', None)
                        final_page = final_page if isinstance(final_page, str) else page[0]
                        urls, pages = adapter.listing(html, final_page)
                        if config['source'] == 'olnisa' and not config.get('source_warning'):
                            warning = olnisa.discovery_warning(html)
                            if warning:
                                config['source_warning'] = warning
                                with self.db() as db:
                                    saved = json.loads(db.execute('SELECT value FROM config').fetchone()[0])
                                    saved['source_warning'] = warning
                                    db.execute('UPDATE config SET value=?', (json.dumps(saved),))
                                self.event('source_warning', {'error': warning}, callback)
                        if config['source'] == 'olnisa' and page[0] == config['start_url']:
                            config['expected_total'] = olnisa.advertised_count(html)
                            with self.db() as db:
                                saved = json.loads(db.execute('SELECT value FROM config').fetchone()[0])
                                saved['expected_total'] = config['expected_total']
                                db.execute('UPDATE config SET value=?', (json.dumps(saved),))
                        require_space(self.root, 256 * MIB)
                        with self.db() as db:
                            for url in urls:
                                if target is not None and count >= target:
                                    break
                                added = db.execute('INSERT OR IGNORE INTO items(url) VALUES (?)', (url,)).rowcount
                                count += added
                                increment(db, 'discovered', added)
                            for url in pages:
                                db.execute('INSERT OR IGNORE INTO pages(url) VALUES (?)', (url,))
                            db.execute('UPDATE pages SET done=1 WHERE url=?', (page[0],))
                            increment(db, 'pages')
                        self.event('discovered', {'count': count}, callback)
                    while True:
                        if self.stopped():
                            raise Stopped()
                        with self.db() as db:
                            item = db.execute('SELECT url FROM items WHERE done=0 ORDER BY seq LIMIT 1').fetchone()
                        if not item:
                            break
                        require_space(self.root, 256 * MIB)
                        if enricher:
                            with self.db() as db:
                                original = json.loads(db.execute('SELECT payload FROM inputs WHERE id=?', (item[0],)).fetchone()[0])
                            record = enricher.enrich(original)
                            from .photos import select as select_photos
                            record = select_photos(record, config.get('photo_policy', 'official'), original.get('original_record', original))
                            record.setdefault('provenance', {})['parent_batch_id'] = config['parent_id']
                            self.event('enrichment', {'url': original['source_url'], **record['enrichment']}, callback)
                        else:
                            html = client.get(item[0])
                            final_url = getattr(client, 'last_url', None)
                            final_url = final_url if isinstance(final_url, str) else item[0]
                            record = adapter.product(html, final_url)
                            from .photos import extract, OFFICIAL_HOSTS
                            from urllib.parse import urlsplit
                            if config.get('photo_policy') in ('store', 'fallback') or urlsplit(final_url).hostname in OFFICIAL_HOSTS:
                                record['images'] = extract(html, final_url)
                                record.setdefault('provenance', {})['images'] = {'source_url': final_url, 'policy': config.get('photo_policy', 'official')}
                                record['photo_policy'] = config.get('photo_policy', 'official')
                        if official_client is not None:
                            from copy import deepcopy
                            source_record = deepcopy(record)
                            record = enrich(record, official_client)
                            from .photos import select as select_photos
                            record = select_photos(record, config.get('photo_policy', 'official'), source_record)
                            self.event('enrichment', {'url': item[0], **record['enrichment']}, callback)
                        elif config['source'] == 'eltex':
                            record['images'] = official_images(record)
                        elif not enricher:
                            record['quality']['issues'].append('Официальные данные проверяются отдельным заданием' if config.get('auto_enrich') else 'Обогащение отключено')
                        if config.get('photo_policy') == 'none':
                            def remove_images(value):
                                if isinstance(value, dict):
                                    for field in ('image', 'images'):
                                        value.pop(field, None)
                                    for nested in value.values():
                                        remove_images(nested)
                                elif isinstance(value, list):
                                    for nested in value:
                                        remove_images(nested)
                            remove_images(record)
                            record['images'] = []
                        require_space(self.root, 256 * MIB)
                        outcome = batch.add(record)
                        catalog.add(record, self.id)
                        # A crash here replays this URL; Batch.add prevents duplicate rows.
                        with self.db() as db:
                            db.execute('UPDATE items SET done=1,outcome=?,quality=? WHERE url=?',
                                       (outcome, record['quality']['status'], item[0]))
                            increment(db, 'completed')
                            increment(db, 'quality:' + record['quality']['status'])
                            if 'enrichment' in record:
                                increment(db, 'enrichment:' + record['enrichment']['status'])
                        self.event('saved', {'url': item[0], 'outcome': outcome,
                                            'completed': self.info()['completed']}, callback)
                    if target is not None and self.info()['discovered'] >= target:
                        break
                    with self.db() as db:
                        pending = db.execute('SELECT 1 FROM pages WHERE done=0 LIMIT 1').fetchone()
                    if not pending:
                        break
                state, error = 'COMPLETED', None
                if target is None and config.get('expected_total') and self.info()['completed'] < config['expected_total']:
                    error = f"Неполный сбор: сохранено {self.info()['completed']} из заявленных сайтом {config['expected_total']}"
            except LowDiskSpace as exc:
                state, error = 'PAUSED_DISK', str(exc)
            except (Stopped, KeyboardInterrupt):
                state, error = 'STOPPED', None
            except Exception as exc:
                state, error = 'FAILED', str(exc)
            finally:
                if owned and client is not None:
                    client.close()
                if enricher:
                    enricher.close()
                if official_owned and official_client is not None:
                    official_client.close()
            with self.db() as db:
                db.execute('UPDATE job SET state=?,error=?,updated_at=?', (state, error, utc_now()))
            self.event(state.lower(), {'error': error}, callback)
        if state == 'COMPLETED' and config.get('auto_enrich'):
            try:
                child = self.create_enrichment(self)
                config['child_id'] = child.id
                with self.db() as db:
                    db.execute('UPDATE config SET value=?', (json.dumps({k: config[k] for k in (
                        'source','start_url','enrichment','selectors','auto_enrich','child_id','photo_policy','expected_total','source_warning') if k in config}),))
                from .api import launch_worker
                launch_worker(self.root, child.id)
            except Exception as exc:
                message = 'Сбор сохранён, но обогащение не запущено: ' + str(exc)
                self.event('enrichment_launch_failed', {'error': message}, callback)
                with self.db() as db:
                    db.execute('UPDATE job SET error=?', (message,))
        return self.info()
