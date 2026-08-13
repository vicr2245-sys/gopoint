# Route Planner

Desktop app: describe a route in plain English ("30km hilly bike loop from
Frogner park, avoid busy streets"), Claude parses it into structured
parameters, and the app queries multiple map providers in parallel and
shows every route on a map, with the best match highlighted.

## Setup

```bash
pip install -r requirements.txt
cp env.example.txt .env
# fill in .env with your keys
python main.py
```

You need at minimum:
- `ANTHROPIC_API_KEY` — for prompt parsing
- `ORS_API_KEY` — for actual routing (loops, elevation, no card required for the free tier)

`MAPBOX_API_KEY` is optional and can be skipped entirely — its free tier
requires a card on file even though it doesn't charge you, so by default
this app runs on **ORS + OSRM + Nominatim**, none of which need a card.
Add Mapbox later if you ever want it back in the mix; nothing else needs
to change.

OSRM (routing fallback) is added automatically once ORS or Mapbox is
configured. Nominatim (geocoding fallback) is always included — it's free
with no signup at all.

## Architecture

```
main.py                    entry point, wires providers -> engine -> window
config.py                  reads .env, builds the list of active providers

core/
  prompt_parser.py          Claude API: prompt -> RouteRequest (structured JSON)
  route_engine.py           orchestrates providers concurrently, ranks results
  providers/
    base.py                 abstract RouteProvider interface
    ors_provider.py          OpenRouteService - primary (loops, elevation)
    mapbox_provider.py       Mapbox Directions - OPTIONAL (needs a card, off by default)
    osrm_provider.py         OSRM - free routing fallback, no key needed
    nominatim_provider.py    Nominatim - free geocoding-only fallback, no key needed

models/
  route_request.py          RouteRequest (parsed intent) + NormalizedRoute (result)

ui/
  main_window.py             PyQt5 window: prompt box, results list, map
  map_view.py                Leaflet.js map embedded via QWebEngineView
```

## Adding a new provider

1. Subclass `RouteProvider` in `core/providers/`, implement `geocode()` and
   `get_route()`, returning a `NormalizedRoute`.
2. Add it to `get_configured_providers()` in `config.py` behind whatever
   env var holds its key.

That's it — the engine, ranking, and map rendering are provider-agnostic.

## Building a standalone .exe (Windows)

Once you've confirmed the app runs correctly with `python main.py`, you can
package it into a distributable `.exe` that doesn't need Python installed
on the target machine.

```bash
build.bat
```

That's it — it installs/updates dependencies (including PyInstaller),
cleans out any previous build, and produces:

```
dist\RoutePlanner\RoutePlanner.exe
dist\RoutePlanner\env.example.txt   (copied automatically)
dist\RoutePlanner\_internal\...     (bundled Python + Qt + WebEngine)
```

**First run of the built app**: copy `env.example.txt` to `.env` in that
same `dist\RoutePlanner\` folder and fill in your API keys, exactly like
you did for the source version — the app looks for `.env` right next to
the `.exe` itself.

**To rebuild after making code changes**: just run `build.bat` again. It
always does a clean rebuild (deletes the old `build\` and `dist\` folders
first), so you never end up with stale bundled files.

A few things worth knowing:
- **The build is large** (several hundred MB) — that's normal for a
  Chromium-based embedded browser (QtWebEngine) bundled with everything it
  needs to run standalone. `route_planner.spec` deliberately collects
  *all* of PyQt5's files rather than relying on PyInstaller's automatic
  detection, since the automatic hook has a track record of missing
  WebEngine resource files (leading to a blank map). This trades build
  size for reliability.
- **`console=True` by default** in `route_planner.spec` — a console
  window stays open alongside the app, showing any startup errors. Once
  you've confirmed a build works cleanly, you can flip this to
  `console=False` in the spec (find the `EXE(...)` block) for a release
  build with no visible terminal.
- **No custom icon yet** — add a `.ico` file to the project and set
  `icon='your-file.ico'` in the same `EXE(...)` block in
  `route_planner.spec` when you want one.
- If you ever get a blank/broken map in the built `.exe` specifically
  (works fine with `python main.py` but not the built version), that's
  almost always a QtWebEngine resource-bundling issue — re-running
  `build.bat` after a `pip install --upgrade pyinstaller` is the first
  thing to try, since PyInstaller's Qt/WebEngine hooks improve over time.



- **Loop routing on Mapbox/OSRM is a heuristic** (synthetic waypoints on a
  circle around the start point), not a true "round trip" mode — only ORS
  supports that natively. Loop quality from ORS will generally be better.
- **`current_location`**: if the user doesn't mention a start location, the
  parser fills in the placeholder `"current_location"` — you'll want to wire
  this up to actual OS geolocation (or just ask the user) before shipping.
- **OSRM's public demo server** has no uptime guarantee and rate-limits
  aggressively — fine for dev, self-host it for production use.
- **Ranking is a simple weighted score** (distance-match, elevation
  preference) — easy to extend with things like road-safety data, surface
  type, or popularity/heatmap data from Strava if you add that provider later.
- No caching yet — repeated identical requests re-hit every API.
