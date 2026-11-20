const form = document.getElementById("aqi-form");
const cityEl = document.getElementById("city");
const profEl = document.getElementById("profile");
const btn = document.getElementById("submit-btn");
const errEl = document.getElementById("error-msg");
const resEl = document.getElementById("results");
const statusEl = document.getElementById("live-status");
const contrastBtn = document.getElementById("contrast-toggle");

function renderForecastBars(values) {
  const container = document.getElementById("forecast-bars");
  container.innerHTML = "";
  const maxVal = Math.max(...values, 100);

  values.forEach((val, idx) => {
    const col = document.createElement("div");
    col.className = "bar-col";
    col.title = `+${idx + 1}h: AQI ${val}`;

    const fill = document.createElement("div");
    fill.className = "bar-fill";
    fill.style.height = `${Math.max(12, Math.round((val / maxVal) * 52))}px`;

    const lbl = document.createElement("span");
    lbl.className = "bar-label";
    lbl.textContent = val;

    col.appendChild(fill);
    col.appendChild(lbl);
    container.appendChild(col);
  });
}

async function fetchReport(city, profile) {
  errEl.classList.add("hidden");
  btn.disabled = true;
  btn.textContent = "Analyzing...";

  try {
    const res = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ city, profile }),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || "Unable to retrieve air quality telemetry.");
    }

    document.getElementById("loc-name").textContent = `${data.location.name}, ${data.location.country}`;
    document.getElementById("prof-label").textContent = `Profile: ${data.profile}`;

    const badge = document.getElementById("aqi-badge");
    badge.textContent = data.air_quality.badge;
    badge.className = `badge ${data.air_quality.badge}`;

    document.getElementById("aqi-num").textContent = data.air_quality.us_aqi;
    document.getElementById("aqi-cat").textContent = data.air_quality.category;
    document.getElementById("aqi-risk").textContent = `Exposure Risk: ${data.air_quality.risk_level}`;
    document.getElementById("dominant-pol").textContent = `Primary Driver: ${data.air_quality.dominant_pollutant}`;

    document.getElementById("pm25").textContent = data.air_quality.pollutants.pm2_5;
    document.getElementById("pm10").textContent = data.air_quality.pollutants.pm10;
    document.getElementById("no2").textContent = data.air_quality.pollutants.no2;
    document.getElementById("o3").textContent = data.air_quality.pollutants.o3;

    renderForecastBars(data.air_quality.hourly_forecast || []);

    document.getElementById("ai-src").textContent = data.advisory.source;
    document.getElementById("adv-health").textContent = data.advisory.health;
    document.getElementById("adv-commute").textContent = data.advisory.commute;
    document.getElementById("adv-urban").textContent = data.advisory.urban;

    resEl.classList.remove("hidden");
    statusEl.textContent = `Updated AQI report for ${data.location.name}: ${data.air_quality.us_aqi}`;
  } catch (err) {
    errEl.textContent = err.message;
    errEl.classList.remove("hidden");
    statusEl.textContent = `Error: ${err.message}`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Analyze Air Quality";
  }
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  fetchReport(cityEl.value.trim(), profEl.value);
});

document.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    cityEl.value = chip.dataset.city;
    fetchReport(chip.dataset.city, profEl.value);
  });
});

contrastBtn.addEventListener("click", () => {
  const active = document.body.classList.toggle("high-contrast");
  contrastBtn.setAttribute("aria-pressed", String(active));
});

window.addEventListener("DOMContentLoaded", () => {
  fetchReport(cityEl.value, profEl.value);
});
