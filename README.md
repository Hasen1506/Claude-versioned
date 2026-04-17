# Enterprise Simulator v2.0

Production-grade supply chain optimization platform. 7 MILP/LP solvers, 17 forecast models, Monte Carlo VaR/CVaR, and full financial analytics. Render-deployable.

## Quick Start
```bash
pip install -r requirements.txt
python app.py
# Open http://localhost:5000
```

## Deploy to Render
1. Push to GitHub
2. Connect repo at render.com → auto-detects render.yaml
3. Starter plan ($7/mo) — sufficient for all solvers

## 7 Solver Engines

| # | Solver | Objective | Key Output |
|---|--------|-----------|------------|
| 1 | **Procurement** | Min inventory + ordering cost | PO schedule, cost breakdown |
| 2 | **Production Scheduler** | Min setup + overtime + makespan | Gantt chart, line utilization |
| 3 | **Profit Maximizer** | Max contribution margin | Optimal mix, **shadow prices** |
| 4 | **Transport** | Optimal mode + allocation | Mode selection, spike alerts |
| 5 | **Capital Budget** | Max portfolio NPV | Buy/lease decisions, PI ranking |
| 6 | **Monte Carlo** | Risk distribution (1000 runs) | VaR₉₅, CVaR₉₅, fragility |
| 7 | **Pipeline** | Profit→Procurement→Production | End-to-end chained optimization |

## 17 API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/health` | Server status |
| `POST /api/solve/procurement` | MILP procurement optimizer |
| `POST /api/solve/production` | MILP production scheduler + Gantt |
| `POST /api/solve/profitmix` | LP profit maximizer + shadow prices |
| `POST /api/solve/transport` | Mode selection + demand sensing + allocation |
| `POST /api/solve/capital` | Capital budget portfolio optimizer |
| `POST /api/solve/pipeline` | Chained: Profit → Procurement → Production |
| `POST /api/solve/montecarlo` | 1000-run stochastic simulation |
| `POST /api/solve/sensitivity` | Parameter sweep + tornado chart |
| `POST /api/solve/researcher` | 200-experiment auto-optimizer |
| `POST /api/calc/landed-cost` | Indian import duty calculator |
| `POST /api/calc/npv` | NPV/IRR/payback calculator |
| `POST /api/calc/depreciation` | SLM/WDV/UoP depreciation |
| `POST /api/calc/wacc` | Weighted average cost of capital |
| `POST /api/report/pdf` | PDF report generator |
| `POST /api/whatif` | What-If Bot (NLP scenario interpreter) |

## 7 Frontend Tabs

1. **Setup** — Company, WACC, service level, planning horizon, production lines
2. **Products & Demand** — 17 forecast models, BOM (backup suppliers, sub-contracting), demand sensing, events, MTO, cost events, CSV import/export
3. **Supply Network** — Supplier master, landed cost calculator, Incoterms reference
4. **Finance & Costs** — NPV/IRR, WACC, depreciation (3 methods), buy vs lease, asset register, hedging, CCC, cash flow timeline
5. **Optimize & Solve** — 7 solver modes, dynamic constraint toggles, ATP/CTP, scenario save/load, MILP export
6. **Analysis & Reports** — MC VaR/CVaR, tornado chart, auto-researcher, What-If Bot, EVM tracker, S&OP gap, network map, TCO waterfall, PDF export
7. **Learning Lab** — 21 interactive sections + Probability Lab

## Codebase: 4,169 lines across 17 files
```
app.py (400 lines)           — Flask server + 17 API routes
static/index.html (2,169)    — React SPA
solvers/
  procurement.py (358)       — MILP: min procurement cost
  production.py (220)        — MILP: min makespan + setup
  profitmix.py (177)         — LP: max contribution margin
  transport.py (159)         — Mode selection + allocation
  capital.py (158)           — Binary LP: max portfolio NPV
  montecarlo.py (135)        — Stochastic simulation
  finance.py (228)           — NPV, landed cost, depreciation, WACC
  report.py (165)            — PDF report generator
```
