# Qatar Restaurant Deals

A **free, open-source PWA** that aggregates restaurant deals in Qatar and updates
itself with **no paid services and no server to maintain**.

It uses the [git-scraping](https://simonwillison.net/tags/git-scraping/) pattern:
a scheduled GitHub Action collects deals, writes them to a **SQLite database in
this repo**, exports `deals.json` + CSV, and commits them back. A static **Astro**
site on **GitHub Pages** reads the data. Total running cost: **$0**.

## Why it's built this way

Two NotebookLM research passes (`docs/research/`) established the legal + technical
reality of aggregating deals in Qatar:

| Source | Verdict |
|---|---|
| **Instagram Graph API** (Business Discovery) | ✅ Free, ToS-compliant, lowest risk → primary engine |
| Talabat / Snoonu / Rafeeq scraping | ❌ Walled gardens; criminal-law risk (Cybercrime Law 14/2014) — excluded |
| The Entertainer / iEAT (B2B API) | Paid contracts — out of the free scope |

Design rules baked in:
- **No user PII stored** → falls under Qatar PDPL's anonymisation exemption (no consent banners).
- **Store deal *facts*, not verbatim creatives** → facts aren't copyrightable (Law 7/2002).
- **Auto-expiry is mandatory** → showing stale deals is an offense (Cybercrime Law Art. 6/8).

## Structure

```
data/        deals.db (SQLite, source of truth) · deals.json (for the site) · restaurants.csv (seed) · exports/ (CSV)
ingest/      db.py (schema + load + expire + dedupe + export) · fetch_instagram.py · extract_offers.py (Phase B)
web/         Astro + Tailwind static PWA (EN/AR + RTL)
.github/workflows/   deploy.yml (Pages) · ingest.yml (autonomous cron — Phase B)
docs/research/       NotebookLM research reports
```

## Quickstart

```bash
# 1. Build the database + exports from the seed data
python ingest/db.py --init
python ingest/db.py --load-seed
python ingest/db.py --export-json --export-csv

# 2. Run the site locally
cd web
npm install
npm run dev
```

## Roadmap

- **Phase A — done/in progress:** working site with seeded deals, SQLite + CSV export, EN/AR, deploy to Pages.
- **Phase B:** autonomous Instagram Graph API ingestion on a GitHub Actions cron.
- **Phase C:** auto-expiry hardening, Arabic NLP extraction, offline caching, polish.
