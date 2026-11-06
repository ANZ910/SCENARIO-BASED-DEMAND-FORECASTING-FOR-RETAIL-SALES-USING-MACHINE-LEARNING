import re
from datetime import date, timedelta

from flask import Flask, render_template, request, jsonify
import predict

app = Flask(__name__)

@app.route("/")
def index():
    return render_template("index.html")


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


def validate_inputs(data):
    """Return (cleaned_inputs, None) if valid, else (None, error_message) if not"""

    if not isinstance(data, dict):
        return None, "Request body must be valid JSON"

    period = data.get("forecast_period_days")
    if period not in [7, 14, 30]:
        return None, "forecast_period_days must be 7, 14, or 30"

    for name in ("promo2", "school_holiday"):
        if data.get(name) not in (0,1):
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

    distance = data.get("competition_distance")
    if isinstance(distance, bool) or not isinstance(distance, (int, float)) or distance<0:
        return None, "competition_distance must be a number that is 0 or more"

    store_type = data.get("store_type")
    if not isinstance(store_type, str) or store_type not in predict.STORE_TYPE_OPTIONS:
        options = ", ".join(predict.STORE_TYPE_OPTIONS)
        return None, f"store_type must be one of: {options}."

    cleaned = {
        "forecast_period_days": int(period),
        "start_date": start_date,
        "promo_dates": sorted(set(promo_dates)),
        "promo2": int(data["promo2"]),
        "state_holiday_label": label,
        "school_holiday": int(data["school_holiday"]),
        "competition_distance": float(distance),
        "store_type": store_type
    }
    return cleaned, None

@app.route("/forecast", methods=["POST"])

def forecast():
    data = request.get_json(silent = True)
    cleaned, error = validate_inputs(data)
    if error:
        return jsonify({"error": error}), 400

    try:
        result =predict.generate_forecast(**cleaned)
    except Exception:
        app.logger.exception("Forecast generation failed")
        return jsonify({
            "error" : "something went wrong while generating the forecast. Please try again"
        }), 500

    return jsonify(result)

if __name__ == "__main__":
    predict.warm_up()
    app.run(debug=True, use_reloader=False)