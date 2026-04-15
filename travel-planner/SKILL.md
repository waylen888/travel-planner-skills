---
name: travel-planner
description: "Create and update travel itineraries in Notion — from a short description to a polished page with inline databases, daily schedules, and bilingual POI details. Use this skill whenever the user wants to: create a new trip itinerary, update/modify an existing travel plan in Notion, swap out POIs, reorder days, add new stops, or re-optimize a trip. Triggers on imperative phrases that express an action intent — e.g. 'add this flight to the trip', 'swap to a different restaurant', 'change day 3', 'insert a stop', 'move this to day 2', 'plan a trip to X', 'put my itinerary in Notion', 'add a coffee shop to the afternoon', or 're-plan my trip'. Do NOT trigger on declarative/informational statements that merely record facts without requesting an action (e.g. a user noting a flight number is a memo, not a command). When the user mentions travel details (flights, hotels, transport) without clear action intent, auto-resolve incomplete information first (see 'Auto-Resolve Incomplete Travel Info' section), then present findings and ask whether they want to update the trip. Only ask the user for missing details when autonomous resolution fails."
trigger: /travel-planner
---

# /travel-planner

Create or update a travel itinerary in Notion — from a one-line description to a polished page, with the ability to revise later.

## Usage

```
/travel-planner                                # new trip — asks for destination and preferences
/travel-planner <path-to-itinerary.json>       # new trip from JSON file
/travel-planner update <notion-page-url>       # modify an existing trip page
```

## Runtime

- **Runner**: `uv run python` — auto-manages Python version and virtualenv via `pyproject.toml` in each skill directory
- **Python**: >=3.11, stdlib only (no pip dependencies)
- **Script**: `<this-skill-dir>/scripts/notion_create_page.py` — `<this-skill-dir>` is the directory where this SKILL.md lives
- **Invocation**: `cd <this-skill-dir> && uv run python scripts/notion_create_page.py [args]`
- **Output**: JSON to stdout, logs to stderr, exit code 0 on success / 1 on error
- **Temp files**: Save itinerary JSON to `~/.travel-planner/itineraries/` (the script auto-copies it there, but prefer saving directly to avoid leftover files in the working directory)

## Prerequisites

1. **NOTION_API_KEY** — a Notion integration token (starts with `ntn_` or `secret_`)
2. **NOTION_PARENT_PAGE_ID** — the Notion page ID where new trips are created as children

Check `$NOTION_API_KEY` and `$NOTION_PARENT_PAGE_ID` env vars first. If not set, ask the user.

---

## Auto-Resolve Incomplete Travel Info

When the user mentions travel details (flights, hotels, transport, destinations) without providing complete information, **proactively resolve missing details before asking the user**. Use WebSearch, WebFetch, and other available tools to fill in gaps autonomously.

### Trigger

Any mention of travel-related fragments that lack full details:
- Flight numbers without times/dates (e.g., 「CI113」「BR108」)
- Hotel names without dates or confirmation numbers
- Transport references without schedules (e.g., 「新幹線到大阪」)
- Destination mentions with partial context (e.g., 「四國加上回程機票」)

### Resolution Flow

1. **Identify what's missing** — parse the user's message to determine what info is provided vs what's needed
2. **Auto-resolve via tools** — run WebSearch / WebFetch in parallel to fill gaps:

   | Fragment type | What to search | Example query |
   |---------------|---------------|---------------|
   | Flight number | Route, schedule, duration | `"CI113 flight schedule route"` |
   | Hotel name | Location, check-in policy | `"Hotel Nikko Kochi address"` |
   | Train/bus route | Timetable, duration, cost | `"四國 JR 特急 時刻表"` |
   | Destination | Airports, transport options | `"四國 機場 交通"` |

3. **Cross-reference with existing trips** — run `--list-trips` to check if this relates to an existing trip in the registry
4. **Present findings** — show the user what was resolved and what action you propose:

   ```
   我查到了以下資訊：
   ✅ CI113：高雄 KHH → 桃園 TPE，每日 18:25-19:55（中華航空）
   ✅ 找到現有行程「四國」
   
   要我把這班回程航班加到四國行程的最後一天嗎？
   ```

5. **Only ask the user** when:
   - WebSearch returns ambiguous or conflicting results
   - Multiple trips match and can't be auto-determined
   - The info truly can't be found online (e.g., private bookings)

### Parallel execution

Run these steps concurrently when possible:
- WebSearch for flight/hotel/transport details **AND** `--list-trips` to check registry — these are independent
- Multiple WebSearch queries for different fragments — all independent

---

## Mode A: Create New Trip

### Step 1 — Gather input

The user might give you anything from a one-liner to a full JSON file:

| User gives you | What you do |
|----------------|-------------|
| `「東京五天，喜歡動漫跟咖啡」` | Generate a complete itinerary based on preferences |
| `A JSON file path` | Read and validate the JSON |
| `A list of POIs with dates` | Assemble into canonical JSON |

When generating from a description, create a rich itinerary with:
- Sensible day grouping by geographic proximity
- A mix of the requested themes + local essentials
- Bilingual names (Traditional Chinese + local language)
- Budget estimates in both local currency and TWD
- Realistic time slots and opening hours
- Transport notes between POIs
- Packing checklist and travel tips

### Step 2 — Build the canonical JSON

Assemble the itinerary into this format. Save it as a `.json` file so the user can re-use or edit it later.

```json
{
  "lang": "zh-TW",
  "destination": {
    "city": "Tokyo",
    "city_local": "東京",
    "country": "Japan",
    "country_local": "日本"
  },
  "dates": {
    "start": "2025-03-15",
    "end": "2025-03-19"
  },
  "cover_query": "tokyo skyline",
  "travelers": 2,
  "daily_itinerary": [
    {
      "day": 1,
      "date": "2025-03-15",
      "theme": "Akihabara & Anime Culture",
      "theme_local": "秋葉原與動漫文化",
      "pois": [
        {
          "name": "Akihabara Electric Town",
          "name_local": "秋葉原電気街",
          "category": "shopping",
          "time_slot": "10:00-13:00",
          "budget_jpy": 5000,
          "budget_twd": 1100,
          "opening_hours": "10:00-21:00 daily",
          "description": "The heart of otaku culture with multi-story anime shops.",
          "description_local": "御宅族文化中心，多層動漫商店林立。",
          "google_maps_link": "https://maps.google.com/?q=Akihabara",
          "tags": ["anime", "shopping", "iconic"],
          "tips": "Visit on weekdays to avoid crowds."
        }
      ],
      "meals": [
        {
          "type": "lunch",
          "name": "Ichiran Ramen Akihabara",
          "name_local": "一蘭拉麵 秋葉原店",
          "budget_jpy": 1500,
          "budget_twd": 330,
          "google_maps_link": "https://maps.google.com/?q=Ichiran+Akihabara"
        }
      ],
      "transport_notes": "JR Yamanote Line to Akihabara Station"
    }
  ],
  "packing_checklist": [
    "Passport / 護照",
    "JR Pass / JR 周遊券"
  ],
  "travel_tips": [
    "IC card (Suica/Pasmo) saves time on transit / IC 卡大幅節省交通時間"
  ]
}
```

Field notes:
- `lang` = UI language for Notion page labels: `zh-TW` (default), `en`, `ja`. Set based on the user's conversation language.
- `*_local` = Traditional Chinese (or local language for POI names)
- `budget_twd` = Taiwan Dollar equivalent — always include
- `cover_query` = Unsplash search term for cover image
- Omit budget fields if unknown rather than using 0

### Step 3 — Push to Notion

```bash
python3 <skill-dir>/scripts/notion_create_page.py \
  --api-key "$NOTION_API_KEY" \
  --parent-page-id "$NOTION_PARENT_PAGE_ID" \
  --itinerary <path-to-itinerary.json>
```

The script creates:
1. A page with cover image, emoji icon, and bilingual title
2. Trip Overview callout (destination, dates, travelers)
3. Travel Tips callout blocks
4. An inline database (Date, POI, Category, Time, Budget, Status, Location, Tags)
5. Database rows for every POI and meal
6. Daily H2 sections with POI details, budgets, maps links
7. Packing checklist as to-do blocks

The script returns JSON: `{ "page_url", "page_id", "database_id", "itinerary_path" }`.

**Important:** The script saves a metadata file at `~/.travel-planner/<page_id>.meta.json` containing the page_id, database_id, and itinerary JSON path. This is how update mode knows where things are.

### Step 4 — Report to user

Return:
- Notion page URL (clickable)
- Summary (days, POIs, meals)
- Path to the saved JSON (in case they want to edit it manually)
- Remind them: 「之後想修改行程，只要說『幫我改第三天』或『換掉這個餐廳』就好」

---

## Mode B: Update Existing Trip

This is the re-planning flow. The user has an existing Notion trip page and wants to modify it.

### Step 1 — Identify what to change

The user might say:
- 「把第三天的景點換掉」→ replace Day 3 POIs
- 「下午加一個咖啡廳」→ add a POI to a specific day/time
- 「把淺草寺移到第二天」→ move a POI between days
- 「刪掉行李清單裡的 JR Pass」→ remove a checklist item
- 「重新安排所有景點的順序」→ full re-optimize
- 「多加一天」→ extend the trip

### Step 2 — Read current state

```bash
python3 <skill-dir>/scripts/notion_create_page.py \
  --api-key "$NOTION_API_KEY" \
  --read-page <page_id>
```

This reads the existing Notion page and database, returning the current itinerary as JSON. Compare this with the user's requested changes.

If the metadata file exists at `~/.travel-planner/<page_id>.meta.json`, also load the original itinerary JSON — it may be more complete than what Notion stores (e.g., tips, transport notes).

### Step 3 — Apply changes to itinerary JSON

Modify the itinerary JSON based on the user's request. The key principle: **change only what was requested, preserve everything else.**

For each change type:

| Change | What to modify in JSON |
|--------|----------------------|
| Swap a POI | Replace the POI object in `daily_itinerary[day].pois[index]` |
| Add a POI | Insert into `pois[]` at the right time slot, shift others |
| Remove a POI | Delete from `pois[]` |
| Move a POI to another day | Remove from source day, add to target day |
| Change time slot | Update `time_slot` field |
| Add/remove a day | Add/remove entry in `daily_itinerary[]`, renumber `day` fields |
| Edit checklist | Modify `packing_checklist[]` |
| Full re-optimize | Regenerate `daily_itinerary` while keeping the same POI pool |

After modifying, show the user a summary of changes before pushing:
```
變更摘要：
- Day 3: 移除「東京鐵塔」，新增「teamLab Borderless」(14:00-17:00)
- Day 3: 午餐從「松屋」改為「鳥貴族」
確認推送到 Notion？
```

### Step 4 — Push updates to Notion

```bash
python3 <skill-dir>/scripts/notion_create_page.py \
  --api-key "$NOTION_API_KEY" \
  --update-page <page_id> \
  --itinerary <path-to-updated-itinerary.json>
```

The update script:
1. Reads the current page blocks and database rows
2. Deletes blocks for changed days (by matching H2 headings)
3. Appends new blocks for the updated days in the correct position
4. Updates/adds/removes database rows to match the new itinerary
5. Updates the Trip Overview callout if dates or destination changed
6. Preserves unchanged sections entirely

### Step 5 — Report changes

Return:
- Notion page URL
- What was changed (added/removed/moved POIs)
- Updated JSON path

---

## Notion Page Structure

```
🗺️ [City_local] [City] — [start] ~ [end] Travel Itinerary
├── Cover: Unsplash image
├── 📋 Trip Overview (callout, blue background)
│   ├── Destination / 目的地
│   ├── Dates / 日期
│   └── Travelers / 旅伴人數
├── 💡 Travel Tips (callout blocks, yellow background)
├── ── divider ──
├── 📍 Itinerary Database (inline)
│   │  Date | POI Name | Category | Time | Budget | Status | Location
│   ├── row per POI and meal...
├── ── divider ──
├── 📅 Day 1 — Theme / 主題 (H2)
│   ├── 🚃 Transport note (callout, gray)
│   ├── 🕐 10:00-13:00  POI Name / 當地名 (H3)
│   │   ├── description (bilingual)
│   │   ├── 💰 Budget: ¥5,000 / NT$1,100
│   │   ├── 🕐 Hours: 10:00-21:00
│   │   ├── ✨ Tip (callout, yellow)
│   │   └── 📍 Google Maps (bookmark)
│   ├── 🍽️ Meal (bulleted, bold)
│   └── ...
├── 📅 Day 2 — ... (H2)
├── ── divider ──
└── ✅ Packing Checklist / 行李清單
    ├── ☐ Passport / 護照
    └── ...
```

## Error Handling

- **401**: API key invalid or integration not shared with page → tell user to check both
- **400 "Could not find page"**: wrong page ID or no access → guide user to share page with integration
- **Unsplash fail**: skip cover, continue
- **100-block limit**: script auto-batches with append-children endpoint
- **Update conflicts**: if the page was manually edited in Notion and structure is unrecognizable, fall back to full rebuild with user confirmation

## User Data Directory

All user data is stored under `~/.travel-planner/`:

```
~/.travel-planner/
├── registry.json              # Trip index — all trips with page_id, itinerary path, city
├── geocache.json              # Geocoding cache (shared with Navigator)
├── itineraries/               # Itinerary JSON files (one per trip)
│   ├── tokyo-may-2026.json
│   └── shikoku-jun-2026.json
└── <page_id>.meta.json        # Notion page metadata (page_id, database_id, itinerary path)
```

This directory is **independent of skill installation location** — skills read/write here regardless of where they are installed.

## Trip Registry

Every trip created or updated is auto-registered at `~/.travel-planner/registry.json`. This enables multi-trip management — Navigator and other agents can look up trips by city name instead of remembering file paths.

```bash
# List all registered trips
python3 <skill-dir>/scripts/notion_create_page.py --list-trips
```

Output:
```json
{
  "trips": [
    {
      "name": "東京 Tokyo 2026-05-15",
      "city": "Tokyo",
      "city_local": "東京",
      "page_id": "...",
      "page_url": "https://notion.so/...",
      "itinerary_path": "/path/to/tokyo-may-2026.json",
      "days": 5,
      "start_date": "2026-05-15",
      "updated": "2026-04-15"
    }
  ]
}
```

When updating a trip, use the registry to resolve page_id and itinerary path:
1. Run `--list-trips` to find the trip
2. Use `page_id` for `--update-page` and `itinerary_path` for `--itinerary`

## Integration with Other Skills

This skill accepts data from:
- **Explorer Skill** → POI JSON feeds into `daily_itinerary[].pois[]`
- **Navigator Skill** → optimized `daily_itinerary[]` with time slots, coordinates, and transit times

The canonical JSON is the contract between skills.

### Using Navigator before Notion push

When the user has an unordered list of POIs and wants them optimized:

1. Save POIs as `pois.json` (array of POI objects with `visit_duration_min`)
2. Run Navigator to cluster + order:
   ```bash
   python3 <navigator-skill-dir>/scripts/navigator.py optimize \
     --pois pois.json --city "Tokyo" --days 5 --start-date 2026-05-15 > optimized.json
   ```
3. Claude reads `optimized.json`, fills in `theme`, `theme_local`, picks specific restaurants for `meals`, writes `transport_notes`
4. Claude wraps with `destination`, `dates`, `packing_checklist`, `travel_tips` → full itinerary JSON
5. Push to Notion with travel-planner

### Adding a POI to existing trip (full pipeline)

When the user pastes a link or says a place name:

**Step 0 — Resolve which trip:**
Before running the pipeline, determine which trip the POI should be added to:

1. Run `--list-trips` to get all registered trips
2. If the user specified a trip (e.g., 「東京加這個」) → use that trip
3. If only **one trip** exists in registry → auto-select it
4. If **multiple trips** exist and user didn't specify → **ask the user** which trip to add to, showing the available trips list
5. If **no trips** exist → ask the user to create one first with `/travel-planner`

**Step 1 — Explorer** extracts structured POI data:
   ```bash
   python3 <explorer-skill-dir>/scripts/explorer.py \
     --url "https://maps.google.com/?q=teamLab" --city "Tokyo" \
     --save /tmp/new_poi.json
   ```
2. **Navigator** finds the optimal insertion position:
   ```bash
   python3 <navigator-skill-dir>/scripts/navigator.py insert \
     --trip "東京" --new-poi /tmp/new_poi.json > updated.json
   ```
3. Claude reviews `_navigator_insert_result` (which day, disruption score), updates meals/transport
4. **Travel Planner** pushes to Notion with `--update-page`

This pipeline is fully deterministic — no model reasoning needed for POI data extraction, geocoding, or route optimization.

### Parallel execution guidelines

When multiple independent operations exist, run them in parallel using concurrent Bash tool calls:

| Scenario | What to parallelize |
|----------|-------------------|
| User pastes multiple URLs | Run multiple Explorer calls simultaneously, one per URL |
| Adding a POI to existing trip | Run Explorer (extract POI) and `--read-page` (read current Notion state) at the same time |
| Creating a new trip from scratch | Run `--list-trips` (check registry) while generating the itinerary JSON |
| Updating trip + forwarding luggage info | Run `--update-page` and any unrelated lookups concurrently |

**Do NOT parallelize** steps with dependencies:
- Explorer must finish before Navigator (Navigator needs POI data)
- Navigator must finish before Travel Planner update (need optimized itinerary)
- `save_metadata` is handled internally by the script — no manual parallelization needed
