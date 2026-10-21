"""Small, restartable export snapshots of completed batches. No source refetch."""
import json

from .attachments import references
from .disk import require_space, MIB
from .jobs import Job, worker_lock
from .materials import coverage
from .retention import receipt
from .storage import Batch, utc_now

MAX_PRODUCTS = 25
MAX_REFERENCES = 40


def summary(parent):
    with parent.db() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='archive_parts'").fetchone():
            return {'count': 0, 'next_cursor': '', 'done': False, 'recent': []}
        count = db.execute('SELECT count(*) FROM archive_parts').fetchone()[0]
        recent = [dict(row) for row in db.execute('SELECT * FROM archive_parts ORDER BY seq DESC LIMIT 10')]
    last = recent[0] if recent else None
    cursor = (last['end_cursor'] if last['ready'] else last['start_cursor']) if last else ''
    source = Batch(parent.root, parent.id)
    with source.connection() as db:
        remaining = bool(db.execute('SELECT 1 FROM records WHERE record_id>? LIMIT 1', (cursor,)).fetchone())
    return {'count': count, 'next_cursor': cursor, 'done': not remaining,
            'recent': recent}


def create_next(parent, after=''):
    """The same cursor always returns the same child, including after a crash.

    A pending child protects parent cleanup. Raw rows retain their original
    collection timestamps, IDs, payload and hashes. Parent history stays intact.
    """
    if not isinstance(after, str) or len(after) > 128:
        raise ValueError('Invalid partition cursor')
    source = Batch(parent.root, parent.id)
    with worker_lock(source.path.with_suffix('.maintenance.lock')), worker_lock(parent.path.with_suffix('.lock')):
        if parent.info()['state'] != 'COMPLETED':
            raise ValueError('Сначала завершите исходное задание')
        retained = receipt(parent)
        if retained and retained['state'] in ('CLEANING', 'CLEANED'):
            raise ValueError('Исходные записи уже очищаются или очищены')
        if parent.info().get('source') == 'archive-part':
            raise ValueError('Создавайте следующие части из исходной партии')
        with parent.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS archive_parts (seq INTEGER PRIMARY KEY, start_cursor TEXT UNIQUE, end_cursor TEXT, child_id TEXT UNIQUE, ready INTEGER DEFAULT 0, record_count INTEGER, reference_count INTEGER)')
            saved = db.execute('SELECT * FROM archive_parts WHERE start_cursor=?', (after,)).fetchone()
            if saved and saved['ready']:
                return Job(parent.root, saved['child_id'])
            if not saved:
                last = db.execute('SELECT * FROM archive_parts ORDER BY seq DESC LIMIT 1').fetchone()
                if after != (last['end_cursor'] if last and last['ready'] else ''):
                    raise ValueError('Неверный курсор следующей части')
                if last and not last['ready']:
                    raise ValueError('Сначала завершите незавершённую часть')
        if not saved:
            rows, refs = [], 0
            with source.connection() as db:
                for row in db.execute('SELECT * FROM records WHERE record_id>? ORDER BY record_id LIMIT ?', (after, MAX_PRODUCTS)):
                    count = sum(1 for _ in references(json.loads(row['payload'])))
                    if rows and refs + count > MAX_REFERENCES:
                        break
                    rows.append(dict(row)); refs += count
            if not rows:
                raise ValueError('Все записи уже распределены по частям')
            require_space(parent.root, 16 * MIB + sum(len(r['payload'].encode()) for r in rows) * 3)
            # Job lock is already held; Batch.seal() would acquire it again.
            with source.connection() as db:
                db.execute("UPDATE batch SET state='SEALED' WHERE state='OPEN'")
            child = Job.create(parent.root, len(rows))
            config = {'source': 'archive-part', 'parent_id': parent.id, 'start_url': '',
                      'enrichment': 'none', 'auto_enrich': False,
                      'photo_policy': parent.info().get('photo_policy', 'official')}
            with child.db() as db:
                db.execute('UPDATE config SET value=?', (json.dumps(config),))
                db.execute("UPDATE job SET state='PREPARING'")
                db.execute('DELETE FROM pages')
            with parent.db() as db:
                db.execute('CREATE TABLE IF NOT EXISTS dependents (id TEXT PRIMARY KEY, ready INTEGER)')
                db.execute('INSERT INTO dependents VALUES (?,0)', (child.id,))
                db.execute('INSERT INTO archive_parts(start_cursor,end_cursor,child_id,record_count,reference_count) VALUES (?,?,?,?,?)',
                           (after, rows[-1]['record_id'], child.id, len(rows), refs))
                saved = db.execute('SELECT * FROM archive_parts WHERE start_cursor=?', (after,)).fetchone()
        child = Job(parent.root, saved['child_id'])
        target = Batch(parent.root, child.id)
        with worker_lock(target.path.with_suffix('.maintenance.lock')), worker_lock(child.path.with_suffix('.lock')):
            if target.info()['state'] == 'OPEN':
                with source.connection() as src, target.connection() as dest:
                    for row in src.execute('SELECT * FROM records WHERE record_id>? AND record_id<=? ORDER BY record_id',
                                           (after, saved['end_cursor'])):
                        require_space(parent.root, len(row['payload'].encode()) * 3 + MIB)
                        dest.execute('INSERT OR IGNORE INTO records VALUES (?,?,?,?,?,?)', tuple(row))
            # Recompute bounded counters after an interrupted snapshot, never double-count.
            counts = {'discovered': 0, 'completed': 0}
            for row in target.records():
                record = json.loads(row['payload'])
                counts['discovered'] += 1; counts['completed'] += 1
                for field, present in coverage(record)['fields'].items():
                    key = 'coverage:' + field
                    counts[key] = counts.get(key, 0) + int(present)
                counts['coverage:measured'] = counts['completed']
                quality = 'quality:' + record.get('quality', {}).get('status', 'REVIEW')
                counts[quality] = counts.get(quality, 0) + 1
            if counts['completed'] != saved['record_count']:
                raise ValueError('Количество записей части не совпадает со снимком')
            with target.connection() as db:
                db.execute("UPDATE batch SET state='SEALED' WHERE state='OPEN'")
            with child.db() as db:
                for key, value in counts.items():
                    db.execute('INSERT OR REPLACE INTO counters VALUES (?,?)', (key, value))
                db.execute("UPDATE job SET state='COMPLETED',error=NULL,updated_at=?", (utc_now(),))
            with parent.db() as db:
                db.execute('UPDATE dependents SET ready=1 WHERE id=?', (child.id,))
                db.execute('UPDATE archive_parts SET ready=1 WHERE child_id=?', (child.id,))
        return child
