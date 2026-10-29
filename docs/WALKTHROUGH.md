# Loom walkthrough outline (≈ 8 minutes)

Weights from the brief: 40 % logic, 40 % UI/map/heatmap, 15 % code, 5 % docs. Spend time accordingly.

## 0:00 – 0:40 · Intro
- What the app does in one sentence; stack (React + Leaflet, Django REST, OSRM, Open-Meteo).
- Show the live URL and the GitHub repo.

## 0:40 – 2:30 · Live demo (live forecast)
- Pick *Dallas → Oklahoma City*, departure in a few hours, 40,000 lb, 25 mi. Plan.
- Walk the recommendation box: the reasons name the deciding criterion.
- Route cards: drive time, arrival, Severe+/High miles, average risk, the risk strip.
- Click another route on the map → it becomes the risk-coloured route; click a checkpoint
  for its popup (ETA, wind/gust, rain, snow, what drove the level, load rule).
- Checkpoint table → click a row to fly to it.

## 2:30 – 4:00 · Demo storm (proves the logic)
- Switch to *Demo storm*, 10 mi interval, re-plan *Chicago → Minneapolis*.
- Route A now has No Travel/Severe miles and drops to last; explain why C beats B (High miles).
- Change load to 20,000 lb and re-plan: show how the load rules soften wind levels.
- Heatmap: drag the slider, press play; truck marker moves along the selected route; switch the
  Risk / Wind / Rain / Snow layers; the legend thresholds match the rules.

## 4:00 – 6:30 · Code tour
- `risk.py` — rules as data, band edges, load rules, `assess()` = worst factor.
- `checkpoints.py` — truck speed cap, checkpoint spacing, ETAs, "represented miles".
- `weather.py` — batched + cached Open-Meteo, interpolation at the ETA (wind vs precip buckets).
- `recommend.py` — criteria table, tolerances, explanations.
- `routing.py` — topping up to three distinct routes with via-points; rejection rules.
- `heatmap.py` + `lib/heatmap.ts` — Mercator-square grid, frames as image overlays, 15-min blending.

## 6:30 – 7:30 · Quality & performance
- Run `python manage.py test trips` (43 tests).
- Network tab: plan ≈ 1–2 s, heatmap a few hundred ms, payloads gzipped (tens of KB).
- Canvas renderer for markers, memoised layers, frame cache.

## 7:30 – 8:00 · Trade-offs / next steps
- Car router + speed cap vs a truck router; hours of service; gusts; paid API keys for scale.
