"""Schema-level invariants: invalid states are unconstructable."""
import pytest
from pydantic import ValidationError

from scp.model import Dataset, LotSizing, ProductionSource, Resource, SafetyStockPolicy, TransportLane

from .factory import base, ds, example_dict


def test_examples_round_trip():
    for name in ("kitchenware_network", "single_product_plant"):
        d = Dataset.model_validate(example_dict(name))
        again = Dataset.model_validate_json(d.model_dump_json())
        assert again == d


def test_unknown_field_rejected():
    d = base()
    d["products"][0]["colour"] = "red"
    with pytest.raises(ValidationError):
        ds(d)


@pytest.mark.parametrize("value", [-0.1, 1.5])
def test_fraction_bounds(value):
    d = base()
    d["settings"]["wacc"] = value
    with pytest.raises(ValidationError):
        ds(d)


def test_percent_is_not_accepted_as_fraction():
    d = base()
    d["settings"]["default_service_level"] = 95  # a percent typed by mistake
    with pytest.raises(ValidationError):
        ds(d)


def test_lot_sizing_requires_parameters():
    with pytest.raises(ValidationError):
        LotSizing(policy="FIXED")
    with pytest.raises(ValidationError):
        LotSizing(policy="POQ")
    assert LotSizing(policy="POQ", periods=2).periods == 2


def test_safety_stock_requires_parameters():
    with pytest.raises(ValidationError):
        SafetyStockPolicy(method="fixed")
    with pytest.raises(ValidationError):
        SafetyStockPolicy(method="days_of_supply", days=0)


def test_resource_day_cannot_exceed_24h():
    with pytest.raises(ValidationError):
        Resource(id="R", location="P", shifts_per_day=3, hours_per_shift=8, overtime_hours_per_day=2)
    r = Resource(id="R", location="P", units=2, shifts_per_day=2, hours_per_shift=8, efficiency=0.5)
    assert r.hours_per_workday == pytest.approx(16.0)


def test_production_source_structure():
    ok = dict(id="PV", location="P", product="A", components=[{"product": "B", "qty": 1, "operation": 10}],
              operations=[{"seq": 20, "resource": "M"}, {"seq": 10, "resource": "M"}])
    ps = ProductionSource(**ok)
    assert [o.seq for o in ps.operations] == [10, 20]  # sorted by seq
    for bad in (
        {**ok, "components": [{"product": "B", "qty": 1}, {"product": "B", "qty": 2}]},     # duplicate line
        {**ok, "components": [{"product": "A", "qty": 1}]},                                 # self component
        {**ok, "components": [{"product": "B", "qty": 1, "operation": 99}]},                # unknown op
        {**ok, "operations": [{"seq": 10, "resource": "M"}, {"seq": 10, "resource": "M"}]},  # duplicate seq
        {**ok, "assembly_scrap": 1.0},                                                       # 100% scrap
    ):
        with pytest.raises(ValidationError):
            ProductionSource(**bad)


def test_operation_labor_hours_need_labor_resource():
    with pytest.raises(ValidationError):
        ProductionSource(id="PV", location="P", product="A",
                         operations=[{"seq": 10, "resource": "M", "labor_hours_per_unit": 0.1}])


def test_lane_rules():
    with pytest.raises(ValidationError):
        TransportLane(id="L", origin="X", destination="X", modes=[{"transit_days": 1}])
    with pytest.raises(ValidationError):
        TransportLane(id="L", origin="X", destination="Y", modes=[])
    with pytest.raises(ValidationError):
        TransportLane(id="L", origin="X", destination="Y",
                      modes=[{"transit_days": 1, "default": True}, {"transit_days": 2, "default": True}])
    ln = TransportLane(id="L", origin="X", destination="Y",
                       modes=[{"mode": "rail", "transit_days": 5}, {"mode": "truck_ftl", "transit_days": 2, "default": True}])
    assert ln.planning_mode.transit_days == 2
    assert ln.carries("anything")


def test_json_schema_carries_unit_and_ref_metadata():
    schema = Dataset.model_json_schema()
    op = schema["$defs"]["Operation"]["properties"]
    assert op["resource"]["x-ref"] == "resource"
    assert op["run_hours_per_unit"]["x-unit"] == "hours"
    lp = schema["$defs"]["LocationProduct"]["properties"]
    assert lp["holding_rate"]["x-unit"] == "fraction"
