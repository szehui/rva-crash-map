#!/usr/bin/env python3
"""RVA Crash Tracker — collector stage.

Scrapes 7 local news sources for crash-related articles, extracts candidates,
writes candidates JSON for agent-side classification/dedup, maintains seen-URL state.

Usage:
  python3 rva_crash_tracker.py --mode daily          # last 2 days of articles
  python3 rva_crash_tracker.py --mode backfill --days 30
  python3 rva_crash_tracker.py --mode backfill --days 30 --fresh   # reset state, refetch all
"""
import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.error
import ssl
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
CTX = ssl.create_default_context()

import rva_paths as paths

STATE_DIR = paths.STATE_DIR
STATE_FILE = paths.CRASH_STATE
CAND_FILE = paths.CANDIDATES

# crash-series words that suggest a traffic incident in title/slug
CRASH_RE = re.compile(
    r"\b(crash\w*|collid\w*|collision|pedestrian\w*|fatal\w*|killed|kill\w*|injur\w*"
    r"|motorcycl\w*|bicycl\w*|cyclist|struck|overturn\w*"
    r"|hit[- ]and[- ]run|struck[- ]and[- ](?:kill|injur)\w*|hit by (?:a |an |one )?(?:car|truck|SUV|van|vehicle)\w*"
    r"|traffic(?: fatality)?|roadway|wreck\w*|died|death|struck by (?:a |an |one )?(?:car|truck|SUV|van|vehicle))\b", re.I)

# reject these clearly-non-traffic senses of "crash"/"struck"
NON_TRAFFIC_RE = re.compile(
    r"\b(stock|stocks|market|plane|aircraft|helicopter|software|website|server|computer"
    r"|testing|test|wedding|party|graduation|business)[- ]?crash"
    r"|crash(es|ed|ing)? (?:the |a |into )?(?:party|wedding|website|course|gates?"
    r"|stock|markets?|iphone|phone)"
    r"|\bplane\b|\baircraft\b|\bhelicopter\b"
    r"|struck by (?:a |an |one |the )?(?:falling|fly(ing)?|broken|loose|toppl\w*|train"
    r"|branch|tree|limb|object\w*|goalpost)\w*"
    r"|hit by (?:a |an |one |the )?(?:falling|fly(ing)?|broken|wayward|toppl\w*|branch|tree|limb)", re.I)

LOCALITY_SLUGS = {
    "richmond": "City of Richmond",
    "richmond-city": "City of Richmond",
    "henrico-county": "Henrico County",
    "henrico": "Henrico County",
    "chesterfield-county": "Chesterfield County",
    "chesterfield": "Chesterfield County",
    "hanover-county": "Hanover County",
    "hanover": "Hanover County",
    "ashland": "Hanover County",
}

TARGET_LOCALITIES = {"City of Richmond", "Henrico County", " Chesterfield County".strip(),
                     "Hanover County"}


def fetch(url, timeout=30, max_bytes=900000):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return r.status, r.headers.get("Content-Type", "?"), r.read(max_bytes).decode("utf-8", "replace")


def strip_cdata(s):
    return re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", s, flags=re.S) if s else s


NAV_PARA_RE = re.compile(
    r"^\s*(Sign In|Donate|Subscribe|Home [A-Z]|Menu|Newsletter|FOLLOW|Top Stories"
    r"|Local News|Watch Live|Share (?:on|via|this)|Comments? (?:Related|$)|[A-Z][a-z]+ News Actions"
    r"|Actions Facebook|Related Stories|Read More|Most Read)", re.I)


def extract_body(html, max_chars=8000, url=""):
    """Tolerant paragraph harvest: headers/footers sliced off, nav paras dropped.
    Falls back to og:description when the page is nav-heavy or paywalled."""
    s = html.find("</header>")
    e = html.find("<footer")
    seg = html[s:e] if (s >= 0 and e > s) else html
    paras = []
    for pm in re.finditer(r"<p[^>]*>(.*?)</p>", seg, re.S):
        txt = re.sub(r"<[^>]+>", " ", pm.group(1))
        txt = re.sub(r"&nbsp;", " ", txt)
        txt = re.sub(r"\s+", " ", txt).strip()
        if len(txt) > 50 and not NAV_PARA_RE.search(txt) and not re.search(r"^\W+$", txt):
            paras.append(txt)
    out = "\n\n".join(paras[:40])[:max_chars]
    # nav-boilerplate fallback: if the harvest looks like menu junk, use meta description
    mm = re.search(r'<meta[^>]*(?:name="description"|property="og:description")[^>]*content="([^"]*)"', html, re.I)
    meta_desc = mm.group(1) if mm else ""
    if len(paras) < 2 and meta_desc:
        return (meta_desc[:max_chars]) or out
    if re.search(r"(Log In Subscribe|Site Search AI Answers)", out[:300]) or len(out) < 120:
        return meta_desc or out
    return out


def parse_pubdate(raw):
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw.strip()).astimezone(timezone.utc)
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw.strip()[:26], fmt).replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None


def rss_items(xml):
    items = []
    for m in re.finditer(r"<item>(.*?)</item>|<entry>(.*?)</entry>", xml, re.S):
        it = m.group(1) or m.group(2)

        def g(tag, dotall=False):
            mm = re.search(rf"<{re.escape(tag)}[^>]*>(.*?)</{re.escape(tag)}>", it,
                           re.S if dotall else 0)
            return strip_cdata(mm.group(1)).strip() if mm else ""

        link = g("link") or ""
        if not link:
            lm = re.search(r'<link[^>]*href="([^"]+)"', it)
            link = lm.group(1) if lm else ""
        items.append({
            "title": re.sub(r"\s+", " ", g("title")),
            "link": link.strip(),
            "pubDate": g("pubDate") or g("published") or g("updated"),
            "description": re.sub(r"<[^>]+>", " ", g("description") or g("content:encoded") or g("content")),
        })
    return items


def sitemap_entries(xml):
    """Return [(loc, lastmod)] from a sitemap (handles news:publication_date too)."""
    entries = []
    for m in re.finditer(r"<url>(.*?)</url>", xml, re.S):
        b = m.group(1)
        loc = re.search(r"<loc>(.*?)</loc>", b, re.S)
        lm = re.search(r"<lastmod>(.*?)</lastmod>", b, re.S) or \
             re.search(r"<news:publication_date>(.*?)</news:publication_date>", b, re.S)
        if loc:
            entries.append((loc.group(1).strip(), (lm.group(1).strip() if lm else "")))
    return entries


# ------------------------------------------------------------------------------
# Per-source collectors: each returns list of {source, title, url, pubDate}
# ------------------------------------------------------------------------------

def collect_wtvr(days_back, today):
    out = []
    # recent news sitemap covers ~2 days; monthly sitemaps cover the rest
    urls = ["https://www.wtvr.com/news-sitemap-content.xml"]
    for d in range(days_back):
        dt = today - timedelta(days=d)
        mm, yy = f"{dt.month:02d}", dt.year
        s = f"https://www.wtvr.com/sitemap-{yy}{mm}.xml"
        if s not in urls:
            urls.append(s)
    seen_monthly = set()
    for u in urls:
        try:
            _, _, body = fetch(u)
        except Exception as e:
            print(f"  [wtvr] {u} -> {type(e).__name__}", file=sys.stderr)
            continue
        for loc, lm in sitemap_entries(body):
            if "/videos/" in loc:
                continue
            key = loc
            if key in seen_monthly:
                continue
            seen_monthly.add(key)
            dt = None
            if lm:
                dt = parse_pubdate(lm)
            out.append({"source": "wtvr.com", "title": slug_to_title(loc.rsplit("/", 1)[-1]),
                        "url": loc, "pubDate": lm, "_dt": dt})
    return out


def slug_to_title(slug):
    s = re.sub(r"[-_]", " ", slug)
    s = re.sub(r"\b(sept?|september)[ -]?(\d{1,2})\b.*$", "", s, flags=re.I)
    return s.strip().title()


def collect_nbc12(days_back, today):
    out = []
    url = "https://www.nbc12.com/arc/outboundfeeds/rss/?outputType=xml&size=100"
    try:
        _, _, body = fetch(url)
        items = rss_items(body)
        for it in items:
            if not it.get("link"):
                continue
            it["source"] = "nbc12.com"
            out.append(it)
    except Exception as e:
        print(f"  [nbc12] {type(e).__name__}", file=sys.stderr)
    return out


def collect_wric(days_back, today):
    """WRIC article pages are behind a PerimeterX bot wall, but the WordPress
    REST API (wp-json/wp/v2/posts) works and returns full content."""
    out = []
    seen = set()
    cutoff = today - timedelta(days=days_back)
    page = 1
    while page <= 12:  # plenty for 30 days
        try:
            _, _, body = fetch(
                f"https://www.wric.com/wp-json/wp/v2/posts?per_page=100&page={page}"
                f"&orderby=date&order=desc&_fields=id,date,link,title,content")
        except urllib.error.HTTPError as e:
            if e.code == 400 and page > 1:
                break  # past-the-end page
            break
        except Exception:
            break
        try:
            posts = json.loads(body)
        except Exception:
            break
        if not posts:
            break
        stop = False
        for p in posts:
            dt = datetime.fromisoformat(p["date"]).replace(tzinfo=timezone.utc)
            if dt < cutoff:
                stop = True
                continue
            link = p.get("link") or ""
            if link and link not in seen:
                seen.add(link)
                # WP REST returns escaped title text (no tags)
                title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", p.get("title", {}).get("rendered", ""))).strip()
                ctext = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ",
                               p.get("content", {}).get("rendered", ""))).strip()
                out.append({"source": "wric.com", "title": title, "url": link,
                            "pubDate": p["date"], "description": ctext[:6000],
                            "_dt": dt})
        if stop:
            break
        page += 1
    return out


def collect_vpm(days_back, today):
    out = []
    for feed in ("https://vpm.org/feed/", "https://vpm.org/rss/"):
        try:
            _, _, body = fetch(feed)
            for it in rss_items(body):
                it["source"] = "vpm.org"
                out.append(it)
        except Exception as e:
            print(f"  [vpm] {type(e).__name__}", file=sys.stderr)
    return out


def collect_richmonder(days_back, today):
    out = []
    # RSS for recent; posts sitemap filtered by lastmod for backfill
    try:
        _, _, body = fetch("https://richmonder.org/feed/")
        for it in rss_items(body):
            it["source"] = "richmonder.org"
            out.append(it)
    except Exception as e:
        print(f"  [richmonder rss] {type(e).__name__}", file=sys.stderr)
    if days_back > 3:
        cutoff = today - timedelta(days=days_back)
        try:
            _, _, body = fetch("https://www.richmonder.org/sitemap-posts.xml")
            for loc, lm in sitemap_entries(body):
                dt = parse_pubdate(lm)
                if dt and dt >= cutoff:
                    out.append({"source": "richmonder.org", "title": slug_to_title(loc.rsplit("/", 1)[-1]),
                                "url": loc, "pubDate": lm, "_dt": dt})
        except Exception as e:
            print(f"  [richmonder sitemap] {type(e).__name__}", file=sys.stderr)
    return out


def collect_henricocitizen(days_back, today):
    out = []
    try:
        _, _, body = fetch("https://henricocitizen.com/rss/")
        for it in rss_items(body):
            it["source"] = "henricocitizen.com"
            out.append(it)
    except Exception as e:
        print(f"  [henricocitizen rss] {type(e).__name__}", file=sys.stderr)
    if days_back > 3:
        cutoff = today - timedelta(days=days_back)
        try:
            _, _, body = fetch("https://www.henricocitizen.com/sitemap-posts.xml")
            for loc, lm in sitemap_entries(body):
                dt = parse_pubdate(lm)
                if dt and dt >= cutoff:
                    out.append({"source": "henricocitizen.com", "title": slug_to_title(loc.rsplit("/", 1)[-1]),
                                "url": loc, "pubDate": lm, "_dt": dt})
        except Exception as e:
            print(f"  [henricocitizen sitemap] {type(e).__name__}", file=sys.stderr)
    return out


def collect_richmond_com(days_back, today):
    """RTD: walk dated editorial sitemaps (robots.txt blocks /tncms/search/)."""
    out = []
    seen = set()
    for d in range(days_back):
        dt = today - timedelta(days=d)
        u = f"https://richmond.com/tncms/sitemap/editorial.xml?date={dt.date().isoformat()}"
        try:
            _, _, body = fetch(u)
        except Exception:
            continue
        for loc, lm in sitemap_entries(body):
            if loc in seen:
                continue
            seen.add(loc)
            slug = loc.rsplit("/", 1)[-1]
            slug = re.sub(r"^(article|collection|gallery|collection)_", "", slug)
            slug = re.sub(r"\.(html|htm)$", "", slug)
            # RTD editorial sitemap uses opaque UUIDs, no keyword slugs — title comes
            # from a second fetch pass only for accepted candidates.
            out.append({"source": "richmond.com", "title": "", "url": loc,
                        "pubDate": "", "_dt": dt.replace(hour=12, tzinfo=timezone.utc)})
    return out


COLLECTORS = {
    "wtvr.com": collect_wtvr,
    "nbc12.com": collect_nbc12,
    "wric.com": collect_wric,
    "vpm.org": collect_vpm,
    "richmonder.org": collect_richmonder,
    "henricocitizen.com": collect_henricocitizen,
    "richmond.com": collect_richmond_com,
}


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            return json.load(open(STATE_FILE))
        except Exception:
            pass
    return {"seen_urls": {}, "processed_incidents": []}


def save_state(state):
    os.makedirs(STATE_DIR, exist_ok=True)
    json.dump(state, open(STATE_FILE, "w"), indent=1)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["daily", "backfill"], default="daily")
    ap.add_argument("--days", type=int, default=2, help="days of coverage (backfill)")
    ap.add_argument("--fresh", action="store_true", help="ignore state, dont skip seen URLs")
    ap.add_argument("--max-fetch", type=int, default=40, help="max article bodies to fetch per run")
    ap.add_argument("--output", default=CAND_FILE)
    args = ap.parse_args()

    today = datetime.now(timezone.utc)
    days_back = args.days if args.mode == "backfill" else 2

    state = load_state()
    if args.fresh:
        state["seen_urls"] = {}

    # --- collect raw entries ---
    raw = []
    for name, fn in COLLECTORS.items():
        try:
            items = fn(days_back, today)
            print(f"  {name}: {len(items)} raw entries", file=sys.stderr)
            raw.extend(items)
        except Exception as e:
            print(f"  {name}: COLLECTOR FAILED {type(e).__name__} {e}", file=sys.stderr)

    # dedupe within a source by URL; normalize link->url for RSS items
    by_url = {}
    for it in raw:
        if not it.get("url"):
            it["url"] = it.get("link") or ""
        if not it.get("url"):
            continue
        u = it["url"].split("?")[0].rstrip("/")
        if u and u not in by_url:
            by_url[u] = it
    raw = list(by_url.values())
    print(f"  collected unique URLs: {len(raw)}", file=sys.stderr)

    # --- filter: crash keywords in title or slug ---
    # RTD URLs are opaque UUIDs (no signal) — they bypass the keyword gate and
    # get screened by the title-resolve pass below.
    candidates = []
    skipped_seen = 0
    skipped_kw = 0
    rtd_all = []
    for it in raw:
        u = it["url"]
        norm = u.split("?")[0].rstrip("/")
        if norm in state["seen_urls"] and not args.fresh:
            skipped_seen += 1
            continue
        if it["source"] == "richmond.com" and not it.get("title"):
            rtd_all.append(it)
            continue
        text_probe = (it.get("title") or "") + " " + re.sub(r"[-_/]", " ", u)
        if not CRASH_RE.search(text_probe):
            skipped_kw += 1
            continue
        if NON_TRAFFIC_RE.search(it.get("title") or ""):
            skipped_kw += 1
            continue
        candidates.append(it)
    print(f"  keyword filter: {len(candidates)} candidates ({skipped_kw} non-crash, "
          f"{skipped_seen} already seen, {len(rtd_all)} RTD to resolve)", file=sys.stderr)

    # RTD: resolve <title> for every URL in budget; keep only crash-titled ones.
    if rtd_all:
        print(f"  resolving {len(rtd_all)} RTD article titles...", file=sys.stderr)
        kept = []
        for c in rtd_all[:args.max_fetch]:
            try:
                _, _, pbody = fetch(c["url"], max_bytes=200000)
                tm = re.search(r"<title[^>]*>(.*?)</title>", pbody, re.S | re.I)
                if tm:
                    ttl = re.sub(r"\s+", " ", strip_cdata(tm.group(1))).strip()
                    c["title"] = ttl
                    # strip site suffix
                    c["title"] = re.sub(r"\s*\|\s*(Richmond|richmond\.com).*$", "", c["title"])
                    if CRASH_RE.search(c["title"]) and not NON_TRAFFIC_RE.search(c["title"]):
                        c["body"] = extract_body(pbody)
                        c["fetched"] = True
                        kept.append(c)
                state["seen_urls"][c["url"].split("?")[0].rstrip("/")] = today.strftime("%Y-%m-%d")
            except Exception:
                pass
        candidates += kept

    # --- fetch article bodies for candidates (cap at max_fetch) ---
    results = []
    for i, c in enumerate(candidates[:args.max_fetch]):
        url = c["url"]
        try:
            _, _, body = fetch(url, max_bytes=500000)
            c["body"] = extract_body(body)
            c["fetched"] = True
        except Exception as e:
            c["body"] = ""
            c["fetch_error"] = f"{type(e).__name__}: {e}"
        c["_dt"] = (c.get("_dt") or parse_pubdate(c.get("pubDate")))
        c["_dt_iso"] = c["_dt"].isoformat() if c["_dt"] else ""
        c.pop("_dt", None)
        results.append(c)
        # mark seen
        state["seen_urls"][url.split("?")[0].rstrip("/")] = today.strftime("%Y-%m-%d")

    state["last_run"] = {"at": today.isoformat(), "mode": args.mode,
                         "candidates": len(results)}
    save_state(state)

    with open(args.output, "w") as f:
        json.dump({"generated": today.isoformat(), "mode": args.mode,
                   "days_back": days_back, "articles": results}, f, indent=1)
    print(f"  wrote {len(results)} candidate articles -> {args.output}", file=sys.stderr)
    print(json.dumps({"candidates": len(results), "output": args.output,
                      "state_file": STATE_FILE}))


if __name__ == "__main__":
    main()
