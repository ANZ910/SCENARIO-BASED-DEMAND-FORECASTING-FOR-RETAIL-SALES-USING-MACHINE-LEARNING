# Run this ONCE (python build_data.py path/to/rossmann_store_sales.json) after
# Experiments.ipynb. It repeats the notebook's cleaning and feature steps, but
# keeps the Store and Date columns that cleaned_rossmann.json drops, because
# the dashboard now needs them for:
#   1. history.json         - every store's real daily sales (for the store
#                             picker and the actual-vs-predicted chart)
#   2. training_frame.pkl   - the model-ready table WITH dates, so predict.py
#                             can train on the past and test on the future
#                             (a real time split) instead of the last stores.

import json
import os
import sys
 
import numpy as np
import pandas as pd
from sklearn.preprocessing import LabelEncoder
 
HERE = os.path.dirname(os.path.abspath(__file__))
RAW_PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "rossmann_store_sales.json")
 
print(f"Reading {RAW_PATH} ...")
raw = pd.read_json(RAW_PATH)
raw["Date"] = pd.to_datetime(raw["Date"])
raw["StateHoliday"] = raw["StateHoliday"].astype(str)   # '0' and 0 both become '0'
raw = raw.sort_values(["Store", "Date"]).reset_index(drop=True)
 
FIRST_DATE = raw["Date"].min()
LAST_DATE = raw["Date"].max()
NUM_DAYS = (LAST_DATE - FIRST_DATE).days + 1
 
 
# ---------------------------------------------------------------------------
# 1. Same cleaning as Experiments.ipynb (Store and Date are kept this time)
# ---------------------------------------------------------------------------
df = raw[raw["Open"] == 1].copy()
 
median_distance = df["CompetitionDistance"].median()
df["CompetitionDistance"] = df["CompetitionDistance"].fillna(median_distance)
for col in ("CompetitionOpenSinceMonth", "CompetitionOpenSinceYear",
            "Promo2SinceWeek", "Promo2SinceYear"):
    df[col] = df[col].fillna(0).astype(int)
df["PromoInterval"] = df["PromoInterval"].fillna("None")
 
encoders = {}
for col in ["StateHoliday", "StoreType", "Assortment", "PromoInterval"]:
    le = LabelEncoder()
    df[col] = le.fit_transform(df[col].astype(str))
    encoders[col] = le
 
df = df[df["Sales"] > 0]
df = df.dropna()
df = df.sort_values(["Store", "Date"])
 
df["Year"] = df["Date"].dt.year
df["Month"] = df["Date"].dt.month
df["Day"] = df["Date"].dt.day
df["WeekOfYear"] = df["Date"].dt.isocalendar().week.astype(int)
 
g = df.groupby("Store")["Sales"]
df["Sales_Lag_7"] = g.shift(7)
df["Sales_Lag_14"] = g.shift(14)
df["Sales_Lag_30"] = g.shift(30)
df["RollingMean_7"] = g.shift(1).groupby(df["Store"]).transform(lambda x: x.rolling(7).mean())
df["RollingMean_30"] = g.shift(1).groupby(df["Store"]).transform(lambda x: x.rolling(30).mean())
 
df["CompetitionOpenDuration"] = np.where(
    df["CompetitionOpenSinceYear"] == 0, 0,
    (df["Year"] - df["CompetitionOpenSinceYear"]) * 12
    + (df["Month"] - df["CompetitionOpenSinceMonth"]),
).clip(min=0)
df["PromoDuration"] = np.where(
    df["Promo2SinceYear"] == 0, 0,
    (df["Year"] - df["Promo2SinceYear"]) * 52
    + (df["WeekOfYear"] - df["Promo2SinceWeek"]),
).clip(min=0)
df["CompetitionDistance_Log"] = np.log1p(df["CompetitionDistance"])
 
keep = ["Store", "Date", "Sales", "DayOfWeek", "Open", "Promo", "StateHoliday",
        "SchoolHoliday", "StoreType", "Assortment", "Promo2", "PromoInterval",
        "Year", "Month", "Day", "WeekOfYear", "Sales_Lag_7", "Sales_Lag_14",
        "Sales_Lag_30", "RollingMean_7", "RollingMean_30",
        "CompetitionOpenDuration", "PromoDuration", "CompetitionDistance_Log"]
training_frame = df[keep].reset_index(drop=True)
training_frame.to_pickle(os.path.join(HERE, "training_frame.pkl"))
print(f"training_frame.pkl: {len(training_frame):,} rows, "
      f"{training_frame['Date'].min().date()} to {training_frame['Date'].max().date()}")
 
 
# ---------------------------------------------------------------------------
# 2. Encoder mappings: check against the notebook's file if it is there
# ---------------------------------------------------------------------------
mappings = {col: {str(c): int(i) for i, c in enumerate(le.classes_)}
            for col, le in encoders.items()}
mapping_path = os.path.join(HERE, "encoder_mappings.json")
if os.path.exists(mapping_path):
    with open(mapping_path) as f:
        existing = json.load(f)
    same = all({str(k): int(v) for k, v in existing.get(col, {}).items()} == m
               for col, m in mappings.items())
    print("encoder_mappings.json matches the notebook's labels." if same else
          "WARNING: encoder_mappings.json differs from the labels rebuilt here. "
          "Re-export it from the notebook, or delete it and rerun this script.")
else:
    with open(mapping_path, "w") as f:
        json.dump(mappings, f, indent=2)
    print("encoder_mappings.json was missing, so it was written from the rebuilt labels.")
 
 
# ---------------------------------------------------------------------------
# 3. history.json: real daily sales for every store (closed or missing day = 0)
# ---------------------------------------------------------------------------
stores = {}
for store_id, s in raw.groupby("Store"):
    first = s.iloc[0]
    day_index = (s["Date"] - FIRST_DATE).dt.days.to_numpy()
 
    sales = np.zeros(NUM_DAYS, dtype=int)
    promo = np.zeros(NUM_DAYS, dtype=int)
    school = np.zeros(NUM_DAYS, dtype=int)
    state = np.array(["0"] * NUM_DAYS, dtype="<U1")
    # A day only counts as open if the store sold something (same rule as training)
    sales[day_index] = np.where(s["Open"].to_numpy() == 1, s["Sales"].to_numpy(), 0)
    promo[day_index] = s["Promo"].to_numpy()
    school[day_index] = s["SchoolHoliday"].to_numpy()
    state[day_index] = s["StateHoliday"].to_numpy()
 
    distance = first["CompetitionDistance"]
    stores[str(int(store_id))] = {
        "store_type": first["StoreType"],
        "assortment": first["Assortment"],
        "competition_distance": float(median_distance if pd.isna(distance) else distance),
        "competition_since_month": int(0 if pd.isna(first["CompetitionOpenSinceMonth"]) else first["CompetitionOpenSinceMonth"]),
        "competition_since_year": int(0 if pd.isna(first["CompetitionOpenSinceYear"]) else first["CompetitionOpenSinceYear"]),
        "promo2": int(first["Promo2"]),
        "promo2_since_week": int(0 if pd.isna(first["Promo2SinceWeek"]) else first["Promo2SinceWeek"]),
        "promo2_since_year": int(0 if pd.isna(first["Promo2SinceYear"]) else first["Promo2SinceYear"]),
        "promo_interval": "None" if pd.isna(first["PromoInterval"]) else first["PromoInterval"],
        "sales": sales.tolist(),
        "promo": "".join(map(str, promo)),
        "school": "".join(map(str, school)),
        "state_holiday": "".join(state),
    }
 
history = {
    "first_date": FIRST_DATE.strftime("%Y-%m-%d"),
    "last_date": LAST_DATE.strftime("%Y-%m-%d"),
    "num_days": NUM_DAYS,
    "stores": stores,
}
with open(os.path.join(HERE, "history.json"), "w") as f:
    json.dump(history, f, separators=(",", ":"))
size_mb = os.path.getsize(os.path.join(HERE, "history.json")) / 1e6
print(f"history.json: {len(stores)} stores x {NUM_DAYS} days ({size_mb:.1f} MB)")