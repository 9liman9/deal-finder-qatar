#!/usr/bin/env python3
"""
extract_offers.py — Phase B step 2: turn raw Instagram captions (data/raw_instagram.json)
into structured deal facts (data/instagram_deals.json), ready for `db.py --load-instagram`.

Heuristic, rules-first extraction (free, offline, deterministic) — no LLM/compute needed:
  - a keyword gate decides whether a post is even a promo (most posts aren't)
  - regex pulls discount %, promo codes, BOGO / set-menu / freebie signals
  - dateparser reads a stated end-date; if none, a conservative TTL is applied so the
    deal auto-expires instead of lingering (stale deals carry legal weight in Qatar)
  - Arabic is detected so the right language slot is filled

Deliberately does NOT copy the post image (displaying their creative = copyright risk).
We keep only FACTS + a link to the original post (the permalink).

Low-confidence rows are flagged `needs_review: true` for a human spot-check.

Usage:  python ingest/extract_offers.py
"""

from __future__ import annotations

import csv
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

try:
    import dateparser
except ImportError:
    sys.exit("[extract] missing dependency: pip install -r ingest/requirements.txt")

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_IN = DATA_DIR / "raw_instagram.json"
RESTAURANTS_CSV = DATA_DIR / "restaurants.csv"
OUT = DATA_DIR / "instagram_deals.json"

# Deals with no stated end-date expire this many days after the post date.
DEFAULT_TTL_DAYS = 14

_ARABIC = re.compile(r"[؀-ۿ]")
# Promo signal gate (EN + AR). A caption with none of these is not treated as a deal.
_PROMO_SIGNALS = re.compile(
    r"(\d{1,2}\s*%|%\s*\d{1,2}|\boff\b|discount|offer|deal|promo|voucher|coupon|"
    r"buy\s*1|buy\s*one|bogo|free\b|set\s*menu|combo|happy\s*hour|"
    r"خصم|عرض|عروض|مجان|كوبون|قسيمة|اشتر)",
    re.I,
)
_PCT = re.compile(r"(\d{1,2})\s*%|%\s*(\d{1,2})")
_CODE = re.compile(r"(?:promo\s*code|use\s*code|code|coupon|كود|رمز)\s*:?\s*([A-Z0-9]{3,15})", re.I)
# Allow an item between "buy one" and "get one", and catch "get one free" / "1+1".
_BOGO = re.compile(
    r"buy\s*(?:1|one)\b.{0,30}?\bget\s*(?:1|one|another)\b|get\s*(?:1|one)\s*free"
    r"|bogo|1\s*\+\s*1|اشتر\S*\s+وا?حد",
    re.I,
)
_SET = re.compile(r"set\s*menu|set\s*meal|combo|وجبة", re.I)
_FREE = re.compile(r"\bfree\b|مجان", re.I)
# End-date phrase → capture a window, then pull a date-shaped token out of it.
_END = re.compile(
    r"(?:valid\s*(?:until|till|through|til)|until|till|ends?|expires?|عرض\s*حتى|حتى|لغاية|ينتهي)\s*:?\s*(.{3,40})",
    re.I,
)
_DATE_TOKEN = re.compile(
    r"\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}\s*[/-]\s*\d{1,2}(?:\s*[/-]\s*\d{2,4})?"
    r"|\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z؀-ۿ]{3,}(?:\s+\d{2,4})?"
    r"|[A-Za-z]{3,}\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{2,4})?",
    re.I,
)


def detect_type(caption: str, pct: int | None, code: str | None) -> str:
    if pct is not None:
        return "discount_pct"
    if code:
        return "coupon"
    if _BOGO.search(caption):
        return "bogo"
    if _SET.search(caption):
        return "set_menu"
    if _FREE.search(caption):
        return "free_item"
    return "other"


def parse_end_date(caption: str, posted: datetime | None) -> tuple[str | None, bool]:
    """Return (YYYY-MM-DD or None, parsed_explicitly?)."""
    m = _END.search(caption)
    if not m:
        return None, False
    window = m.group(1)
    tok = _DATE_TOKEN.search(window)
    candidate = tok.group(0) if tok else window  # prefer a clean date token over messy text
    settings = {"PREFER_DATES_FROM": "future", "RETURN_AS_TIMEZONE_AWARE": False}
    if posted:
        settings["RELATIVE_BASE"] = posted
    dt = dateparser.parse(candidate, settings=settings)
    if dt and (posted is None or dt.date() >= posted.date()):
        return dt.date().isoformat(), True
    return None, False


def first_line(caption: str) -> str:
    """First non-empty line, hashtags stripped, trimmed to a clean ~80-char title."""
    line = next((l.strip() for l in caption.splitlines() if l.strip()), caption.strip())
    line = re.sub(r"#\S+", "", line)        # drop hashtags
    line = re.sub(r"\s+", " ", line).strip()
    if len(line) > 80:
        line = line[:80].rsplit(" ", 1)[0].rstrip() + "…"
    return line


def load_handle_to_slug() -> dict[str, str]:
    mapping: dict[str, str] = {}
    if RESTAURANTS_CSV.exists():
        with RESTAURANTS_CSV.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                h = (row.get("ig_handle") or "").strip().lstrip("@").lower()
                if h and row.get("slug"):
                    mapping[h] = row["slug"].strip()
    return mapping


def extract_one(caption: str, posted: datetime | None) -> dict | None:
    if not caption or not _PROMO_SIGNALS.search(caption):
        return None  # not a promo

    pm = _PCT.search(caption)
    pct = None
    if pm:
        pct = int(pm.group(1) or pm.group(2))
        if not (1 <= pct <= 99):
            pct = None
    cm = _CODE.search(caption)
    code = cm.group(1).upper() if cm else None
    deal_type = detect_type(caption, pct, code)

    end_iso, explicit = parse_end_date(caption, posted)
    if not end_iso and posted:
        end_iso = (posted + timedelta(days=DEFAULT_TTL_DAYS)).date().isoformat()

    line = first_line(caption)
    has_ar = bool(_ARABIC.search(line))
    has_latin = bool(re.search(r"[A-Za-z]", line))

    title_ar = line if has_ar else None
    if has_latin:
        title_en = line
    else:
        # Arabic-only caption: synthesise a short English title from the facts.
        labels = {"discount_pct": f"{pct}% off" if pct else "Discount",
                  "bogo": "Buy 1 Get 1", "set_menu": "Set menu",
                  "coupon": "Promo code offer", "free_item": "Free item", "other": "Special offer"}
        title_en = labels[deal_type]

    # Low confidence: vague type with no % and no code, or no end-date signal at all.
    needs_review = deal_type == "other" or (not explicit)

    return {
        "title_en": title_en,
        "title_ar": title_ar,
        "deal_type": deal_type,
        "discount_value": pct,
        "code": code,
        "valid_to": end_iso,
        "source": "instagram",
        "source_url": None,  # set by caller (the post permalink)
        # image_url intentionally omitted — we do not republish their creative (copyright).
        "needs_review": needs_review,
    }


def main() -> int:
    if not RAW_IN.exists():
        sys.exit(f"[extract] missing {RAW_IN} — run fetch_instagram.py first")
    raw = json.loads(RAW_IN.read_text(encoding="utf-8"))
    handle_to_slug = load_handle_to_slug()

    deals = []
    skipped_unmapped = 0
    for entry in raw:
        handle = (entry.get("ig_handle") or "").lstrip("@").lower()
        slug = handle_to_slug.get(handle)
        if not slug:
            skipped_unmapped += 1
            continue
        for post in entry.get("posts", []):
            posted = None
            if post.get("timestamp"):
                try:
                    posted = datetime.fromisoformat(post["timestamp"].replace("Z", "+00:00")).replace(tzinfo=None)
                except ValueError:
                    posted = None
            d = extract_one(post.get("caption", ""), posted)
            if not d:
                continue
            d["restaurant_slug"] = slug
            d["source_url"] = post.get("permalink")
            deals.append(d)

    OUT.write_text(json.dumps(deals, ensure_ascii=False, indent=2), encoding="utf-8")
    review = sum(1 for d in deals if d.get("needs_review"))
    print(f"[extract] {len(deals)} candidate deals ({review} flagged needs_review), "
          f"{skipped_unmapped} unmapped handles -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
