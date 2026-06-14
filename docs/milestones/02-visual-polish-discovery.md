# Milestone 2 — Visual Polish, Discovery & Shareable Deals

**Status:** ✅ Shipped (2026-06-14). All four workstreams built, tested, and deployed.
**Predecessor:** M1 — built + shipped + on autopilot (Editorial Luxe typographic site, 180+ live deals, daily cron).

## Outcome (what actually shipped)
- **Visual system:** `BrandMark.astro` — every one of 182 cards now has a header visual:
  a real brand **logo** where a domain resolved, otherwise a deterministic Fraunces-monogram
  tile (6 on-brand palettes × 3 motifs, seeded by slug, zero network). Also a logo chip on
  featured-carousel slides.
- **Logos:** `ingest/resolve_logos.py` (DNS-prechecked heuristic `.com`/`.qa` guesses →
  parked-domain + dining + local gates → own apple-touch-icon/favicon, hotlinked) +
  `db.py --load-logos` + a best-effort cron step. **First run: 11/124 venues (~9%)** at
  *high precision* (false positives like elixir.com/restaurant.com deliberately rejected —
  a wrong logo is worse than none). Monogram covers the other 113. Hit rate climbs over time
  as the cron re-attempts (`--limit 60`/day, 14-day miss cache) and `--ddg` can be enabled.
- **Discovery:** segmented sort (Ending soon · Top % off · Lowest price · Surprise me) that
  reorders the grid client-side, persists in localStorage; removable active-filter chips.
- **Per-deal pages:** 182 static `/deal/{id}/` pages, each with its own title / meta /
  canonical / Open Graph (logo as OG image when available) / Twitter / JSON-LD `Offer`, a
  Web-Share button (clipboard fallback + toast), and a "View original offer →" to the source.
  Cards link inward to these pages.
- Build: **183 pages**, green. Legal guardrail intact — logos + generated tiles only, never
  the copyrighted promo creatives.

## Goal
Make the site feel *richer and more browsable* without breaking the legal foundation that
made M1 possible. Three workstreams: a **visual identity per venue**, **discovery & sorting**,
and **shareable per-deal pages**.

## The guardrail (non-negotiable — read before building visuals)
Under **Qatar Copyright Law 7/2002**, a restaurant's *promotional creative* for an offer
(the designed banner, the food photo) is copyrighted. M1 went typographic specifically to
avoid copying those. This milestone does **not** change that. It adds visuals from the two
*defensible* sources only:

| Source | Legal basis | Use |
| --- | --- | --- |
| Brand **logo** | trademark, *nominative/identification* use (what Google/Yelp/Zomato do) | ✅ when a domain resolves |
| **Generated** monogram/pattern tile | we authored it | ✅ universal fallback |
| Offer **promo image** | copyrighted creative | 🚫 never copied — we keep linking to source |

Decided with the user: **logos where resolvable, generated tile everywhere else, no promo-creative copying.**

---

## Workstream 1 — Visual system (logo + generated fallback)

### Components
- **`web/src/components/BrandMark.astro`** — single reusable visual. Props `{ name, slug, logoUrl, size }`.
  - If `logoUrl` present → `<img loading="lazy" decoding="async">` with the venue name as alt, wrapped in a tasteful frame (thin gold ring, cream pad).
  - Else → inline **SVG monogram tile**: 1–2 initials in Fraunces over a deterministic field.
    - Palette + pattern chosen by hashing `slug` into a **curated** set of on-brand pairs
      (maroon/gold/cream variants — never rainbow). Faint ◆ / diagonal-rule motif echoing the
      carousel. Pure SVG/CSS, **zero network**, never fails.
  - Used in `DealCard.astro` (card header) and `FeaturedCarousel.astro` (slide corner).

### Logo resolution (best-effort, cached, tiered)
New **`ingest/resolve_logos.py`** (network/bs4, like `fetch_deal_sites.py`). Reads venues
missing a logo from `data/deals.json`; for each, tries in order, stops on first hit:
1. **Heuristic domain guess + verify** — `{slug}.com`, `{slug}.qa`, `{slug}.com.qa` (dashes
   stripped variants); GET with browser UA, accept only if the page `<title>`/`og:site_name`
   contains the venue name. Cheap, no external search, good for chains/known brands.
2. **DuckDuckGo Lite** (`lite.duckduckgo.com/lite/`, no-JS, no key) first organic result →
   domain, same verify. Last resort; tolerant of failure.
3. On a verified domain, prefer the site's own `apple-touch-icon` / `og:image` / `link[rel=icon]`;
   else fall back to **`https://www.google.com/s2/favicons?domain={d}&sz=128`** (free, no key).
   We **hotlink** the final URL (nominative use; no re-hosting of brand assets).

Writes `data/logos.json` (`slug → { logo_url, domain }`). Caches misses in
`data/logo_misses.json` with a date so the daily cron doesn't re-hammer failures
(retry only after N days). **Honest expectation:** hit rate likely ~25–45% of 124 venues;
the generated tile carries the rest. That's the point of the fallback.

### Persistence
- **`db.py --load-logos`** — UPSERTs `logo_url` into `restaurants` (mirrors the
  `scraped_deals.json → --load-scraped` pattern; keeps `db.py` itself stdlib-only by reading
  a JSON the resolver produced). COALESCE already protects existing values.

### Cron
`refresh-data.yml` gains one step after `--load-scraped`: run `resolve_logos.py` then
`db.py --load-logos` (before `--export-json`). Best-effort; a failure never blocks the run.

---

## Workstream 2 — Discovery & sorting

### Sort control
A segmented control beside the filter bar (bilingual, RTL-safe):
**Ending soon · Biggest discount · Lowest price · Surprise me**.
- Implemented client-side by **reordering grid DOM nodes** (the grid is already a flat list of
  `[data-card]`). Add render-time `data-discount` and a client-computed `data-days` (the expiry
  loop already computes days — store it on the node). Nulls sort last.
- **Surprise me** = Fisher–Yates shuffle (browser `Math.random` is fine) + briefly spotlight
  the top card.
- Sort runs after filtering so only visible cards reorder; persists in `localStorage`.

### Tighter filter UX
- **Active-filter chips** under the bar: one removable chip per active filter + "Clear all"
  (Reset stays). Makes current state legible when several filters stack.
- Keep all existing filters (search · cuisine · area · price · type · channel).

Files: `web/src/pages/index.astro` (markup + client script only — no data changes).

---

## Workstream 3 — Per-deal detail + share

### Static per-deal pages
- **`web/src/pages/deal/[id].astro`** via `getStaticPaths()` over `deals.json` (~180 pages,
  trivial for a static build). Each renders: BrandMark, restaurant name, title/description,
  discount **or** price block, code, area/cuisine, client-recomputed expiry (Qatar time),
  **"View original offer →"** (source_url, the only outbound copy path), and a back link.
- Its own `<title>`, meta description, canonical, per-deal **Open Graph/Twitter** tags, and
  JSON-LD **`Offer`**. Extend `Layout.astro` to accept optional `ogImage` (default stays
  `icon.svg`); per-deal OG image = resolved logo if any, else site icon.
- **Routing change:** the card's main body becomes a link to `/deal/{id}/` (internal — better
  SEO + a real share target); the explicit **"View original →"** to `source_url` stays on both
  card footer and detail page. "via {source}" attribution stays.

### Share
- **`navigator.share()`** (Web Share API) with **copy-link** fallback, on both the card (small
  ghost icon) and the detail page. Shares the per-deal URL + title; the per-deal OG tags make
  WhatsApp/iMessage cards look intentional.
- *Out of scope (flagged):* build-time generated **OG images** (satori/@vercel-og style PNG per
  deal). High polish, real dependency cost — revisit only if share cards feel weak with logo/icon.

---

## Build sequence
1. **Generated tile first** — `BrandMark.astro` with monogram fallback only; wire into DealCard
   + Carousel. Site instantly looks more visual, zero network risk. *(de-risks the milestone)*
2. **Logo resolver** — `resolve_logos.py` + `db.py --load-logos` + cron step; logos layer on top.
3. **Sort + filter chips** — index.astro client work.
4. **Per-deal pages + share** — `deal/[id].astro`, Layout OG extension, card routing, share button.

Each step ships independently and leaves the site in a working state.

## Verification
- `BrandMark` renders a tile for every venue with **no `logo_url`**; an `<img>` when present;
  initials/colour stable across reloads for a given slug.
- `python ingest/resolve_logos.py` writes `data/logos.json`; `db.py --load-logos` populates
  rows; re-running resolves only still-missing venues (cache honoured). Run logs report hit rate.
- Sort reorders visible cards correctly (incl. nulls-last); persists; interplays with filters;
  RTL unaffected. Chips add/remove filters and stay in sync with controls.
- `npm run build` emits `/deal/{id}/index.html` per active deal; each has unique title +
  canonical + OG + JSON-LD `Offer`; "View original →" points to `source_url`; share works
  (Web Share where supported, clipboard fallback elsewhere).
- Lighthouse: no regression; images lazy-load; no layout shift from tiles.

## Out of scope (YAGNI for M2)
Promo-creative copying (legal), per-deal generated OG PNGs (deferred), more data sources
(separate milestone), maps, user accounts, push.
