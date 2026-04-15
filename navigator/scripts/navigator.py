#!/usr/bin/env python3
"""
Navigator Skill — Optimize travel itinerary routing and scheduling.

Clusters POIs by geographic proximity, orders them within each day using
nearest-neighbor greedy, and assigns time slots respecting opening hours
and real transit times from Google Maps.

Usage:
    python3 navigator.py optimize --pois pois.json --city Tokyo --days 5
    python3 navigator.py insert  --itinerary trip.json --new-poi poi.json --city Tokyo
"""

import argparse
import json
import math
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GOOGLE_GEOCODING_URL = "https://maps.googleapis.com/maps/api/geocode/json"
GOOGLE_DISTANCE_MATRIX_URL = "https://maps.googleapis.com/maps/api/distancematrix/json"
GEOCACHE_PATH = os.path.expanduser("~/.travel-planner/geocache.json")
REGISTRY_PATH = os.path.expanduser("~/.travel-planner/registry.json")

DEFAULT_DAY_START = "09:00"
DEFAULT_DAY_END = "19:00"
DEFAULT_VISIT_DURATION_MIN = 60
MEAL_DURATION_MIN = 60
LUNCH_WINDOW = (720, 780)   # 12:00-13:00
DINNER_WINDOW = (1080, 1140) # 18:00-19:00

# Fallback: assume 30 min per 5 km when Distance Matrix fails
HAVERSINE_TRANSIT_FACTOR = 6.0  # min per km

# ---------------------------------------------------------------------------
# Time Utilities
# ---------------------------------------------------------------------------

def parse_time(s):
    """Parse "HH:MM" to minutes since midnight. Returns None on failure."""
    s = s.strip()
    if not s:
        return None
    parts = s.split(":")
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]) * 60 + int(parts[1])
    except ValueError:
        return None


def format_time(minutes):
    """Convert minutes since midnight to "HH:MM"."""
    h = minutes // 60
    m = minutes % 60
    return f"{h:02d}:{m:02d}"


def parse_opening_hours(hours_str):
    """
    Parse opening hours string to (open_min, close_min).
    Handles: "06:00-17:00 daily", "10:00-21:00", "24h", "sunrise to sunset",
             "08:00-17:30 (Apr-Sep)", "closed Monday" (ignored — treated as open).
    Returns (0, 1440) as fallback.
    """
    if not hours_str:
        return (0, 1440)
    s = hours_str.strip().lower()
    if "24h" in s:
        return (0, 1440)
    if "sunrise" in s:
        return (360, 1080)  # 06:00-18:00 as safe default

    # Extract first HH:MM-HH:MM pattern
    import re
    m = re.search(r"(\d{1,2}:\d{2})\s*[-–—~]\s*(\d{1,2}:\d{2})", s)
    if m:
        open_t = parse_time(m.group(1))
        close_t = parse_time(m.group(2))
        if open_t is not None and close_t is not None:
            return (open_t, close_t)
    return (0, 1440)


def is_open_at(opening_hours_str, time_min):
    """Check if a POI is open at the given time (minutes since midnight)."""
    open_t, close_t = parse_opening_hours(opening_hours_str)
    return open_t <= time_min < close_t


def time_slot_str(start_min, end_min):
    """Format a time slot as "HH:MM-HH:MM"."""
    return f"{format_time(start_min)}-{format_time(end_min)}"


def get_visit_duration(poi):
    """Get visit duration in minutes from POI, with fallback."""
    return poi.get("visit_duration_min") or DEFAULT_VISIT_DURATION_MIN

# ---------------------------------------------------------------------------
# Haversine
# ---------------------------------------------------------------------------

def haversine(lat1, lng1, lat2, lng2):
    """Great-circle distance in km between two lat/lng points."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlng / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def haversine_transit_min(lat1, lng1, lat2, lng2):
    """Estimate transit minutes from haversine distance."""
    km = haversine(lat1, lng1, lat2, lng2)
    return max(5, int(math.ceil(km * HAVERSINE_TRANSIT_FACTOR)))

# ---------------------------------------------------------------------------
# Google Maps API Helpers
# ---------------------------------------------------------------------------

def google_api_request(url, params):
    """Make a GET request to a Google Maps API endpoint."""
    query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    full_url = f"{url}?{query}"
    try:
        req = urllib.request.Request(full_url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"Google API error {e.code}: {body}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Google API request failed: {e}", file=sys.stderr)
        return None


def geocode_single(name, city, api_key):
    """Geocode a single POI name + city. Returns (lat, lng) or None."""
    query = f"{name}, {city}"
    data = google_api_request(GOOGLE_GEOCODING_URL, {
        "address": query,
        "key": api_key
    })
    if not data or data.get("status") != "OK" or not data.get("results"):
        print(f"  Geocoding failed for '{query}': {data.get('status') if data else 'no response'}", file=sys.stderr)
        return None
    loc = data["results"][0]["geometry"]["location"]
    return (loc["lat"], loc["lng"])


def distance_matrix_batch(origins, destinations, api_key):
    """
    Call Google Distance Matrix API with transit mode.
    origins/destinations: list of (lat, lng) tuples.
    Returns NxM matrix of transit minutes. None for failed elements.
    API limit: 25 origins x 25 destinations per request.
    """
    if not origins or not destinations:
        return []

    def format_latlngs(points):
        return "|".join(f"{lat},{lng}" for lat, lng in points)

    results = [[None] * len(destinations) for _ in range(len(origins))]

    # Batch in chunks of 25
    for o_start in range(0, len(origins), 25):
        o_end = min(o_start + 25, len(origins))
        o_chunk = origins[o_start:o_end]
        for d_start in range(0, len(destinations), 25):
            d_end = min(d_start + 25, len(destinations))
            d_chunk = destinations[d_start:d_end]

            data = google_api_request(GOOGLE_DISTANCE_MATRIX_URL, {
                "origins": format_latlngs(o_chunk),
                "destinations": format_latlngs(d_chunk),
                "mode": "transit",
                "key": api_key
            })

            if not data or data.get("status") != "OK":
                continue

            for i, row in enumerate(data.get("rows", [])):
                for j, elem in enumerate(row.get("elements", [])):
                    if elem.get("status") == "OK":
                        secs = elem["duration"]["value"]
                        results[o_start + i][d_start + j] = int(math.ceil(secs / 60))

    return results

# ---------------------------------------------------------------------------
# Geocache
# ---------------------------------------------------------------------------

def load_geocache():
    """Load geocache from disk. Returns dict."""
    try:
        with open(GEOCACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_geocache(cache):
    """Atomic write geocache to disk."""
    os.makedirs(os.path.dirname(GEOCACHE_PATH), exist_ok=True)
    tmp = GEOCACHE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    os.rename(tmp, GEOCACHE_PATH)


def geocode_all(pois, city, api_key):
    """
    Batch geocode all POIs. Returns {poi_name: (lat, lng)}.
    Uses cache first, only calls API for misses.
    """
    cache = load_geocache()
    coords = {}
    misses = []

    for poi in pois:
        name = poi["name"]
        key = f"{name}|{city}"
        if key in cache:
            c = cache[key]
            coords[name] = (c["lat"], c["lng"])
        else:
            misses.append(poi)

    if misses:
        print(f"Geocoding {len(misses)} POIs (cache hits: {len(pois) - len(misses)})...", file=sys.stderr)
        for poi in misses:
            name = poi["name"]
            result = geocode_single(name, city, api_key)
            if result:
                coords[name] = result
                cache[f"{name}|{city}"] = {
                    "lat": result[0], "lng": result[1],
                    "ts": datetime.now().strftime("%Y-%m-%d")
                }
            else:
                # Try with local name
                local = poi.get("name_local", "")
                if local:
                    result = geocode_single(local, city, api_key)
                    if result:
                        coords[name] = result
                        cache[f"{name}|{city}"] = {
                            "lat": result[0], "lng": result[1],
                            "ts": datetime.now().strftime("%Y-%m-%d")
                        }
        save_geocache(cache)
    else:
        print(f"All {len(pois)} POIs found in geocache.", file=sys.stderr)

    return coords

# ---------------------------------------------------------------------------
# Clustering (Haversine-based, for optimize mode)
# ---------------------------------------------------------------------------

def cluster_pois(pois, coords, num_days):
    """
    Assign POIs to days by geographic proximity.
    Seed-based greedy: pick farthest-apart POIs as seeds, assign rest to nearest.
    """
    if num_days >= len(pois):
        # Each POI gets its own day (or fewer POIs than days)
        result = [[poi] for poi in pois]
        while len(result) < num_days:
            result.append([])
        return result

    # Filter POIs that have coordinates
    valid_pois = [p for p in pois if p["name"] in coords]
    no_coord = [p for p in pois if p["name"] not in coords]

    if not valid_pois:
        # No coordinates — just split evenly
        chunk_size = math.ceil(len(pois) / num_days)
        return [pois[i:i + chunk_size] for i in range(0, len(pois), chunk_size)]

    # Compute centroid
    lats = [coords[p["name"]][0] for p in valid_pois]
    lngs = [coords[p["name"]][1] for p in valid_pois]
    centroid = (sum(lats) / len(lats), sum(lngs) / len(lngs))

    # Pick seeds: first seed = farthest from centroid
    seeds = []
    used = set()

    # Seed 1: farthest from centroid
    best_idx = max(range(len(valid_pois)),
                   key=lambda i: haversine(centroid[0], centroid[1],
                                           coords[valid_pois[i]["name"]][0],
                                           coords[valid_pois[i]["name"]][1]))
    seeds.append(best_idx)
    used.add(best_idx)

    # Subsequent seeds: farthest from all existing seeds
    for _ in range(1, num_days):
        best_dist = -1
        best_j = None
        for j in range(len(valid_pois)):
            if j in used:
                continue
            min_dist_to_seeds = min(
                haversine(coords[valid_pois[j]["name"]][0], coords[valid_pois[j]["name"]][1],
                          coords[valid_pois[seeds[s]]["name"]][0], coords[valid_pois[seeds[s]]["name"]][1])
                for s in range(len(seeds))
            )
            if min_dist_to_seeds > best_dist:
                best_dist = min_dist_to_seeds
                best_j = j
        if best_j is not None:
            seeds.append(best_j)
            used.add(best_j)

    # Assign POIs to nearest seed
    capacity = math.ceil(len(valid_pois) / num_days) + 1
    clusters = [[] for _ in range(num_days)]

    # Place seeds first
    for day_idx, seed_idx in enumerate(seeds):
        clusters[day_idx].append(valid_pois[seed_idx])

    # Assign remaining
    remaining = [(i, p) for i, p in enumerate(valid_pois) if i not in used]
    # Sort by distance to nearest seed (farthest first — assign hard-to-place POIs first)
    remaining.sort(key=lambda ip: min(
        haversine(coords[ip[1]["name"]][0], coords[ip[1]["name"]][1],
                  coords[valid_pois[seeds[s]]["name"]][0], coords[valid_pois[seeds[s]]["name"]][1])
        for s in range(len(seeds))
    ), reverse=True)

    for _, poi in remaining:
        c = coords[poi["name"]]
        # Find nearest seed that still has capacity
        best_day = None
        best_dist = float("inf")
        for day_idx, seed_idx in enumerate(seeds):
            if len(clusters[day_idx]) >= capacity:
                continue
            sc = coords[valid_pois[seed_idx]["name"]]
            d = haversine(c[0], c[1], sc[0], sc[1])
            if d < best_dist:
                best_dist = d
                best_day = day_idx
        if best_day is not None:
            clusters[best_day].append(poi)
        else:
            # All at capacity — add to smallest cluster
            smallest = min(range(num_days), key=lambda d: len(clusters[d]))
            clusters[smallest].append(poi)

    # Distribute POIs without coordinates evenly
    for i, poi in enumerate(no_coord):
        clusters[i % num_days].append(poi)

    return clusters

# ---------------------------------------------------------------------------
# Transit Matrix Builder
# ---------------------------------------------------------------------------

def build_transit_matrix(pois, coords, api_key, mock_data=None):
    """
    Build a transit time matrix for a set of POIs.
    Returns dict: (name_a, name_b) -> minutes.
    """
    matrix = {}
    valid = [p for p in pois if p["name"] in coords]

    if not valid:
        return matrix

    names = [p["name"] for p in valid]
    points = [coords[n] for n in names]

    if mock_data:
        # Use mock distances
        for i, a in enumerate(names):
            for j, b in enumerate(names):
                if i != j:
                    key = f"{a}|{b}"
                    if key in mock_data:
                        matrix[(a, b)] = mock_data[key]
                    else:
                        matrix[(a, b)] = haversine_transit_min(
                            coords[a][0], coords[a][1], coords[b][0], coords[b][1])
        return matrix

    # Call Distance Matrix API
    dm = distance_matrix_batch(points, points, api_key)

    for i, a in enumerate(names):
        for j, b in enumerate(names):
            if i != j:
                val = dm[i][j] if dm and i < len(dm) and j < len(dm[i]) else None
                if val is not None:
                    matrix[(a, b)] = val
                else:
                    # Fallback to haversine estimate
                    matrix[(a, b)] = haversine_transit_min(
                        coords[a][0], coords[a][1], coords[b][0], coords[b][1])

    return matrix

# ---------------------------------------------------------------------------
# Day Ordering (Greedy Nearest-Neighbor)
# ---------------------------------------------------------------------------

def order_day(pois, coords, transit_matrix, day_start_min, day_end_min):
    """
    Order POIs within a single day using greedy nearest-neighbor.
    Assigns time_slot to each POI.
    Returns (ordered_pois, unscheduled_pois).
    """
    if not pois:
        return [], []

    current_time = day_start_min
    ordered = []
    remaining = list(pois)
    unscheduled = []
    prev_name = None

    while remaining:
        best_poi = None
        best_cost = float("inf")
        best_start = None

        for poi in remaining:
            name = poi["name"]
            duration = get_visit_duration(poi)
            open_t, close_t = parse_opening_hours(poi.get("opening_hours", ""))

            # Transit time from previous POI
            transit = 0
            if prev_name and (prev_name, name) in transit_matrix:
                transit = transit_matrix[(prev_name, name)]
            elif prev_name and name in coords and prev_name in coords:
                transit = haversine_transit_min(
                    coords[prev_name][0], coords[prev_name][1],
                    coords[name][0], coords[name][1])

            arrive = current_time + transit
            # Wait for opening if needed
            start = max(arrive, open_t)
            end = start + duration

            # Check constraints
            if end > day_end_min:
                continue  # Doesn't fit in remaining day
            if start >= close_t:
                continue  # Opens too late or already closed

            # Cost = transit time + wait time
            cost = transit + max(0, open_t - arrive)
            if cost < best_cost:
                best_cost = cost
                best_poi = poi
                best_start = start

        if best_poi is None:
            # No more POIs can fit — move remaining to unscheduled
            unscheduled.extend(remaining)
            break

        duration = get_visit_duration(best_poi)
        end = best_start + duration

        # Add transit info
        transit_min = 0
        if prev_name and (prev_name, best_poi["name"]) in transit_matrix:
            transit_min = transit_matrix[(prev_name, best_poi["name"])]

        # Remove original from remaining BEFORE copying
        remaining.remove(best_poi)

        best_poi = dict(best_poi)  # copy for mutation
        best_poi["time_slot"] = time_slot_str(best_start, end)
        best_poi["transit_from_prev_min"] = transit_min
        if best_poi["name"] in coords:
            best_poi["lat"] = coords[best_poi["name"]][0]
            best_poi["lng"] = coords[best_poi["name"]][1]

        ordered.append(best_poi)
        current_time = end
        prev_name = best_poi["name"]

    return ordered, unscheduled


# ---------------------------------------------------------------------------
# Meal Slot Insertion
# ---------------------------------------------------------------------------

def insert_meal_slots(ordered_pois, day_start_min, day_end_min):
    """
    Insert placeholder meal breaks where gaps overlap lunch/dinner windows.
    Returns list of meal dicts with time_slot.
    """
    meals = []

    def check_window(window_start, window_end, label, meal_type):
        """Check if there's room for a meal in the given window."""
        # Find what's happening during this window
        for poi in ordered_pois:
            ts = poi.get("time_slot", "")
            if "-" in ts:
                parts = ts.split("-")
                ps = parse_time(parts[0])
                pe = parse_time(parts[1])
                if ps is not None and pe is not None:
                    # POI overlaps meal window entirely
                    if ps <= window_start and pe >= window_end:
                        return
        # Find the best gap for the meal
        best_start = window_start
        meals.append({
            "type": meal_type,
            "time_slot": time_slot_str(best_start, best_start + MEAL_DURATION_MIN),
            "name": "",
            "name_local": ""
        })

    check_window(LUNCH_WINDOW[0], LUNCH_WINDOW[1], "Lunch Break", "lunch")
    check_window(DINNER_WINDOW[0], DINNER_WINDOW[1], "Dinner Break", "dinner")

    return meals

# ---------------------------------------------------------------------------
# Optimize Orchestrator
# ---------------------------------------------------------------------------

def optimize(pois, num_days, city, api_key, day_start="09:00", day_end="19:00",
             start_date=None, mock_data=None):
    """
    Main optimize: cluster POIs into days, order within each day.
    Returns { "daily_itinerary": [...], "_unscheduled": [...] }
    """
    day_start_min = parse_time(day_start) or 540
    day_end_min = parse_time(day_end) or 1140

    # Step 1: Geocode all POIs
    coords = geocode_all(pois, city, api_key)
    geocoded_count = len(coords)
    print(f"Geocoded {geocoded_count}/{len(pois)} POIs.", file=sys.stderr)

    # Step 2: Cluster POIs into days
    clusters = cluster_pois(pois, coords, num_days)
    print(f"Clustered into {len(clusters)} days: {[len(c) for c in clusters]}", file=sys.stderr)

    # Step 3: Order each day
    daily_itinerary = []
    all_unscheduled = []

    for day_idx, day_pois in enumerate(clusters):
        if not day_pois:
            # Empty day
            date_str = ""
            if start_date:
                d = datetime.strptime(start_date, "%Y-%m-%d") + timedelta(days=day_idx)
                date_str = d.strftime("%Y-%m-%d")
            daily_itinerary.append({
                "day": day_idx + 1,
                "date": date_str,
                "theme": "",
                "theme_local": "",
                "pois": [],
                "meals": [],
                "transport_notes": ""
            })
            continue

        # Build transit matrix for this day's POIs
        print(f"Day {day_idx + 1}: computing transit for {len(day_pois)} POIs...", file=sys.stderr)
        transit = build_transit_matrix(day_pois, coords, api_key, mock_data)

        # Order by greedy nearest-neighbor
        ordered, unsched = order_day(day_pois, coords, transit, day_start_min, day_end_min)
        all_unscheduled.extend(unsched)

        # Insert meal slots
        meals = insert_meal_slots(ordered, day_start_min, day_end_min)

        # Compute date
        date_str = ""
        if start_date:
            d = datetime.strptime(start_date, "%Y-%m-%d") + timedelta(days=day_idx)
            date_str = d.strftime("%Y-%m-%d")

        daily_itinerary.append({
            "day": day_idx + 1,
            "date": date_str,
            "theme": "",
            "theme_local": "",
            "pois": ordered,
            "meals": meals,
            "transport_notes": ""
        })

    result = {"daily_itinerary": daily_itinerary}
    if all_unscheduled:
        result["_unscheduled"] = [{
            "name": p["name"],
            "name_local": p.get("name_local", ""),
            "reason": "Could not fit within day time budget"
        } for p in all_unscheduled]
        print(f"Warning: {len(all_unscheduled)} POIs could not be scheduled.", file=sys.stderr)

    return result

# ---------------------------------------------------------------------------
# Insert POI into Existing Itinerary
# ---------------------------------------------------------------------------

def insert_poi(daily_itinerary, new_poi, city, api_key,
               day_start="09:00", day_end="19:00", mock_data=None):
    """
    Insert a single POI into an existing itinerary at the optimal position.
    Returns updated daily_itinerary + _navigator_insert_result metadata.
    """
    day_start_min = parse_time(day_start) or 540
    day_end_min = parse_time(day_end) or 1140
    new_duration = get_visit_duration(new_poi)
    new_open, new_close = parse_opening_hours(new_poi.get("opening_hours", ""))

    # Collect all existing POIs for geocoding
    all_pois = [new_poi]
    for day in daily_itinerary:
        all_pois.extend(day.get("pois", []))

    coords = geocode_all(all_pois, city, api_key)

    if new_poi["name"] not in coords:
        print(f"Error: Could not geocode new POI '{new_poi['name']}'", file=sys.stderr)
        return {
            "daily_itinerary": daily_itinerary,
            "_navigator_insert_result": {
                "success": False,
                "reason": "Geocoding failed for new POI"
            }
        }

    best_day = None
    best_pos = None
    best_score = float("inf")

    for day_idx, day in enumerate(daily_itinerary):
        pois = day.get("pois", [])

        # Build transit matrix for this day's POIs + new POI
        day_pois_plus = pois + [new_poi]
        transit = build_transit_matrix(day_pois_plus, coords, api_key, mock_data)

        # Try each insertion position
        for pos in range(len(pois) + 1):
            prev_name = pois[pos - 1]["name"] if pos > 0 else None
            next_name = pois[pos]["name"] if pos < len(pois) else None
            new_name = new_poi["name"]

            # Transit: prev -> new
            t_prev_new = 0
            if prev_name and (prev_name, new_name) in transit:
                t_prev_new = transit[(prev_name, new_name)]

            # Transit: new -> next
            t_new_next = 0
            if next_name and (new_name, next_name) in transit:
                t_new_next = transit[(new_name, next_name)]

            # Old transit: prev -> next (what we're replacing)
            t_prev_next = 0
            if prev_name and next_name and (prev_name, next_name) in transit:
                t_prev_next = transit[(prev_name, next_name)]

            # Calculate arrival time at new POI
            if prev_name and pos > 0:
                prev_ts = pois[pos - 1].get("time_slot", "")
                if "-" in prev_ts:
                    prev_end = parse_time(prev_ts.split("-")[1])
                    if prev_end is not None:
                        arrive = prev_end + t_prev_new
                    else:
                        continue
                else:
                    continue
            else:
                arrive = day_start_min

            start = max(arrive, new_open)
            end = start + new_duration

            # Check constraints
            if start >= new_close:
                continue  # POI won't be open
            if end > day_end_min:
                continue  # Exceeds day budget

            # Check it doesn't overlap with next POI's time
            if next_name and pos < len(pois):
                next_ts = pois[pos].get("time_slot", "")
                if "-" in next_ts:
                    next_start = parse_time(next_ts.split("-")[0])
                    if next_start is not None and end + t_new_next > next_start:
                        # Would need to shift downstream — compute shift cost
                        shift_needed = (end + t_new_next) - next_start
                    else:
                        shift_needed = 0
                else:
                    shift_needed = 0
            else:
                shift_needed = 0

            # Disruption score: added transit + downstream shift
            added_transit = t_prev_new + t_new_next - t_prev_next
            score = added_transit + shift_needed * 2  # Penalize shifts more

            if score < best_score:
                best_score = score
                best_day = day_idx
                best_pos = pos

    if best_day is None:
        return {
            "daily_itinerary": daily_itinerary,
            "_unscheduled": [{
                "name": new_poi["name"],
                "name_local": new_poi.get("name_local", ""),
                "reason": "Could not fit in any day"
            }],
            "_navigator_insert_result": {
                "success": False,
                "reason": "No feasible insertion position found"
            }
        }

    # Insert and recompute time slots for the affected day
    day = daily_itinerary[best_day]
    pois = list(day.get("pois", []))

    # Enrich new POI
    enriched_new = dict(new_poi)
    if new_poi["name"] in coords:
        enriched_new["lat"] = coords[new_poi["name"]][0]
        enriched_new["lng"] = coords[new_poi["name"]][1]

    pois.insert(best_pos, enriched_new)

    # Recompute time slots for the whole day
    day_pois_for_transit = pois
    transit = build_transit_matrix(day_pois_for_transit, coords, api_key, mock_data)

    current_time = day_start_min
    prev_name = None
    for i, poi in enumerate(pois):
        name = poi["name"]
        duration = get_visit_duration(poi)
        open_t, close_t = parse_opening_hours(poi.get("opening_hours", ""))

        t = 0
        if prev_name and (prev_name, name) in transit:
            t = transit[(prev_name, name)]

        arrive = current_time + t
        start = max(arrive, open_t)
        end = start + duration

        pois[i] = dict(poi)
        pois[i]["time_slot"] = time_slot_str(start, end)
        pois[i]["transit_from_prev_min"] = t
        if name in coords:
            pois[i]["lat"] = coords[name][0]
            pois[i]["lng"] = coords[name][1]

        current_time = end
        prev_name = name

    # Update the day
    daily_itinerary[best_day] = dict(day)
    daily_itinerary[best_day]["pois"] = pois
    daily_itinerary[best_day]["meals"] = insert_meal_slots(pois, day_start_min, day_end_min)

    return {
        "daily_itinerary": daily_itinerary,
        "_navigator_insert_result": {
            "success": True,
            "inserted_day": best_day + 1,
            "inserted_position": best_pos + 1,
            "disruption_minutes": int(best_score)
        }
    }

# ---------------------------------------------------------------------------
# Input Helpers
# ---------------------------------------------------------------------------

def load_pois_from_file(path):
    """
    Load POIs from a JSON file. Accepts either:
    - A bare array of POI objects: [{...}, ...]
    - A full itinerary JSON (extracts all POIs from daily_itinerary)
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        return data

    if isinstance(data, dict) and "daily_itinerary" in data:
        pois = []
        for day in data["daily_itinerary"]:
            pois.extend(day.get("pois", []))
        return pois

    print(f"Error: Unrecognized JSON format in {path}", file=sys.stderr)
    sys.exit(1)


def load_itinerary_from_file(path):
    """Load full itinerary JSON and return the daily_itinerary array."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict) and "daily_itinerary" in data:
        return data["daily_itinerary"]

    print(f"Error: No daily_itinerary found in {path}", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Trip Registry Lookup
# ---------------------------------------------------------------------------

def load_registry():
    """Load the trip registry."""
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"trips": []}


def find_trip(query):
    """
    Find a trip by fuzzy matching on city, city_local, or name.
    Returns the matching trip entry or None.
    """
    registry = load_registry()
    trips = registry.get("trips", [])
    if not trips:
        return None

    query_lower = query.lower().strip()

    # Exact match on city or city_local
    for t in trips:
        if (t.get("city", "").lower() == query_lower or
                t.get("city_local", "").strip() == query.strip()):
            return t

    # Substring match on name, city, city_local
    for t in trips:
        searchable = " ".join([
            t.get("name", ""), t.get("city", ""),
            t.get("city_local", ""), t.get("country", "")
        ]).lower()
        if query_lower in searchable:
            return t

    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Navigator Skill — Optimize travel itinerary routing and scheduling."
    )
    parser.add_argument("mode", choices=["optimize", "insert"],
                        help="optimize: cluster+order POIs into days. "
                             "insert: add one POI to existing itinerary.")
    parser.add_argument("--pois",
                        help="Path to JSON with POI list or full itinerary (optimize mode)")
    parser.add_argument("--itinerary",
                        help="Path to full itinerary JSON (insert mode)")
    parser.add_argument("--trip",
                        help="Trip name/city to look up in registry (alternative to --itinerary)")
    parser.add_argument("--new-poi",
                        help="Path to JSON with single POI to insert (insert mode)")
    parser.add_argument("--city",
                        help="Destination city name (e.g., 'Tokyo'). Auto-detected with --trip.")
    parser.add_argument("--days", type=int,
                        help="Number of days (optimize mode)")
    parser.add_argument("--start-date",
                        help="Start date YYYY-MM-DD (optional)")
    parser.add_argument("--day-start", default=DEFAULT_DAY_START,
                        help=f"Daily start time HH:MM (default: {DEFAULT_DAY_START})")
    parser.add_argument("--day-end", default=DEFAULT_DAY_END,
                        help=f"Daily end time HH:MM (default: {DEFAULT_DAY_END})")
    parser.add_argument("--api-key",
                        help="Google Maps API key (default: $GOOGLE_MAPS_API_KEY)")
    parser.add_argument("--mock-distances",
                        help="Path to mock distance matrix JSON (for testing)")

    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        print("Error: --api-key or GOOGLE_MAPS_API_KEY env var required.", file=sys.stderr)
        sys.exit(1)

    mock_data = None
    if args.mock_distances:
        with open(args.mock_distances, "r", encoding="utf-8") as f:
            mock_data = json.load(f)

    # Resolve --trip to itinerary path and city
    trip_entry = None
    if args.trip:
        trip_entry = find_trip(args.trip)
        if not trip_entry:
            registry = load_registry()
            available = [f"  - {t.get('city_local', '')} {t.get('city', '')} ({t.get('start_date', '')})"
                         for t in registry.get("trips", [])]
            print(f"Error: No trip found matching '{args.trip}'.", file=sys.stderr)
            if available:
                print("Available trips:", file=sys.stderr)
                print("\n".join(available), file=sys.stderr)
            else:
                print("No trips registered yet. Create one with travel-planner first.", file=sys.stderr)
            sys.exit(1)
        if not args.itinerary:
            args.itinerary = trip_entry.get("itinerary_path", "")
        if not args.city:
            args.city = trip_entry.get("city", "")
        print(f"Resolved trip: {trip_entry.get('name', '')} → {args.itinerary}", file=sys.stderr)

    if not args.city:
        print("Error: --city is required (or use --trip to auto-detect).", file=sys.stderr)
        sys.exit(1)

    if args.mode == "optimize":
        if not args.pois:
            print("Error: --pois required for optimize mode.", file=sys.stderr)
            sys.exit(1)
        if not args.days:
            print("Error: --days required for optimize mode.", file=sys.stderr)
            sys.exit(1)

        pois = load_pois_from_file(args.pois)
        print(f"Loaded {len(pois)} POIs from {args.pois}", file=sys.stderr)

        result = optimize(
            pois=pois,
            num_days=args.days,
            city=args.city,
            api_key=api_key,
            day_start=args.day_start,
            day_end=args.day_end,
            start_date=args.start_date,
            mock_data=mock_data
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.mode == "insert":
        if not args.itinerary:
            print("Error: --itinerary or --trip required for insert mode.", file=sys.stderr)
            sys.exit(1)
        if not args.new_poi:
            print("Error: --new-poi required for insert mode.", file=sys.stderr)
            sys.exit(1)

        daily_itinerary = load_itinerary_from_file(args.itinerary)

        with open(args.new_poi, "r", encoding="utf-8") as f:
            new_poi = json.load(f)

        print(f"Inserting '{new_poi['name']}' into {len(daily_itinerary)}-day itinerary...",
              file=sys.stderr)

        result = insert_poi(
            daily_itinerary=daily_itinerary,
            new_poi=new_poi,
            city=args.city,
            api_key=api_key,
            day_start=args.day_start,
            day_end=args.day_end,
            mock_data=mock_data
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
