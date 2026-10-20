"""Persistent background preparation; a closed browser does not cancel export."""
import os
from pathlib import Path
import subprocess
import sys
import time

from .jobs import worker_lock
from .storage import Batch


def save(batch, state, error=''):
    with batch.connection() as db:
        db.execute('CREATE TABLE IF NOT EXISTS export_task (id INTEGER PRIMARY KEY CHECK(id=1), state TEXT, updated REAL, error TEXT)')
        db.execute('INSERT OR REPLACE INTO export_task VALUES (1,?,?,?)', (state, time.time(), error))


def status(batch):
    with batch.connection() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='export_task'").fetchone():
            return {}
        row = db.execute('SELECT state,updated,error FROM export_task WHERE id=1').fetchone()
    if not row:
        return {}
    state, updated, error = row
    if state in ('QUEUED', 'RUNNING') and time.time() - updated > 30:
        try:
            with worker_lock(batch.path.with_suffix('.export-worker.lock')):
                save(batch, 'FAILED', 'Подготовка прервана. Исходные записи сохранены; можно повторить.')
                state, error = 'FAILED', 'Подготовка прервана; повторите запуск.'
        except ValueError:
            pass  # Worker still owns the lock.
    return {'state': state, 'error': error}


def start(root, batch_id):
    batch = Batch(root, batch_id)
    with worker_lock(batch.path.with_suffix('.export-launch.lock')):
        if status(batch).get('state') in ('QUEUED', 'RUNNING'):
            return status(batch)
        if (Path(root) / 'exports' / (batch.id + '.zip')).exists():
            raise ValueError('Архив уже создан и не перезаписывается')
        save(batch, 'QUEUED')
        command = [sys.executable, '-m', 'espbs', '--data-dir', str(Path(root).resolve()),
                   'archive-worker', batch.id]
        kwargs = {'stdin': subprocess.DEVNULL, 'stdout': subprocess.DEVNULL,
                  'stderr': subprocess.DEVNULL, 'close_fds': True}
        if os.name == 'nt':
            kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        else:
            kwargs['start_new_session'] = True
        try:
            subprocess.Popen(command, **kwargs)
        except Exception as error:
            save(batch, 'FAILED', str(error))
            raise
        return {'state': 'QUEUED', 'error': ''}


def run(root, batch_id):
    from .archive import export_batch
    from .jobs import Job
    batch = Batch(root, batch_id)
    with worker_lock(batch.path.with_suffix('.export-worker.lock')):
        save(batch, 'RUNNING')
        try:
            job = Job(root, batch.id)
            if job.reconcile()['state'] != 'COMPLETED':
                raise ValueError('Only a completed job can be archived')
            path = export_batch(batch, Path(root) / 'exports', include_files=True)
            save(batch, 'COMPLETED')
            return {'archive': str(path)}
        except Exception as error:
            save(batch, 'FAILED', str(error))
            raise
