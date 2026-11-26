#!/usr/bin/env python3
"""
Build the RVA Crash Tracker map visualization from the Google Sheet.

Pipeline:
  1. Read Crashes!A2:I500 from the tracker sheet.
  2. Resolve each Location to lat/lon using a persistent cache
     (default ~/.hermes/state/rva_map_geocode.json):
       a. exact cache hit
       b. US Census geocoder (best for street addresses / intersections)
       c. Photon geocoder restricted to the Richmond-metro bbox
          (Photon alone will happily return a same-named street in another state)
       d. curated highway/interchange anchors (mile markers, ramps)
       e. locality centroid, flagged approx=True
  3. Write output/rva_crash_map.html (Leaflet), output/rva_crashes.geojson, and
     output/rva_crash_incidents.json.

Usage:
  python3 build_crash_map.py                 # build with cache, geocode new locations
  python3 build_crash_map.py --no-geocode    # skip network, approx for unknown
  python3 build_crash_map.py --refresh-cache # re-geocode everything

Screenshot (headless Chromium, no display needed):
  python3 -m http.server 8791 --bind 127.0.0.1 --directory output &
  ~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome --headless --no-sandbox \
      --disable-gpu --hide-scrollbars --window-size=1600,1000 --virtual-time-budget=15000 \
      --screenshot=output/rva_crash_map.png http://127.0.0.1:8791/rva_crash_map.html
"""
import argparse
import difflib
import json
import os
import re
import time
from collections import Counter
from urllib.parse import quote
from urllib.request import Request, urlopen

from google.auth.transport.requests import Request as GRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from map_anchors import load_anchors, match as match_anchor

import rva_paths as paths

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = paths.OUTPUT_DIR
# Coverage began with a 30-day backfill from launch, so tracked crashes start in late
# August. One real 2026-05-23 crash was logged during setup; it is plotted but flagged
# pre_window so reports can separate it (66 tracked + 1).
WINDOW_START = paths.WINDOW_START
TOKEN = paths.TOKEN
CACHE = paths.GEOCODE_CACHE
TEMPLATE = paths.TEMPLATE

LAT_MIN, LAT_MAX, LON_MIN, LON_MAX = 37.15, 37.95, -78.05, -77.05
UA = {"User-Agent": "Mozilla/5.0 (RVA-Crash-Tracker map builder)"}

LOCALITY_ALIASES = {
    "Richmond": "City of Richmond",
    "Henrico": "Henrico County",
    "Hanover": "Hanover County",
    "Chesterfield": "Chesterfield County",
}

# Curated anchors for locations no geocoder resolves (highways, ramps, vague references).
# Match on all `keys` appearing (case-insensitive) in the location string.
ANCHORS = [
    (("i-95", "lewistown"), 37.730, -77.442, "I-95 Exit 89 / Lewistown Rd, Hanover"),
    (("i-95", "chamberlayne"), 37.566, -77.452, "I-95 Exit 79 / Chamberlayne Ave"),
    (("i-95", "seventh" ), 37.535, -77.432, "7th St overpass, downtown Richmond"),
    (("i-95", "bensley"), 37.442, -77.462, "I-95 MM 67, Bensley"),
    (("i-95", "ruffin mill"), 37.305, -77.395, "Exit 58 Ruffin Mill Rd, Chesterfield"),
    (("i-95", "288"), 37.435, -77.462, "Rt 288 / I-95 interchange"),
    (("i-64", "parham"), 37.622, -77.560, "I-64 MM 182 / Parham Rd"),
    (("i-64", "250"), 37.638, -77.630, "I-64 Exit 178 / Rt 250 Short Pump"),
    (("i-64", "gayton"), 37.645, -77.640, "I-64 MM 176.3 / N Gayton Rd"),
    (("i-64", "i-95"), 37.545, -77.443, "I-64/I-95 downtown interchange"),
    (("i-64", "217"), 37.442, -77.060, "I-64 MM 217 (New Kent line area)"),
    (("i64", "217"), 37.442, -77.060, "I-64 MM 217 (New Kent line area)"),
    (("i-295", "portugee"), 37.525, -77.300, "Portugee Rd, eastern Henrico"),
    (("i-295", "creighton"), 37.545, -77.340, "Creighton Rd / I-295, eastern Henrico"),
    (("i-295", "eastern"), 37.520, -77.300, "I-295 eastern Henrico"),
    (("woods edge",), 37.345, -77.405, "I-95 Exit 58 / Woods Edge Rd, Chesterfield"),
    (("i-295",), 37.585, -77.430, "I-295 in Henrico"),
    (("288", "courthouse"), 37.505, -77.640, "Rt 288 / Courthouse Rd, Midlothian"),
    (("new market", "turner"), 37.470, -77.330, "New Market Rd (Rt 5), Varina"),
    (("nuckols", "295"), 37.655, -77.578, "Nuckols Rd / I-295 overpass"),
    (("lakeridge",), 37.720, -77.450, "Lakeridge Pkwy off Lewistown Rd, Hanover"),
    (("washington highway",), 37.733, -77.471, "Rt 1 / Washington Hwy, Ashland"),
    (("glen allen",), 37.666, -77.506, "Glen Allen"),
]
LOCALITY_CENTROID = {
    "City of Richmond": (37.545, -77.460),
    "Henrico County": (37.610, -77.500),
    "Chesterfield County": (37.430, -77.550),
    "Hanover County": (37.760, -77.470),
    "Charles City County": (37.370, -77.070),
}
CITY_FOR = {
    "Henrico County": ["Henrico", "Richmond", "Glen Allen"],
    "Chesterfield County": ["Chesterfield", "Midlothian", "Chester", "Richmond"],
    "Hanover County": ["Ashland", "Hanover", "Mechanicsville", "Glen Allen"],
    "City of Richmond": ["Richmond"],
    "Charles City County": ["Charles City"],
}


def sheets_client():
    td = json.load(open(TOKEN))
    creds = Credentials(token=td.get("token"), refresh_token=td.get("refresh_token"),
                        token_uri=td.get("token_uri"), client_id=td.get("client_id"),
                        client_secret=td.get("client_secret"), scopes=td.get("scopes"))
    if creds.expired and creds.refresh_token:
        creds.refresh(GRequest())
        td["token"] = creds.token
        td.pop("expiry", None)  # never persist expiry (Hermes rewrites this file)
        json.dump(td, open(TOKEN, "w"), indent=2)
    return build("sheets", "v4", credentials=creds)


def census(street, city):
    url = ("https://geocoding.geo.census.gov/geocoder/locations/address?"
           f"street={quote(street)}&city={quote(city)}&state=VA"
           "&benchmark=Public_AR_Current&format=json")
    try:
        with urlopen(Request(url, headers=UA), timeout=15) as r:
            d = json.loads(r.read().decode())
        m = d.get("result", {}).get("addressMatches", [])
        if m:
            c = m[0]["coordinates"]
            return {"lat": c["y"], "lon": c["x"], "display": m[0]["matchedAddress"], "approx": False}
    except Exception:
        pass
    return None


def photon(q):
    url = f"https://photon.komoot.io/api/?q={quote(q)}&limit=5&lang=en"
    try:
        with urlopen(Request(url, headers=UA), timeout=15) as r:
            d = json.loads(r.read().decode())
    except Exception:
        return None
    for f in d.get("features", []):
        lon, lat = f["geometry"]["coordinates"][:2]
        if LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX:
            p = f["properties"]
            label = ", ".join(x for x in [p.get("name"), p.get("street"), p.get("city"), p.get("county")] if x)
            return {"lat": lat, "lon": lon, "display": label, "approx": False}
    return None


def street_candidates(loc):
    base = re.sub(r"\s*,?\s*(Henrico County|Chesterfield County|Hanover County|"
                  r"City of Richmond|Charles City County)\s*$", "", loc, flags=re.I)
    out = []
    m = re.match(r"(\d+)(?:st|nd|rd|th)?\s+block of\s+(.+)", base, re.I)
    if m:
        out += [f"{m.group(1)} {m.group(2)}", m.group(2)]
    for sep in (" & ", " and "):
        if sep in base:
            a, b = base.split(sep, 1)
            out += [a.strip(), b.strip()]
            break
    out.append(base)
    cleaned = []
    for s in out:
        s = re.sub(r"\(.*?\)", "", s)
        s = re.split(r"\s+(?:near|just south of|just north of|area of|in the area of)\s+", s, flags=re.I)[0]
        s = s.strip(" ,.-")
        if s and s not in cleaned:
            cleaned.append(s)
    return cleaned


def anchor_for(loc):
    for keys, lat, lon, why in ANCHORS:
        if all(k in loc.lower() for k in keys):
            return {"lat": lat, "lon": lon, "display": f"APPROXIMATE ({why})", "approx": True}
    return None


def geocode(loc, locality):
    got = anchor_for(loc)
    if got:
        return got
    for cand in street_candidates(loc):
        for city in CITY_FOR.get(locality, ["Richmond"]):
            got = census(cand, city)
            if got:
                return got
            time.sleep(0.15)
    clean = re.sub(r"^\d+(?:st|nd|rd|th)?\s+block of\s+", "", loc, flags=re.I)
    got = photon(clean + ", Virginia")
    if got:
        return got
    lat, lon = LOCALITY_CENTROID.get(locality, (37.55, -77.48))
    return {"lat": lat, "lon": lon, "display": f"APPROXIMATE ({locality} centroid)", "approx": True}


def best_cached(loc, cache):
    if loc in cache:
        return cache[loc]
    def norm(s):
        s = s.lower()
        s = re.sub(r"\([^)]*\)", " ", s)
        # qualitative tails add noise, not signal: "near X", "in front of Y"
        s = re.split(r"\b(?:near|in front of|just south of|just north of|in the area of)\b", s)[0]
        s = re.sub(r"\b(intersection of|block of|the|henrico county|chesterfield county|"
                   r"hanover county|city of richmond|richmond|henrico|hanover)\b", " ", s)
        s = re.sub(r"[^a-z0-9 ]", " ", s)
        return " ".join(s.split())
    ranked = sorted(((difflib.SequenceMatcher(None, norm(loc), norm(k)).ratio(), k) for k in cache),
                    reverse=True)
    if ranked and ranked[0][0] >= 0.85:
        return cache[ranked[0][1]]
    return None


def num(s):
    s = (s or "").strip().lower()
    if not s or s in ("none", "none reported", "not reported"):
        return 0
    m = re.search(r"\d+", s)
    return int(m.group()) if m else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-geocode", action="store_true")
    ap.add_argument("--refresh-cache", action="store_true")
    args = ap.parse_args()

    cache = {}
    if os.path.exists(CACHE) and not args.refresh_cache:
        cache = json.load(open(CACHE))

    sheet_id = paths.sheet_id()
    sh = sheets_client()
    rows = sh.spreadsheets().values().get(
        spreadsheetId=sheet_id, range="Crashes!A2:I500").execute().get("values", [])

    anchors = load_anchors()
    incidents, missing = [], 0
    for i, r in enumerate(rows, start=2):
        r = (r + [""] * 9)[:9]
        date, tm, loc, locality, what, inj, fat, src, links = r
        locality = (locality or "").strip()
        locality = LOCALITY_ALIASES.get(locality, locality)
        # A vague string like "I-95 northbound (Hanover County)" must not inherit a
        # coordinate from a fuzzy cache hit on a different I-95 segment, so fuzzy
        # reuse is limited to locations with an address number or a cross street.
        specific = bool(re.search(r"\b\d{3,}\b", loc)) or "&" in loc or " and " in loc.lower()
        # Verified row anchors beat everything: they came from real OSM geometry, a
        # mile-marker interpolation, or a confirmed street address.
        g = None
        hit = match_anchor(loc, anchors)
        if hit:
            lat, lon, conf, how = hit
            g = {"lat": lat, "lon": lon, "display": f"{conf.upper()} ({how})",
                 "approx": conf != "surveyed", "confidence": conf, "how": how}
        g = g or cache.get(loc) or anchor_for(loc) or (best_cached(loc, cache) if specific else None)
        if not g and not args.no_geocode:
            if specific:
                g = geocode(loc, locality)
            else:
                # Vague reference ("I-95 northbound (Hanover County)"): a geocoder will
                # snap it to some arbitrary point on the highway, often in the wrong
                # jurisdiction. Locality centroid + approx flag is the honest answer.
                lat0, lon0 = LOCALITY_CENTROID.get(locality, (37.55, -77.48))
                g = {"lat": lat0, "lon": lon0,
                     "display": f"APPROXIMATE ({locality} centroid)", "approx": True}
            cache[loc] = g
            print(f"  geocoded: {loc[:60]} -> {g['lat']:.4f},{g['lon']:.4f}{' (approx)' if g['approx'] else ''}")
        if not g:
            missing += 1
            lat, lon = LOCALITY_CENTROID.get(locality, (37.55, -77.48))
            g = {"lat": lat, "lon": lon, "display": "APPROXIMATE (no geocode)", "approx": True}
        f, j = num(fat), num(inj)
        incidents.append({
            "row": i, "date": date, "time": tm, "location": loc, "locality": locality,
            "what": what, "injuries": inj, "fatalities": fat, "fatal_n": f, "inj_n": j,
            "severity": "fatal" if f else ("injury" if j else "property"),
            "sources": src, "links": links, "lat": g["lat"], "lon": g["lon"],
            "approx": bool(g.get("approx")), "month": (date or "")[:7],
            # The sheet keeps one genuinely-reported 2026-05-23 crash from before
            # tracking began. It stays on the map, but counts as pre-window so the
            # daily report can say "66 tracked + 1 earlier" instead of a bare 67.
            "pre_window": bool(date) and date < WINDOW_START,
            "geo_confidence": g.get("confidence", "approximate"),
            "geo_how": g.get("how", g.get("display", "")),
        })

    os.makedirs(OUT_DIR, exist_ok=True)
    json.dump(cache, open(CACHE, "w"), indent=2)
    json.dump(incidents, open(os.path.join(OUT_DIR, "rva_crash_incidents.json"), "w"), indent=1)

    feats = [{"type": "Feature",
              "geometry": {"type": "Point", "coordinates": [x["lon"], x["lat"]]},
              "properties": {k: v for k, v in x.items() if k not in ("lat", "lon")}}
             for x in incidents]
    json.dump({"type": "FeatureCollection", "features": feats},
              open(os.path.join(OUT_DIR, "rva_crashes.geojson"), "w"), indent=1)

    tpl = open(TEMPLATE).read()
    html = tpl.replace("__DATA__", json.dumps(incidents, ensure_ascii=False))
    open(os.path.join(OUT_DIR, "rva_crash_map.html"), "w").write(html)

    pre = sum(1 for x in incidents if x.get("pre_window"))
    print(f"incidents={len(incidents)} (window={len(incidents) - pre}, pre_window={pre}) "
          f"approx={sum(1 for x in incidents if x['approx'])} ungeocoded={missing}")
    print("by locality:", dict(Counter(x["locality"] for x in incidents)))
    print("by severity:", dict(Counter(x["severity"] for x in incidents)))
    print("outputs:", OUT_DIR)


if __name__ == "__main__":
    main()
