# Deploying to Render

This app is a **single Flask web service**. `app.py` serves the API *and* the
frontend (the `app_v2/` build) from one process — there is no separate static
site, no build step (the `.jsx` is compiled in the browser by Babel-standalone).
So you deploy **one** Render service.

---

## Web Service vs Blueprint — which one?

Both end up creating the same kind of thing (a "Web Service"). The difference is
*how* it gets configured:

| | **Blueprint** (recommended) | **Web Service** (manual) |
|---|---|---|
| Config source | `render.yaml` in the repo | typed into the dashboard |
| Reproducible | ✅ in git, reviewable | ❌ lives only in Render's UI |
| Multiple services | ✅ one file defines all | one service per manual setup |
| When to use | you have a `render.yaml` (we do) | quick one-off, no IaC |

**Use Blueprint.** We already have `render.yaml`, so Render will read the build
command, start command, health check, and env vars from it — nothing to type by
hand, and the config is version-controlled. "Web Service (manual)" would *ignore*
`render.yaml` and make you re-enter everything in the UI.

---

## Steps (Blueprint)

1. **Push the repo to GitHub** (Render deploys from a connected git repo):
   ```bash
   git push origin main
   ```
2. In the Render dashboard: **New +  →  Blueprint**.
3. **Connect the repository** (authorize GitHub if first time) and pick this repo
   + the `main` branch.
4. Render parses `render.yaml` and shows the service it will create
   (`enterprise-simulator`, Python, starter plan). Click **Apply**.
5. *(Optional)* If you use the Claude `/api/ai/*` endpoints, open the service →
   **Environment** → set `ANTHROPIC_API_KEY`. It is declared `sync: false` in
   `render.yaml` precisely so the key is **never committed** — you paste it in the
   dashboard. The app runs fine without it (those endpoints just return an error
   if called).
6. First build runs `pip install -r requirements.txt`, then
   `gunicorn app:app …`. Watch the log; wait for `Booting worker`.
7. Open the service URL. You should get the **app_v2** UI. Render hits
   `/api/health` for the health check; you can too:
   ```
   https://<your-service>.onrender.com/api/health   →  {"status":"ok", ...}
   ```

The legacy monolith is parked at `…/legacy` for comparison and is otherwise
unused.

---

## Steps (manual Web Service — only if you skip the blueprint)

**New +  →  Web Service**, connect the repo, then type:

- **Runtime:** Python 3
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120`
- **Health Check Path:** `/api/health`
- **Environment variable:** `PYTHON_VERSION = 3.11.0` (and optionally `ANTHROPIC_API_KEY`)

---

## Notes / gotchas

- **One service, not two.** Don't add a separate "Static Site" for the frontend —
  Flask serves `app_v2/` itself (`static_folder='app_v2'` in `app.py`). A static
  site would have no API to call.
- **`$PORT` is mandatory.** Render injects `PORT`; gunicorn must bind it (it does).
  Binding a hardcoded `5000` will fail the health check.
- **Cold starts** on the free/starter plan: the first request after idle can take
  ~30–60s while the instance spins up. The MILP `--timeout 120` covers long solves.
- **`Procfile`** mirrors the same start command, so Heroku-style platforms work too;
  Render uses `render.yaml`'s `startCommand`.
- **CBC solver** ships inside the `pulp` wheel — no extra system package needed.
- **Local sanity check before pushing:**
  ```bash
  gunicorn app:app --bind 0.0.0.0:5000 &
  curl -s localhost:5000/api/health
  curl -s localhost:5000/ | head -1      # → <!doctype html>
  curl -s localhost:5000/lib.jsx | head -1
  ```
