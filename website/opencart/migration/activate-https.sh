#!/usr/bin/env bash
# Run on the new server after both public names resolve here.
set -euo pipefail
expected=136.234.4.214
for host in energostor.ru www.energostor.ru; do
    records=$(dig @1.1.1.1 +short A "$host" | awk '/^[0-9.]+$/')
    if [[ "$records" != "$expected" || -n "$(dig @1.1.1.1 +short AAAA "$host" | awk '/:/')" ]]; then
        echo "Waiting for A/AAAA records of $host"
        exit 0
    fi
done

config=/etc/nginx/conf.d/energostor-next.conf
if grep -q 'listen 443 ssl' "$config"; then
    exit 0
fi
certbot certonly --non-interactive --webroot -w /var/www/energostor-acme \
    --cert-name energostor.ru -d energostor.ru -d www.energostor.ru

backup=$(mktemp)
cp "$config" "$backup"
cat > "$config" <<'NGINX'
server {
    listen 127.0.0.1:8782;
    server_name localhost;
    add_header X-Robots-Tag "noindex, nofollow" always;
    set $energostor_preview 1;
    include /etc/nginx/snippets/energostor-next-storefront.conf;
}
server {
    listen 80;
    listen [::]:80;
    server_name energostor.ru www.energostor.ru;
    location ^~ /.well-known/acme-challenge/ {
        root /var/www/energostor-acme;
        try_files $uri =404;
    }
    location / { return 301 https://energostor.ru$request_uri; }
}
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name www.energostor.ru;
    ssl_certificate /etc/letsencrypt/live/energostor.ru/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/energostor.ru/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    add_header Content-Security-Policy "upgrade-insecure-requests" always;
    return 301 https://energostor.ru$request_uri;
}
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name energostor.ru;
    ssl_certificate /etc/letsencrypt/live/energostor.ru/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/energostor.ru/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    add_header Content-Security-Policy "upgrade-insecure-requests" always;
    set $energostor_preview "";
    include /etc/nginx/snippets/energostor-next-storefront.conf;
}
NGINX
if ! nginx -t || ! systemctl reload nginx; then
    cp "$backup" "$config"
    nginx -t && systemctl reload nginx
    exit 1
fi
rm -f "$backup"
