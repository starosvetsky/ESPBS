"""Require HTTPS subresources on the existing Energostor TLS virtual hosts."""
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess

config=Path('/etc/nginx/conf.d/energostor-next.conf')
original=config.read_text()
policy='    add_header Content-Security-Policy "upgrade-insecure-requests" always;'
anchor='    include /etc/letsencrypt/options-ssl-nginx.conf;'
if original.count(anchor)!=2 or 'server_name energostor.ru;' not in original:
    raise SystemExit('Unexpected virtual host layout; no changes made')
if policy not in original:
    backup=Path('/opt/energostor-next/nginx-backups')/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup.mkdir(parents=True,mode=0o700)
    shutil.copy2(config,backup/config.name)
    try:
        config.write_text(original.replace(anchor,anchor+'\n'+policy))
        subprocess.run(['nginx','-t'],check=True)
        subprocess.run(['systemctl','reload','nginx'],check=True)
    except BaseException:
        config.write_text(original)
        subprocess.run(['nginx','-t'],check=True)
        subprocess.run(['systemctl','reload','nginx'],check=True)
        raise
    print('HTTPS subresource policy enabled. Backup:',backup)
else:
    print('HTTPS subresource policy already enabled')
