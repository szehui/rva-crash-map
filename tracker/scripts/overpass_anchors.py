#!/usr/bin/env python3
"""
Step 2: compute real highway/cross-street crossing points from the cached OSM geometry.

Reads ~/.hermes/state/osm_geometry.json (from osm_download.py) and writes
~/.hermes/state/rva_overpass_anchors.json, keyed by a human-readable pair name:

    {"I-64 x N Gayton Rd": {"lat": .., "lon": .., "gap_m": 3}}

`gap_m` is how far apart the two ways actually are at the closest point — a large gap
means the pair does not really intersect (grade-separated roads do cross; a gap of
hundreds of metres means the street does not touch that highway in this metro).

Usage: python3 overpass_anchors.py
"""
import json
import math
import os

import rva_paths as paths

GEOM = paths.OSM_GEOMETRY
OUT = paths.OVERPASS_ANCHORS

# anchor key -> (highway feature, cross feature)
PAIRS = {
    "I-64 x N Gayton Rd": ("I-64", "N Gayton Rd"),
    "I-64 x Parham Rd": ("I-64", "Parham Rd"),
    "I-64 x W Broad St": ("I-64", "W Broad St"),
    "I-64 x I-95": ("I-64", "I-95"),
    "I-95 x Lewistown Rd": ("I-95", "Lewistown Rd"),
    "I-95 x Chamberlayne Ave": ("I-95", "Chamberlayne Ave"),
    "I-95 x N 7th St": ("I-95", "N 7th St"),
    "I-95 x Ruffin Mill Rd": ("I-95", "Ruffin Mill Rd"),
    "I-95 x Woods Edge Rd": ("I-95", "Woods Edge Rd"),
    "I-95 x Bensley Rd": ("I-95", "Bensley Rd"),
    "I-95 x VA-288": ("I-95", "VA-288"),
    "I-295 x Nuckols Rd": ("I-295", "Nuckols Rd"),
    "I-295 x Creighton Rd": ("I-295", "Creighton Rd"),
    "I-295 x Portugee Rd": ("I-295", "Portugee Rd"),
    "VA-288 x Courthouse Rd": ("VA-288", "Courthouse Rd"),
}

LAT0, LON0 = 37.60, -77.50
M_PER_DEG_LAT = 111_320.0
M_PER_DEG_LON = 111_320.0 * math.cos(math.radians(LAT0))


def xy(pt):
    return (pt[1] * M_PER_DEG_LON, pt[0] * M_PER_DEG_LAT)


def densify(seg, step=25.0):
    out = []
    pts = [xy(p) for p in seg]
    for i in range(len(pts) - 1):
        (x1, y1), (x2, y2) = pts[i], pts[i + 1]
        d = math.hypot(x2 - x1, y2 - y1)
        n = max(1, int(d / step))
        for k in range(n):
            out.append((x1 + (x2 - x1) * k / n, y1 + (y2 - y1) * k / n))
    out.append(pts[-1])
    return out


def closest(a_segs, b_segs):
    """Closest approach between two sets of segments, with a 200 m grid index."""
    B = []
    for s in b_segs:
        B.extend(densify(s))
    grid = {}
    for x, y in B:
        grid.setdefault((int(x // 200), int(y // 200)), []).append((x, y))
    best = (1e18, None)
    for s in a_segs:
        for x, y in densify(s):
            cx, cy = int(x // 200), int(y // 200)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for bx, by in grid.get((cx + dx, cy + dy), ()):
                        d = math.hypot(x - bx, y - by)
                        if d < best[0]:
                            best = (d, ((x + bx) / 2, (y + by) / 2))
    d, mid = best
    if mid is None:
        return None
    return round(mid[1] / M_PER_DEG_LAT, 5), round(mid[0] / M_PER_DEG_LON, 5), round(d)


def main():
    geom = json.load(open(GEOM))
    out = {}
    for key, (a, b) in PAIRS.items():
        if a not in geom or b not in geom:
            print(f"skip  {key}: missing geometry ({a if a not in geom else b})")
            continue
        got = closest(geom[a], geom[b])
        if not got:
            print(f"miss  {key}")
            continue
        lat, lon, gap = got
        verdict = "ok" if gap <= 40 else ("CHECK" if gap <= 250 else "BAD")
        out[key] = {"lat": lat, "lon": lon, "gap_m": gap}
        print(f"{verdict:5s} {key:26s} {lat:.5f},{lon:.5f}  gap={gap}m")
    json.dump(out, open(OUT, "w"), indent=2)
    print(f"\nwrote {OUT} ({len(out)} anchors)")


if __name__ == "__main__":
    main()
