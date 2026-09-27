# SCP in one container: the engine (FastAPI) serves the API and the built web client on port 8000.
# Build from this folder:  docker build -t scp .
# See docs/DEPLOY.md for the database, mail, single sign-on, backups and a reverse proxy.

# --- the web client ------------------------------------------------------------------------------
FROM node:20-bookworm-slim AS web
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# --- the engine ----------------------------------------------------------------------------------
FROM python:3.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    SCP_DB=/data/scp.sqlite \
    SCP_REQUIRE_SIGNIN=1 \
    SCP_SIGNUP=invite
WORKDIR /app
# dependencies first, so a code change does not reinstall them
COPY engine/pyproject.toml engine/
RUN mkdir -p engine/scp && touch engine/scp/__init__.py \
 && pip install --no-cache-dir ./engine && pip uninstall -y scp
COPY engine/ engine/
COPY examples/ examples/
RUN pip install --no-cache-dir --no-deps -e ./engine
COPY --from=web /app/web/dist web/dist
RUN useradd --system --uid 10001 --home /data scp && mkdir -p /data && chown scp /data
USER scp
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"
# one worker: saves are checked against the company's latest revision under a lock inside the process
CMD ["uvicorn", "scp.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--timeout-keep-alive", "75"]
