#!/bin/sh
# Build only the derived catalog. The original parser batches stay read-only.
set -eu
exec /usr/bin/python3 /opt/energostor-catalog/build_catalog.py --source /var/lib/espbs --dest /var/lib/energostor-catalog/catalog.sqlite3 --max-mb 1536
