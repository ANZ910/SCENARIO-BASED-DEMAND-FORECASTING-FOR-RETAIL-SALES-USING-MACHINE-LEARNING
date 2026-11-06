// Front-end logic for the Demand Forecasting Dashboard.
// Reads the scenario inputs, sends them to Flask (/forecast),
// then draws both charts and fills in the summary cards.

// Colours used by the charts
const SCENARIO_COLOR = "#2e27b7";
const BASELINE_COLOR = "#42474d";

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

// Show the slider's current number as the user drags it
distanceSlider.addEventListener("input", () => {
  distanceValue.textContent = distanceSlider.value;
});


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

// Type C stores are closed on Sundays, so promo has no effect there
function isClosed(date) {
  return storeTypeSelect.value === "c" && weekdayIndex(date) === 6;
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
    text += " (Type C is closed on Sundays)";
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
        cell.title = "Closed on Sundays (Type C)";
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
  promoDaysBlock.hidden = !promoBox.checked;
  if (promoBox.checked && selectedPromoDates.size === 0) {
    applyPreset("weekdays");
  }
});

// A new period or start date moves the window; a new store type changes which days are closed
function onWindowChange() {
  pruneSelection();
  renderCalendar();
}
periodSelect.addEventListener("change", onWindowChange);
startDateInput.addEventListener("change", onWindowChange);
storeTypeSelect.addEventListener("change", renderCalendar);


// ---------- Forecast request ----------

// Read every input and build the JSON that /forecast expects
function getInputs() {
  return {
    forecast_period_days: Number(periodSelect.value),
    start_date: startDateInput.value,
    promo_dates: promoBox.checked ? [...selectedPromoDates].sort() : [],
    promo2: promo2Box.checked ? 1 : 0,
    state_holiday_label: holidaySelect.value,
    school_holiday: schoolBox.checked ? 1 : 0,
    competition_distance: Number(distanceSlider.value),
    store_type: storeTypeSelect.value
  };
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

  const maxTotal = Math.max(baselineTotal, scenarioTotal);

  const layout = {
    margin: { t: 40, r: 10, b: 40, l: 60 },
    yaxis: { title: "Total Predicted Sales", rangemode: "tozero" },
    showlegend: false
  };

  Plotly.newPlot("comparison-chart", [barTrace], layout, { responsive: true });
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
  if (promoBox.checked && stats.picked === 0) {
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

  // Days with 0 sales are closed days (e.g. Type C on Sundays), so skip them
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
promoDaysBlock.hidden = !promoBox.checked;
if (promoBox.checked) {
  applyPreset("weekdays");   // the browser can restore a ticked Promo box on reload
} else {
  renderCalendar();
}