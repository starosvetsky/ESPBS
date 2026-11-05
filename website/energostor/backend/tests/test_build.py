"""Сборка производной БД: дедупликация, снимки, атомарность, статистика."""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import ROOT  # noqa: F401
from espbs_catalog import store, taxonomy as tx
from espbs_catalog.store import BuildError, build
from fixtures import make_batch, product

AD_TAIL = (" – артикул товара бренда {brand}. Купите оптом в компании Олписа "
           "по телефону +7 (812) 000-00-00.")


def payload(name, *, brand="", mpn="", url="", description="", **kwargs):
    return product(name, brand=brand, mpn=mpn, url=url,
                   description=(description or f"Описание {name}.") + AD_TAIL.format(brand=brand or "—"),
                   **kwargs)


class BuildTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="catalog-test-"))
        self.source = self.tmp / "source"
        self.batches = self.source / "batches"
        self.batches.mkdir(parents=True)
        self.dest = self.tmp / "catalog.sqlite3"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- helpers ---------------------------------------------------------
    def batch(self, name, records, created="2026-01-01T00:00:00+00:00"):
        return make_batch(self.batches / name, records, created)

    def build(self, **kwargs):
        return build(self.source, self.dest, **kwargs)

    def rows(self, sql, params=()):
        conn = sqlite3.connect(self.dest)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(row) for row in conn.execute(sql, params)]
        finally:
            conn.close()

    # -- дедупликация ----------------------------------------------------
    def test_mpn_case_and_punctuation_are_exact(self):
        self.batch('exact.sqlite3', [{'payload': payload('Part', brand='B', mpn=x)} for x in ['Ab-1', 'AB-1', '-AB-1']])
        self.build()
        self.assertEqual(len(self.rows('SELECT id FROM products')), 3)

    def test_same_record_without_mpn_repeats_safely(self):
        for name, stamp, title in [('a.sqlite3', '2026-01-01T00:00:00Z', 'Old'), ('b.sqlite3', '2026-02-01T00:00:00Z', 'New')]:
            self.batch(name, [{'record_id': 'same-exact-record', 'payload': payload(title, brand='B'), 'collected_at': stamp}])
        self.build()
        rows=self.rows('SELECT name FROM products')
        self.assertEqual(rows, [{'name':'New'}])

    def test_late_old_snapshot_supplies_only_missing_fields(self):
        self.batch('a.sqlite3', [{'payload':payload('New',brand='B',mpn='ABC1'), 'collected_at':'2026-05-01T00:00:00Z'}], created='2026-01-01T00:00:00Z')
        self.batch('b.sqlite3', [{'payload':payload('Old',brand='B',mpn='ABC1',images=['https://example.org/device.jpg']), 'collected_at':'2026-01-01T00:00:00Z'}], created='2026-06-01T00:00:00Z')
        self.build()
        row=self.rows('SELECT name,images FROM products')[0]
        self.assertEqual(row['name'],'New')
        self.assertEqual(json.loads(row['images']),['https://example.org/device.jpg'])

    def test_destination_cannot_replace_source_batch(self):
        source=self.batch('a.sqlite3', [{'payload':payload('Part',brand='B',mpn='ABC1')}])
        before=source.read_bytes()
        with self.assertRaises(BuildError):build(self.source,source)
        self.assertEqual(source.read_bytes(),before)

    def test_large_technical_specification_is_preserved(self):
        attrs={f'Parameter {n}': ['Technical value ' * 60] for n in range(55)}
        self.batch('specs.sqlite3',[{'payload':payload('Device',brand='B',mpn='ABC1',attributes=attrs)}])
        self.build()
        actual=json.loads(self.rows('SELECT attributes FROM products')[0]['attributes'])
        self.assertEqual(len(actual),55)
        self.assertGreater(len(actual[0]['value']),400)

    def test_same_brand_and_mpn_merge_newest_snapshot_wins(self):
        self.batch("a.sqlite3", [
            {"payload": payload("Выключатель 16 А", brand="Schneider Electric", mpn="A9F04116",
                                description="Старое описание 16 А."),
             "collected_at": "2026-01-01T10:00:00Z"},
        ])
        self.batch("b.sqlite3", [
            {"payload": payload("Выключатель 16 А", brand="schneider electric", mpn=" A9F04116 ",
                                description="Новое описание 16 А."),
             "collected_at": "2026-02-01T10:00:00Z"},
        ])

        stats = self.build()
        products = self.rows("SELECT * FROM products")
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]["description"], "Новое описание 16 А.")
        self.assertEqual(stats.updated, 1)
        self.assertEqual(stats.inserted, 1)

        audit = self.rows("SELECT * FROM audit_records ORDER BY collected_at")
        self.assertEqual(len(audit), 2)
        self.assertEqual({row["product_id"] for row in audit}, {products[0]["id"]})
        self.assertEqual([row["outcome"] for row in audit], ["inserted", "updated"])

    def test_older_snapshot_never_overwrites_newer(self):
        # «старая» партия обрабатывается последней по имени, но снимок в ней древнее
        self.batch("a-new.sqlite3", [
            {"payload": payload("Реле 24 В", brand="Schneider Electric", mpn="RXM2AB2BD",
                                description="Свежее описание."),
             "collected_at": "2026-05-01T10:00:00Z"},
        ], created="2026-05-01T00:00:00+00:00")
        self.batch("z-old.sqlite3", [
            {"payload": payload("Реле 24 В", brand="Schneider Electric", mpn="RXM2AB2BD",
                                description="Устаревшее описание."),
             "collected_at": "2025-01-01T10:00:00Z"},
        ], created="2026-06-01T00:00:00+00:00")

        stats = self.build()
        products = self.rows("SELECT description FROM products")
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]["description"], "Свежее описание.")
        self.assertEqual(stats.duplicates, 1)

    def test_records_without_mpn_are_never_merged(self):
        self.batch("a.sqlite3", [
            {"payload": payload("Кабель силовой", brand="DKC", url="https://example.org/a"),
             "collected_at": "2026-01-01T10:00:00Z"},
            {"payload": payload("Кабель силовой", brand="DKC", url="https://example.org/b"),
             "collected_at": "2026-01-01T10:00:00Z"},
        ])
        self.build()
        products = self.rows("SELECT id, dedupe_key FROM products")
        self.assertEqual(len(products), 2)
        self.assertTrue(all(row["dedupe_key"] is None for row in products))
        self.assertEqual(len({row["id"] for row in products}), 2)

    def test_same_mpn_different_brand_is_not_merged(self):
        self.batch("a.sqlite3", [
            {"payload": payload("Клемма 2.5", brand="Phoenix Contact", mpn="UT 2,5"),
             "collected_at": "2026-01-01T10:00:00Z"},
            {"payload": payload("Клемма 2.5", brand="IEK", mpn="UT 2,5"),
             "collected_at": "2026-01-01T10:00:00Z"},
        ])
        self.build()
        self.assertEqual(len(self.rows("SELECT id FROM products")), 2)

    def test_brand_without_mpn_is_not_merged(self):
        self.batch("a.sqlite3", [
            {"payload": payload("Шкаф напольный", brand="DKC", url="https://example.org/1"),
             "collected_at": "2026-01-01T10:00:00Z"},
            {"payload": payload("Шкаф напольный", brand="DKC", url="https://example.org/2"),
             "collected_at": "2026-01-01T10:00:00Z"},
        ])
        self.build()
        self.assertEqual(len(self.rows("SELECT id FROM products")), 2)

    def test_product_ids_are_stable_between_builds(self):
        self.batch("a.sqlite3", [
            {"payload": payload("Товар", brand="Brand", mpn="AB-100"),
             "collected_at": "2026-01-01T10:00:00Z"},
        ])
        self.build()
        first = [row["id"] for row in self.rows("SELECT id FROM products ORDER BY id")]

        self.dest.unlink()
        self.build()
        second = [row["id"] for row in self.rows("SELECT id FROM products ORDER BY id")]
        self.assertEqual(first, second)

    # -- категории -------------------------------------------------------
    def test_category_from_known_source_url(self):
        url = ("https://olnisa.ru/manufacturers/schneider/"
               "nizkovoltnoe-oborudovanie/modulnyj-avtomaticheskij-vyklyuchatel-avtomat/")
        self.batch("a.sqlite3", [
            {"payload": payload("Автомат 16 А", brand="Schneider Electric", mpn="A1", url=url),
             "collected_at": "2026-01-01T10:00:00Z"},
        ])
        self.build()
        row = self.rows("SELECT parent, child FROM products")[0]
        self.assertEqual(row["child"], "lv-breakers")
        self.assertEqual(row["parent"], "low-voltage")

    def test_unknown_url_uses_brand_rules(self):
        self.batch("a.sqlite3", [
            {"payload": payload("Коммутатор DES-3200-28", brand="D-Link", mpn="DES-3200-28",
                                url="https://dlink.ru/ru/products/1/des-3200-28.html"),
             "collected_at": "2026-01-01T10:00:00Z"},
            {"payload": payload("Странный товар", brand="NoName", mpn="ZZ-1",
                                url="https://example.org/x/y/z"),
             "collected_at": "2026-01-01T10:00:00Z"},
        ])
        self.build()
        rows = {row["mpn"]: row for row in self.rows("SELECT mpn, parent, child FROM products")}
        self.assertEqual(rows["DES-3200-28"]["child"], "nw-switches")
        self.assertEqual(rows["DES-3200-28"]["parent"], "network")
        self.assertEqual(rows["ZZ-1"]["child"], "ot-misc")

    def test_parent_and_child_counts_match_products(self):
        self.batch("a.sqlite3", [
            {"payload": payload("Автомат 16 А", brand="Schneider Electric", mpn="A1",
                                url="https://x/nizkovoltnoe-oborudovanie/modulnyj-avtomaticheskij-vyklyuchatel-avtomat/"),
             "collected_at": "2026-01-01T10:00:00Z"},
            {"payload": payload("Автомат 25 А", brand="Schneider Electric", mpn="A2",
                                url="https://x/nizkovoltnoe-oborudovanie/modulnyj-avtomaticheskij-vyklyuchatel-avtomat/"),
             "collected_at": "2026-01-01T10:00:00Z"},
        ])
        self.build()
        child = self.rows("SELECT products FROM children WHERE slug='lv-breakers'")[0]["products"]
        parent = self.rows("SELECT products FROM parents WHERE slug='low-voltage'")[0]["products"]
        self.assertEqual(child, 2)
        self.assertEqual(parent, 2)

    # -- публичность полей ----------------------------------------------
    def test_products_table_has_no_source_columns(self):
        self.batch("a.sqlite3", [
            {"payload": payload("Товар", brand="Brand", mpn="AB-100"),
             "collected_at": "2026-01-01T10:00:00Z"},
        ])
        self.build()
        conn = sqlite3.connect(self.dest)
        try:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(products)")}
        finally:
            conn.close()
        for forbidden in ("source", "source_url", "provenance", "enrichment",
                          "record_id", "payload", "batch", "external_id"):
            self.assertNotIn(forbidden, columns)

    def test_audit_table_keeps_record_identity_internally(self):
        self.batch("a.sqlite3", [{"payload": payload("Товар", brand="Brand", mpn="AB-100"),
                                  "collected_at": "2026-01-01T10:00:00Z"}])
        self.build()
        audit = self.rows("SELECT record_id, product_id, outcome FROM audit_records")
        self.assertEqual(len(audit), 1)
        self.assertTrue(audit[0]["record_id"].startswith("a-"))
        self.assertEqual(audit[0]["outcome"], "inserted")

    # -- устойчивость ----------------------------------------------------
    def test_atomic_failure_keeps_previous_catalog(self):
        self.batch("a.sqlite3", [{"payload": payload("Товар", brand="Brand", mpn="AB-100"),
                                  "collected_at": "2026-01-01T10:00:00Z"}])
        self.build()
        before = self.dest.read_bytes()

        self.batch("b.sqlite3", [{"payload": payload("Товар 2", brand="Brand", mpn="AB-200"),
                                  "collected_at": "2026-02-01T10:00:00Z"}])

        calls = {"n": 0}
        original = store._upsert

        def failing(conn, row):
            calls["n"] += 1
            if calls["n"] > 1:
                raise RuntimeError("диск закончился")
            return original(conn, row)

        with mock.patch.object(store, "_upsert", side_effect=failing):
            with self.assertRaises(RuntimeError):
                self.build()

        self.assertEqual(self.dest.read_bytes(), before, "целевая БД изменилась при ошибке")
        leftovers = list(self.tmp.glob(".catalog.sqlite3.*.tmp"))
        self.assertEqual(leftovers, [], "временный файл не удалён")

    def test_corrupt_batch_raises_and_keeps_destination(self):
        self.batch("a.sqlite3", [{"payload": payload("Товар", brand="Brand", mpn="AB-100"),
                                  "collected_at": "2026-01-01T10:00:00Z"}])
        self.build()
        before = self.dest.read_bytes()

        (self.batches / "b.sqlite3").write_bytes(b"not a sqlite database at all")
        with self.assertRaises((sqlite3.Error, BuildError)):
            self.build()
        self.assertEqual(self.dest.read_bytes(), before)
        self.assertEqual(list(self.tmp.glob(".catalog.sqlite3.*.tmp")), [])

    def test_source_is_never_modified(self):
        path = self.batch("a.sqlite3", [
            {"payload": payload("Товар", brand="Brand", mpn="AB-100"),
             "collected_at": "2026-01-01T10:00:00Z"},
        ])
        before = path.read_bytes()
        self.build()
        self.assertEqual(path.read_bytes(), before)

    def test_invalid_payload_is_skipped_not_fatal(self):
        path = self.batch("a.sqlite3", [{"payload": payload("Товар", brand="Brand", mpn="AB-100"),
                                         "collected_at": "2026-01-01T10:00:00Z"}])
        with sqlite3.connect(path) as conn:
            conn.execute(
                "INSERT INTO records(record_id, source, external_id, payload, content_sha256, collected_at) "
                "VALUES ('broken','test','broken','{not json', '0', '2026-01-01T00:00:00Z')"
            )
        stats = self.build()
        self.assertEqual(stats.skipped, 1)
        self.assertEqual(stats.raw_records, 2)
        outcomes = {row["outcome"] for row in self.rows("SELECT outcome FROM audit_records")}
        self.assertIn("skipped", outcomes)

    def test_limit_stops_early(self):
        self.batch("a.sqlite3", [
            {"payload": payload(f"Товар {i}", brand="Brand", mpn=f"AB-{i}"),
             "collected_at": "2026-01-01T10:00:00Z"} for i in range(5)
        ])
        stats = self.build(limit=2)
        self.assertEqual(stats.raw_records, 2)
        self.assertEqual(len(self.rows("SELECT id FROM products")), 2)

    def test_meta_counts(self):
        self.batch("a.sqlite3", [
            {"payload": payload("Товар", brand="Brand", mpn="AB-100"),
             "collected_at": "2026-01-01T10:00:00Z"},
            {"payload": payload("Товар без артикула", brand="Brand", url="https://e/1"),
             "collected_at": "2026-01-01T10:00:00Z"},
        ])
        stats = self.build()
        conn = sqlite3.connect(self.dest)
        try:
            meta = dict(conn.execute("SELECT key, value FROM meta"))
        finally:
            conn.close()
        self.assertEqual(meta["raw_records"], "2")
        self.assertEqual(meta["unique_products"], "2")
        self.assertEqual(meta["duplicates"], "0")
        self.assertEqual(meta["batches"], "1")
        self.assertEqual(stats.inserted, 2)

    def test_brand_rollup(self):
        self.batch("a.sqlite3", [
            {"payload": payload("Товар", brand="Schneider Electric", mpn="A1"),
             "collected_at": "2026-01-01T10:00:00Z"},
            {"payload": payload("Товар 2", brand="Schneider Electric", mpn="A2"),
             "collected_at": "2026-01-01T10:00:00Z"},
            {"payload": payload("Товар 3", brand="DKC", mpn="D1"),
             "collected_at": "2026-01-01T10:00:00Z"},
        ])
        self.build()
        brands = {row["title"]: row["products"] for row in self.rows("SELECT title, products FROM brands")}
        self.assertEqual(brands, {"Schneider Electric": 2, "DKC": 1})


if __name__ == "__main__":
    unittest.main()
