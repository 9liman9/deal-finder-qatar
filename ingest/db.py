#!/usr/bin/env python3
"""
db.py — the single source of truth for the Qatar Restaurant Deals data layer.

Pure standard library (sqlite3, csv, json, re). Manages the SQLite database that
lives in the repo (data/deals.db) and produces the artifacts the static site +
users need:

    python ingest/db.py --init                 # create the schema (idempotent)
    python ingest/db.py --load-seed            # load data/restaurants.csv + seed_deals.json
    python ingest/db.py --expire               # mark deals past valid_to as expired (Qatar time)
    python ingest/db.py --export-json          # write data/deals.json (active deals, for the site)
    python ingest/db.py --export-csv           # write data/exports/*.csv (formula-injection safe)
    python ingest/db.py --stats                # print row counts

Flags can be combined:
    python ingest/db.py --init --load-seed --expire --export-json --export-csv

Design rules baked in here:
  - The database stores ONLY restaurant + deal FACTS — never user PII (Qatar PDPL
    anonymisation exemption).
  - Dates are normalised to strict YYYY-MM-DD and expiry is anchored to Qatar time
    (UTC+3) — showing a stale deal is a legal problem, so the boundary must be exact.
  - Untrusted text (Phase B will scrape Instagram captions) is sanitised at this
    boundary: URL schemes are allow-listed, IG handles are charset-validated, and
    CSV cells are guarded against spreadsheet formula injection.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths (resolved relative to this file so it runs from anywhere)
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
EXPORTS_DIR = DATA_DIR / "exports"
DB_PATH = DATA_DIR / "deals.db"
RESTAURANTS_CSV = DATA_DIR / "restaurants.csv"
SEED_DEALS_JSON = DATA_DIR / "seed_deals.json"
INSTAGRAM_DEALS_JSON = DATA_DIR / "instagram_deals.json"
SCRAPED_DEALS_JSON = DATA_DIR / "scraped_deals.json"
DEALS_JSON = DATA_DIR / "deals.json"

# Qatar has a fixed UTC+3 offset year-round (no DST), so a fixed offset is correct
# and avoids depending on the tzdata package (absent on Windows / minimal CI).
QATAR_TZ = timezone(timedelta(hours=3))

DEAL_TYPES = {"discount_pct", "bogo", "set_menu", "coupon", "free_item", "other"}

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_IG_HANDLE_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")
# Leading chars that trigger formula execution in Excel / Google Sheets.
_CSV_DANGEROUS_PREFIX = ("=", "+", "-", "@", "\t", "\r")

SCHEMA = """
CREATE TABLE IF NOT EXISTS restaurants (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    slug      TEXT UNIQUE NOT NULL,
    name_en   TEXT NOT NULL,
    name_ar   TEXT,
    ig_handle TEXT,
    cuisine   TEXT,
    area      TEXT,
    lat       REAL,
    lng       REAL,
    logo_url  TEXT
);

CREATE TABLE IF NOT EXISTS deals (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    restaurant_id  INTEGER NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
    title_en       TEXT NOT NULL,
    title_ar       TEXT,
    description_en TEXT,
    description_ar TEXT,
    deal_type      TEXT,
    discount_value REAL,
    code           TEXT,
    valid_from     TEXT,
    valid_to       TEXT,
    source         TEXT DEFAULT 'manual',
    source_url     TEXT,
    image_url      TEXT,
    first_seen     TEXT,
    last_seen      TEXT,
    status         TEXT DEFAULT 'active',
    content_hash   TEXT UNIQUE,
    -- belt-and-suspenders: dates that reach the DB must be strict YYYY-MM-DD.
    -- NOTE: in GLOB, '_' is literal and '?' is the single-char wildcard, so we use
    -- explicit digit classes (not '____-__-__', which would match literal underscores).
    CHECK (valid_to   IS NULL OR valid_to   GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    CHECK (valid_from IS NULL OR valid_from GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]')
);

CREATE INDEX IF NOT EXISTS idx_deals_valid_to    ON deals(valid_to);
CREATE INDEX IF NOT EXISTS idx_deals_status      ON deals(status);
CREATE INDEX IF NOT EXISTS idx_deals_restaurant  ON deals(restaurant_id);
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today_qatar() -> str:
    """Today's date in Asia/Qatar (UTC+3). Expiry is anchored here, not to the runner."""
    return datetime.now(QATAR_TZ).date().isoformat()


def normalize_date(v) -> str | None:
    """Coerce a date-ish value to strict YYYY-MM-DD, or None if unparseable/empty."""
    if v is None or v == "":
        return None
    s = str(v).strip()
    candidate = s[:10] if "T" in s else s
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(candidate, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def safe_url(u) -> str | None:
    """Allow only http(s) URLs — blocks javascript:/data: stored-XSS via scraped data."""
    if not u or not isinstance(u, str):
        return None
    try:
        from urllib.parse import urlparse
        scheme = urlparse(u).scheme.lower()
        return u if scheme in ("http", "https") else None
    except ValueError:
        return None


def clean_handle(h) -> str | None:
    """Strip a leading @ and validate against Instagram's real handle charset."""
    if not h:
        return None
    handle = str(h).strip().lstrip("@")
    return handle if _IG_HANDLE_RE.match(handle) else None


def _csv_safe(value):
    """Neutralise spreadsheet formula injection in exported CSV cells."""
    if isinstance(value, str) and value and value[0] in _CSV_DANGEROUS_PREFIX:
        return "'" + value
    return value


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def content_hash(restaurant_id: int, title_en: str, valid_to, code) -> str:
    """Stable fingerprint of a deal's identity, used to dedupe across runs.

    Intentionally narrow (restaurant + title + validity + code): the same logical
    deal keeps its hash even when mutable fields (discount, description) are
    corrected, so insert_deal() UPDATEs those in place instead of leaving the old
    value live. A genuinely different deal (new title/date/code) gets a new row.
    """
    raw = f"{restaurant_id}|{(title_en or '').strip().lower()}|{valid_to or ''}|{(code or '').strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _to_float(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "restaurant"


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def cmd_init(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()
    print(f"[init] schema ready at {DB_PATH}")


def upsert_restaurant(conn: sqlite3.Connection, r: dict) -> int | None:
    """Insert or update a restaurant by slug; return its id (or None if the row is invalid)."""
    slug = (r.get("slug") or "").strip()
    name_en = (r.get("name_en") or "").strip()
    if not slug or not name_en:
        print(f"[load-seed] WARN: skipping restaurant row (missing slug/name_en): {r!r}")
        return None
    conn.execute(
        """
        INSERT INTO restaurants (slug, name_en, name_ar, ig_handle, cuisine, area, lat, lng, logo_url)
        VALUES (:slug, :name_en, :name_ar, :ig_handle, :cuisine, :area, :lat, :lng, :logo_url)
        ON CONFLICT(slug) DO UPDATE SET
            name_en=excluded.name_en, name_ar=excluded.name_ar, ig_handle=excluded.ig_handle,
            cuisine=excluded.cuisine, area=excluded.area, lat=excluded.lat, lng=excluded.lng,
            logo_url=excluded.logo_url
        """,
        {
            "slug": slug,
            "name_en": name_en,
            "name_ar": r.get("name_ar"),
            "ig_handle": clean_handle(r.get("ig_handle")),
            "cuisine": r.get("cuisine"),
            "area": r.get("area"),
            "lat": _to_float(r.get("lat")),
            "lng": _to_float(r.get("lng")),
            "logo_url": safe_url(r.get("logo_url")),
        },
    )
    row = conn.execute("SELECT id FROM restaurants WHERE slug = ?", (slug,)).fetchone()
    return row["id"]


def insert_deal(conn: sqlite3.Connection, restaurant_id: int, d: dict, source: str = "manual") -> bool:
    """Insert a new deal, or UPDATE mutable fields if its identity hash already exists.

    Returns True if a new row was inserted. A deal whose valid_to is present but
    unparseable is skipped (we will not publish a deal we cannot expiry-check).
    """
    title_en = (d.get("title_en") or "").strip()
    if not title_en:
        print(f"[load-seed] WARN: skipping deal with no title_en: {d!r}")
        return False

    raw_valid_to = d.get("valid_to")
    valid_to = normalize_date(raw_valid_to)
    if raw_valid_to and valid_to is None:
        print(f"[load-seed] WARN: skipping deal '{title_en}' — unparseable valid_to {raw_valid_to!r}")
        return False
    valid_from = normalize_date(d.get("valid_from"))

    code = d.get("code")
    chash = content_hash(restaurant_id, title_en, valid_to, code)
    ts = now_iso()
    params = {
        "restaurant_id": restaurant_id,
        "title_en": title_en,
        "title_ar": d.get("title_ar"),
        "description_en": d.get("description_en"),
        "description_ar": d.get("description_ar"),
        "deal_type": d.get("deal_type") if d.get("deal_type") in DEAL_TYPES else "other",
        "discount_value": _to_float(d.get("discount_value")),
        "code": code,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "source": source,
        "source_url": safe_url(d.get("source_url")),
        "image_url": safe_url(d.get("image_url")),
        "first_seen": ts,
        "last_seen": ts,
        "content_hash": chash,
    }
    # Explicit exists-check rather than INSERT OR IGNORE: OR IGNORE would also
    # silently swallow CHECK/NOT NULL violations (masking real data bugs). Here a
    # genuine constraint violation raises, while dedupe is handled deliberately.
    exists = conn.execute("SELECT 1 FROM deals WHERE content_hash = ?", (chash,)).fetchone()
    if exists:
        # Same logical deal — refresh mutable fields so a corrected discount/
        # description supersedes the stale value, and re-activate it.
        conn.execute(
            """
            UPDATE deals SET
                title_ar=:title_ar, description_en=:description_en, description_ar=:description_ar,
                deal_type=:deal_type, discount_value=:discount_value, valid_from=:valid_from,
                source=:source, source_url=:source_url, image_url=:image_url,
                last_seen=:last_seen, status='active'
            WHERE content_hash=:content_hash
            """,
            params,
        )
        return False
    conn.execute(
        """
        INSERT INTO deals
            (restaurant_id, title_en, title_ar, description_en, description_ar,
             deal_type, discount_value, code, valid_from, valid_to,
             source, source_url, image_url, first_seen, last_seen, status, content_hash)
        VALUES
            (:restaurant_id, :title_en, :title_ar, :description_en, :description_ar,
             :deal_type, :discount_value, :code, :valid_from, :valid_to,
             :source, :source_url, :image_url, :first_seen, :last_seen, 'active', :content_hash)
        """,
        params,
    )
    return True


def cmd_load_seed(conn: sqlite3.Connection) -> None:
    if not RESTAURANTS_CSV.exists():
        sys.exit(f"[load-seed] missing {RESTAURANTS_CSV}")
    if not SEED_DEALS_JSON.exists():
        sys.exit(f"[load-seed] missing {SEED_DEALS_JSON}")

    with RESTAURANTS_CSV.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    loaded = 0
    for r in rows:
        if upsert_restaurant(conn, r) is not None:
            loaded += 1
    print(f"[load-seed] upserted {loaded}/{len(rows)} restaurants")

    slug_to_id = {row["slug"]: row["id"] for row in conn.execute("SELECT id, slug FROM restaurants")}

    deals = json.loads(SEED_DEALS_JSON.read_text(encoding="utf-8"))
    inserted = 0
    for d in deals:
        slug = d.get("restaurant_slug")
        if slug not in slug_to_id:
            print(f"[load-seed] WARN: deal references unknown restaurant '{slug}', skipping")
            continue
        if insert_deal(conn, slug_to_id[slug], d, source=d.get("source", "manual")):
            inserted += 1
    conn.commit()
    print(f"[load-seed] inserted {inserted} new deals ({len(deals)} in seed file)")


def cmd_load_instagram(conn: sqlite3.Connection) -> None:
    """Load extract_offers.py output (data/instagram_deals.json) as source='instagram'."""
    if not INSTAGRAM_DEALS_JSON.exists():
        print(f"[load-instagram] no {INSTAGRAM_DEALS_JSON} — skipping")
        return
    slug_to_id = {row["slug"]: row["id"] for row in conn.execute("SELECT id, slug FROM restaurants")}
    deals = json.loads(INSTAGRAM_DEALS_JSON.read_text(encoding="utf-8"))
    inserted = 0
    for d in deals:
        slug = d.get("restaurant_slug")
        if slug not in slug_to_id:
            print(f"[load-instagram] WARN: unknown restaurant '{slug}', skipping")
            continue
        if insert_deal(conn, slug_to_id[slug], d, source="instagram"):
            inserted += 1
    conn.commit()
    print(f"[load-instagram] inserted {inserted} new deals ({len(deals)} candidates)")


def cmd_load_scraped(conn: sqlite3.Connection) -> None:
    """Load fetch_deal_sites.py output (data/scraped_deals.json). Restaurants arrive as
    names (not slugs/handles), so we auto-create them by slugified name."""
    if not SCRAPED_DEALS_JSON.exists():
        print(f"[load-scraped] no {SCRAPED_DEALS_JSON} — skipping")
        return
    deals = json.loads(SCRAPED_DEALS_JSON.read_text(encoding="utf-8"))
    inserted = 0
    for d in deals:
        name = (d.get("restaurant_name") or "").strip()
        if not name:
            continue
        rid = upsert_restaurant(conn, {
            "slug": slugify(name), "name_en": name, "name_ar": None,
            "ig_handle": None, "cuisine": d.get("cuisine"), "area": d.get("area"),
            "lat": None, "lng": None, "logo_url": None,
        })
        if rid is None:
            continue
        if insert_deal(conn, rid, d, source=d.get("source", "scraped")):
            inserted += 1
    conn.commit()
    print(f"[load-scraped] inserted {inserted} new deals ({len(deals)} candidates)")


def cmd_expire(conn: sqlite3.Connection) -> None:
    today = today_qatar()
    cur = conn.execute(
        "UPDATE deals SET status='expired' WHERE valid_to IS NOT NULL AND valid_to < ? AND status='active'",
        (today,),
    )
    conn.commit()
    print(f"[expire] marked {cur.rowcount} deal(s) expired (valid_to < {today} Qatar time)")


def _active_deals_query() -> str:
    return """
        SELECT d.id, d.title_en, d.title_ar, d.description_en, d.description_ar,
               d.deal_type, d.discount_value, d.code, d.valid_from, d.valid_to,
               d.source, d.source_url, d.image_url, d.last_seen,
               r.slug AS r_slug, r.name_en AS r_name_en, r.name_ar AS r_name_ar,
               r.ig_handle AS r_ig_handle, r.cuisine AS r_cuisine, r.area AS r_area,
               r.lat AS r_lat, r.lng AS r_lng, r.logo_url AS r_logo_url
        FROM deals d
        JOIN restaurants r ON r.id = d.restaurant_id
        WHERE d.status = 'active'
        ORDER BY d.valid_to IS NULL, d.valid_to ASC, r.name_en ASC
    """


def cmd_export_json(conn: sqlite3.Connection) -> None:
    rows = conn.execute(_active_deals_query()).fetchall()
    deals = []
    cuisines, areas, deal_types = set(), set(), set()
    for row in rows:
        if row["r_cuisine"]:
            cuisines.add(row["r_cuisine"])
        if row["r_area"]:
            areas.add(row["r_area"])
        if row["deal_type"]:
            deal_types.add(row["deal_type"])
        deals.append({
            "id": row["id"],
            "title": {"en": row["title_en"], "ar": row["title_ar"]},
            "description": {"en": row["description_en"], "ar": row["description_ar"]},
            "deal_type": row["deal_type"],
            "discount_value": row["discount_value"],
            "code": row["code"],
            "valid_from": row["valid_from"],
            "valid_to": row["valid_to"],
            "source": row["source"],
            "source_url": row["source_url"],
            "image_url": row["image_url"],
            "restaurant": {
                "slug": row["r_slug"],
                "name": {"en": row["r_name_en"], "ar": row["r_name_ar"]},
                "ig_handle": row["r_ig_handle"],
                "cuisine": row["r_cuisine"],
                "area": row["r_area"],
                "lat": row["r_lat"],
                "lng": row["r_lng"],
                "logo_url": row["r_logo_url"],
            },
        })
    payload = {
        "generated_at": now_iso(),
        "count": len(deals),
        "filters": {
            "cuisines": sorted(cuisines),
            "areas": sorted(areas),
            "deal_types": sorted(deal_types),
        },
        "deals": deals,
    }
    DEALS_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[export-json] wrote {len(deals)} active deals -> {DEALS_JSON}")


def cmd_export_csv(conn: sqlite3.Connection) -> None:
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

    def dump(filename: str, query: str) -> None:
        cur = conn.execute(query)
        cols = [c[0] for c in cur.description]
        rows = cur.fetchall()
        path = EXPORTS_DIR / filename
        with path.open("w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig => Excel reads Arabic
            writer = csv.writer(f)
            writer.writerow(cols)  # always emit the header, even for empty tables
            for row in rows:
                writer.writerow([_csv_safe(v) for v in row])
        print(f"[export-csv] {len(rows):>4} rows -> {path}")

    dump("restaurants.csv",
         "SELECT slug, name_en, name_ar, ig_handle, cuisine, area, lat, lng, logo_url FROM restaurants ORDER BY name_en")
    dump("deals.csv",
         "SELECT id, restaurant_id, title_en, title_ar, deal_type, discount_value, code, "
         "valid_from, valid_to, source, source_url, status FROM deals ORDER BY valid_to")
    dump("active_deals.csv", _active_deals_query())


def cmd_stats(conn: sqlite3.Connection) -> None:
    r = conn.execute("SELECT COUNT(*) c FROM restaurants").fetchone()["c"]
    total = conn.execute("SELECT COUNT(*) c FROM deals").fetchone()["c"]
    active = conn.execute("SELECT COUNT(*) c FROM deals WHERE status='active'").fetchone()["c"]
    expired = conn.execute("SELECT COUNT(*) c FROM deals WHERE status='expired'").fetchone()["c"]
    print(f"[stats] restaurants={r}  deals={total}  active={active}  expired={expired}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Qatar Restaurant Deals data layer")
    p.add_argument("--init", action="store_true", help="create the schema")
    p.add_argument("--load-seed", action="store_true", help="load restaurants.csv + seed_deals.json")
    p.add_argument("--load-instagram", action="store_true", help="load data/instagram_deals.json (source=instagram)")
    p.add_argument("--load-scraped", action="store_true", help="load data/scraped_deals.json (auto-create restaurants)")
    p.add_argument("--expire", action="store_true", help="mark deals past valid_to as expired (Qatar time)")
    p.add_argument("--export-json", action="store_true", help="write data/deals.json")
    p.add_argument("--export-csv", action="store_true", help="write data/exports/*.csv")
    p.add_argument("--stats", action="store_true", help="print row counts")
    args = p.parse_args(argv)

    if not any(vars(args).values()):
        p.print_help()
        return 0

    conn = connect()
    try:
        conn.executescript(SCHEMA)  # safe: IF NOT EXISTS
        if args.init:
            cmd_init(conn)
        if args.load_seed:
            cmd_load_seed(conn)
        if args.load_instagram:
            cmd_load_instagram(conn)
        if args.load_scraped:
            cmd_load_scraped(conn)
        if args.expire:
            cmd_expire(conn)
        if args.export_json:
            cmd_export_json(conn)
        if args.export_csv:
            cmd_export_csv(conn)
        if args.stats:
            cmd_stats(conn)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
