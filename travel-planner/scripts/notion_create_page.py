#!/usr/bin/env python3
"""
Create or update a Notion travel itinerary page from structured JSON.

Architecture: Main page = dashboard, each day = subpage, thematic subpages
for food guide, transport guide, and budget overview.

Usage:
    # Create new page
    python3 notion_create_page.py \
        --api-key <KEY> --parent-page-id <ID> --itinerary <path.json>

    # Read existing page back to JSON
    python3 notion_create_page.py \
        --api-key <KEY> --read-page <PAGE_ID>

    # Update existing page with new itinerary
    python3 notion_create_page.py \
        --api-key <KEY> --update-page <PAGE_ID> --itinerary <path.json>
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error

NOTION_API_VERSION = "2022-06-28"
NOTION_BASE = "https://api.notion.com/v1"
META_DIR = os.path.expanduser("~/.travel-planner")
ITINERARIES_DIR = os.path.join(META_DIR, "itineraries")
REGISTRY_PATH = os.path.join(META_DIR, "registry.json")

# ── Language Packs ─────────────────────────────────────────────────────────

LANG_PACKS = {
    "zh-TW": {
        "page_title": "{city_local} — {start} ~ {end} 旅遊行程",
        "destination": "目的地：{city_line}",
        "dates": "日期：{date_line}",
        "travelers": "旅伴人數：{travelers}",
        "tips_heading": "💡 旅行小提示",
        "day_heading": "第 {day} 天 — {theme}",
        "day_heading_date": "第 {day} 天 — {theme}（{date}）",
        "budget_label": "💰 預算：{budget}",
        "hours_label": "🕐 營業時間：{hours}",
        "maps_label": "📍 {name} Google Maps",
        "checklist_heading": "✅ 行李清單",
        "db_title": "📍 {city_local} 行程表",
        "days_suffix": "天",
        "meal_breakfast": "早餐",
        "meal_lunch": "午餐",
        "meal_dinner": "晚餐",
        "meal_snack": "點心",
        "daily_nav_heading": "📅 每日行程",
        "thematic_nav_heading": "📂 主題整理",
        "food_title": "美食清單",
        "transport_title": "交通攻略",
        "budget_title": "預算總覽",
        "budget_col_day": "天",
        "budget_col_date": "日期",
        "budget_col_poi": "景點預算",
        "budget_col_meal": "餐飲預算",
        "budget_col_total": "小計",
        "budget_grand_total": "總計",
        "food_day_heading": "Day {day} — {theme}（{date}）",
        "transport_day_heading": "Day {day}：{theme}",
    },
    "en": {
        "page_title": "{city} — {start} ~ {end} Travel Itinerary",
        "destination": "Destination: {city_line}",
        "dates": "Dates: {date_line}",
        "travelers": "Travelers: {travelers}",
        "tips_heading": "💡 Travel Tips",
        "day_heading": "Day {day} — {theme}",
        "day_heading_date": "Day {day} — {theme}  ({date})",
        "budget_label": "💰 Budget: {budget}",
        "hours_label": "🕐 Hours: {hours}",
        "maps_label": "📍 {name} on Google Maps",
        "checklist_heading": "✅ Packing Checklist",
        "db_title": "📍 {city} Itinerary",
        "days_suffix": "days",
        "meal_breakfast": "Breakfast",
        "meal_lunch": "Lunch",
        "meal_dinner": "Dinner",
        "meal_snack": "Snack",
        "daily_nav_heading": "📅 Daily Itinerary",
        "thematic_nav_heading": "📂 Thematic Guides",
        "food_title": "Food Guide",
        "transport_title": "Transport Guide",
        "budget_title": "Budget Overview",
        "budget_col_day": "Day",
        "budget_col_date": "Date",
        "budget_col_poi": "POI Budget",
        "budget_col_meal": "Meal Budget",
        "budget_col_total": "Subtotal",
        "budget_grand_total": "Grand Total",
        "food_day_heading": "Day {day} — {theme} ({date})",
        "transport_day_heading": "Day {day}: {theme}",
    },
    "ja": {
        "page_title": "{city_local} — {start} ~ {end} 旅行プラン",
        "destination": "目的地：{city_line}",
        "dates": "日程：{date_line}",
        "travelers": "旅行者数：{travelers}",
        "tips_heading": "💡 旅行のヒント",
        "day_heading": "{day}日目 — {theme}",
        "day_heading_date": "{day}日目 — {theme}（{date}）",
        "budget_label": "💰 予算：{budget}",
        "hours_label": "🕐 営業時間：{hours}",
        "maps_label": "📍 {name} Google Maps",
        "checklist_heading": "✅ 持ち物リスト",
        "db_title": "📍 {city_local} 旅程表",
        "days_suffix": "日間",
        "meal_breakfast": "朝食",
        "meal_lunch": "昼食",
        "meal_dinner": "夕食",
        "meal_snack": "おやつ",
        "daily_nav_heading": "📅 日程表",
        "thematic_nav_heading": "📂 テーマ別",
        "food_title": "グルメガイド",
        "transport_title": "交通ガイド",
        "budget_title": "予算一覧",
        "budget_col_day": "日",
        "budget_col_date": "日付",
        "budget_col_poi": "観光予算",
        "budget_col_meal": "食事予算",
        "budget_col_total": "小計",
        "budget_grand_total": "合計",
        "food_day_heading": "{day}日目 — {theme}（{date}）",
        "transport_day_heading": "{day}日目：{theme}",
    },
}

DEFAULT_LANG = os.environ.get("TRAVEL_PLANNER_LANG", "zh-TW")


def get_lang_pack(lang=None):
    """Get language pack. Falls back to zh-TW."""
    lang = lang or DEFAULT_LANG
    return LANG_PACKS.get(lang, LANG_PACKS["zh-TW"])


# ── Trip Registry ─────────��────────────────────────────────��───────────────

def load_registry():
    """Load the trip registry. Returns {"trips": [...]}."""
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"trips": []}


def save_registry(registry):
    """Atomic write registry to disk."""
    os.makedirs(META_DIR, exist_ok=True)
    tmp = REGISTRY_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)
    os.rename(tmp, REGISTRY_PATH)


def register_trip(page_id, page_url, data, itinerary_path):
    """Add or update a trip in the registry."""
    registry = load_registry()
    dest = data.get("destination", {})
    dates = data.get("dates", {})
    days = len(data.get("daily_itinerary", []))

    entry = {
        "name": "{0} {1} {2}".format(
            dest.get("city_local", ""), dest.get("city", ""),
            dates.get("start", "")),
        "city": dest.get("city", ""),
        "city_local": dest.get("city_local", ""),
        "country": dest.get("country", ""),
        "page_id": page_id,
        "page_url": page_url,
        "itinerary_path": os.path.abspath(itinerary_path) if itinerary_path else "",
        "days": days,
        "start_date": dates.get("start", ""),
        "end_date": dates.get("end", ""),
        "updated": __import__("datetime").datetime.now().strftime("%Y-%m-%d"),
    }

    # Update existing or append new
    found = False
    for i, t in enumerate(registry["trips"]):
        if t["page_id"] == page_id:
            registry["trips"][i] = entry
            found = True
            break
    if not found:
        registry["trips"].append(entry)

    save_registry(registry)
    return entry


# ── Notion API helpers ───��──────────────────────────────────────────────────

def notion_request(method, path, api_key, body=None):
    url = "{0}{1}".format(NOTION_BASE, path)
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "Bearer {0}".format(api_key))
    req.add_header("Notion-Version", NOTION_API_VERSION)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        print("Notion API error {0}: {1}".format(e.code, error_body), file=sys.stderr)
        sys.exit(1)


def rich_text(content, bold=False, italic=False, color="default", link=None):
    return {
        "type": "text",
        "text": {"content": content, "link": {"url": link} if link else None},
        "annotations": {
            "bold": bold, "italic": italic,
            "strikethrough": False, "underline": False,
            "code": False, "color": color,
        },
    }


def heading(level, text, color="default"):
    key = "heading_{0}".format(level)
    return {"object": "block", "type": key, key: {
        "rich_text": [rich_text(text)], "color": color, "is_toggleable": False,
    }}


def paragraph(text, bold=False, color="default", link=None):
    return {"object": "block", "type": "paragraph", "paragraph": {
        "rich_text": [rich_text(text, bold=bold, color=color, link=link)] if text else [],
        "color": "default",
    }}


def callout(text_parts, emoji="💡", color="default"):
    if isinstance(text_parts, str):
        text_parts = [(text_parts, False)]
    return {"object": "block", "type": "callout", "callout": {
        "rich_text": [rich_text(t, bold=b) for t, b in text_parts],
        "icon": {"emoji": emoji},
        "color": color,
    }}


def todo(text, checked=False):
    return {"object": "block", "type": "to_do", "to_do": {
        "rich_text": [rich_text(text)], "checked": checked, "color": "default",
    }}


def bulleted(text, bold=False):
    return {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {
        "rich_text": [rich_text(text, bold=bold)], "color": "default",
    }}


def bookmark(url, caption=""):
    return {"object": "block", "type": "bookmark", "bookmark": {
        "url": url,
        "caption": [rich_text(caption)] if caption else [],
    }}


def divider():
    return {"object": "block", "type": "divider", "divider": {}}


def link_to_page(page_id):
    """Create a link_to_page block pointing to a child page."""
    return {"object": "block", "type": "link_to_page", "link_to_page": {
        "type": "page_id", "page_id": page_id,
    }}


def table_block(headers, rows):
    """Create a Notion table block with header row + data rows."""
    width = len(headers)
    children = []
    # Header row
    children.append({
        "type": "table_row",
        "table_row": {
            "cells": [[rich_text(h, bold=True)] for h in headers]
        }
    })
    for row in rows:
        children.append({
            "type": "table_row",
            "table_row": {
                "cells": [[rich_text(str(cell))] for cell in row]
            }
        })
    return {"object": "block", "type": "table", "table": {
        "table_width": width,
        "has_column_header": True,
        "has_row_header": False,
        "children": children,
    }}


# ── Unsplash cover ──────────────────────────────────────────────────────────

def get_unsplash_cover(query):
    """Return a direct Unsplash image URL suitable for a Notion external cover.

    source.unsplash.com was fully deprecated in 2023.  We use curated
    images.unsplash.com direct URLs keyed by common travel destinations.
    For unknown queries, a generic travel hero image is returned.
    """
    # Curated cover photos — direct CDN URLs that Notion can render
    COVERS = {
        "tokyo":     "https://images.unsplash.com/photo-1540959733332-eab4deabeeaf?w=1600&h=900&fit=crop",
        "osaka":     "https://images.unsplash.com/photo-1590559899731-a382839e5549?w=1600&h=900&fit=crop",
        "kyoto":     "https://images.unsplash.com/photo-1493976040374-85c8e12f0c0e?w=1600&h=900&fit=crop",
        "seoul":     "https://images.unsplash.com/photo-1534274988757-a28bf1a57c17?w=1600&h=900&fit=crop",
        "taipei":    "https://images.unsplash.com/photo-1470004914212-05527e49370b?w=1600&h=900&fit=crop",
        "bangkok":   "https://images.unsplash.com/photo-1508009603885-50cf7c579365?w=1600&h=900&fit=crop",
        "singapore": "https://images.unsplash.com/photo-1525625293386-3f8f99389edd?w=1600&h=900&fit=crop",
        "paris":     "https://images.unsplash.com/photo-1502602898657-3e91760cbb34?w=1600&h=900&fit=crop",
        "london":    "https://images.unsplash.com/photo-1513635269975-59663e0ac1ad?w=1600&h=900&fit=crop",
        "new york":  "https://images.unsplash.com/photo-1496442226666-8d4d0e62e6e9?w=1600&h=900&fit=crop",
        "hong kong": "https://images.unsplash.com/photo-1536599018102-9f803c979b13?w=1600&h=900&fit=crop",
        "okinawa":   "https://images.unsplash.com/photo-1583400225628-3f8b4dc98da0?w=1600&h=900&fit=crop",
        "hokkaido":  "https://images.unsplash.com/photo-1578271887552-5ac3a72752bc?w=1600&h=900&fit=crop",
        "shikoku":   "https://images.unsplash.com/photo-1528360983277-13d401cdc186?w=1600&h=900&fit=crop",
    }
    FALLBACK = "https://images.unsplash.com/photo-1488646953014-85cb44e25828?w=1600&h=900&fit=crop"

    if not query:
        return FALLBACK
    q = query.lower().strip()
    for key, url in COVERS.items():
        if key in q:
            return url
    return FALLBACK


# ── Build blocks ───────────────��───────────────────────���────────────────────

def build_overview_callout(data, lang=None):
    L = get_lang_pack(lang)
    dest = data["destination"]
    dates = data["dates"]
    days = len(data.get("daily_itinerary", []))
    city_line = "{0} {1}, {2} {3}".format(
        dest.get("city_local", ""), dest["city"],
        dest.get("country_local", ""), dest["country"])
    date_line = "{0} ~ {1} ({2} {3})".format(dates["start"], dates["end"], days, L["days_suffix"])
    travelers = data.get("travelers", "")

    parts = [
        (L["destination"].format(city_line=city_line) + "\n", True),
        (L["dates"].format(date_line=date_line) + "\n", False),
    ]
    if travelers:
        parts.append((L["travelers"].format(travelers=travelers), False))

    return callout(parts, emoji="📋", color="blue_background")


def build_tips_blocks(tips, lang=None):
    L = get_lang_pack(lang)
    if not tips:
        return []
    blocks = [heading(2, L["tips_heading"])]
    for tip in tips:
        blocks.append(callout(tip, emoji="💡", color="yellow_background"))
    return blocks


def _get_display_theme(day_data, lang):
    """Get the display theme string based on language."""
    theme = day_data.get("theme", "") or day_data.get("theme_local", "")
    theme_local = day_data.get("theme_local", "")
    if lang and lang == "en":
        return theme
    return theme_local or theme


def build_day_content_blocks(day_data, lang=None):
    """Build content blocks for a day (without H2 heading — used inside subpages)."""
    L = get_lang_pack(lang)
    blocks = []

    transport = day_data.get("transport_notes", "")
    if transport:
        blocks.append(callout("🚃 {0}".format(transport), emoji="🚃", color="gray_background"))

    for poi in day_data.get("pois", []):
        name = poi["name"]
        name_local = poi.get("name_local", "")
        time_slot = poi.get("time_slot", "")
        poi_title = "🕐 {0}  {1}".format(time_slot, name)
        if name_local:
            poi_title += " / {0}".format(name_local)
        blocks.append(heading(3, poi_title))

        desc = poi.get("description", "")
        desc_local = poi.get("description_local", "")
        if desc:
            full_desc = desc
            if desc_local:
                full_desc += "\n{0}".format(desc_local)
            blocks.append(paragraph(full_desc))

        budget_parts = []
        if poi.get("budget_jpy"):
            budget_parts.append("¥{0:,}".format(poi["budget_jpy"]))
        if poi.get("budget_twd"):
            budget_parts.append("NT${0:,}".format(poi["budget_twd"]))
        if budget_parts:
            blocks.append(paragraph(L["budget_label"].format(budget=" / ".join(budget_parts)), bold=True))

        if poi.get("opening_hours"):
            blocks.append(paragraph(L["hours_label"].format(hours=poi["opening_hours"])))

        if poi.get("tips"):
            blocks.append(callout(poi["tips"], emoji="✨", color="yellow_background"))

        if poi.get("google_maps_link"):
            blocks.append(bookmark(poi["google_maps_link"],
                                   L["maps_label"].format(name=name)))

    meal_type_map = {
        "breakfast": L["meal_breakfast"],
        "lunch": L["meal_lunch"],
        "dinner": L["meal_dinner"],
        "snack": L["meal_snack"],
    }
    for meal in day_data.get("meals", []):
        raw_type = meal.get("type", "meal")
        meal_type_label = meal_type_map.get(raw_type, raw_type.capitalize())
        meal_name = meal["name"]
        meal_local = meal.get("name_local", "")
        emoji_map = {"breakfast": "🌅", "lunch": "🍽️", "dinner": "🌙", "snack": "🍡"}
        meal_emoji = emoji_map.get(raw_type, "🍽️")

        label = "{0} {1}：{2}".format(meal_emoji, meal_type_label, meal_name)
        if meal_local and meal_local != meal_name:
            label += " / {0}".format(meal_local)

        budget_parts = []
        if meal.get("budget_jpy"):
            budget_parts.append("¥{0:,}".format(meal["budget_jpy"]))
        if meal.get("budget_twd"):
            budget_parts.append("NT${0:,}".format(meal["budget_twd"]))
        if budget_parts:
            label += "  (💰 {0})".format(" / ".join(budget_parts))

        blocks.append(bulleted(label, bold=True))

        if meal.get("google_maps_link"):
            blocks.append(bookmark(meal["google_maps_link"],
                                   "📍 {0}".format(meal_name)))

    return blocks


def build_checklist_blocks(items, lang=None):
    L = get_lang_pack(lang)
    if not items:
        return []
    blocks = [heading(2, L["checklist_heading"])]
    for item in items:
        blocks.append(todo(item))
    return blocks


# ── Create inline database ─────��────────────────────────────────���───────────

def create_itinerary_database(api_key, parent_page_id, data, lang=None):
    L = get_lang_pack(lang)
    dest = data["destination"]
    db_title = L["db_title"].format(
        city=dest["city"], city_local=dest.get("city_local", dest["city"]))

    payload = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "title": [{"type": "text", "text": {"content": db_title}}],
        "is_inline": True,
        "properties": {
            "POI": {"title": {}},
            "Date": {"date": {}},
            "Category": {
                "select": {
                    "options": [
                        {"name": "sightseeing", "color": "blue"},
                        {"name": "shrine", "color": "purple"},
                        {"name": "temple", "color": "purple"},
                        {"name": "museum", "color": "blue"},
                        {"name": "memorial", "color": "gray"},
                        {"name": "onsen", "color": "red"},
                        {"name": "cycling", "color": "green"},
                        {"name": "shopping", "color": "pink"},
                        {"name": "food", "color": "orange"},
                        {"name": "nature", "color": "green"},
                        {"name": "culture", "color": "purple"},
                        {"name": "nightlife", "color": "red"},
                        {"name": "transport", "color": "gray"},
                        {"name": "accommodation", "color": "yellow"},
                    ]
                }
            },
            "Time Slot": {"rich_text": {}},
            "Budget (Local)": {"number": {"format": "number"}},
            "Budget (TWD)": {"number": {"format": "number"}},
            "Status": {
                "status": {
                    "options": [
                        {"name": "Not Started", "color": "default"},
                        {"name": "Confirmed", "color": "blue"},
                        {"name": "Done", "color": "green"},
                        {"name": "Skipped", "color": "red"},
                    ]
                }
            },
            "Location": {"url": {}},
            "Tags": {"multi_select": {"options": []}},
            "Day": {"number": {"format": "number"}},
        },
    }

    result = notion_request("POST", "/databases", api_key, payload)
    return result["id"]


def build_db_row_props(day_num, date_str, item_type, item):
    name = item["name"]
    name_local = item.get("name_local", "")
    display_name = "{0} / {1}".format(name, name_local) if name_local else name

    props = {
        "POI": {"title": [rich_text(display_name)]},
        "Day": {"number": day_num},
    }
    if date_str:
        props["Date"] = {"date": {"start": date_str}}
    if item.get("category"):
        props["Category"] = {"select": {"name": item["category"]}}
    elif item_type == "meal":
        props["Category"] = {"select": {"name": "food"}}
    if item.get("time_slot"):
        props["Time Slot"] = {"rich_text": [rich_text(item["time_slot"])]}
    # Accept any budget key that starts with budget_ (except budget_twd)
    for key, val in item.items():
        if key.startswith("budget_") and key != "budget_twd" and val:
            props["Budget (Local)"] = {"number": val}
            break
    if item.get("budget_twd"):
        props["Budget (TWD)"] = {"number": item["budget_twd"]}
    if item.get("google_maps_link"):
        props["Location"] = {"url": item["google_maps_link"]}
    if item.get("tags"):
        props["Tags"] = {"multi_select": [{"name": t} for t in item["tags"]]}
    return props


def populate_database(api_key, database_id, data):
    rows_created = 0
    for day_data in data.get("daily_itinerary", []):
        day_num = day_data["day"]
        date_str = day_data.get("date")

        for poi in day_data.get("pois", []):
            props = build_db_row_props(day_num, date_str, "poi", poi)
            notion_request("POST", "/pages", api_key,
                           {"parent": {"database_id": database_id}, "properties": props})
            rows_created += 1

        for meal in day_data.get("meals", []):
            props = build_db_row_props(day_num, date_str, "meal", meal)
            notion_request("POST", "/pages", api_key,
                           {"parent": {"database_id": database_id}, "properties": props})
            rows_created += 1

    return rows_created


# ── Subpage creation ──���────────────────────────────��────────────────────────

def _append_blocks_batched(api_key, page_id, blocks):
    """Append blocks to a page in batches of 100."""
    remaining = list(blocks)
    while remaining:
        batch = remaining[:100]
        remaining = remaining[100:]
        notion_request("PATCH", "/blocks/{0}/children".format(page_id), api_key,
                       {"children": batch})


def create_day_subpage(api_key, parent_page_id, day_data, lang=None):
    """Create a child page for a single day. Returns the page ID."""
    L = get_lang_pack(lang)
    day_num = day_data["day"]
    display_theme = _get_display_theme(day_data, lang)
    date_str = day_data.get("date", "")

    if date_str:
        title = L["day_heading_date"].format(day=day_num, theme=display_theme, date=date_str)
    else:
        title = L["day_heading"].format(day=day_num, theme=display_theme)

    children = build_day_content_blocks(day_data, lang)

    first_batch = children[:100]
    remaining = children[100:]

    page_payload = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "icon": {"type": "emoji", "emoji": "📅"},
        "properties": {
            "title": {"title": [{"type": "text", "text": {"content": title}}]}
        },
        "children": first_batch,
    }

    result = notion_request("POST", "/pages", api_key, page_payload)
    page_id = result["id"]

    if remaining:
        _append_blocks_batched(api_key, page_id, remaining)

    return page_id


def create_food_subpage(api_key, parent_page_id, data, lang=None):
    """Create a food guide subpage listing all meals + food POIs by day."""
    L = get_lang_pack(lang)
    children = []

    meal_type_map = {
        "breakfast": L["meal_breakfast"],
        "lunch": L["meal_lunch"],
        "dinner": L["meal_dinner"],
        "snack": L["meal_snack"],
    }
    emoji_map = {"breakfast": "🌅", "lunch": "🍽️", "dinner": "🌙", "snack": "🍡"}

    for day_data in data.get("daily_itinerary", []):
        day_num = day_data["day"]
        display_theme = _get_display_theme(day_data, lang)
        date_str = day_data.get("date", "")

        meals = day_data.get("meals", [])
        food_pois = [p for p in day_data.get("pois", [])
                     if p.get("category") in ("food", "cafe", "restaurant")
                     or "food" in (p.get("tags") or [])]

        if not meals and not food_pois:
            continue

        title = L["food_day_heading"].format(day=day_num, theme=display_theme, date=date_str)
        children.append(heading(3, title))

        for meal in meals:
            raw_type = meal.get("type", "meal")
            meal_type_label = meal_type_map.get(raw_type, raw_type.capitalize())
            meal_name = meal["name"]
            meal_local = meal.get("name_local", "")
            meal_emoji = emoji_map.get(raw_type, "🍽️")

            label = "{0} {1}：{2}".format(meal_emoji, meal_type_label, meal_name)
            if meal_local and meal_local != meal_name:
                label += " / {0}".format(meal_local)

            budget_parts = []
            if meal.get("budget_jpy"):
                budget_parts.append("¥{0:,}".format(meal["budget_jpy"]))
            if meal.get("budget_twd"):
                budget_parts.append("NT${0:,}".format(meal["budget_twd"]))
            if budget_parts:
                label += "  (💰 {0})".format(" / ".join(budget_parts))

            children.append(bulleted(label, bold=True))
            if meal.get("google_maps_link"):
                children.append(bookmark(meal["google_maps_link"], "📍 {0}".format(meal_name)))

        for poi in food_pois:
            poi_name = poi["name"]
            poi_local = poi.get("name_local", "")
            label = "🍴 {0}".format(poi_name)
            if poi_local:
                label += " / {0}".format(poi_local)
            if poi.get("tips"):
                label += " — {0}".format(poi["tips"])
            children.append(bulleted(label))
            if poi.get("google_maps_link"):
                children.append(bookmark(poi["google_maps_link"], "📍 {0}".format(poi_name)))

    if not children:
        children.append(paragraph("No food items found."))

    first_batch = children[:100]
    remaining = children[100:]

    page_payload = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "icon": {"type": "emoji", "emoji": "🍽️"},
        "properties": {
            "title": {"title": [{"type": "text", "text": {"content": L["food_title"]}}]}
        },
        "children": first_batch,
    }

    result = notion_request("POST", "/pages", api_key, page_payload)
    page_id = result["id"]

    if remaining:
        _append_blocks_batched(api_key, page_id, remaining)

    return page_id


def create_transport_subpage(api_key, parent_page_id, data, lang=None):
    """Create a transport guide subpage consolidating all transport notes."""
    L = get_lang_pack(lang)
    children = []

    for day_data in data.get("daily_itinerary", []):
        day_num = day_data["day"]
        display_theme = _get_display_theme(day_data, lang)
        transport = day_data.get("transport_notes", "")

        if not transport:
            continue

        title = L["transport_day_heading"].format(day=day_num, theme=display_theme)
        children.append(heading(3, title))
        children.append(callout("🚃 {0}".format(transport), emoji="🚃", color="gray_background"))

    # Add transport-related tips from travel_tips
    transport_keywords = ["JR", "新幹線", "租車", "ETC", "巴士", "bus", "ferry",
                          "渡船", "機場", "airport", "自行車", "cycling", "bike",
                          "train", "metro", "IC card", "IC 卡", "Suica", "ICOCA"]
    transport_tips = []
    for tip in data.get("travel_tips", []):
        if any(kw.lower() in tip.lower() for kw in transport_keywords):
            transport_tips.append(tip)

    if transport_tips:
        children.append(divider())
        children.append(heading(3, L["tips_heading"]))
        for tip in transport_tips:
            children.append(callout(tip, emoji="💡", color="yellow_background"))

    if not children:
        children.append(paragraph("No transport notes found."))

    page_payload = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "icon": {"type": "emoji", "emoji": "🚃"},
        "properties": {
            "title": {"title": [{"type": "text", "text": {"content": L["transport_title"]}}]}
        },
        "children": children[:100],
    }

    result = notion_request("POST", "/pages", api_key, page_payload)
    page_id = result["id"]

    if len(children) > 100:
        _append_blocks_batched(api_key, page_id, children[100:])

    return page_id


def create_budget_subpage(api_key, parent_page_id, data, lang=None):
    """Create a budget overview subpage with a summary table."""
    L = get_lang_pack(lang)

    headers = [
        L["budget_col_day"],
        L["budget_col_date"],
        L["budget_col_poi"],
        L["budget_col_meal"],
        L["budget_col_total"],
    ]

    rows = []
    grand_poi = 0
    grand_meal = 0

    for day_data in data.get("daily_itinerary", []):
        poi_budget = sum(p.get("budget_twd", 0) or 0 for p in day_data.get("pois", []))
        meal_budget = sum(m.get("budget_twd", 0) or 0 for m in day_data.get("meals", []))
        total = poi_budget + meal_budget
        grand_poi += poi_budget
        grand_meal += meal_budget

        rows.append([
            str(day_data["day"]),
            day_data.get("date", ""),
            "NT${0:,}".format(poi_budget) if poi_budget else "-",
            "NT${0:,}".format(meal_budget) if meal_budget else "-",
            "NT${0:,}".format(total) if total else "-",
        ])

    # Grand total row
    grand_total = grand_poi + grand_meal
    rows.append([
        L["budget_grand_total"], "",
        "NT${0:,}".format(grand_poi),
        "NT${0:,}".format(grand_meal),
        "NT${0:,}".format(grand_total),
    ])

    children = [table_block(headers, rows)]

    page_payload = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "icon": {"type": "emoji", "emoji": "💰"},
        "properties": {
            "title": {"title": [{"type": "text", "text": {"content": L["budget_title"]}}]}
        },
        "children": children,
    }

    result = notion_request("POST", "/pages", api_key, page_payload)
    return result["id"]


# ── Metadata persistence ─────��──────────────────────────────────────────────

def _copy_itinerary_to_data_dir(itinerary_path):
    """Copy itinerary JSON into ~/.travel-planner/itineraries/ with a UUID filename."""
    import uuid
    import shutil
    os.makedirs(ITINERARIES_DIR, exist_ok=True)
    src = os.path.abspath(itinerary_path)
    # Check if src is already in ITINERARIES_DIR with a UUID name — reuse it
    if os.path.dirname(src) == os.path.abspath(ITINERARIES_DIR):
        return src
    dest = os.path.join(ITINERARIES_DIR, "{0}.json".format(uuid.uuid4().hex[:12]))
    shutil.copy2(src, dest)
    return dest


def save_metadata(page_id, database_id, itinerary_path,
                  day_subpage_ids=None, thematic_subpage_ids=None):
    """Save metadata and copy itinerary to data dir. Returns (meta_path, canonical_itinerary_path)."""
    os.makedirs(META_DIR, exist_ok=True)
    canonical_path = _copy_itinerary_to_data_dir(itinerary_path)
    meta = {
        "page_id": page_id,
        "database_id": database_id,
        "itinerary_path": canonical_path,
        "day_subpage_ids": day_subpage_ids or [],
        "thematic_subpage_ids": thematic_subpage_ids or {},
    }
    meta_path = os.path.join(META_DIR, "{0}.meta.json".format(page_id.replace("-", "")))
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    return meta_path, canonical_path


def load_metadata(page_id):
    clean_id = page_id.replace("-", "")
    meta_path = os.path.join(META_DIR, "{0}.meta.json".format(clean_id))
    if not os.path.exists(meta_path):
        return None
    with open(meta_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Read existing page ──────────────────────────────────────────────────────

def read_page_blocks(api_key, page_id):
    """Read all blocks from a page, handling pagination."""
    blocks = []
    cursor = None
    while True:
        path = "/blocks/{0}/children?page_size=100".format(page_id)
        if cursor:
            path += "&start_cursor={0}".format(cursor)
        result = notion_request("GET", path, api_key)
        blocks.extend(result.get("results", []))
        if not result.get("has_more"):
            break
        cursor = result.get("next_cursor")
    return blocks


def query_database(api_key, database_id):
    """Query all rows from a database."""
    rows = []
    body = {"page_size": 100}
    while True:
        result = notion_request("POST", "/databases/{0}/query".format(database_id), api_key, body)
        rows.extend(result.get("results", []))
        if not result.get("has_more"):
            break
        body["start_cursor"] = result.get("next_cursor")
    return rows


def extract_plain_text(rich_text_array):
    """Extract plain text from a Notion rich_text array."""
    return "".join(rt.get("plain_text", "") for rt in rich_text_array)


def read_existing_itinerary(api_key, page_id):
    """Read a Notion page and reconstruct the itinerary structure.
    Returns: { "page_id", "blocks", "database_id", "database_rows", "meta" }
    """
    blocks = read_page_blocks(api_key, page_id)

    # Find inline database
    database_id = None
    database_rows = []
    for block in blocks:
        if block.get("type") == "child_database":
            database_id = block["id"]
            break

    if database_id:
        database_rows = query_database(api_key, database_id)

    meta = load_metadata(page_id)

    return {
        "page_id": page_id,
        "blocks": blocks,
        "database_id": database_id,
        "database_rows": database_rows,
        "meta": meta,
    }


# ── Update existing page ────────���──────────────────────────────────────────

def delete_block(api_key, block_id):
    notion_request("DELETE", "/blocks/{0}".format(block_id), api_key)


def archive_page(api_key, page_id):
    """Archive (soft-delete) a page."""
    notion_request("PATCH", "/pages/{0}".format(page_id), api_key, {"archived": True})


def clear_database_rows(api_key, database_id):
    """Archive (delete) all existing rows in a database."""
    rows = query_database(api_key, database_id)
    deleted = 0
    for row in rows:
        notion_request("PATCH", "/pages/{0}".format(row["id"]), api_key, {"archived": True})
        deleted += 1
    return deleted


def _identify_deletable_blocks(blocks):
    """Identify blocks to delete during update.

    Keeps: overview callout, tips section, inline database.
    Deletes: everything else (nav headings, link_to_page, dividers after tips,
             old-style day blocks, checklist).
    """
    to_delete = []
    past_tips = False
    in_tips = False

    for block in blocks:
        btype = block.get("type", "")
        bid = block["id"]

        # Detect tips heading
        if btype == "heading_2":
            text = extract_plain_text(block.get("heading_2", {}).get("rich_text", []))
            if "💡" in text:
                in_tips = True
                continue
            else:
                if in_tips:
                    past_tips = True
                    in_tips = False

        # Keep overview callout (before tips)
        if not past_tips and not in_tips:
            if btype == "callout":
                text = extract_plain_text(block.get("callout", {}).get("rich_text", []))
                if "目的地" in text or "Destination" in text:
                    continue
            # Keep tips heading and tip callouts
            if in_tips or (btype == "heading_2"):
                continue
            # Keep first divider (after overview, before tips) — but we may not have one
            # Actually, the first divider is after tips; let's not try to be too clever
            continue

        if in_tips:
            # Keep tip callout blocks
            if btype == "callout":
                continue

        # Past tips section — delete everything except child_database
        if past_tips:
            if btype == "child_database":
                continue  # Keep the database
            to_delete.append(bid)

    return to_delete


def update_travel_page(api_key, page_id, data, itinerary_path=None, lang=None):
    """Update an existing travel page with new itinerary data.

    Strategy:
    1. Archive old subpages (day + thematic) from metadata
    2. Delete nav/checklist/old-day blocks from main page (keep overview, tips, DB)
    3. Clear and repopulate database
    4. Create new day subpages
    5. Create new thematic subpages
    6. Append new nav blocks + checklist to main page
    7. Update overview callout + page title
    """
    lang = lang or data.get("lang", "zh-TW")
    L = get_lang_pack(lang)
    current = read_existing_itinerary(api_key, page_id)
    blocks = current["blocks"]
    database_id = current["database_id"]
    meta = current["meta"] or {}

    # 1. Archive old subpages
    for sp_id in meta.get("day_subpage_ids", []):
        try:
            archive_page(api_key, sp_id)
        except SystemExit:
            print("Warning: could not archive day subpage {0}".format(sp_id), file=sys.stderr)

    for sp_id in (meta.get("thematic_subpage_ids") or {}).values():
        if sp_id:
            try:
                archive_page(api_key, sp_id)
            except SystemExit:
                print("Warning: could not archive thematic subpage {0}".format(sp_id), file=sys.stderr)

    # 2. Delete nav/checklist/old-day blocks from main page
    blocks_to_delete = _identify_deletable_blocks(blocks)
    for bid in blocks_to_delete:
        delete_block(api_key, bid)

    # 3. Clear and repopulate database
    if database_id:
        clear_database_rows(api_key, database_id)
        rows_created = populate_database(api_key, database_id, data)
    else:
        database_id = create_itinerary_database(api_key, page_id, data, lang)
        rows_created = populate_database(api_key, database_id, data)

    # 4. Create new day subpages
    day_subpage_ids = []
    for day_data in data.get("daily_itinerary", []):
        sp_id = create_day_subpage(api_key, page_id, day_data, lang)
        day_subpage_ids.append(sp_id)

    # 5. Create new thematic subpages
    food_id = create_food_subpage(api_key, page_id, data, lang)
    transport_id = create_transport_subpage(api_key, page_id, data, lang)
    budget_id = create_budget_subpage(api_key, page_id, data, lang)
    thematic_ids = {"food": food_id, "transport": transport_id, "budget": budget_id}

    # 6. Append new nav blocks + checklist
    nav_blocks = []
    nav_blocks.append(divider())
    nav_blocks.append(heading(2, L["daily_nav_heading"]))
    for sp_id in day_subpage_ids:
        nav_blocks.append(link_to_page(sp_id))
    nav_blocks.append(divider())
    # Database already exists in page — it stays in place
    nav_blocks.append(heading(2, L["thematic_nav_heading"]))
    nav_blocks.append(link_to_page(food_id))
    nav_blocks.append(link_to_page(transport_id))
    nav_blocks.append(link_to_page(budget_id))
    nav_blocks.append(divider())
    nav_blocks.extend(build_checklist_blocks(data.get("packing_checklist", []), lang))

    _append_blocks_batched(api_key, page_id, nav_blocks)

    # 7. Update overview callout
    refreshed_blocks = read_page_blocks(api_key, page_id)
    for block in refreshed_blocks:
        if block.get("type") == "callout":
            text = extract_plain_text(block.get("callout", {}).get("rich_text", []))
            if "Destination" in text or "目的地" in text:
                new_callout = build_overview_callout(data, lang)
                notion_request("PATCH", "/blocks/{0}".format(block["id"]), api_key,
                               {"callout": new_callout["callout"]})
                break

    # Update page title
    dest = data["destination"]
    dates = data["dates"]
    new_title = L["page_title"].format(
        city=dest.get("city", ""), city_local=dest.get("city_local", ""),
        start=dates["start"], end=dates["end"])
    notion_request("PATCH", "/pages/{0}".format(page_id), api_key, {
        "properties": {"title": {"title": [{"type": "text", "text": {"content": new_title}}]}}
    })

    # Save metadata and update registry
    canonical_path = None
    if itinerary_path:
        _, canonical_path = save_metadata(page_id, database_id, itinerary_path,
                                          day_subpage_ids, thematic_ids)
    page_url = "https://notion.so/{0}".format(page_id.replace("-", ""))
    register_trip(page_id, page_url, data, canonical_path)

    total_pois = sum(len(d.get("pois", [])) for d in data.get("daily_itinerary", []))
    total_meals = sum(len(d.get("meals", [])) for d in data.get("daily_itinerary", []))
    total_days = len(data.get("daily_itinerary", []))

    return {
        "page_id": page_id,
        "database_id": database_id,
        "day_subpage_ids": day_subpage_ids,
        "thematic_subpage_ids": thematic_ids,
        "summary": "Updated {0}-day itinerary for {1}: {2} POIs, {3} meals, {4} database rows, "
                   "{0} day subpages, 3 thematic subpages.".format(
                       total_days, dest["city"], total_pois, total_meals, rows_created),
        "stats": {
            "days": total_days,
            "pois": total_pois,
            "meals": total_meals,
            "database_rows": rows_created,
            "blocks_deleted": len(blocks_to_delete),
            "subpages_created": total_days + 3,
        },
    }


# ── Main page creation ────────��─────────────────────────────────────────────

def create_travel_page(api_key, parent_page_id, data, itinerary_path=None, lang=None):
    lang = lang or data.get("lang", "zh-TW")
    L = get_lang_pack(lang)
    dest = data["destination"]
    dates = data["dates"]

    title = L["page_title"].format(
        city=dest.get("city", ""), city_local=dest.get("city_local", ""),
        start=dates["start"], end=dates["end"])

    cover_query = data.get("cover_query", "{0} travel".format(dest["city"]))
    cover_url = get_unsplash_cover(cover_query)

    # Step 1: Create main page with overview + tips
    children = []
    children.append(build_overview_callout(data, lang))
    children.extend(build_tips_blocks(data.get("travel_tips", []), lang))
    children.append(divider())

    first_batch = children[:100]
    remaining_init = children[100:]

    page_payload = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "icon": {"type": "emoji", "emoji": "🗺️"},
        "cover": {"type": "external", "external": {"url": cover_url}},
        "properties": {
            "title": {"title": [{"type": "text", "text": {"content": title}}]}
        },
        "children": first_batch,
    }

    page_result = notion_request("POST", "/pages", api_key, page_payload)
    page_id = page_result["id"]
    page_url = page_result["url"]

    if remaining_init:
        _append_blocks_batched(api_key, page_id, remaining_init)

    # Step 2: Create day subpages
    day_subpage_ids = []
    for day_data in data.get("daily_itinerary", []):
        sp_id = create_day_subpage(api_key, page_id, day_data, lang)
        day_subpage_ids.append(sp_id)

    # Step 3: Append daily navigation
    nav_blocks = [heading(2, L["daily_nav_heading"])]
    for sp_id in day_subpage_ids:
        nav_blocks.append(link_to_page(sp_id))
    nav_blocks.append(divider())

    _append_blocks_batched(api_key, page_id, nav_blocks)

    # Step 4: Create inline database (appears here in block order)
    db_id = create_itinerary_database(api_key, page_id, data, lang)
    rows_created = populate_database(api_key, db_id, data)

    # Step 5: Create thematic subpages
    food_id = create_food_subpage(api_key, page_id, data, lang)
    transport_id = create_transport_subpage(api_key, page_id, data, lang)
    budget_id = create_budget_subpage(api_key, page_id, data, lang)
    thematic_ids = {"food": food_id, "transport": transport_id, "budget": budget_id}

    # Step 6: Append thematic navigation + checklist
    tail_blocks = [divider()]
    tail_blocks.append(heading(2, L["thematic_nav_heading"]))
    tail_blocks.append(link_to_page(food_id))
    tail_blocks.append(link_to_page(transport_id))
    tail_blocks.append(link_to_page(budget_id))
    tail_blocks.append(divider())
    tail_blocks.extend(build_checklist_blocks(data.get("packing_checklist", []), lang))

    _append_blocks_batched(api_key, page_id, tail_blocks)

    # Step 7: Save metadata and register trip
    canonical_path = None
    if itinerary_path:
        _, canonical_path = save_metadata(page_id, db_id, itinerary_path,
                                          day_subpage_ids, thematic_ids)
    register_trip(page_id, page_url, data, canonical_path)

    total_pois = sum(len(d.get("pois", [])) for d in data.get("daily_itinerary", []))
    total_meals = sum(len(d.get("meals", [])) for d in data.get("daily_itinerary", []))
    total_days = len(data.get("daily_itinerary", []))

    return {
        "page_url": page_url,
        "page_id": page_id,
        "database_id": db_id,
        "day_subpage_ids": day_subpage_ids,
        "thematic_subpage_ids": thematic_ids,
        "itinerary_path": canonical_path,
        "summary": "Created {0}-day itinerary for {1} with {2} POIs, {3} meals, {4} database rows, "
                   "{0} day subpages, 3 thematic subpages.".format(
                       total_days, dest["city"], total_pois, total_meals, rows_created),
        "stats": {
            "days": total_days,
            "pois": total_pois,
            "meals": total_meals,
            "database_rows": rows_created,
            "subpages_created": total_days + 3,
        },
    }


# ── CLI ──���──────────────────────────���───────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Create or update a Notion travel itinerary.")
    parser.add_argument("--api-key", help="Notion integration API key (required except --list-trips)")
    parser.add_argument("--parent-page-id", help="Parent Notion page ID (for create)")
    parser.add_argument("--itinerary", help="Path to itinerary JSON file")
    parser.add_argument("--read-page", help="Read an existing page and output current state as JSON")
    parser.add_argument("--update-page", help="Update an existing page with new itinerary data")
    parser.add_argument("--list-trips", action="store_true", help="List all registered trips")
    parser.add_argument("--lang",
                        help="UI language override: zh-TW, en, ja (default: read from itinerary JSON 'lang' field)")
    args = parser.parse_args()

    lang = args.lang  # None means "read from JSON", which defaults to zh-TW

    if args.list_trips:
        registry = load_registry()
        print(json.dumps(registry, indent=2, ensure_ascii=False))
        return

    if not args.api_key:
        print("Error: --api-key is required", file=sys.stderr)
        sys.exit(1)

    if args.read_page:
        result = read_existing_itinerary(args.api_key, args.read_page)
        # Simplify output for readability
        output = {
            "page_id": result["page_id"],
            "database_id": result["database_id"],
            "block_count": len(result["blocks"]),
            "database_row_count": len(result["database_rows"]),
            "blocks": result["blocks"],
            "database_rows": result["database_rows"],
        }
        if result["meta"]:
            output["meta"] = result["meta"]
        print(json.dumps(output, indent=2, ensure_ascii=False))

    elif args.update_page:
        if not args.itinerary:
            print("Error: --itinerary is required for --update-page", file=sys.stderr)
            sys.exit(1)
        with open(args.itinerary, "r", encoding="utf-8") as f:
            data = json.load(f)
        result = update_travel_page(args.api_key, args.update_page, data, args.itinerary, lang)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    else:
        if not args.parent_page_id or not args.itinerary:
            print("Error: --parent-page-id and --itinerary are required for create",
                  file=sys.stderr)
            sys.exit(1)
        with open(args.itinerary, "r", encoding="utf-8") as f:
            data = json.load(f)
        result = create_travel_page(args.api_key, args.parent_page_id, data, args.itinerary, lang)
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
