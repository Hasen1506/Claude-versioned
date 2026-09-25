# TimesFM in SCP: what it is, whether it helps, and how it is wired in

## What it is

TimesFM is Google Research's pretrained time-series foundation model (a decoder-only transformer,
ICML 2024). It forecasts a series **zero-shot**: nothing is fitted per series, and a whole portfolio
goes through one batched forward pass. The package is `timesfm` on PyPI (Apache-2.0 code). Its
checkpoints differ in licence:

| Checkpoint | Size | Weights licence | Usable for a business planning system? |
|---|---|---|---|
| `google/timesfm-2.5-200m-pytorch` | 200M (+30M quantile head), 16k context | **Apache-2.0** | **Yes**, and it is the default here |
| `google/timesfm-3.0-pytorch` (Aug 2026) | 330M, multivariate and covariates | **Non-commercial only** | No. It is refused unless `SCP_TIMESFM_ALLOW_NONCOMMERCIAL=1` is set for evaluation |
| 1.0 / 2.0 | 200M / 500M | Apache-2.0 | Superseded by 2.5 |

TimesFM 3.0 ranks first on public benchmarks (GIFT-Eval, fev-bench). Its weights cannot be used
in production, so the adapter targets 2.5.

## Is it "way better" than the statistical models?

Not uniformly. Overall:

- **Where it tends to win:** longer, patterned histories (clear seasonality, regime shifts, weekly
  plus yearly cycles), many related series, and new series with enough context. On public benchmarks
  it matches or beats tuned ETS/ARIMA on average, without per-series tuning.
- **Where it does not:** short histories (fewer than about a season of weeks), intermittent or
  lumpy spare-part demand (Croston/SBA/TSB remain the right tools), and series that are mostly
  promotion-driven, where cleansing and event lifts matter more than the model.
- **Costs:** PyTorch and about 1 GB of weights on the engine host. CPU inference is fine for
  thousands of weekly series; a GPU helps above that. None of it runs in the browser.

For a small or mid-sized organisation the right answer is empirical, per series: **enter TimesFM
into the same backtest as every other model and let it win only where it measurably does.** SCP
does exactly that.

## How it is integrated

`engine/scp/demand/foundation.py` wraps TimesFM 2.5 behind a small `Provider` interface:

1. The forecast run collects every series' context at every rolling backtest origin, plus the full
   history for the future, and calls TimesFM **twice in total** (one batch for the backtest, one for
   the forecast). This does not grow with the number of series.
2. TimesFM's forecasts are scored with the same metric (MASE, WAPE or RMSE) on the same origins as
   the statistical models, and appear in the same leaderboard.
3. It becomes a series' champion only if it beats the others there. The forecast-value-add column
   shows by how much.
4. If TimesFM is not installed, not enabled, or fails to load, the run carries on with the
   statistical models, and the Demand page shows why TimesFM was not used.

To enable it on the engine host:

```bash
cd scp/engine
pip install -e ".[timesfm]"                 # timesfm[torch]
export SCP_TIMESFM=1
export SCP_TIMESFM_CHECKPOINT=google/timesfm-2.5-200m-pytorch   # or a local directory with the weights
uvicorn scp.api.app:app
```

Then tick `timesfm` in **Demand → Forecast settings → Models** and re-run the forecast.

## Verification

- `tests/test_demand.py::test_foundation_model_competes_and_wins_when_it_is_better` stands in an
  oracle provider. It checks that the foundation model enters the backtest, is batched into exactly
  two calls, wins where it is better, and that its forecast is what gets released.
- Other tests check that TimesFM is skipped when it is not selected, is off by default, and that
  the 3.0 non-commercial checkpoint is refused.
- The development environment for this change blocks Hugging Face downloads, so the real weights
  were not run here. The adapter follows the published `timesfm` 2.5 API
  (`TimesFM_2p5_200M_torch.from_pretrained`, `compile(ForecastConfig(...))`, `forecast(horizon, inputs)`).
  Run it once on a host with network access before relying on it.
