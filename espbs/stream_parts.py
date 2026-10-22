"""Bounded immutable snapshots of an opt-in journal, including live collectors."""
import hashlib
import json
from uuid import uuid4

from .attachments import references
from .disk import MIB, require_space
from .jobs import Job, worker_lock
from .materials import coverage
from .retention import receipt
from .storage import Batch, canonical_json, utc_now

MAX_PRODUCTS = 25
MAX_REFERENCES = 40
WINDOW = 2
FIELDS = ('record_id', 'source', 'external_id', 'payload', 'content_sha256', 'collected_at')


def fingerprint(rows):
    return hashlib.sha256(canonical_json([
        [row[key] for key in FIELDS] for row in rows
    ]).encode()).hexdigest()


def _copy(target, rows):
    with target.connection() as db:
        for row in rows:
            db.execute('INSERT OR IGNORE INTO records VALUES (?,?,?,?,?,?)',
                       tuple(row[key] for key in FIELDS))


def create_next(parent, after=0):
    """Return the same child for a cursor; None means caught up, not finished.

    Parent maintenance serializes snapshots/cleanup, not the collector lock.
    Journal payloads are immutable; live record updates cannot change the copy.
    """
    if type(after) is not int or not 0 <= after <= 9223372036854775807:
        raise ValueError('Invalid stream cursor')
    source = Batch(parent.root, parent.id)
    with worker_lock(source.path.with_suffix('.maintenance.lock')):
        info = parent.info()
        if info.get('source') == 'archive-part':
            raise ValueError('Use the original collection, not an archive part')
        retained = receipt(parent)
        if retained and retained['state'] in ('CLEANING', 'CLEANED'):
            raise ValueError('Source is being cleaned')
        # Also rejects ordinary batches rather than claiming they are caught up.
        source.changes(after, 1)
        with parent.db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS stream_parts (
                seq INTEGER PRIMARY KEY, start_seq INTEGER UNIQUE NOT NULL,
                end_seq INTEGER NOT NULL, child_id TEXT UNIQUE NOT NULL,
                ready INTEGER NOT NULL DEFAULT 0, released INTEGER NOT NULL DEFAULT 0,
                record_count INTEGER NOT NULL, fingerprint TEXT NOT NULL)''')
            db.execute('CREATE INDEX IF NOT EXISTS stream_parts_pending ON stream_parts(released)')
            saved = db.execute('SELECT * FROM stream_parts WHERE start_seq=?', (after,)).fetchone()
            if saved and saved['ready']:
                return Job(parent.root, saved['child_id'])
            if not saved:
                last = db.execute('SELECT * FROM stream_parts ORDER BY seq DESC LIMIT 1').fetchone()
                if after != (last['end_seq'] if last and last['ready'] else 0) or (last and not last['ready']):
                    raise ValueError('Resume the pending part or use the last end_seq')
                pending = list(db.execute('SELECT child_id FROM stream_parts WHERE released=0'))
        if not saved:
            occupied = 0
            for item in pending:
                state = receipt(Job(parent.root, item['child_id']))
                if state and state['state'] == 'CLEANED':
                    with parent.db() as db:
                        db.execute('UPDATE stream_parts SET released=1 WHERE child_id=?', (item['child_id'],))
                else:
                    occupied += 1
            rows, seen, refs = [], set(), 0
            for row in source.changes(after, MAX_PRODUCTS):
                count = sum(1 for _ in references(json.loads(row['payload'])))
                if row['record_id'] in seen or (rows and refs + count > MAX_REFERENCES):
                    break
                rows.append(row); seen.add(row['record_id']); refs += count
            if not rows:
                return None
            if occupied >= WINDOW:
                raise ValueError('Download, verify and explicitly clean a previous part first')
            require_space(parent.root, 256 * MIB + sum(len(row['payload'].encode()) for row in rows) * 3)
            child_id = str(uuid4())
            with parent.db() as db:
                db.execute('CREATE TABLE IF NOT EXISTS dependents (id TEXT PRIMARY KEY, ready INTEGER)')
                db.execute('INSERT INTO dependents VALUES (?,0)', (child_id,))
                db.execute('INSERT INTO stream_parts(start_seq,end_seq,child_id,record_count,fingerprint) '
                           'VALUES (?,?,?,?,?)', (after, rows[-1]['seq'], child_id, len(rows), fingerprint(rows)))
                saved = db.execute('SELECT * FROM stream_parts WHERE start_seq=?', (after,)).fetchone()
        rows = [row for row in source.changes(after, MAX_PRODUCTS) if row['seq'] <= saved['end_seq']]
        if len(rows) != saved['record_count'] or fingerprint(rows) != saved['fingerprint']:
            raise ValueError('Journal range no longer matches the saved snapshot')
        from .stream_registration import ensure_child
        require_space(parent.root, 256 * MIB + sum(len(row['payload'].encode()) for row in rows) * 3)
        child = ensure_child(parent, saved)
        target = Batch(parent.root, child.id)
        with worker_lock(target.path.with_suffix('.maintenance.lock')), worker_lock(child.path.with_suffix('.lock')):
            require_space(parent.root, 16 * MIB + sum(len(row['payload'].encode()) for row in rows) * 3)
            if target.info()['state'] == 'OPEN':
                _copy(target, rows)
            actual = list(target.records())
            if fingerprint(actual) != fingerprint(sorted(rows, key=lambda row: row['record_id'])):
                raise ValueError('Part contents do not match the journal snapshot')
            counts = {'discovered': len(rows), 'completed': len(rows), 'coverage:measured': len(rows)}
            for row in rows:
                record = json.loads(row['payload'])
                for field, present in coverage(record)['fields'].items():
                    key = 'coverage:' + field
                    counts[key] = counts.get(key, 0) + int(present)
                key = 'quality:' + record.get('quality', {}).get('status', 'REVIEW')
                counts[key] = counts.get(key, 0) + 1
            with target.connection() as db:
                db.execute("UPDATE batch SET state='SEALED' WHERE state='OPEN'")
            with child.db() as db:
                for key, value in counts.items():
                    db.execute('INSERT OR REPLACE INTO counters VALUES (?,?)', (key, value))
                db.execute("UPDATE job SET state='COMPLETED',error=NULL,updated_at=?", (utc_now(),))
            with parent.db() as db:
                db.execute('UPDATE dependents SET ready=1 WHERE id=?', (child.id,))
                db.execute('UPDATE stream_parts SET ready=1 WHERE child_id=?', (child.id,))
        return child
