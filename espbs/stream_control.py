"""Collector backpressure. No archive download, confirmation or deletion."""
from contextlib import contextmanager
from .jobs import Job, worker_lock
from .retention import receipt
from .storage import Batch
from .stream_parts import MAX_PRODUCTS, WINDOW, create_next

MAX_VERSIONS = 10_000
MAX_PAYLOAD_BYTES = 64 * 1024 * 1024


class WaitingForParts(ValueError):
    pass


def progress(job):
    with job.db() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='stream_parts'").fetchone():
            return 0, False, 0
        last = db.execute('SELECT * FROM stream_parts ORDER BY seq DESC LIMIT 1').fetchone()
        pending = list(db.execute('SELECT child_id,ready FROM stream_parts WHERE released=0'))
    occupied = 0
    for row in pending:
        if not row['ready']:
            occupied += 1
            continue
        saved = receipt(Job(job.root, row['child_id']))
        if not saved or saved['state'] != 'CLEANED':
            occupied += 1
    return ((last['end_seq'] if last['ready'] else last['start_seq']) if last else 0,
            bool(last and not last['ready']), occupied)


@contextmanager
def request_slot(job):
    with worker_lock(Batch(job.root, job.id).path.with_suffix('.stream-gate.lock')):
        _checkpoint(job)
        yield


def checkpoint(job, flush=False):
    with worker_lock(Batch(job.root, job.id).path.with_suffix('.stream-gate.lock')):
        _checkpoint(job, flush)


def _checkpoint(job, flush=False):
    """Called before HTTP and at completion; replay an unfinished snapshot first."""
    batch = Batch(job.root, job.id)
    while True:
        after, unfinished, occupied = progress(job)
        if unfinished:
            create_next(job, after, _gate_held=True)
            continue
        rows = batch.changes(after, MAX_PRODUCTS)
        if flush and not rows:
            return
        if occupied >= WINDOW:
            raise WaitingForParts('Две части ожидают скачивания и явной очистки. После проверки копий очистите часть и продолжите сбор.')
        if not rows or (not flush and len(rows) < MAX_PRODUCTS):
            return
        create_next(job, after, _gate_held=True)
