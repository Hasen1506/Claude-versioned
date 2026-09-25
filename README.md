# SCP: supply chain planning for small and mid-sized organisations

An SAP S/4HANA / IBP / Kinaxis-style planning system for a network you design yourself: locations, products,
bills of material, routings, suppliers and transport lanes, planned end to end from demand to delivery.

Everything lives in [`scp/`](scp/README.md):

| Path | What it is |
|---|---|
| [`scp/README.md`](scp/README.md) | How to run it, the stages, the API and how it is verified |
| [`scp/docs/BLUEPRINT.md`](scp/docs/BLUEPRINT.md) | Scope, data model, planning flow, correctness proofs and the phased roadmap (P0–P10) |
| `scp/engine` | Python engine and FastAPI service: validation, demand, inventory, S&OP LP, MRP/DRP, scheduling, promising, actuals, versions, finance, control tower |
| `scp/web` | React + TypeScript client: network designer and one numbered stage per planning step |
| `scp/examples` | Example networks (kitchenware, single-product plant) and the script that builds them |

## Quick start

```bash
cd scp/engine && pip install -e ".[dev]" && uvicorn scp.api.app:app --port 8000
cd scp/web && npm install && npm run build   # then open http://localhost:8000
```

CI (`.github/workflows/scp.yml`) runs ruff, pytest, the example reproducibility check, the API-type drift check,
the web typecheck and build, and the Playwright end-to-end suite.

The legacy Enterprise Simulator (Flask solvers, `app_v2/`, `index.html`, `design/`) was retired in favour of
`scp/`. It remains in git history at commit `176b26f`.
