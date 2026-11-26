const form = document.getElementById("aqi-form");
const cityEl = document.getElementById("city");
const profEl = document.getElementById("profile");
const btn = document.getElementById("submit-btn");
const errEl = document.getElementById("error-msg");
const resEl = document.getElementById("results");
const statusEl = document.getElementById("live-status");
const contrastBtn = document.getElementById("contrast-toggle");
const copyShareBtn = document.getElementById("copy-share-btn");

let activeRequest;

function readRequestPayload(city, profile) {
  const distanceRaw = parseFloat(document.getElementById("hh-distance").value);
  const roomRaw = parseFloat(document.getElementById("hh-room").value);
  return {
    city,
    profile,
    household: {
      has_children: document.getElementById("hh-children").checked,
      has_elderly: document.getElementById("hh-elderly").checked,
      has_respiratory_risk: document.getElementById("hh-resp").checked,
      commute_mode: document.getElementById("hh-commute").value,
      commute_distance_km: Number.isFinite(distanceRaw) && distanceRaw >= 0.5 ? distanceRaw : 10,
      budget_tier: document.getElementById("hh-budget").value,
      owns_purifier: document.getElementById("hh-purifier").checked,
      room_area_sqft: Number.isFinite(roomRaw) && roomRaw >= 40 ? roomRaw : 180,
    },
  };
}

function formatPollutant(value) {
  return value === null || value === undefined ? "Unavailable" : `${value} \u00b5g/m\u00b3`;
}

function renderForecast(air) {
  const values = air.hourly_forecast || [];
  const points = air.forecast_points || [];
  const container = document.getElementById("forecast-bars");
  const tbody = document.getElementById("forecast-table-body");
  const maxVal = Math.max(...values, 100);

  const barCols = values.map((val, idx) => {
    const col = document.createElement("div");
    col.className = "bar-col";
    const timeLabel = points[idx] ? points[idx].time.slice(11, 16) : `+${idx + 1}h`;
    col.title = `${timeLabel}: AQI ${val}`;

    const fill = document.createElement("div");
    fill.className = "bar-fill";
    fill.style.height = `${Math.max(12, Math.round((val / maxVal) * 52))}px`;

    const lbl = document.createElement("span");
    lbl.className = "bar-label";
    lbl.textContent = String(val);

    col.append(fill, lbl);
    return col;
  });
  container.replaceChildren(...barCols);

  const rows = (points.length ? points : values.map((v, i) => ({ time: `+${i + 1}h`, us_aqi: v }))).map((pt) => {
    const tr = document.createElement("tr");
    const tdTime = document.createElement("td");
    tdTime.textContent = pt.time.includes("T") ? pt.time.slice(11, 16) : pt.time;
    const tdVal = document.createElement("td");
    tdVal.textContent = String(pt.us_aqi);
    tr.append(tdTime, tdVal);
    return tr;
  });
  tbody.replaceChildren(...rows);

  document.getElementById("forecast-summary").textContent = values.length
    ? `Forecast US AQI over the next ${values.length} hours ranges from ${Math.min(...values)} to ${Math.max(...values)}.`
    : "Hourly forecast unavailable.";

  const winBox = document.getElementById("window-summary");
  const bestText = air.best_window
    ? `Cleaner 2h window: ${air.best_window.label} (est. AQI ${air.best_window.average_aqi})`
    : "No clearly cleaner outdoor window in forecast";
  const worstText = air.worst_window
    ? `Peak smog window: ${air.worst_window.label} (est. AQI ${air.worst_window.average_aqi})`
    : "";
  winBox.textContent = worstText ? `${bestText} | ${worstText}` : bestText;
}

function renderStackItems(containerId, items, buildText) {
  const container = document.getElementById(containerId);
  const nodes = items.map((item) => {
    const div = document.createElement("div");
    div.className = "stack-item";
    const title = document.createElement("strong");
    const body = document.createElement("p");
    const note = document.createElement("p");
    note.className = "muted-text";
    buildText(item, title, body, note);
    div.append(title, body, note);
    return div;
  });
  container.replaceChildren(...nodes);
}

function renderImpactAndSizing(advisory) {
  const cadrBox = document.getElementById("cadr-box");
  if (advisory.indoor_sizing) {
    const s = advisory.indoor_sizing;
    cadrBox.textContent =
      `Room CADR Target (${s.room_area_sqft} sq ft): ${s.recommended_cadr_m3h[0]}-${s.recommended_cadr_m3h[1]} m\u00b3/h at ${s.target_ach} ACH. ${s.methodology_note}`;
  } else {
    cadrBox.textContent = "";
  }

  const impactBox = document.getElementById("impact-box");
  if (advisory.commute_impact) {
    const imp = advisory.commute_impact;
    const line1 = document.createElement("strong");
    line1.textContent = `${imp.current_mode} \u2192 ${imp.recommended_mode} (${imp.one_way_km} km one-way)`;
    const line2 = document.createElement("p");
    line2.textContent = `Est. tailpipe savings: ${imp.daily_co2_saved_kg} kg CO\u2082e/day | ${imp.annual_co2_saved_kg} kg/yr (range ${imp.uncertainty_band_kg[0]}-${imp.uncertainty_band_kg[1]} kg/yr).`;
    const line3 = document.createElement("p");
    line3.className = "muted-text";
    line3.textContent = `${imp.exposure_note} ${imp.factor_citation}`;
    impactBox.replaceChildren(line1, line2, line3);
  } else {
    impactBox.textContent = "";
  }

  document.getElementById("share-text").textContent = advisory.community_share_text || "";
}

function renderReport(data) {
  const air = data.air_quality;
  const adv = data.advisory;

  document.getElementById("loc-name").textContent = `${data.location.name}, ${data.location.country}`;
  document.getElementById("prof-label").textContent = `Profile: ${data.profile}`;

  const badge = document.getElementById("aqi-badge");
  badge.textContent = air.badge;
  badge.className = `badge ${air.badge}`;

  const aqiNum = document.getElementById("aqi-num");
  aqiNum.textContent = String(air.us_aqi);
  aqiNum.setAttribute("aria-label", `US AQI score ${air.us_aqi}`);

  document.getElementById("aqi-cat").textContent = air.category;
  document.getElementById("aqi-risk").textContent = `Exposure Risk: ${air.risk_level}`;
  document.getElementById("dominant-pol").textContent = `Primary Driver: ${air.dominant_pollutant}`;

  const timeInfo = air.measurement_time ? ` | Reading time: ${air.measurement_time} (${air.timezone})` : "";
  const cacheInfo = air.is_cached ? " [cached]" : "";
  document.getElementById("provenance-note").textContent = `${air.data_source}${timeInfo}${cacheInfo}`;

  document.getElementById("pm25").textContent = formatPollutant(air.pollutants.pm2_5);
  document.getElementById("pm10").textContent = formatPollutant(air.pollutants.pm10);
  document.getElementById("no2").textContent = formatPollutant(air.pollutants.no2);
  document.getElementById("o3").textContent = formatPollutant(air.pollutants.o3);

  renderForecast(air);

  document.getElementById("ai-src").textContent = adv.source;
  document.getElementById("adv-why").textContent = adv.why_this_matters || "";
  document.getElementById("adv-health").textContent = adv.health;
  document.getElementById("adv-commute").textContent = adv.commute;
  document.getElementById("adv-urban").textContent = adv.urban;

  renderStackItems("routine-list", adv.daily_routine || [], (step, title, body, note) => {
    title.textContent = `${step.slot}: ${step.title}`;
    body.textContent = step.action;
    note.textContent = step.reason;
  });

  renderStackItems("indoor-list", adv.indoor_hacks || [], (hack, title, body, note) => {
    title.textContent = `${hack.title} (${hack.cost_tier})`;
    body.textContent = hack.action;
    note.textContent = hack.why_it_helps;
  });

  renderImpactAndSizing(adv);
}

function errorMessage(status, data) {
  if (typeof data.detail === "string") {
    return data.detail;
  }
  if (status === 422) {
    return "Please enter a valid city name (2-80 characters) and valid numeric inputs.";
  }
  return "Unable to retrieve air quality telemetry.";
}

async function fetchReport(city, profile) {
  activeRequest?.abort();
  resEl.classList.add("hidden");
  errEl.classList.add("hidden");

  if (!city || city.trim().length < 2) {
    const message = "Please enter a valid city name (2-80 characters).";
    errEl.textContent = message;
    errEl.classList.remove("hidden");
    statusEl.textContent = `Error: ${message}`;
    return;
  }

  btn.disabled = true;
  btn.textContent = "Analyzing...";

  resEl.setAttribute("aria-busy", "true");
  statusEl.textContent = `Loading air quality for ${city}...`;
  const controller = new AbortController();
  activeRequest = controller;
  const timer = setTimeout(() => controller.abort(), 20000);

  try {
    const res = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(readRequestPayload(city, profile)),
      signal: controller.signal,
    });
    const data = await res.json().catch(() => ({}));
    if (activeRequest !== controller) return;
    if (!res.ok) {
      throw new Error(errorMessage(res.status, data));
    }

    renderReport(data);
    resEl.classList.remove("hidden");
    statusEl.textContent = `Updated AQI report for ${data.location.name}: ${data.air_quality.us_aqi}`;
  } catch (err) {
    if (activeRequest !== controller) return;
    const message =
      err.name === "AbortError" ? "The request timed out. Please try again." : err.message;
    errEl.textContent = message;
    errEl.classList.remove("hidden");
    statusEl.textContent = `Error: ${message}`;
  } finally {
    clearTimeout(timer);
    if (activeRequest !== controller) return;
    activeRequest = undefined;
    resEl.setAttribute("aria-busy", "false");
    btn.disabled = false;
    btn.textContent = "Analyze Air Quality";
  }
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  fetchReport(cityEl.value.trim(), profEl.value);
});

document.querySelectorAll(".chip[data-city]").forEach((chip) => {
  chip.addEventListener("click", () => {
    cityEl.value = chip.dataset.city;
    fetchReport(chip.dataset.city, profEl.value);
  });
});

contrastBtn.addEventListener("click", () => {
  const active = document.body.classList.toggle("high-contrast");
  contrastBtn.setAttribute("aria-pressed", String(active));
});

copyShareBtn.addEventListener("click", async () => {
  const text = document.getElementById("share-text").textContent;
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    copyShareBtn.textContent = "Copied!";
    statusEl.textContent = "Community update copied to clipboard.";
    setTimeout(() => {
      copyShareBtn.textContent = "Copy Community Update";
    }, 2000);
  } catch {
    statusEl.textContent = "Clipboard copy unavailable; select and copy the text manually.";
  }
});

window.addEventListener("DOMContentLoaded", () => {
  fetchReport(cityEl.value, profEl.value);
});
