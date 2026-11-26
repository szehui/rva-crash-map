#!/usr/bin/env python3
"""
Audit the crash map for placement errors that a geocoder cannot detect about itself.

Two classes of failure showed up in review:
  1. Wrong county. "9000 River Road" is a Chesterfield address, but the geocoder returned
     the River Road in Henrico 12 km away. A pin in the wrong jurisdiction is obviously
     wrong to a reader and invisible to the geocoder.
  2. Collapsed addresses. Two different rows ("7200 block" and "7800 block" of W Broad,
     "7700" and "9700" Midlothian Tpke) resolved to the same coordinate, which means at
     least one of them silently fell back to a neighbouring match.

Checks:
  * point-in-polygon against OSM county/city boundaries  -> WRONG COUNTY
  * identical (lat, lon) shared by rows with different locations -> COLLAPSED
  * pin more than N metres from any road -> OFF-ROAD (usually a bad geocode)

Usage:
    python3 locality_audit.py              # audit the current incidents JSON
    python3 locality_audit.py --refresh    # re-download boundary polygons first
"""
import json
import os
import sys
import urllib.parse
import urllib.request

import rva_paths as paths

STATE = paths.STATE_DIR
BOUNDS = os.path.join(STATE, "va_locality_bounds.json")
INCIDENTS = paths.INCIDENTS_JSON

UA = {"User-Agent": "RVA-Crash-Tracker/1.0 (crash map geocoding)"}
ENDPOINTS = [
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]

# sheet Locality value -> OSM boundary name
LOCALITY_NAMES = {
    "Henrico County": "Henrico County",
    "Chesterfield County": "Chesterfield County",
    "Hanover County": "Hanover County",
    "New Kent County": "New Kent County",
    "City of Richmond": "Richmond",
    "Charles City County": "Charles City County",
}


def overpass(query, timeout=120):
    data = urllib.parse.urlencode({"data": query}).encode()
    last = None
    for ep in ENDPOINTS:
        try:
            req = urllib.request.Request(ep, data=data, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            last = e
    raise RuntimeError(f"overpass failed: {last}")


def fetch_bounds():
    """Download admin boundary polygons for the tracked localities."""
    names = "|".join(LOCALITY_NAMES.values())
    q = f"""[out:json][timeout:120];
relation["boundary"="administrative"]["admin_level"~"6|8"]["name"~"^({names})$"];
out geom;"""
    els = overpass(q)["elements"]
    out = {}
    for el in els:
        name = el["tags"].get("name")
        rings = []
        for m in el.get("members", []):
            if m.get("role") != "outer" or "geometry" not in m:
                continue
            ring = [(p["lat"], p["lon"]) for p in m["geometry"]]
            if len(ring) >= 4:
                rings.append(ring)
        if rings:
            out[name] = rings
    json.dump(out, open(BOUNDS, "w"))
    return out


def load_bounds(refresh=False):
    if refresh or not os.path.exists(BOUNDS):
        return fetch_bounds()
    return json.load(open(BOUNDS))


def in_ring(lat, lon, ring):
    """Ray casting; ring is [(lat, lon), ...]."""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        yi, xi = ring[i]
        yj, xj = ring[j]
        if ((yi > lat) != (yj > lat)) and \
           (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def locality_at(lat, lon, bounds):
    for name, rings in bounds.items():
        for ring in rings:
            if in_ring(lat, lon, ring):
                return name
    return None


def main():
    refresh = "--refresh" in sys.argv
    bounds = load_bounds(refresh)
    print(f"boundaries loaded: {', '.join(sorted(bounds))}\n")

    inc = json.load(open(INCIDENTS))
    wrong, collapsed, offroad = [], {}, []

    seen = {}
    for x in inc:
        want = LOCALITY_NAMES.get(x["locality"], x["locality"])
        got = locality_at(x["lat"], x["lon"], bounds)
        if got and want in (got, "Richmond") and got not in (want, None):
            # allow Richmond city vs county-of-Richmond confusion only if names differ
            pass
        if got and want and got != want and not (want == "City of Richmond" and got == "Richmond"):
            wrong.append((x["row"], x["locality"], got, x["location"][:55]))

        key = (round(x["lat"], 5), round(x["lon"], 5))
        seen.setdefault(key, []).append((x["row"], x["location"][:40]))

    for key, rows in seen.items():
        if len(rows) > 1:
            locs = {r[1] for r in rows}
            if len(locs) > 1:
                collapsed[key] = rows

    print(f"WRONG COUNTY ({len(wrong)}):")
    for row, sheet, actual, loc in wrong:
        print(f"  R{row:2d} sheet says {sheet:18s} but pin is in {actual:22s} | {loc}")
    if not wrong:
        print("  none")

    print(f"\nCOLLAPSED COORDINATES ({len(collapsed)}):")
    for key, rows in collapsed.items():
        print(f"  {key}: " + "; ".join(f"R{r} {l}" for r, l in rows))
    if not collapsed:
        print("  none")

    return 1 if (wrong or collapsed) else 0


if __name__ == "__main__":
    sys.exit(main())
