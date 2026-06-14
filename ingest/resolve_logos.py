#!/usr/bin/env python3
"""
resolve_logos.py — best-effort brand-logo resolution for venues missing one.

Legal note: we only ever use a brand's LOGO (trademark, nominative/identification use —
what Google/Yelp/Zomato do) and we HOTLINK it; we never copy a restaurant's promotional
offer creative (copyright). Venues we can't resolve fall back to a generated monogram tile
on the site, so coverage is always 100% — this just upgrades what it can.

Strategy per venue (stop at first hit):
  1. Heuristic domain guess ({slug}.com / .qa / .com.qa) + verify the page title mentions
     the venue (filters parked/wrong domains). No external search, fast.
  2. DuckDuckGo Lite (no-JS, no key) first organic result -> domain, same verify. Last resort.
  3. On a verified domain, take the apple-touch-icon / <link rel=icon> (the logo); else fall
     back to Google's favicon service. The chosen URL is hotlinked, not re-hosted.

Caching (so the daily cron never re-hammers): hits are written to data/logos.json (applied by
`db.py --load-logos`); misses are remembered in data/logo_misses.json and skipped for
MISS_TTL_DAYS. deals.db already persists resolved logos across runs.

Usage:  python ingest/resolve_logos.py [--limit N] [--retry-misses]
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("[logos] missing deps: pip install -r ingest/requirements.txt")

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "deals.db"
LOGOS_JSON = DATA_DIR / "logos.json"
MISSES_JSON = DATA_DIR / "logo_misses.json"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
TIMEOUT = 10
MISS_TTL_DAYS = 14  # don't re-try a failed venue for this long

# Domain-parking / for-sale marketplaces. A guessed/searched domain that lands here is NOT
# the venue. PARKING_HOSTS is matched ONLY against an icon's host (never page body, which
# would false-flag legit GoDaddy-hosted sites). PARKING_PHRASES is matched against the page
# and is kept tight so real restaurant copy never trips it.
PARKING_HOSTS = re.compile(
    r"(domainmarket|hugedomains|afternic|sedoparking|\bsedo\.|dan\.com|bodis|parkingcrew|"
    r"above\.com|undeveloped|sav\.com|voodoo\.com|uniregistry|parklogic|domize)",
    re.I,
)
PARKING_PHRASES = re.compile(
    r"(this domain (?:name )?(?:is|may be) for sale|buy this domain|the domain .{0,60}? is for sale|"
    r"\bdomain for sale\b|domain is parked|domain name is for sale|interested in (?:buying |purchasing )?this domain|"
    r"checkout the full domain details|the owner of this domain)",
    re.I,
)


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "en"})
    return s


def _name_tokens(name: str) -> list[str]:
    """Significant lowercase word-tokens (len>=4) used to confirm a page is really the venue."""
    return [w for w in re.findall(r"[a-z]+", (name or "").lower()) if len(w) >= 4]


# A real venue site reads like food/hospitality. Generic single-word .coms (elixir.com the
# language, orion.com, tulum.com the resort) won't hit these — so they get rejected.
DINING_KW = re.compile(
    r"\b(restaurant|dining|reservation|reserve a table|book a table|cuisine|brunch|buffet|"
    r"bistro|eatery|trattoria|brasserie|steak\s?house|grill|bakery|patisserie|caf[eé]|"
    r"shisha|iftar|suhoor|set menu|food menu|our menu|appetiz|main course|dessert|"
    r"pizza|burger|sushi|biryani|shawarma|kebab|seafood|barbecue|\bbbq\b|charcoal|mezze)\b",
    re.I,
)
LOCAL_KW = re.compile(r"\b(qatar|doha|lusail|west bay|the pearl|katara|msheireb|al sadd|souq waqif)\b", re.I)

# Names too generic to resolve safely — they'd match unrelated big-brand .coms.
GENERIC_NAMES = {
    "restaurant", "restaurants", "cafe", "café", "lounge", "kitchen", "grill", "bakery",
    "bistro", "eatery", "diner", "buffet", "coffee", "the-restaurant", "food", "menu",
}


def candidate_domains(slug: str) -> list[str]:
    nodash = slug.replace("-", "")
    return [f"{nodash}.com", f"{nodash}.qa"]


def _page_identifies(html: str, tokens: list[str]) -> bool:
    """True if the page's <title>/og:site_name mentions the venue — guards parked domains."""
    if not tokens:
        return False
    soup = BeautifulSoup(html, "html.parser")
    hay = " ".join(
        filter(
            None,
            [
                (soup.title.get_text(" ", strip=True) if soup.title else ""),
                _meta(soup, "og:site_name"),
                _meta(soup, "og:title"),
            ],
        )
    ).lower()
    return any(t in hay for t in tokens)


def _meta(soup: BeautifulSoup, prop: str) -> str:
    el = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
    return (el.get("content") or "").strip() if el else ""


def _looks_parked(html: str) -> bool:
    """True if the page is a domain-parking / for-sale placeholder, not a real venue site."""
    head = html[:4000].lower()
    return bool(PARKING_PHRASES.search(head))


def _context_text(soup: BeautifulSoup) -> str:
    """Title + meta/og descriptions + body text — so JS-SPA restaurant sites (whose body is
    near-empty server-side) are still recognised via their meta tags."""
    parts = [
        soup.title.get_text(" ", strip=True) if soup.title else "",
        _meta(soup, "description"),
        _meta(soup, "og:description"),
        _meta(soup, "og:title"),
        _meta(soup, "og:site_name"),
        soup.get_text(" ", strip=True)[:20000],
    ]
    return " ".join(filter(None, parts)).lower()


def _resolves(host: str) -> bool:
    """Fast DNS check — skip the HTTP attempt entirely for non-existent guessed domains
    (the common case for small venues), which is what made the naive version crawl."""
    try:
        socket.setdefaulttimeout(2)
        socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
        return True
    except (socket.gaierror, socket.timeout, OSError):
        return False
    finally:
        socket.setdefaulttimeout(None)


def _fetch(sess: requests.Session, url: str):
    # (connect, read) timeouts — a dead/firewalled host fails the connect in ~4s, not 10.
    # One retry on a live host so a transient blip doesn't poison the 14-day miss cache.
    for attempt in range(2):
        try:
            r = sess.get(url, timeout=(4, 8), allow_redirects=True)
            ct = r.headers.get("content-type", "")
            if r.status_code == 200 and "html" in ct:
                return r
            return None  # a real 404/non-html answer — no point retrying
        except requests.RequestException:
            if attempt == 0:
                continue
    return None


def best_logo(sess: requests.Session, base_url: str, html: str) -> str | None:
    """Pick the brand's own logo from a verified homepage: apple-touch-icon / rel=icon,
    else its /favicon.ico if it actually exists. Never a third-party parking/CDN asset."""
    soup = BeautifulSoup(html, "html.parser")
    best, best_sz = None, -1
    for link in soup.find_all("link", rel=True):
        rels = " ".join(link.get("rel")).lower()
        if "icon" not in rels:  # matches "icon", "shortcut icon", "apple-touch-icon"
            continue
        href = link.get("href")
        if not href:
            continue
        abs_url = urljoin(base_url, href)
        if urlparse(abs_url).scheme not in ("http", "https"):
            continue
        if PARKING_HOSTS.search(urlparse(abs_url).netloc):  # e.g. cdn.domainmarket.com
            continue
        sz = 0
        m = re.search(r"(\d{2,4})x\d{2,4}", link.get("sizes", "") or "")
        if m:
            sz = int(m.group(1))
        if "apple-touch-icon" in rels:
            sz += 200  # bias toward the crisp 180px logo
        if sz > best_sz:
            best, best_sz = abs_url, sz
    if best:
        return best
    # Fallback: the site's OWN /favicon.ico — only if it really serves one (confirms a real site).
    fav = urljoin(base_url, "/favicon.ico")
    try:
        h = sess.get(fav, timeout=TIMEOUT, allow_redirects=True)
        ct = h.headers.get("content-type", "")
        if h.status_code == 200 and (ct.startswith("image/") or "icon" in ct) and len(h.content) > 70:
            return h.url if not PARKING_HOSTS.search(urlparse(h.url).netloc) else None
    except requests.RequestException:
        pass
    return None


def ddg_domain(sess: requests.Session, query: str) -> str | None:
    """First organic result domain from DuckDuckGo Lite (no JS, no key). Tolerant of failure."""
    try:
        r = sess.post(
            "https://lite.duckduckgo.com/lite/",
            data={"q": query},
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return None
    except requests.RequestException:
        return None
    soup = BeautifulSoup(r.text, "html.parser")
    for a in soup.select("a[href]"):
        href = a.get("href", "")
        m = re.search(r"uddg=([^&]+)", href)
        target = requests.utils.unquote(m.group(1)) if m else href
        netloc = urlparse(target).netloc.lower()
        if not netloc or netloc.endswith("duckduckgo.com"):
            continue
        # Skip aggregators/social — we want the brand's own site.
        if re.search(r"(facebook|instagram|tripadvisor|zomato|talabat|snoonu|youtube|wikipedia|deliveroo)\.", netloc):
            continue
        return netloc[4:] if netloc.startswith("www.") else netloc
    return None


def resolve_one(sess: requests.Session, slug: str, name: str, use_ddg: bool = False) -> tuple[str | None, str | None]:
    """Return (logo_url, domain) or (None, None). Only a venue's OWN logo is ever returned."""
    tokens = _name_tokens(name)
    if not tokens or all(t in GENERIC_NAMES for t in tokens) or slug in GENERIC_NAMES:
        return None, None  # too generic to resolve to the right brand
    single = len(tokens) <= 1  # generic one-word names need an extra local signal

    def try_domain(domain: str) -> tuple[str | None, str | None]:
        if not _resolves(domain):  # skip HTTP for non-existent domains (fast path)
            return None, None
        r = _fetch(sess, f"https://{domain}/")
        if not r or _looks_parked(r.text):
            return None, None
        soup = BeautifulSoup(r.text, "html.parser")
        if not _page_identifies(r.text, tokens):
            return None, None
        ctx = _context_text(soup)
        if not DINING_KW.search(ctx):  # must read like a dining venue
            return None, None
        if single and not (domain.endswith(".qa") or LOCAL_KW.search(ctx)):
            return None, None  # one-word name on a generic .com — too risky without a QA signal
        logo = best_logo(sess, r.url, r.text)
        return (logo, domain) if logo else (None, None)

    # 1) heuristic guesses ({slug}.com / .qa / .com.qa)
    for domain in candidate_domains(slug):
        logo, dom = try_domain(domain)
        if logo:
            return logo, dom

    # 2) DuckDuckGo Lite fallback (opt-in; slow/rate-limited) — only trust a result that
    #    shares a name token with the venue.
    if use_ddg:
        domain = ddg_domain(sess, f"{name} restaurant Qatar")
        if domain and any(t in domain.replace(".", "") for t in tokens):
            logo, dom = try_domain(domain)
            if logo:
                return logo, dom

    return None, None


def load_misses() -> dict:
    if MISSES_JSON.exists():
        try:
            return json.loads(MISSES_JSON.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {}
    return {}


def main(argv: list[str]) -> int:
    try:  # make logging robust on Windows' legacy cp1252 console
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Resolve brand logos for venues missing one")
    ap.add_argument("--limit", type=int, default=None, help="cap attempts this run (default: all)")
    ap.add_argument("--retry-misses", action="store_true", help="ignore the miss cache")
    ap.add_argument("--ddg", action="store_true", help="also try a DuckDuckGo search (slower, opt-in)")
    args = ap.parse_args(argv)

    if not DB_PATH.exists():
        print(f"[logos] no DB at {DB_PATH} — run db.py --init --load-scraped first")
        return 0

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT slug, name_en FROM restaurants "
        "WHERE logo_url IS NULL OR logo_url='' ORDER BY name_en"
    ).fetchall()
    conn.close()

    today = date.today()
    misses = {} if args.retry_misses else load_misses()

    def recently_missed(slug: str) -> bool:
        ts = misses.get(slug)
        if not ts:
            return False
        try:
            return (today - datetime.fromisoformat(ts).date()).days < MISS_TTL_DAYS
        except ValueError:
            return False

    fresh = [r for r in rows if not recently_missed(r["slug"])]
    cached = len(rows) - len(fresh)
    todo = fresh[: args.limit] if args.limit else fresh
    print(f"[logos] {len(rows)} venue(s) without a logo - attempting {len(todo)} "
          f"(cache-skipped {cached}, limit-deferred {len(fresh) - len(todo)})")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Accumulate with prior hits so a chunked or interrupted run never loses ground.
    resolved: dict[str, dict] = {}
    if LOGOS_JSON.exists():
        try:
            for it in json.loads(LOGOS_JSON.read_text(encoding="utf-8")):
                if it.get("slug"):
                    resolved[it["slug"]] = it
        except (ValueError, OSError):
            pass

    def flush() -> None:
        LOGOS_JSON.write_text(json.dumps(list(resolved.values()), ensure_ascii=False, indent=2), encoding="utf-8")
        MISSES_JSON.write_text(json.dumps(misses, ensure_ascii=False, indent=2), encoding="utf-8")

    sess = _session()
    new_hits = 0
    for i, r in enumerate(todo, 1):
        slug, name = r["slug"], r["name_en"]
        try:
            logo_url, domain = resolve_one(sess, slug, name, use_ddg=args.ddg)
        except Exception as e:  # never let one venue kill the run
            logo_url, domain = None, None
            print(f"[logos]   ! {name}: {e!r}")
        if logo_url:
            resolved[slug] = {"slug": slug, "name": name, "logo_url": logo_url, "domain": domain}
            misses.pop(slug, None)
            new_hits += 1
            print(f"[logos] OK {name} -> {domain}")
        else:
            misses[slug] = today.isoformat()
        if i % 10 == 0:
            flush()  # incremental save — survives timeout/interruption
            print(f"[logos]   ...{i}/{len(todo)} ({new_hits} new)")

    flush()
    rate = f"{100*new_hits/len(todo):.0f}%" if todo else "n/a"
    print(f"[logos] resolved {new_hits}/{len(todo)} this run ({rate}); "
          f"{len(resolved)} total in {LOGOS_JSON}")
    print(f"[logos] next: python ingest/db.py --load-logos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
