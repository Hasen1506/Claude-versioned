import test from "node:test";
import assert from "node:assert/strict";
import { getExample, listExamples } from "./examples.ts";
import { buildNetworkView, runPlan, validateDataset } from "./engine/core.ts";
import { runActuals, runForecast, runInventory, runPromise, runPurchasing, runSales, runSchedule, runSop } from "./engine/planning.ts";
import { runAsk, runFinance, runScenarioProof, runTower, runWhatIf } from "./engine/analytics.ts";

test("bundled examples load cleanly", () => {
  const examples = listExamples();
  assert.ok(examples.length >= 3, `Expected at least 3 examples, got ${examples.length}`);
  const names = examples.map((e) => e.name);
  assert.ok(names.includes("single_product_plant"));
  assert.ok(names.includes("kitchenware_network"));
  assert.ok(names.includes("chennai_port_pumps"));
});

for (const name of ["single_product_plant", "kitchenware_network", "chennai_port_pumps"]) {
  test(`end-to-end planning pipeline works on ${name}`, () => {
    const ds = getExample(name);
    assert.ok(ds, `Example ${name} should exist`);

    const val = validateDataset(ds);
    assert.equal(val.blocking, false, `${name} should have no blocking validation issues`);

    const net = buildNetworkView(ds);
    assert.ok(net.locations.length > 0);
    assert.equal(net.cycles.length, 0);

    const plan = runPlan(ds);
    assert.equal(plan.ok, true);
    assert.ok(plan.buckets.length > 0);
    assert.ok(plan.nodes.length > 0);
    assert.ok(plan.kpis.orders_buy > 0, `${name} should plan purchase orders`);
    assert.ok(plan.kpis.purchase_cost > 0, `${name} should have positive purchase cost`);
    assert.ok(plan.kpis.on_time_fill_rate >= 0 && plan.kpis.on_time_fill_rate <= 1);

    const fc = runForecast(ds);
    assert.equal(fc.ok, true);

    const inv = runInventory(ds);
    assert.equal(inv.ok, true);
    assert.ok(inv.nodes.length > 0);

    const sop = runSop(ds);
    assert.equal(sop.ok, true);
    assert.ok(sop.buckets.length > 0);

    const sched = runSchedule(ds);
    assert.equal(sched.ok, true);

    const prom = runPromise(ds);
    assert.equal(prom.ok, true);

    const pur = runPurchasing(ds);
    assert.equal(pur.ok, true);

    const sales = runSales(ds);
    assert.equal(sales.currency, ds.settings.currency);

    const act = runActuals(ds);
    assert.ok(act.stock.length > 0);

    const fin = runFinance(ds);
    assert.equal(fin.ok, true);
    assert.equal(fin.reconciliation?.reconciled, true);

    const tower = runTower(ds);
    assert.equal(tower.ok, true);
    assert.ok(tower.kpis.length >= 3);
  });
}

test("what-if, ask, and scenario proof return structured results", () => {
  const ds = getExample("chennai_port_pumps");
  assert.ok(ds);
  const whatif = runWhatIf(ds, [
    { label: "Baseline", chips: [] },
    { label: "Demand +20%", chips: [{ kind: "demand", pct: 0.2 }] },
  ]);
  assert.equal(whatif.scenarios.length, 2);
  assert.ok(whatif.scenarios[1].total_cost >= whatif.scenarios[0].total_cost);

  const ans = runAsk(ds, "What does the plan cost?");
  assert.ok(ans.understood.length > 0);
  assert.ok(ans.answer.length > 0);

  const proof = runScenarioProof("s1-coffee");
  assert.ok(proof);
  assert.equal(proof.ok, true);
  assert.ok(proof.passed > 0);
});
