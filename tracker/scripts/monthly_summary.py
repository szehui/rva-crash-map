#!/usr/bin/env python3
"""
Monthly rollup of crash incidents for the previous calendar month.

Reads the incidents JSON that build_crash_map.py writes from the sheet, so the same
numbers back the map and the summary. Prints markdown facts; the cron agent turns them
into prose (this script never editorialises or infers beyond the sheet).

Usage:
    python3 monthly_summary.py                # previous month
    python3 monthly_summary.py --month 2026-10
    python3 monthly_summary.py --month 2026-10 --json
"""
import argparse
import calendar
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime

import rva_paths as paths

INCIDENTS = paths.INCIDENTS_JSON
OUTDIR = paths.MONTHLY_DIR

# A crash counts as a vulnerable-road-user crash when the article text describes someone
# on foot, on a bike, or on two wheels. Matched against the "what happened" column only —
# not the location — so a crash "near Bybee's Road" doesn't get counted as a bike crash.
VRU_PATTERNS = [
    ("pedestrian", r"\bpedestrian|\bwoman walking|\bman walking|\bhit by (a )?(car|truck|suv|van|vehicle)|struck by (a )?(car|truck|suv|van|vehicle)"),
    ("bicyclist", r"\bbicycl|\bbike\b|\bcyclist"),
    ("motorcyclist", r"\bmotorcycl|\bmoped|\bmotor ?bike"),
    ("scooter", r"\bscooter"),
    ("wheelchair", r"\bwheelchair"),
    ("skateboard", r"\bskateboard"),
]

DAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def parse_month(s):
    y, m = (int(x) for x in s.split("-"))
    return y, m


def previous_month(today=None):
    today = today or date.today()
    first = today.replace(day=1)
    prev_last = first.fromordinal(first.toordinal() - 1)
    return prev_last.year, prev_last.month


def vru_kind(text):
    t = (text or "").lower()
    hits = [name for name, pat in VRU_PATTERNS if re.search(pat, t)]
    return hits


def is_highway(location):
    loc = location or ""
    return bool(re.search(r"\bI-\d+|interstate|mile ?marker|\bMM ?\d+|Route \d+|VA-\d+", loc, re.I))


def weekday_of(date_str):
    try:
        return DAY_ORDER[datetime.strptime(date_str, "%Y-%m-%d").weekday()]
    except Exception:
        return None


def corridor_key(location):
    """Normalise a location string to a corridor name so counts actually aggregate."""
    loc = location or ""
    loc = re.sub(r"\([^)]*\)", "", loc)                                   # parentheticals
    loc = re.sub(r"^\s*Intersection of\s+", "", loc, flags=re.I)          # keep the streets
    loc = re.sub(r"^\s*(the\s+)?\d+[\d,]*\s*block of\s*", "", loc, flags=re.I)
    loc = re.sub(r"\s+(?:near|just (?:before|after)|in the area of)\s+.*$", "", loc, flags=re.I)
    loc = loc.strip(" ,.")

    # highway designators first: I-95 northbound, Route 1, VA-288, US 60
    m = re.match(r"(I-\d+|VA-\d+|US\s?\d+|Route\s?\d+|SR\s?\d+)", loc, re.I)
    if m:
        return re.sub(r"\s+", " ", m.group(1).upper().replace("ROUTE ", "Route ")).strip()

    # a real road name, with the suffix as its own word ("East Main Street" must not
    # collapse to "East" the way a case-insensitive "St" inside "East" would do)
    m = re.match(
        r"(?:\d+\s+)?(.+?)\s+"
        r"(Road|Rd|Street|St|Avenue|Ave|Boulevard|Blvd|Highway|Hwy|Pike|Turnpike|Tpke|"
        r"Drive|Dr|Lane|Ln|Parkway|Pkwy|Court|Ct|Place|Pl|Way|Trail)\b", loc, re.I)
    if m:
        name = f"{m.group(1)} {m.group(2)}"
        for full, short in (("Street", "St"), ("Road", "Rd"), ("Avenue", "Ave"),
                            ("Boulevard", "Blvd"), ("Parkway", "Pkwy"),
                            ("Turnpike", "Tpke"), ("Highway", "Hwy"), ("Drive", "Dr"),
                            ("Lane", "Ln"), ("Court", "Ct"), ("Place", "Pl")):
            name = re.sub(rf"\b{full}\b", short, name, flags=re.I)
        name = re.sub(r"\b([WENS])\.\s*", r"\1 ", name)   # "W. Broad" -> "W Broad"
        return re.sub(r"\s+", " ", name).strip()
    return loc.split(",")[0].strip()[:40]


def load(month):
    if not os.path.exists(INCIDENTS):
        sys.exit(f"missing {INCIDENTS} — run build_crash_map.py first")
    rows = json.load(open(INCIDENTS))
    key = f"{month[0]:04d}-{month[1]:02d}"
    return [r for r in rows if (r.get("month") or r.get("date", "")[:7]) == key], rows


def stats(rows):
    fatal_rows = [r for r in rows if r.get("fatal_n", 0) > 0]
    deaths = sum(r.get("fatal_n", 0) for r in rows)
    injuries = sum(r.get("inj_n", 0) for r in rows)
    vru = [(r, vru_kind((r.get("what") or "") or (r.get("location") or ""))) for r in rows]
    vru = [(r, k) for r, k in vru if k]
    vru_deaths = sum(r.get("fatal_n", 0) for r, _ in vru)
    hwy = [r for r in rows if is_highway(r.get("location"))]
    return {
        "incidents": len(rows),
        "deaths": deaths,
        "injuries": injuries,
        "fatal_crashes": len(fatal_rows),
        "by_locality": dict(Counter(r.get("locality", "Unknown") for r in rows).most_common()),
        "by_severity": dict(Counter(r.get("severity", "unknown") for r in rows).most_common()),
        "by_weekday": dict(Counter(weekday_of(r.get("date", "")) for r in rows if weekday_of(r.get("date", "")))),
        "highway_incidents": len(hwy),
        "vru_incidents": len(vru),
        "vru_deaths": vru_deaths,
        "vru_kinds": dict(Counter(k for _, ks in vru for k in ks).most_common()),
        "corridors": dict(Counter(corridor_key(r.get("location")) for r in rows if corridor_key(r.get("location"))).most_common(8)),
        "fatalities": sorted(
            [{"date": r.get("date"), "location": r.get("location"), "locality": r.get("locality"),
              "deaths": r.get("fatal_n", 0), "what": (r.get("what") or "")[:160]} for r in fatal_rows],
            key=lambda x: x["date"] or ""),
        "vru_detail": [{"date": r.get("date"), "location": r.get("location"), "kinds": ks}
                       for r, ks in vru],
    }


def pct(part, whole):
    return f"{(100.0 * part / whole):.0f}%" if whole else "0%"


def render(month, cur, prev, ytd):
    y, m = month
    name = f"{calendar.month_name[m]} {y}"
    lines = [f"# {name} — reported crash incidents", ""]
    lines.append(f"- Incidents logged: **{cur['incidents']}**")
    lines.append(f"- Deaths: **{cur['deaths']}** across {cur['fatal_crashes']} fatal crashes")
    lines.append(f"- Injured (as reported): **{cur['injuries']}**")
    if prev["incidents"]:
        d = cur["incidents"] - prev["incidents"]
        arrow = "up" if d > 0 else ("down" if d < 0 else "flat")
        lines.append(f"- vs prior month: {arrow} {abs(d)} incidents ({prev['incidents']} → {cur['incidents']})")
    lines.append("")
    lines.append("## By jurisdiction")
    for loc, n in cur["by_locality"].items():
        lines.append(f"- {loc}: {n}")
    lines.append("")
    lines.append("## Severity")
    for sev, n in cur["by_severity"].items():
        lines.append(f"- {sev}: {n}")
    lines.append("")
    lines.append("## Vulnerable road users")
    lines.append(f"- {cur['vru_incidents']} of {cur['incidents']} incidents ({pct(cur['vru_incidents'], cur['incidents'])}) "
                 f"involved someone walking, biking, or riding two wheels")
    lines.append(f"- {cur['vru_deaths']} of {cur['deaths']} deaths ({pct(cur['vru_deaths'], cur['deaths'])})")
    if cur["vru_kinds"]:
        lines.append(f"- Breakdown: {', '.join(f'{k} {v}' for k, v in cur['vru_kinds'].items())}")
    lines.append("")
    lines.append("## Highway vs surface street")
    lines.append(f"- Interstate/route-number locations: {cur['highway_incidents']}")
    lines.append(f"- Everything else (named streets, blocks, intersections): {cur['incidents'] - cur['highway_incidents']}")
    lines.append("")
    if cur["corridors"]:
        lines.append("## Most frequent locations/corridors")
        for c, n in cur["corridors"].items():
            lines.append(f"- {c}: {n}")
        lines.append("")
    if cur["by_weekday"]:
        lines.append("## By weekday")
        for d in DAY_ORDER:
            if d in cur["by_weekday"]:
                lines.append(f"- {d}: {cur['by_weekday'][d]}")
        lines.append("")
    lines.append("## Fatalities")
    if cur["fatalities"]:
        for f in cur["fatalities"]:
            lines.append(f"- {f['date']} · {f['location']} ({f['locality']}) — {f['deaths']} dead")
    else:
        lines.append("- none reported")
    lines.append("")
    lines.append("## Running total")
    lines.append(f"- {ytd} incidents logged in the dataset overall")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", help="YYYY-MM (default: previous month)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    month = parse_month(args.month) if args.month else previous_month()
    cur_rows, all_rows = load(month)

    py, pm = (month[0], month[1] - 1) if month[1] > 1 else (month[0] - 1, 12)
    prev_rows, _ = load((py, pm))

    cur = stats(cur_rows)
    prev = stats(prev_rows)
    out = render(month, cur, prev, len(all_rows))

    os.makedirs(OUTDIR, exist_ok=True)
    path = os.path.join(OUTDIR, f"{month[0]:04d}-{month[1]:02d}.md")
    open(path, "w").write(out + "\n")

    if args.json:
        print(json.dumps({"month": f"{month[0]:04d}-{month[1]:02d}", "current": cur,
                          "previous": prev, "total_rows": len(all_rows), "path": path}, indent=1))
    else:
        print(out)
        print(f"\n(saved to {path})")

    if not cur_rows:
        print("\nNOTE: no incidents logged for this month.", file=sys.stderr)


if __name__ == "__main__":
    main()
