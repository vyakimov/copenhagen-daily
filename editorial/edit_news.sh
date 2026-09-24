#!/bin/sh
# Self-locating wrapper for the editorial desk. Emits exactly one JSON object on stdout.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON="$ROOT/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    printf '%s\n' '{"action":"startup","error":{"details":{"expected":".venv/bin/python"},"message":"The editorial virtual environment is missing. Provision it from uv.lock, then retry.","type":"dependency_missing"},"meta":{"schema_version":"1.0"},"ok":false}'
    exit 1
fi
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYTHON" -m news_editorial "$@"
