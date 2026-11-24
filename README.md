## Suggested reading order
 
1. This README
2. `ExperimentsNew.ipynb` - the full data pipeline and model comparison, with outputs
3. `build_data.py` - rebuilds the same pipeline but keeps `Store` and `Date`
4. `predict.py` - the forecasting engine
5. `app.py` - the Flask routes and input validation
6. `backtest_evaluation.py` - the accuracy evidence
7. `templates/index.html`, `static/script.js`, `static/style.css` - the dashboard
## System overview
 
```
Rossmann data (raw)
        |
        +--> ExperimentsNew.ipynb -- cleaning, encoding, feature engineering,
        |         |                   model comparison (FYP1)
        |         +--> cleaned_rossmann.json    (model-ready, no Store/Date)
        |         +--> encoder_mappings.json    (label-encoder lookups)
        |
        +--> build_data.py -------- same cleaning and features, Store and Date kept
                  |
                  +--> training_frame.pkl      (model-ready table WITH dates)
                  +--> history.json            (every store's real daily sales)
                  |
                  v
          predict.py  -- trains/loads XGBoost, builds features, recursive forecasting
                  |
                  +--> app.py (Flask) -- /forecast and /stores, input validation
                  |          |
                  |          v
                  |   Browser dashboard -- scenario inputs, summary cards,
                  |                        history+forecast chart, accuracy cards
                  |
                  +--> backtest_evaluation.py -- scores the dashboard's own
                                                 forecast path on unseen days
                                                 --> backtest_results.csv
```
 
The notebook and `build_data.py` own all preprocessing. `predict.py` only consumes their output files; it never touches the raw data or refits the encoders, so the training and deployment pipelines cannot drift apart. `build_data.py` checks its rebuilt label encodings against the notebook's `encoder_mappings.json` and warns if they differ.
 
## Data and preprocessing pipeline
 
All steps below are implemented in `ExperimentsNew.ipynb`, in this order, and repeated in `build_data.py`.
 
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
 
The result is **21 model features**, saved as `cleaned_rossmann.json`. `build_data.py` keeps `Store` and `Date` alongside the same 21 features and saves `training_frame.pkl`, which is what the dashboard trains on.
 
## Evaluation
 
The system is evaluated in two different ways, because they answer two different questions. Both are reported, and neither is a substitute for the other.
 
### A. Model comparison — generalisation to unseen stores
 
Four models were trained on the same 21 features. The frame is sorted by store and then date, and split 80/20 by row position without shuffling. Because the sort key is `Store` first, this puts **whole stores** on either side of the split: the test set is the last ~20% of store IDs in that ordering, each with its full date range. So this measures how well a model generalises to stores it has never seen, not how well it predicts the future.
 
| Model         | MAE     | RMSE    | MAPE (%) |
|---------------|---------|---------|----------|
| LightGBM      | 645.56  | 955.92  | 10.31    |
| **XGBoost**   | 637.16  | 954.37  | 10.24    |
| Random Forest | 727.42  | 1054.31 | 11.77    |
| LSTM          | 2191.59 | 2922.81 | 38.53    |
 
XGBoost (2000 trees, learning rate 0.05, max depth 10) gave the lowest error and was selected for deployment.
 
Two caveats on this table. First, every row is a single-step prediction made from *real* past sales, so it is an easier task than the multi-day forecast the dashboard actually performs. Second, the **LSTM was run with one timestep per sample** (`X.reshape(n, 1, features)`), so it never saw a sequence. It is included as a non-sequential neural baseline, and its score should not be read as evidence about recurrent models on this problem in general.
 
### B. End-to-end backtest — the number a user actually gets
 
`predict.py` sets `TRAIN_CUTOFF = "2015-06-18"`, so the model learns only from days up to that date and the last six weeks of data stay hidden. `backtest_evaluation.py` then calls `generate_forecast` — the same function the dashboard calls — with real store history and the real promo, holiday and closed-day calendar (`replay_actual=True`), over rolling windows that start entirely after the cutoff. Each day's prediction feeds the next day's lag features, so compounding error is included. Results are compared against a seasonal-naive forecast that repeats the last observed week.
 
60 random stores, 780 windows, all after 2015-06-18:
 
| Horizon | Windows | Model MAPE | Naive MAPE | Model MAE | Naive MAE | Total-sales error |
|---------|---------|-----------|-----------|-----------|-----------|------------------|
| 7 days  | 360     | **9.27%** | 32.07%    | 632       | 2243      | 4.60%            |
| 14 days | 300     | **9.57%** | 22.28%    | 661       | 1549      | 4.11%            |
| 30 days | 120     | **10.02%** | 21.13%   | 689       | 1506      | 2.95%            |
 
Overall: **9.50% MAPE against 26.62%** for the naive baseline.
 
By store type (all horizons):
 
| Store type | Windows | Model MAPE | Naive MAPE |
|------------|---------|-----------|-----------|
| A | 403 | 9.54% | 25.84% |
| B | 13  | 5.00% | 11.07% |
| C | 130 | 8.92% | 26.19% |
| D | 234 | 9.99% | 29.07% |
 
Two things stand out. Recursive error grows only slightly with horizon (9.27% to 10.02% from 7 to 30 days), which suggests the calendar and store-profile features carry most of the signal rather than the recursive lag chain. And total-sales error falls as the horizon lengthens (4.60% to 2.95%), because daily over- and under-shoots cancel out over a longer period — useful if the number you care about is a monthly total rather than any single day.
 
Full per-window results are committed in `backtest_results.csv`.
 
To reproduce:
 
```bash
python backtest_evaluation.py --stores 60 --seed 42
```
 
## How the forecasting works
 
1. The user picks a **forecast period** (7, 14, or 30 days) and a **start date**.
2. They either pick a **real store** from the list, type their **own recent average sales** (last 7 days and/or last 30 days), or use the generic store.
3. They set the scenario: the exact **dates** a promotion runs, a state holiday falls, or a school holiday falls, plus the continuous campaign flag, store type, and competition distance.
4. For each day, `predict.py` builds the full 21-feature vector from the scenario and the calendar date.
5. Lag and rolling features use **recursive forecasting**: the first day is seeded from the last 30 trading days of real history (or from the typed averages, or from a chain-wide average in generic mode), and each later day uses the model's own previous predictions.
6. Days the store is closed are returned as zero without calling the model. By default this is Sundays for store types A, C and D; type B trades on Sundays.
7. The same process runs a second time for a **baseline** of normal conditions (no promo, no campaign, no holiday), keeping the same store and competition distance.
8. With a real store and a window inside the data, the dashboard also returns the real sales for those days, a seasonal-naive forecast, and accuracy metrics, so the user can see how close the forecast came.
### Seeding
 
| Mode | Seed for the 30-day lag window |
|------|-------------------------------|
| Store chosen | That store's last 30 open-day sales before the start date |
| Averages typed | Newest 7 slots from the 7-day average; older 23 solved so the 30-day mean matches the 30-day average |
| Generic store | `SEED_SALES = 6950.0` (all-time chain average) in all 30 slots |
 
## Features
 
- Forecast horizons of 7, 14, or 30 days, from any start date
- Store picker over all 1,115 stores, with each store's real type, assortment, competition distance and Promo2 status applied automatically
- Or type your own recent average daily sales instead of picking a store
- Per-date scenario inputs: mark the exact days a promotion, state holiday or school holiday falls on
- Continuous campaign (Promo2), store type, and a competition-distance slider
- Scenario vs baseline comparison
- Summary cards: total predicted sales, average daily sales on open days, peak day, change vs baseline
- Combined history-and-forecast chart: up to 90 days of real sales with the forecast branching off it
- Accuracy panel when replaying a past window: model MAPE, naive MAPE, MAE, and total sales error
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
pip install flask pandas numpy scikit-learn xgboost lightgbm plotly
# TensorFlow is only needed to re-run the LSTM cells in the notebook:
# pip install tensorflow
```
 
### Data files
 
The large data files are tracked with Git LFS or not stored here at all, so a plain clone will not give you working data.
 
1. Download the Rossmann Store Sales data from Kaggle and combine the store and sales tables into `rossmann_store_sales.json`, the file loaded by the first cells of `ExperimentsNew.ipynb`.
2. Run `ExperimentsNew.ipynb` from top to bottom. It produces `cleaned_rossmann.json` and `encoder_mappings.json`.
3. Run `python build_data.py rossmann_store_sales.json` once. It produces `training_frame.pkl` and `history.json`, and verifies its label encodings against `encoder_mappings.json`.
`training_frame.pkl`, `history.json` and `encoder_mappings.json` must all sit next to `predict.py`. `training_frame.pkl` is gitignored, so step 3 is required on every fresh clone.
 
## Running the app
 
```bash
python app.py
```
 
Open `http://127.0.0.1:5000` in your browser.
 
On the first run the model trains on all days up to `TRAIN_CUTOFF`, which takes a few minutes. The trained model is then cached in `_trained_model_cache.pkl`, so later starts are near-instant. The cache is rebuilt automatically if the training data or the model settings change.
 
> For real forecasting rather than backtesting, set `TRAIN_CUTOFF = None` in `predict.py` to train on all available data. The backtest then has no fully out-of-sample window, so the two cannot be done at once.
 
## API
 
### `GET /stores`
 
Everything the store picker needs.
 
```json
{
  "stores": [{ "id": 1, "store_type": "c", "promo2": 0, "...": "..." }],
  "first_date": "2013-01-01",
  "last_date": "2015-07-31",
  "train_cutoff": "2015-06-18"
}
```
 
### `POST /forecast`
 
```json
{
  "forecast_period_days": 14,
  "start_date": "2015-06-19",
  "store_id": 819,
  "promo_dates": ["2015-06-22", "2015-06-23"],
  "promo2": 0,
  "state_holiday_label": "None",
  "state_holiday_dates": [],
  "school_holiday_dates": [],
  "competition_distance": 2300,
  "store_type": "a",
  "replay_actual": false
}
```
 
| Field | Notes |
|-------|-------|
| `forecast_period_days` | 7, 14, or 30. Required. |
| `start_date` | `YYYY-MM-DD`, year 2000-2100. Optional; defaults to tomorrow. Required if `store_id` or any date list is given. |
| `store_id` | Store number from `/stores`. Optional. Uses that store's real history and store facts. |
| `recent_avg_7`, `recent_avg_30` | Your own average daily sales. Optional, and mutually exclusive with `store_id`. |
| `promo_dates` | Dates the promotion runs. Must fall inside the forecast window. |
| `promo2` | 0 or 1. Required. |
| `state_holiday_label` | `None`, `Public Holiday`, `Easter`, or `Christmas`. Required. Must not be `None` if `state_holiday_dates` is non-empty. |
| `state_holiday_dates`, `school_holiday_dates` | Same rules as `promo_dates`. |
| `competition_distance` | Metres, 0 or more. Required only when no `store_id` is given. |
| `store_type` | `a`, `b`, `c`, or `d`. Required only when no `store_id` is given. |
| `replay_actual` | `true` forecasts under the real promo/holiday/closed calendar for that window, so the result can be scored. Needs a `store_id` and a window inside the data. |
 
Response:
 
| Key | Contents |
|-----|----------|
| `scenario`, `baseline` | Lists of `{date, predicted_sales, closed}` |
| `summary` | Total and average predicted sales, open days, peak day |
| `history` | Up to 90 days of real sales before the start date (store mode only) |
| `actual` | Real sales inside the forecast window, `null` per closed day |
| `metrics` | `mape`, `mae`, `rmse`, `total_error_pct`, `naive_mape`, `naive_mae` (replay mode only) |
| `store` | The chosen store's type, assortment, competition distance, Promo2, Sunday closure |
| `seed_source` | Which seeding mode was used, for display |
| `replay_used`, `train_cutoff`, `overlaps_training` | Flags so the dashboard can warn when a window overlaps training data |
 
Invalid input returns `400` with an `error` message. An unexpected failure returns `500`.
 
## Limitations
 
- **Generic mode is weakly grounded.** With no store and no typed averages, all 30 lag slots are seeded from a single chain-wide average (`SEED_SALES`). The shape of the forecast still responds to the scenario and the calendar, but the level is generic. Picking a store or typing recent averages is strongly preferred.
- **No product-level forecasting.** The Rossmann dataset records total daily sales per store with no SKU or category breakdown, so the system forecasts store-level demand only. Per-product forecasting would require a different dataset.
- **The model is store-agnostic.** `Store` is dropped as a feature. A chosen store influences the forecast through its history, type, assortment, competition distance and Promo2 status, not through a learned store identity.
- **Closed days are rule-based.** Outside replay mode, closures are inferred from store type and weekday, not from a real calendar, so public-holiday closures are not modelled.
- **The LSTM baseline is non-sequential.** See the caveats under Evaluation A.
- **Scenario inputs are not validated against reality.** Nothing stops a user marking a promotion on every day of a 30-day window, which is well outside anything in the training data.
## Tech stack
 
Python, Flask, XGBoost, pandas, NumPy, scikit-learn, LightGBM, TensorFlow/Keras (for the LSTM experiment), Plotly.js
