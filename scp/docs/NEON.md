# Neon PostgreSQL for SCP

Configured 4 October 2026. The owner approved a fresh production database; no historical SQLite data is imported.

| Resource | Value |
| --- | --- |
| Neon project | `Claude Versioned` (`lucky-river-59434445`) |
| Region | AWS Singapore |
| Production branch | `br-super-rain-b3ighzk3` |
| PostgreSQL validation branch | `br-polished-violet-b3yl7asf` |
| Migration validation branch | `br-little-mouse-b3ba6m68` |
| Validation service | `claude-neon-validation` (`srv-db0rf9c9v7es73cncja0`) |
| Existing production service | `Claude-versioned` (`srv-d8alfsi8qa3s73eus3h0`) |

## Storage selection

Set server-only `DATABASE_URL` to the chosen branch's PostgreSQL URL, with `sslmode=verify-full`. The PostgreSQL driver uses certifi's CA bundle, verifies the hostname, supports the Neon pooler and accepts the provider's channel-binding parameter. The app uses its existing accounts and sessions; Neon Auth and the Data API are not enabled for this project. Never commit a real connection string.

When DATABASE_URL is absent, SCP_DB/local SQLite behavior is retained. An invalid or unreachable DATABASE_URL fails startup; it does not fall back to an ephemeral file. The application schema is `scp`, and requires CREATE SCHEMA and CREATE EXTENSION privileges for citext. Schema initialization takes an advisory lock. Existing SQLite SQL is adapted for bound PostgreSQL parameters, case-insensitive email columns and searches, generated IDs, binary revisions, double-precision worklist quantities, and immutable base-version triggers. Keep one uvicorn worker: the current Store shares one connection protected by an in-process lock, and some operations span multiple statements outside explicit transactions. Multi-worker or multi-instance writes require further transaction/connection refactoring.

SCP_BACKUP_DIR is SQLite-only and fails explicitly when combined with PostgreSQL. Back it up with `python -m scp.admin backup <folder>` (a consistent snapshot while the server runs; DEPLOY.md §4) and keep Neon's retained restore history as a second line; the free history window is limited.

## Validation

Forty-seven existing account, version, working-copy and recovery tests pass with SQLite, and changed files pass ruff. The isolated Render service executes `tests/postgres_smoke.py` during its build against the development branch. It verified case-insensitive sign-in, account isolation, compressed revisions, immutable base triggers, scenario promotion and persistence after reconnect. Signup is closed and sign-in is required on that validation API. It has no frontend build and is not the production app. Fictional fixtures remain on development branches only.

`tests/postgres_migration_smoke.py` checks a fictional SQLite source against the separate migration branch: dry-run rollback, full-field verification, binary revisions, version parents and refusal to overwrite a nonempty destination. Its execution is explicitly gated by SCP_POSTGRES_SMOKE=1 and a separate SCP_MIGRATION_TEST_URL. This variable is only for validation, never normal production startup.

## Fresh production cutover

The owner explicitly approved starting fresh on 4 October 2026. Production uses branch `br-super-rain-b3ighzk3`; fictional fixtures stay on development branches. No historical accounts, sessions, companies or versions are imported. Set the production DATABASE_URL privately on the existing Render service, retain its email/SSO/settings, and keep the full build (`pip install -e scp/engine && cd scp/web && npm ci && npm run build`) and single-worker uvicorn startup. Main auto-deploys this service. The old Enterprise Simulator services are unrelated to the active SCP deployment.

## Optional migration for other installations

For an installation that needs to preserve SQLite data, freeze writes and obtain a consistent backup using SQLite's online backup API or the existing admin backup command before redeploying an ephemeral host. With a backup and a private, empty destination URL:

```sh
pip install -e scp/engine
# DATABASE_URL is injected privately, never included in shell history or source control.
python -m scp.migrate_postgres backup.sqlite
python -m scp.migrate_postgres backup.sqlite --apply
```

The helper opens the source read-only, checks SQLite integrity, rejects unknown tables/columns and nonempty destinations, orders foreign keys and version parents, compares every copied field, and commits only after verification. Dry-run rows are rolled back; schema initialization remains. Sequence values may advance during validation. Preserve the backup. A post-cutover rollback must account for new PostgreSQL writes.
