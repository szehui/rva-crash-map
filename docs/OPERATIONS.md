# Operations

Day-to-day use of the pipeline: what each script does, how to fix a bad pin, and how to
keep the data honest.

## Script map

| script | role | when |
|---|---|---|
| `rva_crash_tracker.py` | stage 1 collector: 7 sources → candidate articles | daily, `--mode daily` (last 2 days) |
| `build_crash_map.py` | sheet → coordinates → map HTML + GeoJSON + incidents JSON | every publish |
| `map_anchors.py` | hand-verified coordinates for specific rows, keyed by row + location hint | read by the build |
| `locality_audit.py` | county-polygon + duplicate-coordinate checks on the built dataset | every publish |
| `publish_map.sh` | build → audit → copy → commit → push → verify live | daily |
| `monthly_summary.py` | previous month's counts, corridors, VRU share, fatals | 1st of the month |
| `osm_lookup.py` | resolve one address or intersection against OSM geometry | when a pin is wrong |
| `osm_download.py` → `overpass_anchors.py` → `mm_reference.py` | rebuild the OSM geometry / junction / mile-marker reference files | rarely, when adding highway anchors |
| `rva_paths.py` | resolves paths + sheet id from config/env | imported by all of the above |

## Manual rebuild

```bash
cd tracker/scripts
python3 build_crash_map.py            # writes output_dir only
bash publish_map.sh --no-push         # build + audit, no git
bash publish_map.sh                   # full publish
```

`publish_map.sh` refuses to publish a stale artefact: it checks that
`rva_crash_incidents.json` was rewritten during this run and that the build produced
non-empty output. If the build crashes, the pipe would otherwise hide it.

## Fixing a pin

The audit is the entry point. Run it and read the two lists:

```
WRONG COUNTY (1):
  R42  8000 block of River Road   stated=Chesterfield County  pin=Henrico County
COLLAPSED COORDINATES (1):
  R62 and R53 share 37.502, -77.543
```

**Wrong county** almost always means the geocoder matched a same-named street in a
different jurisdiction. US Census is the usual culprit: it never fails, it just picks
*some* River Road and answers confidently. Resolve against OSM instead:

```bash
# a block address: street, house number, then bbox (south west north east)
python3 osm_lookup.py addr "River Road" 9000 37.20 -77.60 37.28 -77.45

# an intersection: two street regexes, then the same bbox
python3 osm_lookup.py xing "5th" "Franklin" 37.53 -77.45 37.55 -77.43
```

`addr` returns the actual OSM address node for that house number; `xing` returns the
node where both streets meet (a shared node gives gap 0.0 m). Widen the bbox if it
reports nothing — that is usually the fix, not a different street name.

**Collapsed coordinates** means one row inherited another's point, typically because its
own match silently fell back. Find which row is wrong (compare the reported location to
the shared point), resolve it as above.

Then record the result in `map_anchors.py` so it survives the next rebuild:

```python
ROW_ANCHORS[42] = (37.23936, -77.52928, "surveyed", "OSM address node 9000 River Rd")
ROW_LOCATION_HINTS[42] = "9000 block of River Road"
```

The row number is only a fallback — the build matches the location string first, because
row numbers shift when the daily run inserts a crash out of date order. Keep the hint a
substring of the sheet's Location cell.

Re-run `publish_map.sh` and confirm `WRONG COUNTY (0)` / `COLLAPSED COORDINATES (0)`.

### Confidence tiers

Every pin carries one, and the map renders it:

| tier | meaning | marker |
|---|---|---|
| `surveyed` | exact address node, or two streets sharing a node | solid |
| `interpolated` | mile marker interpolated between OSM junctions | dashed edge |
| `midpoint` | the article named no landmark; corridor midpoint inside the locality | hollow |
| `approximate` | locality centroid only | hollow |

Do not promote a `midpoint` to a precise-looking pin to make the map tidier. An honest
blob beats a confident lie — the three midpoints in this dataset are interstates where
the report named no cross street.

## Monthly summary

```bash
python3 monthly_summary.py                  # previous calendar month
python3 monthly_summary.py --month 2026-10
python3 monthly_summary.py --month 2026-10 --json
```

It prints markdown facts and writes `output_dir/monthly/YYYY-MM.md`. It never
editorialises; the prose comes from the agent prompt.

Counting rules worth knowing before you quote a number:

- **VRU** (vulnerable road user) is matched against the *what happened* text only, not
  the location — otherwise "near Bybee's Road" becomes a bike crash. Kinds counted:
  pedestrian, bicyclist, motorcyclist, scooter, wheelchair, skateboard.
- **Corridors** normalise block numbers, parentheticals, "near/at" tails and road
  suffixes, so `W Broad Street` and `W Broad St` aggregate.
- **Highway vs surface street** matches `I-95`, `VA-288`, `Route 1`, `mile marker`.
- Rows before `WINDOW_START` (2026-08-01) are `pre_window`: plotted, excluded from
  monthly rollups, and reported separately from the tracked count.

## Data integrity habits

These are the failure modes that actually bit this pipeline:

1. **Re-read the sheet after every write.** Google's `values().append` can insert
   mid-grid rather than at the end. Assert no blank rows, no duplicate
   `(date, location-prefix)` keys, correct sort order.
2. **Never write a row you cannot source.** If no outlet states the crash date, the row
   cannot be keyed — hold it and log it in the run notes instead.
3. **Deduplicate across outlets before writing**, not after. Four articles about one
   crash is one row with four links.
4. **One outlet's weekday word is the weakest date signal.** Prefer an explicit calendar
   date; when outlets disagree, trust the one that names the date.
5. **Check the article window against the crash date.** A charging announcement can
   surface a crash from a week earlier; insert by date rather than appending.

## Keeping the package current

`tracker/` is generated from the working skill directory. After editing a packaged
script, regenerate and publish:

```bash
bash scripts/package_to_repo.sh          # copies into tracker/ and pushes
```

Do not hand-edit files in `tracker/` — the next sync overwrites them.
