#!/bin/sh

set -eu

NEWS_GATHERER_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
NEWS_GATHERER_PYTHON="$NEWS_GATHERER_ROOT/.venv/bin/python"

if [ ! -x "$NEWS_GATHERER_PYTHON" ]; then
    printf '%s\n' '{"action":"startup","error":{"details":{"expected":".venv/bin/python"},"message":"The project virtual environment is missing. Ask the operator to provision it from the locked dependencies, then retry.","type":"dependency_missing"},"meta":{"schema_version":"2.0"},"ok":false}'
    exit 1
fi

cd "$NEWS_GATHERER_ROOT"
export PYTHONPATH="$NEWS_GATHERER_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$NEWS_GATHERER_PYTHON" -m news_ingest "$@"
