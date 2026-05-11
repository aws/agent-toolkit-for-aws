const STORAGE_KEY = "logistics-weather:v1";
const GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search";
const FORECAST_URL = "https://api.open-meteo.com/v1/forecast";

// Open-Meteo WMO weather codes -> [emoji, label]
const WMO = {
  0:  ["☀️",  "Clear"],
  1:  ["🌤️", "Mainly clear"],
  2:  ["⛅",         "Partly cloudy"],
  3:  ["☁️",  "Overcast"],
  45: ["🌫️", "Fog"],
  48: ["🌫️", "Rime fog"],
  51: ["🌦️", "Light drizzle"],
  53: ["🌦️", "Drizzle"],
  55: ["🌧️", "Heavy drizzle"],
  56: ["🌧️", "Freezing drizzle"],
  57: ["🌧️", "Freezing drizzle"],
  61: ["🌦️", "Light rain"],
  63: ["🌧️", "Rain"],
  65: ["🌧️", "Heavy rain"],
  66: ["🌧️", "Freezing rain"],
  67: ["🌧️", "Freezing rain"],
  71: ["🌨️", "Light snow"],
  73: ["🌨️", "Snow"],
  75: ["🌨️", "Heavy snow"],
  77: ["🌨️", "Snow grains"],
  80: ["🌦️", "Rain showers"],
  81: ["🌧️", "Heavy showers"],
  82: ["⛈️",  "Violent showers"],
  85: ["🌨️", "Snow showers"],
  86: ["🌨️", "Heavy snow showers"],
  95: ["⛈️",  "Thunderstorm"],
  96: ["⛈️",  "Thunderstorm w/ hail"],
  99: ["⛈️",  "Thunderstorm w/ hail"],
};

const state = {
  sites: [],
  units: "metric",
  data: new Map(), // id -> latest forecast payload
};

const grid = document.getElementById("grid");
const empty = document.getElementById("empty");
const statusBar = document.getElementById("status");
const updatedEl = document.getElementById("updated");
const cityInput = document.getElementById("city-input");
const suggestionList = document.getElementById("suggestions");
const addForm = document.getElementById("add-form");

function load() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed.sites)) state.sites = parsed.sites;
    if (parsed.units === "imperial" || parsed.units === "metric") state.units = parsed.units;
  } catch { /* ignore corrupt storage */ }
}

function save() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ sites: state.sites, units: state.units }));
  } catch { /* quota or private mode — ignore */ }
}

function setStatus(msg) {
  if (!msg) { statusBar.hidden = true; statusBar.textContent = ""; return; }
  statusBar.hidden = false;
  statusBar.textContent = msg;
}

function siteId(site) {
  return `${site.latitude.toFixed(3)},${site.longitude.toFixed(3)}`;
}

async function searchCities(q) {
  const url = `${GEOCODE_URL}?name=${encodeURIComponent(q)}&count=6&language=en&format=json`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Geocoding failed: ${res.status}`);
  const json = await res.json();
  return json.results || [];
}

async function fetchForecast(site) {
  const params = new URLSearchParams({
    latitude: site.latitude,
    longitude: site.longitude,
    current: "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,weather_code,wind_speed_10m,wind_direction_10m",
    daily: "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max",
    timezone: "auto",
    forecast_days: "4",
    temperature_unit: state.units === "imperial" ? "fahrenheit" : "celsius",
    wind_speed_unit: state.units === "imperial" ? "mph" : "kmh",
    precipitation_unit: state.units === "imperial" ? "inch" : "mm",
  });
  const res = await fetch(`${FORECAST_URL}?${params}`);
  if (!res.ok) throw new Error(`Forecast failed: ${res.status}`);
  return res.json();
}

function formatLocalTime(iso, tz) {
  try {
    return new Date(iso).toLocaleString(undefined, {
      timeZone: tz, weekday: "short", hour: "numeric", minute: "2-digit",
    });
  } catch {
    return new Date(iso).toLocaleString();
  }
}

function dayLabel(dateStr, tz) {
  try {
    const d = new Date(dateStr + "T12:00:00");
    return d.toLocaleDateString(undefined, { timeZone: tz, weekday: "short" });
  } catch {
    return dateStr.slice(5);
  }
}

function unitLabels() {
  return state.units === "imperial"
    ? { temp: "°F", wind: "mph", precip: "in" }
    : { temp: "°C", wind: "km/h", precip: "mm" };
}

function severityFor(code, windSpeed) {
  if ([95, 96, 99, 82].includes(code)) return "Severe weather: thunderstorms / violent showers.";
  if ([65, 75, 81, 86].includes(code)) return "Heavy precipitation expected.";
  if ([56, 57, 66, 67].includes(code)) return "Freezing precipitation — hazardous roads.";
  const gusty = state.units === "imperial" ? windSpeed >= 35 : windSpeed >= 55;
  if (gusty) return "High winds — review outdoor operations.";
  return null;
}

function renderEmptyState() {
  const hasSites = state.sites.length > 0;
  empty.hidden = hasSites;
  grid.hidden = !hasSites;
}

function render() {
  renderEmptyState();
  grid.innerHTML = "";
  const tpl = document.getElementById("card-tpl");
  const u = unitLabels();

  for (const site of state.sites) {
    const id = siteId(site);
    const node = tpl.content.firstElementChild.cloneNode(true);
    node.dataset.id = id;
    node.querySelector(".card__city").textContent = site.name;
    node.querySelector(".card__region").textContent = [site.admin1, site.country].filter(Boolean).join(", ");
    node.querySelector(".card__remove").addEventListener("click", () => removeSite(id));

    const data = state.data.get(id);
    if (data === "loading") {
      node.classList.add("is-loading");
      node.querySelector(".card__cond").textContent = "Loading…";
    } else if (data instanceof Error) {
      node.classList.add("is-error");
      node.querySelector(".card__cond").textContent = data.message;
    } else if (data) {
      const cur = data.current;
      const [icon, label] = WMO[cur.weather_code] || ["", "Conditions unavailable"];
      node.querySelector(".card__icon").textContent = icon;
      node.querySelector(".card__temp-value").textContent = Math.round(cur.temperature_2m);
      node.querySelector(".card__temp-unit").textContent = u.temp;
      node.querySelector(".card__cond").textContent = label;
      node.querySelector(".card__feels").textContent = `Feels like ${Math.round(cur.apparent_temperature)}${u.temp}`;
      node.querySelector(".card__wind").textContent = `${Math.round(cur.wind_speed_10m)} ${u.wind}`;
      node.querySelector(".card__hum").textContent = `${cur.relative_humidity_2m}%`;
      node.querySelector(".card__precip").textContent = `${cur.precipitation} ${u.precip}`;
      node.querySelector(".card__time").textContent = formatLocalTime(cur.time, data.timezone);

      const fc = node.querySelector(".card__forecast");
      const days = data.daily.time.slice(1, 4); // skip today, show next 3
      for (let i = 0; i < days.length; i++) {
        const idx = i + 1;
        const [dIcon] = WMO[data.daily.weather_code[idx]] || [""];
        const li = document.createElement("li");
        li.innerHTML = `
          <span class="day">${dayLabel(days[i], data.timezone)}</span>
          <span class="ico">${dIcon}</span>
          <span class="hi">${Math.round(data.daily.temperature_2m_max[idx])}°</span>
          <span class="lo">${Math.round(data.daily.temperature_2m_min[idx])}°</span>
        `;
        fc.appendChild(li);
      }

      const alertText = severityFor(cur.weather_code, cur.wind_speed_10m);
      if (alertText) {
        const a = node.querySelector(".card__alert");
        a.hidden = false;
        a.textContent = alertText;
      }
    }
    grid.appendChild(node);
  }

  if (state.sites.length > 0) {
    updatedEl.textContent = `Updated ${new Date().toLocaleTimeString()}`;
  } else {
    updatedEl.textContent = "";
  }
}

async function refreshSite(site) {
  const id = siteId(site);
  state.data.set(id, "loading");
  render();
  try {
    const data = await fetchForecast(site);
    state.data.set(id, data);
  } catch (err) {
    state.data.set(id, err);
  }
  render();
}

async function refreshAll() {
  if (state.sites.length === 0) { render(); return; }
  setStatus("");
  await Promise.all(state.sites.map(refreshSite));
}

function addSite(site) {
  const id = siteId(site);
  if (state.sites.some(s => siteId(s) === id)) {
    setStatus(`${site.name} is already on the board.`);
    return;
  }
  state.sites.push(site);
  save();
  refreshSite(site);
}

function removeSite(id) {
  state.sites = state.sites.filter(s => siteId(s) !== id);
  state.data.delete(id);
  save();
  render();
}

let suggestTimer = null;
function scheduleSuggest() {
  clearTimeout(suggestTimer);
  const q = cityInput.value.trim();
  if (q.length < 2) { suggestionList.hidden = true; return; }
  suggestTimer = setTimeout(async () => {
    try {
      const results = await searchCities(q);
      renderSuggestions(results);
    } catch (err) {
      setStatus(err.message);
    }
  }, 200);
}

function renderSuggestions(results) {
  suggestionList.innerHTML = "";
  if (!results.length) { suggestionList.hidden = true; return; }
  for (const r of results) {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = [r.name, r.admin1, r.country].filter(Boolean).join(", ");
    btn.addEventListener("click", () => {
      addSite({
        name: r.name,
        admin1: r.admin1,
        country: r.country,
        latitude: r.latitude,
        longitude: r.longitude,
      });
      cityInput.value = "";
      suggestionList.hidden = true;
    });
    li.appendChild(btn);
    suggestionList.appendChild(li);
  }
  suggestionList.hidden = false;
}

addForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const q = cityInput.value.trim();
  if (!q) return;
  try {
    const results = await searchCities(q);
    if (!results.length) { setStatus(`No matches for "${q}".`); return; }
    addSite({
      name: results[0].name,
      admin1: results[0].admin1,
      country: results[0].country,
      latitude: results[0].latitude,
      longitude: results[0].longitude,
    });
    cityInput.value = "";
    suggestionList.hidden = true;
  } catch (err) {
    setStatus(err.message);
  }
});

cityInput.addEventListener("input", scheduleSuggest);
cityInput.addEventListener("blur", () => setTimeout(() => suggestionList.hidden = true, 120));
cityInput.addEventListener("focus", scheduleSuggest);

document.querySelectorAll(".unit").forEach(btn => {
  btn.addEventListener("click", () => {
    if (btn.classList.contains("is-active")) return;
    document.querySelectorAll(".unit").forEach(b => b.classList.toggle("is-active", b === btn));
    state.units = btn.dataset.units;
    save();
    refreshAll();
  });
});

document.getElementById("refresh").addEventListener("click", refreshAll);

empty.addEventListener("click", async (e) => {
  const target = e.target.closest("[data-quickadd]");
  if (!target) return;
  const q = target.textContent;
  try {
    const results = await searchCities(q);
    if (results.length) {
      addSite({
        name: results[0].name,
        admin1: results[0].admin1,
        country: results[0].country,
        latitude: results[0].latitude,
        longitude: results[0].longitude,
      });
    }
  } catch (err) {
    setStatus(err.message);
  }
});

load();
document.querySelectorAll(".unit").forEach(b => b.classList.toggle("is-active", b.dataset.units === state.units));
render();
refreshAll();

// Auto-refresh every 15 minutes
setInterval(refreshAll, 15 * 60 * 1000);
