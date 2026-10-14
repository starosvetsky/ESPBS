server {
    server_name starosvetsky.ru www.starosvetsky.ru;

    root /var/www/starosvetsky.ru;
    index index.html;

    include /etc/nginx/snippets/espbs.conf;

    location / {
        try_files $uri $uri/ /index.html;
    }

    listen [::]:443 ssl ipv6only=on; # managed by Certbot
    listen 443 ssl; # managed by Certbot
    ssl_certificate /etc/letsencrypt/live/starosvetsky.ru/fullchain.pem; # managed by Certbot
    ssl_certificate_key /etc/letsencrypt/live/starosvetsky.ru/privkey.pem; # managed by Certbot
    include /etc/letsencrypt/options-ssl-nginx.conf; # managed by Certbot
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem; # managed by Certbot
}

server {
    if ($host = www.starosvetsky.ru) {
        return 301 https://$host$request_uri;
    } # managed by Certbot

    if ($host = starosvetsky.ru) {
        return 301 https://$host$request_uri;
    } # managed by Certbot

    listen 80;
    listen [::]:80;

    server_name starosvetsky.ru www.starosvetsky.ru;
    return 404; # managed by Certbot
}
