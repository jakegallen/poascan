# python:3.12-slim, pinned to its multi-arch index digest (Dependabot proposes updates)
FROM python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704
WORKDIR /app
RUN pip install --no-cache-dir pillow==12.3.0
# Offline IP to country file for the daily country count (DB-IP Lite, CC BY 4.0). GEOIP_MONTH busts the cache monthly.
# A failed fetch leaves no file and the build goes on; the server then counts no country.
ARG GEOIP_MONTH=unset
COPY tools/geoip_fetch.py /tmp/geoip_fetch.py
RUN mkdir -p data && echo "geoip month $GEOIP_MONTH" && python3 /tmp/geoip_fetch.py data/country.mmdb && rm /tmp/geoip_fetch.py
COPY poascan/ poascan/
COPY static/ static/
COPY data/census.csv data/tools.json data/declared_families.json data/clients.json data/
ENV PORT=8080 HOST=0.0.0.0 POASCAN_DB=/data/poascan.db PYTHONUNBUFFERED=1 MALLOC_ARENA_MAX=2
RUN groupadd -r -g 10001 poascan && useradd -r -u 10001 -g 10001 poascan && mkdir -p /data && chown poascan:poascan /data
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s CMD python3 -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=4)"
# Fly volumes mount root-owned at /data: fix ownership as root, then drop to the unprivileged user.
CMD ["sh", "-c", "chown -R 10001:10001 /data && exec setpriv --reuid=10001 --regid=10001 --init-groups python3 -m poascan.server"]
