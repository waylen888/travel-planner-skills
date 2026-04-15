---
name: explorer
description: "Extract structured POI data from URLs or place names via Google Places API. Use when the user pastes a Google Maps link, Tabelog link, or any restaurant/attraction URL and wants to add it to a trip. Also use when the user mentions a place name and you need structured data (coordinates, opening hours, category, budget). Triggers on: pasted URLs containing 'google.com/maps', 'tabelog.com', 'tripadvisor.com', or when you need POI data for Navigator insertion."
trigger: /explorer
---

# /explorer

Extract structured POI data from URLs or place names. Parses Google Maps links, restaurant sites, or plain text queries, then uses Google Places API to return a canonical POI JSON ready for Navigator.

## Usage

```
/explorer --url <link> --city <city>
/explorer --query <place-name> --city <city>
```

## Runtime

- **Runner**: `uv run python` — auto-manages Python version and virtualenv via `pyproject.toml` in each skill directory
- **Python**: >=3.11, stdlib only (no pip dependencies)
- **Script**: `<this-skill-dir>/scripts/explorer.py` — `<this-skill-dir>` is the directory where this SKILL.md lives
- **Invocation**: `cd <this-skill-dir> && uv run python scripts/explorer.py [args]`
- **Output**: POI JSON to stdout, logs to stderr, exit code 0 on success / 1 on error
- **Output contract**: Single POI JSON object compatible with Navigator's `--new-poi` input and travel-planner's `pois[]` schema
- **`--url` and `--query` are mutually exclusive** — provide exactly one

## User Data

Explorer itself does not write to the shared data directory, but its output feeds into skills that do:

- **Save POI output with `--save`** to pass to Navigator's `--new-poi`
- Navigator and Travel Planner store data at `~/.travel-planner/` (see travel-planner SKILL.md for full directory layout)

## Prerequisites

1. **GOOGLE_MAPS_API_KEY** — Google Maps Platform API key with **Places API (New)** enabled

Check `$GOOGLE_MAPS_API_KEY` env var first. If not set, ask the user.

---

## Supported URL Types

| Source | Example | Parsing Method |
|--------|---------|---------------|
| Google Maps (full) | `https://www.google.com/maps/place/淺草寺/...` | Extract place name from URL path |
| Google Maps (query) | `https://maps.google.com/?q=Senso-ji+Temple` | Extract from `?q=` parameter |
| Google Maps (short) | `https://goo.gl/maps/...` or `https://maps.app.goo.gl/...` | Follow redirect → parse full URL |
| Tabelog | `https://tabelog.com/tokyo/...` | Fetch page `<title>` |
| TripAdvisor | `https://www.tripadvisor.com/...` | Fetch page `<title>` |
| Booking.com | `https://www.booking.com/hotel/...` | Fetch page `<title>` |
| Any URL | Any restaurant/attraction page | Fetch page `<title>` as fallback |
| Plain text | `teamLab Borderless` | Use directly as search query |

---

## Command

```bash
# From a Google Maps link
python3 <skill-dir>/scripts/explorer.py \
  --url "https://maps.google.com/?q=淺草寺" \
  --city "Tokyo" \
  --api-key "$GOOGLE_MAPS_API_KEY"

# From a place name
python3 <skill-dir>/scripts/explorer.py \
  --query "一蘭拉麵 新宿" \
  --city "Tokyo" \
  --api-key "$GOOGLE_MAPS_API_KEY"

# Save output to file (for piping to Navigator)
python3 <skill-dir>/scripts/explorer.py \
  --query "teamLab Borderless" \
  --city "Tokyo" \
  --save /tmp/teamlab.json
```

---

## Output

Standard POI JSON, ready for Navigator's `--new-poi`:

```json
{
  "name": "淺草寺",
  "name_local": "淺草寺",
  "category": "culture",
  "visit_duration_min": 60,
  "opening_hours": "06:00-17:00 daily",
  "description": "東京最古老的佛教寺廟...",
  "description_local": "東京最古老的佛教寺廟...",
  "google_maps_link": "https://maps.google.com/?cid=...",
  "lat": 35.7148,
  "lng": 139.7967,
  "budget_jpy": 0,
  "budget_twd": 0,
  "tags": ["temple", "tourist_attraction", "place_of_worship"],
  "tips": "Google 評分 4.5⭐ (42,000 則評論)"
}
```

### Fields Extracted

| Field | Source | Reliability |
|-------|--------|-------------|
| `name` / `name_local` | Places API `displayName` (zh-TW) | Deterministic |
| `lat` / `lng` | Places API `location` | Deterministic |
| `opening_hours` | Places API `regularOpeningHours` | Deterministic |
| `category` | Mapped from `primaryType` / `types` | Deterministic |
| `visit_duration_min` | Rule-based: category → duration table | Heuristic |
| `budget_jpy` / `budget_twd` | Mapped from `priceLevel` | Approximate |
| `description` | Places API `editorialSummary` | When available |
| `google_maps_link` | Places API `googleMapsUri` | Deterministic |
| `rating` / `tips` | Places API `rating` + `userRatingCount` | Deterministic |
| `tags` | Places API `types` (top 5) | Deterministic |

### Visit Duration Rules

| Category | Default Duration |
|----------|-----------------|
| Restaurant / Cafe / Bar | 45-60 min |
| Museum / Art Gallery | 90-120 min |
| Temple / Shrine | 60 min |
| Park / Garden | 90 min |
| Amusement Park | 180 min |
| Shopping Mall | 120 min |
| Other | 60 min |

---

## Integration: Full 3-Skill Pipeline

The three skills connect via JSON files. All scripts use Python 3.11+ stdlib only.

```
Explorer output (POI JSON) → Navigator --new-poi input
Navigator output (daily_itinerary[]) → Travel Planner --itinerary input
```

### Concrete example: user says 「東京加這個 https://maps.google.com/?q=teamLab」

```bash
# Step 1 — Explorer: URL → structured POI JSON
python3 <explorer-dir>/scripts/explorer.py \
  --url "https://maps.google.com/?q=teamLab+Borderless" \
  --city "Tokyo" \
  --api-key "$GOOGLE_MAPS_API_KEY" \
  --save /path/to/teamlab.json

# Step 2 — Navigator: find optimal insertion position
python3 <navigator-dir>/scripts/navigator.py insert \
  --trip "東京" \
  --new-poi /path/to/teamlab.json \
  --api-key "$GOOGLE_MAPS_API_KEY" \
  > /path/to/updated-itinerary.json

# Step 3 — Agent fills theme/meals/transport_notes in updated JSON, then:
# Travel Planner: push to Notion
python3 <travel-planner-dir>/scripts/notion_create_page.py \
  --api-key "$NOTION_API_KEY" \
  --update-page "<page_id from registry>" \
  --itinerary /path/to/updated-itinerary.json
```

### Data flow contract

| From | To | Format | Required fields |
|------|----|--------|----------------|
| Explorer | Navigator | Single POI JSON object | `name`, `opening_hours`, `visit_duration_min` (defaults to 60 if omitted) |
| Navigator | Travel Planner | `{"daily_itinerary": [...]}` | Each POI must have `name`, `time_slot` |
| Travel Planner | Notion | Full itinerary JSON | `destination`, `dates`, `daily_itinerary`, optionally `lang` |

### What each skill fills vs what the agent fills

| Field | Explorer | Navigator | Agent | Travel Planner |
|-------|----------|-----------|-------|----------------|
| `name` / `name_local` | fills from API | preserves | can override | renders |
| `lat` / `lng` | fills from API | fills if missing | — | — |
| `opening_hours` | fills from API | reads for scheduling | can override | renders |
| `visit_duration_min` | fills by category rules | reads for scheduling | can override | — |
| `time_slot` | — | fills | — | renders |
| `transit_from_prev_min` | — | fills | — | — |
| `theme` / `theme_local` | — | leaves empty | **must fill** | renders |
| `meals[].name` | — | time placeholder only | **must fill** | renders |
| `transport_notes` | — | leaves empty | **must fill** | renders |
| `lang` | — | — | **must set** (zh-TW/en/ja) | reads for UI labels |
| `budget_*` | fills from price level | preserves | can override | renders |

---

## Parallel Execution

When the user provides multiple URLs or place names at once, run separate Explorer calls **in parallel** using concurrent Bash tool calls — each invocation is independent and has no shared state. Collect all results, then pass them together to Navigator or Travel Planner.

## Error Handling

| Error | Behavior | Exit code |
|-------|----------|-----------|
| URL can't be parsed | Suggests using `--query` instead | 1 |
| Short URL redirect fails | Falls back to parsing original URL | continues |
| Places API returns no results | Prints error to stderr | 1 |
| Places API (New) not enabled | Prints activation URL to stderr | 1 |
| Page title fetch fails | Falls back to URL path parsing | continues |
| Neither `--url` nor `--query` provided | Prints usage error | 1 |
| `GOOGLE_MAPS_API_KEY` not set | Prints error to stderr | 1 |
