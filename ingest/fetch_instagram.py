#!/usr/bin/env python3
"""
fetch_instagram.py — Phase B step 1: pull recent public posts from Qatar restaurant
Instagram **Business/Creator** accounts via the Instagram Graph API Business
Discovery endpoint (the Facebook-Login path — the only one that supports querying
other accounts).

It reads the handle list from data/restaurants.csv (the `ig_handle` column), queries
each, and writes the raw posts to data/raw_instagram.json for extract_offers.py.

Credentials come from the environment (never commit them):
    IG_USER_ID       your authenticated Instagram Business account's user id
    IG_ACCESS_TOKEN  a long-lived access token (60 days)
    GRAPH_VERSION    optional, defaults to v22.0

Usage:
    python ingest/fetch_instagram.py            # query all handles in restaurants.csv
    python ingest/fetch_instagram.py --limit 5  # only the first 5 (for testing)

NOTE: querying accounts you do not own requires Meta App Review in production.
Until then this only returns data for your own / app-tester accounts.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import quote

try:
    import requests
except ImportError:
    sys.exit("[fetch] missing dependency: pip install -r ingest/requirements.txt")

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RESTAURANTS_CSV = DATA_DIR / "restaurants.csv"
RAW_OUT = DATA_DIR / "raw_instagram.json"

GRAPH_VERSION = os.environ.get("GRAPH_VERSION", "v22.0")
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"

# Business Use Case rate limit is ~200 requests/hour/account. One request per handle
# (recent media only, no pagination) keeps us well under that for a normal seed list.
REQUEST_PAUSE_S = 1.0
MAX_RETRIES = 4


def load_handles(limit: int | None) -> list[str]:
    if not RESTAURANTS_CSV.exists():
        sys.exit(f"[fetch] missing {RESTAURANTS_CSV}")
    handles: list[str] = []
    with RESTAURANTS_CSV.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            h = (row.get("ig_handle") or "").strip().lstrip("@")
            if h:
                handles.append(h)
    # de-dupe, preserve order
    seen, ordered = set(), []
    for h in handles:
        if h not in seen:
            seen.add(h)
            ordered.append(h)
    return ordered[:limit] if limit else ordered


def business_discovery(ig_user_id: str, token: str, handle: str) -> list[dict] | None:
    """Return the target account's recent media, or None on a hard error for that handle."""
    fields = (
        f"business_discovery.username({quote(handle)})"
        "{username,media{caption,timestamp,permalink,media_url,media_type}}"
    )
    params = {"fields": fields, "access_token": token}
    url = f"{GRAPH_BASE}/{ig_user_id}"

    backoff = 5
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, params=params, timeout=30)
        except requests.RequestException as e:
            print(f"[fetch] {handle}: network error ({e}); retry {attempt}/{MAX_RETRIES}")
            time.sleep(backoff)
            backoff *= 2
            continue

        if resp.status_code == 200:
            data = resp.json()
            media = (data.get("business_discovery") or {}).get("media", {})
            return media.get("data", []) if isinstance(media, dict) else []

        # Rate limited — back off and retry.
        if resp.status_code == 429:
            print(f"[fetch] {handle}: rate limited (429); backing off {backoff}s")
            time.sleep(backoff)
            backoff *= 2
            continue

        # Other errors: surface the message, skip this handle (don't kill the batch).
        try:
            err = resp.json().get("error", {})
            msg = err.get("message", resp.text[:200])
            code = err.get("code")
        except ValueError:
            msg, code = resp.text[:200], None
        print(f"[fetch] {handle}: skipped (HTTP {resp.status_code}, code {code}): {msg}")
        return None

    print(f"[fetch] {handle}: gave up after {MAX_RETRIES} retries")
    return None


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Fetch QA restaurant posts via Instagram Business Discovery")
    p.add_argument("--limit", type=int, default=None, help="only query the first N handles")
    args = p.parse_args(argv)

    ig_user_id = os.environ.get("IG_USER_ID")
    token = os.environ.get("IG_ACCESS_TOKEN")
    if not ig_user_id or not token:
        sys.exit("[fetch] IG_USER_ID and IG_ACCESS_TOKEN must be set in the environment.")

    handles = load_handles(args.limit)
    print(f"[fetch] querying {len(handles)} handle(s) via {GRAPH_VERSION} Business Discovery")

    results = []
    ok = 0
    for h in handles:
        media = business_discovery(ig_user_id, token, h)
        if media is not None:
            ok += 1
            posts = [
                {
                    "caption": m.get("caption", ""),
                    "timestamp": m.get("timestamp"),
                    "permalink": m.get("permalink"),
                    "media_url": m.get("media_url"),
                    "media_type": m.get("media_type"),
                }
                for m in media
            ]
            results.append({"ig_handle": h, "posts": posts})
        time.sleep(REQUEST_PAUSE_S)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RAW_OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    total_posts = sum(len(r["posts"]) for r in results)
    print(f"[fetch] {ok}/{len(handles)} handles ok, {total_posts} posts -> {RAW_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
