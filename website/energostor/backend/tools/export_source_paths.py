"""Export the audited source-category list into the work tree.

Reads the read-only audit file produced by the coordinator and writes
``espbs_catalog/data/source_paths.json``: the 505 source paths with their
record counts.  Product payloads, URLs and provenance are NOT copied — only
the path strings and aggregate counts, which the taxonomy tests need.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

AUDIT = Path(r"D:\Codex\starosvetsky\.tmp\catalog-taxonomy-audit.json")
OUT = Path(__file__).resolve().parent.parent / "espbs_catalog" / "data" / "source_paths.json"


def main() -> int:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    paths = audit["categories"]
    total = sum(count for _, count in paths)
    payload = {
        "about": "Source category paths from the read-only server audit; counts are records.",
        "total_records": total,
        "paths": [[path, count] for path, count in paths],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"paths={len(paths)} records={total} -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
