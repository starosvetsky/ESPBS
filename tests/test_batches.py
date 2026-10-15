"""Synthetic fixtures exercise storage/export only. No manufacturer requests."""

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from unittest.mock import patch

from espbs.archive import export_batch, file_hash, verify_archive
from espbs.storage import Batch


def product(**overrides):
    return {"source": "fixture", "source_url": "https://example.invalid/item/1",
            "external_id": "1", "name": 'Товар <пример> & "тест"',
            "manufacturer": "Тестовый бренд", "model": "A-1",
            "attributes": {"Ток, А": "16", "Число": 16, "Есть": True},
            "documents": [{"url": "https://example.invalid/manual.pdf"}],
            "images": [], "optional": None, **overrides}


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.batch = Batch.create(self.root)
        self.output = self.root / "exports"

    def test_durable_save_without_export(self):
        self.batch.add(product())
        reopened = Batch(self.root, self.batch.id)
        self.assertEqual(reopened.info()["record_count"], 1)
        self.assertEqual(json.loads(next(reopened.records())["payload"]), product())

    def test_committed_record_survives_process_exit(self):
        script = (
            "import os,sys; from espbs.storage import Batch; "
            "Batch(sys.argv[1],sys.argv[2]).add("
            "{'source':'fixture','source_url':'https://example.invalid/1','name':'persisted'}); "
            "os._exit(7)"
        )
        result = subprocess.run([sys.executable, "-c", script, str(self.root), self.batch.id])
        self.assertEqual(result.returncode, 7)
        self.assertEqual(self.batch.info()["record_count"], 1)

    def test_repeat_update_and_source_identity(self):
        self.assertEqual(self.batch.add(product()), "inserted")
        self.assertEqual(self.batch.add(product()), "unchanged")
        self.assertEqual(self.batch.add(product(name="Изменено")), "updated")
        self.assertEqual(self.batch.add(product(source="another")), "inserted")
        self.assertEqual(self.batch.info()["record_count"], 2)

    def test_invalid_record_does_not_damage_previous(self):
        self.batch.add(product())
        for invalid in (product(name=""), product(name="bad\x00"), product(price=float("nan"))):
            with self.assertRaises(ValueError):
                self.batch.add(invalid)
        self.assertEqual(self.batch.info()["record_count"], 1)

    def test_fallback_identity_uses_source_url(self):
        self.batch.add(product(external_id=""))
        self.assertEqual(self.batch.add(product(external_id="")), "unchanged")

    def test_empty_batch_remains_open(self):
        with self.assertRaises(ValueError):
            export_batch(self.batch, self.output)
        self.assertEqual(self.batch.info()["state"], "OPEN")

    def test_roundtrip_and_offline_verification(self):
        self.batch.add(product(description="line 1\r\nline 2"))
        path = export_batch(self.batch, self.output)
        receipt = verify_archive(path)
        self.assertEqual(receipt["record_count"], 1)
        self.assertEqual(receipt["batch_id"], self.batch.id)
        self.assertEqual(self.batch.info()["state"], "ARCHIVED")
        self.assertEqual(self.batch.info()["archive_sha256"], file_hash(path))
        with zipfile.ZipFile(path) as archive:
            root = ET.fromstring(archive.read("products.xml"))
            node = root.find("product")
            self.assertEqual(node.find("field[@name='name']").text, product()["name"])
            self.assertEqual(node.find("field[@name='attributes']/field[@name='Число']").text, "16")
            self.assertEqual(node.find("field[@name='optional']").get("type"), "null")
            self.assertEqual(node.find("field[@name='description']").text, "line 1\r\nline 2")
        # Verification also works on a different computer without the batch database.
        result = subprocess.run([sys.executable, "-m", "espbs", "--data-dir", str(self.root / "missing"),
                                 "verify", str(path)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_sealed_batch_cannot_change(self):
        self.batch.add(product())
        self.batch.seal()
        with self.assertRaises(ValueError):
            self.batch.add(product(name="late update"))
        self.assertEqual(json.loads(next(self.batch.records())["payload"])["name"], product()["name"])

    def test_export_retry_keeps_same_archive(self):
        self.batch.add(product())
        path = export_batch(self.batch, self.output)
        before = path.read_bytes()
        self.assertEqual(export_batch(self.batch, self.output), path)
        self.assertEqual(before, path.read_bytes())
        self.assertEqual(self.batch.info()["record_count"], 1)

    def test_disk_failure_retains_records_and_allows_retry(self):
        self.batch.add(product())
        with patch("espbs.archive.zipfile.ZipFile", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                export_batch(self.batch, self.output)
        self.assertEqual(self.batch.info()["state"], "SEALED")
        self.assertEqual(self.batch.info()["record_count"], 1)
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertEqual(verify_archive(export_batch(self.batch, self.output))["record_count"], 1)

    def test_published_archive_survives_metadata_failure(self):
        self.batch.add(product())
        with patch.object(self.batch, "mark_archived", side_effect=OSError("database unavailable")):
            with self.assertRaises(OSError):
                export_batch(self.batch, self.output)
        self.assertEqual(self.batch.info()["state"], "SEALED")
        path = export_batch(self.batch, self.output)
        self.assertTrue(path.exists())
        self.assertEqual(self.batch.info()["state"], "ARCHIVED")

    def rewrite_archive(self, path, xml=None, manifest_update=None):
        with zipfile.ZipFile(path) as archive:
            original_xml = archive.read("products.xml")
            manifest = json.loads(archive.read("manifest.json"))
        data = original_xml if xml is None else xml
        manifest.update(manifest_update or {})
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("products.xml", data)
            archive.writestr("manifest.json", json.dumps(manifest))

    def test_corruption_and_count_mismatch_rejected(self):
        self.batch.add(product())
        path = export_batch(self.batch, self.output)
        self.rewrite_archive(path, manifest_update={"xml_sha256": "0" * 64})
        with self.assertRaises(ValueError):
            verify_archive(path)
        with self.assertRaises(ValueError):
            export_batch(self.batch, self.output)
        self.assertEqual(self.batch.info()["record_count"], 1)

    def test_wrong_count_rejected(self):
        self.batch.add(product())
        path = export_batch(self.batch, self.output)
        self.rewrite_archive(path, manifest_update={"record_count": 99})
        with self.assertRaisesRegex(ValueError, "count mismatch"):
            verify_archive(path)

    def test_dtd_is_rejected_even_with_matching_hash(self):
        self.batch.add(product())
        path = export_batch(self.batch, self.output)
        xml = f'<!DOCTYPE products [<!ENTITY x "unsafe">]><products version="1" batch_id="{self.batch.id}"><product>&x;</product></products>'.encode()
        self.rewrite_archive(path, xml, {"xml_bytes": len(xml), "xml_sha256": hashlib.sha256(xml).hexdigest()})
        with self.assertRaisesRegex(ValueError, "DTD"):
            verify_archive(path)

    def test_size_limit(self):
        self.batch.add(product())
        path = export_batch(self.batch, self.output)
        with self.assertRaises(ValueError):
            verify_archive(path, max_xml_bytes=1)

    def test_partial_jsonl_import_is_durable(self):
        source = self.root / "input.jsonl"
        source.write_text(json.dumps(product()) + '\n{"broken":\n', encoding="utf-8")
        run = subprocess.run([sys.executable, "-m", "espbs", "--data-dir", str(self.root),
                              "ingest", self.batch.id, str(source)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(run.returncode, 1)
        self.assertIn("Line 2", run.stderr)
        self.assertEqual(self.batch.info()["record_count"], 1)

    def test_batch_id_cannot_escape_storage_directory(self):
        with self.assertRaises(ValueError):
            Batch(self.root, "../../other")


if __name__ == "__main__":
    unittest.main()
