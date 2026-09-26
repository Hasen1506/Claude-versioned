"""The supply network as a graph.

* **Planning nodes** are (location, product) pairs that can hold stock and need planning.
* **Supply options** say how a node can be replenished: make (production source), buy
  (purchasing source) or transfer (inbound lane from another stocking location).
* **Low-level code** (LLC): 0 for nodes nothing else consumes; otherwise 1 + the max LLC of
  its consumers — across BOM *and* transport edges — so MRP can plan every node after all of
  its requirements are known (S/4 guide §8, figure 8.1, extended to a network).
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Literal

from ..model import Dataset, LocationType, ProcurementType

Node = tuple[str, str]  # (location, product)
OptionKind = Literal["make", "buy", "transfer"]


@dataclass(frozen=True)
class SupplyOption:
    kind: OptionKind
    source_id: str            # production source / purchasing source / lane id
    node: Node                # the node being supplied
    upstream: tuple[Node, ...]  # component nodes (make), origin node (transfer), supplier node (buy)
    priority: int
    quota: float | None


@dataclass
class NetworkGraph:
    nodes: list[Node]
    options: dict[Node, list[SupplyOption]]
    consumers: dict[Node, set[Node]]
    suppliers_of: dict[Node, set[Node]]
    llc: dict[Node, int]
    cycles: list[list[Node]]
    order: list[Node] = field(default_factory=list)  # planning order: ascending LLC

    @property
    def acyclic(self) -> bool:
        return not self.cycles


_KIND_RANK = {"make": 0, "transfer": 1, "buy": 2}


def supply_options(ds: Dataset, node: Node) -> list[SupplyOption]:
    """Every way ``node`` can be replenished, ranked by priority then make < transfer < buy."""
    from ..plan.structure import needs   # the BOM rules live with planning; imported late to avoid a cycle

    loc, prod = node
    lp = ds.location_product_by_key.get(node)
    proc = lp.procurement if lp else ProcurementType.ANY
    out: list[SupplyOption] = []
    for ps in ds.production_sources:
        if ps.location == loc and ps.product == prod and proc is not ProcurementType.EXTERNAL:
            ups = tuple((loc, n.product) for n in needs(ds, ps))
            out.append(SupplyOption("make", ps.id, node, ups, ps.priority, ps.quota))
    if proc is ProcurementType.MAKE:
        out.sort(key=lambda o: (o.priority, _KIND_RANK[o.kind], o.source_id))
        return out
    for pu in ds.purchasing_sources:
        if pu.location == loc and pu.product == prod:
            out.append(SupplyOption("buy", pu.id, node, ((pu.supplier, prod),), pu.priority, pu.quota))
    for ln in ds.lanes:
        if ln.destination != loc or not ln.carries(prod):
            continue
        otype = ds.location_type(ln.origin)
        if otype in (LocationType.SUPPLIER, LocationType.CUSTOMER):
            continue  # supplier lanes carry purchases (freight), not transfers
        out.append(SupplyOption("transfer", ln.id, node, ((ln.origin, prod),), ln.priority, ln.quota))
    out.sort(key=lambda o: (o.priority, _KIND_RANK[o.kind], o.source_id))
    return out


def seed_nodes(ds: Dataset) -> list[Node]:
    """Nodes that exist regardless of sourcing: demand points, maintained location-products,
    and nodes with scheduled receipts. A record with a broken reference (unknown location or product)
    seeds nothing: the readiness gate reports it once, as the broken reference, not again as a phantom
    node with no source."""
    seen: dict[Node, None] = {}

    def add(loc: str, prod: str, *, supplier_ok: bool = False) -> None:
        t = ds.location_type(loc)
        if t is None or prod not in ds.product_by_id or (t is LocationType.SUPPLIER and not supplier_ok):
            return
        seen.setdefault((loc, prod))

    for d in ds.demand:
        add(d.location, d.product)
    for lp in ds.location_products:
        add(lp.location, lp.product)
    for r in ds.receipts:
        add(r.location, r.product, supplier_ok=True)
    return list(seen)


def build_graph(ds: Dataset) -> NetworkGraph:
    """Expand upstream from the seed nodes through every supply option."""
    options: dict[Node, list[SupplyOption]] = {}
    consumers: dict[Node, set[Node]] = defaultdict(set)
    suppliers_of: dict[Node, set[Node]] = defaultdict(set)
    queue: deque[Node] = deque(seed_nodes(ds))
    known: dict[Node, None] = dict.fromkeys(queue)
    after: list[tuple[Node, Node]] = []   # (main, co-product): the co-product is planned after its main product
    while queue:
        node = queue.popleft()
        opts = supply_options(ds, node)
        options[node] = opts
        for o in opts:
            if o.kind == "buy":
                continue  # supplier nodes are leaves, not planned
            ups = list(o.upstream)
            if o.kind == "make":
                ps = ds.production_source_by_id[o.source_id]
                for co in ps.co_products:
                    cn = (node[0], co.product)
                    if co.product in ds.product_by_id:
                        after.append((node, cn))
                        if cn not in known:
                            known[cn] = None
                            queue.append(cn)
            for up in ups:
                consumers[up].add(node)
                suppliers_of[node].add(up)
                if up not in known:
                    known[up] = None
                    queue.append(up)
    nodes = list(known)
    # the ordering edges count only for the planning order, not as supply
    order_cons = {k: set(v) for k, v in consumers.items()}
    order_sups = {k: set(v) for k, v in suppliers_of.items()}
    for main, co in after:
        order_cons.setdefault(co, set()).add(main)
        order_sups.setdefault(main, set()).add(co)
    llc, cycles = _low_level_codes(nodes, order_cons, order_sups)
    order = sorted((n for n in nodes if n in llc), key=lambda n: (llc[n], n))
    return NetworkGraph(nodes, options, dict(consumers), dict(suppliers_of), llc, cycles, order)


def _low_level_codes(nodes: list[Node], consumers: dict[Node, set[Node]],
                     suppliers_of: dict[Node, set[Node]]) -> tuple[dict[Node, int], list[list[Node]]]:
    remaining = {n: len(consumers.get(n, ())) for n in nodes}
    llc: dict[Node, int] = {}
    q = deque(n for n in nodes if remaining[n] == 0)
    for n in q:
        llc[n] = 0
    while q:
        v = q.popleft()
        for u in suppliers_of.get(v, ()):
            llc[u] = max(llc.get(u, 0), llc[v] + 1)
            remaining[u] -= 1
            if remaining[u] == 0:
                q.append(u)
    unresolved = [n for n in nodes if remaining[n] > 0]
    cycles = _cycles(unresolved, suppliers_of) if unresolved else []
    for n in unresolved:
        llc.pop(n, None)
    return llc, cycles


def _cycles(nodes: list[Node], suppliers_of: dict[Node, set[Node]]) -> list[list[Node]]:
    """Strongly connected components with more than one node (or a self-loop): Tarjan."""
    idx: dict[Node, int] = {}
    low: dict[Node, int] = {}
    on: set[Node] = set()
    stack: list[Node] = []
    out: list[list[Node]] = []
    counter = [0]
    scope = set(nodes)

    def strong(v: Node) -> None:
        # iterative Tarjan to avoid recursion limits on long chains
        work = [(v, iter(sorted(set(suppliers_of.get(v, ())) & scope)))]
        idx[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on.add(v)
        while work:
            node, it = work[-1]
            advanced = False
            for w in it:
                if w not in idx:
                    idx[w] = low[w] = counter[0]
                    counter[0] += 1
                    stack.append(w)
                    on.add(w)
                    work.append((w, iter(sorted(set(suppliers_of.get(w, ())) & scope))))
                    advanced = True
                    break
                if w in on:
                    low[node] = min(low[node], idx[w])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == idx[node]:
                comp = []
                while True:
                    w = stack.pop()
                    on.discard(w)
                    comp.append(w)
                    if w == node:
                        break
                if len(comp) > 1 or node in suppliers_of.get(node, ()):
                    out.append(sorted(comp))

    for n in sorted(nodes):
        if n not in idx:
            strong(n)
    return out


# --------------------------------------------------------------------------------------------
# Location-level view for the network designer
# --------------------------------------------------------------------------------------------
@dataclass
class LocationEdge:
    origin: str
    destination: str
    kind: Literal["lane", "purchase"]
    ids: list[str]
    products: list[str] | None  # None = all products


_TYPE_LAYER = {
    LocationType.SUPPLIER: 0, LocationType.PLANT: 1, LocationType.WAREHOUSE: 2,
    LocationType.DC: 2, LocationType.STORE: 3, LocationType.CUSTOMER: 4,
}


def location_edges(ds: Dataset) -> list[LocationEdge]:
    agg: dict[tuple[str, str, str], LocationEdge] = {}
    for ln in ds.lanes:
        key = (ln.origin, ln.destination, "lane")
        e = agg.setdefault(key, LocationEdge(ln.origin, ln.destination, "lane", [], []))
        e.ids.append(ln.id)
        if e.products is not None:
            e.products = None if not ln.products else sorted(set(e.products) | set(ln.products))
    for pu in ds.purchasing_sources:
        key = (pu.supplier, pu.location, "purchase")
        e = agg.setdefault(key, LocationEdge(pu.supplier, pu.location, "purchase", [], []))
        e.ids.append(pu.id)
        if e.products is not None:
            e.products = sorted(set(e.products) | {pu.product})
    return list(agg.values())


def location_layers(ds: Dataset) -> dict[str, int]:
    """Column for each location in a left-to-right flow layout: longest path from the sources,
    never left of its type's natural column, customers always last."""
    layer = {loc.id: _TYPE_LAYER[loc.type] for loc in ds.locations}
    edges = [(e.origin, e.destination) for e in location_edges(ds)
             if e.origin in layer and e.destination in layer]
    for _ in range(len(layer)):
        changed = False
        for a, b in edges:
            if layer[b] < layer[a] + 1 and ds.location_type(b) is not LocationType.CUSTOMER:
                layer[b] = layer[a] + 1
                changed = True
        if not changed:
            break
    last = max([v for k, v in layer.items() if ds.location_type(k) is not LocationType.CUSTOMER],
               default=0) + 1
    for loc in ds.locations:
        if loc.type is LocationType.CUSTOMER:
            layer[loc.id] = max(last, _TYPE_LAYER[LocationType.CUSTOMER])
    # compact: renumber used layers 0..k
    used = sorted(set(layer.values()))
    remap = {v: i for i, v in enumerate(used)}
    return {k: remap[v] for k, v in layer.items()}
