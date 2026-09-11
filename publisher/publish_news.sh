#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ ! -d "$ROOT/node_modules" ]; then
  printf '%s\n' '{"action":"unknown","error":{"details":{},"message":"publisher dependencies are not installed; run npm ci in publisher/","type":"dependency_missing"},"meta":{"cli_version":"0.1.0","envelope_version":"1.0"},"ok":false}'
  exit 1
fi
exec node "$ROOT/bin/publish_news.ts" "$@"
