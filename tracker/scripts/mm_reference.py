#!/usr/bin/env python3
"""
Place a point at a mile marker on an interstate using OSM motorway-junction nodes.

Virginia exit numbers equal mile markers, so a sorted table of junctions for one
interstate is also a mile-marker calibration table. Interpolating between the two
junctions that bracket a target MM puts a point on the road within ~100 m -- far better
than a hand-typed anchor and no chaining required.

Writes ~/.hermes/state/rva_mm_points.json
"""
import json
import math
import os

import rva_paths as paths

GEOM = paths.OSM_GEOMETRY
JUNCTIONS = paths.OSM_JUNCTIONS
OUT = paths.MM_POINTS

M_PER_DEG_LAT = 111_320.0
M_PER_DEG_LON = 111_320.0 * math.cos(math.radians(37.6))


def near_highway(lat, lon, segs, tol_m=120.0):
    """Is this node within tol_m of the highway polyline?"""
    for s in segs:
        for p in s:
            dy = (p[0] - lat) * M_PER_DEG_LAT
            dx = (p[1] - lon) * M_PER_DEG_LON
            if dx * dx + dy * dy < tol_m * tol_m:
                return True
    return False


def table(hw, junctions, geom):
    segs = geom[hw]
    rows = [j for j in junctions if near_highway(j["lat"], j["lon"], segs)]
    # collapse A/B pairs: keep the one with the smaller suffix per MM
    by_mm = {}
    for j in sorted(rows, key=lambda r: (r["mm"], r["suffix"])):
        by_mm.setdefault(j["mm"], j)
    return [by_mm[k] for k in sorted(by_mm)]


def interp(tbl, mm):
    if not tbl:
        return None
    if mm <= tbl[0]["mm"]:
        a = b = tbl[0]
        t = 0.0
    elif mm >= tbl[-1]["mm"]:
        a = b = tbl[-1]
        t = 0.0
    else:
        for i in range(len(tbl) - 1):
            if tbl[i]["mm"] <= mm <= tbl[i + 1]["mm"]:
                a, b = tbl[i], tbl[i + 1]
                t = (mm - a["mm"]) / (b["mm"] - a["mm"])
                break
    lat = a["lat"] + (b["lat"] - a["lat"]) * t
    lon = a["lon"] + (b["lon"] - a["lon"]) * t
    span = abs(b["mm"] - a["mm"]) if a is not b else 0
    return round(lat, 5), round(lon, 5), span


def main():
    geom = json.load(open(GEOM))
    junctions = json.load(open(JUNCTIONS))

    targets = {
        "I-64": [176.3, 217.0, 178.0, 183.0],
        "I-95": [57.9, 62.8, 67.0, 88.0],
        "I-295": [],
    }
    out = {}
    for hw, mms in targets.items():
        tbl = table(hw, junctions, geom)
        if not tbl:
            print(f"{hw}: no junctions matched")
            continue
        print(f"\n{hw} exit table ({len(tbl)} junctions, MM {tbl[0]['mm']:.0f}-{tbl[-1]['mm']:.0f}):")
        print("   ", ", ".join(f"{r['mm']:.0f}" for r in tbl))
        for mm in mms:
            got = interp(tbl, mm)
            if not got:
                continue
            lat, lon, span = got
            key = f"{hw} MM{mm}"
            out[key] = {"lat": lat, "lon": lon, "bracket_span_mi": span,
                        "source": "OSM motorway_junction interpolation"}
            flag = "extrapolated" if span == 0 else f"bracketed ±{span/2:.1f} mi"
            print(f"  MM {mm:5.1f} -> {lat:.5f},{lon:.5f}   ({flag})")

    json.dump(out, open(OUT, "w"), indent=2)
    print(f"\nwrote {OUT} ({len(out)} points)")


if __name__ == "__main__":
    main()
