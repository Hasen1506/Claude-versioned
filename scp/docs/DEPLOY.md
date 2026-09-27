# Running SCP for a company

One container holds everything: the engine (Python, FastAPI) serves the API and the built web client on port 8000,
and keeps every company, account, plan version and change document in one SQLite file. Put a reverse proxy with
HTTPS in front of it, give it a folder for the database and one for backups, and, when you have them, a mail server
and your identity provider.

## 1. Build and start

```bash
cd scp
docker build -t scp .
docker run -d --name scp -p 127.0.0.1:8000:8000 \
  -v scp-data:/data -v /srv/scp-backups:/backups \
  -e SCP_PUBLIC_URL=https://plan.example.com \
  -e SCP_BACKUP_DIR=/backups \
  --restart unless-stopped scp
```

The server runs as user 10001 inside the container: a backup folder on the host must be writable by it
(`sudo mkdir -p /srv/scp-backups && sudo chown 10001 /srv/scp-backups`).

Open `http://localhost:8000` on the server (or the public address once the proxy below is in place), make the first
account: it becomes the server's first user and makes the first company. The image starts with sign-in required and
new accounts by invitation only (see the settings below); a company owner invites the others from *Account*.

`deploy/compose.yaml` does the same with Docker Compose and adds Caddy for HTTPS (a certificate from Let's Encrypt,
renewed by itself): set the host name in `deploy/Caddyfile`, then `docker compose -f deploy/compose.yaml up -d`.

Without Docker: Python ≥ 3.11 and Node ≥ 20,

```bash
cd scp/engine && pip install -e .
cd ../web && npm ci && npm run build
cd ../engine && SCP_DB=/var/lib/scp/scp.sqlite SCP_REQUIRE_SIGNIN=1 SCP_SIGNUP=invite \
  uvicorn scp.api.app:app --host 127.0.0.1 --port 8000 --workers 1 --proxy-headers
```

and run it under systemd (or the like) so it restarts.

## 2. Settings

Everything is set by environment variables. None is needed to try it; the ones marked *production* should be set.

| Variable | What it does | Default |
|---|---|---|
| `SCP_DB` | The database file. Keep it on a volume that is backed up. | `~/.scp/scp.sqlite`; in the image `/data/scp.sqlite` |
| `SCP_REQUIRE_SIGNIN` | `1`: every call needs a signed-in person, and everything is kept in a company. *Production.* | off; in the image `1` |
| `SCP_SIGNUP` | Who may make an account: `open` (anyone), `invite` (an e-mail a company owner invited, and the very first account), `closed` (the first account only). *Production:* `invite`. | `open`; in the image `invite` |
| `SCP_PUBLIC_URL` | The address people open, e.g. `https://plan.example.com`. Used in links sent by mail and for single sign-on. *Production.* | none |
| `SCP_BACKUP_DIR` | A folder for the nightly copy of the database. None: no nightly copy. *Production.* | none |
| `SCP_BACKUP_HOUR` | When the nightly copy is taken (hour, UTC). | `2` |
| `SCP_BACKUP_KEEP` | How many nightly copies are kept; the oldest go. | `14` |
| `SCP_SMTP_HOST` | Mail server for "forgot your password" links. None: no mail is sent, and a company owner (or the administrator) gives the link instead. | none |
| `SCP_SMTP_PORT` | | `587` (`465` with `ssl`) |
| `SCP_SMTP_TLS` | `starttls`, `ssl` or `none`. | `starttls` |
| `SCP_SMTP_USER`, `SCP_SMTP_PASSWORD` | The mail account. | none |
| `SCP_SMTP_FROM` | The sender address. | the user |
| `SCP_OIDC_ISSUER` | Single sign-on: your identity provider's issuer (OpenID Connect). None: no single sign-on. | none |
| `SCP_OIDC_CLIENT_ID`, `SCP_OIDC_CLIENT_SECRET` | The application registered with the provider. | none |
| `SCP_OIDC_NAME` | The button says "Sign in with …". | "your company account" |
| `OPENBLAS_NUM_THREADS` | Threads of the maths library per process. Leave it at 1: the forecast runs one process per core. | `1` |

Keep the secrets (`SCP_SMTP_PASSWORD`, `SCP_OIDC_CLIENT_SECRET`) out of the image: pass them with `--env-file`
or your platform's secrets.

### Mail

Any SMTP server works: your company's, or a sending service (Amazon SES, Postmark, SendGrid, Mailgun). For Microsoft
365 with an app password: `SCP_SMTP_HOST=smtp.office365.com`, `SCP_SMTP_PORT=587`, `SCP_SMTP_TLS=starttls`, the
mailbox as user and sender. The mail says where to set a new password (`SCP_PUBLIC_URL/#/account/reset/…`); the
link works once, for an hour. At most five are sent per address per hour.

Without mail, "Forgot your password?" tells the person to ask their company's owner: on *Account*, each planner and
viewer has *Link to set a new password* (valid a day), and the administrator can make one for anyone:
`python -m scp.admin reset-link person@example.com`.

### Single sign-on

Register a web application with your provider and give it the redirect address
`https://plan.example.com/api/auth/sso/callback` (your `SCP_PUBLIC_URL` followed by `/api/auth/sso/callback`),
scopes `openid email profile`. Then set:

* **Microsoft Entra ID**: `SCP_OIDC_ISSUER=https://login.microsoftonline.com/<tenant id>/v2.0`, the application
  (client) id and a client secret; `SCP_OIDC_NAME=Microsoft`.
* **Google Workspace**: `SCP_OIDC_ISSUER=https://accounts.google.com`, an OAuth client of type *Web application*.
* **Okta, Keycloak, Auth0, Authentik**: the issuer the provider shows (it serves
  `<issuer>/.well-known/openid-configuration`).

Only a verified e-mail address is accepted. A person signing in for the first time gets an account when
`SCP_SIGNUP` lets them (with `invite`: when a company owner invited that address); an existing account with the same
e-mail is the same person, whichever way they sign in.

## 3. The reverse proxy

The proxy adds HTTPS and must allow large requests and long answers: a company travels with each planning request
(a company of 5,000 products and 20 places is about 70 MB), and planning it takes minutes.

Caddy (`deploy/Caddyfile`):

```
plan.example.com {
	request_body {
		max_size 256MB
	}
	reverse_proxy 127.0.0.1:8000 {
		transport http {
			read_timeout 15m
			write_timeout 15m
		}
	}
}
```

nginx:

```nginx
server {
    listen 443 ssl http2;
    server_name plan.example.com;
    # ssl_certificate …; ssl_certificate_key …;
    client_max_body_size 256m;
    proxy_read_timeout 900s;
    proxy_send_timeout 900s;
    gzip on;
    gzip_types application/json;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

nginx's defaults (1 MB bodies, 60 s answers) refuse a medium-sized company's save and cut off its plan.

## 4. Backups and putting one back

With `SCP_BACKUP_DIR` set, the server copies the database there every night (`scp-YYYYMMDD-HHMMSS.sqlite`, a
consistent copy taken while people work) and keeps the newest `SCP_BACKUP_KEEP`. Copy that folder off the machine
as well (your backup tool, `rclone`, a storage bucket): a backup on the same disk does not survive the disk.

By hand, next to the running server (same `SCP_DB`):

```bash
docker exec scp python -m scp.admin backup /backups          # a copy now
docker exec scp python -m scp.admin check /backups/scp-20260927-020000.sqlite   # what it holds
```

To put one back, stop the server first; the database it replaces is kept beside it as `*.before-restore`:

```bash
docker stop scp
docker run --rm -v scp-data:/data -v /srv/scp-backups:/backups scp \
  python -m scp.admin restore /backups/scp-20260927-020000.sqlite
docker start scp
```

Everyone is then signed in as they were at the time of the copy, and every company is as it was then; each
company's *History* shows its saves up to that point.

Other administrator commands: `python -m scp.admin users` (the accounts and their companies),
`python -m scp.admin reset-link <e-mail>`.

## 5. Size of the machine

Measured on a 4-core machine with a generated company of 5,000 products at 20 places (two plants, eighteen
warehouses; 11,635 planning policies), two years of weekly sales history (624,000 rows) and 26 weeks of forecast
(156,000 rows): a 71 MB company.

| Step (as *Plan everything* runs them) | Time | Peak memory of the server process |
|---|---|---|
| Reading the company | 3.6 s | 1.4 GB |
| Data checks and network view (after each change) | 7 s each | 2.1 GB |
| Supply plan | 66–78 s | 5.5 GB |
| Forecast (6,000 series, 4 cores) | 136 s | 6.1 GB |
| Promising (the plan is kept, not made again) | 3 s | |
| Safety stock | 30 s | |
| Capacity (S&OP) | 14 s | |
| Schedule | 5 s | |
| Buying | 4 s | |
| Actuals | 9 s | |
| Money | 17 s | |
| Performance | 12 s | 6.7 GB |
| Saving a change (only what changed is sent) | 5–7 s | |

*Plan everything* takes about five minutes for a company that size; `engine/scripts/scale.py` measures your own
machine (`python scripts/scale.py --products 1000`).

So for a company that size: **4 cores and 8 GB of memory**, and one company planned at a time. The browser is the
limit before the server is: it receives every result whole (the supply plan alone is about 130 MB at 1,000 products),
so until results are sent in pages (the next phase), keep companies to a few hundred products. A company of a few
hundred products needs 2 cores and 2 GB. The database grows by about the company's size every 25 saves (each save
keeps only what changed, with a full copy every 25), so give the data volume some room and keep an eye on it.

Run **one** server process (`--workers 1`, as the image does): a save is checked against the company's latest
revision under a lock inside the process, and a second process would not see it. The forecast uses every core by
itself.

## 6. Updating

```bash
git pull && docker build -t scp . && docker stop scp && docker rm scp && docker run … (as above)
```

The database is upgraded on start (new tables and columns are added; nothing is removed). Take a backup before an
update: `docker exec scp python -m scp.admin backup /backups`.
