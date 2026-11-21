# Accuracy evidence for the dashboard model. Run: python backtest_evaluation.py
#
# It scores the model on the last weeks of the data, which predict.py keeps out
# of training (TRAIN_CUTOFF). Two views are reported:
#
#   1. One-step test: every held-out day is predicted from REAL past sales.
#      This is the style of number the notebook reports.
#   2. Recursive backtest: the dashboard's own forecast (predict.generate_forecast
#      with real store history and the real promo / holiday / closed-day
#      calendar). Each day feeds the next day's lags, so errors can build up.
#      This is the number that matches what a user sees on the dashboard.
#
# Both are compared with a naive forecast that just repeats the last observed
# week, to show how much the model adds.
 
import argparse
import os
from datetime import date, timedelta
 
import numpy as np
import pandas as pd
 
import predict
 
parser = argparse.ArgumentParser()
parser.add_argument("--stores", type=int, default=60, help="how many random stores to test")
parser.add_argument("--seed", type=int, default=42)
args = parser.parse_args()
 
if predict.TRAIN_CUTOFF is None:
    raise SystemExit("Set TRAIN_CUTOFF in predict.py first, otherwise there is no unseen data.")
 
cutoff = date.fromisoformat(predict.TRAIN_CUTOFF)
first_date, last_date = predict.get_data_range()
model = predict._get_model()
 
 
def pct(a, p):
    return float(np.mean(np.abs(a - p) / a) * 100)
 
 
# ---------------------------------------------------------------------------
# 1. One-step test on the held-out days (all stores)
# ---------------------------------------------------------------------------
frame = pd.read_pickle(predict.TRAINING_FRAME_PATH)
test = frame[frame["Date"] > pd.Timestamp(cutoff)]
pred = np.maximum(model.predict(test[predict.FEATURE_ORDER]), 0)
actual = test["Sales"].to_numpy(dtype=float)
print(f"\n1) One-step test: {len(test):,} store-days from {test['Date'].min().date()} to {test['Date'].max().date()}")
print(f"   MAPE {pct(actual, pred):.2f}%   MAE {np.mean(np.abs(actual - pred)):.0f}   "
      f"RMSE {np.sqrt(np.mean((actual - pred) ** 2)):.0f}")
 
# ---------------------------------------------------------------------------
# 2. Recursive backtest with the dashboard's own code path
# ---------------------------------------------------------------------------
rng = np.random.default_rng(args.seed)
stores = predict.list_stores()
chosen = rng.choice(len(stores), size=min(args.stores, len(stores)), replace=False)
chosen = [stores[i] for i in chosen]
 
rows = []
for horizon in (7, 14, 30):
    start = cutoff + timedelta(days=1)
    while start + timedelta(days=horizon - 1) <= last_date:
        for s in chosen:
            out = predict.generate_forecast(
                forecast_period_days=horizon, promo_dates=[], promo2=s["promo2"],
                state_holiday_label="None", school_holiday=0,
                competition_distance=0, store_type="a", start_date=start,
                store_id=s["id"], replay_actual=True)
            m = out["metrics"]
            if m is None:
                continue
            rows.append({"horizon": horizon, "start": start.isoformat(), "store": s["id"],
                         "store_type": s["store_type"], **m})
        start += timedelta(days=7)
    print(f"   horizon {horizon}d done")
 
res = pd.DataFrame(rows)
res.to_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "backtest_results.csv"), index=False)
 
print(f"\n2) Recursive backtest: {len(chosen)} random stores, windows entirely after {cutoff}")
print("   (each row averages the per-window metrics; 'naive' repeats the last observed week)\n")
summary = res.groupby("horizon").agg(
    windows=("mape", "size"), model_MAPE=("mape", "mean"), naive_MAPE=("naive_mape", "mean"),
    model_MAE=("mae", "mean"), naive_MAE=("naive_mae", "mean"),
    total_error_pct=("total_error_pct", lambda x: float(np.mean(np.abs(x)))),
).round(2)
print(summary.to_string())
 
print("\n   By store type (all horizons):")
print(res.groupby("store_type").agg(windows=("mape", "size"), model_MAPE=("mape", "mean"),
                                   naive_MAPE=("naive_mape", "mean")).round(2).to_string())
print("\n   Full results saved to backtest_results.csv")