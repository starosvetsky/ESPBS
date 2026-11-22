#!/bin/sh
# Certbot deploy hook: let nginx load renewed certificates after validation.
set -eu
/usr/sbin/nginx -t
/usr/bin/systemctl reload nginx
