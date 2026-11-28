#!/usr/bin/env python3
"""
Verified map anchors for specific sheet rows.

Each entry was resolved against real geometry (OSM highway/cross-street closest approach),
an OSM mile-marker or motorway-junction interpolation, a US Census address match, or a
business address confirmed in the article. `how` records which, so a reviewer can tell a
surveyed point from an interpolated one. Interpolated mile-marker points are snapped
onto the roadway centreline afterwards (linear interpolation cuts corners on curves).

Rows are keyed by sheet row number because location strings are inconsistent
(parentheticals, "Intersection of", block ranges) and regex matching proved fragile.

Maintenance: when the daily cron inserts rows, row numbers shift. build_crash_map.py
therefore matches on the location string first and falls back to row number only when the
string still matches ROW_LOCATION_HINTS.

Regenerate the underlying geometry with:
    python3 osm_download.py && python3 overpass_anchors.py && python3 mm_reference.py
"""
import json
import os

ANCHORS_PATH = os.path.expanduser("~/.hermes/state/rva_map_row_anchors.json")

# row -> (lat, lon, confidence, how)
# confidence: "surveyed" (two ways intersect, gap < 50 m, or a geocoded street address)
#             "interpolated" (mile-marker interpolation between OSM junctions)
#             "midpoint" (vague source: corridor midpoint inside the locality)
ROW_ANCHORS = {
    65: (37.34961, -77.36518, "surveyed", "OSM shared intersection node (gap 0.0 m)"),
    64: (37.48578, -77.53426, "surveyed", "OSM shared intersection node (gap 0.0 m)"),
    57: (37.54145, -77.44169, "surveyed", "OSM shared intersection node (gap 0.0 m)"),
    54: (37.49529, -77.55600, "surveyed", "OSM shared intersection node (gap 0.0 m)"),
    49: (37.61058, -77.53783, "surveyed", "OSM shared intersection node (gap 0.0 m)"),
    48: (37.53995, -77.43469, "surveyed", "OSM shared intersection node (gap 0.0 m)"),
    47: (37.53125, -77.42492, "surveyed", "OSM shared intersection node (gap 0.0 m)"),
    46: (37.62405, -77.63800, "surveyed", "OSM shared intersection node (gap 0.0 m)"),
    43: (37.54204, -77.45724, "surveyed", "OSM shared intersection node (gap 0.0 m)"),
    40: (37.61858, -77.49948, "surveyed", "OSM shared intersection node (gap 0.0 m)"),
    39: (37.52121, -77.32824, "surveyed", "OSM shared intersection node (gap 0.0 m)"),
    34: (37.53467, -77.56136, "surveyed", "OSM shared intersection node (gap 0.0 m)"),
    32: (37.59010, -77.50399, "surveyed", "OSM shared intersection node (gap 0.0 m)"),
    15: (37.62293, -77.47756, "surveyed", "OSM shared intersection node (gap 0.0 m)"),
    10: (37.55230, -77.54818, "surveyed", "OSM shared intersection node (gap 0.0 m)"),
    7: (37.63650, -77.54984, "surveyed", "OSM shared intersection node (gap 0.0 m)"),
    6: (37.59695, -77.60707, "surveyed", "OSM shared intersection node (gap 0.0 m)"),
    28: (37.53042, -77.62477, "surveyed", "OSM address node 2700 Old Gun Road W"),
    27: (37.36196, -77.41662, "surveyed", "OSM addresses 11920-12020 Jefferson Davis Hwy"),
    20: (37.71429, -77.62385, "surveyed", "OSM addresses 15104-15240 Ashland Rd"),
    18: (37.54122, -77.43909, "surveyed", "OSM shared intersection node (gap 0.0 m)"),
    4: (37.23936, -77.52928, "surveyed", "OSM address node 9000 River Rd (Chesterfield); corrects a Census match to a Henrico River Rd"),
    67:  (37.65325, -77.62105, "surveyed", "Lauderdale Dr x W Broad St geometry"),
    63:  (37.48019, -77.64654, "surveyed", "OSM addresses 1010-1224 Kingscross Rd"),
    62:  (37.50293, -77.57456, "surveyed", "OSM address node 9700 Midlothian Tpke; previously collapsed onto the 7700 block"),
    60:  (37.78690, -77.41856, "surveyed", "OSM addresses 9174-9332 Hickory Hill Rd"),
    53:  (37.50032, -77.53863, "surveyed", "OSM address node 7700 Midlothian Tpke"),
    41:  (37.39647, -77.47240, "surveyed", "OSM addresses 8746-8824 Chester Forest Ln"),
    38:  (37.33839, -77.44655, "surveyed", "OSM address node 13000 Harrowgate Rd"),
    37:  (37.37522, -77.60134, "surveyed", "OSM address node 10000 Spring Run Rd"),
    36:  (37.61284, -77.52028, "surveyed", "OSM address node 7200 W Broad St; previously collapsed onto the 7800 block"),
    30:  (37.48672, -77.49737, "surveyed", "OSM address node 5700 Hull Street Rd (interpolated 5696-5724)"),
    29:  (37.42852, -77.49412, "surveyed", "OSM address node 6400 Iron Bridge Pl"),
    2:  (37.70211, -77.44875, "interpolated", "OSM mile-marker 88 node on I-95"),
    5:  (37.26588, -77.56399, "surveyed", "Census address 10300 River Rd; between Chesdin Ridge Dr and Chesdin Park Dr"),
    8:  (37.48800, -76.97770, "interpolated", "I-64 MM 217, interpolated between OSM exits 214 and 220 (New Kent)"),
    9:  (37.42977, -77.31306, "surveyed", "New Market Rd x Turner Rd geometry"),
    11: (37.66483, -77.59533, "midpoint", "I-295 midpoint within Henrico (source gives no landmark)"),
    13: (37.49218, -77.29267, "midpoint", "I-295 midpoint in eastern Henrico"),
    16: (37.55124, -77.43948, "surveyed", "I-95 x Chamberlayne Ave crossing (unsnapped: the snapped centreline point is the I-64/I-95 junction used by row 21)"),
    19: (37.40935, -77.56515, "surveyed", "VA-288 x Courthouse Rd geometry"),
    21: (37.55083, -77.43813, "surveyed", "I-64 x I-95 interchange geometry"),
    22: (37.72102, -77.44870, "surveyed", "I-95 x Lewistown Rd geometry (Exit 89)"),
    23: (37.65173, -77.59765, "interpolated", "I-64 MM 178 (article text); exit 178 = Short Pump/Rt 250"),
    24: (37.35015, -77.37742, "surveyed", "OSM address node 900 W Hundred Rd"),
    25: (37.31166, -77.39827, "surveyed", "I-95 x Woods Edge Rd geometry (Exit 58)"),
    26: (37.80989, -77.46061, "midpoint", "I-95 midpoint within Hanover (source gives no landmark)"),
    31: (37.71936, -77.45327, "surveyed", "Lakeridge Pkwy x Lewistown Rd geometry"),
    33: (37.67099, -77.58148, "surveyed", "Nuckols Rd x I-295 geometry"),
    35: (37.29308, -77.41060, "surveyed", "Census address 16701 Jefferson Davis Hwy (Eagle Motors)"),
    44: (37.48976, -77.29468, "surveyed", "I-295 x Portugee Rd geometry"),
    45: (37.38324, -77.41531, "interpolated", "I-95 MM 62.8, bracketed by OSM exits 62 and 64"),
    50: (37.61587, -77.54147, "interpolated", "I-64 MM 182.2, bracketed by OSM exits 181 and 183"),
    51: (37.73314, -77.47100, "surveyed", "Census address 12100 Washington Hwy, Ashland"),
    52: (37.30708, -77.39521, "interpolated", "I-95 MM 57.9, bracketed by OSM exits 54 and 58"),
    55: (37.66313, -77.62990, "surveyed", "I-64 x N Gayton Rd overpass geometry (article cites MM 176.3; OSM exits 177/178 are coincident, so the named cross street is the more reliable anchor)"),
    56: (37.58113, -77.32882, "surveyed", "Creighton Rd x I-295 geometry"),
    58: (37.44748, -77.42320, "interpolated", "I-95 MM 67, bracketed by OSM exits 62 and 69"),
    59: (37.54702, -77.43034, "surveyed", "I-95 x N 7th St geometry"),
    61: (37.37801, -77.40910, "surveyed", "VA-288 x I-95 geometry"),
    68: (37.68813, -77.45207, "surveyed", "I-95 x Sliding Hill Rd crossing geometry (Exit 86 = MM 86), gap 0.4 m"),
    69: (37.47764, -77.71794, "surveyed", "Brightwalton Rd x Webster Crescent Ln shared OSM node (gap 0.0 m)"),
    70: (37.63003, -77.53562, "approximate", "W Broad St x N Parham Rd (source names only 'West Broad Street')"),
}

# Fallback matching when row numbers shift: (row, location substring)
ROW_LOCATION_HINTS = {
    65: "West Hundred Road & Rivers Bend",
    64: "Turner Road and Elkhardt",
    57: "North 3rd Street & East Main",
    54: "Gateway Centre Parkway & Midlothian",
    49: "Skipwith Road & Anoka",
    48: "East Grace Street & North 9th",
    47: "East Main Street & 21st",
    46: "Gayton Road and Ridgefield",
    43: "Idlewood Road & Harrison",
    40: "Staples Mill Road & Bremner",
    39: "Williamsburg Road & S. Airport",
    34: "Forest Hill Avenue & Buford",
    32: "W. Broad Street & Libbie",
    15: "Woodman Road and Delta",
    10: "Huguenot and Cherokee",
    7: "W. Broad Street and Tuckernuck",
    6: "Pump Road and Patterson",
    28: "2700 block of Old Gunn Road",
    27: "12000 block of Route 1",
    20: "15200 block of Ashland Road",
    67: "Lauderdale Drive & West Broad",
    63: "1200 block of Kingscross",
    62: "9700 block of Midlothian Turnpike",
    60: "9300 block of Hickory Hill",
    53: "7700 block of Midlothian Turnpike",
    41: "8800 block of Chester Forest",
    38: "13000 block of Harrowgate",
    37: "10000 block of Spring Run",
    36: "7200 block of W. Broad Street",
    30: "5700 block of Hull Street",
    29: "6400 block of Iron Bridge",
    18: "N. 5th and E. Franklin",
    4: "9000 block of River Road",
    2: "Lewistown Road exit",
    5: "10300 block of River Road",
    8: "mile marker 217, New Kent",
    9: "New Market Road near Turner Road",
    11: "I-295 northbound, Henrico",
    13: "I-295, eastern Henrico",
    16: "Chamberlayne Avenue exit",
    19: "Courthouse Road exit ramp",
    21: "I-64 westbound to I-95 southbound ramp",
    22: "I-95 northbound near Lewistown Road",
    23: "I-64 westbound at Route 250 exit",
    24: "900 block of W. Hundred Road",
    25: "mile marker 58, Woods Edge Road",
    26: "I-95 northbound (Hanover County)",
    31: "Lakeridge Parkway just south of Lewistown",
    33: "Nuckols Road at I-295 overpass",
    35: "Eagle Motors on Route 1",
    44: "Portugee Road",
    45: "mile marker 62.8",
    50: "Exit 181B",
    51: "12100 block of Washington Highway",
    52: "Ruffin Mill Road (Exit 58)",
    55: "mile marker 176.3",
    56: "Creighton Road in the area of the I-295",
    58: "mile marker 67 (Bensley",
    59: "Seventh Street overpass",
    61: "Ramp from Route 288 South",
    68: "mile marker 86",
    69: "Brightwalton Road & Webster Crescent",
    70: "West Broad Street, Henrico",
}


def load_anchors():
    """Return {location_hint: (lat, lon, confidence, how)} for joining against the sheet."""
    out = {}
    for row, (lat, lon, conf, how) in ROW_ANCHORS.items():
        out[ROW_LOCATION_HINTS[row]] = (lat, lon, conf, how)
    return out


def match(location, anchors):
    """Best anchor for a sheet Location string, or None."""
    loc = (location or "")
    best = None
    for hint, val in anchors.items():
        if hint in loc:
            # prefer the longest matching hint (most specific)
            if best is None or len(hint) > len(best[0]):
                best = (hint, val)
    return best[1] if best else None


if __name__ == "__main__":
    json.dump({str(k): v for k, v in ROW_ANCHORS.items()}, open(ANCHORS_PATH, "w"), indent=1)
    from collections import Counter
    c = Counter(v[2] for v in ROW_ANCHORS.values())
    print(f"{len(ROW_ANCHORS)} row anchors: {dict(c)}")
    print(f"wrote {ANCHORS_PATH}")
