"""Streaming XML/ZIP creation and offline verification. Never removes source records."""

import hashlib
import json
import os
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from xml.parsers import expat

from .storage import Batch, canonical_json

CHUNK = 64 * 1024
MAX_XML_BYTES = 8 * 1024**3
MAX_STREAM_RECORDS = 25  # Version 3 format limit; verifier remains stdlib-only.


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def xml_value(node, value):
    if isinstance(value, dict):
        node.set("type", "object")
        for key, item in sorted(value.items()):
            xml_value(ET.SubElement(node, "field", name=key), item)
    elif isinstance(value, list):
        node.set("type", "array")
        for item in value:
            xml_value(ET.SubElement(node, "item"), item)
    elif value is None:
        node.set("type", "null")
    elif isinstance(value, bool):
        node.set("type", "boolean")
        node.text = "true" if value else "false"
    elif isinstance(value, (int, float)):
        node.set("type", "number")
        node.text = canonical_json(value)
    else:
        node.set("type", "string")
        node.text = value


def stream_snapshot(batch):
    """Validate a registered snapshot before assigning journal identities."""
    from .jobs import Job
    root = batch.path.parent.parent
    if not (root / 'jobs' / (batch.id + '.sqlite3')).exists():
        return None
    config = Job(root, batch.id).info()
    bounds = config.get('stream_range')
    if bounds is None:
        return None
    from .stream_parts import fingerprint
    parent = Job(root, config['parent_id'])
    with parent.db() as db:
        saved = db.execute('SELECT * FROM stream_parts WHERE child_id=?', (batch.id,)).fetchone()
    if (not saved or not saved['ready'] or bounds !=
            {'after': saved['start_seq'], 'through': saved['end_seq']}):
        raise ValueError('Stream part is not published or range differs')
    if not 0 < bounds['through'] - bounds['after'] <= MAX_STREAM_RECORDS:
        raise ValueError('Invalid stream snapshot size')
    rows = [row for row in Batch(root, parent.id).changes(bounds['after'], MAX_STREAM_RECORDS)
            if row['seq'] <= bounds['through']]
    if (len(rows) != saved['record_count'] or fingerprint(rows) != saved['fingerprint']
            or [r['seq'] for r in rows] != list(range(bounds['after'] + 1, bounds['through'] + 1))
            or fingerprint(list(batch.records())) != fingerprint(sorted(rows, key=lambda r: r['record_id']))):
        raise ValueError('Stream snapshot does not match journal range')
    return {'source_batch_id': parent.id, 'stream_range': bounds,
            'sequences': {r['record_id']: r['seq'] for r in rows}}


def xml_chunks(batch, snapshot=None):
    attrs = {'version': '1', 'batch_id': batch.id}
    if snapshot:
        attrs.update(version='3', source_batch_id=snapshot['source_batch_id'],
                     after=str(snapshot['stream_range']['after']),
                     through=str(snapshot['stream_range']['through']))
    opening = ET.tostring(ET.Element('products', attrs), encoding='utf-8').replace(b' />', b'>')
    yield b'<?xml version="1.0" encoding="utf-8"?>\n' + opening + b'\n'
    for record in batch.records():
        node = ET.Element("product", record_id=record["record_id"], collected_at=record["collected_at"],
                          content_sha256=record["content_sha256"])
        if snapshot:
            node.set('journal_seq', str(snapshot['sequences'][record['record_id']]))
        xml_value(node, json.loads(record["payload"]))
        yield ET.tostring(node, encoding="utf-8").replace(b"\r", b"&#13;") + b"\n"
    yield b"</products>\n"


def verify_archive(path, max_xml_bytes=MAX_XML_BYTES):
    """Check ZIP CRC, XML structure, manifest identity, count and XML SHA-256.

    Hashes detect corruption, not authorship. No ZIP member is extracted to disk.
    DTDs and entities are rejected; the XML stream has an explicit size limit.
    """
    with zipfile.ZipFile(path) as archive:
        if 'manifest.json' not in archive.namelist():
            raise ValueError("Missing manifest.json")
        if archive.getinfo("manifest.json").file_size > 65536:
            raise ValueError("Manifest too large")
        manifest = json.loads(archive.read("manifest.json"))
        if not isinstance(manifest, dict) or manifest.get("format") != "espbs-batch" or manifest.get("version") not in (1, 2, 3):
            raise ValueError("Unsupported archive format")
        snapshot = manifest['version'] == 3
        if snapshot:
            from uuid import UUID
            bounds = manifest.get('stream_range')
            if (not isinstance(bounds, dict) or set(bounds) != {'after', 'through'}
                    or any(type(bounds[k]) is not int for k in bounds)
                    or not 0 <= bounds['after'] < bounds['through'] <= 9223372036854775807
                    or bounds['through'] - bounds['after'] > MAX_STREAM_RECORDS
                    or manifest.get('record_count') != bounds['through'] - bounds['after']):
                raise ValueError('Invalid stream range')
            source = manifest.get('source_batch_id')
            if not isinstance(source, str) or str(UUID(source)) != source or source == manifest.get('batch_id'):
                raise ValueError('Invalid stream source batch')
        elif 'stream_range' in manifest or 'source_batch_id' in manifest:
            raise ValueError('Stream metadata requires archive version 3')
        if manifest['version'] == 1 or (snapshot and manifest.get('attachments') == 'references-only'):
            if sorted(archive.namelist()) != ["manifest.json", "products.xml"]:
                raise ValueError("Expected exactly manifest.json and products.xml")
        else:
            from .attachments import verify
            if manifest.get('attachments') != 'embedded-with-report':
                raise ValueError('Invalid attachment mode')
            verify(archive, manifest)
        if type(manifest.get("record_count")) is not int or manifest["record_count"] < 1:
            raise ValueError("Invalid record count")
        if type(manifest.get("xml_bytes")) is not int or not 0 < manifest["xml_bytes"] <= max_xml_bytes:
            raise ValueError("Invalid XML size")
        if archive.getinfo("products.xml").file_size != manifest["xml_bytes"]:
            raise ValueError("XML size mismatch")
        parser = expat.ParserCreate()
        depth = 0
        count = 0
        sequences, identities = set(), set()

        def reject(*args):
            raise ValueError("DTD and entities are forbidden")

        def start(name, attrs):
            nonlocal depth, count
            if depth == 0:
                if name != "products" or attrs.get("batch_id") != manifest.get("batch_id") or attrs.get("version") != ("3" if snapshot else "1"):
                    raise ValueError("XML batch identity mismatch")
                if snapshot and (attrs.get('source_batch_id') != source
                        or attrs.get('after') != str(bounds['after'])
                        or attrs.get('through') != str(bounds['through'])):
                    raise ValueError('XML stream range mismatch')
            elif depth == 1:
                if name != "product":
                    raise ValueError("Unexpected XML record")
                count += 1
                if snapshot:
                    seq = attrs.get('journal_seq', '')
                    if not seq.isascii() or not seq.isdecimal() or len(seq) > 19:
                        raise ValueError('Invalid journal sequence')
                    seq = int(seq)
                    identity = attrs.get('record_id')
                    if (not bounds['after'] < seq <= bounds['through'] or seq in sequences
                            or not identity or identity in identities):
                        raise ValueError('Duplicate or out-of-range stream record')
                    sequences.add(seq)
                    identities.add(identity)
            depth += 1
            if depth > 64:
                raise ValueError("XML nesting limit exceeded")

        def end(name):
            nonlocal depth
            depth -= 1

        parser.StartDoctypeDeclHandler = reject
        parser.EntityDeclHandler = reject
        parser.ExternalEntityRefHandler = reject
        parser.StartElementHandler = start
        parser.EndElementHandler = end
        digest = hashlib.sha256()
        total = 0
        with archive.open("products.xml") as stream:
            for chunk in iter(lambda: stream.read(CHUNK), b""):
                total += len(chunk)
                if total > max_xml_bytes:
                    raise ValueError("XML size limit exceeded")
                digest.update(chunk)
                parser.Parse(chunk, False)
        parser.Parse(b"", True)
        if total != manifest["xml_bytes"] or digest.hexdigest() != manifest.get("xml_sha256"):
            raise ValueError("XML checksum mismatch")
        if count != manifest["record_count"]:
            raise ValueError("Record count mismatch")
    return {**manifest, "archive_sha256": file_hash(path)}


def export_batch(batch, destination, include_files=False):
    from .jobs import worker_lock
    with worker_lock(batch.path.with_suffix('.maintenance.lock')):
        return _export_batch(batch, destination, include_files)


def _export_batch(batch, destination, include_files=False):
    from .jobs import Job
    from .retention import receipt
    root = batch.path.parent.parent
    if (root / 'jobs' / (batch.id + '.sqlite3')).exists():
        saved = receipt(Job(root, batch.id))
        if saved and saved['state'] in ('CLEANING', 'CLEANED'):
            raise ValueError('Batch cleanup has started; archive cannot be recreated')
    from .disk import require_space, MIB
    snapshot = stream_snapshot(batch)
    # Check before sealing: refusal must leave an open batch writable.
    target = Path(destination) / (batch.id + '.zip')
    if not target.exists():
        xml_size = sum(len(chunk) for chunk in xml_chunks(batch, snapshot))
        require_space(destination, xml_size + xml_size // 100 + 16 * MIB)
    batch.seal()
    info = batch.info()
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    final_path = destination / (batch.id + ".zip")
    if final_path.exists():
        verified = verify_archive(final_path)
        if include_files and verified.get('attachments') != 'embedded-with-report':
            raise ValueError('Архив ссылок уже создан; он не перезаписывается. Используйте новую партию.')
        if verified["batch_id"] != batch.id or verified["record_count"] != info["record_count"]:
            raise ValueError("Existing archive belongs to another batch")
        expected = hashlib.sha256()
        for chunk in xml_chunks(batch, snapshot):
            expected.update(chunk)
        if verified["xml_sha256"] != expected.hexdigest():
            raise ValueError("Existing archive does not match the batch records")
        if info["archive_sha256"] and info["archive_sha256"] != verified["archive_sha256"]:
            raise ValueError("Existing archive differs from the saved checksum")
        batch.mark_archived(verified["archive_sha256"])
        return final_path
    fd, temporary = tempfile.mkstemp(prefix=batch.id + "-", suffix=".partial", dir=destination)
    os.close(fd)
    try:
        digest = hashlib.sha256()
        total = 0
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            with archive.open("products.xml", "w", force_zip64=True) as stream:
                def write(data):
                    nonlocal total
                    require_space(destination, len(data) + MIB)
                    total += len(data)
                    if total > MAX_XML_BYTES:
                        raise ValueError("Batch XML exceeds size limit; use smaller batches")
                    digest.update(data)
                    stream.write(data)

                for chunk in xml_chunks(batch, snapshot):
                    write(chunk)
            manifest = {"format": "espbs-batch", "version": 1, "batch_id": batch.id,
                        "created_at": info["created_at"], "record_count": info["record_count"],
                        "xml_sha256": digest.hexdigest(), "xml_bytes": total,
                        "attachments": "references-only"}
            if include_files:
                from .attachments import embed
                manifest.update(embed(archive, batch, destination))
                manifest['version'] = 2
            if snapshot:
                manifest.update(version=3, source_batch_id=snapshot['source_batch_id'],
                                stream_range=snapshot['stream_range'])
            archive.writestr("manifest.json", canonical_json(manifest).encode("utf-8"))
        verified = verify_archive(temporary)
        with open(temporary, "rb+") as stream:
            os.fsync(stream.fileno())
        # A second exporter must never overwrite an already published archive.
        # Link publication is atomic and no-clobber on the same filesystem.
        os.link(temporary, final_path)
        if os.name != "nt":
            directory_fd = os.open(destination, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        batch.mark_archived(verified["archive_sha256"])
        return final_path
    finally:
        Path(temporary).unlink(missing_ok=True)
