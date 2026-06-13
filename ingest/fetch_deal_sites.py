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

_PRICE = re.compile(r"(?:QAR|QR)\s?[\d,]+(?:\.\d+)?", re.I)
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


# Keyword → cuisine (specific first, generic last). Used to restore the cuisine filter.
CUISINE_KEYWORDS = [
    ("Italian", ["pizza", "pizzeria", "italian", "pasta", "trattoria", "napoli", "risotto"]),
    ("Japanese", ["sushi", "japanese", "ramen", "teppanyaki", "izakaya", "sashimi", "nikkei", "robata"]),
    ("Indian", ["biryani", "indian", "tandoor", "curry", "masala", "dosa", "punjab", "mughlai", "dalchini", "taj rasoi", "rasoi"]),
    ("Persian", ["persian", "iranian", "parisa", "shiraz", "saffron"]),
    ("Chinese", ["chinese", "dim sum", "szechuan", "cantonese", "peking", "wok"]),
    ("Thai", ["thai", "pad thai", "tom yum"]),
    ("Turkish", ["turkish", "ottoman", "anatolia"]),
    ("Mexican", ["mexican", "taco", "burrito", "cantina"]),
    ("Seafood", ["seafood", "oyster", "lobster", "prawn", "fish market"]),
    ("Steakhouse", ["steakhouse", "steak", "prime cut", "grill house"]),
    ("Burgers", ["burger", "smash"]),
    ("Lebanese", ["lebanese", "mezze", "shawarma", "arabic", "levant", "manakish", "zaatar", "kebab", "mandi", "shisha"]),
    ("Cafe", ["cafe", "coffee", "karak", "bakery", "patisserie", "roastery", "afternoon tea", "high tea"]),
    ("Healthy", ["healthy", "salad", "poke", "vegan", "organic"]),
    ("Chicken", ["fried chicken", "broasted", "jollibee"]),
    ("International", ["buffet", "international", "brunch", "world cuisine"]),
]


def infer_cuisine(text: str) -> str | None:
    t = (text or "").lower()
    for cuisine, kws in CUISINE_KEYWORDS:
        if any(k in t for k in kws):
            return cuisine
    return None


_PRICE_NUM = re.compile(r"(?:QAR|QR)\s?([\d,]+)", re.I)
_DELIVERY = re.compile(r"deliver|online order|order online|app[- ]?exclusive|promo code|use code|talabat|snoonu|pickup|take[- ]?away|carryout", re.I)
_DINEIN = re.compile(r"dine.?in|set menu|set lunch|set dinner|buffet|afternoon tea|brunch|lounge|a la carte|sharing menu|\btable\b|iftar|suhoor|high tea", re.I)


def parse_price_num(text: str) -> float | None:
    m = _PRICE_NUM.search(text or "")
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def infer_channel(text: str, deal_type: str | None) -> str:
    has_delivery = bool(_DELIVERY.search(text or "")) or deal_type == "coupon"
    has_dinein = bool(_DINEIN.search(text or ""))
    if has_delivery and has_dinein:
        return "both"
    if has_delivery:
        return "delivery"
    return "dine_in"  # default — our sources skew dine-in


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


def _offernmenu_name(alt: str) -> str:
    name = alt or ""
    for pat in (r"\(copy\)", r"restaurant offer in qatar", r"\boffers?\b", r"\bdoha\b"):
        name = re.sub(pat, "", name, flags=re.I)
    return clean_ws(name).strip(" -,")


def parse_offernmenu(html: bytes, url: str, today: datetime) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    default_to = (today + timedelta(days=DEFAULT_TTL_DAYS)).date().isoformat()
    deals, seen = [], set()

    for a in soup.select('a[href*="/offer/"]'):
        href = a.get("href")
        if not href or href in seen:
            continue
        seen.add(href)
        cont = a.find_parent(["article", "li", "div"]) or a
        text = clean_ws(norm(cont.get_text(" ", strip=True)))
        img = cont.find("img")
        name = _offernmenu_name(img.get("alt", "") if img else "")
        if not name or len(name) < 2:
            continue

        pct_m = _PCT.search(text)
        pct = int(pct_m.group(1)) if pct_m and 1 <= int(pct_m.group(1)) <= 99 else None
        price_m = re.search(r"(\d+)\s*QAR", text, re.I)

        valid_to = default_to
        exp = re.search(r"EXPIRES?\s*IN\s*(\d{1,2}/\d{1,2}/\d{4})", text, re.I)
        gone = re.search(r"Offer\s*Expired!?\s*([A-Za-z]+\s+\d{1,2},?\s+\d{4})", text, re.I)
        if exp:
            dt = dateparser.parse(exp.group(1), settings={"DATE_ORDER": "MDY", "RETURN_AS_TIMEZONE_AWARE": False})
            if dt:
                valid_to = dt.date().isoformat()
        elif gone:
            dt = dateparser.parse(gone.group(1), settings={"RETURN_AS_TIMEZONE_AWARE": False})
            if dt:
                valid_to = dt.date().isoformat()  # past → will be expired

        if pct is not None:
            title, dtype = f"{pct}% off", "discount_pct"
        elif price_m:
            title, dtype = f"Offer from QR {price_m.group(1)}", "other"
        else:
            title, dtype = "Special offer", "other"

        deals.append({
            "restaurant_name": name.title() if name.islower() else name,
            "area": detect_area(text),
            "title_en": title,
            "description_en": (f"From QR {price_m.group(1)}" if price_m and pct is None else None),
            "deal_type": dtype,
            "discount_value": pct,
            "valid_to": valid_to,
            "source": "offernmenu",
            "source_url": href,
        })
    return deals


_SECTION_WORDS = re.compile(r"deals?\b|offers?\b|read|popular|top stories|related|comments|share|business lunch deals in qatar", re.I)


def parse_marhaba(html: bytes, url: str, today: datetime) -> list[dict]:
    """Marhaba article: headings (h2-h4) are restaurant names, following <p>/<li> hold the offer."""
    soup = BeautifulSoup(html, "html.parser")
    art = (soup.find("article")
           or soup.find("div", class_=re.compile(r"entry-content|post-content|td-post-content|content", re.I))
           or soup)
    default_to = (today + timedelta(days=DEFAULT_TTL_DAYS)).date().isoformat()
    restaurant = None
    deals: list[dict] = []

    for el in art.find_all(["h2", "h3", "h4", "p", "li"]):
        if el.name in ("h2", "h3", "h4"):
            t = clean_ws(norm(el.get_text(" ", strip=True)))
            if t and len(t) < 60 and not _SECTION_WORDS.search(t):
                restaurant = t
            continue
        if not restaurant:
            continue
        text = clean_ws(norm(el.get_text(" ", strip=True)))
        if not text:
            continue
        price_m = _PRICE.search(text)
        pct_m = _PCT.search(text)
        if not price_m and not pct_m:
            continue
        pct = int(pct_m.group(1)) if pct_m and 1 <= int(pct_m.group(1)) <= 99 else None

        dtype = classify(text, pct)
        before_price = text.split(price_m.group())[0] if price_m else text
        cand = clean_ws(re.sub(r"\bprices?\b\s*:?\s*$", "", before_price, flags=re.I))
        TYPE_LABEL = {"discount_pct": (f"{pct}% off" if pct else "Discount"), "bogo": "Buy 1 Get 1",
                      "set_menu": "Set menu", "free_item": "Freebie", "coupon": "Coupon", "other": "Lunch offer"}
        title = cand[:70] if len(cand) >= 5 else TYPE_LABEL[dtype]
        bits = []
        if price_m:
            bits.append(price_m.group().upper())
        tm = _TIME.search(text)
        if tm:
            bits.append(tm.group())

        deals.append({
            "restaurant_name": restaurant,
            "area": detect_area(text),
            "title_en": title,
            "description_en": clean_ws(" · ".join(bits)) or None,
            "deal_type": dtype,
            "discount_value": pct,
            "valid_to": end_date(text, today) or default_to,
            "source": "marhaba",
            "source_url": url,
        })
    return deals


SITES = [
    {"name": "factqatar", "url": "https://factqatar.com/the-best-dining-deals-in-qatar/", "parser": parse_factqatar},
    {"name": "offernmenu", "url": "https://offernmenu.com/", "parser": parse_offernmenu},
    {"name": "marhaba", "url": "https://marhaba.qa/business-lunch-deals-in-qatar/", "parser": parse_marhaba},
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

    # Drop junk restaurant names (CMS drafts / placeholders) before enriching.
    def _valid_name(n: str | None) -> bool:
        if not n:
            return False
        if re.search(r"auto.?draft|^untitled|^copy\b|^test\b|placeholder", n, re.I):
            return False
        return len(re.sub(r"[^A-Za-z؀-ۿ]", "", n)) >= 2

    all_deals = [d for d in all_deals if _valid_name(d.get("restaurant_name"))]

    # Enrich each deal: cuisine, numeric price, and dine-in/delivery channel.
    for d in all_deals:
        blob = f"{d.get('restaurant_name','')} {d.get('title_en','')} {d.get('description_en') or ''}"
        d["cuisine"] = infer_cuisine(blob)
        d["price"] = parse_price_num(f"{d.get('description_en') or ''} {d.get('title_en') or ''}")
        d["channel"] = infer_channel(blob, d.get("deal_type"))

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(all_deals, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[scrape] {len(all_deals)} total deals -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
