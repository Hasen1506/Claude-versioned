# SCP: supply chain planning for small and mid-sized organisations

An SAP S/4HANA / IBP / Kinaxis-style planning system you run on your own network: model locations, products,
bills of material, routings on machines and labour, suppliers and transport lanes, check the data, and plan
it end to end.

**Read [`docs/BLUEPRINT.md`](docs/BLUEPRINT.md) first.** It covers the scope, the data model, the planning
flow, how correctness is proven, and the phased roadmap. This directory is independent of the legacy app in
the repository root.

## Run it

```bash
# engine + API (Python ≥ 3.11)
cd scp/engine
pip install -e ".[dev]"
uvicorn scp.api.app:app --port 8000      # serves the API, and the web client once it is built

# web client (Node ≥ 20)
cd scp/web
npm install
npm run build                            # then open http://localhost:8000
# or, for development with hot reload:
npm run dev                              # http://localhost:5173 (proxies /api to :8000)
```

Start from an example (a fictional multi-echelon appliance maker, or a one-product plant), create a blank
network, or import a dataset JSON. The dataset is saved in your browser and can be exported at any time.

## What is here (P0 + P1)

| Area | Where | What it does |
|---|---|---|
| Data model | `engine/scp/model` | Typed master and transactional data. Fractions are 0–1, and quantities are in base UoM. Units are enforced by the schema, not by convention. |
| Readiness gate | `engine/scp/validate` | 24 coded master-data checks with fix hints. Errors block planning. |
| Network | `engine/scp/network` | Supply options per (location, product), low-level codes across BOM and transport edges, cycle detection. |
| Supply planning | `engine/scp/plan` | Network MRP/DRP: forecast consumption by strategy, PIR splitting, safety stock (fixed / coverage / α / β), lot sizing (L4L / FIXED / EOQ / POQ / MIN_MAX + MOQ / rounding / max split), quota sourcing, working-day scheduling, firming fence, BOM explosion with scrap, capacity / supplier / lane load, pegging, delay propagation, exceptions, cost KPIs. |
| API | `engine/scp/api` | `examples`, `schema`, `rules`, `validate`, `network`, `plan` |
| Web | `web/src` | Network map with product trace, schema-generated editors with undo/redo, readiness, and the plan workspace: KPIs, the stock/requirements view, capacity, and orders with a pegging tree. |

## How correctness is checked

```bash
cd scp/engine && python -m pytest -q                 # 116 tests
cd scp/web && npm run gen:api && git diff --exit-code src/api/schema.d.ts   # UI types == engine
cd scp/web && npm run build && npx playwright test   # end-to-end in a real browser
```

- **Types:** invalid values cannot be constructed. The API answers 422 and names the field.
- **Readiness rules:** each rule has a test that makes it fire and a clean dataset that passes.
- **Golden scenarios:** hand-computed MRP cases, covering netting, lot sizing, scrap, working days, fences,
  quotas, transfers, MTO/ATO and reorder point.
- **Plan invariants:** material balance, pegging, requirement sizing and date order. These are checked on the
  examples and on 40 randomly generated networks.
- **CI** runs all of it (`.github/workflows/scp.yml`).

Regenerate the examples with `python scp/examples/build_examples.py`. CI checks that they are reproducible.
