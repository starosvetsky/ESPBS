#!/usr/bin/env python3
"""Read-only HTTP API for the public Энергостор catalog.

Only loopback by default:

    python server.py --db data/catalog.sqlite3 --port 8766

The coordinator proxies ``/energostor/api/catalog/`` to this service, but the
handler also accepts the already-prefixed paths so that both a plain ``/api/``
proxy and a pass-through prefix work without configuration.
"""

from __future__ import annotations

import argparse
import json
import math
import mimetypes
import os
import re
import sqlite3
import sys
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

PRODUCT_ID = re.compile(r"^[0-9a-f]{16}$")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
SORTS = {
    "name": "p.name COLLATE NOCASE, p.id",
    "brand": "p.brand COLLATE NOCASE, p.name COLLATE NOCASE, p.id",
    "new": "p.collected_ts DESC, p.name COLLATE NOCASE, p.id",
}
DEFAULT_LIMIT = 24
MAX_LIMIT = 60
MAX_PAGE = 5000
MAX_QUERY = 120
MAX_WORDS = 6

PREFIXES = ("/energostor/api/catalog", "/api/catalog", "/catalog", "/api")


class Catalog:
    """Thread-local read-only access to the built catalog."""

    def __init__(self, path: Path):
        self.path = Path(path).resolve()
        self._local = threading.local()
        self._cache_lock = threading.Lock()
        self._meta_cache = None

    @property
    def connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            uri = self.path.as_uri() + "?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=10, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only=ON")
            self._local.conn = conn
        return conn

    # -- queries ---------------------------------------------------------
    def stats(self) -> dict:
        try:
            rows = self.connection.execute("SELECT key, value FROM meta").fetchall()
        except sqlite3.Error:
            return {}
        return {row["key"]: row["value"] for row in rows}

    def meta(self) -> dict:
        with self._cache_lock:
            if self._meta_cache is not None:
                return self._meta_cache
            conn = self.connection
            stats = self.stats()
            parents = []
            for row in conn.execute(
                "SELECT slug, title, products FROM parents WHERE products > 0 ORDER BY position"
            ):
                parents.append({"slug": row["slug"], "title": row["title"], "count": row["products"], "children": []})
            index = {parent["slug"]: parent for parent in parents}
            for row in conn.execute(
                "SELECT slug, parent, title, products FROM children "
                "WHERE products > 0 ORDER BY position"
            ):
                parent = index.get(row["parent"])
                if parent is None:
                    continue
                parent["children"].append(
                    {"slug": row["slug"], "title": row["title"], "count": row["products"]}
                )
            brands = [
                {"slug": row["slug"], "title": row["title"], "count": row["products"]}
                for row in conn.execute(
                    "SELECT slug, title, products FROM brands WHERE products > 0 "
                    "ORDER BY title COLLATE NOCASE"
                )
            ]
            payload = {
                "stats": {
                    "products": int(stats.get("unique_products", 0) or 0),
                    "raw_records": int(stats.get("raw_records", 0) or 0),
                    "duplicates": int(stats.get("duplicates", 0) or 0),
                    "brands": len(brands),
                    "categories": sum(len(p["children"]) for p in parents),
                    "with_images": int(stats.get("products_with_images", 0) or 0),
                    "with_documents": int(stats.get("products_with_docs", 0) or 0),
                    "with_attributes": int(stats.get("products_with_attrs", 0) or 0),
                    "first_collected": stats.get("first_collected", ""),
                    "last_collected": stats.get("last_collected", ""),
                    "built_at": stats.get("built_at", ""),
                    "source_batches": int(stats.get("batches", 0) or 0),
                },
                "categories": parents,
                "brands": brands,
            }
            self._meta_cache = payload
            return payload

    def search(self, query: dict) -> dict:
        q = _clean_query(query.get("q", [""])[0])
        brand = _clean_slug(query.get("brand", [""])[0])
        category = _clean_slug(query.get("category", [""])[0])
        sort = (query.get("sort", ["name"])[0] or "name").lower()
        if sort not in SORTS:
            sort = "name"
        page = _clamp_int(query.get("page", ["1"])[0], 1, MAX_PAGE, 1)
        limit = _clamp_int(query.get("limit", [str(DEFAULT_LIMIT)])[0], 1, MAX_LIMIT, DEFAULT_LIMIT)

        where = []
        params: list = []
        if brand:
            where.append("p.brand_slug = ?")
            params.append(brand)
        if category:
            where.append("(p.parent = ? OR p.child = ?)")
            params.extend([category, category])
        for word in _query_words(q):
            where.append("p.search LIKE ? ESCAPE '\\'")
            params.append("%" + _escape_like(word) + "%")

        clause = ("WHERE " + " AND ".join(where)) if where else ""
        conn = self.connection
        total = conn.execute(f"SELECT COUNT(*) FROM products p {clause}", params).fetchone()[0]
        pages = max(1, math.ceil(total / limit)) if total else 1
        page = min(page, pages)
        offset = (page - 1) * limit
        rows = conn.execute(
            f"""
            SELECT p.id, p.name, p.brand, p.brand_slug, p.mpn, p.parent, p.child,
                   p.summary, p.images, p.has_docs, p.has_attrs, p.collected_at
            FROM products p {clause}
            ORDER BY {SORTS[sort]}
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        ).fetchall()

        titles = self._titles()
        items = []
        for row in rows:
            images = _loads(row["images"], [])
            items.append({
                "id": row["id"],
                "name": row["name"],
                "brand": row["brand"],
                "brandSlug": row["brand_slug"],
                "mpn": row["mpn"],
                "parent": row["parent"],
                "parentTitle": titles["parents"].get(row["parent"], ""),
                "child": row["child"],
                "childTitle": titles["children"].get(row["child"], ""),
                "summary": row["summary"],
                "image": images[0] if images else None,
                "hasDocs": bool(row["has_docs"]),
                "hasAttrs": bool(row["has_attrs"]),
                "price": "Цена по запросу",
            })
        return {
            "items": items,
            "total": total,
            "page": page,
            "pages": pages,
            "limit": limit,
            "query": q,
            "brand": brand,
            "category": category,
            "sort": sort,
        }

    def product(self, product_id: str) -> dict | None:
        row = self.connection.execute(
            """
            SELECT p.* FROM products p WHERE p.id = ?
            """,
            (product_id,),
        ).fetchone()
        if row is None:
            return None
        titles = self._titles()
        images = _loads(row["images"], [])
        return {
            "id": row["id"],
            "name": row["name"],
            "brand": row["brand"],
            "brandSlug": row["brand_slug"],
            "mpn": row["mpn"],
            "parent": row["parent"],
            "parentTitle": titles["parents"].get(row["parent"], ""),
            "child": row["child"],
            "childTitle": titles["children"].get(row["child"], ""),
            "summary": row["summary"],
            "description": row["description"],
            "attributes": _loads(row["attributes"], []),
            "images": images,
            "documents": _loads(row["documents"], []),
            "price": "Цена по запросу",
            "updated": row["collected_at"],
        }

    def _titles(self) -> dict:
        with self._cache_lock:
            cache = getattr(self, "_title_cache", None)
            if cache is None:
                conn = self.connection
                cache = {
                    "parents": {r["slug"]: r["title"] for r in conn.execute("SELECT slug, title FROM parents")},
                    "children": {r["slug"]: r["title"] for r in conn.execute("SELECT slug, title FROM children")},
                }
                self._title_cache = cache
            return cache


def _loads(value, fallback):
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if isinstance(parsed, list) else fallback


def _clean_query(value: str) -> str:
    text = " ".join(str(value).split())
    return text[:MAX_QUERY]


def _query_words(text: str) -> list[str]:
    words = [word for word in text.casefold().split(" ") if word]
    return words[:MAX_WORDS]


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _clean_slug(value: str) -> str:
    text = str(value or "").strip().lower()
    return text if SLUG.match(text) else ""


def _clamp_int(value, low: int, high: int, default: int) -> int:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


class Handler(BaseHTTPRequestHandler):
    server_version = "energostor-catalog/1.0"
    catalog: Catalog = None  # set by serve()
    web_root: Path | None = None

    # -- plumbing --------------------------------------------------------
    def log_message(self, fmt, *args):  # noqa: A003 - stdlib signature
        if os.environ.get("CATALOG_QUIET"):
            return
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self._common_headers()
        self.end_headers()

    def do_GET(self):  # noqa: N802
        try:
            self._get()
        except BrokenPipeError:
            pass

    def _get(self):
        parts = urlsplit(self.path)
        path = self._strip_prefix(unquote(parts.path))
        query = parse_qs(parts.query, keep_blank_values=True)

        if path in ("/health", "/healthz"):
            return self._health()
        if path == "/meta":
            return self._json(self.catalog.meta(), cache=30)
        if path == "/products":
            return self._json(self.catalog.search(query), cache=15)
        if path.startswith("/products/"):
            product_id = path[len("/products/"):].strip("/")
            if not PRODUCT_ID.match(product_id):
                return self._error(HTTPStatus.BAD_REQUEST, "Некорректный идентификатор товара")
            item = self.catalog.product(product_id)
            if item is None:
                return self._error(HTTPStatus.NOT_FOUND, "Товар не найден")
            return self._json(item, cache=300)

        if self.web_root is not None:
            if self._static(path):
                return
        return self._error(HTTPStatus.NOT_FOUND, "Не найдено")

    def _strip_prefix(self, path: str) -> str:
        for prefix in PREFIXES:
            if path == prefix:
                return "/"
            if path.startswith(prefix + "/"):
                return path[len(prefix):]
        return path

    # -- responses -------------------------------------------------------
    def _health(self):
        stats = self.catalog.stats()
        payload = {
            "status": "ok",
            "products": int(stats.get("unique_products", 0) or 0),
            "schema": stats.get("schema_version", ""),
            "built_at": stats.get("built_at", ""),
        }
        self._json(payload, cache=0)

    def _json(self, payload, cache: int = 0):
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self._common_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "public, max-age=%d" % cache if cache else "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status, message: str):
        body = json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._common_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _common_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Accept, Content-Type")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")

    # -- optional static files for local preview -------------------------
    def _static(self, path: str) -> bool:
        if path == "/":
            path = "/catalog/"
        if path.endswith("/"):
            path += "index.html"
        candidate = (self.web_root / path.lstrip("/")).resolve()
        try:
            candidate.relative_to(self.web_root)
        except ValueError:
            return False
        if not candidate.is_file():
            return False
        ctype, _ = mimetypes.guess_type(candidate.name)
        body = candidate.read_bytes()
        self.send_response(HTTPStatus.OK)
        self._common_headers()
        self.send_header("Content-Type", ctype or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return True


def serve(db: Path, host: str, port: int, web_root: Path | None = None) -> ThreadingHTTPServer:
    Handler.catalog = Catalog(db)
    Handler.web_root = web_root.resolve() if web_root else None
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    return httpd


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="HTTP API каталога (только чтение).")
    parser.add_argument("--db", type=Path, required=True, help="производная БД каталога")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--web-root", type=Path, default=None,
                        help="раздавать статику из этого каталога для локальной проверки")
    args = parser.parse_args(argv)

    if not args.db.is_file():
        print(f"Нет файла БД: {args.db}", file=sys.stderr)
        return 2
    httpd = serve(args.db, args.host, args.port, args.web_root)
    print(f"Каталог: http://{args.host}:{args.port}/  (БД: {args.db})", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
