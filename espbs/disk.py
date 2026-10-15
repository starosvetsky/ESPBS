"""Advisory disk headroom checks; never remove user data."""
import os
import shutil
from pathlib import Path

MIB = 1024 * 1024


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


def status(root):
    root = Path(root)
    usage = shutil.disk_usage(existing_parent(root))
    reserve = reserve_bytes()
    sizes = {}
    for name in ('batches', 'jobs', 'exports'):
        sizes[name] = sum(p.stat().st_size for p in (root / name).glob('*') if p.is_file())
    sizes['directory'] = sum(p.stat().st_size for p in root.glob('directory.sqlite3*') if p.is_file())
    return {'free_bytes': usage.free, 'total_bytes': usage.total,
            'reserve_bytes': reserve, 'collection_headroom_bytes': 256 * MIB,
            'can_collect': usage.free >= reserve + 256 * MIB, 'sizes': sizes}
