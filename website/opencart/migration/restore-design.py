"""Restore the owner's PDF reference composition without touching catalogue data."""
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sys


def main():
    root=Path(sys.argv[1]).resolve()
    if root!=Path('/opt/energostor-next'):
        raise SystemExit('Unexpected release path')
    source=Path(__file__).with_name('restored')
    public=root/'upload'
    backup=root/'design-backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup.mkdir(parents=True,mode=0o700)
    files={source/f'{name}.twig':public/f'catalog/view/template/common/{name}.twig' for name in ['header','home','footer']}
    files[source/'restored.css']=public/'energostor-theme/assets/css/restored.css'
    files[source/'partners.css']=public/'energostor-theme/assets/css/partners.css'
    files[source/'partners.twig']=public/'catalog/view/template/information/partners.twig'
    files[source.parent/'ui/information.twig']=public/'catalog/view/template/information/information.twig'
    for asset in (source/'assets').iterdir():
        if asset.suffix not in ['.png','.svg']:
            continue
        files[asset]=public/'energostor-theme/assets/img/reference'/asset.name
    for origin,target in files.items():
        relative=target.relative_to(root)
        if target.exists():
            destination=backup/relative
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(target,destination)
        target.parent.mkdir(parents=True,exist_ok=True)
        temp=target.with_name(target.name+'.restore-tmp')
        shutil.copyfile(origin,temp)
        temp.replace(target)
    (root/'restored-design.txt').write_text('Owner PDF reference restored; keep editorial publishing separate from the common shell.\n')
    for compiled in (public/'system/storage/cache/template').rglob('*.php'):
        compiled.unlink()
    print(f'Restored {len(files)} presentation files. Backup: {backup}. Catalogue untouched.')


if __name__=='__main__':
    main()
