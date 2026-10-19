from flask import Flask, render_template, request, jsonify
import predict 

app = Flask(__name__)

@app.route("/")
def index():
    return render_template("index.html")



def validate_inputs(data):
    """Return (cleaned_inputs, None) if valid, else (None, error_message) if not"""

    if not isinstance(data, dict):
        return None, "Request body must be valid JSON"

    period = data.get("forecast_period_days")
    if period not in [7, 14, 30]:
        return None, "forecast_period_days must be 7, 14, or 30"

    for name in ("promo", "promo2", "school_holiday"):
        if data.get(name) not in (0,1):
            return None, f"{name} must be 0 or 1"

    label = data.get("state_holiday_label")
    if not isinstance(label, str) or label not in predict.STATE_HOLIDAY_OPTIONS:
        options = ", ".join(predict.STATE_HOLIDAY_OPTIONS)
        return None, f"state_holiday_label must be one of: {options}."

    distance = data.get("competition_distance")
    if isinstance(distance, bool) or not isinstance(distance, (int, float)) or distance<0:
        return None, "competition_distance must be a number that is 0 or more"

    cleaned = {
        "forecast_period_days": int(period),
        "promo": int(data["promo"]),
        "promo2": int(data["promo2"]),
        "state_holiday_label": label,
        "school_holiday": int(data["school_holiday"]),
        "competition_distance": float(distance)
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


