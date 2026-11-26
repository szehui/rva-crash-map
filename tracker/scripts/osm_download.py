#!/usr/bin/env python3
"""
Step 1: download the OSM geometry we need once, cache it to disk.

Overpass mirrors time out under load, so network work is separated from the
(CPU-bound) closest-approach math in overpass_anchors.py. Runs incrementally: each
feature is saved as soon as it arrives, so a timeout only costs the in-flight item.

Usage: python3 osm_download.py [feature ...]   # no args = all
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

ENDPOINTS = [
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]
UA = {"User-Agent": "RVA-Crash-Tracker/1.0 (crash map geocoding)"}
import rva_paths as paths

OUT = paths.OSM_GEOMETRY
BBOX = "(37.15,-78.05,37.95,-77.05)"

# name -> ("ref", regex) for highways, ("name", exact) for streets
FEATURES = {
    "I-64": ("ref", "^I 64$"),
    "I-95": ("ref", "^I 95$"),
    "I-295": ("ref", "^I 295$"),
    "VA-288": ("ref", "^VA 288$"),
    "N Gayton Rd": ("name", "North Gayton Road"),
    "Parham Rd": ("name", "Parham Road"),
    "N Parham Rd": ("name", "North Parham Road"),
    "S Parham Rd": ("name", "South Parham Road"),
    "Bensley Rd2": ("name", "Bensley Road"),
    "Jefferson Davis Hwy": ("name", "Jefferson Davis Highway"),
    "Midlothian Tpke": ("name", "Midlothian Turnpike"),
    "W Broad St": ("name", "West Broad Street"),
    "Lewistown Rd": ("name", "Lewistown Road"),
    "Chamberlayne Ave": ("name", "Chamberlayne Avenue"),
    "N 7th St": ("name", "North 7th Street"),
    "Ruffin Mill Rd": ("name", "Ruffin Mill Road"),
    "Woods Edge Rd": ("name", "Woods Edge Road"),
    "Bensley Rd": ("name", "Bensley Road"),
    "Nuckols Rd": ("name", "Nuckols Road"),
    "Creighton Rd": ("name", "Creighton Road"),
    "Portugee Rd": ("name", "Portugee Road"),
    "Courthouse Rd": ("name", "Courthouse Road"),
    "Lakeridge Pkwy": ("name", "Lakeridge Parkway"),
    "New Market Rd": ("name", "New Market Road"),
    "Turner Rd": ("name", "Turner Road"),
    "Rivers Bend Rd": ("name", "Rivers Bend Road"),
    "W Hundred Rd": ("name", "West Hundred Road"),
}


def fetch(query):
    last = None
    for ep in ENDPOINTS:
        for attempt in range(2):
            try:
                req = urllib.request.Request(
                    ep, data=urllib.parse.urlencode({"data": query}).encode(), headers=UA)
                with urllib.request.urlopen(req, timeout=90) as r:
                    return json.loads(r.read().decode())
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(2)
    raise RuntimeError(repr(last))


def main():
    want = sys.argv[1:] or list(FEATURES)
    cache = json.load(open(OUT)) if os.path.exists(OUT) else {}
    for key in want:
        if key in cache:
            print(f"cached {key} ({len(cache[key])} segments)", flush=True)
            continue
        kind, val = FEATURES[key]
        flt = f'["highway"]["ref"~"{val}"]' if kind == "ref" else f'["name"="{val}"]'
        q = f"[out:json][timeout:120];way{flt}{BBOX};out geom;"
        try:
            data = fetch(q)
        except Exception as e:  # noqa: BLE001
            print(f"FAIL   {key}: {e}", flush=True)
            continue
        segs = []
        for el in data.get("elements", []):
            pts = [[round(p["lat"], 6), round(p["lon"], 6)] for p in (el.get("geometry") or []) if p]
            if len(pts) >= 2:
                segs.append(pts)
        cache[key] = segs
        json.dump(cache, open(OUT, "w"))
        print(f"OK     {key}: {len(segs)} segments", flush=True)
        time.sleep(0.5)
    print(f"\n{len(cache)} features cached -> {OUT}", flush=True)


if __name__ == "__main__":
    main()
