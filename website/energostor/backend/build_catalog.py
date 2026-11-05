#!/usr/bin/env python3
"""Build the derived public catalog database from saved parser batches.

Usage
-----
    python build_catalog.py --source /var/lib/espbs --dest data/catalog.sqlite3

The source directory is only ever opened with ``mode=ro``.  The destination
is written to a temporary file and atomically renamed on success, so a failed
build never damages the catalog that is currently served.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from espbs_catalog.store import BuildError, BuildStats, build


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Собрать витрину каталога из сохранённых партий парсера (только чтение).",
    )
    parser.add_argument("--source", required=True, type=Path,
                        help="каталог данных парсера (в нём batches/*.sqlite3) или один файл партии")
    parser.add_argument("--dest", required=True, type=Path,
                        help="путь к производной БД каталога")
    parser.add_argument("--limit", type=int, default=None,
                        help="обработать не более N записей (для проверки)")
    parser.add_argument("--max-mb", type=int, default=2048,
                        help="предохранитель по размеру производной БД, МБ (по умолчанию 2048)")
    parser.add_argument("--quiet", action="store_true", help="без прогресса")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    log = None if args.quiet else (lambda message: print(message, file=sys.stderr))
    try:
        stats = build(
            args.source,
            args.dest,
            limit=args.limit,
            max_bytes=args.max_mb * 1024 * 1024,
            log=log,
        )
    except BuildError as error:
        print(f"Ошибка сборки: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Сборка прервана, целевая БД не изменена.", file=sys.stderr)
        return 130

    _report(stats, args.dest)
    return 0


def _report(stats: BuildStats, dest: Path) -> None:
    import sqlite3

    conn = sqlite3.connect(dest)
    try:
        meta = {row[0]: row[1] for row in conn.execute("SELECT key, value FROM meta")}
    finally:
        conn.close()
    print("Готово.")
    print(f"  партий:            {stats.batches}")
    print(f"  сырых записей:     {stats.raw_records}")
    print(f"  товаров:           {meta.get('unique_products', '?')}")
    print(f"  дубликатов слито:  {stats.duplicates}")
    print(f"  пропущено:         {stats.skipped}")
    print(f"  с фото / док-ми:   {meta.get('products_with_images', '?')} / {meta.get('products_with_docs', '?')}")
    print(f"  снимки:            {stats.first_collected or '—'} … {stats.last_collected or '—'}")
    print(f"  база:              {dest} ({dest.stat().st_size // 1024} КБ)")


if __name__ == "__main__":
    sys.exit(main())
