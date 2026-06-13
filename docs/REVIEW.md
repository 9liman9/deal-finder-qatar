# Phase A — Deep Code Review

**Reviewed:** 2026-06-13
**Depth:** deep (cross-file: data layer → JSON → Astro templates → runtime i18n → service worker)
**Reviewer:** Claude (gsd-code-reviewer)
**Status:** issues_found

## Scope

Reviewed the full Phase A surface: `ingest/db.py` (data layer), the three Astro templates
(`index.astro`, `Layout.astro`, `DealCard.astro`), the hand-written service worker, the build
sync script, Astro config, the deploy workflow, and the seed data. Reviewed against the stated
constraints: zero user PII, mandatory deal auto-expiry (Qatar legal requirement), bilingual
EN/AR + RTL, free + zero-maintenance, and the fact that **Phase B will pipe untrusted Instagram
caption text through these same templates** — so escaping was scrutinised as if all deal/
restaurant fields were attacker-controlled.

Phase B's absence (`fetch_instagram.py`, `extract_offers.py`) was **not** flagged — it is
intentionally deferred.

## Findings summary

| Severity | Count |
|----------|-------|
| 🔴 Critical (P0) | 3 |
| 🟠 High (P1) | 5 |
| 🟡 Medium (P2) | 7 |
| 🟢 Low (P3) | 6 |
| **Total** | **21** |

---

## 🔴 Critical (P0)

### CR-01 — `javascript:`/`data:` URL injection in `source_url` href (stored XSS via Phase B)
**File:** `web/src/components/DealCard.astro:115`

```astro
{deal.source_url && (
  <a href={deal.source_url} target="_blank" rel="noopener" ...>
```

Astro HTML-escapes attribute values (quotes/angle brackets), so attribute breakout is prevented,
but it does **not** validate the URL *scheme*. A `source_url` of `javascript:alert(document.cookie)`
(or `data:text/html,...`) is rendered verbatim into the `href` and executes on click. Today
`source_url` is hand-seeded, but in Phase B it will be derived from scraped Instagram data — the
exact untrusted path the review brief warns about. This is a stored-XSS hole waiting for Phase B.

**Fix:** Allowlist the scheme at the boundary. In `DealCard.astro` frontmatter:
```ts
function safeUrl(u: unknown): string | null {
  if (typeof u !== "string") return null;
  try {
    const parsed = new URL(u, "https://example.invalid");
    return /^https?:$/.test(parsed.protocol) ? u : null;
  } catch { return null; }
}
const sourceUrl = safeUrl(deal.source_url);
```
then `{sourceUrl && (<a href={sourceUrl} ...>)}`. Better still, also sanitise/validate in
`ingest/db.py` on insert so the DB never stores a non-http(s) `source_url`.

### CR-02 — Unvalidated `ig_handle` interpolated into Instagram href (open-redirect / off-site link)
**File:** `web/src/components/DealCard.astro:111`

```astro
<a href={`https://instagram.com/${r.ig_handle}`} ...>@{r.ig_handle}</a>
```

`ig_handle` is concatenated raw into the URL path. Angle brackets/quotes are escaped so no
attribute breakout, but a scraped handle like `../../evil.com/x`, `?next=//evil.com`, or one
containing `/` sends users to an attacker-chosen Instagram path or breaks the link. A handle of
`@foo` (with stray `@`) produces `instagram.com/@foo`. With Phase B feeding handles parsed from
captions, this becomes an attacker-controlled link target on a deal card the user trusts.

**Fix:** Validate against Instagram's real handle charset and strip a leading `@` before building
the URL:
```ts
const handle = String(r.ig_handle ?? "").replace(/^@/, "");
const igOk = /^[A-Za-z0-9._]{1,30}$/.test(handle);
```
Only render the anchor when `igOk`, and use `https://instagram.com/${encodeURIComponent(handle)}`.

### CR-03 — Expiry comparison is string-based on inconsistent date formats → legally-stale deals can leak
**File:** `ingest/db.py:223-231` (`cmd_expire`), interacting with `:226`

```python
"UPDATE deals SET status='expired' WHERE valid_to IS NOT NULL AND valid_to < ? AND status='active'"
```

The comparison is a **lexicographic string compare** of `valid_to` against `date.today().isoformat()`
(`YYYY-MM-DD`). This is correct *only if every `valid_to` is exactly a 10-char `YYYY-MM-DD` string*.
Nothing enforces that: `valid_to` is a free-form `TEXT` column (`db.py:71`), seed/scraped values
could be `2026-7-5` (no zero-pad), `2026/07/05`, `15-07-2026`, or an ISO datetime
`2026-07-15T23:59:00`. Any of those break the ordering — e.g. `"2026-7-5" < "2026-06-13"` is
**true** lexically (the `-7` sorts before `-0`), so a deal valid until July would be wrongly
expired; conversely `"2026-7-5"` vs a today of `"2026-12-01"` compares wrong the other way and a
genuinely expired deal stays **active**. Serving an expired deal is the specific legal violation
called out in the brief. Auto-expiry being mandatory makes this a P0.

There is also a **timezone gap**: `today_str()` uses `date.today()` (server/runner local date) while
the rest of the file is UTC (`now_iso()`). On the GitHub-Actions UTC runner vs. Qatar (UTC+3) the
"today" boundary is off by up to 3 hours, so a deal can be served for a few hours past its Qatar
midnight expiry.

**Fix:** (1) Normalise and validate `valid_to` to strict `YYYY-MM-DD` on insert (`insert_deal`),
rejecting/parking malformed rows. (2) Make the expiry boundary explicit and Qatar-anchored:
compare against "today in Asia/Qatar" (`datetime.now(ZoneInfo("Asia/Qatar")).date().isoformat()`),
and consider expiring on `valid_to < today` only after Qatar midnight. (3) Add a `CHECK
(valid_to IS NULL OR valid_to GLOB '____-__-__')` constraint, or store dates as Julian/`DATE`-typed
values so comparisons are numeric, not lexical.

---

## 🟠 High (P1)

### HR-01 — Client filter reads `dataset.search` with no guard → first non-matching keystroke can throw
**File:** `web/src/pages/index.astro:121`

```js
(!q || card.dataset.search.includes(q)) && ...
```

`card.dataset.search` is populated from `data-search={searchBlob}` in `DealCard.astro:61`. If a card
ever lacks the attribute (e.g. a future card variant, or `searchBlob` evaluating to `""` which is
fine, but any refactor that conditionally omits it), `dataset.search` is `undefined` and `.includes`
throws, killing the whole filter handler. Defensive coding here is cheap.

**Fix:** `(!q || (card.dataset.search || "").includes(q))`. Apply the same guard mentally to
`dataset.cuisine/area/type` (those use `===` so they're safe, but normalise to `""`).

### HR-02 — `content_hash` dedupe key omits most of the deal → silent loss of legitimately different deals
**File:** `ingest/db.py:106-110, 78 (UNIQUE), 149-190`

The hash is `restaurant_id | title_en | valid_to | code`. Two genuinely different deals that share
those four fields but differ elsewhere (e.g. same title/date but different `discount_value`,
`description`, `deal_type`, or `source_url`) collide → `INSERT OR IGNORE` silently drops the second
(`:186-189`). Worse for Phase B: a corrected/edited caption that keeps the title but fixes the
discount will be ignored, so the **wrong** discount stays live. Conversely, a title typo fix
creates a brand-new row instead of updating, leaving a stale duplicate active until expiry.

**Fix:** Either (a) include the substantive fields in the hash (`deal_type`, `discount_value`,
`description_en`) so meaningful edits create a new fingerprint, **and** add an explicit update path
that supersedes the old row; or (b) keep the narrow key but on conflict `UPDATE` the mutable fields
(discount_value, descriptions, source_url, last_seen) rather than only bumping `last_seen`.

### HR-03 — Expiry never runs in CI → deals expire only when someone manually runs `--expire`
**File:** `.github/workflows/deploy.yml` (whole file) + `ingest/db.py:223`

The deploy workflow rebuilds the site on push to `data/deals.json`, but **nothing in the repo runs
`python ingest/db.py --expire --export-json` on a schedule**. `export_json` only emits
`status='active'` rows (`:243`), so a deal's `valid_to` passing does **not** remove it from the live
JSON until (a) `--expire` is run and (b) a new `deals.json` is committed to re-trigger deploy. With
no cron, an expired deal stays on the live site indefinitely — directly the legal-staleness problem.
"Zero-maintenance" + "auto-expiry mandatory" requires this to be automated.

**Fix:** Add a scheduled workflow (e.g. daily `cron`) that runs
`python ingest/db.py --expire --export-json --export-csv`, commits the data if changed, and lets the
existing `paths: data/deals.json` trigger fire. Even before Phase B, this is needed so already-seeded
deals expire on time.

### HR-04 — Service worker can serve a stale (expired) `deals.json` despite network-first intent
**File:** `web/public/sw.js:46-59`

Navigations are network-first (good), but `deals.json` is fetched as a same-origin **asset**, which
falls into the second branch: `return cached || network` — i.e. **cache-first** (it returns the
cached copy immediately and only revalidates in the background). On a return visit the user sees the
*previous* build's deals — potentially expired ones — until the next load. Given the legal weight of
stale deals, the data file specifically should not be cache-first.

**Fix:** Treat the data JSON as network-first like navigations: branch on
`url.pathname.endsWith("deals.json")` (or a `/data/` path) and do
`fetch(req).then(...).catch(() => caches.match(req))`. Keep stale-while-revalidate only for truly
static hashed assets (CSS/JS/fonts).

### HR-05 — Icon-only language toggle changes meaning but not its accessible name correctly
**File:** `web/src/layouts/Layout.astro:60-67, 104-105`

The toggle's `aria-label="Switch language"` is static, while the visible label flips between
"العربية"/"English" (`:105`). A screen-reader user always hears "Switch language" with no indication
of the current/target language, and the visible label text and the accessible name diverge. Also the
toggle is the only control conveying current language state and it is not exposed as a
`role`/`aria-pressed` toggle.

**Fix:** Update `aria-label` in `applyLang` alongside the label (e.g.
`btn.setAttribute("aria-label", lang === "ar" ? "Switch to English" : "التبديل إلى العربية")`), or
drop the static `aria-label` and let the visible label be the accessible name. Consider
`lang` attributes on the label spans so each language string is announced in the right voice.

---

## 🟡 Medium (P2)

### MR-01 — `<select>` option text for cuisines/areas is not translated and never re-rendered on lang switch
**File:** `web/src/pages/index.astro:64, 69` and i18n engine `Layout.astro:95-98`

Cuisine and area options (`<option value={c}>{c}</option>`) have no `data-en/data-ar`, so they stay
in their source language (English data values) regardless of toggle. Only the "All cuisines"/"All
areas" placeholders translate. In Arabic mode the dropdowns are half-translated. The type `<option>`
*does* carry `data-en/data-ar` (`:75`) but the i18n engine swaps `textContent` of `[data-en]`
nodes — for an `<option>` that works, so types are fine; cuisines/areas are the gap.

**Fix:** Carry an Arabic label for cuisine/area (the data already has `name_ar`; add a cuisine/area
translation map or store `cuisine_ar`/`area_ar`) and render `data-en`/`data-ar` on those options.

### MR-02 — Filter values compare against English data while option labels may be translated → selecting an Arabic-labelled type still works only because value stays English
**File:** `web/src/pages/index.astro:75, 122-124` + `DealCard.astro:60`

The card stores `data-type={deal.deal_type}` (the raw key, e.g. `discount_pct`) and the type
`<option value={t}>` also uses the raw key, so matching works. But this is fragile: it only holds
because the *value* is the untranslated key while only the *label* is swapped. If anyone "helpfully"
sets the option value to the translated label later, the filter silently breaks. Worth a comment /
test to lock the invariant.

**Fix:** Add a code comment documenting that option `value` must remain the raw `deal_type` key, and
ideally a tiny test asserting card `data-type` values are a subset of the filter option values.

### MR-03 — `cmd_export_csv` writes a single empty cell for empty tables, corrupting headers
**File:** `ingest/db.py:304-309`

When a query returns zero rows the code writes `writer.writerow([])` — a CSV with one blank line and
no header row. A consumer expecting the documented columns gets a malformed file. (Also `SELECT *`
on `:312-313` ties the CSV header order to physical column order — schema changes silently reshuffle
columns.)

**Fix:** Always write the header row from the cursor description even when empty:
`writer.writerow([c[0] for c in cur.description])` after executing, then the data rows. Prefer
explicit column lists over `SELECT *` for stable exports.

### MR-04 — CSV export is vulnerable to formula injection when opened in Excel
**File:** `ingest/db.py:296-314`

Exports use `utf-8-sig` so Excel opens them — good for Arabic — but fields are written verbatim. A
deal title/description/code (Phase B: from Instagram captions) beginning with `=`, `+`, `-`, `@`, or
tab/CR triggers Excel/Sheets formula execution (CSV injection), e.g. `=HYPERLINK(...)` or a command
via DDE. Since the CSVs are a user-facing export, this is a real risk once data is scraped.

**Fix:** Prefix any cell whose first char is in `= + - @ \t \r` with a single quote `'` (or wrap in
quotes and lead with `'`) when writing CSVs. Centralise in the `dump()` writer.

### MR-05 — `daysLeft` is baked at build time and goes stale between rebuilds
**File:** `web/src/pages/index.astro:8-16`, `DealCard.astro:30-47`

The badge ("3 days left", "Ends today") is computed at build using `new Date()` on the build server.
Without the daily rebuild (see HR-03) the badge drifts: a card built 4 days ago still says "3 days
left". The comment at `DealCard.astro:30` acknowledges "cron rebuilds keep it fresh" — but no cron
exists yet. Also `daysLeft` uses build-server local midnight (`setHours(0,0,0,0)`), not Qatar time,
so the day-boundary can be off (same TZ concern as CR-03).

**Fix:** Tie to the daily rebuild from HR-03, and/or recompute the badge client-side on load from
`data-valid-to` so it is correct regardless of build age. Anchor "today" to Asia/Qatar.

### MR-06 — `upsert_restaurant` requires `name_en` NOT NULL but passes `r.get("name_en")` (None on bad CSV row) → opaque IntegrityError
**File:** `ingest/db.py:122-146` + schema `:50`

`name_en TEXT NOT NULL`, but a malformed `restaurants.csv` row missing that column yields
`r.get("name_en") == None`, raising a raw `sqlite3.IntegrityError` that aborts the whole load with a
stack trace and no row context. Same for a missing `slug` → `KeyError` at `:134`.

**Fix:** Validate required fields per row before upsert and emit a `WARN: skipping restaurant row N
(missing slug/name_en)` like the deals loader already does at `:215`, so one bad row doesn't fail the
batch.

### MR-07 — `install` precaches only the scope root; offline first-load of sub-assets unguaranteed
**File:** `web/public/sw.js:8-15`

`cache.addAll([new URL("./", scope).pathname])` precaches only the root document. CSS/JS/`deals.json`
are cached lazily on first fetch, so a user who installs the PWA and immediately goes offline gets a
bare HTML shell. Minor for a deal app but undercuts the "installable PWA" claim.

**Fix:** Precache the built CSS/JS entry and `deals.json` in `install`, or accept lazy caching and
document the limitation. (Hashed asset names make a hand-maintained list brittle — a generated
precache manifest would be the robust path, but that conflicts with "zero-maintenance"; a comment
acknowledging the tradeoff suffices.)

---

## 🟢 Low (P3)

### LR-01 — `usingSampleData` banner shows for any `source === "manual"`, will mis-fire in Phase B
**File:** `web/src/pages/index.astro:30`

`deals.some(d => d.deal.source === "manual")` — once Phase B mixes scraped + manual deals, a single
manual deal makes the whole site display the "sample deals" warning. Use an explicit flag (e.g. a
`is_sample` field or a build env var) instead of overloading `source`.

### LR-02 — `rel="noopener"` without `noreferrer` on external links
**File:** `web/src/components/DealCard.astro:111, 115`

`target="_blank"` links use `rel="noopener"` but not `noreferrer`. `noopener` covers the security
case, but adding `noreferrer` avoids leaking the referrer to Instagram/source sites. Minor privacy
polish consistent with the "no personal data" ethos.

### LR-03 — Search input lacks an associated visible/`aria` label
**File:** `web/src/pages/index.astro:57-60`

`<input id="f-search" type="search" placeholder=...>` has only a placeholder, which is not an
accessible name substitute (disappears on focus, poor contrast). The three `<select>`s likewise have
no `<label>`/`aria-label`.

**Fix:** Add `aria-label` (translated via `data-en/data-ar` + an aria-swap in the i18n engine) or
visually-hidden `<label>`s to the search input and each select.

### LR-04 — i18n engine only swaps `textContent` and `placeholder`; no support for translated `aria-label`/`alt`/`title`
**File:** `web/src/layouts/Layout.astro:95-102`

The engine handles `data-en/data-ar` (text) and `data-en-ph/data-ar-ph` (placeholder) only. Any
future translated `aria-label`, `title`, or image `alt` can't be expressed. Generalise to a small
attribute map (`data-en-aria`, etc.) now to avoid retrofitting. Relates to HR-05/LR-03.

### LR-05 — Deploy workflow `BASE_PATH` breaks for `<user>.github.io` repos / custom domains
**File:** `.github/workflows/deploy.yml:40` (+ `astro.config.mjs:9-10` comment acknowledges it)

`BASE_PATH: /${{ github.event.repository.name }}/` is wrong when the repo *is* `<owner>.github.io`
(should be `/`) or when a custom domain is used. The config comment notes the edge case but the
workflow doesn't handle it. Also note the deploy trigger `paths: data/deals.json` means edits to the
*source* `seed_deals.json`/`restaurants.csv` won't deploy until `deals.json` is regenerated — easy to
forget without the HR-03 cron.

**Fix:** Add a conditional (or a manual override input) for the `<owner>.github.io`/custom-domain
case, and document that only `data/deals.json` changes trigger deploy.

### LR-06 — Pin GitHub Actions to commit SHAs; `node-version: 20` lags `package.json` engines `>=22.12`
**File:** `.github/workflows/deploy.yml:30-33, 42, 54` + `web/package.json:6`

Actions are pinned to floating major tags (`@v4`, `@v3`) — supply-chain hardening best practice is
to pin to a full commit SHA with the tag in a comment. Separately, the workflow installs Node 20 but
`package.json` declares `"node": ">=22.12.0"`, so CI runs on an unsupported runtime; `npm ci` may
warn or future deps may break.

**Fix:** Pin actions to SHAs (`actions/checkout@<sha> # v4`), and bump `node-version` to `22` to
match the declared engine.

---

## Cross-cutting notes (verified, not defects)

- **PII / PDPL:** Confirmed the schema (`db.py:46-84`) and exported JSON (`:259-281`) store only
  restaurant + deal facts — no user identifiers, no accounts. The PDPL anonymisation posture holds.
- **Astro auto-escaping:** Verified that text expressions and attribute expressions in `.astro`
  files are HTML-entity-escaped, and that the runtime i18n swap uses `textContent =` (not
  `innerHTML`), so even malicious caption text in `data-en/data-ar` cannot inject markup. The
  remaining XSS exposure is specifically the **`href` scheme** (CR-01) and **URL path
  interpolation** (CR-02), not text rendering.
- **SQL:** All queries use parameter binding (`:name` / `?`); no string-formatted SQL → no SQLI.
- **`localStorage` failures:** Both inline scripts wrap `localStorage` access in `try/catch`
  (`Layout.astro:39-45, 107-116`) — private-mode failures degrade gracefully. Good.
- **Pre-paint lang script:** `Layout.astro:37-46` sets `lang`/`dir` before paint, avoiding the
  direction flash; the FOUC of *text* (English flashes before AR swap at `:117`) is minor and
  inherent to the static-HTML-then-swap approach — acceptable for Phase A.
- **`sync-data.mjs` fallback:** Path resolution and the missing-file empty-dataset fallback
  (`:15-22`) are correct and keep `npm run build` from hard-failing when `deals.json` is absent.

---

_Reviewed: 2026-06-13 · Reviewer: Claude (gsd-code-reviewer) · Depth: deep_
