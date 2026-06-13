#!/usr/bin/env python3
"""
db.py — the single source of truth for the Qatar Restaurant Deals data layer.

Pure standard library (sqlite3, csv, json). Manages the SQLite database that lives
in the repo (data/deals.db) and produces the artifacts the static site + users need:

    python ingest/db.py --init                 # create the schema (idempotent)
    python ingest/db.py --load-seed            # load data/restaurants.csv + data/seed_deals.json
    python ingest/db.py --expire               # mark deals past valid_to as expired
    python ingest/db.py --export-json          # write data/deals.json (active deals, for the site)
    python ingest/db.py --export-csv           # write data/exports/*.csv
    python ingest/db.py --stats                # print row counts

Flags can be combined, e.g.:
    python ingest/db.py --init --load-seed --expire --export-json --export-csv

Design rule: the database stores ONLY restaurant + deal FACTS — never user PII.
This keeps the whole app under Qatar PDPL's anonymisation exemption.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import sys
from datetime import date, datetime, timezone
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
DEALS_JSON = DATA_DIR / "deals.json"

DEAL_TYPES = {"discount_pct", "bogo", "set_menu", "coupon", "free_item", "other"}

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
    content_hash   TEXT UNIQUE
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


def today_str() -> str:
    return date.today().isoformat()


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def content_hash(restaurant_id: int, title_en: str, valid_to: str | None,
                 code: str | None) -> str:
    """Stable fingerprint of a deal, used to dedupe across runs."""
    raw = f"{restaurant_id}|{(title_en or '').strip().lower()}|{valid_to or ''}|{(code or '').strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def cmd_init(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()
    print(f"[init] schema ready at {DB_PATH}")


def upsert_restaurant(conn: sqlite3.Connection, r: dict) -> int:
    """Insert or update a restaurant by slug; return its id."""
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
            "slug": r["slug"],
            "name_en": r.get("name_en"),
            "name_ar": r.get("name_ar"),
            "ig_handle": r.get("ig_handle"),
            "cuisine": r.get("cuisine"),
            "area": r.get("area"),
            "lat": _to_float(r.get("lat")),
            "lng": _to_float(r.get("lng")),
            "logo_url": r.get("logo_url"),
        },
    )
    row = conn.execute("SELECT id FROM restaurants WHERE slug = ?", (r["slug"],)).fetchone()
    return row["id"]


def insert_deal(conn: sqlite3.Connection, restaurant_id: int, d: dict, source: str = "manual") -> bool:
    """Insert a deal if its content_hash is new. Returns True if inserted."""
    title_en = d["title_en"]
    valid_to = d.get("valid_to")
    code = d.get("code")
    chash = content_hash(restaurant_id, title_en, valid_to, code)
    ts = now_iso()
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO deals
            (restaurant_id, title_en, title_ar, description_en, description_ar,
             deal_type, discount_value, code, valid_from, valid_to,
             source, source_url, image_url, first_seen, last_seen, status, content_hash)
        VALUES
            (:restaurant_id, :title_en, :title_ar, :description_en, :description_ar,
             :deal_type, :discount_value, :code, :valid_from, :valid_to,
             :source, :source_url, :image_url, :first_seen, :last_seen, 'active', :content_hash)
        """,
        {
            "restaurant_id": restaurant_id,
            "title_en": title_en,
            "title_ar": d.get("title_ar"),
            "description_en": d.get("description_en"),
            "description_ar": d.get("description_ar"),
            "deal_type": d.get("deal_type") if d.get("deal_type") in DEAL_TYPES else "other",
            "discount_value": _to_float(d.get("discount_value")),
            "code": code,
            "valid_from": d.get("valid_from"),
            "valid_to": valid_to,
            "source": source,
            "source_url": d.get("source_url"),
            "image_url": d.get("image_url"),
            "first_seen": ts,
            "last_seen": ts,
            "content_hash": chash,
        },
    )
    if cur.rowcount == 0:
        # Already seen — bump last_seen so we know it's still live.
        conn.execute("UPDATE deals SET last_seen = ? WHERE content_hash = ?", (ts, chash))
        return False
    return True


def cmd_load_seed(conn: sqlite3.Connection) -> None:
    if not RESTAURANTS_CSV.exists():
        sys.exit(f"[load-seed] missing {RESTAURANTS_CSV}")
    if not SEED_DEALS_JSON.exists():
        sys.exit(f"[load-seed] missing {SEED_DEALS_JSON}")

    # Restaurants
    with RESTAURANTS_CSV.open(encoding="utf-8") as f:
        restaurants = list(csv.DictReader(f))
    for r in restaurants:
        upsert_restaurant(conn, r)
    print(f"[load-seed] upserted {len(restaurants)} restaurants")

    # Map slug -> id
    slug_to_id = {row["slug"]: row["id"] for row in conn.execute("SELECT id, slug FROM restaurants")}

    # Deals
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


def cmd_expire(conn: sqlite3.Connection) -> None:
    today = today_str()
    cur = conn.execute(
        "UPDATE deals SET status='expired' WHERE valid_to IS NOT NULL AND valid_to < ? AND status='active'",
        (today,),
    )
    conn.commit()
    print(f"[expire] marked {cur.rowcount} deal(s) expired (valid_to < {today})")


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
        rows = conn.execute(query).fetchall()
        path = EXPORTS_DIR / filename
        with path.open("w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig => Excel reads Arabic
            writer = csv.writer(f)
            if rows:
                writer.writerow(rows[0].keys())
                for row in rows:
                    writer.writerow(list(row))
            else:
                writer.writerow([])
        print(f"[export-csv] {len(rows):>4} rows -> {path}")

    dump("restaurants.csv", "SELECT * FROM restaurants ORDER BY name_en")
    dump("deals.csv", "SELECT * FROM deals ORDER BY valid_to")
    dump("active_deals.csv", _active_deals_query())


def cmd_stats(conn: sqlite3.Connection) -> None:
    r = conn.execute("SELECT COUNT(*) c FROM restaurants").fetchone()["c"]
    total = conn.execute("SELECT COUNT(*) c FROM deals").fetchone()["c"]
    active = conn.execute("SELECT COUNT(*) c FROM deals WHERE status='active'").fetchone()["c"]
    expired = conn.execute("SELECT COUNT(*) c FROM deals WHERE status='expired'").fetchone()["c"]
    print(f"[stats] restaurants={r}  deals={total}  active={active}  expired={expired}")


def _to_float(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Qatar Restaurant Deals data layer")
    p.add_argument("--init", action="store_true", help="create the schema")
    p.add_argument("--load-seed", action="store_true", help="load restaurants.csv + seed_deals.json")
    p.add_argument("--expire", action="store_true", help="mark deals past valid_to as expired")
    p.add_argument("--export-json", action="store_true", help="write data/deals.json")
    p.add_argument("--export-csv", action="store_true", help="write data/exports/*.csv")
    p.add_argument("--stats", action="store_true", help="print row counts")
    args = p.parse_args(argv)

    if not any(vars(args).values()):
        p.print_help()
        return 0

    conn = connect()
    try:
        # --init must run before anything that touches tables
        if args.init or args.load_seed or args.expire or args.export_json or args.export_csv or args.stats:
            conn.executescript(SCHEMA)  # safe: IF NOT EXISTS
        if args.init:
            cmd_init(conn)
        if args.load_seed:
            cmd_load_seed(conn)
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
