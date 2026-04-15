#!/usr/bin/env python3
"""
Explorer Skill — Extract structured POI data from URLs or place names.

Parses Google Maps links, place names, or search queries, then uses
Google Places API to return a canonical POI JSON ready for Navigator.

Usage:
    python3 explorer.py --url "https://maps.google.com/..." --city Tokyo
    python3 explorer.py --query "teamLab Borderless" --city Tokyo
    python3 explorer.py --url "https://tabelog.com/..." --city Tokyo
"""

import argparse
import json
import math
import os
import re
import sys
import urllib.parse
import urllib.request

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GOOGLE_PLACES_FIND_URL = "https://places.googleapis.com/v1/places:searchText"
GOOGLE_PLACES_DETAIL_URL = "https://places.googleapis.com/v1/places"

# Category → default visit duration (minutes)
DURATION_MAP = {
    "restaurant": 60,
    "cafe": 45,
    "bar": 60,
    "bakery": 30,
    "meal_delivery": 60,
    "meal_takeaway": 30,
    "food": 60,
    "lodging": 30,       # just checking in, not staying
    "museum": 120,
    "art_gallery": 90,
    "amusement_park": 180,
    "aquarium": 120,
    "zoo": 150,
    "park": 90,
    "garden": 90,
    "temple": 60,
    "shrine": 60,
    "church": 45,
    "mosque": 45,
    "hindu_temple": 45,
    "synagogue": 45,
    "tourist_attraction": 90,
    "point_of_interest": 60,
    "shopping_mall": 120,
    "store": 60,
    "spa": 120,
    "stadium": 150,
    "night_club": 120,
    "movie_theater": 150,
}

# Category mapping to canonical categories
CATEGORY_MAP = {
    "restaurant": "food",
    "cafe": "food",
    "bar": "food",
    "bakery": "food",
    "meal_delivery": "food",
    "meal_takeaway": "food",
    "food": "food",
    "lodging": "accommodation",
    "museum": "culture",
    "art_gallery": "culture",
    "temple": "culture",
    "shrine": "culture",
    "church": "culture",
    "mosque": "culture",
    "hindu_temple": "culture",
    "synagogue": "culture",
    "amusement_park": "sightseeing",
    "aquarium": "sightseeing",
    "zoo": "sightseeing",
    "tourist_attraction": "sightseeing",
    "point_of_interest": "sightseeing",
    "park": "nature",
    "garden": "nature",
    "shopping_mall": "shopping",
    "store": "shopping",
    "spa": "sightseeing",
    "stadium": "sightseeing",
    "night_club": "nightlife",
    "movie_theater": "sightseeing",
}

# Price level → approximate budget per person (JPY as reference)
PRICE_LEVEL_JPY = {
    "PRICE_LEVEL_FREE": 0,
    "PRICE_LEVEL_INEXPENSIVE": 1000,
    "PRICE_LEVEL_MODERATE": 2500,
    "PRICE_LEVEL_EXPENSIVE": 5000,
    "PRICE_LEVEL_VERY_EXPENSIVE": 10000,
}

TWD_PER_JPY = 0.22  # rough conversion rate

# ---------------------------------------------------------------------------
# URL Parsing
# ---------------------------------------------------------------------------

def parse_google_maps_url(url):
    """
    Extract search query or place info from various Google Maps URL formats.
    Returns a search query string.

    Supported formats:
    - https://maps.google.com/?q=Senso-ji+Temple
    - https://www.google.com/maps/place/Senso-ji+Temple/...
    - https://goo.gl/maps/...  (short links — resolved via redirect)
    - https://maps.app.goo.gl/...  (new short links)
    - https://www.google.com/maps/search/ramen+tokyo/...
    - https://www.google.com/maps/@35.7148,139.7967,15z (coordinate only)
    """
    parsed = urllib.parse.urlparse(url)

    # ?q= parameter
    params = urllib.parse.parse_qs(parsed.query)
    if "q" in params:
        return urllib.parse.unquote_plus(params["q"][0])

    path = urllib.parse.unquote(parsed.path)

    # /maps/place/PLACE_NAME/...
    m = re.search(r"/maps/place/([^/]+)", path)
    if m:
        return m.group(1).replace("+", " ").replace("_", " ")

    # /maps/search/QUERY/...
    m = re.search(r"/maps/search/([^/]+)", path)
    if m:
        return m.group(1).replace("+", " ")

    # /maps/@LAT,LNG,ZOOM  (no place name — return coords as query)
    m = re.search(r"/maps/@([-\d.]+),([-\d.]+)", path)
    if m:
        return f"{m.group(1)},{m.group(2)}"

    return None


def parse_generic_url(url):
    """
    Try to extract a place name from non-Google URLs.
    Works for Tabelog, TripAdvisor, Booking.com, Yelp, etc.
    Falls back to page title via the URL path.
    """
    parsed = urllib.parse.urlparse(url)
    path = urllib.parse.unquote(parsed.path)

    # Tabelog: /tokyo/A1234/A123456/12345678/
    # The useful part is usually in the page title, not the URL
    # We'll resolve this by fetching the page and extracting <title>

    # Try to extract something from the last path segment
    segments = [s for s in path.split("/") if s]
    if segments:
        # Clean up the last segment
        last = segments[-1]
        # Remove file extensions
        last = re.sub(r"\.\w+$", "", last)
        # Replace hyphens/underscores with spaces
        last = re.sub(r"[-_]", " ", last)
        if len(last) > 3:
            return last

    return None


def resolve_short_url(url):
    """Follow redirects for short URLs (goo.gl, maps.app.goo.gl)."""
    try:
        req = urllib.request.Request(url, method="HEAD")
        req.add_header("User-Agent", "Mozilla/5.0")
        opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler)
        resp = opener.open(req, timeout=10)
        return resp.url
    except Exception:
        # Try GET if HEAD fails
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "Mozilla/5.0")
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.url
        except Exception as e:
            print(f"Could not resolve short URL: {e}", file=sys.stderr)
            return url


def fetch_page_title(url):
    """Fetch a web page and extract the <title> tag content."""
    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "Mozilla/5.0")
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="replace")
            m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
            if m:
                title = m.group(1).strip()
                # Clean common suffixes
                for suffix in [" - Google Maps", " | Tabelog", " - TripAdvisor",
                               " - Yelp", " | Booking.com", " - じゃらん"]:
                    title = title.replace(suffix, "")
                return title.strip()
    except Exception as e:
        print(f"Could not fetch page title: {e}", file=sys.stderr)
    return None


def extract_query_from_url(url):
    """
    Main URL → query resolver. Handles all URL types.
    Returns a search query string for Places API.
    """
    # Resolve short URLs first
    if "goo.gl" in url or "maps.app" in url:
        print(f"Resolving short URL...", file=sys.stderr)
        url = resolve_short_url(url)
        print(f"Resolved to: {url}", file=sys.stderr)

    # Try Google Maps parsing
    if "google" in url and "map" in url.lower():
        query = parse_google_maps_url(url)
        if query:
            return query

    # Try page title extraction for non-Google URLs
    title = fetch_page_title(url)
    if title:
        return title

    # Fallback: try generic URL parsing
    query = parse_generic_url(url)
    if query:
        return query

    return None


# ---------------------------------------------------------------------------
# Google Places API (New)
# ---------------------------------------------------------------------------

def places_search(query, city, api_key):
    """
    Search for a place using Google Places API (New).
    Returns the first matching place with full details.
    """
    body = {
        "textQuery": f"{query}, {city}",
        "languageCode": "zh-TW",
        "maxResultCount": 1,
    }

    fields = [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.location",
        "places.types",
        "places.regularOpeningHours",
        "places.priceLevel",
        "places.rating",
        "places.userRatingCount",
        "places.googleMapsUri",
        "places.editorialSummary",
        "places.primaryType",
    ]

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(GOOGLE_PLACES_FIND_URL, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Goog-Api-Key", api_key)
    req.add_header("X-Goog-FieldMask", ",".join(fields))

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        print(f"Places API error {e.code}: {body_text}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Places API request failed: {e}", file=sys.stderr)
        return None

    places = result.get("places", [])
    if not places:
        print(f"No places found for '{query}' in {city}.", file=sys.stderr)
        return None

    return places[0]


def places_detail_by_id(place_id, api_key):
    """Get full details for a place by its resource name (places/xxx)."""
    fields = [
        "id",
        "displayName",
        "formattedAddress",
        "location",
        "types",
        "regularOpeningHours",
        "priceLevel",
        "rating",
        "userRatingCount",
        "googleMapsUri",
        "editorialSummary",
        "primaryType",
    ]

    url = f"{GOOGLE_PLACES_DETAIL_URL}/{place_id}"
    req = urllib.request.Request(url)
    req.add_header("X-Goog-Api-Key", api_key)
    req.add_header("X-Goog-FieldMask", ",".join(fields))
    req.add_header("Accept-Language", "zh-TW")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"Places Detail API failed: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# POI Builder
# ---------------------------------------------------------------------------

def format_opening_hours(place):
    """Extract opening hours string from Places API response."""
    hours = place.get("regularOpeningHours", {})

    # Try weekdayDescriptions first (human readable)
    descriptions = hours.get("weekdayDescriptions", [])
    if descriptions:
        # Check if all days are the same
        times = set()
        for desc in descriptions:
            # "Monday: 10:00 – 17:00" → "10:00 – 17:00"
            parts = desc.split(": ", 1)
            if len(parts) == 2:
                times.add(parts[1].strip())

        if len(times) == 1:
            time_str = times.pop()
            # Normalize dash
            time_str = time_str.replace(" – ", "-").replace("–", "-")
            return f"{time_str} daily"
        else:
            # Return all days
            return "; ".join(descriptions)

    # Fallback to periods
    periods = hours.get("periods", [])
    if periods:
        # Check for 24h (open at 00:00, no close)
        if len(periods) == 1 and periods[0].get("open", {}).get("hour", -1) == 0:
            close = periods[0].get("close")
            if not close:
                return "24h"

        # Extract first period as representative
        first = periods[0]
        open_h = first.get("open", {}).get("hour", 0)
        open_m = first.get("open", {}).get("minute", 0)
        close_h = first.get("close", {}).get("hour", 0)
        close_m = first.get("close", {}).get("minute", 0)
        return f"{open_h:02d}:{open_m:02d}-{close_h:02d}:{close_m:02d} daily"

    return ""


def determine_category(place):
    """Map Google place types to canonical categories."""
    primary = place.get("primaryType", "")
    if primary and primary in CATEGORY_MAP:
        return CATEGORY_MAP[primary]

    types = place.get("types", [])
    for t in types:
        if t in CATEGORY_MAP:
            return CATEGORY_MAP[t]

    return "sightseeing"


def determine_visit_duration(place):
    """Estimate visit duration based on place type."""
    primary = place.get("primaryType", "")
    if primary and primary in DURATION_MAP:
        return DURATION_MAP[primary]

    types = place.get("types", [])
    for t in types:
        if t in DURATION_MAP:
            return DURATION_MAP[t]

    return 60  # default


def estimate_budget(place, travelers=1):
    """Estimate budget from price level."""
    price_level = place.get("priceLevel", "")
    jpy = PRICE_LEVEL_JPY.get(price_level)
    if jpy is None:
        return None, None
    total_jpy = jpy * travelers
    total_twd = int(total_jpy * TWD_PER_JPY)
    return total_jpy, total_twd


def build_poi_json(place, city=""):
    """
    Convert a Google Places API response to canonical POI JSON.
    """
    display_name = place.get("displayName", {})
    name_local = display_name.get("text", "")
    name_en = display_name.get("text", "")  # API returns in requested language

    # For bilingual: the search was in zh-TW, so displayName is Chinese
    # We use the same as both since we only get one language per request
    location = place.get("location", {})
    lat = location.get("latitude", 0)
    lng = location.get("longitude", 0)

    summary = place.get("editorialSummary", {})
    description = summary.get("text", "")

    opening_hours = format_opening_hours(place)
    category = determine_category(place)
    duration = determine_visit_duration(place)
    budget_jpy, budget_twd = estimate_budget(place)

    maps_uri = place.get("googleMapsUri", "")
    if not maps_uri and name_local:
        maps_uri = f"https://maps.google.com/?q={urllib.parse.quote(name_local + ' ' + city)}"

    rating = place.get("rating")
    rating_count = place.get("userRatingCount")

    poi = {
        "name": name_local,
        "name_local": name_local,
        "category": category,
        "visit_duration_min": duration,
        "opening_hours": opening_hours,
        "description": description,
        "description_local": description,
        "google_maps_link": maps_uri,
        "lat": lat,
        "lng": lng,
        "tags": [],
    }

    # Add budget if available
    if budget_jpy is not None:
        poi["budget_jpy"] = budget_jpy
        poi["budget_twd"] = budget_twd

    # Add rating as tip
    tips_parts = []
    if rating:
        tips_parts.append(f"Google 評分 {rating}⭐")
        if rating_count:
            tips_parts.append(f"({rating_count:,} 則評論)")
    if tips_parts:
        poi["tips"] = " ".join(tips_parts)

    # Build tags from types
    types = place.get("types", [])
    tag_candidates = [t for t in types if t not in (
        "point_of_interest", "establishment", "political",
        "geocode", "premise", "subpremise")]
    poi["tags"] = tag_candidates[:5]

    return poi


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Explorer Skill — Extract structured POI data from URLs or place names."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--url",
                       help="URL to parse (Google Maps, Tabelog, TripAdvisor, etc.)")
    group.add_argument("--query",
                       help="Place name or search query (e.g., 'teamLab Borderless')")
    parser.add_argument("--city", required=True,
                        help="City context for search (e.g., 'Tokyo')")
    parser.add_argument("--api-key",
                        help="Google Maps API key (default: $GOOGLE_MAPS_API_KEY)")
    parser.add_argument("--save",
                        help="Save POI JSON to this file path (optional)")

    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        print("Error: --api-key or GOOGLE_MAPS_API_KEY env var required.", file=sys.stderr)
        sys.exit(1)

    # Step 1: Get search query
    if args.url:
        print(f"Parsing URL: {args.url}", file=sys.stderr)
        query = extract_query_from_url(args.url)
        if not query:
            print(f"Error: Could not extract place info from URL.", file=sys.stderr)
            print(f"Try using --query with the place name instead.", file=sys.stderr)
            sys.exit(1)
        print(f"Extracted query: {query}", file=sys.stderr)
    else:
        query = args.query

    # Step 2: Search Places API
    print(f"Searching: '{query}' in {args.city}...", file=sys.stderr)
    place = places_search(query, args.city, api_key)
    if not place:
        print("Error: No place found.", file=sys.stderr)
        sys.exit(1)

    display = place.get("displayName", {}).get("text", "?")
    address = place.get("formattedAddress", "?")
    print(f"Found: {display} — {address}", file=sys.stderr)

    # Step 3: Build POI JSON
    poi = build_poi_json(place, args.city)

    # Step 4: Output
    output = json.dumps(poi, indent=2, ensure_ascii=False)
    print(output)

    if args.save:
        os.makedirs(os.path.dirname(os.path.abspath(args.save)), exist_ok=True)
        with open(args.save, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Saved to: {args.save}", file=sys.stderr)


if __name__ == "__main__":
    main()
