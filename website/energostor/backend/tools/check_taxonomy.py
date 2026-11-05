"""Review rubrication of the audited source paths (not part of the service).

Prints a per-parent listing so the mapping can be checked by eye, and flags
paths that fall through to the generic bucket.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from espbs_catalog import taxonomy as tx  # noqa: E402


def main() -> int:
    data = json.loads((ROOT / "espbs_catalog" / "data" / "source_paths.json").read_text("utf-8"))
    paths = [(p, c) for p, c in data["paths"]]
    tx.load_known_paths([p for p, _ in paths])

    by_parent: dict[str, list[tuple[str, int, str]]] = defaultdict(list)
    per_child = Counter()
    fall: list[tuple[str, int]] = []
    for path, count in paths:
        child = tx.classify_path(path)
        if child is None:
            fall.append((path, count))
            continue
        per_child[child] += 1
        rub = tx.rubric_for(child)
        by_parent[rub.parent].append((path, count, child))

    only = sys.argv[1:] if len(sys.argv) > 1 else None
    for parent, title in tx.PARENTS:
        if only and parent not in only:
            continue
        items = sorted(by_parent[parent], key=lambda x: -x[1])
        total = sum(c for _, c, _ in items)
        print(f"\n=== {title}  ({parent}) paths={len(items)} records={total}")
        for child, child_title in [(c, tx.TITLE_BY_CHILD[c]) for c in tx.CHILDREN_BY_PARENT[parent]]:
            group = [(p, n) for p, n, c in items if c == child]
            if not group:
                continue
            print(f"  -- {child_title} ({child}) records={sum(n for _, n in group)}")
            for p, n in sorted(group, key=lambda x: -x[1]):
                print(f"       {n:6d}  {p}")

    print("\n=== no-source-category:", fall)
    zero = [c for c in tx.TITLE_BY_CHILD if per_child[c] == 0]
    print("empty children:", zero)
    return 0


if __name__ == "__main__":
    sys.exit(main())
