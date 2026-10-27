#!/bin/sh
set -eu
cd "$(dirname "$0")"
exec docker compose -f compose.web.yml -f compose.acme.yml -f compose.https.yml "$@"
