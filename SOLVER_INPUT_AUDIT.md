# Solver-Input Audit — are the inputs right, and are the solvers correct?

Date: 2026-06-03. Scope: the app_v2 frontend ↔ the Python solvers at repo root.
Question answered (your two asks): **(1) is every input the solvers need actually
enterable, and (2) are the solvers themselves correct — do we even *need* as many
inputs, or are some just noise we copied forward?**

## TL;DR

- The **solvers are correct.** yield / scrap / salvage / shelf-life / expiry are all
  real, properly-modelled levers with sound math. This was *not* a solver-accuracy
  problem.
- The real gap was **plumbing**: several genuine levers were **hard-coded in the JS
  payload** (`salvage_rate:0.8`, `scrap_factor:0.01`) or **display-only** (yield,
  shelf), so the user could not set them even though the solver reads them.
- We did **not** blindly wire up every field. We graded each input by whether it
  changes an answer for this dataset, and exposed accordingly (below).
- One genuine **correctness bug** was found and fixed (shelf-life unit mismatch in
  the profit-mix payload — see §3).

---

## 1. How the loss/expiry levers are actually defined (the correct mental model)

These four are easy to conflate. They are distinct and the solvers model them as
distinct:

| Lever | Granularity | Means | Where it bites |
|---|---|---|---|
| **yield_pct** | per **product** | fraction of *started* units that come out good | grosses up units to start → more material + more machine-hours. `effective_qty = qty·(1+scrap)/yield`. Always active. |
| **scrap_factor** | per **part** | fraction of *that part's material* lost in conversion (chips, offcuts) | grosses up material to buy, independent of yield. Small (≈1%) but real. |
| **shelf_life** | per **product** | periods a finished unit can be held before it expires | gates whether expiry happens at all. |
| **salvage_rate** | per **product** | fraction of a unit's make-cost recovered when expired/excess stock is scrapped | sets the **size** of the write-off: `writeoff/unit = (var+material)·(1−salvage)`. |

Key correctness fact (verified in `montecarlo.py`, `profitmix.py`, `procurement.py`):
**expiry only occurs when `shelf_life < planning_horizon`.** For this dataset the
finished goods have 365–730 day shelf lives against a ~52-week horizon, so expiry
(and therefore salvage) is **inert for 5 of 6 SKUs** — only TPA-7722 (180 d) is
short enough to ever spoil in-horizon.

So the honest answer to *"do we need as many inputs?"* is **no** — salvage and
shelf-life should **not** be scattered as a field on every product row, because
they'd be dead inputs for almost every SKU. yield is the lever that always matters.

---

## 2. Where each input is exposed now (the disciplined result)

- **yield %** — promoted to a first-class, editable per-SKU field (Products → "Yield
  & expiry"), and shown as a live column in the catalog. It drives every solve, so
  it leads.
- **shelf-life (days)** — editable per-SKU in the same card, with a live readout of
  whether expiry is **ACTIVE or inactive** at the current horizon (honest: tells you
  when the value is inert).
- **salvage %** — editable per-SKU but governed: the card states plainly when it is
  a no-op for that SKU (shelf ≥ horizon) so it isn't mistaken for a live knob.
- **scrap %** — editable per-part in the BOM "Advanced" disclosure (it's a per-part
  property, not per-product), with the `qty·(1+scrap)/yield` formula shown.

All four were previously: yield/shelf = display-only; salvage/scrap = buried JS
constants. They now flow to the solvers through the live master (`window.M`), which
every payload builder already reads — so one edit reaches procurement, profit-mix,
production and Monte-Carlo at once, and flags the dependent solves stale.

---

## 3. Correctness bug found + fixed

`console.jsx · profitmixPayload` passed `shelf_life: p.shelf` **in days**, but
`profitmix.py` treats `shelf_life` as **weeks** (`shelf_weeks / (52/12)` → months,
compared to the horizon). A 365-day shelf was read as 365 *weeks* (~84 months), so
the expiry-write-off term **never activated** in profit-mix. Fixed to convert
days→weeks (matching the Monte-Carlo builder, which was already correct) and to pass
`yield_pct` + `salvage_rate`. Verified: profit-mix still returns `Optimal`; the
expiry term is now reachable when shelf < horizon.

---

## 4. Solver-by-solver verdict

| Solver | Correct? | Notes |
|---|---|---|
| `montecarlo.py` | ✅ | FIFO/FEFO cohort aging, expiry write-off net of salvage, yield grossing cost on units *started*, stochastic lead-time lag — all sound. |
| `profitmix.py` | ✅ (after §3) | true LP (CBC), margin + over-production holding + expiry penalty, shadow prices/reduced-costs/crossover. Unit bug in the *payload*, not the solver. |
| `procurement.py` | ✅ | `effective_qty = qty·(1+scrap)/yield`, FIFO expiry vars, yield carry-forward credit. scrap & yield correctly separated. |
| `production.py` | ✅ | compound route yield (Π of per-op yieldPct), line-level OEE not inherited across lines. |

**Conclusion:** the solvers did not need correcting; the *inputs* needed to be
addressable and one payload had a unit bug. We resisted adding inputs that would be
inert for this dataset and instead surfaced the live levers honestly.
