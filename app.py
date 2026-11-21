import re
from datetime import date, timedelta

from flask import Flask, render_template, request, jsonify
import predict

app = Flask(__name__)

MAX_AVERAGE_SALES = 1_000_000   # sanity limit for a typed-in daily average


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/stores")
def stores():
    """Everything the store picker needs: the store list and the data range."""
    first, last = predict.get_data_range()
    return jsonify({
        "stores": predict.list_stores(),
        "first_date": first.isoformat(),
        "last_date": last.isoformat(),
        "train_cutoff": predict.TRAIN_CUTOFF,
    })


def parse_iso_date(value):
    """Return a date for a 'YYYY-MM-DD' string between 2000 and 2100, else None"""

    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    if not 2000 <= parsed.year <= 2100:
        return None
    return parsed


def parse_average(data, name):
    """Return (value or None, None) or (None, error_message) for an optional average."""
    value = data.get(name)
    if value is None:
        return None, None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= MAX_AVERAGE_SALES:
        return None, f"{name} must be a number above 0 (average daily sales)"
    return float(value), None


def validate_inputs(data):
    """Return (cleaned_inputs, None) if valid, else (None, error_message) if not"""

    if not isinstance(data, dict):
        return None, "Request body must be valid JSON"

    period = data.get("forecast_period_days")
    if period not in [7, 14, 30]:
        return None, "forecast_period_days must be 7, 14, or 30"

    for name in ("promo2", "school_holiday"):
        if data.get(name) not in (0, 1):
            return None, f"{name} must be 0 or 1"

    # start_date is optional: if it is missing, predict.py starts tomorrow
    start_date = None
    if data.get("start_date") is not None:
        start_date = parse_iso_date(data["start_date"])
        if start_date is None:
            return None, "start_date must be a date written as YYYY-MM-DD"

    # promo_dates: the real dates that get Promo = 1 (empty list = no promo)
    raw_promo_dates = data.get("promo_dates", [])
    if not isinstance(raw_promo_dates, list) or len(raw_promo_dates) > period:
        return None, f"promo_dates must be a list of at most {period} dates"

    promo_dates = []
    for raw in raw_promo_dates:
        parsed = parse_iso_date(raw)
        if parsed is None:
            return None, "promo_dates must contain dates written as YYYY-MM-DD"
        promo_dates.append(parsed)

    if promo_dates:
        if start_date is None:
            return None, "start_date is required when promo_dates is given"
        last_day = start_date + timedelta(days=period - 1)
        if any(d < start_date or d > last_day for d in promo_dates):
            return None, "every promo date must fall inside the forecast period"

    label = data.get("state_holiday_label")
    if not isinstance(label, str) or label not in predict.STATE_HOLIDAY_OPTIONS:
        options = ", ".join(predict.STATE_HOLIDAY_OPTIONS)
        return None, f"state_holiday_label must be one of: {options}."

    # Optional: a real store (history + store facts) or the user's own recent averages
    store_id = data.get("store_id")
    if store_id is not None:
        if isinstance(store_id, bool) or not isinstance(store_id, int) or not predict.store_exists(store_id):
            return None, "store_id must be a store number from the store list"
        if start_date is None:
            return None, "start_date is required when a store is chosen"

    recent_avg_7, error = parse_average(data, "recent_avg_7")
    if error:
        return None, error
    recent_avg_30, error = parse_average(data, "recent_avg_30")
    if error:
        return None, error
    if store_id is not None and (recent_avg_7 is not None or recent_avg_30 is not None):
        return None, "Choose a store or type your own average sales, not both"

    replay_actual = data.get("replay_actual", False)
    if not isinstance(replay_actual, bool):
        return None, "replay_actual must be true or false"

    # With a real store, its own type and competition distance are used, so the
    # dashboard values are only checked for the generic (no store) case.
    distance = data.get("competition_distance")
    store_type = data.get("store_type")
    if store_id is None:
        if isinstance(distance, bool) or not isinstance(distance, (int, float)) or distance < 0:
            return None, "competition_distance must be a number that is 0 or more"
        if not isinstance(store_type, str) or store_type not in predict.STORE_TYPE_OPTIONS:
            options = ", ".join(predict.STORE_TYPE_OPTIONS)
            return None, f"store_type must be one of: {options}."
    else:
        distance, store_type = 0, "a"

    cleaned = {
        "forecast_period_days": int(period),
        "start_date": start_date,
        "promo_dates": sorted(set(promo_dates)),
        "promo2": int(data["promo2"]),
        "state_holiday_label": label,
        "school_holiday": int(data["school_holiday"]),
        "competition_distance": float(distance),
        "store_type": store_type,
        "store_id": store_id,
        "recent_avg_7": recent_avg_7,
        "recent_avg_30": recent_avg_30,
        "replay_actual": replay_actual,
    }
    return cleaned, None


@app.route("/forecast", methods=["POST"])
def forecast():
    data = request.get_json(silent=True)
    cleaned, error = validate_inputs(data)
    if error:
        return jsonify({"error": error}), 400

    try:
        result = predict.generate_forecast(**cleaned)
    except Exception:
        app.logger.exception("Forecast generation failed")
        return jsonify({
            "error": "something went wrong while generating the forecast. Please try again"
        }), 500

    return jsonify(result)


if __name__ == "__main__":
    predict.warm_up()
    app.run(debug=True, use_reloader=False)
