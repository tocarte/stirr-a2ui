# SEO-1.11 — Local News Market Pages (A2UI-Powered)

**Status:** Draft spec for review
**Pilot market:** Albany, NY (WNYT — NBC affiliate)
**Owners:** stirr-a2ui (agent + tools + catalog), stirr-platform-nextgen (renderer + routes)
**Related:** [a2ui-overview.md](../architecture/a2ui-overview.md), D12, D12b

---

## 1. Purpose

Build a differentiated local news landing page experience that ranks for "[city] local news live," "free [city] news streaming," and related PAA queries. Unlike static market pages, the A2UI-rendered page combines live channel data (VODLIX) with real-time streaming intelligence (weather, traffic, alerts) fetched from external APIs through the A2A agent.

**Why A2UI:** A static page competes weakly against station websites. An A2UI page offers live data the stations don't aggregate, and delivers unique fresh content on every crawl — strong signals for both SEO and GEO (AI citation).

---

## 2. Pilot Market: Albany, NY

**Primary affiliate:** WNYT (NBC, channel 13, Albany DMA #58)
**STIRR channel page:** `/live/{id}/wnyt-albany-ny` (confirm id in VODLIX)
**HLS URL pattern:** Already reverse-engineered for Amagi channels — see `_epg_channel_id_to_hls_url` in `stirr-a2ui/agent/tools.py`
**Reference file:** `stirr-control/docs/VODLIX_NATIVE_HLS_FINDINGS.md`

**Why Albany first:**
- WNYT is the reference station for the Amagi HLS pattern (already validated)
- Albany is referenced as the example in the `WeatherWidget` catalog schema
- Mid-size DMA (#58) — representative, not overrepresented in tests
- Low competitive risk for the pilot

---

## 3. URL & Route Structure

```
/local-news/{state-slug}/{city-slug}/
```

**Examples:**
- `/local-news/ny/albany/` — pilot
- `/local-news/ny/rochester/`
- `/local-news/ca/los-angeles/`
- `/local-news/tx/dallas/`

**Canonical:** Self-referencing. Each market page is canonical for its own URL.

**Sitemap:** Add to `sitemap-local-news.xml` (child of main sitemap index). One entry per market page. `lastmod` updated on schedule refresh.

**Robots:** Allowed. Not blocked like `/contentLists/`.

**Renderer:** Server-side render via Lit in `stirr-platform-nextgen`. Route handler resolves market slug → DMA config → calls A2A agent → composes A2UI surface → SSRs to HTML with `<script type="application/ld+json">` schema injected.

---

## 4. A2UI Surface Composition

A single market page surface contains the following components (all already defined in `stirr_catalog.json` except where noted):

```
Column
├── NewsAlertBanner        [conditional — only if active breaking news]
├── VideoPlayer             [primary affiliate live stream]
├── ChapterNav              [today's newscast schedule]
├── ContentShelf            [all STIRR channels serving this market]
├── Row
│   ├── WeatherWidget      [market location]
│   └── TrafficWidget      [market location]
└── ConversationalSearch    [localized: "Ask about Albany"]
```

**Component reuse:** No new catalog entries required for the pilot. All widgets exist.

**Optional Phase 2 catalog additions:**
- `StationCard` — station name, network, call letters, DMA rank, link to live
- `MarketFactSheet` — structured facts block (population, counties, neighboring DMAs) for GEO entity density

---

## 5. Agent Prompt

The A2A agent receives a market context and generates the A2UI surface.

**Input:**
```json
{
  "intent": "local_news_market_page",
  "market": {
    "slug": "albany-ny",
    "city": "Albany",
    "state": "NY",
    "dma_rank": 58,
    "dma_name": "Albany-Schenectady-Troy",
    "counties": ["Albany", "Rensselaer", "Schenectady", "Saratoga", "Warren", "Washington"],
    "neighboring_dmas": ["New York, NY", "Syracuse, NY", "Burlington, VT"]
  },
  "affiliate": {
    "call_letters": "WNYT",
    "network": "NBC",
    "epg_channel_id": "amg01942-amg01942c5",
    "stirr_url": "https://stirr.com/live/{id}/wnyt-albany-ny"
  }
}
```

**System prompt (high level):**
> You are composing an A2UI surface for a STIRR local news market page. Use only components from the stirr-intent catalog. Fetch live data via the provided tools. Compose in this order: NewsAlertBanner (only if alerts are active), VideoPlayer for the primary affiliate, ChapterNav for today's schedule, ContentShelf of all STIRR channels in this market, a Row containing WeatherWidget and TrafficWidget for the market location, and a localized ConversationalSearch. Use entity-rich, fact-forward Text labels. Populate all fields; prefer specificity over generic phrasing.

**Output:** A2UI JSON surface document compliant with v0.8, `catalogId: "stirr-intent"`.

---

## 6. New Tools Required in `agent/tools.py`

Existing tools in `tools.py` handle VODLIX content and HLS construction. The pilot requires three new tool functions:

### 6.1 `get_weather(location: str) → dict`

**Data source:** National Weather Service API (https://api.weather.gov) — free, government, no API key, commercial-use allowed.

**Returns:** `{ location, temp_f, condition, forecast, humidity, alerts[], summary }` — matches `WeatherWidget` schema.

**Caching:** 15 min TTL. Cache key: `weather:{lat,lon}`.

### 6.2 `get_traffic(location: str) → dict`

**Data source options (pick one):**
- **Google Maps Roads / Distance Matrix** — most accurate, requires API key + usage cost
- **HERE Traffic API** — free tier 250K requests/month, recommended for pilot
- **TomTom Traffic** — free tier 2,500 requests/day

**Recommendation:** HERE for pilot (highest free tier).

**Returns:** `{ location, conditions, delays[], accidents[], summary }` — matches `TrafficWidget` schema.

**Caching:** 5 min TTL.

### 6.3 `get_news_alerts(market_slug: str) → list[dict]`

**Data source options:**
- **NewsAPI.org** — free tier 100 requests/day, limited to 24h old articles (insufficient for breaking news)
- **GDELT 2.0** — free, global news events, 15-min update cadence (best fit)
- **Station RSS feeds** — direct from affiliate sites (e.g., https://wnyt.com/feed/) — free, most local, requires per-station config

**Recommendation:** Hybrid — GDELT for breaking/urgent, station RSS for local coverage.

**Returns:** `[{ headline, summary, iconName, timestamp, source }, ...]` — each entry renders as a `NewsAlertBanner`. Return empty list when no active alerts; renderer skips the component.

**Caching:** 5 min TTL for GDELT, 15 min for station RSS.

### 6.4 `get_schedule(affiliate_call_letters: str, date: str) → list[dict]`

**Data source options:**
- **Gracenote Schedules Direct API** — authoritative, licensed, paid
- **XMLTV feeds** — aggregated EPG data, some free
- **Station website scraping** — fragile, per-station
- **VODLIX EPG** — if STIRR already ingests schedule data for the live player, reuse it

**Recommendation:** Check VODLIX first. If EPG data is already in VODLIX for live channels, no new external source needed.

**Returns:** `[{ title, timestamp, action }, ...]` — matches `ChapterNav.chapters` schema.

---

## 7. Data Config: DMA ↔ Affiliate Map

New config file: `stirr-a2ui/config/dma_market_map.json`

**Structure:**
```json
{
  "albany-ny": {
    "city": "Albany",
    "state": "NY",
    "state_slug": "ny",
    "dma_rank": 58,
    "dma_name": "Albany-Schenectady-Troy",
    "counties": ["Albany", "Rensselaer", "Schenectady", "Saratoga", "Warren", "Washington"],
    "coordinates": { "lat": 42.6526, "lon": -73.7562 },
    "primary_affiliate": {
      "call_letters": "WNYT",
      "network": "NBC",
      "epg_channel_id": "amg01942-amg01942c5",
      "vodlix_channel_id": "TBD"
    },
    "related_channels": []
  }
}
```

**Pilot scope:** Albany only. Expand to top 20 DMAs once pilot validates.

**Source for mapping:** Cross-reference VODLIX channel list with Nielsen DMA rankings. May need a one-time manual reconciliation pass (~20 entries).

---

## 8. SEO / GEO Output Requirements

**On-page HTML requirements (SSR output):**

1. `<title>` — "[City] Local News Live — Watch Free on STIRR"
2. `<meta name="description">` — "Watch free live local news from [City, State]. [Affiliate call letters] [network] live stream, weather, traffic, and breaking alerts on STIRR — no subscription required."
3. `<link rel="canonical">` — self-referencing
4. `<h1>` — "Watch [City] Local News Free on STIRR"
5. JSON-LD schema blocks:
   - `BroadcastService` — the affiliate
   - `LocalBusiness` — the station (if data available)
   - `Place` — the market/city as an entity
   - `FAQPage` — generated from intent-level FAQs ("How do I watch [city] news for free?", "What news stations are available on STIRR in [city]?")
   - `ItemList` — list of STIRR channels serving the market

**GEO requirements:**
- Every fact rendered as a standalone sentence or table cell (not buried in prose)
- Entity labels (city, DMA, call letters, network) appear in at least 3 places each
- Fresh data (weather, traffic, alerts) changes across crawls — signals freshness to AI models
- All linked content uses descriptive anchor text

---

## 9. Phase Plan

**Phase 0 — Spec & alignment (this document):** 1 day
**Phase 1 — Albany pilot:**
- Add `get_weather` tool (NWS API) — 1 day
- Add `get_traffic` tool (HERE API signup + integration) — 2 days
- Add `get_news_alerts` tool (GDELT + WNYT RSS) — 2 days
- Confirm schedule source (VODLIX EPG or external) — 0.5 day
- Build `dma_market_map.json` with Albany entry — 0.5 day
- Agent prompt + surface composition logic — 2 days
- Renderer route in stirr-platform-nextgen — 3 days
- SSR + schema injection — 2 days
- Deploy to staging, test — 2 days
- Google Rich Results Test validation — 0.5 day

**Phase 1 total:** ~2 weeks.

**Phase 2 — Top 20 markets:** Clone Albany pattern with new config entries. Monitor rankings for 30 days. 1 week.

**Phase 3 — Full 185 DMAs:** Industrial build. Per D12 / D12b, port Python agent to Node.js if production scale requires it. Timing TBD.

---

## 10. Open Questions

1. **VODLIX EPG** — does VODLIX already expose newscast schedule data per channel? If yes, `get_schedule` is a VODLIX call, not external.
2. **Renderer SSR** — can the Lit renderer in `stirr-platform-nextgen` server-render for crawlers? If renderer is client-only, Google's WRS should still handle it, but SSR is stronger for SEO.
3. **Traffic API budget** — HERE free tier sufficient for pilot, but top-20 scale may exceed it. Confirm budget approval.
4. **Station RSS licensing** — confirm with content team that pulling headlines from affiliate RSS feeds for display is within partnership terms.
5. **DMA ↔ STIRR channel reconciliation** — who owns this mapping data, and where does it live?

---

## 11. Next Steps

1. Review this spec with stirr-platform-nextgen and stirr-a2ui owners
2. Resolve open questions (§10)
3. Green-light Albany pilot (§9, Phase 1)
4. Update `stirr-control/TASKS.md` SEO-1.11 with spec reference and phase plan
