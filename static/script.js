
// script.js
// Front-end logic for the Demand Forecasting Dashboard.
// Reads the scenario inputs, sends them to Flask (/forecast),
// then draws both charts and fills in the summary cards.
 
// Colours used by the charts 
const SCENARIO_COLOR = "#2e27b7";
const BASELINE_COLOR = "#42474d";
 
// Grab the elements we need (by the ids in index.html)
const periodSelect   = document.getElementById("forecast-period");
const promoBox       = document.getElementById("promo");
const promo2Box      = document.getElementById("promo2");
const holidaySelect  = document.getElementById("state-holiday");
const storeTypeSelect = document.getElementById("store-type");
const schoolBox      = document.getElementById("school-holiday");
const distanceSlider = document.getElementById("competition-distance");
const distanceValue  = document.getElementById("distance-value");
const button         = document.getElementById("forecast-button");
const errorMessage   = document.getElementById("error-message");
 
// Show the slider's current number as the user drags it
distanceSlider.addEventListener("input", () => {
  distanceValue.textContent = distanceSlider.value;
});
 
// Read every input and build the JSON that /forecast expects
function getInputs() {
  return {
    forecast_period_days: Number(periodSelect.value),
    promo: promoBox.checked ? 1 : 0,
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