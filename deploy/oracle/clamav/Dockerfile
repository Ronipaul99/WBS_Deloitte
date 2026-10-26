FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates clamav-daemon clamav-freshclam netcat-openbsd tini \
    && rm -rf /var/lib/apt/lists/* \
    && install -d -o clamav -g clamav /run/clamav /var/lib/clamav

COPY --chmod=0644 clamd.conf freshclam.conf /etc/clamav/
COPY start.sh /usr/local/bin/start-clamav
RUN chmod 0755 /usr/local/bin/start-clamav
USER clamav
EXPOSE 3310
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/start-clamav"]
