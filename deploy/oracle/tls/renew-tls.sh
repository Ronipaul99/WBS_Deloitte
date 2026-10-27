#!/bin/sh
set -eu

cd /home/developer/wbs-web/deploy/oracle
# Avoid concurrent manual/timer renewal attempts on this VM.
exec 9>/home/developer/wbs-web/deploy/oracle/.tls-renew.lock
flock -n 9 || exit 0
docker compose -f compose.web.yml -f compose.acme.yml -f compose.https.yml \
    run --rm --no-deps -T certbot renew --quiet --non-interactive --no-random-sleep-on-renew \
    --deploy-hook '/bin/sh /hooks/deploy-cert.sh'
# Check the exported certificate before gracefully reloading. A reload also
# runs after a no-op renewal so a previously missed reload recovers itself.
docker compose -f compose.web.yml -f compose.acme.yml -f compose.https.yml \
    exec -T ui nginx -t
docker compose -f compose.web.yml -f compose.acme.yml -f compose.https.yml \
    exec -T ui nginx -s reload
