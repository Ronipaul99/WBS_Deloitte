#!/bin/sh
set -eu

if ! printf '%s' "${API_ORIGIN:-}" | grep -Eq '^https://[A-Za-z0-9.-]+(:[0-9]{1,5})?$'; then
    echo "API_ORIGIN must be an exact HTTPS origin" >&2
    exit 1
fi
