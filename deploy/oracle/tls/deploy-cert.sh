#!/bin/sh
set -eu

# Certbot executes this only after successful issuance/renewal. Nginx receives
# only its certificate/key, never the ACME account's private configuration.
lineage=${RENEWED_LINEAGE:?Certbot must provide RENEWED_LINEAGE}
name=${lineage##*/}
case "$name" in
    ''|*[!a-zA-Z0-9_-]*) echo "Invalid certificate lineage name" >&2; exit 1 ;;
esac
destination=/export/$name
test -s "$lineage/fullchain.pem"
test -s "$lineage/privkey.pem"
umask 077
# Keep each lineage separate so IP renewal cannot replace the domain certificate.
mkdir -p "$destination"
cp "$lineage/fullchain.pem" "$destination/fullchain.pem.next"
cp "$lineage/privkey.pem" "$destination/privkey.pem.next"
# The existing Nginx image uses UID/GID 101. Files remain root-owned and can
# only be read by that group; the Nginx mount is read-only.
chgrp 101 /export "$destination" "$destination/fullchain.pem.next" "$destination/privkey.pem.next"
chmod 0750 /export "$destination"
chmod 0640 "$destination/fullchain.pem.next" "$destination/privkey.pem.next"
mv -f "$destination/fullchain.pem.next" "$destination/fullchain.pem"
mv -f "$destination/privkey.pem.next" "$destination/privkey.pem"
date -u +%FT%TZ > "$destination/last-issued-at"
