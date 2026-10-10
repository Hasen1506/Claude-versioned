# Closing the gaps to enterprise planning tools

Written 10 October 2026, from the section-by-section benchmark against SAP S/4HANA with IBP, Kinaxis Maestro and o9
(and, below them, Netstock, Prediko, Odoo and frePPLe). Each phase is one pull request, built, used in the app the
guide's way (input → processing → output), logged in USABILITY_LOG and merged before the next starts. Items found
along the way go to IDEAS.md, not into the running phase.

Order: the live service first (nothing else matters if it is not safe to run), then the planning defects against the
S/4 guide, then what customers buy (connectors), then depth.

## Phase 1: Running it (production hardening)
| # | Gap | Build |
|---|---|---|
| 1.1 | One server process only: saves are checked under a lock inside the process | Save as a compare-and-swap in the database (`UPDATE … WHERE revision = ?`), one connection per request from a pool, idempotent schema setup; `--workers N` on PostgreSQL proven by a test with two processes saving at once |
| 1.2 | No monitoring | Request id and JSON logs, `/api/metrics` (requests, latency, plan runs, queue), an optional error-reporting DSN, the build commit in `/api/health` |
| 1.3 | No two-factor sign-in | TOTP with recovery codes, required per company by its owner; re-authentication for e-mail and password changes |
| 1.4 | No export or deletion of an account | Download everything an account holds; delete an account (companies it alone owns are handed over or deleted, said first) |
| 1.5 | Open settings on a live host | `SCP_ENV=production` refuses to start with open signup and no sign-in unless told so in a setting; the Render settings themselves are the owner's to change (DEPLOY.md lists them) |
| 1.6 | Backup restore never rehearsed on PostgreSQL | `scp.admin` dump and restore for PostgreSQL, and a test that restores into an empty database and opens every company |

## Phase 2: Planning defects against the S/4 guide
| # | Gap (guide §) | Build |
|---|---|---|
| 2.1 | A late firm order gets a duplicate requisition (§8.1) | Rescheduling horizon per product / MRP group: reschedule in first, new supply only beyond it; tolerance as a setting |
| 2.2 | Promises a day early where picking takes a day (§6.2) | Pick/pack and loading time at the shipping place, transport-planning time on the lane; material-availability and goods-issue dates on the promise |
| 2.3 | Only firming type 1 (§8.5); fences and GR time in calendar days | Firming types 2–4; fences and GR time in working days (a migration note for saved data) |
| 2.4 | DDMRP advises but does not plan (§8.7) | MRP type `ddmrp`: the buffer drives planned orders; red and yellow buffers in the inbox |
| 2.5 | Make-to-order supply can be taken by another order (§16.2, §9.2) | Sales-order stock and fixed pegging: a firm receipt assigned to one order is planned and issued only to it |
| 2.6 | Delivery does not re-check stock; imported lines re-priced; late open lines invisible in OTIF (§13, §15, §18.2) | Availability check at delivery creation, price frozen at goods issue, open-late count and value in the OTIF note |
| 2.7 | Allocation is one level; kits confirmed line by line; only EOQ beside fixed lots (§7.2, §7.4, §8.3) | Allocation hierarchy with carry-forward, single delivery for a whole order, part-period balancing / least unit cost / Groff |

## Phase 3: Connectors
| # | Gap | Build |
|---|---|---|
| 3.1 | No packaged connectors (Netstock lists 30+) | A connector framework on top of the existing keys and imports: mapping, dry run, schedule, message log |
| 3.2 | Indian SMEs live in Tally and Zoho | Tally Prime (XML over its HTTP port: masters, stock, vouchers) and Zoho Inventory (REST: items, stock, sales and purchase orders) |
| 3.3 | Online sellers and ERPs | Shopify (orders, stock, locations) and Odoo (JSON-RPC: products, BOMs, stock, orders); outbound purchase and production orders to each |

## Phase 4: Demand and S&OP depth
| # | Gap (guide §) | Build |
|---|---|---|
| 4.1 | No consensus cycle (§4) | A monthly S&OP cycle: data → demand review → supply review → pre-S&OP → executive, each with an owner, sign-off and a frozen snapshot; volume and revenue against budget |
| 4.2 | No forecast value add | Accuracy and bias of the statistical forecast against each override layer, per planner and product group |
| 4.3 | Variants forecast one by one (§5, strategies 60/63, 70) | Planning material: one base forecast consumed by its variants with a factor; a sub-assembly forecast consumed by dependent demand; a strategy advisor from lead times |
| 4.4 | One demand number (no spread) | P90 demand and promise against it; measured supplier lead-time deviation fed into safety stock |

## Phase 5: Speed and an assistant
| # | Gap | Build |
|---|---|---|
| 5.1 | 66–78 s supply plan at 5,000 × 20 | Incremental planning: re-plan only the parts of the network a change reaches (by low-level code and component), cache the rest; target under 15 s for a single change |
| 5.2 | No AI assistant (every leader shipped agents in 2026) | "Ask the plan": a question answered from the plan's own records (why late, what if, who owns), each answer citing the items; proposes one-click fixes that a person keeps |
| 5.3 | What-if smaller than the leaders' | Sweep one chip (cost against service), stored versions as columns, money at risk over time |

## Phase 6: Warehouse and transport (EWM and TM, small)
| # | Gap (guide §) | Build |
|---|---|---|
| 6.1 | No bins (§12.2–12.3) | Storage types and bins, put-away rules, pick lists by bin and waves, a phone page that reads a barcode |
| 6.2 | One planned price; no cycle counts (§12.4) | Moving-average valuation with price differences from invoices; ABC cycle counting |
| 6.3 | No transport planning (§14) | Carriers, freight orders that group deliveries, load building by weight and volume, freight cost and its settlement |

## Phase 7: Wider supply and money
| # | Gap (guide §) | Build |
|---|---|---|
| 7.1 | No drop-ship; job work only adds days (§16.3, §10.1) | Third-party orders; job-work subcontracting with parts sent out as stock at the supplier (GST job-work challan) |
| 7.2 | Suppliers confirm by mail only | Supplier portal: a signed link to confirm or change a PO line; order and dispatch messages in a standard format |
| 7.3 | One company per network (§17.5) | Several companies in one network with inter-company orders and transfer prices |
| 7.4 | No accounting shadow (§15.1) | A double-entry journal from movements and invoices (stock, GR/IR, receivables, payables, COGS), exported to Tally |

## Pause points
The work stops after each phase (and inside a phase after every two or three items) with everything committed,
pushed and the PR updated, so the conversation can be compacted without losing anything.
