"""HTTP API: фильтры, поиск, пагинация, отдача карточек и защита данных."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from tests import ROOT  # noqa: F401
from espbs_catalog.store import build
from fixtures import make_batch, product
from server import serve

SECRET_SOURCE_URL = "https://secret-host.example/manufacturers/hidden/product-1/"
SECRET_BATCH = "SECRET-BATCH-2026"


def payload(name, *, brand="", mpn="", url="", description="", **kwargs):
    return product(name, brand=brand, mpn=mpn, url=url, description=description, **kwargs)


def make_catalog(directory: Path) -> Path:
    batches = directory / "source" / "batches"
    records = [
        {"payload": payload(
            "Выключатель автоматический 3P 63 А", brand="Schneider Electric", mpn="A9F04363",
            url="https://secret-host.example/manufacturers/x/nizkovoltnoe-oborudovanie/"
                "modulnyj-avtomaticheskij-vyklyuchatel-avtomat/",
            description="Выключатель автоматический 3P 63 А, характеристика C, 6 кА. "
                        "Купите оптом в компании Олписа по телефону +7 (812) 000-00-00.",
            attributes={"Номинальный ток": "63 А", "Полюсов": "3"},
            images=["https://olnisa.ru/upload/secret.jpg", "https://cdn.example.org/a.jpg"],
            documents=[{"name": "Паспорт", "url": "https://cdn.example.org/passport.pdf"}],
            extra={"provenance": {"batch": SECRET_BATCH, "parser": "secret-parser"}},
        ), "collected_at": "2026-03-01T10:00:00Z"},
        {"payload": payload(
            "Дифавтомат 2P 32 А", brand="Schneider Electric", mpn="A9R72232",
            url="https://secret-host.example/manufacturers/x/"
                "avtomaticheskij-vyklyuchatel-differenczialnogo-toka-difavtomat-avdt/",
            description="Дифференциальный автомат 2P 32 А, 30 мА.",
        ), "collected_at": "2026-03-01T10:00:00Z"},
        {"payload": payload(
            "Реле промежуточное 24 В", brand="Schneider Electric", mpn="RXM2AB2BD",
            url="https://secret-host.example/manufacturers/x/rele/",
            description="Реле промежуточное 2 переключающих контакта.",
        ), "collected_at": "2026-03-01T10:00:00Z"},
        {"payload": payload(
            "Коммутатор D-Link DES-3200-28", brand="D-Link", mpn="DES-3200-28",
            url="https://dlink.ru/ru/products/1/des-3200-28.html",
            description="Коммутатор управляемый, 24 порта.",
        ), "collected_at": "2026-03-02T10:00:00Z"},
        {"payload": payload(
            "Точка доступа Eltex WEP-2ac", brand="Eltex", mpn="WEP-2ac",
            url="https://eltex-co.ru/catalog/wep-2ac/",
            description="Точка доступа Wi-Fi 6.",
        ), "collected_at": "2026-03-02T10:00:00Z"},
        {"payload": payload(
            "Кабель силовой без артикула", brand="DKC",
            url="https://secret-host.example/manufacturers/x/kabelnye-sborki/",
            description="Кабель силовой 3×2.5.",
        ), "collected_at": "2026-03-03T10:00:00Z"},
    ]
    make_batch(batches / "2026-03.sqlite3", records, "2026-03-01T00:00:00+00:00")

    # второй снимок: тот же товар с более новым описанием
    update = [
        {"payload": payload(
            "Выключатель автоматический 3P 63 А", brand="Schneider Electric", mpn="A9F04363",
            url="https://secret-host.example/manufacturers/x/nizkovoltnoe-oborudovanie/"
                "modulnyj-avtomaticheskij-vyklyuchatel-avtomat/",
            description="Выключатель автоматический 3P 63 А, характеристика C, 6 кА, Acti9.",
            attributes={"Номинальный ток": "63 А"},
        ), "collected_at": "2026-04-01T10:00:00Z"},
    ]
    make_batch(batches / "2026-04.sqlite3", update, "2026-04-01T00:00:00+00:00")

    dest = directory / "catalog.sqlite3"
    build(directory / "source", dest, log=None)
    return dest


class ApiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["CATALOG_QUIET"] = "1"
        cls.tmp = Path(tempfile.mkdtemp(prefix="catalog-api-"))
        cls.db = make_catalog(cls.tmp)
        cls.httpd = serve(cls.db, "127.0.0.1", 0)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # -- helpers ---------------------------------------------------------
    def get(self, path, params=None, expect=200):
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                body = response.read().decode("utf-8")
                status = response.status
                headers = dict(response.headers)
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8")
            status = error.code
            headers = dict(error.headers)
        self.assertEqual(status, expect, msg=f"{path} -> {status}: {body[:300]}")
        return json.loads(body), headers

    def raw(self, path):
        with urllib.request.urlopen(self.base + path, timeout=10) as response:
            return response.read().decode("utf-8")

    # -- базовое ---------------------------------------------------------
    def test_health(self):
        data, headers = self.get("/health")
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["products"], 6)
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["Access-Control-Allow-Origin"], "*")

    def test_meta_structure(self):
        data, _ = self.get("/api/meta")
        self.assertEqual(data["stats"]["products"], 6)
        parents = {parent["slug"]: parent for parent in data["categories"]}
        self.assertIn("low-voltage", parents)
        self.assertIn("network", parents)
        self.assertEqual(parents["low-voltage"]["count"],
                         sum(child["count"] for child in parents["low-voltage"]["children"]))
        self.assertGreater(len(data["brands"]), 1)
        self.assertTrue(all(brand["count"] > 0 for brand in data["brands"]))
        self.assertEqual(sum(parent["count"] for parent in data["categories"]), 6)

    def test_listing_default(self):
        data, _ = self.get("/api/products")
        self.assertEqual(data["total"], 6)
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["pages"], 1)
        self.assertLessEqual(len(data["items"]), 24)
        item = data["items"][0]
        for key in ("id", "name", "brand", "mpn", "parentTitle", "childTitle", "price", "image"):
            self.assertIn(key, item)
        self.assertEqual(item["price"], "Цена по запросу")

    # -- поиск -----------------------------------------------------------
    def test_search_is_case_insensitive_for_cyrillic(self):
        data, _ = self.get("/api/products", {"q": "ВЫКЛЮЧАТЕЛЬ"})
        self.assertGreaterEqual(data["total"], 1)
        self.assertTrue(all("выключатель" in item["name"].lower() for item in data["items"]))

    def test_search_by_mpn_is_case_insensitive(self):
        data, _ = self.get("/api/products", {"q": "a9f04363"})
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["mpn"], "A9F04363")

    def test_search_multiple_words_are_and(self):
        data, _ = self.get("/api/products", {"q": "реле 24"})
        self.assertEqual(data["total"], 1)
        empty, _ = self.get("/api/products", {"q": "реле кабель"})
        self.assertEqual(empty["total"], 0)

    def test_search_wildcards_are_escaped(self):
        data, _ = self.get("/api/products", {"q": "%"})
        self.assertEqual(data["total"], 0)
        data, _ = self.get("/api/products", {"q": "_"})
        self.assertEqual(data["total"], 0)

    def test_empty_result(self):
        data, _ = self.get("/api/products", {"q": "нет такого товара"})
        self.assertEqual(data["items"], [])
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["pages"], 1)

    # -- фильтры ---------------------------------------------------------
    def test_filter_by_brand(self):
        data, _ = self.get("/api/products", {"brand": "schneider-electric"})
        self.assertEqual(data["total"], 3)
        self.assertTrue(all(item["brand"] == "Schneider Electric" for item in data["items"]))

    def test_filter_by_parent_category(self):
        data, _ = self.get("/api/products", {"category": "low-voltage"})
        self.assertEqual(data["total"], 3)
        self.assertTrue(all(item["parent"] == "low-voltage" for item in data["items"]))

    def test_filter_by_child_category(self):
        data, _ = self.get("/api/products", {"category": "lv-breakers"})
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["child"], "lv-breakers")

    def test_filter_combined(self):
        # «автомат» встречается и в «Выключатель автоматический», и в «Дифавтомат»
        data, _ = self.get("/api/products", {"brand": "schneider-electric", "category": "low-voltage",
                                             "q": "автомат"})
        self.assertEqual(data["total"], 2)
        narrowed, _ = self.get("/api/products", {"brand": "schneider-electric",
                                                 "category": "lv-breakers", "q": "63"})
        self.assertEqual(narrowed["total"], 1)

    def test_unknown_filter_returns_empty_not_error(self):
        data, _ = self.get("/api/products", {"brand": "no-such-brand"})
        self.assertEqual(data["total"], 0)
        data, _ = self.get("/api/products", {"category": "nope"})
        self.assertEqual(data["total"], 0)

    # -- пагинация и сортировка -----------------------------------------
    def test_pagination(self):
        first, _ = self.get("/api/products", {"limit": 2, "page": 1, "sort": "name"})
        second, _ = self.get("/api/products", {"limit": 2, "page": 2, "sort": "name"})
        self.assertEqual(first["total"], 6)
        self.assertEqual(first["pages"], 3)
        self.assertEqual(len(first["items"]), 2)
        ids_first = {item["id"] for item in first["items"]}
        ids_second = {item["id"] for item in second["items"]}
        self.assertFalse(ids_first & ids_second)

    def test_page_beyond_last_is_clamped(self):
        data, _ = self.get("/api/products", {"limit": 2, "page": 99})
        self.assertEqual(data["page"], 3)
        self.assertEqual(len(data["items"]), 2)

    def test_limit_is_capped(self):
        data, _ = self.get("/api/products", {"limit": 9999})
        self.assertLessEqual(data["limit"], 60)
        data, _ = self.get("/api/products", {"limit": -5})
        self.assertGreaterEqual(data["limit"], 1)

    def test_bad_page_values_are_safe(self):
        data, _ = self.get("/api/products", {"page": "abc", "limit": "xyz"})
        self.assertEqual(data["page"], 1)
        self.assertGreaterEqual(data["limit"], 1)

    def test_sorting(self):
        by_name, _ = self.get("/api/products", {"sort": "name"})
        names = [item["name"] for item in by_name["items"]]
        self.assertEqual(names, sorted(names, key=str.casefold))

        by_brand, _ = self.get("/api/products", {"sort": "brand"})
        brands = [item["brand"] for item in by_brand["items"]]
        self.assertEqual(brands, sorted(brands, key=lambda value: value.casefold()))

        newest, _ = self.get("/api/products", {"sort": "new"})
        self.assertEqual(len(newest["items"]), 6)
        # снимок 2026-04 у выключателя A9F04363 — он и должен быть первым
        self.assertEqual(newest["items"][0]["mpn"], "A9F04363")

    def test_unknown_sort_falls_back(self):
        data, _ = self.get("/api/products", {"sort": "drop table"})
        self.assertEqual(data["sort"], "name")

    # -- карточка --------------------------------------------------------
    def test_detail(self):
        listing, _ = self.get("/api/products", {"q": "A9F04363"})
        product_id = listing["items"][0]["id"]
        data, _ = self.get(f"/api/products/{product_id}")
        self.assertEqual(data["mpn"], "A9F04363")
        self.assertIn("Выключатель", data["name"])
        self.assertTrue(data["description"].startswith("Выключатель"))
        self.assertEqual(data["attributes"][0]["label"], "Номинальный ток")
        self.assertEqual(data["images"], ["https://cdn.example.org/a.jpg"])
        self.assertEqual(data["documents"][0]["name"], "Паспорт")
        self.assertEqual(data["price"], "Цена по запросу")

    def test_detail_not_found(self):
        data, _ = self.get("/api/products/ffffffffffffffff", expect=404)
        self.assertIn("error", data)

    def test_detail_bad_id(self):
        data, _ = self.get("/api/products/..%2Fetc%2Fpasswd", expect=400)
        self.assertIn("error", data)

    def test_unknown_route(self):
        data, _ = self.get("/api/unknown", expect=404)
        self.assertIn("error", data)

    # -- защита данных ---------------------------------------------------
    def test_no_source_fields_leak_anywhere(self):
        bodies = [
            self.raw("/api/meta"),
            self.raw("/api/products?limit=60"),
            self.raw("/api/products/" + self.get("/api/products")[0]["items"][0]["id"]),
        ]
        forbidden = ["secret-host", SECRET_BATCH, "secret-parser", "provenance", "enrichment",
                     "source_url", "external_id", "record_id", "olnisa.ru", "описа",
                     "олписа", "Олписа"]
        for body in bodies:
            for marker in forbidden:
                self.assertNotIn(marker, body, msg=f"утечка {marker!r}: {body[:200]}")

    def test_description_is_cleaned_in_api(self):
        listing, _ = self.get("/api/products", {"q": "A9F04363"})
        detail, _ = self.get("/api/products/" + listing["items"][0]["id"])
        self.assertNotIn("Олписа", detail["description"])
        self.assertNotIn("+7 (812)", detail["description"])

    # -- префиксы прокси -------------------------------------------------
    def test_prefixed_paths(self):
        for prefix in ("/energostor/api/catalog", "/api/catalog", "/api"):
            data, _ = self.get(prefix + "/meta")
            self.assertEqual(data["stats"]["products"], 6)
        data, _ = self.get("/energostor/api/catalog/products", {"limit": 1})
        self.assertEqual(len(data["items"]), 1)

    def test_options(self):
        request = urllib.request.Request(self.base + "/api/meta", method="OPTIONS")
        with urllib.request.urlopen(request, timeout=10) as response:
            self.assertEqual(response.status, 204)
            self.assertEqual(response.headers["Access-Control-Allow-Methods"], "GET, OPTIONS")


if __name__ == "__main__":
    unittest.main()
