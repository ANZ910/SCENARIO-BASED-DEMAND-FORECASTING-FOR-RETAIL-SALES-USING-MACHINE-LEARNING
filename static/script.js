// Front-end logic for the Demand Forecasting Dashboard.
// Reads the scenario inputs, sends them to Flask (/forecast),
// then draws the charts and fills in the summary cards.

// Colours used by the charts
const SCENARIO_COLOR = "#2e27b7";
const BASELINE_COLOR = "#42474d";
const ACTUAL_COLOR   = "#111827";

// Grab the elements we need (by the ids in index.html)
const periodSelect   = document.getElementById("forecast-period");
const startDateInput = document.getElementById("start-date");
const promoBox       = document.getElementById("promo");
const promo2Box      = document.getElementById("promo2");
const holidaySelect  = document.getElementById("state-holiday");
const storeTypeSelect = document.getElementById("store-type");
const schoolBox      = document.getElementById("school-holiday");
const distanceSlider = document.getElementById("competition-distance");
const distanceValue  = document.getElementById("distance-value");
const button         = document.getElementById("forecast-button");
const errorMessage   = document.getElementById("error-message");
const promoDaysBlock = document.getElementById("promo-days");
const calendarEl     = document.getElementById("promo-calendar");
const promoCountEl   = document.getElementById("promo-count");

// Sales history inputs
const storeSelect    = document.getElementById("store-select");
const storeInfoEl    = document.getElementById("store-info");
const replayBox      = document.getElementById("replay");
const replayRow      = document.getElementById("replay-row");
const averageField   = document.getElementById("average-field");
const avg7Input      = document.getElementById("avg-7");
const avg30Input     = document.getElementById("avg-30");

// Show the slider's current number as the user drags it
distanceSlider.addEventListener("input", () => {
  distanceValue.textContent = distanceSlider.value;
});


// ---------- Sales history state ----------

let storeList = [];            // from /stores
let dataRange = null;          // { first, last, trainCutoff } from /stores
let currentStore = null;       // the chosen store object, or null (generic)

// Almost every store is closed on Sundays; only Type B trades. A chosen store
// uses its own record, otherwise the Store Type dropdown decides.
function closedOnSunday() {
  if (currentStore) return currentStore.closed_on_sunday;
  return storeTypeSelect.value !== "b";
}

// Replay mode: the real promos, holidays and closed days of the chosen period
// are used, so these manual controls are ignored and greyed out.
function replayActive() {
  return currentStore !== null && replayBox.checked;
}

function setLocked(el, locked) {
  const target = el.closest(".field, .toggle-row") || el;
  target.classList.toggle("locked", locked);
  el.disabled = locked;
}

function refreshLocks() {
  const replay = replayActive();
  setLocked(promoBox, replay);
  setLocked(holidaySelect, replay);
  setLocked(schoolBox, replay);
  setLocked(storeTypeSelect, currentStore !== null);
  setLocked(distanceSlider, currentStore !== null);
  promoDaysBlock.hidden = replay || !promoBox.checked;
}


// ---------- Promo days calendar ----------

const WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// The dates (as "YYYY-MM-DD") the user has ticked for promo
const selectedPromoDates = new Set();

// Date -> "YYYY-MM-DD" using local date parts (toISOString would shift the day by time zone)
function toISO(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

// "YYYY-MM-DD" -> Date at local midnight
function parseISO(text) {
  const [y, m, d] = text.split("-").map(Number);
  return new Date(y, m - 1, d);
}

// Monday = 0 ... Sunday = 6
function weekdayIndex(date) {
  return (date.getDay() + 6) % 7;
}

// Tomorrow in the user's own time zone
function setDefaultStartDate() {
  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  startDateInput.value = toISO(tomorrow);
}

// Every real date in the forecast window ([] if the start date is empty or invalid)
function getForecastDates() {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(startDateInput.value)) return [];
  const start = parseISO(startDateInput.value);
  if (isNaN(start)) return [];

  const days = Number(periodSelect.value);
  const dates = [];
  for (let i = 0; i < days; i++) {
    dates.push(new Date(start.getFullYear(), start.getMonth(), start.getDate() + i));
  }
  return dates;
}

// Closed days (Sundays for most stores): promo has no effect there
function isClosed(date) {
  return closedOnSunday() && weekdayIndex(date) === 6;
}

// How many open days there are, and how many of them have promo
function promoStats() {
  const dates = getForecastDates();
  const openDates = dates.filter(d => !isClosed(d));
  const picked = openDates.filter(d => selectedPromoDates.has(toISO(d))).length;
  return { total: dates.length, open: openDates.length, picked: picked };
}

function updatePromoCount() {
  const stats = promoStats();
  if (stats.total === 0) {
    promoCountEl.textContent = "Choose a start date to pick promo days.";
    return;
  }
  let text = `${stats.picked} of ${stats.open} open days with promo`;
  if (stats.open < stats.total) {
    text += " (closed on Sundays)";
  }
  promoCountEl.textContent = text;
}

// Drop ticked dates that are no longer inside the forecast window
function pruneSelection() {
  const valid = new Set(getForecastDates().map(toISO));
  [...selectedPromoDates].forEach(iso => {
    if (!valid.has(iso)) selectedPromoDates.delete(iso);
  });
}

// Draw the calendar: Mon-Sun header, blank cells before the first date, then one button per date
function renderCalendar() {
  calendarEl.replaceChildren();

  const dates = getForecastDates();
  if (dates.length > 0) {
    WEEKDAY_NAMES.forEach(name => {
      const head = document.createElement("div");
      head.className = "calendar-head";
      head.textContent = name;
      calendarEl.appendChild(head);
    });

    for (let i = 0; i < weekdayIndex(dates[0]); i++) {
      calendarEl.appendChild(document.createElement("div"));
    }

    dates.forEach((date, i) => {
      const iso = toISO(date);
      const cell = document.createElement("button");
      cell.type = "button";
      cell.className = "day-cell";
      cell.dataset.date = iso;

      const num = document.createElement("span");
      num.className = "day-num";
      num.textContent = date.getDate();
      cell.appendChild(num);

      // Show the month on the first cell and on the 1st of each month
      if (i === 0 || date.getDate() === 1) {
        const month = document.createElement("span");
        month.className = "day-month";
        month.textContent = MONTH_NAMES[date.getMonth()];
        cell.appendChild(month);
      }

      if (isClosed(date)) {
        cell.classList.add("closed");
        cell.setAttribute("aria-disabled", "true");
        cell.title = "Closed on Sundays";
      } else {
        const on = selectedPromoDates.has(iso);
        cell.classList.toggle("selected", on);
        cell.setAttribute("aria-pressed", String(on));
      }

      calendarEl.appendChild(cell);
    });
  }

  updatePromoCount();
}

// Tick or untick one date (only that cell is updated, so keyboard focus stays on it)
calendarEl.addEventListener("click", event => {
  const cell = event.target.closest(".day-cell");
  if (!cell || cell.classList.contains("closed")) return;

  const iso = cell.dataset.date;
  const on = !selectedPromoDates.has(iso);
  if (on) selectedPromoDates.add(iso); else selectedPromoDates.delete(iso);

  cell.classList.toggle("selected", on);
  cell.setAttribute("aria-pressed", String(on));
  updatePromoCount();
});

// Presets replace the current selection. Closed days are skipped.
function applyPreset(name) {
  selectedPromoDates.clear();

  if (name !== "clear") {
    getForecastDates().forEach((date, i) => {
      if (isClosed(date)) return;
      const weekday = weekdayIndex(date);
      const on =
        name === "every" ||
        (name === "weekdays" && weekday < 5) ||
        (name === "weekends" && weekday >= 5) ||
        (name === "first-week" && i < 7);
      if (on) selectedPromoDates.add(toISO(date));
    });
  }

  renderCalendar();
}

document.querySelectorAll("[data-preset]").forEach(btn => {
  btn.addEventListener("click", () => applyPreset(btn.dataset.preset));
});

// The calendar only shows while Promo is ON; start with Weekdays so it is never empty
promoBox.addEventListener("change", () => {
  promoDaysBlock.hidden = replayActive() || !promoBox.checked;
  if (promoBox.checked && selectedPromoDates.size === 0) {
    applyPreset("weekdays");
  }
});

// A new period or start date moves the window; a new store type changes which days are closed
function onWindowChange() {
  pruneSelection();
  renderCalendar();
}
// With a store and replay on, keep the window inside the data so it can be checked
periodSelect.addEventListener("change", () => {
  if (replayActive()) setBacktestStartDate();
  onWindowChange();
});
startDateInput.addEventListener("change", onWindowChange);
storeTypeSelect.addEventListener("change", renderCalendar);


// ---------- Store picker and sales upload ----------

function formatMetres(value) {
  return Math.round(value).toLocaleString("en-US");
}

// Latest start date whose whole window is still inside the data
function setBacktestStartDate() {
  if (!dataRange) return;
  const last = parseISO(dataRange.last);
  last.setDate(last.getDate() - (Number(periodSelect.value) - 1));
  startDateInput.value = toISO(last);
}

function chooseStore(storeId) {
  currentStore = storeList.find(s => s.id === storeId) || null;

  if (currentStore) {
    clearAverages();
    // Fill the controls with this store's real facts (they are locked below)
    storeTypeSelect.value = currentStore.store_type;
    distanceSlider.value = Math.min(currentStore.competition_distance, Number(distanceSlider.max));
    distanceValue.textContent = Math.round(currentStore.competition_distance);
    promo2Box.checked = currentStore.promo2 === 1;
    replayBox.checked = false;   // off by default so Promo and Holiday stay editable (what-if)
    setBacktestStartDate();

    const sunday = currentStore.closed_on_sunday ? "closed on Sundays" : "open on Sundays";
    storeInfoEl.textContent =
      `Store ${currentStore.id}: Type ${currentStore.store_type.toUpperCase()}, ` +
      `assortment ${currentStore.assortment}, nearest competitor ` +
      `${formatMetres(currentStore.competition_distance)} m, ` +
      `${currentStore.promo2 ? "runs a continuous campaign" : "no continuous campaign"}, ${sunday}. ` +
      `Sales data runs ${dataRange.first} to ${dataRange.last}.`;
    storeInfoEl.hidden = false;
  } else {
    storeInfoEl.hidden = true;
    replayBox.checked = false;
    setDefaultStartDate();
  }

  replayRow.hidden = currentStore === null;
  averageField.hidden = currentStore !== null;
  pruneSelection();
  refreshLocks();
  renderCalendar();
}

storeSelect.addEventListener("change", () => {
  chooseStore(storeSelect.value === "" ? null : Number(storeSelect.value));
});

replayBox.addEventListener("change", () => {
  if (replayBox.checked) setBacktestStartDate();
  refreshLocks();
  onWindowChange();
});

// Recent average sales typed by the user (blank or invalid = not used)
function readAverage(input) {
  const value = Number(input.value);
  return input.value.trim() !== "" && isFinite(value) && value > 0 ? value : null;
}

function clearAverages() {
  avg7Input.value = "";
  avg30Input.value = "";
}

async function loadStores() {
  try {
    const response = await fetch("/stores");
    if (!response.ok) throw new Error("no store list");
    const data = await response.json();
    storeList = data.stores;
    dataRange = { first: data.first_date, last: data.last_date, trainCutoff: data.train_cutoff };

    storeList.forEach(s => {
      const option = document.createElement("option");
      option.value = s.id;
      option.textContent = `Store ${s.id} (Type ${s.store_type.toUpperCase()})`;
      storeSelect.appendChild(option);
    });
  } catch (err) {
    // Without history.json the dashboard still works in generic mode
    storeSelect.disabled = true;
    storeSelect.options[0].textContent = "Store history not available (run build_data.py)";
  }
}


// ---------- Forecast request ----------

// Read every input and build the JSON that /forecast expects
function getInputs() {
  const replay = replayActive();
  const inputs = {
    forecast_period_days: Number(periodSelect.value),
    start_date: startDateInput.value,
    promo_dates: (promoBox.checked && !replay) ? [...selectedPromoDates].sort() : [],
    promo2: promo2Box.checked ? 1 : 0,
    state_holiday_label: replay ? "None" : holidaySelect.value,
    school_holiday: (schoolBox.checked && !replay) ? 1 : 0,
    competition_distance: Number(distanceSlider.value),
    store_type: storeTypeSelect.value,
    replay_actual: replay
  };
  if (currentStore) {
    inputs.store_id = currentStore.id;
  } else {
    const avg7 = readAverage(avg7Input);
    const avg30 = readAverage(avg30Input);
    if (avg7 !== null) inputs.recent_avg_7 = avg7;
    if (avg30 !== null) inputs.recent_avg_30 = avg30;
  }
  return inputs;
}

// Format numbers like 54,064.01
function formatNumber(value) {
  return Number(value).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  });
}

// Add up predicted_sales across a list of days
function sumSales(days) {
  return days.reduce((total, d) => total + d.predicted_sales, 0);
}

// Fill the three summary cards
function showSummary(summary) {
  document.getElementById("total-sales").textContent =
    formatNumber(summary.total_predicted_sales);
  document.getElementById("average-sales").textContent =
    formatNumber(summary.average_daily_sales);
  document.getElementById("peak-day").textContent =
    `${summary.peak_day} (${summary.peak_day_date})`;
}

// Chart 1: daily forecast, scenario vs baseline (line chart)
function drawDailyChart(result) {
  const dayLabels = result.scenario.map((d, i) => `Day ${i + 1}`);
  const dates     = result.scenario.map(d => d.date);

  const scenarioTrace = {
    x: dayLabels,
    y: result.scenario.map(d => d.predicted_sales),
    customdata: dates,
    name: "Scenario",
    type: "scatter",
    mode: "lines+markers",
    line: { color: SCENARIO_COLOR },
    fill: "tozeroy",
    fillcolor: "rgba(59, 130, 246, 0.08)",
    hovertemplate: "%{x} (%{customdata})<br>Sales: %{y:,.0f}<extra>Scenario</extra>"
  };

  const baselineTrace = {
    x: dayLabels,
    y: result.baseline.map(d => d.predicted_sales),
    customdata: dates,
    name: "Baseline",
    type: "scatter",
    mode: "lines+markers",
    line: { color: BASELINE_COLOR, dash: "dash" },
    hovertemplate: "%{x} (%{customdata})<br>Sales: %{y:,.0f}<extra>Baseline</extra>"
  };

  const n = result.scenario.length;
  const tickEvery = n > 14 ? 3 : 1;   // for 30 days, label every 3rd day
  const tickvals = dayLabels.filter((_, i) => i % tickEvery === 0);

  const layout = {
    margin: { t: 40, r: 10, b: 50, l: 60 },
    xaxis: {
      tickvals: tickvals,
      tickangle: n > 7 ? -45 : 0,     // tilt the labels once there are many
      automargin: true
    },
    yaxis: { title: "Predicted Sales", rangemode: "tozero" },
    legend: { orientation: "h", y: 1.12 }   // legend moved above the chart
  };

  Plotly.newPlot("forecast-chart", [scenarioTrace, baselineTrace], layout, { responsive: true });
}

// Chart 2: total sales, baseline vs scenario (bar chart)
function drawComparisonChart(result) {
  const baselineTotal = sumSales(result.baseline);
  const scenarioTotal = sumSales(result.scenario);

  const barTrace = {
    x: ["Baseline", "Scenario"],
    y: [baselineTotal, scenarioTotal],
    type: "bar",
    marker: { color: [BASELINE_COLOR, SCENARIO_COLOR] },
    text: [baselineTotal, scenarioTotal].map(v => v.toLocaleString("en-US", { maximumFractionDigits: 0 })),
    textposition: "outside",
    cliponaxis: false,
    hovertemplate: "%{x}<br>Total sales: %{y:,.0f}<extra></extra>"
  };

  const layout = {
    margin: { t: 40, r: 10, b: 40, l: 60 },
    yaxis: { title: "Total Predicted Sales", rangemode: "tozero" },
    showlegend: false
  };

  Plotly.newPlot("comparison-chart", [barTrace], layout, { responsive: true });
}


// ---------- Chart 3: past sales + forecast (and the accuracy check) ----------

const historyNote  = document.getElementById("history-note");
const accuracyBadge = document.getElementById("accuracy-badge");
const accuracyCards = document.getElementById("accuracy-cards");
const accuracyNote  = document.getElementById("accuracy-note");

// Past sales and the forecast on one date axis. The actual line runs through
// the history and (when the data has it) the forecast window; the predicted
// lines branch off at the last known sales day.
function drawHistoryChart(result) {
  // Show only a little history before the forecast, so the forecast itself fills
  // about 40% of the chart instead of being squashed (the server sends up to 90 days)
  const keepDays = Math.max(14, Math.round(result.scenario.length * 1.5));
  const history = (result.history || []).slice(-keepDays);
  const actual  = result.actual || [];
  const target  = document.getElementById("history-chart");

  const averages = result.averages;   // the user's own 7-day / 30-day averages, or null

  if (history.length === 0 && actual.length === 0 && !averages) {
    Plotly.purge(target);
    target.replaceChildren();
    historyNote.textContent = currentStore
      ? "There is no sales history before this start date, so there is nothing to plot."
      : "Choose a store, or type your recent average sales, to see past sales together with the forecast.";
    return;
  }

  const startDate = result.scenario[0].date;
  const endDate   = result.scenario[result.scenario.length - 1].date;

  // The date n days before the forecast starts
  function daysBeforeStart(n) {
    const d = parseISO(startDate);
    d.setDate(d.getDate() - n);
    return toISO(d);
  }

  // Actual sales: history then the forecast window (closed days = gap)
  const actualPoints = history.concat(actual.map(a => ({ date: a.date, sales: a.sales })));
  const actualTrace = {
    x: actualPoints.map(p => p.date),
    y: actualPoints.map(p => p.sales),
    name: "Actual sales",
    type: "scatter",
    mode: "lines",
    connectgaps: true,
    line: { color: ACTUAL_COLOR, width: 2 },
    hovertemplate: "%{x}<br>Actual: %{y:,.0f}<extra></extra>"
  };

  // The user's averages are drawn as flat lines over the days they describe
  const averageTraces = [];
  if (averages) {
    if (averages.avg_30 !== null) {
      averageTraces.push({
        x: [daysBeforeStart(30), daysBeforeStart(1)], y: [averages.avg_30, averages.avg_30],
        name: "Your 30-day average", type: "scatter", mode: "lines",
        line: { color: "#6b7280", width: 2 },
        hovertemplate: "30-day average: %{y:,.0f}<extra></extra>"
      });
    }
    if (averages.avg_7 !== null) {
      averageTraces.push({
        x: [daysBeforeStart(7), daysBeforeStart(1)], y: [averages.avg_7, averages.avg_7],
        name: "Your 7-day average", type: "scatter", mode: "lines",
        line: { color: ACTUAL_COLOR, width: 3 },
        hovertemplate: "7-day average: %{y:,.0f}<extra></extra>"
      });
    }
  }

  // The forecast starts where the history ends
  let lastKnown = [...history].reverse().find(p => p.sales !== null) || null;
  if (averages) {
    const level = averages.avg_7 !== null ? averages.avg_7 : averages.avg_30;
    lastKnown = { date: daysBeforeStart(1), sales: level };
  }

  // If the forecast starts long after the last day with data (history ends in
  // 2015 but the start date is in 2026, say), cut the empty stretch out of the
  // axis and label it, instead of drawing one long jump across the years.
  let gapDays = 0;
  if (lastKnown && !averages) {
    gapDays = Math.round((parseISO(startDate) - parseISO(lastKnown.date)) / 86400000);
  }
  const bigGap = gapDays > 30;

  // Otherwise the predicted lines start from the last known sales
  const joinX = lastKnown && !bigGap ? [lastKnown.date] : [];
  const joinY = lastKnown && !bigGap ? [lastKnown.sales] : [];

  const scenarioTrace = {
    x: joinX.concat(result.scenario.map(d => d.date)),
    y: joinY.concat(result.scenario.map(d => d.closed ? null : d.predicted_sales)),
    name: result.replay_used ? "Predicted sales" : "Predicted (your scenario)",
    type: "scatter",
    mode: "lines+markers",
    connectgaps: true,
    line: { color: SCENARIO_COLOR, width: 3.5 },
    marker: { size: 8 },
    hovertemplate: "%{x}<br>Predicted: %{y:,.0f}<extra></extra>"
  };

  const baselineTrace = {
    x: joinX.concat(result.baseline.map(d => d.date)),
    y: joinY.concat(result.baseline.map(d => d.closed ? null : d.predicted_sales)),
    name: "Baseline (no promo or holiday)",
    type: "scatter",
    mode: "lines",
    connectgaps: true,
    line: { color: "#9ca3af", width: 1.3, dash: "dash" },
    hovertemplate: "%{x}<br>Baseline: %{y:,.0f}<extra></extra>"
  };

  const xaxis = { type: "date", automargin: true };
  const gapNotes = [];
  if (bigGap) {
    const hideFrom = parseISO(lastKnown.date);
    hideFrom.setDate(hideFrom.getDate() + 1);
    xaxis.rangebreaks = [{ values: [toISO(hideFrom)], dvalue: (gapDays - 2) * 86400000 }];

    // Zoom to the history that is left plus the forecast (the cut stretch would
    // otherwise leave a large empty area on the right)
    const first = parseISO(actualPoints[0].date);
    first.setDate(first.getDate() - 1);
    const last = parseISO(endDate);
    last.setDate(last.getDate() + 1);
    xaxis.range = [toISO(first), toISO(last)];

    // Date labels for both sides of the break (automatic ticks would be placed
    // as if the cut stretch were still there, leaving the history unlabelled)
    const evenDates = (from, to, count) => {
      const a = parseISO(from);
      const span = Math.round((parseISO(to) - a) / 86400000);
      const out = [];
      for (let i = 0; i < count; i++) {
        out.push(toISO(new Date(a.getFullYear(), a.getMonth(), a.getDate() + Math.round(span * i / (count - 1)))));
      }
      return out;
    };
    xaxis.tickvals = evenDates(actualPoints[0].date, lastKnown.date, 4).concat(evenDates(startDate, endDate, 4));
    xaxis.tickformat = "%d %b %Y";

    gapNotes.push({
      x: startDate, xref: "x", y: 0.04, yref: "paper", xanchor: "right", yanchor: "bottom",
      showarrow: false, font: { size: 11, color: "#6b7280" },
      text: "gap: no data"
    });
  }

  const layout = {
    margin: { t: 30, r: 20, b: 50, l: 70 },
    xaxis: xaxis,
    yaxis: { title: "Daily sales", rangemode: "tozero" },
    legend: { orientation: "h", y: 1.15 },
    hovermode: "x unified",
    shapes: [
      // light band over the forecast window
      { type: "rect", xref: "x", yref: "paper", x0: startDate, x1: endDate, y0: 0, y1: 1,
        fillcolor: "rgba(79, 70, 229, 0.07)", line: { width: 0 }, layer: "below" },
      // dashed line where the forecast starts
      { type: "line", xref: "x", yref: "paper", x0: startDate, x1: startDate, y0: 0, y1: 1,
        line: { color: "#6b7280", width: 1, dash: "dot" } }
    ],
    annotations: [
      { x: startDate, xref: "x", y: 1, yref: "paper", text: "Forecast starts", showarrow: false,
        xanchor: "left", yanchor: "bottom", font: { size: 11, color: "#6b7280" } }
    ].concat(gapNotes)
  };

  historyNote.textContent = result.seed_source
    ? `Forecast seeded from: ${result.seed_source}.`
    : "";
  if (bigGap) {
    historyNote.textContent +=
      ` There is no sales data for ${gapDays.toLocaleString("en-US")} days between the last known day ` +
      `(${lastKnown.date}) and the forecast start (${startDate}); that stretch is cut out of the chart.`;
  }
  // After a cut-out gap, join the last actual point to the first predicted point
  // with a dotted line so the two parts still read as one chart
  const connectorTraces = [];
  if (bigGap) {
    const firstOpen = result.scenario.find(d => !d.closed);
    if (firstOpen) {
      connectorTraces.push({
        x: [lastKnown.date, firstOpen.date], y: [lastKnown.sales, firstOpen.predicted_sales],
        type: "scatter", mode: "lines", showlegend: false, hoverinfo: "skip",
        line: { color: SCENARIO_COLOR, width: 2, dash: "dot" }
      });
    }
  }

  const traces = actualPoints.length > 0 ? [actualTrace] : [];
  Plotly.newPlot(target, traces.concat(averageTraces, connectorTraces, [baselineTrace, scenarioTrace]), layout, { responsive: true });
}

// Accuracy cards and the out-of-sample badge (only when real sales exist)
function showAccuracy(result) {
  const m = result.metrics;
  accuracyBadge.hidden = true;
  accuracyCards.hidden = true;
  accuracyNote.hidden = true;

  if (!currentStore) return;

  if (!m) {
    // A store is chosen but this window cannot be scored
    accuracyNote.hidden = false;
    const gap = dataRange && result.scenario[0].date > dataRange.last;
    accuracyNote.textContent = gap
      ? `The sales data ends on ${dataRange.last}, so there are no actual sales to compare with for this period. ` +
        `The forecast starts from the store's last known sales.`
      : "Your scenario is shown against the real sales, but it is not scored because your promo and holiday choices may differ from what really happened. Switch on 'Test accuracy' to score the model.";
    return;
  }

  document.getElementById("acc-mape").textContent = `${m.mape.toFixed(1)}%`;
  document.getElementById("acc-naive").textContent =
    m.naive_mape === undefined ? "-" : `${m.naive_mape.toFixed(1)}%`;
  document.getElementById("acc-mae").textContent = Math.round(m.mae).toLocaleString("en-US");
  const sign = m.total_error_pct > 0 ? "+" : "";
  document.getElementById("acc-total").textContent = `${sign}${m.total_error_pct.toFixed(1)}%`;
  accuracyCards.hidden = false;

  accuracyBadge.hidden = false;
  if (result.overlaps_training) {
    accuracyBadge.className = "badge warn";
    accuracyBadge.textContent =
      `Part of this period is inside the model's training data (up to ${result.train_cutoff}), ` +
      `so the error looks better than it would on new data. Start after ${result.train_cutoff} for a fair test.`;
  } else {
    accuracyBadge.className = "badge ok";
    accuracyBadge.textContent =
      `Fair test: the model was trained only on days up to ${result.train_cutoff}, so it has never seen these days.`;
  }

  accuracyNote.hidden = false;
  accuracyNote.textContent =
    `Scored on ${m.days_compared} open days using the real promos, holidays and closed days of this period. ` +
    `MAPE is the average percentage miss per day; the naive forecast repeats the last observed week.`;
}


// Send the inputs to Flask and handle the reply
async function runForecast() {
  errorMessage.textContent = "";

  // Check the promo days before sending anything
  const stats = promoStats();
  if (stats.total === 0) {
    errorMessage.textContent = "Choose a start date.";
    return;
  }
  if (!currentStore) {
    for (const [input, label] of [[avg7Input, "7-day"], [avg30Input, "30-day"]]) {
      if (input.value.trim() !== "" && readAverage(input) === null) {
        errorMessage.textContent = `The ${label} average must be a number above 0.`;
        return;
      }
    }
  }
  if (promoBox.checked && !replayActive() && stats.picked === 0) {
    errorMessage.textContent = "Pick at least one open promo day, or switch Promo off.";
    return;
  }

  button.disabled = true;
  button.textContent = "Generating...";

  try {
    const response = await fetch("/forecast", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(getInputs())
    });

    // If the server sent back something that is not JSON (e.g. a 404 page)
    const contentType = response.headers.get("content-type") || "";
    if (!contentType.includes("application/json")) {
      errorMessage.textContent =
        `Unexpected response from the server (status ${response.status}).`;
      return;
    }

    const result = await response.json();

    if (!response.ok) {
      errorMessage.textContent = result.error;   // 400 or 500 message from Flask
      return;
    }

    showSummary(result.summary);
    showUplift(result);
    showInsights(result);
    drawHistoryChart(result);
    showAccuracy(result);
    drawDailyChart(result);
    drawComparisonChart(result);
  } catch (err) {
    errorMessage.textContent = "Could not reach the server. Is it running?";
  } finally {
    button.disabled = false;
    button.textContent = "Generate Forecast";
  }
}

function showUplift(result) {
  const base = sumSales(result.baseline);
  const scen = sumSales(result.scenario);
  const pct = base === 0 ? 0 : ((scen - base) / base) * 100;
  const el = document.getElementById("uplift");
  el.textContent = `${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%`;
  el.className = pct >= 0 ? "positive" : "negative";
}

function showInsights(result) {
  const scen = result.scenario;
  const base = result.baseline;
  const fmt  = v => Math.round(v).toLocaleString("en-US");
  const weekday = dateStr => new Date(dateStr + "T00:00:00")
    .toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "short" });

  const sales = scen.map(d => d.predicted_sales);
  const peakIdx = sales.indexOf(Math.max(...sales));

  // Days with 0 sales are closed days (e.g. Sundays), so skip them
  const openSales = sales.filter(v => v > 0);
  const lowIdx  = sales.indexOf(Math.min(...openSales));
  const closedDays = scen.filter(d => d.predicted_sales === 0);

  const items = [];

  items.push(`Sales are forecast to peak on <b>${weekday(scen[peakIdx].date)}</b> (Day ${peakIdx + 1}) at about ${fmt(sales[peakIdx])}.`);
  items.push(`The weakest open day is <b>${weekday(scen[lowIdx].date)}</b> (Day ${lowIdx + 1}) at about ${fmt(sales[lowIdx])}.`);
  if (closedDays.length > 0) {
    const names = closedDays.map(d => weekday(d.date)).join(", ");
    items.push(`The store is closed on <b>${names}</b>, so no sales are expected.`);
  }

  // Scenario vs baseline
  const scenTotal = sumSales(scen);
  const baseTotal = sumSales(base);
  const diff = scenTotal - baseTotal;
  const pct  = baseTotal === 0 ? 0 : (diff / baseTotal) * 100;
  if (Math.abs(pct) < 0.5) {
    items.push("The selected scenario gives <b>about the same</b> total sales as normal conditions.");
  } else if (diff > 0) {
    items.push(`The selected scenario is forecast to <b>increase</b> total sales by ${fmt(diff)} (${pct.toFixed(1)}%) compared with normal conditions.`);
  } else {
    items.push(`The selected scenario is forecast to <b>reduce</b> total sales by ${fmt(-diff)} (${Math.abs(pct).toFixed(1)}%) compared with normal conditions.`);
  }

  // Strongest weekday on average (only meaningful with 2+ weeks)
  if (scen.length >= 14) {
    const totals = {}, counts = {};
    scen.filter(d => d.predicted_sales > 0).forEach(d => {
      const name = new Date(d.date + "T00:00:00").toLocaleDateString("en-GB", { weekday: "long" });
      totals[name] = (totals[name] || 0) + d.predicted_sales;
      counts[name] = (counts[name] || 0) + 1;
    });
    const best = Object.keys(totals).reduce((a, b) =>
      totals[a] / counts[a] >= totals[b] / counts[b] ? a : b);
    items.push(`On average, <b>${best}</b> is the strongest day of the week in this period.`);
  }

  document.getElementById("insights-list").innerHTML =
    items.map(t => `<li>${t}</li>`).join("");
  document.getElementById("insights").hidden = false;
}

button.addEventListener("click", runForecast);


// ---------- Start-up ----------
setDefaultStartDate();
refreshLocks();
if (promoBox.checked) {
  applyPreset("weekdays");   // the browser can restore a ticked Promo box on reload
} else {
  renderCalendar();
}
loadStores();