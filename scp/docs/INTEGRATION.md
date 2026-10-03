# Connecting your ERP and other systems

Phase Q connects SCP to the rest of the company in three ways:

- **Your ERP sends data in.** It sends customer orders, stock, goods movements and master data.
- **Your ERP takes orders out.** It takes back the purchase, production and transfer orders the planners released, and acknowledges them with its own numbers.
- **The server works on its own.** It reads files on a schedule, and it e-mails documents and worklist reminders.

All of this works on a company kept on the server. The API is at `/api/companies/{cid}/…`, where `{cid}` is the company's id, e.g. `C0001`. The id is shown in the address bar after `#/account`, and `GET /api/companies` lists it.

The full schema of every call is at `/docs` (OpenAPI) on your server.

## Keys

An owner makes a key on **Connections → Keys**. Each key has a name, e.g. "SAP", and acts in one of two roles:

- **Planner.** It sends and takes data.
- **Viewer.** It only takes data.

The key itself starts with `scpk_`. It is shown once, and the server keeps only its fingerprint. The system sends it with every call:

```
Authorization: Bearer scpk_…
```

What a key can do:

- It works in its own company only. In any other company the answer is `404`.
- A key cannot create a company or gain another role by being added as a member. Its role is the one its owner gave the key.
- It is not a member: it is not listed among the people and cannot send e-mail.
- It can be withdrawn at any time. After that every call with it gets `401`.

## How a message is applied

Every message the ERP sends is applied to the company's latest save:

- It becomes a new revision, saved by the key (for example "SAP (key)"). It appears in **History** with what changed, and it can be put back like any other save.
- A planner with the company open takes it in on their next save, as they would a colleague's change. Their browser also checks for newer saves every minute.
- Records a planner set aside as unfinished stay as they are. A message never replaces a whole list that holds such records: it is refused with `409` and a reason.
- If the company asks for a second person's approval of master data, master records the ERP sends wait for that approval. The answer says so in `held`.

**Message ids.** Give each message an id (`message_id`). If the ERP did not hear the answer and sends the same message again, it is not applied a second time. The first answer comes back with status `duplicate`.

**Answers.** Every answer says what became of each item:

```json
{
  "message": {
    "seq": 12, "at": "2026-10-03T06:00:04+00:00", "by": "SAP (key)", "direction": "in", "kind": "orders",
    "message_id": "SAP-0001", "status": "partly", "summary": "2 orders: 1 taken, 1 refused", "revision": 41,
    "items": [
      {"ref": "4711", "status": "applied", "message": "SO-00031 taken for West trade distributors: 1 line …", "id": "SO-00031"},
      {"ref": "4712", "status": "refused", "message": "line 1: there is no product 'NOPE'", "id": null}
    ]
  },
  "revision": 41,
  "held": null
}
```

The status of an item is one of:

| Status | Meaning |
|---|---|
| `applied` | taken |
| `unchanged` | already as sent |
| `duplicate` | sent before |
| `refused` | not taken; the message says why |

A message as a whole is `applied`, `partly`, `refused`, `unchanged` or `duplicate`.

Every message, in and out, is listed on **Connections → Messages**, and with `GET /api/companies/{cid}/messages?status=refused`.

## Messages in

### Customer orders: `POST /erp/orders`

```json
{
  "message_id": "SAP-0001",
  "orders": [
    {"number": "4711", "customer": "CUS-WEST-TRADE", "order_date": "2026-09-28", "customer_ref": "PO 88-17",
     "lines": [{"product": "MG-500", "qty": 40, "date": "2026-10-12", "price": 2450}]}
  ]
}
```

Orders are matched by the ERP's number.

- **A new number** is taken as a new sales order. It is promised, priced and credit-checked as an order taken on *Orders*.
- **A known number** is compared line by line, by position:
  - A changed quantity, date or price changes the line.
  - An extra line is added.
  - A line no longer on the ERP's order is cancelled.
- **`"cancelled": true`** cancels what is still open.
- **Fixed once taken:** the customer and a line's product cannot change. Cancel the order and send a new one.
- **No price** takes the customer's price here.

One line that cannot be taken refuses its whole order, with the reason given.

### Stock: `POST /erp/stock`

```json
{"message_id": "SAP-STOCK-2026-10-02", "as_of": "2026-10-02",
 "stock": [{"location": "PLT-PUNE", "product": "MOT-500", "qty": 412}]}
```

Each quantity is what is on hand at the end of the day, across every batch and stock type.

- **A place and product with no movements yet:** the quantity becomes the opening balance.
- **Otherwise:** the difference to the stock here is posted as a count difference, e.g. "40 on hand: −2 posted (count difference)".

**By batch and stock type.** A row may name a `batch` and a `stock_type` (`unrestricted`, `quality` or `blocked`):

```json
{"stock": [{"location": "PLT-PUNE", "product": "MOT-500", "batch": "B2609", "expires_on": "2027-03-31", "qty": 300},
           {"location": "PLT-PUNE", "product": "MOT-500", "batch": "B2610", "stock_type": "quality", "qty": 112}]}
```

- A place and product given this way is counted lot by lot, as a physical inventory is. The count is kept on *Actuals* as a posted document marked "Stock from the ERP".
- A lot here that the ERP does not list is counted as none.
- A batch new here is made with the `expires_on` given.
- A product kept by batch needs the batch on each row. A product not kept by batch cannot have one.
- A place and product being counted on an open document here is refused until that count is posted or cancelled.

`as_of` defaults to the day before the planning start.

### Goods movements: `POST /erp/postings`

```json
{"message_id": "SAP-MOV-000918",
 "postings": [
   {"ref": "5000012345", "action": "receive", "order": "4500000123/10", "qty": 100, "date": "2026-10-01"},
   {"ref": "5000012346", "action": "deliver", "order": "0000004711/10", "qty": 40, "date": "2026-10-02"},
   {"ref": "5000012347", "action": "scrap", "location": "PLT-PUNE", "product": "MOT-500", "qty": 3}
 ]}
```

**Actions.** `action` is one of:

| Action | What it does |
|---|---|
| `receive` | goods receipt against a purchase, production or transfer order |
| `ship` | a transfer leaves |
| `deliver` | goods issue to a customer |
| `move` | between stock types |
| `scrap` | goods taken out of stock |

**Order numbers.** An order can be named by our number or the ERP's:

| ERP number | Means |
|---|---|
| `4500000123/10` | item 10 of the purchase order the ERP numbered 4500000123 |
| a production or transfer order's ERP number | that order |
| `4711/1` | line 1 of the customer order the ERP numbered 4711 |

**Batches and stock types.** Batches, expiry dates and stock types are taken as on *Actuals*: `batch`, `expires_on`, `supplier_batch`, `stock_type`, `to_type`.

**Each document once.** A posting is taken once per `ref`; the same ref again is `duplicate`.

### Master data: `GET /erp/records`, `POST /erp/records/{list}`

`GET /erp/records` names the lists that can be sent, for example products, locations, location_products, vendors, customers and purchasing_sources.

```json
{"message_id": "MDM-77", "records": [{"id": "MG-500", "name": "Mixer grinder 500 W", "price": 2450}]}
```

A record is matched by its key:

- Products, by `id`.
- A product at a place, by `location` + `product`.
- Every other list, by the key shown in *Master data*.

A known record changes only in the fields sent, and a new one is added. A record with an unknown reference, or one that breaks a rule, is refused with the reason.

## Orders out

### Taking orders: `GET /erp/purchase-orders`, `/erp/production-orders`, `/erp/transfer-orders`

These return the orders planners released for the ERP to carry out:

- **Purchase orders:** released and approved ones, not those waiting for a release.
- **Production and transfer orders:** firm ones.

```json
{"revision": 41, "orders": [
  {"kind": "purchase_order", "id": "PO-00012", "version": "9f2c1d0a6b7e4c31", "change": "new", "erp_ref": "",
   "location": "PLT-PUNE", "supplier": "SUP-COPPER", "supplier_name": "Shakti Copper", "order_date": "2026-09-28",
   "currency": "INR", "lines": [{"id": "PO-00012-10", "item": 10, "product": "CU-WIRE", "qty": 500, "open": 500,
   "date": "2026-10-09", "price": 612.5, "cancelled": false}]}
]}
```

Without `?all=true`, only orders the ERP has not taken in their current form are listed.

- `change` is one of:
  - `new`: never taken.
  - `changed`: taken, then changed here (a new quantity, date or line).
  - `withdrawn`: taken, then deleted here. It has no lines. The ERP should close its copy and acknowledge it with its number; it is then `taken`, listed only with `?all=true`.
- `version` fingerprints what the ERP needs. A new version means something changed.
- A pull that differs from the last one is logged in Messages as a message out.

### Acknowledging: `POST /erp/acknowledge`

```json
{"message_id": "SAP-ACK-31",
 "orders": [{"kind": "purchase_order", "id": "PO-00012", "erp_ref": "4500000123", "version": "9f2c1d0a6b7e4c31",
             "sent_to_supplier": true}]}
```

- The ERP's number is kept on the order and shown with it. Movements can name the order by it from then on.
- The order counts as taken in this version.
- `sent_to_supplier` marks a purchase order as sent.
- An acknowledgement of an older version than the order has now keeps the ERP's number, and the order is listed again as `changed`.
- An order the ERP has already numbered is not renumbered: an acknowledgement with a different number is refused.
- A `withdrawn` order is acknowledged with the ERP's number it had. Putting a save back that brings the order back here cancels the withdrawal.

### Purchase order cancellations

A cancelled line is retained for the ERP with `cancelled: true` and `open: 0`, alongside any remaining lines.
Cancelling the last line removes the order from Buying but keeps its cancellation in the ERP feed. The order also
has `cancelled: true`. Acknowledge its new `version` just like a quantity or date change; it stays in the feed until
that version is taken. An acknowledgement of the earlier order, including one arriving after cancellation, keeps
the ERP number and leaves the cancellation pending. `?all=true` also includes acknowledged cancellations.

The saved dataset keeps these removed headers in `cancelled_purchase_orders`, and each header's `cancelled_lines`
holds its removed line snapshots. These records preserve the history and prevent cancelled order or line numbers
from being reused.

## Scheduled imports

Where the ERP cannot call an API, it writes an export that the server reads. An owner sets this up on **Connections → Scheduled imports**: what the file brings, where it is, and when to read it.

**Where.** One of:
- **A web address.** Optional headers are sent with it, e.g. `Authorization`; their values are not shown again.
  When changing an import, omitted or `null` headers retain saved values only if the protocol, host and port stay
  the same. An explicit `"headers": {}` removes them. Changing to another origin or to a folder clears saved headers
  unless new headers are explicitly provided for the new web address. The browser also offers **Remove saved request headers**.
- **A file pattern in the company's folder on the server**, e.g. `orders-*.csv`. Each file read is moved to `done/` (or `failed/`).

**When.** Every hour, every day or every week, at a time in the server's time zone.

**Formats:**
- **CSV.** The delimiter is detected: comma, semicolon, tab or bar.
  - Stock can have a column per stock type, as SAP's MARD does (`Unrestricted`/`LABST`, `Quality inspection`/`INSME`, `Blocked`/`SPEME`): each row becomes a row per stock type.
  - A header row names the columns. Names are recognised in English and as SAP exports them: `Material`/`MATNR`, `Plant`/`WERK`, `Menge`, `VBELN`, `KUNNR`, `MBLNR`, `CHARG`, and so on.
  - Dates are read day first (`05/01/2026` is 5 January) unless the import says otherwise.
  - German numbers are read (`1.234,5`).
  - SAP movement types become actions: 101 receive, 601 deliver, 641/351 ship, 311/321 move, 551 scrap.
  - Customer orders have one row per line; rows with the same order number make one order.
- **JSON.** The message as the API takes it, or just its list of items.

**Each file once.** A file is applied as the message of its kind, by the owner who set the import up, and logged with what became of each line. The same file content is never applied twice.

**Run now** reads the file at once.

## E-mail from the server

When the server has a mail server set up (`SCP_SMTP_HOST`, see [DEPLOY.md](DEPLOY.md)), documents can go from the server.

**Documents.** These have **Send from here** beside *E-mail* on *Buying* and *Selling*:
- purchase orders and delivery schedules
- order confirmations
- invoices and credit notes
- statements of account and payment reminders (*Selling → Customers*)

The document is attached twice: as a PDF the server lays out itself (A4, no browser needed), and as the page *Print* shows, the exact copy. It comes from the server's address, and replies go to whoever sent it. Rules:
- It goes only to addresses the company knows: the supplier's or customer's e-mail in their purchasing or sales data, or a member's.
- A company sends at most 500 e-mails a day.
- Sending a purchase order or a confirmation also records it as sent.
- On a scheduling agreement, it sends the delivery schedule.
- Sending a payment reminder records it on its invoices, so the next reminder follows only when they are still unpaid at the next reminder day.
- **Firming** with *send* e-mails each approved purchase order to its supplier. An order whose supplier has no e-mail address, or whose mail fails, is named and stays unsent.

**Worklist reminders.** An owner sets the days and the time on **Connections → E-mail**. On those days, each person who owns open exceptions on the worklist gets one e-mail with them:
- the ones past their time first, then the oldest;
- with a link to the worklist.

An owner of an exception is found by e-mail address or by a member's name.

Every e-mail sent, or refused by the mail server, is listed under **Sent**.

## Server settings

These are set in the server's environment:

| Variable | What it does | Default |
|---|---|---|
| `SCP_IMPORT_DIR` | Folder of company folders (`<dir>/<company id>/`) for scheduled imports. None: imports read web addresses only. | none |
| `SCP_IMPORT_HOSTS` | Comma-separated hosts a scheduled import may read from. None: any host on the internet, never one inside the server's own network. That means no private, loopback or link-local address, as the name resolves when the file is read, redirects included. | none |
| `SCP_TIMEZONE` | Time zone of the imports' and reminders' times of day, e.g. `Asia/Kolkata`. | `UTC` |
| `SCP_SCHEDULER` | `0` stops this server from running imports and reminders, e.g. on a second server using the same database. | on |
| `SCP_SMTP_*`, `SCP_PUBLIC_URL` | Mail, as for password resets; the public address is used in reminder links. | none |
