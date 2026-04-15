# Travel Planner Skills

三個 Claude Code Skills 組成的旅遊規劃管線，從一句話描述到完整的 Notion 行程頁面。

```
使用者輸入 (URL / 地名 / 旅行描述)
       ↓
  Explorer ── 解析 URL 或地名，輸出結構化 POI JSON
       ↓
  Navigator ── 地理分群、路線最佳化、時段排程
       ↓
  Claude Agent ── 填入主題、挑選餐廳、撰寫交通備註
       ↓
  Travel Planner ── 推送至 Notion（含封面、子頁面、資料庫）
```

## Skills 總覽

### Explorer

從 Google Maps 連結、Tabelog、TripAdvisor 等 URL 或純文字地名擷取 POI 資料。

- 支援 7+ 種 URL 格式（含短網址自動展開）
- 透過 Google Places API (New) 取得名稱、座標、營業時間、預算等
- 自動推估造訪時間與預算（日圓 / 台幣）

```bash
python explorer/scripts/explorer.py --url "https://maps.google.com/..." --city "Tokyo"
```

### Navigator

將 POI 清單最佳化為每日行程，或將新景點插入既有行程。

**最佳化模式** — 將 N 個 POI 分群至 M 天，以地理鄰近度排序並指派時段：

```bash
python navigator/scripts/navigator.py optimize \
  --pois pois.json --city "Tokyo" --days 5 --start-date 2026-05-15
```

**插入模式** — 找到干擾最小的插入位置：

```bash
python navigator/scripts/navigator.py insert \
  --trip "Tokyo" --new-poi teamlab.json
```

- 使用 Google Distance Matrix API 取得真實交通時間
- API 無法使用時自動 fallback 至直線距離估算
- 座標快取於 `~/.travel-planner/geocache.json`

### Travel Planner

將行程 JSON 推送至 Notion，產生完整頁面結構：

- 主頁面（封面圖、行程總覽、導航連結）
- 每日子頁面（景點、餐食、交通細節）
- 美食攻略 / 交通攻略 / 預算總覽 三個主題頁
- Inline Database（日期、景點、分類、時段、預算、狀態）
- 打包清單（雙語 to-do）

```bash
# 建立
python travel-planner/scripts/notion_create_page.py \
  --api-key $NOTION_API_KEY --parent-page-id $NOTION_PARENT_PAGE_ID \
  --itinerary itinerary.json

# 更新（僅重建有變更的天數）
python travel-planner/scripts/notion_create_page.py \
  --api-key $NOTION_API_KEY --update-page PAGE_ID --itinerary itinerary.json

# 列出所有行程
python travel-planner/scripts/notion_create_page.py --list-trips
```

## 環境需求

- Python 3.11+（無第三方套件，純 stdlib）
- 環境變數：
  - `NOTION_API_KEY` — Notion integration token
  - `NOTION_PARENT_PAGE_ID` — 行程頁面的父頁面 ID
  - `GOOGLE_MAPS_API_KEY` — Google Maps Platform API key（Explorer / Navigator 使用）
- 選配：安裝 `rclone` 並設定名為 `travel-planner` 的 remote，可自動雲端同步 `~/.travel-planner/`

## 多語系支援

行程 JSON 中的 `lang` 欄位支援三種語系：

| 值 | 語系 |
|---|---|
| `zh-TW` | 繁體中文（預設） |
| `en` | English |
| `ja` | 日本語 |

所有 Notion 頁面 UI、欄位標題、打包清單皆依語系切換。

## 本地資料結構

```
~/.travel-planner/
├── registry.json          # 所有行程索引
├── geocache.json          # 座標快取
├── itineraries/           # 行程 JSON 檔
└── <page_id>.meta.json    # 各行程的 Notion metadata
```

## 授權條款

Private — 僅供個人使用。
