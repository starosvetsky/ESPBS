"""Explicit archive receipt and restartable cleanup. No automatic deletion."""
import json
from pathlib import Path

from .archive import verify_archive
from .jobs import worker_lock
from .storage import Batch, utc_now


def receipt(job):
    with job.db() as db:
        db.execute('CREATE TABLE IF NOT EXISTS retention (id INTEGER PRIMARY KEY CHECK(id=1), receipt TEXT, state TEXT)')
        row = db.execute('SELECT receipt,state FROM retention WHERE id=1').fetchone()
        return {'receipt': json.loads(row[0]), 'state': row[1]} if row else None


def confirm_copy(job, report):
    with worker_lock(job.path.with_suffix('.lock')):
        old = receipt(job)
        if old and old['state'] != 'VERIFIED':
            raise ValueError('Cleanup already started')
        if job.info()['state'] != 'COMPLETED':
            raise ValueError('Only completed jobs can be confirmed')
        archive = verify_archive(job.root / 'exports' / (job.id + '.zip'))
        batch = Batch(job.root, job.id).info()
        for key in ('batch_id', 'archive_sha256', 'xml_sha256', 'record_count'):
            if report.get(key) != archive[key]:
                raise ValueError('Local verification report does not match: ' + key)
        if archive['archive_sha256'] != batch['archive_sha256']:
            raise ValueError('Archive does not match saved batch checksum')
        saved = {key: archive[key] for key in ('batch_id', 'archive_sha256', 'xml_sha256', 'record_count')}
        saved['confirmed_at'] = utc_now()
        with job.db() as db:
            db.execute("INSERT OR REPLACE INTO retention VALUES (1,?,'VERIFIED')", (json.dumps(saved),))
        return receipt(job)


def cleanup(job, confirmation):
    if confirmation != job.id:
        raise ValueError('Type the full job ID to confirm cleanup')
    batch = Batch(job.root, job.id)
    with worker_lock(batch.path.with_suffix('.maintenance.lock')), worker_lock(job.path.with_suffix('.lock')):
        with job.db() as db:
            if db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='dependents'").fetchone():
                if db.execute('SELECT 1 FROM dependents WHERE ready=0 LIMIT 1').fetchone():
                    raise ValueError('Дождитесь копирования исходных записей в очередь обогащения')
        saved = receipt(job)
        if not saved:
            raise ValueError('Verify and confirm the downloaded copy first')
        if saved['state'] == 'CLEANED':
            return saved
        batch = Batch(job.root, job.id)
        if batch.info()['state'] != 'ARCHIVED':
            raise ValueError('Batch is not archived')
        archive = job.root / 'exports' / (job.id + '.zip')
        # Resolve and check the exact file; never delete a caller-supplied path.
        if archive.resolve().parent != (job.root / 'exports').resolve() or archive.is_symlink():
            raise ValueError('Unexpected archive path')
        if saved['state'] == 'VERIFIED':
            current = verify_archive(archive)
            if current['archive_sha256'] != saved['receipt']['archive_sha256']:
                raise ValueError('Server archive changed after confirmation')
            with job.db() as db:
                db.execute("UPDATE retention SET state='CLEANING' WHERE id=1")
        # Keep batch and job metadata for history. Each step is safe to repeat.
        with batch.connection() as db:
            db.execute('DELETE FROM records')
        with batch.connection() as db:
            db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            db.execute('VACUUM')
        with job.db() as db:
            if db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='inputs'").fetchone():
                db.execute('DELETE FROM inputs')
        with job.db() as db:
            db.execute('VACUUM')
        archive.unlink(missing_ok=True)
        with job.db() as db:
            db.execute("UPDATE retention SET state='CLEANED' WHERE id=1")
        return receipt(job)
