# SCP in one container: the engine (FastAPI) serves the API and the built web client on port 8000.
# Build from this folder:  docker build -t scp .
# See docs/DEPLOY.md for the database, mail, single sign-on, backups and a reverse proxy.

# --- the web client ------------------------------------------------------------------------------
# 22.23.4 is the 21 October 2026 security release: Brotli decoder RCE, TLS hostname bypasses,
# and rejection of the compromised eMudhra intermediates.
FROM node:22.23.4-bookworm-slim AS web
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
# DLA-4845-1: bookworm's security update drops emSign ECC Root CA - G3. Scheduled imports
# verify TLS with this system bundle (ssl.create_default_context).
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ca-certificates \
 && dpkg --compare-versions "$(dpkg-query -W -f='${Version}' ca-certificates)" ge '20250419~deb12u2' \
 && rm -rf /var/lib/apt/lists/*
# dependencies first, so a code change does not reinstall them.
# pip before 26.2.2 vendors a CA bundle that still trusts the compromised eMudhra root, and it
# trusts that bundle even when the system store does not. Download the wheel with the system
# store, check the published digest, then install it.
COPY engine/pyproject.toml engine/
RUN python -c 'import hashlib, urllib.request; url="https://files.pythonhosted.org/packages/3f/06/3e4420302363fbb71be3c7f35ce042f54bfca330e3e66b3a2e3c4cca579f/pip-26.2.2-py3-none-any.whl"; expected="fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70"; data=urllib.request.urlopen(url, timeout=120).read(); digest=hashlib.sha256(data).hexdigest(); assert digest==expected, digest; open("/tmp/pip.whl","wb").write(data)' \
 && python -m pip install --no-cache-dir /tmp/pip.whl && rm /tmp/pip.whl \
 && mkdir -p engine/scp && touch engine/scp/__init__.py \
 && pip install --no-cache-dir ./engine && pip uninstall -y scp
COPY engine/ engine/
COPY examples/ examples/
RUN pip install --no-cache-dir --no-deps -e ./engine
COPY --from=web /app/web/dist web/dist
# Build contexts can have restrictive directory modes; the runtime user must be able to read the application.
RUN chmod -R a+rX /app && useradd --system --uid 10001 --home /data scp && mkdir -p /data && chown scp /data
USER scp
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"
# one worker: saves are checked against the company's latest revision under a lock inside the process
# X-Forwarded-* headers are trusted only from the proxy (FORWARDED_ALLOW_IPS, default the machine itself; CV-H10).
# Links that leave the server are made from SCP_PUBLIC_URL alone, whatever the headers say.
ENV FORWARDED_ALLOW_IPS=127.0.0.1
CMD ["sh", "-c", "exec uvicorn scp.api.app:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips \"$FORWARDED_ALLOW_IPS\" --timeout-keep-alive 75"]
