#!/bin/bash
set -euo pipefail

if ! compgen -G '/var/lib/clamav/main.c[vl]d' >/dev/null; then
    freshclam --config-file=/etc/clamav/freshclam.conf
fi

clamd --config-file=/etc/clamav/clamd.conf &
scanner_pid=$!
freshclam --daemon --foreground=true --config-file=/etc/clamav/freshclam.conf &
updater_pid=$!

shutdown() {
    kill "$scanner_pid" "$updater_pid" 2>/dev/null || true
    wait "$scanner_pid" "$updater_pid" 2>/dev/null || true
}
trap shutdown EXIT
trap 'exit 0' TERM INT
wait -n "$scanner_pid" "$updater_pid"
# Restart both processes if either exits, including an unexpected clean exit.
exit 1
