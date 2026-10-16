"""Odoo (ENTERPRISE_PLAN 3.3): its external API with a user's login and API key.

The job's source is Odoo's address (``https://my-company.odoo.com``) and its database a setting; the login and an
API key made for that user (Preferences → Account security → New API key) are kept with the job and never shown
again. Odoo 19 has a new JSON API (``/json/2``, the key as a bearer token) beside the JSON-RPC every version answers
(``/jsonrpc``, Odoo 20 removes it): a setting says which. A job reads, a page of 500 at a time:

* products (variants) as products: the internal reference, else the name, as the code; the unit and the category's
  last part for a new product; the sales price as its price; services and combos are not read;
* customers and vendors (companies and people without a parent) as customers and suppliers, with the tax ID and
  address;
* bills of materials (normal ones, not kits) as ways to make a product at the plant the job names: the BOM's
  quantity and its components (the steps here are kept);
* stock on hand in internal locations, by warehouse: a warehouse is the place of the same name here, the one the
  mapping translates it to, or the place the job names when it is not translated;
* confirmed sales orders changed since the last good run: the order's reference as the number, the customer (its
  company) and the delivery date (else the order date) of every line; a cancelled one cancelled here;

and makes purchase orders (requests for quotation confirmed at once) and manufacturing orders (confirmed), each with
our number as its source document: a changed order is changed there (a manufacturing order's quantity by Odoo's own
"change quantity"), a cancelled one cancelled. Odoo's reference (P00012, WH/MO/00007) is kept as the ERP's.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any
from urllib.parse import quote, urlparse

from . import AppSettings, slug, today

KINDS = ["records:products", "records:locations", "records:production_sources", "stock", "orders",
         "send:purchase_order", "send:production_order"]
SECRETS = ["login", "api_key"]
PLACES = True
PAGE = 500
MAX_PAGES = 100
_STAMP = "%Y-%m-%d %H:%M:%S"


def base(source: str) -> str:
    u = urlparse(source.strip())
    return f"{u.scheme}://{u.netloc}"


def check(source: str, s: AppSettings, secrets: dict[str, str], kind: str = "") -> None:
    if not s.database:
        raise ValueError("Odoo needs its database's name (the my-company of my-company.odoo.com, or the one chosen "
                         "at sign in)")
    missing = [k.replace("_", " ") for k in SECRETS if not (secrets.get(k) or "").strip()]
    if missing:
        raise ValueError(f"Odoo needs the {' and the '.join(missing)} of a user (Preferences → Account security → "
                         "New API key)")
    if kind == "records:production_sources" and not s.place:
        raise ValueError("Odoo's bills of materials are ways to make at a plant here: name the plant")


def same(old_source: str, old: AppSettings, source: str, new: AppSettings) -> bool:
    return base(old_source) == base(source) and old.database == new.database


class Session:
    """Calls as one user of one database."""

    def __init__(self, job: dict, s: AppSettings, secrets: dict[str, str]) -> None:
        check(job["source"], s, secrets)
        self.base, self.db, self.json2 = base(job["source"]), s.database, s.odoo_api == "json2"
        self.login, self.key = secrets["login"].strip(), secrets["api_key"].strip()
        self.uid: int | None = None
        self.calls = 0
        self._fields: dict[str, set[str]] = {}

    def _post(self, url: str, body: Any, headers: dict[str, str]) -> tuple[int, Any]:
        from .. import imports
        self.calls += 1
        status, raw = imports.http("POST", url, {"Content-Type": "application/json", **headers},
                                   json.dumps(body).encode())
        try:
            return status, json.loads(raw.decode("utf-8-sig", errors="replace") or "null")
        except json.JSONDecodeError:
            raise ValueError(f"Odoo's answer is not JSON ({status}): {raw[:120]!r}") from None

    def _rpc(self, service: str, method: str, args: list[Any]) -> Any:
        status, data = self._post(f"{self.base}/jsonrpc", {"jsonrpc": "2.0", "method": "call", "id": self.calls,
                                                           "params": {"service": service, "method": method,
                                                                      "args": args}}, {})
        if not isinstance(data, dict):
            raise ValueError(f"Odoo did not answer as JSON-RPC ({status})")
        if data.get("error"):
            e = data["error"]
            raise ValueError(f"Odoo says: {(e.get('data') or {}).get('message') or e.get('message') or e}"[:400])
        if status >= 400:
            raise ValueError(f"Odoo answered {status}")
        return data.get("result")

    def call(self, model: str, method: str, args: list[Any] | None = None, kw: dict[str, Any] | None = None,
             names: tuple[str, ...] = ()) -> Any:
        args, kw = list(args or []), dict(kw or {})
        if self.json2:
            status, data = self._post(f"{self.base}/json/2/{quote(model)}/{quote(method)}",
                                      {**dict(zip(names, args, strict=False)), **kw},
                                      {"Authorization": f"bearer {self.key}", "X-Odoo-Database": self.db})
            if status in (401, 403):
                raise ValueError("Odoo does not take the API key (check it, the database and the user's rights)")
            if status >= 400:
                said = data.get("message") if isinstance(data, dict) else None
                raise ValueError(f"Odoo says: {said or status}"[:400])
            return data
        if self.uid is None:
            uid = self._rpc("common", "authenticate", [self.db, self.login, self.key, {}])
            if not isinstance(uid, int) or isinstance(uid, bool):
                raise ValueError("Odoo does not take the login and API key (check them and the database)")
            self.uid = uid
        return self._rpc("object", "execute_kw", [self.db, self.uid, self.key, model, method, args, kw])

    def search_read(self, model: str, domain: list[Any], fields: list[str], order: str = "id",
                    every: bool = False) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        kw: dict[str, Any] = {"fields": fields, "order": order, "limit": PAGE}
        if every:
            kw["context"] = {"active_test": False}
        for page in range(MAX_PAGES):
            got = self.call(model, "search_read", [domain], {**kw, "offset": page * PAGE}, ("domain",)) or []
            out += [r for r in got if isinstance(r, dict)]
            if len(got) < PAGE:
                return out
        raise ValueError(f"Odoo has more than {MAX_PAGES * PAGE} {model} records: read only what changed")

    def has(self, model: str, field: str) -> bool:
        if model not in self._fields:
            self._fields[model] = set(self.call(model, "fields_get", [], {"attributes": ["type"]}) or {})
        return field in self._fields[model]

    def codes(self, ids: list[int]) -> dict[int, str]:
        """Our code of each product variant (its internal reference, else its name)."""
        if not ids:
            return {}
        got = self.search_read("product.product", [("id", "in", sorted(set(ids)))], ["default_code", "name"],
                               every=True)
        return {p["id"]: code(p) for p in got}


def code(p: dict[str, Any]) -> str:
    return str(p.get("default_code") or p.get("name") or "").strip()


def _id(v: Any) -> int | None:
    """A many-to-one's ID ([7, "Name"] or 7)."""
    if isinstance(v, list) and v:
        v = v[0]
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _name(v: Any) -> str:
    return str(v[1]) if isinstance(v, list) and len(v) > 1 else ""


def _day(v: Any) -> str | None:
    if not isinstance(v, str) or not v:
        return None
    return v[:10]


def _text(html: Any) -> str:
    if not isinstance(html, str):
        return ""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _since(job: dict, s: AppSettings) -> str:
    t = None
    if job.get("cursor"):
        try:
            t = dt.datetime.fromisoformat(job["cursor"])
        except ValueError:
            t = None
    if t is None:
        t = dt.datetime.combine(today() - dt.timedelta(days=s.days_back), dt.time(), dt.UTC)
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.UTC)
    return t.astimezone(dt.UTC).strftime(_STAMP)


def read(job: dict, s: AppSettings, secrets: dict[str, str], headers: dict[str, str]) -> bytes:
    z = Session(job, s, secrets)
    kind = job["kind"]
    if kind == "records:products":
        got = z.search_read("product.product", [("active", "=", True)],
                            ["default_code", "name", "uom_id", "categ_id", "list_price", "type"])
        return json.dumps({"products": got}).encode()
    if kind == "records:locations":
        got = z.search_read("res.partner", ["&", ("parent_id", "=", False), "|", ("customer_rank", ">", 0),
                                            ("supplier_rank", ">", 0)],
                            ["name", "customer_rank", "supplier_rank", "vat", "street", "street2", "city", "zip",
                             "state_id", "country_id"])
        return json.dumps({"partners": got}).encode()
    if kind == "records:production_sources":
        boms = z.search_read("mrp.bom", [("active", "=", True), ("type", "=", "normal")],
                             ["code", "product_tmpl_id", "product_id", "product_qty"])
        lines = z.search_read("mrp.bom.line", [("bom_id", "in", [b["id"] for b in boms])],
                              ["bom_id", "product_id", "product_qty"], order="bom_id, sequence, id") if boms else []
        tmpls = sorted({t for b in boms if not _id(b.get("product_id")) for t in [_id(b.get("product_tmpl_id"))] if t})
        variants = z.search_read("product.product", [("product_tmpl_id", "in", tmpls)],
                                 ["default_code", "name", "product_tmpl_id"]) if tmpls else []
        ids = [i for b in boms for i in [_id(b.get("product_id"))] if i] + \
              [i for ln in lines for i in [_id(ln.get("product_id"))] if i]
        return json.dumps({"boms": boms, "lines": lines, "variants": variants,
                           "codes": {str(k): v for k, v in z.codes(ids).items()}}).encode()
    if kind == "stock":
        quants = z.search_read("stock.quant", [("location_id.usage", "=", "internal")],
                               ["product_id", "location_id", "warehouse_id", "quantity"])
        ids = [i for q in quants for i in [_id(q.get("product_id"))] if i]
        return json.dumps({"quants": quants, "codes": {str(k): v for k, v in z.codes(ids).items()}}).encode()
    if kind == "orders":
        heads = z.search_read("sale.order", [("write_date", ">", _since(job, s)),
                                             ("state", "in", ["sale", "done", "cancel"])],
                              ["name", "partner_id", "date_order", "commitment_date", "client_order_ref", "state",
                               "note"])
        lines = z.search_read("sale.order.line", [("order_id", "in", [h["id"] for h in heads]),
                                                  ("display_type", "=", False)],
                              ["order_id", "product_id", "product_uom_qty", "price_unit"],
                              order="order_id, sequence, id") if heads else []
        pids = sorted({i for h in heads for i in [_id(h.get("partner_id"))] if i})
        partners = z.search_read("res.partner", [("id", "in", pids)], ["commercial_partner_id", "name"],
                                 every=True) if pids else []
        ids = [i for ln in lines for i in [_id(ln.get("product_id"))] if i]
        return json.dumps({"orders": heads, "lines": lines,
                           "customers": {str(p["id"]): _name(p.get("commercial_partner_id")) or p.get("name")
                                         for p in partners},
                           "codes": {str(k): v for k, v in z.codes(ids).items()}}).encode()
    raise ValueError(f"Odoo gives no {kind}")


# ------------------------------------------------------------------------------------------------ reading
def _json(raw: bytes) -> dict[str, Any]:
    try:
        data = json.loads(raw.decode("utf-8-sig", errors="replace") or "{}")
    except json.JSONDecodeError:
        raise ValueError(f"Odoo's answer is not JSON: {raw[:120]!r}") from None
    return data if isinstance(data, dict) else {}


def _list(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    got = data.get(key)
    if not isinstance(got, list):
        raise ValueError(f"Odoo's answer has no {key}")
    return [x for x in got if isinstance(x, dict)]


def rows(kind: str, raw: bytes, s: AppSettings) -> list[dict[str, Any]]:
    data = _json(raw)
    codes = {int(k): v for k, v in (data.get("codes") or {}).items()}
    out: list[dict[str, Any]] = []
    if kind == "records:products":
        for p in _list(data, "products"):
            c = code(p)
            if not c or p.get("type") in ("service", "combo"):
                continue
            r: dict[str, Any] = {"id": c, "name": str(p.get("name") or c)}
            if _name(p.get("uom_id")):
                r["base_uom"] = _name(p["uom_id"])[:12]
            if _name(p.get("categ_id")):
                r["family"] = _name(p["categ_id"]).split("/")[-1].strip()
            if isinstance(p.get("list_price"), (int, float)) and p["list_price"] > 0:
                r["price"] = float(p["list_price"])
            out.append(r)
    elif kind == "records:locations":
        for p in _list(data, "partners"):
            name = str(p.get("name") or "").strip()
            if not name:
                continue
            supplier = (p.get("supplier_rank") or 0) > (p.get("customer_rank") or 0)
            r = {"id": name, "name": name, "type": "supplier" if supplier else "customer"}
            if p.get("vat"):
                r["tax_id"] = str(p["vat"])[:40]
            if _name(p.get("state_id")):
                r["region"] = _name(p["state_id"])
            lines = [str(p.get(k) or "").strip() for k in ("street", "street2", "city", "zip")] + \
                    [_name(p.get("state_id")), _name(p.get("country_id"))]
            if any(lines):
                r["address"] = "\n".join(x for x in lines if x)[:400]
            out.append(r)
    elif kind == "records:production_sources":
        lines: dict[int, list[dict[str, Any]]] = {}
        for ln in _list(data, "lines"):
            b, p = _id(ln.get("bom_id")), _id(ln.get("product_id"))
            if b and p in codes and (ln.get("product_qty") or 0) > 0:
                lines.setdefault(b, []).append({"product": codes[p], "qty": float(ln["product_qty"])})
        variants: dict[int, list[str]] = {}
        for v in _list(data, "variants"):
            t = _id(v.get("product_tmpl_id"))
            if t and code(v):
                variants.setdefault(t, []).append(code(v))
        for b in _list(data, "boms"):
            p = _id(b.get("product_id"))
            made = [codes[p]] if p in codes else variants.get(_id(b.get("product_tmpl_id")) or 0, [])
            for c in made:
                ref = str(b.get("code") or "").strip()
                out.append({"id": ref if ref and len(made) == 1 else c, "location": s.place, "product": c,
                            "output_qty": float(b.get("product_qty") or 1.0) or 1.0,
                            "components": lines.get(b["id"], [])})
    elif kind == "stock":
        summed: dict[tuple[str, str], float] = {}
        for q in _list(data, "quants"):
            p = _id(q.get("product_id"))
            place = _name(q.get("warehouse_id")) or _name(q.get("location_id"))
            if p in codes and isinstance(q.get("quantity"), (int, float)):
                k = (place, codes[p])
                summed[k] = summed.get(k, 0.0) + float(q["quantity"])
        out = [{"location": loc, "product": c, "qty": max(q, 0.0)} for (loc, c), q in summed.items()]
    elif kind == "orders":
        customers = data.get("customers") or {}
        by: dict[int, list[dict[str, Any]]] = {}
        for ln in _list(data, "lines"):
            o = _id(ln.get("order_id"))
            if o:
                by.setdefault(o, []).append(ln)
        for so in _list(data, "orders"):
            head: dict[str, Any] = {"number": str(so.get("name") or ""),
                                    "customer": str(customers.get(str(_id(so.get("partner_id")))) or
                                                    _name(so.get("partner_id")))}
            if _day(so.get("date_order")):
                head["order_date"] = _day(so["date_order"])
            if so.get("client_order_ref"):
                head["customer_ref"] = str(so["client_order_ref"])[:64]
            if _text(so.get("note")):
                head["note"] = _text(so["note"])[:400]
            if so.get("state") == "cancel":
                head["cancelled"] = True
            due = _day(so.get("commitment_date")) or head.get("order_date")
            lines = [ln for ln in by.get(so["id"], []) if _id(ln.get("product_id")) in codes
                     and (ln.get("product_uom_qty") or 0) > 0]
            if not lines:
                out.append(head)
            for ln in lines:
                r = {**head, "product": codes[_id(ln["product_id"]) or 0], "qty": ln["product_uom_qty"], "date": due}
                if isinstance(ln.get("price_unit"), (int, float)):
                    r["price"] = ln["price_unit"]
                out.append(r)
    return out


# ------------------------------------------------------------------------------------------------ sending
def _stamp(d: dt.date | None) -> str | None:
    return f"{d.isoformat()} 12:00:00" if d else None


class Sender:
    """Purchase and manufacturing orders to Odoo, each made, changed or cancelled by its own calls."""

    def __init__(self, job: dict, s: AppSettings, secrets: dict[str, str], headers: dict[str, str]) -> None:
        self.z = Session(job, s, secrets)
        self._products: dict[str, int] = {}
        self._partners: dict[str, int | None] = {}
        self._types: dict[tuple[str, str], int | None] = {}

    def codes(self, ds: Any, kind: str, here: str) -> str:
        if kind == "supplier":
            loc = ds.location_by_id.get(here)
            return (getattr(loc, "name", "") or here) if loc else here
        return here

    def product(self, c: str) -> int:
        if c not in self._products:
            got = self.z.search_read("product.product", [("default_code", "=", c)], ["default_code"]) or \
                self.z.search_read("product.product", [("name", "=", c)], ["name"])
            if not got:
                raise ValueError(f"Odoo has no product {c!r} (by internal reference or name): translate the product")
            self._products[c] = got[0]["id"]
        return self._products[c]

    def partner(self, name: str) -> int:
        if name not in self._partners:
            got = self.z.search_read("res.partner", [("name", "=", name), ("parent_id", "=", False)],
                                     ["supplier_rank"])
            got.sort(key=lambda p: -(p.get("supplier_rank") or 0))
            self._partners[name] = got[0]["id"] if got else None
        found = self._partners[name]
        if found is None:
            raise ValueError(f"Odoo has no vendor {name!r}: translate the supplier, or add it in Odoo")
        return found

    def picking_type(self, warehouse: str, what: str) -> int | None:
        """The operation type of a warehouse (incoming, mrp_operation), for a place the mapping translates."""
        if not warehouse:
            return None
        k = (warehouse, what)
        if k not in self._types:
            got = self.z.search_read("stock.picking.type", [("code", "=", what), ("warehouse_id.name", "=", warehouse)],
                                     ["id"])
            if not got:
                raise ValueError(f"Odoo's warehouse {warehouse!r} has no {what.replace('_', ' ')} operation")
            self._types[k] = got[0]["id"]
        return self._types[k]

    def payload(self, o: Any, party: str, items: dict[str, str], places: dict[str, str]) -> bytes:
        if o.change == "withdrawn" or o.cancelled or (o.kind == "purchase_order"
                                                      and not any(not ln.cancelled for ln in o.lines)):
            return json.dumps({"cancel": o.erp_ref}).encode()
        if o.kind == "production_order":
            vals: dict[str, Any] = {"product_id": self.product(items[o.product]), "product_qty": o.qty,
                                    "origin": o.id, "date_deadline": _stamp(o.due)}
            vals["date_start" if self.z.has("mrp.production", "date_start") else "date_planned_start"] = _stamp(o.start)
            t = self.picking_type(places.get(o.location, ""), "mrp_operation")
            if t:
                vals["picking_type_id"] = t
            return json.dumps({"model": "mrp.production", "vals": vals}).encode()
        lines = []
        for ln in o.lines:
            if ln.cancelled:
                continue
            x: dict[str, Any] = {"product_id": self.product(items[ln.product]), "product_qty": ln.qty,
                                 "date_planned": _stamp(ln.date)}
            if ln.price is not None:
                x["price_unit"] = ln.price
            lines.append(x)
        vals = {"partner_id": self.partner(party), "origin": o.id, "lines": lines}
        if o.order_date:
            vals["date_order"] = _stamp(o.order_date)
        t = self.picking_type(places.get(o.location, ""), "incoming")
        if t:
            vals["picking_type_id"] = t
        return json.dumps({"model": "purchase.order", "vals": vals}).encode()

    def _find(self, model: str, o: Any) -> dict[str, Any] | None:
        dom = [("name", "=", o.erp_ref)] if o.erp_ref else [("origin", "=", o.id), ("state", "!=", "cancel")]
        got = self.z.search_read(model, dom, ["name", "state", "product_qty"] if model == "mrp.production"
                                 else ["name", "state"])
        return got[0] if got else None

    def send(self, o: Any, payload: bytes) -> str:
        body = json.loads(payload)
        model = "mrp.production" if o.kind == "production_order" else "purchase.order"
        found = self._find(model, o)
        if "cancel" in body:
            if found is None:
                raise ValueError(f"Odoo has no {o.erp_ref or o.id} to cancel")
            if found.get("state") != "cancel":
                self.z.call(model, "action_cancel" if model == "mrp.production" else "button_cancel", [[found["id"]]],
                            names=("ids",))
            return str(found["name"])
        vals = dict(body["vals"])
        if found is not None and found.get("state") in ("done", "cancel"):
            raise ValueError(f"{found['name']} is {'done' if found['state'] == 'done' else 'cancelled'} in Odoo: it "
                             "cannot change")
        if model == "purchase.order":
            lines = vals.pop("lines")
            if found is None:
                vals["order_line"] = [[0, 0, x] for x in lines]
                oid = self._made(model, vals)
                self.z.call(model, "button_confirm", [[oid]], names=("ids",))
            else:
                oid = found["id"]
                vals["order_line"] = self._lines(oid, lines)
                vals.pop("date_order", None)
                self.z.call(model, "write", [[oid], vals], names=("ids", "vals"))
        elif found is None:
            oid = self._made(model, vals)
            self.z.call(model, "action_confirm", [[oid]], names=("ids",))
        else:
            oid = found["id"]
            qty = vals.pop("product_qty")
            vals.pop("product_id", None)
            if abs(float(found.get("product_qty") or 0) - qty) > 1e-9:
                if found.get("state") == "draft":
                    vals["product_qty"] = qty
                else:
                    wiz = self.z.call("change.production.qty", "create", [[{"mo_id": oid, "product_qty": qty}]],
                                      names=("vals_list",))
                    self.z.call("change.production.qty", "change_prod_qty", [wiz if isinstance(wiz, list) else [wiz]],
                                names=("ids",))
            self.z.call(model, "write", [[oid], vals], names=("ids", "vals"))
        if found is not None:
            return str(found["name"])
        got = self.z.search_read(model, [("id", "=", oid)], ["name"])
        if not got:
            raise ValueError("Odoo made the order but does not give its reference")
        return str(got[0]["name"])

    def _made(self, model: str, vals: dict[str, Any]) -> int:
        got = self.z.call(model, "create", [[vals]], names=("vals_list",))
        oid = got[0] if isinstance(got, list) and got else got
        if not isinstance(oid, int) or isinstance(oid, bool):
            raise ValueError("Odoo made the order but did not give its ID")
        return oid

    def _lines(self, oid: int, lines: list[dict[str, Any]]) -> list[list[Any]]:
        """Odoo's line commands that make its lines ours: a line kept by product, in order, changed; a new one
        added; one no longer here cut to what was received (a confirmed order's lines are not deleted)."""
        theirs = self.z.search_read("purchase.order.line", [("order_id", "=", oid), ("display_type", "=", False)],
                                    ["product_id", "product_qty", "qty_received"], order="sequence, id")
        free = list(theirs)
        out: list[list[Any]] = []
        for x in lines:
            match = next((t for t in free if _id(t.get("product_id")) == x["product_id"]), None)
            if match is None:
                out.append([0, 0, x])
                continue
            free.remove(match)
            out.append([1, match["id"], {k: v for k, v in x.items() if k != "product_id"}])
        for t in free:
            out.append([1, t["id"], {"product_qty": float(t.get("qty_received") or 0)}])
        return out


__all__ = ["Sender", "Session", "check", "read", "rows", "slug"]
