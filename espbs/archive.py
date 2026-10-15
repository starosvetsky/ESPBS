"""Streaming XML/ZIP creation and offline verification. Never removes source records."""

import hashlib
import json
import os
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from xml.parsers import expat

from .storage import canonical_json

CHUNK = 64 * 1024
MAX_XML_BYTES = 8 * 1024**3


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


def xml_chunks(batch):
    yield f'<?xml version="1.0" encoding="utf-8"?>\n<products version="1" batch_id="{batch.id}">\n'.encode()
    for record in batch.records():
        node = ET.Element("product", record_id=record["record_id"], collected_at=record["collected_at"],
                          content_sha256=record["content_sha256"])
        xml_value(node, json.loads(record["payload"]))
        yield ET.tostring(node, encoding="utf-8").replace(b"\r", b"&#13;") + b"\n"
    yield b"</products>\n"


def verify_archive(path, max_xml_bytes=MAX_XML_BYTES):
    """Check ZIP CRC, XML structure, manifest identity, count and XML SHA-256.

    Hashes detect corruption, not authorship. No ZIP member is extracted to disk.
    DTDs and entities are rejected; the XML stream has an explicit size limit.
    """
    with zipfile.ZipFile(path) as archive:
        if sorted(archive.namelist()) != ["manifest.json", "products.xml"]:
            raise ValueError("Expected exactly manifest.json and products.xml")
        if archive.getinfo("manifest.json").file_size > 65536:
            raise ValueError("Manifest too large")
        manifest = json.loads(archive.read("manifest.json"))
        if not isinstance(manifest, dict) or manifest.get("format") != "espbs-batch" or manifest.get("version") != 1:
            raise ValueError("Unsupported archive format")
        if type(manifest.get("record_count")) is not int or manifest["record_count"] < 1:
            raise ValueError("Invalid record count")
        if type(manifest.get("xml_bytes")) is not int or not 0 < manifest["xml_bytes"] <= max_xml_bytes:
            raise ValueError("Invalid XML size")
        if archive.getinfo("products.xml").file_size != manifest["xml_bytes"]:
            raise ValueError("XML size mismatch")
        parser = expat.ParserCreate()
        depth = 0
        count = 0

        def reject(*args):
            raise ValueError("DTD and entities are forbidden")

        def start(name, attrs):
            nonlocal depth, count
            if depth == 0:
                if name != "products" or attrs.get("batch_id") != manifest.get("batch_id") or attrs.get("version") != "1":
                    raise ValueError("XML batch identity mismatch")
            elif depth == 1:
                if name != "product":
                    raise ValueError("Unexpected XML record")
                count += 1
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


def export_batch(batch, destination):
    from .disk import require_space, MIB
    # Check before sealing: refusal must leave an open batch writable.
    target = Path(destination) / (batch.id + '.zip')
    if not target.exists():
        xml_size = sum(len(chunk) for chunk in xml_chunks(batch))
        require_space(destination, xml_size + xml_size // 100 + 16 * MIB)
    batch.seal()
    info = batch.info()
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    final_path = destination / (batch.id + ".zip")
    if final_path.exists():
        verified = verify_archive(final_path)
        if verified["batch_id"] != batch.id or verified["record_count"] != info["record_count"]:
            raise ValueError("Existing archive belongs to another batch")
        expected = hashlib.sha256()
        for chunk in xml_chunks(batch):
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

                for chunk in xml_chunks(batch):
                    write(chunk)
            manifest = {"format": "espbs-batch", "version": 1, "batch_id": batch.id,
                        "created_at": info["created_at"], "record_count": info["record_count"],
                        "xml_sha256": digest.hexdigest(), "xml_bytes": total,
                        "attachments": "references-only"}
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
