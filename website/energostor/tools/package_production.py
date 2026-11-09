"""Build a production archive for the root of energostor.ru.

The source tree deliberately remains a noindex preview. Production-only changes
are applied to archive members in memory, so packaging cannot accidentally make
the public preview indexable or enable its forms.
"""
from __future__ import annotations

import hashlib
import json
import re
import tarfile
from io import BytesIO
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT.parent / ".tmp" / "energostor-production.tar.gz"
PUBLIC_DIRS = ("assets", "brands", "catalog", "vendors")
PUBLIC_FILES = ("index.html", "send.php")


def production_bytes(path: Path) -> bytes:
    relative = path.relative_to(ROOT).as_posix()
    if relative == "robots.txt":
        return b"User-agent: *\nAllow: /\n"
    data = path.read_bytes()
    if path.suffix.lower() != ".html":
        return data
    text = data.decode("utf-8")
    text = re.sub(
        r'<meta\s+name=["\']robots["\']\s+content=["\'][^"\']*["\']\s*/?>',
        '<meta name="robots" content="index, follow">',
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r'\sdata-preview=["\']true["\']', "", text, flags=re.IGNORECASE)
    return text.encode("utf-8")


def files() -> list[Path]:
    result = [ROOT / name for name in PUBLIC_FILES]
    result.append(ROOT / "robots.txt")
    for directory in PUBLIC_DIRS:
        result.extend(path for path in (ROOT / directory).rglob("*") if path.is_file())
    return sorted(set(result))


def main() -> None:
    selected = files()
    forbidden = {".py", ".sqlite", ".sqlite3", ".zip"}
    assert not any(path.suffix.lower() in forbidden for path in selected)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    with tarfile.open(OUTPUT, "w:gz") as archive:
        for path in selected:
            relative = path.relative_to(ROOT).as_posix()
            content = production_bytes(path)
            info = tarfile.TarInfo(relative)
            info.size = len(content)
            info.mode = 0o644
            archive.addfile(info, BytesIO(content))
            hashes[relative] = hashlib.sha256(content).hexdigest()
    manifest = {
        "domain": "energostor.ru",
        "target_path": "/var/www/energostor.ru",
        "files": hashes,
        "archive_sha256": hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),
    }
    manifest_path = OUTPUT.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Packaged {len(selected)} production files: {OUTPUT}")
    print("SHA256:", manifest["archive_sha256"])


if __name__ == "__main__":
    main()
