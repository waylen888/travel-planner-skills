---
name: navigator
description: "Optimize travel itinerary routing with real Google Maps transit times. Use when: inserting a new POI into an existing trip (finds the best day and position automatically), re-ordering an itinerary for optimal routing, or clustering unordered POIs into daily groups. Triggers on: 'add X to the trip', 'optimize the route', 're-order day 3', 'insert this POI', or when Explorer outputs a POI that needs to be placed into an itinerary."
trigger: /navigator
---

# /navigator

Optimize travel itinerary routing — cluster POIs by geographic proximity, order by nearest-neighbor, assign time slots respecting opening hours and real transit times.

## Usage

```
/navigator optimize --pois <pois.json> --city <city> --days <N>
/navigator insert  --itinerary <trip.json> --new-poi <poi.json> --city <city>
/navigator insert  --trip <city/name> --new-poi <poi.json>   # auto-lookup via registry
```

## Runtime

- **Runner**: `uv run python` — auto-manages Python version and virtualenv via `pyproject.toml` in each skill directory
- **Python**: >=3.11, stdlib only (no pip dependencies)
- **Script**: `<this-skill-dir>/scripts/navigator.py` — `<this-skill-dir>` is the directory where this SKILL.md lives
- **Invocation**: `cd <this-skill-dir> && uv run python scripts/navigator.py [mode] [args]`
- **Output**: JSON to stdout, logs to stderr, exit code 0 on success / 1 on error
- **Input**: Accepts Explorer's POI JSON output directly as `--new-poi` (insert mode) or in a POI array (optimize mode)
- **Output contract**: `daily_itinerary[]` array compatible with travel-planner's canonical JSON schema

## Prerequisites

1. **GOOGLE_MAPS_API_KEY** — Google Maps Platform API key with Geocoding + Distance Matrix enabled

Check `$GOOGLE_MAPS_API_KEY` env var first. If not set, ask the user.

---

## Mode A: Optimize

Takes an unordered list of POIs and produces an optimized `daily_itinerary[]`.

### Input

A JSON file containing either:
- A bare array of POI objects: `[{...}, ...]`
- A full itinerary JSON (auto-extracts POIs from `daily_itinerary`)

Each POI should include `visit_duration_min` (minutes to spend). Defaults to 60 if omitted.

### Command

```bash
python3 <skill-dir>/scripts/navigator.py optimize \
  --pois pois.json \
  --city "Tokyo" \
  --days 5 \
  --start-date 2026-05-15 \
  --api-key "$GOOGLE_MAPS_API_KEY"
```

Optional: `--day-start` (default 09:00), `--day-end` (default 19:00), `--mock-distances` (testing)

### Algorithm

1. **Geocode** all POIs via Google Geocoding API (cached at `~/.travel-planner/geocache.json`)
2. **Cluster** POIs into N days by geographic proximity (haversine-based seed selection + greedy assignment)
3. **Order** each day's POIs using greedy nearest-neighbor with real transit times (Google Distance Matrix, transit mode)
4. **Assign time slots** respecting opening hours and visit duration
5. **Insert meal placeholders** at lunch (12:00-13:00) and dinner (18:00-19:00) windows

### Output

```json
{
  "daily_itinerary": [
    {
      "day": 1,
      "date": "2026-05-15",
      "theme": "",
      "theme_local": "",
      "pois": [
        {
          "name": "Senso-ji Temple",
          "name_local": "淺草寺",
          "time_slot": "09:00-10:30",
          "lat": 35.7148,
          "lng": 139.7967,
          "transit_from_prev_min": 0,
          ...all original POI fields preserved...
        }
      ],
      "meals": [
        {"type": "lunch", "time_slot": "12:00-13:00", "name": "", "name_local": ""}
      ],
      "transport_notes": ""
    }
  ],
  "_unscheduled": []
}
```

**Fields Navigator fills:**
- `time_slot` — assigned time window
- `lat`, `lng` — coordinates from geocoding
- `transit_from_prev_min` — transit minutes from previous POI

**Fields Navigator leaves for Claude to fill:**
- `theme` / `theme_local` — day theme
- `meals[].name` / `meals[].name_local` — specific restaurant picks
- `transport_notes` — human-readable directions

---

## Mode B: Insert

Adds a single POI into an existing itinerary at the optimal position.

### Command

```bash
# Option 1: specify itinerary file directly
python3 <skill-dir>/scripts/navigator.py insert \
  --itinerary tokyo-may-2026.json \
  --new-poi teamlab.json \
  --city "Tokyo" \
  --api-key "$GOOGLE_MAPS_API_KEY"

# Option 2: use --trip to auto-lookup from registry (no --city needed)
python3 <skill-dir>/scripts/navigator.py insert \
  --trip "Tokyo" \
  --new-poi teamlab.json \
  --api-key "$GOOGLE_MAPS_API_KEY"
```

The `--trip` flag searches the trip registry (`~/.travel-planner/registry.json`) by city, city_local, or trip name. It auto-resolves the itinerary path and city. Supports both English ("Tokyo") and Chinese ("東京").

### Algorithm

1. Geocode the new POI
2. For each day × each insertion position, compute a disruption score:
   - Added transit time (prev→new + new→next - prev→next)
   - Downstream time shift for subsequent POIs
3. Pick the position with the lowest disruption score
4. Insert POI, recompute all time slots for that day

### Output

Same `daily_itinerary[]` format, plus:

```json
{
  "_navigator_insert_result": {
    "success": true,
    "inserted_day": 3,
    "inserted_position": 2,
    "disruption_minutes": 12
  }
}
```

If the POI can't fit anywhere, it appears in `_unscheduled[]`.

---

## POI Input Schema

```json
{
  "name": "Senso-ji Temple",
  "name_local": "淺草寺",
  "category": "temple",
  "visit_duration_min": 90,
  "opening_hours": "06:00-17:00 daily",
  "budget_jpy": 0,
  "budget_twd": 0,
  "description": "...",
  "description_local": "...",
  "google_maps_link": "https://maps.google.com/?q=Senso-ji+Temple+Tokyo",
  "tags": ["temple", "iconic"],
  "tips": "..."
}
```

The `visit_duration_min` field is critical for scheduling. If omitted, defaults to 60 minutes.

---

## Geocache

## User Data

Navigator reads and writes to the shared data directory `~/.travel-planner/`:

| File | Read/Write | Purpose |
|------|-----------|---------|
| `geocache.json` | Read + Write | Geocoding cache — avoids redundant API calls |
| `registry.json` | Read only | Trip lookup for `--trip` flag (written by travel-planner) |
| `itineraries/*.json` | Read only | Existing itineraries resolved via registry (written by travel-planner) |

See travel-planner SKILL.md for the full directory layout.

### Geocache

Coordinates are cached at `~/.travel-planner/geocache.json`.

Format: `{"POI Name|City": {"lat": 35.71, "lng": 139.79, "ts": "2026-04-14"}}`

The cache has no TTL — coordinates don't change. Delete the file to force re-geocoding.

---

## Trip Registry

When travel-planner creates or updates a Notion page, it auto-registers the trip at `~/.travel-planner/registry.json`. Navigator can look up trips by city or name using `--trip`.

```bash
# List all registered trips
python3 <travel-planner-dir>/scripts/notion_create_page.py --list-trips

# Use in navigator — these all work:
--trip "Tokyo"       # English city name
--trip "東京"         # Chinese city name
--trip "四國"         # partial match on name
```

Registry format:
```json
{
  "trips": [
    {
      "name": "東京 Tokyo 2026-05-15",
      "city": "Tokyo",
      "city_local": "東京",
      "page_id": "abc123...",
      "page_url": "https://notion.so/...",
      "itinerary_path": "/path/to/tokyo-may-2026.json",
      "days": 5,
      "start_date": "2026-05-15",
      "updated": "2026-04-15"
    }
  ]
}
```

---

## Integration with Other Skills

Navigator sits between POI collection and Notion publishing:

```
Explorer Skill
    → POI list with visit_duration_min
    → Navigator optimize
    → daily_itinerary[] with time slots and coordinates
    → Claude fills theme, meals, transport_notes
    → Travel Planner pushes to Notion
```

### Typical workflow

1. User provides POIs or Claude generates them
2. Save POIs as `pois.json`
3. Run Navigator:
   ```bash
   python3 <skill-dir>/scripts/navigator.py optimize \
     --pois pois.json --city "Tokyo" --days 5 --start-date 2026-05-15 > optimized.json
   ```
4. Claude reads `optimized.json`, fills in themes, picks restaurants for meal slots, writes transport notes
5. Claude wraps with destination, dates, checklist, tips → full itinerary JSON
6. Travel Planner pushes to Notion

### Adding a POI to existing trip

1. User says 「加一個 teamLab」
2. Save POI as `teamlab.json`
3. Run Navigator insert:
   ```bash
   python3 <skill-dir>/scripts/navigator.py insert \
     --itinerary tokyo-may-2026.json --new-poi teamlab.json --city "Tokyo" > updated.json
   ```
4. Claude reviews `_navigator_insert_result`, updates meals/transport as needed
5. Travel Planner updates Notion page

---

## Error Handling

| Error | Behavior |
|-------|----------|
| Geocoding fails for a POI | Tries `name_local`, if still fails → adds to `_unscheduled[]` |
| Distance Matrix API fails | Falls back to haversine estimate (6 min/km) |
| POI can't fit in any day | Added to `_unscheduled[]` with reason |
| API key invalid | Prints error to stderr, exits with code 1 |
