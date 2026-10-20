FROM python:3.12-slim
WORKDIR /app
COPY poascan/ poascan/
COPY static/ static/
COPY data/census.csv data/tools.json data/declared_families.json data/
ENV PORT=8080 HOST=0.0.0.0 POASCAN_DB=/data/poascan.db PYTHONUNBUFFERED=1
RUN groupadd -r -g 10001 poascan && useradd -r -u 10001 -g 10001 poascan && mkdir -p /data && chown poascan:poascan /data
EXPOSE 8080
HEALTHCHECK --interval=60s --timeout=5s CMD python3 -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/api/health',timeout=4)"
# Fly volumes mount root-owned at /data: fix ownership as root, then drop to the unprivileged user.
CMD ["sh", "-c", "chown -R 10001:10001 /data && exec setpriv --reuid=10001 --regid=10001 --init-groups python3 -m poascan.server"]
