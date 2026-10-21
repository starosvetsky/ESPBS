"""Bounded archive pipeline. Two parts ahead; never confirms or deletes data."""
import os
import subprocess
import sys
import time

from .archive import verify_archive
from .disk import LowDiskSpace, require_space, MIB
from .jobs import Job, worker_lock
from .partitions import create_next, summary
from .retention import receipt
from .storage import Batch

WINDOW = 2
ACTIVE = ('QUEUED', 'RUNNING')


def initialize(job):
    with job.db() as db:
        db.execute("CREATE TABLE IF NOT EXISTS archive_queue (id INTEGER PRIMARY KEY CHECK(id=1), state TEXT, stop INTEGER DEFAULT 0, last_seq INTEGER DEFAULT 0, release_seq INTEGER DEFAULT 0, current_child TEXT DEFAULT '', incomplete_parts INTEGER DEFAULT 0, updated REAL, error TEXT DEFAULT '')")
        db.execute("INSERT OR IGNORE INTO archive_queue(id,state,updated) VALUES (1,'STOPPED',?)", (time.time(),))


def change(job, state, error=''):
    with job.db() as db:
        db.execute('UPDATE archive_queue SET state=?,error=?,updated=? WHERE id=1', (state, error, time.time()))


def status(job):
    with job.db() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='archive_queue'").fetchone():
            return {}
        row = db.execute('SELECT * FROM archive_queue WHERE id=1').fetchone()
        result = dict(row) if row else {}
    if result.get('state') in ACTIVE and time.time() - result['updated'] > 30:
        try:
            with worker_lock(job.path.with_suffix('.archive-queue-worker.lock')):
                change(job, 'FAILED', 'Процесс очереди прерван. Продолжение использует сохранённые части.')
                result.update(state='FAILED', error='Процесс очереди прерван; продолжите вручную.')
        except ValueError:
            pass
    if result:
        result['window'] = WINDOW
        result['pending'] = result['last_seq'] - result['release_seq']
    return result


def start(job):
    batch = Batch(job.root, job.id)
    with worker_lock(batch.path.with_suffix('.maintenance.lock')), worker_lock(job.path.with_suffix('.lock')):
        info = job.info()
        if info['state'] != 'COMPLETED' or info.get('source') == 'archive-part':
            raise ValueError('Очередь запускается из завершённой исходной партии')
        saved = receipt(job)
        if saved and saved['state'] in ('CLEANING', 'CLEANED'):
            raise ValueError('Исходные данные уже очищаются или очищены')
        initialize(job)
        current = status(job)
        if current['state'] in (*ACTIVE, 'COMPLETED'):
            return current
        with job.db() as db:
            db.execute("UPDATE archive_queue SET state='QUEUED',stop=0,error='',updated=? WHERE id=1", (time.time(),))
        command = [sys.executable, '-m', 'espbs', '--data-dir', str(job.root.resolve()),
                   'archive-queue-worker', job.id]
        kwargs = {'stdin': subprocess.DEVNULL, 'stdout': subprocess.DEVNULL,
                  'stderr': subprocess.DEVNULL, 'close_fds': True}
        if os.name == 'nt':
            kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        else:
            kwargs['start_new_session'] = True
        try:
            subprocess.Popen(command, **kwargs)
        except Exception as error:
            change(job, 'FAILED', str(error))
            raise
        return status(job)


def stop(job):
    initialize(job)
    with job.db() as db:
        db.execute("UPDATE archive_queue SET stop=1,state=CASE WHEN state IN ('QUEUED','RUNNING','COMPLETED') THEN state ELSE 'STOPPED' END WHERE id=1")
    return status(job)


def advance_released(job, current):
    """Sequential release keeps the working set bounded without scanning history."""
    released = current['release_seq']
    while released < current['last_seq']:
        with job.db() as db:
            row = db.execute('SELECT seq,child_id FROM archive_parts WHERE seq>? AND seq<=? ORDER BY seq LIMIT 1',
                             (released, current['last_seq'])).fetchone()
        if not row:
            raise ValueError('Нарушена последовательность архивных частей')
        saved = receipt(Job(job.root, row['child_id']))
        if not saved or saved['state'] != 'CLEANED':
            break
        released = row['seq']
    with job.db() as db:
        db.execute('UPDATE archive_queue SET release_seq=? WHERE id=1', (released,))
    return released


def next_part(job, last_seq):
    with job.db() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='archive_parts'").fetchone():
            return None
        row = db.execute('SELECT * FROM archive_parts WHERE seq>? ORDER BY seq LIMIT 1', (last_seq,)).fetchone()
        return dict(row) if row else None


def run(root, job_id, stop_requested=lambda: False):
    from .export_tasks import run as prepare
    job = Job(root, job_id)
    initialize(job)
    with worker_lock(job.path.with_suffix('.archive-queue-worker.lock')):
        change(job, 'RUNNING')
        try:
            while True:
                current = status(job)
                if current['stop'] or stop_requested():
                    change(job, 'STOPPED'); break
                saved = receipt(job)
                if saved and saved['state'] in ('CLEANING', 'CLEANED'):
                    raise ValueError('Исходные данные очищены; очередь продолжить нельзя')
                released = advance_released(job, current)
                part = next_part(job, current['last_seq'])
                parts = summary(job)
                if not part and parts['done']:
                    change(job, 'COMPLETED'); break
                if current['last_seq'] - released >= WINDOW:
                    change(job, 'WAITING_DOWNLOAD', 'Скачайте, проверьте и отдельно очистите предыдущие части по порядку. Затем продолжите очередь.')
                    break
                require_space(job.root, 512 * MIB)
                if part:
                    child = Job(job.root, part['child_id']) if part['ready'] else create_next(job, part['start_cursor'])
                else:
                    child = create_next(job, parts['next_cursor'])
                    part = next_part(job, current['last_seq'])
                with job.db() as db:
                    db.execute('UPDATE archive_queue SET current_child=?,updated=? WHERE id=1', (child.id, time.time()))
                retained = receipt(child)
                incomplete = False
                if retained and retained['state'] == 'CLEANING':
                    raise ValueError('Завершите отдельную очистку текущей части')
                if not retained or retained['state'] != 'CLEANED':
                    path = job.root / 'exports' / (child.id + '.zip')
                    if not path.exists():
                        prepare(root, child.id)
                    # Same lock as explicit cleanup: it cannot remove the ZIP mid-check.
                    with worker_lock(Batch(root, child.id).path.with_suffix('.maintenance.lock')):
                        report = verify_archive(path)
                        batch_info = Batch(root, child.id).info()
                        if (report['batch_id'] != child.id or report['record_count'] != batch_info['record_count']
                                or report['archive_sha256'] != batch_info['archive_sha256']):
                            raise ValueError('Архив не соответствует сохранённой части или её контрольной сумме')
                    if report['version'] != 2:
                        raise ValueError('У части уже есть архив только со ссылками. Он не перезаписывается; проверьте его отдельно.')
                    counts = report['attachment_summary']
                    incomplete = bool(counts['failed'] or counts['skipped'])
                with job.db() as db:
                    db.execute("UPDATE archive_queue SET last_seq=?,current_child='',incomplete_parts=incomplete_parts+?,updated=? WHERE id=1",
                               (part['seq'], int(incomplete), time.time()))
                if incomplete:
                    change(job, 'REVIEW', 'В архиве есть пропуски или ошибки. Проверьте отчёт; продолжение перейдёт к следующей части.')
                    break
        except LowDiskSpace as error:
            change(job, 'PAUSED_DISK', str(error))
        except Exception as error:
            change(job, 'FAILED', str(error))
    return status(job)
