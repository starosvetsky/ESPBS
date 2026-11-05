"""Package only public static files for the unlinked /energostor/ preview."""
import hashlib
import json
import tarfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
output = root.parent / '.tmp' / 'energostor-preview-20261101.tar.gz'
files = [root / 'index.html', root / 'robots.txt']
for directory in ('assets', 'catalog'):
    files.extend(p for p in (root / directory).rglob('*') if p.is_file())
assert not any(p.suffix in ('.php', '.py', '.zip', '.sqlite3') for p in files)
with tarfile.open(output, 'w:gz') as archive:
    for path in sorted(files):
        archive.add(path, arcname=path.relative_to(root).as_posix(), recursive=False)
manifest = {
    'target_path': '/energostor/',
    'files': {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(files)},
    'archive_sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
}
output.with_suffix('.manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
print(f'Packaged {len(files)} public files: {output}')
print('SHA256:', manifest['archive_sha256'])
