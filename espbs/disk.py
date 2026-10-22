"""Advisory disk headroom checks; never remove user data."""
import os
import shutil
import stat
import time
from collections import OrderedDict
from pathlib import Path
from threading import Lock

MIB = 1024 * 1024
SUMMARY_TTL = 30
_summaries = OrderedDict()
_summary_lock = Lock()


class LowDiskSpace(ValueError):
    pass


def reserve_bytes():
    value = int(os.environ.get('ESPBS_DISK_RESERVE_MIB', '1024'))
    if value < 64:
        raise ValueError('ESPBS_DISK_RESERVE_MIB must be at least 64')
    return value * MIB


def existing_parent(path):
    path = Path(path).resolve()
    while not path.exists():
        path = path.parent
    return path


def require_space(path, extra=0):
    free = shutil.disk_usage(existing_parent(path)).free
    required = reserve_bytes() + extra
    if free < required:
        raise LowDiskSpace(f'Недостаточно места: свободно {free // MIB} МБ, '
                           f'нужно не менее {(required + MIB - 1) // MIB} МБ. '
                           'Данные сохранены. Освободите место и продолжите вручную.')
    return free


def _file_size(path):
    try:
        value = path.stat()
    except FileNotFoundError:
        # WAL files and manually cleaned archives can disappear during a scan.
        return 0
    return value.st_size if stat.S_ISREG(value.st_mode) else 0


def _scan_sizes(root):
    sizes = {}
    for name in ('batches', 'jobs', 'exports'):
        sizes[name] = sum(_file_size(p) for p in (root / name).glob('*'))
    for name in ('directory', 'catalog', 'job-index'):
        sizes[name] = sum(_file_size(p) for p in root.glob(name + '.sqlite3*'))
    sizes['traffic'] = sum(_file_size(p) for p in (root / 'traffic').glob('*'))
    return sizes


def _summary(root):
    # Single-flight refresh: concurrent dashboard requests do not duplicate scans.
    # Only directory totals are cached, never disk headroom or reserve settings.
    with _summary_lock:
        saved = _summaries.get(root)
        if saved is None or time.monotonic() - saved[0] >= SUMMARY_TTL:
            saved = (time.monotonic(), _scan_sizes(root))
            _summaries[root] = saved
        _summaries.move_to_end(root)
        while len(_summaries) > 8:
            _summaries.popitem(last=False)
        return dict(saved[1]), max(0, time.monotonic() - saved[0])


def status(root):
    root = Path(root).resolve()
    sizes, age = _summary(root)
    # Read after a potentially slow summary refresh, not before it.
    usage = shutil.disk_usage(existing_parent(root))
    reserve = reserve_bytes()
    return {'free_bytes': usage.free, 'total_bytes': usage.total,
            'reserve_bytes': reserve, 'collection_headroom_bytes': 256 * MIB,
            'can_collect': usage.free >= reserve + 256 * MIB, 'sizes': sizes,
            'sizes_age_seconds': round(age, 1), 'sizes_refresh_seconds': SUMMARY_TTL}
