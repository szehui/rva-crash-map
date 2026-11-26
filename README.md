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
- Locations are as reported. Block-level addresses and interstate mile markers
  are plotted approximately (hollow markers on the map).
- Fields are populated only from article text; nothing is inferred.
- Victim names appear only where outlets published them.

## Regenerating

Source skill and pipeline: `~/.hermes/skills/research/rva-crash-tracker`
(`scripts/build_crash_map.py` reads the sheet and rebuilds the map + GeoJSON).

## Credits

Map tiles © OpenStreetMap contributors. Incident reporting © the outlets listed
per record.
