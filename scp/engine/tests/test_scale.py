"""What the scale work (Phase L) relies on: results worked out once are handed out again only for the same data."""
import pytest

from scp.api.app import post_validate
from scp.network import build_graph
from scp.plan import mrp
from scp.validate import validate
from scp.validate.lenient import lenient_checked

from .factory import ds, example_dict


@pytest.fixture
def keep_every_plan(monkeypatch):
    monkeypatch.setattr(mrp, "_KEEP_AFTER_S", 0.0)
    monkeypatch.setattr(mrp, "_last", None)


def test_the_plan_is_kept_for_the_same_data_only(keep_every_plan):
    d = ds(example_dict("kitchenware_network"))
    first = mrp.run_mrp(d)
    assert mrp.run_mrp(d) is first
    # equal content read again: the same plan
    assert mrp.run_mrp(ds(example_dict("kitchenware_network"))) is first
    # one changed quantity: planned again
    changed = d.model_copy(update={"demand": [d.demand[0].model_copy(update={"qty": d.demand[0].qty + 7}),
                                              *d.demand[1:]]})
    again = mrp.run_mrp(changed)
    assert again is not first
    assert sum(r.qty for r in again.requirements) > sum(r.qty for r in first.requirements) + 6


def test_a_copy_does_not_take_the_network_of_the_original():
    d = ds(example_dict("kitchenware_network"))
    g = build_graph(d)
    assert build_graph(d) is g
    fewer = d.model_copy(update={"lanes": []})
    assert build_graph(fewer) is not g
    kinds = lambda gr: {o.kind for opts in gr.options.values() for o in opts}  # noqa: E731
    assert "transfer" in kinds(g) and "transfer" not in kinds(build_graph(fewer))
    assert fewer.planning_lp(next(iter(d.location_product_by_key))) is not None


def test_the_readiness_gate_uses_the_checks_it_already_ran():
    raw = example_dict("kitchenware_network")
    parsed, aside, checked = lenient_checked(raw)
    assert checked is not None and not aside
    assert checked == validate(parsed)
    assert post_validate(raw).issues == checked
