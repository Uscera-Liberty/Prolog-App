#!/bin/sh
set -eu

# Render монтирует Persistent Disk после сборки образа, поэтому владелец,
# выставленный через Dockerfile, может быть перекрыт точкой монтирования.
DATA_DIR="${REHAB_DATA_DIR:-/var/data}"
mkdir -p "$DATA_DIR"

if [ "$(id -u)" -eq 0 ]; then
    chown rehab:rehab "$DATA_DIR"
    if [ -f "$DATA_DIR/user_data.json" ]; then
        chown rehab:rehab "$DATA_DIR/user_data.json"
    fi
    exec gosu rehab "$@"
fi

exec "$@"
