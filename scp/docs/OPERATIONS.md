# Authoritative live operations

`POST /api/companies/{company}/commands` executes an operation against the saved company. It accepts parameters, an explicit business date, a base revision and a stable command identifier. It never accepts a caller's replacement dataset. Membership, plant/family scope, named business grants and persisted transaction invariants all apply.

```json
{
  "id": "bank-event-7297",
  "base_revision": 7,
  "posting_date": "2026-11-17",
  "kind": "purchasing",
  "action": "pay_invoice",
  "parameters": {
    "po": "SI-00001",
    "amount": 1100,
    "reference": "BANK-7297"
  }
}
```

Supported kinds are `purchasing`, `sales`, `stock`, `transport`, `intercompany` and `outside`. Their actions and parameters use the existing action request schemas. `dataset`, `action` and `date` are not parameters: the company and action are selected by the command, and `posting_date` supplies the operation's date. This avoids silently posting on the start date of a planning scenario. The invoice model currently shares document and accounting dates; separate ERP document/posting-date semantics remain a finance fit-gap item.

The operation reads authoritative state and commits its company effects, revision, audit trail and receipt in one database transaction. It refuses a stale base revision. It also refuses the whole operation if it needs a master-data change still awaiting approval; physical effects do not commit while a required master change is held. Invalid/incomplete saved data must be completed before executing a live command.

After a lost response, reuse the **same id, posting date and parameters**. A completed command returns `duplicate: true` without executing again. Reusing its id with different business input returns 409. A failed/rolled-back command has no completed receipt and can be retried. Concurrent identical calls produce one effect; distinct commands based on the same stale revision cannot both commit.

The response's `revision` identifies the original completed command. Its `company.meta.revision` and `company.dataset` identify the **current** saved company, including intervening operations. Use the latter to update a working view. A replay never returns an old company snapshot that could resurrect stock or remove a later payment.

`GET /api/companies/{company}/commands?id=bank-event-7297` reconciles completion without issuing another mutation. The receipt retains the original parameters, business date, result, actor, request hash, revision and build commit. Company membership and any required second sign-in step protect this read. The account-data export includes the account's own commands; database backups and migrations include receipts.

The typed browser API client exposes `companyCommand` and `companyCommandRecord`. Existing planning/scenario action APIs and the browser's preview/edit/save workflow remain compatible. Their company saves continue to enforce transaction rules. The new endpoint provides an authoritative operation contract for live integrations; its existence does not imply that every legacy screen has been migrated to command execution.

## Business authorization

An empty `finance.control_roles` matrix preserves legacy owner/planner/viewer semantics. Once configured, omitted grants deny that operation, including for owners and keys. Configure and independently test the approved matrix before relying on separation of duties. Owners administer policy but do not bypass operational grants. `finance.separate_payments` requires a payer different from the recorded invoice entrant and releaser. Unknown legacy entrants require reviewed migration evidence.

Available grants are `master_data`, `planning`, `purchasing`, `sales`, `manufacturing`, `warehouse`, `transport`, `billing`, `payments`, `invoice_release`, `credit_release`, `period_close` and `inventory_adjustment`. The last covers opening balances, adjustments, scrap and unplanned receipts; a warehouse picking grant alone does not authorize those effects. An operation touching several departments can require several grants. Server-validated posting metadata does not grant authority over another department's business fields.

Plant/product-group limits further restrict changes. Existing and proposed product-family ownership are checked separately, so changing a family cannot widen the same write's rights. Physical inventory documents must stay wholly inside the member's plants and product groups. These are write limits; they do not establish departmental confidentiality over every company read model.

## Retained physical facts

Existing posted material facts and their same-day posting order are retained. Stock-status transfers conserve quantity. A blocked physical count refuses other postings until posted or cancelled; its frozen book and material differences are checked against server-derived quantities. Completed count documents cannot be rewritten or removed.

Serialised movements require one serial per whole unit. A serial cannot be held in multiple places or stock types, issued from a place that does not hold it, or issued before receipt. Atomic transfer/status documents can move a serial between places/types. Its serial profile cannot be disabled while stock remains. Invalid legacy serial/opening data needs controlled migration rather than fabricated history.

Known currencies requiring other than two decimal places remain blocked for financial posting and ledger export. This prevents silent misstatement; it does not implement full currency/minor-unit/rounding support. Statutory finance, reference-system outcomes, representative performance, real interface certification and infrastructure recovery still require the independent acceptance described in `ENTERPRISE_READINESS.md`.

## Outside work and reversals

The `outside` command kind accepts the existing outside-action schema: `send_parts`, `back_processed`, `back_unused`, `write_off`, `cancel_challan`, and direct-ship order/send/dispatch actions. It uses the command's explicit business date, authoritative company state, revision check and atomic retry receipt. Retried dispatch does not replace intervening receipts or billing.

Sent job-work quantities, values, parties, source order, charge and original custody events are retained. Unused returns and cancellation require matching material reversals; a worker cannot consume, lose or return more than was sent. Closed/cancelled records cannot reopen. Loss requires both manufacturing and inventory-adjustment authority. Sending a direct-ship supplier order additionally requires purchasing authority when the matrix is configured.

A custody event cannot precede dispatch or an earlier recorded return. When a legacy action omits its date, its fallback is at least the most recent custody event, rather than silently preceding dispatch at the planning epoch. Explicit dated custody views exclude future returns and cancellations; their planning-worklist section still describes the current scenario. Period dispatch rows retain a challan cancelled after the requested period. These behaviors do not establish statutory acceptance of the generated forms or complete snapshots of jurisdiction-specific party/product tax master data.

A reversal retains its original material identity and cumulative reversals cannot exceed the original quantity. The journal now reverses the actual original contra account as well as stock, including balancing WIP/COGS/scrap/count entries. This corrects previously misclassified derived reports: reconcile existing reversal periods and obtain controller acceptance before replacing previously approved external books. Source movements and invoices are retained; unknown legacy facts are not fabricated.
