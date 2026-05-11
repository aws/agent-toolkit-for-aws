# Logistics Weather Board

A single-page weather dashboard for global logistics teams. Add the cities,
ports, and hubs your teams operate from, and see current conditions, a 3-day
outlook, and severe-weather flags at a glance.

## Highlights

- **No API key.** Powered by [Open-Meteo](https://open-meteo.com/) for forecasts
  and geocoding.
- **Multi-site dashboard.** Track an arbitrary number of facilities side by
  side. Sites are saved in `localStorage` per browser.
- **Unit toggle.** Metric (°C, km/h, mm) or imperial (°F, mph, in).
- **Severe-weather flags.** Cards highlight thunderstorms, heavy precipitation,
  freezing rain, and high winds so dispatchers can react quickly.
- **Auto-refresh** every 15 minutes; manual refresh button included.
- **Pure static.** Three files (`index.html`, `styles.css`, `app.js`) — no
  build step.

## Run locally

Open `index.html` directly in a browser, or serve the folder:

```sh
cd weather-app
python3 -m http.server 8000
# then visit http://localhost:8000
```

## Deploy

Because it's a static SPA, any static host works:

- **S3 + CloudFront** — `aws s3 sync weather-app/ s3://your-bucket/` and front
  with CloudFront.
- **Cloudflare Pages** — point Pages at this directory; no build command
  needed.
- **GitHub Pages** — publish the `weather-app/` folder.

Open-Meteo is called directly from the browser, so the only network egress
required from a deployed page is to `*.open-meteo.com`.

## Data attribution

Forecast and geocoding data: © [Open-Meteo](https://open-meteo.com/) — free
for non-commercial use; see their site for commercial terms.
