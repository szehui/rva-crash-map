# Richmond Area Crash Tracker

An interactive map of vehicle crashes reported by local news outlets in the
Richmond, Virginia metro area (City of Richmond, Henrico, Chesterfield, and
Hanover counties), compiled from seven news sources.

**Live map:** https://szehui.github.io/rva-crash-map/

## Data

- `rva_crashes.geojson` — one point per incident, with date, time, location,
  locality, summary, injuries, fatalities, sources, and article links.
  Ready to import into Google My Maps, QGIS, or kepler.gl.
- `rva_crash_incidents.json` — same records, flat JSON.
- `rva_crash_map.png` — static snapshot.

## Method

Headlines and article text are collected daily from WTVR (CBS 6), NBC12 (WWBT),
WRIC (8News), VPM, Richmonder, Henrico Citizen, and the Richmond Times-Dispatch.
Articles are classified as in-scope traffic crashes, deduplicated across outlets
by date/locality/street, and logged to a Google Sheet. Police-report lookups run
weekly against the Henrico County and City of Richmond public portals.

Caveats:

- This is a **media-derived** dataset. Outlets cover a fraction of actual crashes,
  so counts are a floor, not a census. Property-damage-only crashes are
  systematically undercounted.
- Locations are as reported. Markers are styled by how precisely the location
  could be resolved: solid = street address or intersection, dashed edge = mile
  marker interpolated between highway exits, hollow = the report named no landmark.
- Fields are populated only from article text; nothing is inferred.
- Victim names appear only where outlets published them.

## How this updates

The dataset is refreshed by a scheduled job every night: it scrapes the outlets,
classifies new articles, appends to the sheet, then rebuilds this map and
republishes. Before publishing, every pin is checked against county boundaries
and against other rows (two crashes must not share a coordinate); a pin that
lands in the wrong jurisdiction blocks the publish until it is resolved.

A monthly summary of the previous month is produced on the 1st.

Source skill and pipeline: `~/.hermes/skills/research/rva-crash-tracker`
(`scripts/build_crash_map.py` reads the sheet and rebuilds the map + GeoJSON;
`scripts/publish_map.sh` builds, audits, and publishes).

## Run it yourself

The complete pipeline — collector, map builder, geocoder audit, monthly rollup, and the
agent prompts that drive the classification step — is packaged in [`tracker/`](tracker/)
with setup instructions in [`docs/SETUP.md`](docs/SETUP.md).

- [Setup](docs/SETUP.md) — OAuth, spreadsheet, config, first backfill, scheduling
- [Operations](docs/OPERATIONS.md) — script map, fixing a bad pin, monthly counts
- [Troubleshooting](docs/TROUBLESHOOTING.md) — the failures that actually happen
- [Prompts](prompts/) — stage-2 classification and monthly write-up

```bash
git clone https://github.com/szehui/rva-crash-map.git
cd rva-crash-map/tracker/scripts
python3 rva_crash_tracker.py --mode backfill --days 30   # then classify
bash publish_map.sh --no-push                            # build + audit
```

## Credits

Map tiles © OpenStreetMap contributors. Incident reporting © the outlets listed
per record.
