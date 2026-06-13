#!/usr/bin/env python3
"""
fetch_deal_sites.py — scrape public Qatar dining-deal listing sites into structured
deal facts (data/scraped_deals.json), ready for `db.py --load-scraped`.

These are public editorial pages (no login, no anti-bot wall). We extract only FACTS
(restaurant, offer, price, timing, dates) and link back to the source article — we do
not copy their prose verbatim. Each site gets its own small parser; add more to SITES.

Date handling is deliberately conservative: an offer with an end-date in the past is
kept with that date (so --expire drops it), and an offer with no stated date gets a
short TTL — so the live site never shows stale deals.

Usage:  python ingest/fetch_deal_sites.py
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup
    import dateparser
except ImportError:
    sys.exit("[scrape] missing deps: pip install -r ingest/requirements.txt")

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUT = DATA_DIR / "scraped_deals.json"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
DEFAULT_TTL_DAYS = 21

QATAR_AREAS = ["Lusail", "Al Sadd", "West Bay", "The Pearl", "Pearl", "Msheireb",
               "Katara", "Aspire", "Corniche", "Education City", "Al Wakra", "Doha"]

_PRICE = re.compile(r"QR\s?[\d,]+(?:\.\d+)?", re.I)
_PCT = re.compile(r"(\d{1,2})\s*%")
_TIME = re.compile(r"\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm)\s*(?:-|–|—|to)\s*\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm)", re.I)
_END = re.compile(r"(?:valid\s+until|until|till|ends?|through|up\s+to)\s+([A-Za-z0-9 ,]{3,22})", re.I)
_SET_KW = ("set menu", "set lunch", "set dinner", "afternoon tea", "breakfast", "buffet",
           "brunch", "set meal", "sharing menu", "family style", "high tea", "iftar", "suhoor")


def norm(s: str) -> str:
    return (s.replace("’", "'").replace("‘", "'")
             .replace("–", "-").replace("—", "-").replace("•", " "))


def clean_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def detect_area(text: str) -> str | None:
    for a in QATAR_AREAS:
        if re.search(rf"\b{re.escape(a)}\b", text, re.I):
            return "The Pearl" if a == "Pearl" else a
    return None


def classify(text: str, pct: int | None) -> str:
    if pct is not None:
        return "discount_pct"
    t = text.lower()
    if any(k in t for k in _SET_KW):
        return "set_menu"
    if re.search(r"\bfree\b", t):
        return "free_item"
    if any(k in t for k in ("buy one", "buy 1", "bogo", "1 + 1", "1+1")):
        return "bogo"
    return "other"


def end_date(text: str, today: datetime) -> str | None:
    m = _END.search(text)
    if not m:
        return None
    # No PREFER_DATES_FROM: "Feb 17" resolves to the nearest such date (likely past
    # for a monthly article), which is exactly what we want — it then gets expired.
    dt = dateparser.parse(m.group(1), settings={"RELATIVE_BASE": today, "RETURN_AS_TIMEZONE_AWARE": False})
    return dt.date().isoformat() if dt else None


def parse_factqatar(html: bytes, url: str, today: datetime) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    art = soup.find("article") or soup
    venue = None
    outlet = None
    deals: list[dict] = []
    default_to = (today + timedelta(days=DEFAULT_TTL_DAYS)).date().isoformat()

    for el in art.find_all(["h4", "h5", "p"]):
        if el.name == "h4":
            venue = clean_ws(norm(el.get_text(" ", strip=True)))
            outlet = None
            continue
        if el.name == "h5":
            outlet = clean_ws(norm(el.get_text(" ", strip=True)))
            continue

        text = clean_ws(norm(el.get_text(" ", strip=True)))
        if not text:
            continue
        price_m = _PRICE.search(text)
        pct_m = _PCT.search(text)
        if not price_m and not pct_m:
            continue  # not an offer paragraph

        strongs = [clean_ws(norm(s.get_text())) for s in el.find_all(["strong", "b"])]
        offer_name = next((s for s in strongs if s and not s.lower().startswith("price")), "")
        restaurant = outlet or venue
        if not restaurant:
            continue

        pct = int(pct_m.group(1)) if pct_m else None
        if pct is not None and not (1 <= pct <= 99):
            pct = None
        title = offer_name or text[:60]

        # Compact description = price + timing (facts, not their marketing prose).
        bits = []
        if price_m:
            bits.append(price_m.group().upper().replace("QR", "QR "))
        tm = _TIME.search(text)
        if tm:
            bits.append(tm.group())
        description = clean_ws(" · ".join(bits))

        deals.append({
            "restaurant_name": restaurant,
            "area": detect_area(venue or ""),
            "title_en": clean_ws(title)[:90],
            "description_en": description or None,
            "deal_type": classify(text, pct),
            "discount_value": pct,
            "valid_to": end_date(text, today) or default_to,
            "source": "factqatar",
            "source_url": url,
        })
    return deals


SITES = [
    {"name": "factqatar", "url": "https://factqatar.com/the-best-dining-deals-in-qatar/", "parser": parse_factqatar},
]


def main() -> int:
    today = datetime.now(timezone.utc)
    all_deals: list[dict] = []
    for site in SITES:
        try:
            r = requests.get(site["url"], headers={"User-Agent": UA}, timeout=30)
            if r.status_code != 200:
                print(f"[scrape] {site['name']}: HTTP {r.status_code} — skipping")
                continue
            deals = site["parser"](r.content, site["url"], today)
            print(f"[scrape] {site['name']}: {len(deals)} deals")
            all_deals.extend(deals)
        except Exception as e:  # one bad site must not kill the run
            print(f"[scrape] {site['name']}: error {e!r} — skipping")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(all_deals, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[scrape] {len(all_deals)} total deals -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
