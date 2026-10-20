"""Bounded attachment embedding. Original records and URLs are never rewritten."""
import hashlib
import http.client
import json
import re
import socket
import ssl
import tempfile
import time
from urllib.parse import urlsplit

from .disk import MIB, LowDiskSpace, require_space
from .eltex import Stopped
from .photos import forbidden
from .storage import canonical_json
from .universal import Client, public_url

MAX_FILE = 32 * MIB
MAX_TOTAL = 256 * MIB
MAX_ATTEMPTS = 50
MAX_SECONDS = 300
MAX_INDEX = 256 * MIB
CHUNK = 65536


def file_type(header, kind):
    if kind == 'documents':
        if header.startswith(b'%PDF-'):
            return '.pdf'
    else:
        if header.startswith(b'\xff\xd8\xff'):
            return '.jpg'
        if header.startswith(b'\x89PNG\r\n\x1a\n'):
            return '.png'
        if header.startswith((b'GIF87a', b'GIF89a')):
            return '.gif'
        if header.startswith(b'RIFF') and header[8:12] == b'WEBP':
            return '.webp'
    raise ValueError('Неподдерживаемый формат или HTML вместо файла')


def references(record):
    source = record.get('source_url', '')
    sources = {source}
    enrichment = record.get('enrichment', {})
    if enrichment.get('status') == 'MATCHED':
        sources.add(enrichment.get('source_url', ''))
    for kind in ('images', 'documents'):
        values = record.get(kind, [])
        if not isinstance(values, list):
            continue
        for value in values:
            url = value.get('url') if isinstance(value, dict) else value
            origin = value.get('source_url', source) if isinstance(value, dict) else source
            if kind == 'images':
                origin = record.get('provenance', {}).get('images', {}).get('source_url') or source
            yield kind, url, origin, sources


def permitted_host(origin, target, official_hosts):
    if origin == target:
        return True
    if origin not in official_hosts:
        return False
    domain = origin[4:] if origin.startswith('www.') else origin
    return target == domain or target.endswith('.' + domain)


def embed(archive, batch, destination):
    """Stream an index; keep at most MAX_ATTEMPTS results in memory.

    No shared blob store: all durable bytes are in the batch ZIP, so the existing
    explicit receipt/cleanup workflow remains valid.
    """
    root = batch.path.parent.parent
    from .directory import Directory
    official_hosts = {urlsplit(m['home_url']).netloc for m in Directory(root).manufacturers()}
    deadline = time.monotonic() + MAX_SECONDS
    cache, blobs = {}, set()
    stats = {'embedded': 0, 'skipped': 0, 'failed': 0, 'unique_files': 0,
             'file_bytes': 0, 'attempted_urls': 0}
    index_hash = hashlib.sha256()
    index_bytes = index_count = 0
    # Disk-backed index and one bounded temporary file, never a whole catalogue.
    with tempfile.TemporaryFile(dir=destination) as index:
        for row in batch.records():
            record = json.loads(row['payload'])
            for kind, raw_url, origin, sources in references(record):
                entry = {'record_id': row['record_id'], 'kind': kind, 'url': raw_url}
                try:
                    url = public_url(raw_url)
                    origin = public_url(origin)
                    if origin not in sources or not permitted_host(urlsplit(origin).netloc, urlsplit(url).netloc, official_hosts):
                        raise ValueError('Внешний файловый домен требует отдельной проверки')
                    if kind == 'images' and (forbidden(url) or forbidden(origin)):
                        raise ValueError('Изображения Olnisa запрещены')
                    if kind == 'documents' and not urlsplit(url).path.lower().endswith('.pdf'):
                        raise ValueError('Пока скачиваются только PDF-документы')
                    key = (kind, url)
                    if key in cache:
                        result = cache[key]
                    elif (stats['attempted_urls'] >= MAX_ATTEMPTS
                          or stats['file_bytes'] >= MAX_TOTAL or time.monotonic() >= deadline):
                        result = {'status': 'skipped', 'reason': 'Достигнут лимит партии по файлам, объёму или времени'}
                    else:
                        stats['attempted_urls'] += 1
                        allowed_origins = {'https://' + urlsplit(origin).netloc, 'https://' + urlsplit(url).netloc}
                        client = Client(url, root=root, stopped=lambda: time.monotonic() >= deadline,
                                        redirect_origins=allowed_origins)
                        try:
                            limit = min(MAX_FILE, MAX_TOTAL - stats['file_bytes'])
                            require_space(destination, limit + MIB)
                            with tempfile.TemporaryFile(dir=destination) as binary:
                                digest = hashlib.sha256()
                                def write(chunk):
                                    require_space(destination, len(chunk) + MIB)
                                    digest.update(chunk)
                                    binary.write(chunk)
                                meta = client.get(url, sink=write, max_bytes=limit)
                                binary.seek(0)
                                suffix = file_type(binary.read(32), kind)
                                sha = digest.hexdigest()
                                name = 'files/' + sha + suffix
                                if name not in blobs:
                                    binary.seek(0)
                                    with archive.open(name, 'w', force_zip64=True) as member:
                                        for chunk in iter(lambda: binary.read(CHUNK), b''):
                                            require_space(destination, len(chunk) + MIB)
                                            member.write(chunk)
                                    blobs.add(name)
                                    stats['unique_files'] += 1
                                    stats['file_bytes'] += meta['bytes']
                                result = {'status': 'embedded', 'path': name, 'sha256': sha,
                                          'bytes': meta['bytes'], 'final_url': client.last_url,
                                          'content_type': meta['content_type']}
                        except (TimeoutError, ConnectionError, http.client.HTTPException,
                                socket.gaierror, ssl.SSLError) as error:
                            result = {'status': 'failed', 'reason': 'Сетевая ошибка: ' + str(error)}
                        except (LowDiskSpace, OSError):
                            # Disk/write errors abort publication, not silently lose files.
                            raise
                        except (ValueError, Stopped) as error:
                            result = {'status': 'failed', 'reason': str(error) or 'Лимит времени'}
                        finally:
                            client.close()
                        cache[key] = result
                    entry.update(result)
                except ValueError as error:
                    entry.update(status='skipped', reason=str(error))
                stats[entry['status']] += 1
                line = (canonical_json(entry) + '\n').encode('utf-8')
                if len(line) > 65536 or index_bytes + len(line) > MAX_INDEX:
                    raise ValueError('Индекс вложений превышает лимит; используйте меньшую партию')
                require_space(destination, len(line) + MIB)
                index.write(line)
                index_hash.update(line)
                index_bytes += len(line)
                index_count += 1
        index.seek(0)
        with archive.open('attachments.jsonl', 'w', force_zip64=True) as member:
            for chunk in iter(lambda: index.read(CHUNK), b''):
                require_space(destination, len(chunk) + MIB)
                member.write(chunk)
    return {'attachments': 'embedded-with-report', 'attachment_summary': stats,
            'index_sha256': index_hash.hexdigest(), 'index_bytes': index_bytes,
            'index_count': index_count}


def verify(archive, manifest):
    """Bounded, independent verification, without extraction or network access."""
    size = manifest.get('index_bytes')
    if type(size) is not int or not 0 <= size <= MAX_INDEX:
        raise ValueError('Invalid attachment index size')
    if archive.getinfo('attachments.jsonl').file_size != size:
        raise ValueError('Attachment index size mismatch')
    digest, count, total = hashlib.sha256(), 0, 0
    expected = {}
    counts = {'embedded': 0, 'skipped': 0, 'failed': 0}
    with archive.open('attachments.jsonl') as stream:
        while line := stream.readline(65537):
            if len(line) > 65536:
                raise ValueError('Attachment index line too large')
            digest.update(line)
            total += len(line)
            count += 1
            entry = json.loads(line)
            status = entry.get('status')
            if status not in counts or entry.get('kind') not in ('images', 'documents') or not entry.get('record_id'):
                raise ValueError('Invalid attachment entry')
            counts[status] += 1
            if status == 'embedded':
                name, sha, size = entry.get('path', ''), entry.get('sha256', ''), entry.get('bytes')
                if (not re.fullmatch(r'files/[a-f0-9]{64}\.(pdf|jpg|png|gif|webp)', name)
                        or name.split('/')[1].split('.')[0] != sha
                        or type(size) is not int or not 0 < size <= MAX_FILE):
                    raise ValueError('Invalid attachment path/hash/size')
                if name in expected and expected[name] != (sha, size):
                    raise ValueError('Conflicting attachment entries')
                expected[name] = (sha, size)
                if len(expected) > MAX_ATTEMPTS:
                    raise ValueError('Too many embedded files')
    if (total != manifest['index_bytes'] or count != manifest.get('index_count')
            or digest.hexdigest() != manifest.get('index_sha256')):
        raise ValueError('Attachment index checksum/count mismatch')
    names = ['manifest.json', 'products.xml', 'attachments.jsonl', *expected]
    if sorted(archive.namelist()) != sorted(names):
        raise ValueError('Unexpected or duplicate archive members')
    if sum(size for _, size in expected.values()) > MAX_TOTAL:
        raise ValueError('Attachment total size limit exceeded')
    summary = manifest.get('attachment_summary', {})
    if (any(summary.get(k) != v for k, v in counts.items())
            or summary.get('unique_files') != len(expected)
            or summary.get('file_bytes') != sum(size for _, size in expected.values())):
        raise ValueError('Attachment summary mismatch')
    for name, (sha, size) in expected.items():
        if archive.getinfo(name).file_size != size:
            raise ValueError('Attachment size mismatch')
        digest, total = hashlib.sha256(), 0
        with archive.open(name) as stream:
            for chunk in iter(lambda: stream.read(CHUNK), b''):
                total += len(chunk)
                if total > size:
                    raise ValueError('Attachment exceeds declared size')
                digest.update(chunk)
        if total != size or digest.hexdigest() != sha:
            raise ValueError('Attachment checksum mismatch')
