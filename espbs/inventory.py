"""Read the actual batch snapshots, including collections predating Catalog."""
import json
from pathlib import Path
from .storage import Batch
from .presentation import public_product


def batches(root):
    return [Batch(root, path.stem).info() for path in
            sorted((Path(root) / 'batches').glob('*.sqlite3'))]


def products(root, batch_id='', after='', query='', limit=50):
    if not 1 <= limit <= 100 or len(query) > 200:
        raise ValueError('Invalid query or limit')
    cursor_batch, separator, cursor_record = after.partition(':')
    if after and (not separator or len(cursor_record) != 64):
        raise ValueError('Invalid cursor')
    paths = ([Batch(root, batch_id).path] if batch_id else
             sorted((Path(root) / 'batches').glob('*.sqlite3')))
    items = []
    # instr treats user input literally. Python casefold also supports Cyrillic.
    for path in paths:
        if after and path.stem < cursor_batch:
            continue
        batch = Batch(root, path.stem)
        with batch.connection() as db:
            db.create_function('fold', 1, lambda value: str(value or '').casefold())
            rows = db.execute('SELECT record_id,payload,collected_at FROM records '
                              'WHERE record_id>? AND instr(fold(payload),?)>0 '
                              'ORDER BY record_id LIMIT ?',
                              (cursor_record if path.stem == cursor_batch else '',
                               query.casefold(), limit + 1 - len(items)))
            for row in rows:
                items.append({'cursor': path.stem + ':' + row['record_id'],
                              'batch_id': path.stem, 'collected_at': row['collected_at'],
                              'product': public_product(json.loads(row['payload']))})
        if len(items) > limit:
            break
    return {'products': items[:limit], 'has_more': len(items) > limit,
            'next_cursor': items[min(limit, len(items)) - 1]['cursor'] if items else after}
