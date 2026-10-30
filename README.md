# Scenario-Based Demand Forecasting for Retail Sales
 
A machine learning system that forecasts daily retail sales under user-defined "what-if" scenarios (promotions, holidays, competition distance) and compares them against a baseline of normal trading conditions. It is delivered as a Flask web dashboard built on the Rossmann Store Sales dataset.
 
## Summary
 
**Problem.** Retail managers need to know how promotions, holidays, and competition are likely to affect sales before they commit to a plan. A plain sales forecast cannot answer "what happens if I run a promotion next week?"
 
**Solution.** A gradient-boosted model (XGBoost) trained on over one million daily store records, wrapped in a dashboard where the user sets a scenario and receives a day-by-day forecast, a baseline for comparison, and plain-language insights.
 
**Result.** XGBoost achieved the lowest error of the four models compared (MAE 637, RMSE 954, MAPE 10.24% on the held-out test set) and is the model used by the dashboard.
 
<!-- Add screenshots here once saved to the repo, for example:
![Dashboard](docs/dashboard.png)
-->
 
## Project context
 
This repository covers both parts of the Final Year Project.
 
| Part | Focus | Output |
|------|-------|--------|
| **FYP1** | Data preprocessing, feature engineering, and comparison of four models (XGBoost, LightGBM, Random Forest, LSTM) | `Experiments.ipynb`, model comparison, XGBoost selected |
| **FYP2** | Turning the selected model into a working scenario-based forecasting system | `predict.py`, Flask app, dashboard |
 
## Suggested reading order
 
1. This README
2. `Experiments.ipynb` - the full data pipeline and model comparison, with outputs
3. `predict.py` - the forecasting engine
4. `app.py` - the Flask routes and input validation
5. `templates/index.html`, `static/script.js`, `static/style.css` - the dashboard
## System overview
 
```
Rossmann data (raw)
        |
        v
Experiments.ipynb  --- cleaning, encoding, feature engineering, model comparison
        |
        +--> cleaned_rossmann.json     (model-ready dataset)
        +--> encoder_mappings.json     (label-encoder lookups)
        |
        v
predict.py  --- trains/loads XGBoost, builds features, recursive forecasting
        |
        v
app.py (Flask)  --- /forecast endpoint, input validation
        |
        v
Browser dashboard  --- scenario inputs, summary cards, charts, insights
```
 
The notebook owns all preprocessing; `predict.py` only consumes its output files. It never touches the raw data or refits the encoders, so the training and deployment pipelines cannot drift apart.
 
## Data and preprocessing pipeline
 
All steps below are implemented in `Experiments.ipynb`, in this order.
 
### 1. Dataset
 
The Rossmann Store Sales dataset (1,115 German stores) with sales records merged with store information: **1,017,209 rows and 18 columns**. Key fields include daily sales, customer counts, promotion flags, holiday flags, store type and assortment, competition details, and continuous-promotion (Promo2) details.
 
### 2. Inspection
 
The structure, data types, and missing values were checked first. Only the competition and Promo2 fields had gaps:
 
| Column | Missing values |
|--------|----------------|
| `CompetitionDistance` | 2,642 |
| `CompetitionOpenSinceMonth` / `CompetitionOpenSinceYear` | 323,348 each |
| `Promo2SinceWeek` / `Promo2SinceYear` / `PromoInterval` | 508,031 each |
 
### 3. Removing closed-store days
 
Rows where the store was closed (`Open == 0`) were removed. A closed store always has zero sales, which says nothing about demand and would distort the model.
 
### 4. Handling missing values
 
| Column | Treatment | Reason |
|--------|-----------|--------|
| `CompetitionDistance` | Filled with the median | Robust to the long right tail of distances |
| `CompetitionOpenSinceMonth` / `Year` | Filled with 0 | No recorded competitor opening |
| `Promo2SinceWeek` / `Year` | Filled with 0 | Store not in the continuous promotion |
| `PromoInterval` | Filled with `"None"` | Store not in the continuous promotion |
 
The filled columns were then converted from float to integer, and `Date` was converted to a proper datetime type. A duplicate check found no duplicate rows.
 
### 5. Outlier analysis
 
Sales were examined with a boxplot and histogram, and the IQR rule flagged 30,769 high-sales rows. These were **examined but retained**, because unusually high sales days (promotions, pre-holiday peaks) are real demand patterns the forecaster needs to learn. `CompetitionDistance` was also very right-skewed, which was handled with a log transform (step 8).
 
### 6. Encoding categorical variables
 
`StateHoliday`, `StoreType`, `Assortment`, and `PromoInterval` were label-encoded. Each fitted encoder is kept in a dictionary and its mapping is exported to `encoder_mappings.json`, so the dashboard encodes inputs exactly as the training data was encoded. Rows with zero sales were then removed and any remaining null rows dropped.
 
### 7. Feature engineering
 
The data was sorted by store and date, and the following features were created:
 
| Feature | How it is built | Why |
|---------|-----------------|-----|
| `Year`, `Month`, `Day`, `WeekOfYear` | Extracted from `Date` | Captures seasonality and calendar effects |
| `Sales_Lag_7`, `_14`, `_30` | Sales 7, 14, and 30 records earlier, **grouped by store** | Recent sales history. Grouping prevents one store's data leaking into the next |
| `RollingMean_7`, `_30` | Rolling average of previous sales, shifted by one record and grouped by store | Recent sales trend. The shift stops same-day sales leaking into the feature |
| `CompetitionOpenDuration` | Months since the competitor opened (0 if no competitor), clipped at 0 | Turns two date columns into one meaningful quantity |
| `PromoDuration` | Weeks since Promo2 started (0 if not enrolled), clipped at 0 | Same idea for the continuous promotion |
| `CompetitionDistance_Log` | `log(1 + distance)` | Reduces skew and the influence of extreme distances |
 
The first records of each store have no lag history, so their lag and rolling features are missing. These are left as missing values, which XGBoost handles natively.
 
### 8. Dropping columns
 
| Dropped | Reason |
|---------|--------|
| `Store` | The deployed model is store-agnostic |
| `Customers` | Not known at prediction time, and would leak the answer |
| `Date` | Replaced by the extracted date features |
| `CompetitionDistance` | Replaced by the log version |
| `CompetitionOpenSinceMonth` / `Year`, `Promo2SinceWeek` / `Year` | Replaced by the duration features |
 
The result is **21 model features**, saved as `cleaned_rossmann.json`.
 
## Model comparison
 
Four models were trained on the same features. The data is sorted by store and date and split 80/20 by position, without shuffling, so the test set is the last ~20% of stores in that ordering.
 
| Model         | MAE     | RMSE    | MAPE (%) |
|---------------|---------|---------|----------|
| LightGBM      | 645.56  | 955.92  | 10.31    |
| **XGBoost**   | 637.16  | 954.37  | 10.24    |
| Random Forest | 727.42  | 1054.31 | 11.77    |
| LSTM          | 2191.59 | 2922.81 | 38.53    |
 
XGBoost (2000 trees, learning rate 0.05, max depth 10) gave the lowest error and was selected for deployment. The tree-based models clearly outperform the LSTM here. The LSTM was run as a baseline with a single timestep per sample, so it did not learn multi-step sequences.
 
## How the forecasting works
 
1. The user chooses a forecast period (7, 14, or 30 days) and a scenario: promo, continuous campaign, state holiday, school holiday, and competition distance.
2. For each day, `predict.py` builds the full 21-feature vector from the scenario and the calendar date.
3. Lag and rolling features use **recursive forecasting**: day 1 is seeded from all-time average sales, and each later day uses the model's own previous predictions.
4. The same process runs a second time for a **baseline** of normal conditions (no promo, no holiday), keeping the same competition distance.
5. The dashboard shows both series, the totals, the change vs baseline, and rule-based insights such as the peak day and weakest day.
## Features
 
- Forecast horizons of 7, 14, or 30 days
- Scenario inputs for promo, continuous campaign, state holiday, school holiday, and competition distance
- Scenario vs baseline comparison
- Summary cards: total predicted sales, average daily sales, peak day, change vs baseline
- Interactive Plotly charts
- Key insights panel generated from the forecast numbers (no external API)
## Setup
 
**Requirements:** Python 3.10+
 
```bash
# 1. Clone the repo
git clone https://github.com/ANZ910/SCENARIO-BASED-DEMAND-FORECASTING-FOR-RETAIL-SALES-USING-MACHINE-LEARNING.git
cd SCENARIO-BASED-DEMAND-FORECASTING-FOR-RETAIL-SALES-USING-MACHINE-LEARNING
 
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
3. Make sure `encoder_mappings.json` is in the same folder as `predict.py`.
Both `cleaned_rossmann.json` and `encoder_mappings.json` must sit next to `predict.py`.
 
## Running the app
 
```bash
python app.py
```
 
Open `http://127.0.0.1:5000` in your browser.
 
On the first run the model trains on the full dataset, which takes a few minutes. The trained model is then cached in `_trained_model_cache.pkl`, so later starts are near-instant. The cache is rebuilt automatically if `cleaned_rossmann.json` changes.
 
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
 
## Tech stack
 
Python, Flask, XGBoost, pandas, NumPy, scikit-learn, LightGBM, TensorFlow/Keras (for the LSTM experiment), Plotly.js
 
