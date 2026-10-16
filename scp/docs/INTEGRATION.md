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

**A web API, page by page.** From *a web API* reads JSON answers page by page into one message:
- **Next page at** a path in the answer that holds the next page's address (`links.next`, `@odata.nextLink`); an
  address that names a page already read ends the reading.
- **Numbered pages**: `?page=1`, `2`, … (the parameter is named on the import), until a flag in the answer says there
  are no more (`page_context.has_more_page`) or, without one, a page has no records.
- **The Link header** (`"paging": {"mode": "link"}`): the answer's `Link` header names the next page
  (`<https://…?page_info=…>; rel="next"`), as Shopify's REST API and GitHub's do; no such link ends the reading.
- **At most** a number of pages (50 unless set): an answer with more fails the run rather than take a part of it.
- The headers go to the import's own host only; a next page on another host is asked without them.

**Only what changed.** `{since}` anywhere in a web address (a file's or an API's) is the time the last good run started,
as `2026-10-15T06%3A00%3A00%2B00%3A00` (the first run: 1970). A run that fails leaves it as it was, so nothing is missed.
Changing the import to another host or another kind of record starts again from the beginning.

**Mapping.** Without one, columns are recognised by their names (below). With *Name the fields myself* (`mapping` in
the API) each field here is filled from what the mapping names:

```json
{"items": "orders", "each": "line_items",
 "fields": {"number": {"source": "name"},
            "customer": {"source": "customer.code", "values": {"C-77": "CUS-WEST-TRADE"}},
            "date": {"source": "note_attributes.deliver_by", "date_format": "%d %b %Y"},
            "product": {"source": "line.sku", "values": {"MG500": "MG-500"}},
            "qty": {"source": "line.quantity", "factor": 12},
            "location": {"value": "PLT-PUNE"}}}
```

- `source`: a column of a CSV file (as written, or in any case and spacing), or a path in a JSON record
  (`customer.code`, `lines.0.sku`); with `each`, `line.<path>` is the element of the list.
- `items`: the path to the list of records in a JSON answer; `each`: a list in each record that makes one row per
  element (an order's lines; the order's own fields are repeated on each).
- `values`: codes translated, `*` for any other; `factor`: numbers multiplied; `date_format`: as `strftime` writes it
  (`%d-%b-%Y`), and it must give a day, month and year; `value`: used when the source is empty, or always with no source.
- For master data, a field within a field is named with a dot (`lot_sizing.policy`).
- The fields each kind has are in `GET /imports` (`fields`); a mapping naming another is refused.

**Try it first.** `POST /imports/try` with `{"job": {…the import…}, "content": "…a sample…"}` (no `content`: the source
is read now; `"id"` of a saved import uses its saved headers for the same host) and `POST /imports/{id}/dry-run` for a
saved import answer what would become of each line (`"dry_run": true`, summary "Dry run, nothing saved: …"), the
columns found (`columns`) and the first rows as the fields here (`rows`). Nothing is saved, logged or moved, and the
schedule and `{since}` stay as they were. Only an owner may: an import reads from outside with the owner's rights.

**Each file once.** A file is applied as the message of its kind, by the owner who set the import up, and logged with what became of each line. The same file content is never applied twice.

**Run now** reads the file at once. The message log keeps the first 2,000 characters of what was read beside each
message (*What was read* on **Connections → Messages**, `sample` in `GET /messages`).

## Tally Prime and Zoho Inventory

A scheduled import can ask Tally Prime or Zoho Inventory directly (*Connect Tally*, *Connect Zoho* on **Connections
→ Scheduled imports**; `source_type` `tally` or `zoho` in the API). Each job does one thing, on its schedule:

| What it brings | Tally Prime | Zoho Inventory |
|---|---|---|
| `records:products` | stock items: the name (as the code too, unless translated), the stock group as family and the base unit of a new product | items: the SKU (else the name) as the code, the unit and item group of a new product, the selling rate as price; services are left out |
| `records:locations` | ledgers under Sundry Debtors (customers) and Sundry Creditors (suppliers), sub-groups too: address, GSTIN, the state as region of a new one | contacts: customers and vendors, GSTIN, billing address, place of supply as region of a new one |
| `stock` | each stock item's closing balance, counted at the place the job names | each tracked item's stock on hand, counted at the place the job names |
| `orders` | vouchers of the sales order type (`Sales Order` unless set) of the last `days_back` days: a line due in parts is a line per due date (`ORDERDUEDATE`), a cancelled voucher cancels the order, an optional one is not read | sales orders changed since the last good run (newest first, until an older one), each read whole: the shipment date is each line's date, a void order cancels it, a draft is not read |
| `send:purchase_order` | purchase order vouchers numbered as the order here (`Alter` when it changed, `Cancel` when it was cancelled or deleted here), quantities in the stock item's own unit, booked to the purchase ledger | purchase orders numbered as the order here (`ignore_auto_number_generation`), Zoho's item and vendor IDs found by SKU or name; changed: updated, cancelled: cancelled; the earliest line date is the delivery date |

```json
{"name": "Tally stock", "kind": "stock", "source_type": "tally", "source": "http://tally-pc:9000",
 "app": {"company": "Kaveri Kitchenware", "place": "PLT-PUNE"},
 "mapping": {"fields": {"product": {"values": {"Mixer Grinder 500W": "MG-500"}}}},
 "every": "hour", "at": "00:05"}
```

- **Codes.** The mapping translates them (`values`, the other system's code = the code here; a field without
  `source` is the connector's field of the same name). A name not translated becomes the code here as it is, with
  characters a code cannot have made hyphens (`Steel Tumbler 250 ml` → `Steel-Tumbler-250-ml`). Sending, each code
  here goes as the first name translated to it; otherwise as the name of the product or supplier here (Tally: a
  product's name when its code was made from it).
- **Kept as here.** A product's type, unit and family, and a place's type and region, are taken only by a new record:
  one kept here is not made another type because the other system says so. Its name, address and GSTIN follow.
- **Purchase orders out.** The orders an ERP would take (`GET /erp/purchase-orders`) are sent one by one; what the
  other system took is acknowledged as an ERP acknowledges, so each keeps its number there (`erp_ref`) and goes again
  only when it changes. A refused one (Tally's or Zoho's own words) goes again on the next run. Before making one,
  the connector asks whether the other system has it already by our number (an answer lost on the way), and then
  changes it rather than making it twice. An order cancelled here that was never sent is not sent.
- **Tally** answers on its port (F1 Help → Settings → Connectivity: TallyPrime acts as a server, port 9000). It sits
  on the company's own network: the server reaches it only when the administrator allows its host by name
  (`SCP_IMPORT_HOSTS=tally-pc`), so a server on the internet needs a tunnel or a server on the same network. `company`
  is the company's name in Tally (empty: the one open). An answer with a document type (entities) is refused; the
  control characters Tally writes in names are dropped.
- **Zoho**: the organisation ID is the source, `data_centre` where it is kept (`in`, `com`, `eu`, `com.au`, `jp`,
  `ca`, `sa`), and a *self client* from Zoho's API console gives `secrets`: `client_id`, `client_secret` and
  `refresh_token` (scope `ZohoInventory.FullAccess.all`). They are kept on the server and never shown again (their
  names are in `header_names`); changing the job with a value left empty keeps the one kept for the same organisation
  and data centre. An access token is asked for once an hour (once more if Zoho stops taking it early). At most
  20,000 records of a kind, and 500 sales orders changed between two runs, are read.
- **Try it** and **Dry run** work as for a file: a pasted answer of Tally's (or one page of Zoho's) is read as the
  connector would; a dry run of `send:purchase_order` builds what would be sent and sends nothing.

## Shopify and Odoo

*Connect Shopify* and *Connect Odoo* (`source_type` `shopify` or `odoo`) work as Tally and Zoho do: one kind a job,
codes translated by the mapping, a new record's type, unit and family taken only when it is new, orders sent one by
one and acknowledged.

| What it brings | Shopify | Odoo |
|---|---|---|
| `records:products` | product variants: the SKU (else the product's title, and the variant's when there are several) as the code, the product type as a new product's family, the variant's price; a draft or archived product is not read | product variants: the internal reference (else the name) as the code, the unit and the category's last part for a new product, the sales price; services and combos are not read |
| `records:locations` | the shop's active locations as places (a warehouse, a new one), with their address | customers and vendors (companies and people without a parent company): the tax ID, the address, the state as region; a partner that is more vendor than customer is a supplier |
| `records:production_sources` | — | bills of materials (not kits) as ways to make their product at the plant the job names (`place`): the BOM's quantity and components; the steps here are kept |
| `stock` | on hand at each location, per tracked variant | on hand in internal locations, summed by warehouse |
| `orders` | orders updated since the last good run: the name without `#` as the number, the customer the job names (`customer`, the online shop) and the buyer's name as the note, each line's quantity after edits and refunds, a cancelled order cancelled | confirmed sales orders changed since the last good run: the reference as the number, the customer's company as the customer, the delivery date (else the order date) on every line, a cancelled one cancelled; quotations are not read |
| `postings` | fulfilments of the orders updated since the last good run, as deliveries of the order's lines (`1001/10`), each taken once | — |
| `send:purchase_order` | — (Shopify keeps no purchase orders) | requests for quotation made and confirmed, our number as the source document, Odoo's vendor and products found by name and internal reference; changed: its lines rewritten (a line no longer here cut to what was received); cancelled or deleted here: cancelled |
| `send:production_order` | — | manufacturing orders made and confirmed (start and deadline, our number as the source document); a new quantity through Odoo's own *change quantity*; deleted here: cancelled |

```json
{"name": "Shopify orders", "kind": "orders", "source_type": "shopify", "source": "kaveri.myshopify.com",
 "app": {"customer": "WEB-SHOP"}, "secrets": {"access_token": "shpat_…"}, "every": "hour", "at": "00:20"}
{"name": "Production orders to Odoo", "kind": "send:production_order", "source_type": "odoo",
 "source": "https://kaveri.odoo.com", "app": {"database": "kaveri"},
 "secrets": {"login": "planner@kaveri.example", "api_key": "…"}, "every": "hour", "at": "00:25"}
```

- **Shopify** is asked through its Admin GraphQL API (`api_version`, `2026-07` unless set; it pages by cursor and a
  throttled call is asked again once) with a custom app's Admin API access token in Shopify's own header
  (`X-Shopify-Access-Token`). The app needs `read_products`, `read_inventory`, `read_locations`, `read_orders` and,
  for fulfilments, `read_fulfillments`. The source is the shop's `myshopify.com` address; the token is kept for that
  shop only. A shop's buyers are not places here: its orders go to one customer the job names.
- **Odoo** is asked as a user, with an API key made for them (Preferences → Account security → New API key), through
  JSON-RPC (`/jsonrpc`, every version) or, with `"odoo_api": "json2"`, the JSON API of Odoo 19 and later
  (`/json/2/…`, the key as a bearer token); Odoo 20 removes JSON-RPC. `database` is the database's name. The user's
  rights in Odoo are what the connector may do. The login and key are kept for the same address and database.
- **Places.** Shopify's locations and Odoo's warehouses are the places of the same name here, or the ones the mapping
  translates them to (`location` values); a job's `place` takes every one not translated.
- **Odoo's warehouses for orders out.** A place translated to an Odoo warehouse (the mapping's `location`, here =
  there) sends its orders to that warehouse's receipt or manufacturing operation; otherwise Odoo's default.

## E-mail from the server

When the server has a mail server set up (`SCP_SMTP_HOST`, see [DEPLOY.md](DEPLOY.md)), documents can go from the server.

**Documents.** These have **Send from here** beside *E-mail* on *Buying* and *Selling*:
- purchase orders and delivery schedules
- order confirmations
- invoices and credit notes
- statements of account and payment reminders (*Selling → Customers*)

The document is attached twice: as a PDF the server lays out itself (A4, no browser needed), and as the page *Print* shows, the exact copy. It comes from the server's address, and replies go to whoever sent it. Rules:
- It goes only to addresses the company knows: the supplier's or customer's e-mail in their purchasing or sales data, or a member's.
- The sender's own address must be confirmed (*Account → Confirm my address*); one person sends at most `SCP_MAIL_DAILY_PER_ACCOUNT` (100) a day across every company; and a server where anyone may make an account (`SCP_SIGNUP=open`) mails documents only with `SCP_MAIL_OPEN_SIGNUP=1`. Each mail ends with who sent it and for which company.
- A company sends at most 500 e-mails a day.
- Sending a purchase order or a confirmation also records it as sent.
- On a scheduling agreement, it sends the delivery schedule.
- Sending a payment reminder records it on its invoices, so the next reminder follows only when they are still unpaid at the next reminder day.
- **Firming** with *send* e-mails each approved purchase order to its supplier. An order whose supplier has no e-mail address, or whose mail fails, is named and stays unsent.

**Worklist reminders.** An owner sets the days and the time on **Connections → E-mail**. On those days, each person who owns open exceptions on the worklist gets one e-mail with them:
- the ones past their time first, then the oldest;
- with a link to the worklist.

An owner of an exception is found by a member's e-mail address or name; an address written on an exception that is not a member's gets no mail.

Every e-mail sent, or refused by the mail server, is listed under **Sent**.

## Server settings

These are set in the server's environment:

| Variable | What it does | Default |
|---|---|---|
| `SCP_IMPORT_DIR` | Folder of company folders (`<dir>/<company id>/`) for scheduled imports. None: imports read web addresses only. | none |
| `SCP_IMPORT_HOSTS` | Comma-separated hosts a scheduled import may read from. None: any host on the internet, never one inside the server's own network. That means no private, loopback or link-local address, as the name resolves when the file is read, redirects included. A host named here may be on the server's own network (a company's Tally). | none |
| `SCP_TIMEZONE` | Time zone of the imports' and reminders' times of day, e.g. `Asia/Kolkata`. | `UTC` |
| `SCP_SCHEDULER` | `0` stops this server from running imports and reminders, e.g. on a second server using the same database. | on |
| `SCP_SMTP_*`, `SCP_PUBLIC_URL` | Mail, as for password resets; the public address is used in reminder links. | none |
