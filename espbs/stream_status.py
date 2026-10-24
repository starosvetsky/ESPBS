"""Bounded, read-only dashboard views of streaming collection."""
from .jobs import Job
from .retention import receipt
from .storage import Batch
from .stream_control import progress
from .stream_parts import WINDOW


def parts(job, after=0, limit=10):
    if type(after) is not int or not 0 <= after <= 9223372036854775807:
        raise ValueError('Invalid stream part cursor')
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('Invalid stream part page size')
    if not job.info().get('streaming'):
        raise ValueError('Not a streaming collection')
    with job.db() as db:
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='stream_parts'").fetchone()
        rows = list(db.execute('SELECT seq,start_seq,end_seq,child_id,ready,record_count '
                               'FROM stream_parts WHERE seq>? ORDER BY seq LIMIT ?',
                               (after, limit + 1))) if exists else []
    result = []
    for row in rows[:limit]:
        value = dict(row)
        saved = receipt(Job(job.root, row['child_id'])) if row['ready'] else None
        value['retention_state'] = saved['state'] if saved else None
        result.append(value)
    return {'parts': result, 'has_more': len(rows) > limit,
            'next_cursor': result[-1]['seq'] if result else after}


def summary(job, info):
    config = info.get('streaming')
    if not config:
        return None
    after, unfinished, occupied = progress(job)
    batch = Batch(job.root, job.id)
    budget = {**config, 'versions': 0, 'payload_bytes': 0}
    with batch.connection() as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='journal_budget'").fetchone():
            budget.update(dict(db.execute('SELECT * FROM journal_budget WHERE id=1').fetchone()))
    budget.pop('id', None)
    return {'budget': budget, 'next_after': after, 'unfinished': unfinished,
            'occupied': occupied, 'window': WINDOW,
            'can_prepare': unfinished or (occupied < WINDOW and budget['versions'] > after)}
