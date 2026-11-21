# Prediction module for the demand forecasting dashboard.
#
# Training data: training_frame.pkl (built by build_data.py from the raw
# Rossmann file; it is the same table as cleaned_rossmann.json but keeps the
# Date column, so the model can be trained on the past and tested on the
# future). Store history for the dashboard: history.json (also from
# build_data.py). Categorical labels: encoder_mappings.json.
 
import json
import os
import pickle
from datetime import date, datetime, timedelta
 
import numpy as np
import pandas as pd
from xgboost import XGBRegressor
 
# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
TRAINING_FRAME_PATH = os.path.join(_THIS_DIR, "training_frame.pkl")
HISTORY_PATH = os.path.join(_THIS_DIR, "history.json")
ENCODER_MAPPINGS_PATH = os.path.join(_THIS_DIR, "encoder_mappings.json")
MODEL_CACHE_PATH = os.path.join(_THIS_DIR, "_trained_model_cache.pkl")
 
# ---------------------------------------------------------------------------
# Model settings
# ---------------------------------------------------------------------------
XGB_PARAMS = dict(
    n_estimators=2000,
    learning_rate=0.05,
    max_depth=10,
    random_state=42,
    n_jobs=-1,
)
 
# The model only learns from days up to this date. Everything after it (the
# last 6 weeks of the data) is kept hidden, so a backtest that starts after
# this date is a fair test on days the model has never seen. Set to None to
# train on all the data (best for real forecasting, but then no backtest
# window is fully out-of-sample).
TRAIN_CUTOFF = "2015-06-18"
 
# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PROMO_DURATION_DEFAULT = 108          # median PromoDuration where Promo2 == 1
COMPETITION_DURATION_DEFAULT = 61     # median CompetitionOpenDuration where > 0
 
# Used only when no store is chosen (generic mode). All-time chain averages.
SEED_SALES = 6950.0
 
# When "Continuous campaign" is switched on for a store or a generic profile
# that has no real Promo2 interval, this is the most common real interval, so
# the model never sees Promo2 = 1 together with PromoInterval = "None"
# (a combination that does not exist in the training data).
DEFAULT_PROMO2_INTERVAL = "Jan,Apr,Jul,Oct"
DEFAULT_ASSORTMENT = "a"
 
STATE_HOLIDAY_OPTIONS = {
    "None": "0",
    "Public Holiday": "a",
    "Easter": "b",
    "Christmas": "c",
}
_STATE_HOLIDAY_RAW_TO_LABEL = {v: k for k, v in STATE_HOLIDAY_OPTIONS.items()}
 
STORE_TYPE_OPTIONS = ("a", "b", "c", "d")
 
# In the Rossmann data almost every store is closed on Sundays: 98.6% of Type A,
# 100% of Type C and 99.4% of Type D Sunday-rows are closed. Only Type B stores
# (98% open) trade on Sundays.
SUNDAY_CLOSED_TYPES = ("a", "c", "d")
 
FEATURE_ORDER = [
    "DayOfWeek", "Open", "Promo", "StateHoliday", "SchoolHoliday", "StoreType",
    "Assortment", "Promo2", "PromoInterval", "Year", "Month", "Day",
    "WeekOfYear", "Sales_Lag_7", "Sales_Lag_14", "Sales_Lag_30",
    "RollingMean_7", "RollingMean_30", "CompetitionOpenDuration",
    "PromoDuration", "CompetitionDistance_Log",
]
 
 
# ---------------------------------------------------------------------------
# Encoder mappings
# ---------------------------------------------------------------------------
_encoder_mappings = None
 
 
def _load_encoder_mappings():
    global _encoder_mappings
    if _encoder_mappings is None:
        if not os.path.exists(ENCODER_MAPPINGS_PATH):
            raise FileNotFoundError(
                f"Could not find encoder_mappings.json at {ENCODER_MAPPINGS_PATH}. "
                "Run build_data.py or the encoder export cell in Experiments.ipynb."
            )
        with open(ENCODER_MAPPINGS_PATH, "r") as f:
            _encoder_mappings = json.load(f)
    return _encoder_mappings
 
 
def _encode(column, raw_value):
    column_mapping = _load_encoder_mappings()[column]
    if raw_value not in column_mapping:
        raise ValueError(
            f"Value {raw_value!r} not found in encoder_mappings.json for "
            f"column {column!r}. Known values: {list(column_mapping.keys())}"
        )
    return int(column_mapping[raw_value])
 
 
# ---------------------------------------------------------------------------
# Store history (history.json)
# ---------------------------------------------------------------------------
_history = None
 
 
def _load_history():
    global _history
    if _history is None:
        if not os.path.exists(HISTORY_PATH):
            raise FileNotFoundError(
                f"Could not find history.json at {HISTORY_PATH}. "
                "Run: python build_data.py path/to/rossmann_store_sales.json"
            )
        with open(HISTORY_PATH, "r") as f:
            raw = json.load(f)
        stores = {}
        for store_id, s in raw["stores"].items():
            s = dict(s)
            s["sales"] = np.array(s["sales"], dtype=float)
            # Sunday closed? Decided from the store's own history.
            sales = s["sales"]
            first = date.fromisoformat(raw["first_date"])
            sundays = [i for i in range(len(sales)) if (first + timedelta(days=i)).isoweekday() == 7]
            open_share = float(np.mean(sales[sundays] > 0)) if sundays else 0.0
            s["closed_on_sunday"] = open_share < 0.5
            stores[int(store_id)] = s
        _history = {
            "first_date": date.fromisoformat(raw["first_date"]),
            "last_date": date.fromisoformat(raw["last_date"]),
            "num_days": int(raw["num_days"]),
            "stores": stores,
        }
    return _history
 
 
def get_data_range():
    h = _load_history()
    return h["first_date"], h["last_date"]
 
 
def list_stores():
    """Light list for the store picker (no sales arrays)."""
    h = _load_history()
    return [
        {
            "id": store_id,
            "store_type": s["store_type"],
            "assortment": s["assortment"],
            "competition_distance": s["competition_distance"],
            "promo2": s["promo2"],
            "closed_on_sunday": s["closed_on_sunday"],
        }
        for store_id, s in sorted(h["stores"].items())
    ]
 
 
def store_exists(store_id):
    return store_id in _load_history()["stores"]
 
 
# ---------------------------------------------------------------------------
# Training / model cache
# ---------------------------------------------------------------------------
def _train_model():
    if not os.path.exists(TRAINING_FRAME_PATH):
        raise FileNotFoundError(
            f"Could not find training_frame.pkl at {TRAINING_FRAME_PATH}. "
            "Run: python build_data.py path/to/rossmann_store_sales.json"
        )
    df = pd.read_pickle(TRAINING_FRAME_PATH)
    if TRAIN_CUTOFF is not None:
        df = df[df["Date"] <= pd.Timestamp(TRAIN_CUTOFF)]
 
    print(f"Training XGBoost on {len(df):,} rows "
          f"(up to {df['Date'].max().date()}) - this can take several minutes...")
    model = XGBRegressor(**XGB_PARAMS)
    model.fit(df[FEATURE_ORDER], df["Sales"])
    print("Training complete.")
    return model
 
 
def _cache_is_fresh(cache):
    return (
        isinstance(cache, dict)
        and cache.get("cutoff") == TRAIN_CUTOFF
        and cache.get("params") == XGB_PARAMS
        and cache.get("features") == FEATURE_ORDER
        and os.path.exists(TRAINING_FRAME_PATH)
        and cache.get("built_at", 0) >= os.path.getmtime(TRAINING_FRAME_PATH)
    )
 
 
_model = None
 
 
def _get_model():
    global _model
    if _model is not None:
        return _model
 
    if os.path.exists(MODEL_CACHE_PATH):
        try:
            with open(MODEL_CACHE_PATH, "rb") as f:
                cache = pickle.load(f)
        except Exception:
            cache = None
        if _cache_is_fresh(cache):
            print(f"Loading cached model from {MODEL_CACHE_PATH}")
            _model = cache["model"]
            return _model
 
    _model = _train_model()
    with open(MODEL_CACHE_PATH, "wb") as f:
        pickle.dump({
            "model": _model,
            "cutoff": TRAIN_CUTOFF,
            "params": XGB_PARAMS,
            "features": FEATURE_ORDER,
            "built_at": datetime.now().timestamp(),
        }, f)
    print(f"Saved trained model to {MODEL_CACHE_PATH}.")
    return _model
 
 
# ---------------------------------------------------------------------------
# Store profile: the fixed facts about the store being forecast
# ---------------------------------------------------------------------------
def _make_profile(store_id, store_type, competition_distance):
    """Real store facts when a store is chosen, dashboard values otherwise."""
    if store_id is not None:
        s = _load_history()["stores"][store_id]
        return {
            "store_id": store_id,
            "store_type": s["store_type"],
            "assortment": s["assortment"],
            "competition_distance": s["competition_distance"],
            "competition_since": (s["competition_since_year"], s["competition_since_month"]),
            "promo2_since": (s["promo2_since_year"], s["promo2_since_week"]),
            "promo2_interval": s["promo_interval"] if s["promo2"] == 1 else DEFAULT_PROMO2_INTERVAL,
            "closed_on_sunday": s["closed_on_sunday"],
            "real": True,
        }
    return {
        "store_id": None,
        "store_type": store_type,
        "assortment": DEFAULT_ASSORTMENT,
        "competition_distance": competition_distance,
        "competition_since": None,
        "promo2_since": None,
        "promo2_interval": DEFAULT_PROMO2_INTERVAL,
        "closed_on_sunday": store_type in SUNDAY_CLOSED_TYPES,
        "real": False,
    }
 
 
def _competition_duration(profile, d):
    if profile["competition_since"] is not None:
        year, month = profile["competition_since"]
        if year == 0:
            return 0
        return max(0, (d.year - year) * 12 + (d.month - month))
    has_competition = profile["competition_distance"] is not None and profile["competition_distance"] > 0
    return COMPETITION_DURATION_DEFAULT if has_competition else 0
 
 
def _promo_duration(profile, d, promo2):
    if promo2 != 1:
        return 0
    if profile["promo2_since"] is not None and profile["promo2_since"][0] != 0:
        year, week = profile["promo2_since"]
        return max(0, (d.year - year) * 52 + (int(d.isocalendar().week) - week))
    return PROMO_DURATION_DEFAULT
 
 
# ---------------------------------------------------------------------------
# Feature vector and one-day prediction
# ---------------------------------------------------------------------------
def _build_day_features(d, promo, promo2, state_holiday_raw, school_holiday,
                        profile, lag_7, lag_14, lag_30, rolling_7, rolling_30):
    return {
        "DayOfWeek": d.isoweekday(),
        "Open": 1,
        "Promo": int(promo),
        "StateHoliday": _encode("StateHoliday", state_holiday_raw),
        "SchoolHoliday": int(school_holiday),
        "StoreType": _encode("StoreType", profile["store_type"]),
        "Assortment": _encode("Assortment", profile["assortment"]),
        "Promo2": int(promo2),
        # Promo2 off -> "None", exactly as for non-Promo2 stores in training
        "PromoInterval": _encode("PromoInterval", profile["promo2_interval"] if promo2 == 1 else "None"),
        "Year": d.year,
        "Month": d.month,
        "Day": d.day,
        "WeekOfYear": int(d.isocalendar().week),
        "Sales_Lag_7": lag_7,
        "Sales_Lag_14": lag_14,
        "Sales_Lag_30": lag_30,
        "RollingMean_7": rolling_7,
        "RollingMean_30": rolling_30,
        "CompetitionOpenDuration": _competition_duration(profile, d),
        "PromoDuration": _promo_duration(profile, d, promo2),
        "CompetitionDistance_Log": float(np.log1p(profile["competition_distance"])),
    }
 
 
def _predict_one_day(feature_dict):
    row = pd.DataFrame([feature_dict])[FEATURE_ORDER]
    return float(max(_get_model().predict(row)[0], 0.0))
 
 
# ---------------------------------------------------------------------------
# History seeding: the last 30 trading days before the forecast starts
# ---------------------------------------------------------------------------
def _seed_from_store(store_id, start_date):
    """Last 30 open-day sales before start_date, oldest first (None if none)."""
    h = _load_history()
    sales = h["stores"][store_id]["sales"]
    end_idx = min((start_date - h["first_date"]).days, h["num_days"])  # exclusive
    if end_idx <= 0:
        return None
    open_sales = [v for v in sales[:end_idx] if v > 0]
    return _pad_seed(open_sales)
 
 
def _seed_from_averages(avg_7, avg_30):
    """Build the 30-day seed from the user's average daily sales for the last
    7 days and the last 30 days. Either one may be missing.
 
    The newest 7 slots get the 7-day average; the older 23 slots get the value
    that makes the whole 30-day mean equal the 30-day average.
    """
    if avg_7 is None and avg_30 is None:
        return None
    if avg_7 is None:
        avg_7 = avg_30
    if avg_30 is None:
        avg_30 = avg_7
    older = (30 * avg_30 - 7 * avg_7) / 23
    older = max(older, 0.25 * avg_30)  # a very high 7-day average must not push this to 0 or below
    return [float(older)] * 23 + [float(avg_7)] * 7
 
 
def _pad_seed(open_sales):
    if not open_sales:
        return None
    seed = [float(v) for v in open_sales[-30:]]
    if len(seed) < 30:  # short history: fill the oldest slots with what we have
        seed = [float(np.mean(seed))] * (30 - len(seed)) + seed
    return seed
 
 
# ---------------------------------------------------------------------------
# Recursive multi-day forecast (one track)
# ---------------------------------------------------------------------------
def _generate_track(start_date, num_days, profile, seed, promo_dates, promo2,
                    state_holiday_label, school_holiday,
                    closed_dates=None, state_by_date=None, school_by_date=None,
                    promo_flags_by_date=None):
    """Forecast num_days, feeding each prediction into the next day's lags.
 
    closed_dates / state_by_date / school_by_date / promo_flags_by_date are used
    to replay real conditions for a backtest; when they are None the single
    dashboard values apply to every day.
    """
    history = list(seed) if seed is not None else [SEED_SALES] * 30
    results = []
 
    for i in range(num_days):
        d = start_date + timedelta(days=i)
 
        if closed_dates is not None:
            closed = d in closed_dates
        else:
            closed = profile["closed_on_sunday"] and d.isoweekday() == 7
 
        if closed:
            results.append({"date": d.strftime("%Y-%m-%d"), "predicted_sales": 0.0, "closed": True})
            continue
 
        if promo_flags_by_date is not None:
            promo = promo_flags_by_date.get(d, 0)
        else:
            promo = 1 if d in promo_dates else 0
        state_raw = (state_by_date.get(d, "0") if state_by_date is not None
                     else STATE_HOLIDAY_OPTIONS[state_holiday_label])
        school = (school_by_date.get(d, 0) if school_by_date is not None else school_holiday)
 
        features = _build_day_features(
            d, promo, promo2, state_raw, school, profile,
            lag_7=history[-7], lag_14=history[-14], lag_30=history[-30],
            rolling_7=float(np.mean(history[-7:])), rolling_30=float(np.mean(history[-30:])),
        )
        predicted = _predict_one_day(features)
        results.append({"date": d.strftime("%Y-%m-%d"), "predicted_sales": round(predicted, 2), "closed": False})
 
        history.append(predicted)
        history.pop(0)
 
    return results
 
 
# ---------------------------------------------------------------------------
# Real conditions and accuracy metrics
# ---------------------------------------------------------------------------
def _window_slice(store_id, start_date, num_days):
    """Index range of the window inside the stored history, or None if the
    window is not fully inside the data."""
    h = _load_history()
    start_idx = (start_date - h["first_date"]).days
    end_idx = start_idx + num_days  # exclusive
    if start_idx < 0 or end_idx > h["num_days"]:
        return None
    return start_idx, end_idx
 
 
def _real_conditions(store_id, start_date, num_days):
    """Real promo / holiday / closed-day calendar for the window."""
    h = _load_history()
    s = h["stores"][store_id]
    start_idx, end_idx = _window_slice(store_id, start_date, num_days)
    closed, promo, state, school = set(), {}, {}, {}
    for idx in range(start_idx, end_idx):
        d = h["first_date"] + timedelta(days=idx)
        if s["sales"][idx] <= 0:
            closed.add(d)
        promo[d] = int(s["promo"][idx])
        state[d] = s["state_holiday"][idx]
        school[d] = int(s["school"][idx])
    return closed, promo, state, school
 
 
def _actual_series(store_id, start_date, num_days):
    """Actual daily sales inside the data for the window (None for closed)."""
    h = _load_history()
    sales = h["stores"][store_id]["sales"]
    out = []
    for i in range(num_days):
        d = start_date + timedelta(days=i)
        idx = (d - h["first_date"]).days
        if 0 <= idx < h["num_days"]:
            out.append({"date": d.strftime("%Y-%m-%d"),
                        "sales": float(sales[idx]) if sales[idx] > 0 else None})
    return out
 
 
def _seasonal_naive(store_id, start_date, num_days):
    """Naive forecast: repeat the last observed week (same weekday)."""
    h = _load_history()
    sales = h["stores"][store_id]["sales"]
    start_idx = (start_date - h["first_date"]).days
    out = []
    for i in range(num_days):
        src = start_idx - 7 + (i % 7)
        out.append(float(sales[src]) if 0 <= src < h["num_days"] and sales[src] > 0 else None)
    return out
 
 
def _compute_metrics(predicted, actual, naive):
    """MAPE / MAE / RMSE / total error over days that are open in both."""
    p, a, n = [], [], []
    for pred, act, nv in zip(predicted, actual, naive):
        if pred["closed"] or act["sales"] is None:
            continue
        p.append(pred["predicted_sales"])
        a.append(act["sales"])
        n.append(nv)
    if not a:
        return None
    p, a = np.array(p), np.array(a)
    metrics = {
        "days_compared": int(len(a)),
        "mape": round(float(np.mean(np.abs(a - p) / a) * 100), 2),
        "mae": round(float(np.mean(np.abs(a - p))), 1),
        "rmse": round(float(np.sqrt(np.mean((a - p) ** 2))), 1),
        "total_error_pct": round(float((p.sum() - a.sum()) / a.sum() * 100), 2),
    }
    pairs = [(act, nv) for act, nv in zip(a, n) if nv is not None]
    if pairs:
        aa = np.array([x for x, _ in pairs])
        nn = np.array([y for _, y in pairs])
        metrics["naive_mape"] = round(float(np.mean(np.abs(aa - nn) / aa) * 100), 2)
        metrics["naive_mae"] = round(float(np.mean(np.abs(aa - nn))), 1)
    return metrics
 
 
# ---------------------------------------------------------------------------
# Public API - called by app.py
# ---------------------------------------------------------------------------
def generate_forecast(
    forecast_period_days,
    promo_dates,
    promo2,
    state_holiday_label,
    school_holiday,
    competition_distance,
    store_type,
    start_date=None,
    store_id=None,
    recent_avg_7=None,
    recent_avg_30=None,
    replay_actual=False,
):
    """Return scenario + baseline tracks, summary and (for a chosen store) the
    real history, the actual sales for the window and accuracy metrics.
 
    store_id        - Rossmann store 1-1115: real history, real store facts
    recent_avg_7    - average daily sales of the last 7 days (no store_id)
    recent_avg_30   - average daily sales of the last 30 days (no store_id)
    replay_actual   - with a store whose window is inside the data, forecast
                      under the REAL promo/holiday/closed calendar so the
                      result can be scored against the real sales
    """
    if start_date is None:
        start_date = (datetime.now() + timedelta(days=1)).date()
    promo_dates = set(promo_dates or [])
 
    profile = _make_profile(store_id, store_type, competition_distance)
 
    seed, seed_source = None, "chain average (no history)"
    if store_id is not None:
        seed = _seed_from_store(store_id, start_date)
        if seed is not None:
            seed_source = f"store {store_id} history"
    else:
        seed = _seed_from_averages(recent_avg_7, recent_avg_30)
        if seed is not None:
            seed_source = "your recent average sales"
 
    replay_used = bool(replay_actual and store_id is not None
                       and _window_slice(store_id, start_date, forecast_period_days) is not None)
 
    if replay_used:
        closed, promo_flags, state_map, school_map = _real_conditions(store_id, start_date, forecast_period_days)
        scenario = _generate_track(
            start_date, forecast_period_days, profile, seed, set(), promo2,
            "None", 0, closed_dates=closed, state_by_date=state_map,
            school_by_date=school_map, promo_flags_by_date=promo_flags)
    else:
        scenario = _generate_track(
            start_date, forecast_period_days, profile, seed, promo_dates, promo2,
            state_holiday_label, school_holiday)
 
    # Baseline: normal conditions (no promo, no campaign, no holiday)
    baseline = _generate_track(
        start_date, forecast_period_days, profile, seed, set(), 0, "None", 0)
 
    scenario_sales = [d["predicted_sales"] for d in scenario]
    total = round(sum(scenario_sales), 2)
    open_days = sum(1 for d in scenario if not d["closed"])
    peak_index = int(np.argmax(scenario_sales))
    summary = {
        "total_predicted_sales": total,
        "average_daily_sales": round(total / open_days, 2) if open_days else 0.0,
        "open_days": open_days,
        "peak_day": f"Day {peak_index + 1}",
        "peak_day_date": scenario[peak_index]["date"],
    }
 
    result = {
        "scenario": scenario,
        "baseline": baseline,
        "summary": summary,
        "seed_source": seed_source,
        "replay_used": replay_used,
        "history": None,
        "actual": None,
        "metrics": None,
        "store": None,
        "averages": None,
    }
 
    if store_id is not None:
        h = _load_history()
        s = h["stores"][store_id]
        result["store"] = {
            "id": store_id, "store_type": s["store_type"], "assortment": s["assortment"],
            "competition_distance": s["competition_distance"], "promo2": s["promo2"],
            "closed_on_sunday": s["closed_on_sunday"],
        }
        # Up to 90 days of real history before the forecast starts
        start_idx = (start_date - h["first_date"]).days
        # The last 90 days of data before the start (if the start is long after
        # the data ends, that is simply the last 90 days of the data)
        hi = min(max(start_idx, 0), h["num_days"])
        lo = max(0, hi - 90)
        result["history"] = [
            {"date": (h["first_date"] + timedelta(days=i)).strftime("%Y-%m-%d"),
             "sales": float(s["sales"][i]) if s["sales"][i] > 0 else None}
            for i in range(lo, hi)
        ]
        actual = _actual_series(store_id, start_date, forecast_period_days)
        result["actual"] = actual or None
        if replay_used and actual:
            naive = _seasonal_naive(store_id, start_date, forecast_period_days)
            result["metrics"] = _compute_metrics(scenario, actual, naive)
    elif seed is not None:
        # Echo the user's own numbers so the chart can draw them
        result["averages"] = {"avg_7": recent_avg_7, "avg_30": recent_avg_30}
 
    cutoff = date.fromisoformat(TRAIN_CUTOFF) if TRAIN_CUTOFF else None
    result["train_cutoff"] = TRAIN_CUTOFF
    result["overlaps_training"] = bool(cutoff and start_date <= cutoff)
    return result
 
 
def warm_up():
    _get_model()
    try:
        _load_history()
    except FileNotFoundError as e:
        print(f"Warning: {e}")