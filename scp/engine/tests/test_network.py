from scp.network import build_graph, location_layers, supply_options

from .factory import base, demand, ds, load_example


def two_echelon() -> dict:
    d = base()
    d["locations"] += [{"id": "D", "type": "dc"}, {"id": "K", "type": "customer"}]
    d["lanes"] = [{"id": "PD", "origin": "P", "destination": "D", "products": ["A"], "modes": [{"transit_days": 2}]},
                  {"id": "DK", "origin": "D", "destination": "K", "modes": [{"transit_days": 1}]}]
    d["demand"] = [demand("K", "A", "2026-01-15", 10)]
    return d


def test_low_level_codes_span_bom_and_transport():
    g = build_graph(ds(two_echelon()))
    assert g.acyclic
    assert g.llc[("K", "A")] == 0
    assert g.llc[("D", "A")] == 1
    assert g.llc[("P", "A")] == 2
    assert g.llc[("P", "B")] == 3 and g.llc[("P", "C")] == 3
    # every consumer is planned before its supplier
    pos = {n: i for i, n in enumerate(g.order)}
    for up, cons in g.consumers.items():
        for c in cons:
            assert pos[c] < pos[up]


def test_supplier_lane_is_not_a_transfer_option():
    d = two_echelon()
    d["lanes"].append({"id": "SP", "origin": "S", "destination": "P", "modes": [{"transit_days": 4}]})
    opts = supply_options(ds(d), ("P", "B"))
    assert [(o.kind, o.source_id) for o in opts] == [("buy", "PIR-B")]


def test_option_ranking_priority_then_kind():
    d = two_echelon()
    d["locations"].append({"id": "Q", "type": "plant"})
    d["lanes"].append({"id": "QD", "origin": "Q", "destination": "D", "products": ["A"], "priority": 2,
                       "modes": [{"transit_days": 1}]})
    opts = supply_options(ds(d), ("D", "A"))
    assert [o.source_id for o in opts] == ["PD", "QD"]


def test_cycle_detected_and_excluded_from_order():
    d = two_echelon()
    d["lanes"].append({"id": "DP", "origin": "D", "destination": "P", "products": ["A"], "modes": [{"transit_days": 1}]})
    g = build_graph(ds(d))
    assert not g.acyclic
    assert [("D", "A"), ("P", "A")] in g.cycles
    assert ("P", "A") not in g.llc


def test_layers_flow_left_to_right():
    lay = location_layers(load_example("kitchenware_network").model_copy())
    assert lay["SUP-SHENZHEN"] < lay["PLT-PUNE"] < lay["DC-DELHI"] < lay["CUS-NORTH-TRADE"]
    assert lay["CUS-ECOM"] == lay["CUS-WEST-TRADE"]
