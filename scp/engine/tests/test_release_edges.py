"""Conservation checks for fractional forecasts and repeated placement selections."""
import pytest

from scp.demand import release, run_forecast
from scp.inventory import run_inventory
from scp.inventory.apply import apply_placement

from .factory import base, demand, ds
from .test_demand import dataset, weekly


@pytest.mark.parametrize("quantity", [0.0004, 0.01234, 0.999999, 123.456789])
def test_forecast_release_preserves_fractional_quantities(quantity):
    raw = dataset(weekly("P", "A", [quantity] * 30))
    raw["products"][0]["base_uom"] = "KG"
    data = ds(raw)
    result = run_forecast(data)
    assert result.ok
    expected = sum(point.released_qty for series in result.series for point in series.forecast)
    assert expected == pytest.approx(quantity * 8, abs=1e-9)
    released, _ = release(data, result)
    actual = sum(row.qty for row in released.demand if row.released)
    assert actual == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize("copies", [2, 3, 5])
def test_placement_selection_counts_each_stage_once(copies):
    raw = base()
    raw["demand"] = [demand("P", "A", "2026-01-05", 140, period_days=28)]
    data = ds(raw)
    result = run_inventory(data)
    assert result.ok
    one, expected = apply_placement(data, result, ["P|A"])
    repeated, actual = apply_placement(data, result, ["P|A"] * copies)
    assert repeated.model_dump() == one.model_dump()
    assert len(actual.changes) == 1
    assert actual.value_change == pytest.approx(expected.value_change)
