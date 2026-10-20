#!/bin/sh
set -eu
ADS_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec /usr/bin/python3 -B "$ADS_DIR/tools/manage.py" install "$@"
