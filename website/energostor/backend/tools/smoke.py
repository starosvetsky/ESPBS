"""Local smoke check: build a tiny catalog from synthetic batches and query it.

    python tools/smoke.py

Uses only the public interfaces (build_catalog.build, server.serve) so it
catches wiring mistakes early.  Not a substitute for the unit tests.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import threading
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from espbs_catalog.store import build  # noqa: E402
from fixtures import make_batch, product  # noqa: E402
from server import serve  # noqa: E402

AD_TAIL = (
    " – артикул товара бренда Schneider Electric с розничной ценой 1 200 ₽ за штуку. "
    "Купите по специальной цене оптом или в розницу в компании Олписа. "
    "Купить можно по телефону +7 (812) 000-00-00, отправить заявку на почту info@example.ru."
)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="catalog-smoke-"))
    try:
        source = tmp / "source"
        batches = source / "batches"
        records = [
            {"payload": product(
                "Выключатель автоматический 16 А",
                brand="Schneider Electric", mpn="A9F04116",
                url="https://olnisa.ru/manufacturers/schneider-electric/nizkovoltnoe-oborudovanie/"
                    "modulnyj-avtomaticheskij-vyklyuchatel-avtomat/",
                description="Выключатель автоматический 1P 16 А, 4.5 кА." + AD_TAIL,
                attributes={"Номинальный ток": "16 А", "Полюсов": "1"},
                images=["https://olnisa.ru/upload/a.jpg", "https://static.example.org/a.jpg"]),
                "collected_at": "2026-01-01T10:00:00Z"},
            {"payload": product(
                "Коммутатор D-Link DES-3200-28",
                brand="D-Link", mpn="DES-3200-28",
                url="https://dlink.ru/ru/products/1/des-3200-28.html",
                description="Коммутатор управляемый, 24 порта 10/100."),
                "collected_at": "2026-01-01T10:00:00Z"},
            {"payload": product(
                "Товар без артикула",
                brand="NoName",
                url="https://olnisa.ru/manufacturers/noname/aksessuary/"),
                "collected_at": "2026-01-01T10:00:00Z"},
        ]
        make_batch(batches / "a.sqlite3", records, "2026-01-01T00:00:00+00:00")
        make_batch(batches / "b.sqlite3", [
            {"payload": product(
                "Выключатель автоматический 16 А",
                brand="Schneider Electric", mpn="A9F04116",
                url="https://olnisa.ru/manufacturers/schneider-electric/nizkovoltnoe-oborudovanie/"
                    "modulnyj-avtomaticheskij-vyklyuchatel-avtomat/",
                description="Выключатель автоматический 1P 16 А, 4.5 кА, серия Acti9.",
                attributes={"Номинальный ток": "16 А"}),
                "collected_at": "2026-02-01T10:00:00Z"},
        ], "2026-02-01T00:00:00+00:00")

        db = tmp / "catalog.sqlite3"
        stats = build(source, db, log=None)
        print(f"raw={stats.raw_records} inserted={stats.inserted} updated={stats.updated} dup={stats.duplicates}")

        httpd = serve(db, "127.0.0.1", 0)
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{port}"

        def get(path):
            with urllib.request.urlopen(base + path, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))

        health = get("/health")
        meta = get("/api/meta")
        listing = get("/api/products?" + urllib.parse.urlencode({"q": "выключатель", "limit": 10}))
        print("health:", health)
        print("brands:", [b["title"] for b in meta["brands"]][:5])
        print("parents:", [(c["title"], c["count"]) for c in meta["categories"]])
        print("found:", listing["total"], listing["items"][0]["name"] if listing["items"] else None)
        detail = get("/api/products/" + listing["items"][0]["id"])
        print("images:", detail["images"])
        print("description:", detail["description"])
        print("attributes:", detail["attributes"])
        httpd.shutdown()
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
