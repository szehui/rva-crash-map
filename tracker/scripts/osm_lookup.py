#!/usr/bin/env python3
"""
Resolve a street address or intersection against OpenStreetMap data.

Why this exists: the US Census geocoder silently returns the wrong road when a street
name repeats across jurisdictions. "9000 River Road" in Chesterfield resolved to a River
Road in Henrico 12 km away, and "N. 5th and E. Franklin" resolved to "5 N Blvd". OSM has
per-jurisdiction address nodes and real way geometry, so we can do better:

  address()      - nearest addr:housenumber node for the street, or linear interpolation
                   between the bracketing house numbers on that street
  intersection() - closest approach between two named ways, reported with its gap

Every result carries a gap in metres so the caller can decide whether to trust it.

Usage:
    python3 osm_lookup.py addr "River Road" 9000 37.20 -77.60 37.30 -77.50
    python3 osm_lookup.py xing "North 5th Street" "East Franklin Street" 37.53 -77.46 37.56 -77.43
"""
import json
import math
import os
import re
import sys
import urllib.parse
import urllib.request

UA = {"User-Agent": "RVA-Crash-Tracker/1.0 (crash map geocoding)"}
ENDPOINTS = [
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]


import rva_paths as paths

CACHE = paths.OSM_LOOKUP_CACHE


def _cache_load():
    try:
        return json.load(open(CACHE))
    except Exception:
        return {}


def overpass(query, timeout=60):
    cache = _cache_load()
    if query in cache:
        return cache[query]
    data = urllib.parse.urlencode({"data": query}).encode()
    last = None
    for ep in ENDPOINTS:
        try:
            req = urllib.request.Request(ep, data=data, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                result = json.loads(r.read().decode())
                cache[query] = result
                json.dump(cache, open(CACHE, "w"))
                return result
        except Exception as e:  # mirror down, rate limited, timeout
            last = e
    raise RuntimeError(f"all Overpass mirrors failed: {last}")


def dist_m(a, b):
    R = 6371000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * R * math.asin(math.sqrt(h))


def _bbox(s, w, n, e):
    return f"({s},{w},{n},{e})"


def _housenumber(tags):
    m = re.match(r"(\d+)", tags.get("addr:housenumber", "") or "")
    return int(m.group(1)) if m else None


def address(street_regex, number, s, w, n, e):
    """Locate a house number on a street. Returns (lat, lon, gap_m, how)."""
    q = f"""[out:json][timeout:50];
(
  node["addr:street"~"{street_regex}",i]["addr:housenumber"]{_bbox(s,w,n,e)};
  way["addr:street"~"{street_regex}",i]["addr:housenumber"]{_bbox(s,w,n,e)};
  node["addr:place"~"{street_regex}",i]["addr:housenumber"]{_bbox(s,w,n,e)};
);
out center;"""
    els = overpass(q)["elements"]
    pts = []
    for el in els:
        hn = _housenumber(el.get("tags", {}))
        if hn is None:
            continue
        c = el.get("center") or {"lat": el.get("lat"), "lon": el.get("lon")}
        if c.get("lat") is None:
            continue
        pts.append((hn, c["lat"], c["lon"]))
    if not pts:
        return None
    # exact house number wins
    exact = [p for p in pts if p[0] == number]
    if exact:
        hn, la, lo = exact[0]
        return (round(la, 5), round(lo, 5), 0.0, f"exact OSM address node {hn}")
    # otherwise interpolate between bracketing odd/even numbers on the same side
    side = number % 2
    same = sorted([p for p in pts if p[0] % 2 == side])
    lo_pts = [p for p in same if p[0] < number]
    hi_pts = [p for p in same if p[0] > number]
    if lo_pts and hi_pts:
        a, b = lo_pts[-1], hi_pts[0]
        t = (number - a[0]) / (b[0] - a[0])
        lat = a[1] + t * (b[1] - a[1])
        lon = a[2] + t * (b[2] - a[2])
        return (round(lat, 5), round(lon, 5), 0.0,
                f"interpolated between {a[0]} and {b[0]}")
    # fall back to the nearest known number
    nearest = min(pts, key=lambda p: abs(p[0] - number))
    return (round(nearest[1], 5), round(nearest[2], 5),
            abs(nearest[0] - number), f"nearest OSM address {nearest[0]}")


def intersection(a_regex, b_regex, s, w, n, e):
    """Closest approach between two named ways. Returns (lat, lon, gap_m)."""
    q = f"""[out:json][timeout:50];
way["name"~"{a_regex}",i]{_bbox(s,w,n,e)};
out geom;
way["name"~"{b_regex}",i]{_bbox(s,w,n,e)};
out geom;"""
    els = overpass(q)["elements"]
    A = [el for el in els if re.search(a_regex, el.get("tags", {}).get("name", ""), re.I)]
    B = [el for el in els if re.search(b_regex, el.get("tags", {}).get("name", ""), re.I)]
    if not A or not B:
        return None

    # Prefer a node shared by both ways: that is the actual intersection, exact.
    a_nodes = {(round(p["lat"], 6), round(p["lon"], 6)) for a in A for p in a.get("geometry", [])}
    b_nodes = {(round(p["lat"], 6), round(p["lon"], 6)) for b in B for p in b.get("geometry", [])}
    shared = a_nodes & b_nodes
    if shared:
        # if several, take the one closest to the centroid of all shared nodes
        clat = sum(p[0] for p in shared) / len(shared)
        clon = sum(p[1] for p in shared) / len(shared)
        best = min(shared, key=lambda p: dist_m((clat, clon), p))
        return (round(best[0], 5), round(best[1], 5), 0.0)

    # Otherwise closest approach; report the point ON the first way rather than a
    # midpoint, which drifts when the ways are grade-separated (overpasses).
    best = (1e9, None, None)
    for a in A:
        for pa in a.get("geometry", []):
            ap = (pa["lat"], pa["lon"])
            for b in B:
                for pb in b.get("geometry", []):
                    bp = (pb["lat"], pb["lon"])
                    d = dist_m(ap, bp)
                    if d < best[0]:
                        best = (d, ap, bp)
    if best[1] is None:
        return None
    d, ap, _bp = best
    return (round(ap[0], 5), round(ap[1], 5), round(d, 1))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    mode = sys.argv[1]
    if mode == "addr":
        street, num, s, w, n, e = sys.argv[2], int(sys.argv[3]), *map(float, sys.argv[4:8])
        print(address(street, num, s, w, n, e))
    elif mode == "xing":
        a, b, s, w, n, e = sys.argv[2], sys.argv[3], *map(float, sys.argv[4:8])
        print(intersection(a, b, s, w, n, e))
    else:
        print(__doc__)
        sys.exit(1)
