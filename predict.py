# Prediction module for the demand forecasting dashboard. Trains an XGBoost
# model from cleaned_rossmann.json and uses encoder_mappings.json for
# categorical lookups (both exported by Experiments.ipynb).

import json
import os
import pickle
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
from xgboost import XGBRegressor

# Paths
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
CLEANED_DATA_PATH = os.path.join(_THIS_DIR, "cleaned_rossmann.json")
ENCODER_MAPPINGS_PATH = os.path.join(_THIS_DIR, "encoder_mappings.json")

# Local training cache, created by predict.py (not by the notebook) to skip
# retraining on every run. If it is missing or older than cleaned_rossmann.json,
# the model is retrained with the same hyperparameters below.
MODEL_CACHE_PATH = os.path.join(_THIS_DIR, "_trained_model_cache.pkl")


# Model hyperparameters

XGB_PARAMS = dict(
    n_estimators=2000,
    learning_rate=0.05,
    max_depth=10,
    random_state=42,
    n_jobs=-1,
)

# Constants (see project decisions log / chat history for how these were derived)

# Duration defaults ( use empirically observed medians from the
# cleaned training data rather than always defaulting to 0, so a toggle
# that is "on" still carries a realistic cumulative-duration signal).
#   PROMO_DURATION_DEFAULT: median PromoDuration (weeks) where Promo2 == 1
#   COMPETITION_DURATION_DEFAULT: median CompetitionOpenDuration (months)
#     where duration > 0 (i.e. a competitor genuinely exists)
PROMO_DURATION_DEFAULT = 108
COMPETITION_DURATION_DEFAULT = 61

# Seed values for the recursive lag/rolling features. The model is
# store-agnostic (FYP1 report Section 3.5), so there is no single store's
# history to start from. These are all-time averages from
# cleaned_rossmann.json, fixed here because it has no Date column to find
# "recent" days.
SEED_SALES_LAG_7 = 6949.19
SEED_SALES_LAG_14 = 6955.01
SEED_SALES_LAG_30 = 6945.27
SEED_ROLLING_MEAN_7 = 6951.97
SEED_ROLLING_MEAN_30 = 6963.30

# StateHoliday human labels shown on the dashboard dropdown -> raw dataset
# values (before label encoding). These raw values are then looked up in
# encoder_mappings.json to get the actual encoded integer.
STATE_HOLIDAY_OPTIONS = {
    "None": "0",
    "Public Holiday": "a",
    "Easter": "b",
    "Christmas": "c",
}

# StoreType raw dataset values accepted from the dashboard dropdown. These
# are looked up in encoder_mappings.json to get the encoded integer.
STORE_TYPE_OPTIONS = ("a", "b", "c", "d")

# Model feature
FEATURE_ORDER = [
    "DayOfWeek",
    "Open",
    "Promo",
    "StateHoliday",
    "SchoolHoliday",
    "StoreType",
    "Assortment",
    "Promo2",
    "PromoInterval",
    "Year",
    "Month",
    "Day",
    "WeekOfYear",
    "Sales_Lag_7",
    "Sales_Lag_14",
    "Sales_Lag_30",
    "RollingMean_7",
    "RollingMean_30",
    "CompetitionOpenDuration",
    "PromoDuration",
    "CompetitionDistance_Log",
]

# Assortment / PromoInterval have no dedicated dashboard input (they are not
# in the wireframe's scenario input panel). Fixed raw-value defaults are used
# so the feature vector stays complete; these are looked up through
# encoder_mappings.json like everything else. StoreType is now a dashboard
# input (see STORE_TYPE_OPTIONS).
DEFAULT_ASSORTMENT = "a"
DEFAULT_PROMO_INTERVAL = "None"

# Encoder mappings (loaded once from the notebook's)
_encoder_mappings = None

# Load encoder_mappings.json once and cache it.
def _load_encoder_mappings():
    global _encoder_mappings
    if _encoder_mappings is None:
        if not os.path.exists(ENCODER_MAPPINGS_PATH):
            raise FileNotFoundError(
                f"Could not find encoder_mappings.json at {ENCODER_MAPPINGS_PATH}. "
                "Run the encoder export cell in Experiments.ipynb first, then "
                "copy encoder_mappings.json into the same folder as predict.py."
            )
        with open(ENCODER_MAPPINGS_PATH, "r") as f:
            _encoder_mappings = json.load(f)
    return _encoder_mappings


# Return the encoded integer for a raw categorical value.
def _encode(column, raw_value):
    mappings = _load_encoder_mappings()
    column_mapping = mappings[column]
    if raw_value not in column_mapping:
        raise ValueError(
            f"Value {raw_value!r} not found in encoder_mappings.json for "
            f"column {column!r}. Known values: {list(column_mapping.keys())}"
        )
    return int(column_mapping[raw_value])

# Load cleaned_rossmann.json.
def _load_cleaned_data():
    if not os.path.exists(CLEANED_DATA_PATH):
        raise FileNotFoundError(
            f"Could not find cleaned_rossmann.json at {CLEANED_DATA_PATH}. "
            "Run Experiments.ipynb to produce it, then place it in the same "
            "folder as predict.py."
        )
    df = pd.read_json(CLEANED_DATA_PATH, orient="records")
    return df


# Train XGBoost on the cleaned data (80/20 time split, no shuffle).
def _train_model():
    df = _load_cleaned_data()

    X = df.drop("Sales", axis=1)
    y = df["Sales"]

    split_index = int(len(df) * 0.8)
    X_train = X.iloc[:split_index]
    y_train = y.iloc[:split_index]

    print("Training XGBoost model (n_estimators=2000) - this can take a few minutes...")
    model = XGBRegressor(**XGB_PARAMS)
    model.fit(X_train, y_train)
    print("Training complete.")

    return model


# True if the cache exists and is newer than cleaned_rossmann.json.
def _cache_is_fresh():
    if not os.path.exists(MODEL_CACHE_PATH):
        return False
    if not os.path.exists(CLEANED_DATA_PATH):
        return False
    return os.path.getmtime(MODEL_CACHE_PATH) >= os.path.getmtime(CLEANED_DATA_PATH)


def _load_model_from_cache():
    with open(MODEL_CACHE_PATH, "rb") as f:
        return pickle.load(f)


def _save_model_to_cache(model):
    with open(MODEL_CACHE_PATH, "wb") as f:
        pickle.dump(model, f)


_model = None


# Return the model: from memory, else disk cache, else train it.
def _get_model():
    global _model
    if _model is not None:
        return _model

    if _cache_is_fresh():
        print(f"Loading cached model from {MODEL_CACHE_PATH}")
        _model = _load_model_from_cache()
    else:
        _model = _train_model()
        _save_model_to_cache(_model)
        print(f"Saved trained model to {MODEL_CACHE_PATH} for faster future runs.")

    return _model


# Feature vector construction

# Apply log1p, same as training.
def _competition_distance_to_log(distance_metres):
    return float(np.log1p(distance_metres))


# Build one day's feature dict (matches FEATURE_ORDER).
def _build_day_features(
    date,
    promo,
    promo2,
    state_holiday_label,
    school_holiday,
    competition_distance,
    store_type,
    lag_7,
    lag_14,
    lag_30,
    rolling_7,
    rolling_30,
):
    state_holiday_raw = STATE_HOLIDAY_OPTIONS[state_holiday_label]

    # PromoDuration / CompetitionOpenDuration: Option A defaults.
    # 0 when the corresponding condition is off, empirical median when on,
    # since the dashboard has no "since date" input to compute this directly.
    promo_duration = PROMO_DURATION_DEFAULT if promo2 == 1 else 0
    has_competition = competition_distance is not None and competition_distance > 0
    competition_duration = COMPETITION_DURATION_DEFAULT if has_competition else 0

    features = {
        "DayOfWeek": date.isoweekday(),
        "Open": 1,  # dashboard always forecasts for an open store
        "Promo": int(promo),
        "StateHoliday": _encode("StateHoliday", state_holiday_raw),
        "SchoolHoliday": int(school_holiday),
        "StoreType": _encode("StoreType", store_type),
        "Assortment": _encode("Assortment", DEFAULT_ASSORTMENT),
        "Promo2": int(promo2),
        "PromoInterval": _encode("PromoInterval", DEFAULT_PROMO_INTERVAL),
        "Year": date.year,
        "Month": date.month,
        "Day": date.day,
        "WeekOfYear": int(date.isocalendar().week),
        "Sales_Lag_7": lag_7,
        "Sales_Lag_14": lag_14,
        "Sales_Lag_30": lag_30,
        "RollingMean_7": rolling_7,
        "RollingMean_30": rolling_30,
        "CompetitionOpenDuration": competition_duration,
        "PromoDuration": promo_duration,
        "CompetitionDistance_Log": _competition_distance_to_log(competition_distance),
    }
    return features


# Predict sales for one day (never below 0).
def _predict_one_day(feature_dict):
    model = _get_model()
    row = pd.DataFrame([feature_dict])[FEATURE_ORDER]
    pred = model.predict(row)[0]
    return float(max(pred, 0.0))  # sales cannot be negative


# True if the store is closed on this date. Type c stores are closed on
# Sundays in the training data.
def _is_closed(store_type, date):
    return store_type == "c" and date.isoweekday() == 7


# Recursive multi-day forecast (scenario or baseline track)
# Forecast num_days recursively, feeding each prediction into the next day's lags.
# promo_dates is a set of datetime.date objects: Promo is 1 on those real
# dates and 0 on every other day. Promo on a closed day has no effect.
def _generate_track(
    start_date,
    num_days,
    promo_dates,
    promo2,
    state_holiday_label,
    school_holiday,
    competition_distance,
    store_type,
):
    history = [SEED_SALES_LAG_30] * 30  # oldest -> newest, index -1 is "yesterday"
    history[-7:] = [SEED_SALES_LAG_7] * 7
    history[-14:] = [SEED_SALES_LAG_14] * 14

    results = []

    for i in range(num_days):
        current_date = start_date + timedelta(days=i)

        # Closed days: 0 sales, and the lag history is left untouched
        if _is_closed(store_type, current_date):
            results.append({
                "date": current_date.strftime("%Y-%m-%d"),
                "predicted_sales": 0.0,
                "closed": True,
            })
            continue

        lag_7 = history[-7]
        lag_14 = history[-14]
        lag_30 = history[-30]
        rolling_7 = float(np.mean(history[-7:]))
        rolling_30 = float(np.mean(history[-30:]))

        features = _build_day_features(
            date=current_date,
            promo=1 if current_date in promo_dates else 0,
            promo2=promo2,
            state_holiday_label=state_holiday_label,
            school_holiday=school_holiday,
            competition_distance=competition_distance,
            store_type=store_type,
            lag_7=lag_7,
            lag_14=lag_14,
            lag_30=lag_30,
            rolling_7=rolling_7,
            rolling_30=rolling_30,
        )

        predicted_sales = _predict_one_day(features)

        results.append({
            "date": current_date.strftime("%Y-%m-%d"),
            "predicted_sales": round(predicted_sales, 2),
            "closed": False,
        })

        history.append(predicted_sales)
        history.pop(0)

    return results

# Public API - called by application.py

# Return {"scenario", "baseline", "summary"}; baseline has no promos or holidays.
# promo_dates: iterable of datetime.date objects that get Promo = 1. Dates
# outside the forecast window are never reached, and promo on a closed day is
# ignored. start_date: first forecast day (datetime.date); defaults to tomorrow.
def generate_forecast(
    forecast_period_days,
    promo_dates,
    promo2,
    state_holiday_label,
    school_holiday,
    competition_distance,
    store_type,
    start_date=None,
):
    if start_date is None:
        start_date = (datetime.now() + timedelta(days=1)).date()

    promo_dates = set(promo_dates or [])

    scenario = _generate_track(
        start_date=start_date,
        num_days=forecast_period_days,
        promo_dates=promo_dates,
        promo2=promo2,
        state_holiday_label=state_holiday_label,
        school_holiday=school_holiday,
        competition_distance=competition_distance,
        store_type=store_type,
    )

    baseline = _generate_track(
        start_date=start_date,
        num_days=forecast_period_days,
        promo_dates=set(),
        promo2=0,
        state_holiday_label="None",
        school_holiday=0,
        competition_distance=competition_distance,
        store_type=store_type,
    )

    scenario_sales = [d["predicted_sales"] for d in scenario]
    total_predicted_sales = round(sum(scenario_sales), 2)

    # Average over open days only, so closed days (Type c Sundays) do not
    # drag the average down.
    open_days = sum(1 for d in scenario if not d["closed"])
    average_daily_sales = (
        round(total_predicted_sales / open_days, 2) if open_days > 0 else 0.0
    )

    peak_index = int(np.argmax(scenario_sales))
    peak_day_label = f"Day {peak_index + 1}"
    peak_day_date = scenario[peak_index]["date"]

    summary = {
        "total_predicted_sales": total_predicted_sales,
        "average_daily_sales": average_daily_sales,
        "open_days": open_days,
        "peak_day": peak_day_label,
        "peak_day_date": peak_day_date,
    }

    return {
        "scenario": scenario,
        "baseline": baseline,
        "summary": summary,
    }

# Train or load the model at startup so the first request is fast.
def warm_up():
    _get_model()