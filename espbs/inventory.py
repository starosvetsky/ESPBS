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
    if batch_id:
        cursor_batch, separator, cursor_record = after.partition(':')
        if after and (not separator or cursor_batch != batch_id or len(cursor_record) != 64):
            raise ValueError('Invalid cursor')
        paths = [Batch(root, batch_id).path]
    else:
        # Across snapshots record_id is the product identity.  The same product
        # may legitimately occur in several batches; show its newest snapshot.
        cursor_record = after.rsplit(':', 1)[-1] if after else ''
        if after and len(cursor_record) != 64:
            raise ValueError('Invalid cursor')
        paths = sorted((Path(root) / 'batches').glob('*.sqlite3'))
        newest = {}
        for path in paths:
            batch = Batch(root, path.stem)
            with batch.connection() as db:
                db.create_function('fold', 1, lambda value: str(value or '').casefold())
                rows = db.execute('SELECT record_id,payload,collected_at FROM records '
                                  'WHERE record_id>? AND instr(fold(payload),?)>0 '
                                  'ORDER BY record_id LIMIT ?',
                                  (cursor_record, query.casefold(), limit + 1))
                for row in rows:
                    previous = newest.get(row['record_id'])
                    candidate = (row['collected_at'], path.stem, row['payload'])
                    if previous is None or candidate[:2] > previous[:2]:
                        newest[row['record_id']] = candidate
        rows = sorted(newest.items())[:limit + 1]
        items = [{'cursor': record_id, 'batch_id': value[1],
                  'collected_at': value[0],
                  'product': public_product(json.loads(value[2]))}
                 for record_id, value in rows]
        return {'products': items[:limit], 'has_more': len(items) > limit,
                'next_cursor': items[min(limit, len(items)) - 1]['cursor'] if items else after}
    items = []
    # instr treats user input literally. Python casefold also supports Cyrillic.
    for path in paths:
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
