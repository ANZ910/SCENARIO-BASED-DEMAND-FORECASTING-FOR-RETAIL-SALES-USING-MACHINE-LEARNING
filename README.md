# Scenario-Based Demand Forecasting for Retail Sales
 
A Flask dashboard that forecasts daily retail sales under user-defined scenarios (promotions, holidays, competition distance) and compares them against a baseline of normal trading conditions. Built on the Rossmann Store Sales dataset as a Final Year Project.
 
## Features
 
- Forecast horizons of 7, 14, or 30 days
- Scenario inputs: Promo, continuous campaign (Promo2), state holiday, school holiday, and competition distance
- Scenario vs baseline comparison for every forecast
- Summary cards: total predicted sales, average daily sales, peak day, and change vs baseline
- Interactive Plotly charts: daily forecast line chart and a total-sales comparison bar chart
- Key insights panel with plain-language conclusions generated from the forecast numbers (no external API)
## How it works
 
1. **`Experiments.ipynb`** handles all data preprocessing, feature engineering, and model comparison. It outputs the cleaned dataset (`cleaned_rossmann.json`) and the label-encoder mappings (`encoder_mappings.json`).
2. **`predict.py`** is self-contained. It loads those two files, trains an XGBoost model on first run (cached afterwards in `_trained_model_cache.pkl`), and generates recursive multi-day forecasts. Each day's lag and rolling-mean features are updated using the model's own previous predictions.
3. **`app.py`** exposes the Flask routes: `/` serves the dashboard and `/forecast` accepts the scenario as JSON and returns the scenario series, baseline series, and summary.
4. **`templates/index.html`**, **`static/style.css`**, and **`static/script.js`** make up the front end.
The baseline track always uses normal conditions (no promo, no holiday) with the same competition distance as the scenario.
 
## Model comparison
 
Evaluated on a time-ordered 80/20 split (no shuffling):
 
| Model         | MAE     | RMSE    | MAPE (%) |
|---------------|---------|---------|----------|
| LightGBM      | 645.56  | 955.92  | 10.31    |
| **XGBoost**   | 637.16  | 954.37  | 10.24    |
| Random Forest | 727.42  | 1054.31 | 11.77    |
| LSTM          | 2191.59 | 2922.81 | 38.53    |
 
XGBoost was selected for deployment.
 
## Setup
 
**Requirements:** Python 3.10+
 
```bash
# 1. Clone the repo
git clone <your-repo-url>
cd <your-repo-folder>
 
# 2. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
 
# 3. Install dependencies
pip install -r requirements.txt
```
 
### Data files
 
The large data files are not stored in this repository.
 
1. Download the Rossmann Store Sales data from Kaggle and combine the store and sales tables into `rossmann_store_sales.json`, the file loaded by the first cells of `Experiments.ipynb`.
2. Run `Experiments.ipynb` from top to bottom. It produces `cleaned_rossmann.json`.
3. Make sure `encoder_mappings.json` (`{column: {original_value: encoded_int}}` for `StateHoliday`, `StoreType`, `Assortment`, and `PromoInterval`) is in the same folder as `predict.py`.
Both `cleaned_rossmann.json` and `encoder_mappings.json` must sit next to `predict.py`.
 
## Running the app
 
```bash
python app.py
```
 
Open `http://127.0.0.1:5000` in your browser.
 
On the first run the model trains on the full dataset, which takes a few minutes. The trained model is then cached, so later starts are near-instant. The cache is rebuilt automatically if `cleaned_rossmann.json` changes.
 
## API
 
**`POST /forecast`**
 
```json
{
  "forecast_period_days": 14,
  "promo": 1,
  "promo2": 0,
  "state_holiday_label": "None",
  "school_holiday": 0,
  "competition_distance": 2300
}
```
 
- `forecast_period_days`: 7, 14, or 30
- `promo`, `promo2`, `school_holiday`: 0 or 1
- `state_holiday_label`: `None`, `Public Holiday`, `Easter`, or `Christmas`
- `competition_distance`: metres, 0 or more
Returns `scenario` and `baseline` (lists of `{date, predicted_sales}`) plus a `summary` object. Invalid input returns a 400 with an error message.
 
## Limitations
 
- **Store-agnostic.** The model is trained without Store ID, so forecasts are generalised across stores rather than specific to one location.
- **Fixed store attributes.** Store type, assortment, and promo interval use fixed defaults because the dashboard has no inputs for them.
- **Approximated durations.** Promo2 and competition duration use typical values from the training data, since the dashboard has no "since" dates.
- **Seeded lag features.** The first day's lag and rolling features come from all-time averages, not a specific store's recent history.
- **Recursive forecasting.** Later days depend on earlier predictions, so uncertainty grows over longer horizons.
- **Sunday forecasts.** Few stores open on Sundays in the training data, so Sunday predictions are the least reliable.
## Tech stack
 
Python, Flask, XGBoost, pandas, NumPy, scikit-learn, LightGBM, TensorFlow/Keras (for the LSTM experiment), Plotly.js
 
