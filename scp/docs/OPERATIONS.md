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

Supported kinds are `purchasing`, `sales`, `stock`, `transport`, `intercompany`, `outside` and `production_cost`. Business parameters describe the event. The envelope supplies the company, action and explicit posting date. The invoice model currently shares document and accounting dates; separate ERP document/posting-date semantics remain a finance fit-gap item.

## Recovering after a release

A binary rollback and a database restore are separate operations. Releases from `6f97187` can write `purchase_valuation` into saved companies. Release `8a5b6ba` rejects that field when it validates an upgraded document. A hotfix that retains the current schema can continue to read those company records. If an older binary is necessary, first validate a pre-upgrade backup with that binary in an isolated environment. The restored database represents the moment of the backup.

1. Keep a copy of the current database and identify the snapshot boundary. Pause writers before a production recovery or traffic switch, including queued integrations.
2. Inventory the transactions and authorized changes after that boundary. For authoritative commands, preserve their original IDs, business dates, parameters, company and actor. Identify any actions already performed by banks, suppliers or other external systems separately from their ERP entries. Legacy document saves and other effects require reconciliation from their own records.
3. Restore into an isolated database first. Verify receipts for transactions already in the snapshot. Replay eligible missing commands in recorded order with the current restored revision. A retry uses the original command ID, date and parameters. Stop on any conflicting result or unexplained balance.
4. Reconcile company revisions, physical quantities, invoices, clearing accounts, command receipts and external records. Reopen writers after acceptance against those records.

The supplier invoice recovery test in `engine/tests/test_advance_cancellation.py` restores an isolated backup, detects the advance invoice already present, then replays the missing cancellation and receipt. It compares the final saved dataset and literal ledger balances to the uninterrupted path, and checks that retry adds no revision or command record. The check runs with SQLite and with PostgreSQL when the test fixture is configured. Production recovery still depends on a complete transaction inventory, a production-like restore exercise and measured recovery objectives.

The operation reads authoritative state and commits its company effects, revision, audit trail and receipt in one database transaction. It refuses a stale base revision. It also refuses the whole operation if it needs a master-data change still awaiting approval; physical effects do not commit while a required master change is held. Invalid/incomplete saved data must be completed before executing a live command.

After a lost response, reuse the **same id, posting date and parameters**. A completed command returns `duplicate: true` without executing again. Reusing its id with different business input returns 409. A failed/rolled-back command has no completed receipt and can be retried. Concurrent identical calls produce one effect; distinct commands based on the same stale revision cannot both commit.

The response's `revision` identifies the original completed command. Its `company.meta.revision` and `company.dataset` identify the **current** saved company, including intervening operations. Use the latter to update a working view. A replay never returns an old company snapshot that could resurrect stock or remove a later payment.

`GET /api/companies/{company}/commands?id=bank-event-7297` reconciles completion without issuing another mutation. The receipt retains the original parameters, business date, result, actor, request hash, revision and build commit. Company membership and any required second sign-in step protect this read. The account-data export includes the account's own commands; database backups and migrations include receipts.

The typed browser API client exposes `companyCommand` and `companyCommandRecord`. Existing planning/scenario action APIs and the browser's preview/edit/save workflow remain compatible. Their company saves continue to enforce transaction rules. The new endpoint provides an authoritative operation contract for live integrations; its existence does not imply that every legacy screen has been migrated to command execution.

Live settlements use `sales/pay` for customer receipts and refunds and `purchasing/pay_invoice` for supplier payments and refunds. The UI confirms after the server commits. If confirmation is lost, reopen the invoice or credit note in the same tab and select **Retry payment**. This reuses the original command ID, posting date, amount and reference, even if the invoice already shows as settled. If the tab is gone, reconcile the document and command receipt before entering another payment. Bank integrations should derive the command ID from the source transaction and allocation identity. The displayed bank reference is descriptive, and the app records the accounting event.

Live freight settlement uses `transport/settle` with the freight order, posting date, billed amount and the carrier's bill number. With a configured grant matrix, dispatch uses `transport` and booking the payable requires `billing`. The date must fall on or after shipment and in an open period. If confirmation is lost, use **Retry bill** on the freight order in the same tab. The payable books once, in the shipping company's books for outbound freight and the receiving company's books for a collection. The total cost allocation reconciles to the booked amount to the cent. An active carrier bill number identifies one bill in that carrier's account for the paying company, regardless of case or surrounding spaces. New bills preserve the booking identity and the due date calculated when posted. Existing bills without a saved due date use current carrier terms.

On a settled freight order, **Record carrier credit** posts a full credit backed by the carrier's credit number. `transport/credit` requires the original journal voucher in `credit_of`, the carrier credit reference in `bill`, a reason and an explicit open posting date on or after the original bill. The amount follows the original voucher. **Retry credit** reuses that request after lost confirmation. The original voucher remains on its date and the reversal appears on the credit date. The shipment is eligible to be billed again with a new voucher. A full credit removes the remaining bill from the cash forecast until a replacement is booked. A bill with any recorded payment requires AP reconciliation before correction. Partial credits and refunds after payment require an external adjustment process.

Use **Buying → What we owe → Carrier bills** to record a verified bank disbursement. The command is `transport/pay_bill` with the freight `order`, its reviewed `voucher`, `amount` in company currency and the bank `reference`. An omitted amount clears the saved open balance. The command requires an open posting date on or after the bill. It debits carrier AP and credits Bank. The AP list and cash forecast show the remaining liability after a partial payment. In the configured grant matrix the `payments` grant authorizes the operation. With `finance.separate_payments`, the bill entrant cannot also pay it. A legacy bill without a reliable entrant requires reconciliation before payment under this control.

After a lost confirmation, use **Retry payment** on the same bill in the same tab. This reuses the original command identifier and its inputs. A second command with the same bank reference against the same voucher is refused. One bank transaction split across different bills can carry the same bank reference. Each allocation needs a distinct stable command identifier. The app records the accounting event after bank confirmation. Carrier service matching, consolidated invoices, bank statement reconciliation and capitalization into the received stock remain separate fit items.

Saved freight orders can now contain `bill_credits`, `bill_due_on`, `bill_entered_by` and `bill_payments`. Restore with a release that can read the saved fields and replay the original command, date and parameters. An older release requires pre-upgrade data and a reconciliation plan for activity after that backup.

## Business authorization

An empty `finance.control_roles` matrix preserves legacy owner/planner/viewer semantics. Once configured, omitted grants deny that operation, including for owners and keys. Configure and independently test the approved matrix before relying on separation of duties. Owners administer policy but do not bypass operational grants. `finance.separate_payments` requires a payer different from the recorded invoice entrant and releaser. Unknown legacy entrants require reviewed migration evidence.

Available grants include `master_data`, `planning`, `purchasing`, `sales`, `manufacturing`, `warehouse`, `transport`, `billing`, `payments`, `invoice_release`, `credit_release`, `period_close`, `production_cost` and `inventory_adjustment`. The inventory adjustment grant covers opening balances, adjustments, scrap and unplanned receipts. An operation touching several departments can require several grants.

Plant/product-group limits further restrict changes. Existing and proposed product-family ownership are checked separately, so changing a family cannot widen the same write's rights. Physical inventory documents must stay wholly inside the member's plants and product groups. These are write limits; they do not establish departmental confidentiality over every company read model.

## PostgreSQL company writes

Company document reads, saves, merges and business commands use a company-specific advisory lock. They use a dedicated connection through authorization, validation, revision checks and commit. Independent companies can write concurrently. The process admits one waiter at a time for the same company before assigning a connection. Credential checks use their own scope. A server process can open four scoped connections in addition to its global connection. Include those connections when sizing the database.

The global advisory lock still protects operations that span companies or use global identifiers, such as account administration, schema setup and version allocation. Scoped connections hold the global lock in shared mode. This coordinates with existing server processes taking the exclusive lock and preserves global exclusion during changes to membership. SQLite retains its file lock. The deployment's PostgreSQL endpoint must preserve session advisory locks. The concurrency tests verify independent authenticated HTTP writes, same-company conflicts and idle-connection recovery.

## Production cost and period close

Use Accounts → Production WIP in a live company. The order shows material issues, receipts, subcontract charges and production cost postings in the books through the selected date. The manufacturing order and plant appear on the WIP report. The journal retains the order link on each WIP line. The period close checks each completed order separately. Open orders can carry WIP, and a reopened order with an active settlement requires review.

Record actual internal conversion in company currency with the payroll, machine or other source reference. The `production_cost` command's `conversion` action takes `order`, `reference` and integer `amount_minor`. This debits WIP and credits `CONVERSION_ABSORPTION`. Capture the underlying expenditure in its source ledger. The planner's rates contribute to inventory estimates and create no conversion posting.

Once the order is complete, reconcile materials, actual conversion and subcontract bills. `settle` takes `order`, `reference` and `confirm_actuals: true`. It clears the derived WIP balance to `PRODUCTION_VARIANCE`. An open order or an order carrying WIP in another entity requires separate reconciliation. A later correction can use `reverse` with the original posting ID as `posting`, followed by new postings in the open period. Posted cost records stay in the audit trail. Review the ledger mappings for conversion applied and production variance before exporting.

Give the cost accountant the `production_cost` grant and the period approver the `period_close` grant. With an empty matrix company owners can post and close. Use a current reader for company snapshots with the new `production_cost_postings` field. Reuse the command ID during recovery to regenerate the same document number and keep any later reversal linked to its original. Reconcile postings and command receipts after restoring.

## Retained physical facts

Existing posted material facts and their same-day posting order are retained. Stock-status transfers conserve quantity. A blocked physical count refuses other postings until posted or cancelled; its frozen book and material differences are checked against server-derived quantities. Completed count documents cannot be rewritten or removed.

In a live company, save the reviewed physical counts before posting differences. **Post differences** includes the saved quantities and the count date in the company command. The server checks them against the current count document. Warehouse and inventory adjustment grants control the material effect. The resulting planning on-hand projection comes from the journal and is saved with the count. After an interrupted confirmation, open Physical inventory and select **Check posting** for the available document to look up its command receipt.

Serialised movements require one serial per whole unit. A serial cannot be held in multiple places or stock types, issued from a place that does not hold it, or issued before receipt. Atomic transfer/status documents can move a serial between places/types. Its serial profile cannot be disabled while stock remains. Invalid legacy serial/opening data needs controlled migration rather than fabricated history.

Known currencies requiring other than two decimal places remain blocked for financial posting and ledger export. This prevents silent misstatement; it does not implement full currency/minor-unit/rounding support. Statutory finance, reference-system outcomes, representative performance, real interface certification and infrastructure recovery still require the independent acceptance described in `ENTERPRISE_READINESS.md`.

The company currency stays fixed once financial or stock postings exist, including imported customer invoices without a stock history. A currency change with existing books requires a controlled migration and independent reconciliation of opening and comparative balances.

## Outside work and reversals

The `outside` command kind accepts the existing outside-action schema: `send_parts`, `back_processed`, `back_unused`, `write_off`, `cancel_challan`, and direct-ship order/send/dispatch actions. It uses the command's explicit business date, authoritative company state, revision check and atomic retry receipt. Retried dispatch does not replace intervening receipts or billing.

Sent job-work quantities, values, parties, source order, charge and original custody events are retained. Unused returns and cancellation require matching material reversals; a worker cannot consume, lose or return more than was sent. Closed/cancelled records cannot reopen. Loss requires both manufacturing and inventory-adjustment authority. Sending a direct-ship supplier order additionally requires purchasing authority when the matrix is configured.

A custody event cannot precede dispatch or an earlier recorded return. When a legacy action omits its date, its fallback is at least the most recent custody event, rather than silently preceding dispatch at the planning epoch. Explicit dated custody views exclude future returns and cancellations; their planning-worklist section still describes the current scenario. Period dispatch rows retain a challan cancelled after the requested period. These behaviors do not establish statutory acceptance of the generated forms or complete snapshots of jurisdiction-specific party/product tax master data.

A reversal retains its original material identity and cumulative reversals cannot exceed the original quantity. The journal now reverses the actual original contra account as well as stock, including balancing WIP/COGS/scrap/count entries. This corrects previously misclassified derived reports: reconcile existing reversal periods and obtain controller acceptance before replacing previously approved external books. Source movements and invoices are retained; unknown legacy facts are not fabricated.
