# Running the crash tracker yourself

This directory is the complete pipeline behind the [Richmond area crash map](../).
It runs in two stages:

```
collect (Python, no LLM)          classify + log (agent)            build + publish (Python)
─────────────────────────         ─────────────────────            ──────────────────────────
7 news sources ─► candidates ─►  dedupe, decide in-scope,  ─►  sheet ─► geocode ─► audit ─►
                                  write one row per incident              Leaflet map ─► Pages
```

Why two stages: deciding whether "man struck by car in Henrico" is a traffic crash,
which of four outlets' accounts to merge, and what the article actually says is a
judgement call. Everything else — fetching, parsing, geocoding, auditing, publishing —
is deterministic code. The split keeps the expensive part small and the fragile part
testable.

You do not need Hermes to use this. Any agent or human that can run shell commands and
edit a Google Sheet can perform stage 2; the prompts used are in
[`../prompts/`](../prompts/).

---

## 1. Prerequisites

- **Python 3.9+** with `google-auth` and `google-api-python-client`
  ```bash
  python3 -m pip install --user google-auth google-api-python-client
  ```
- **A Google account** that can create a spreadsheet and an OAuth client.
- **A GitHub repository** for the published map (public if you are on a free plan —
  GitHub Pages on a free account requires a public repo).
- **Something to schedule the runs**: cron, systemd timers, or an agent scheduler. The
  daily run needs an LLM in the loop; see step 6.

No API keys are needed for news collection — it reads public feeds and WordPress
endpoints. Geocoding uses OSM/Overpass and the US Census geocoder, both keyless.

## 2. Clone and configure

```bash
git clone https://github.com/szehui/rva-crash-map.git
cd rva-crash-map/tracker
cp config.example.json ~/.config/rva-crash-tracker/config.json
```

Edit the config. Every path is optional and falls back to a sensible default
(`~/.hermes/state`, `~/.hermes/google_token.json`, `./output`, `~/repos/rva-crash-map`):

| key | meaning |
|---|---|
| `state_dir` | scratch dir: seen-URL state, geocode cache, sheet-id file |
| `token` | Google OAuth token JSON (step 3) |
| `output_dir` | where the map artefacts and monthly summaries are written |
| `map_repo` | git checkout whose root GitHub Pages serves |
| `live_url` | public base URL, used to verify a publish |
| `sheet_id` | the spreadsheet id from step 4 |

Environment variables override the file, which is handy for one-off runs and CI:
`RVA_STATE_DIR`, `RVA_TOKEN`, `RVA_OUTPUT_DIR`, `RVA_MAP_REPO`, `RVA_LIVE_URL`,
`RVA_SHEET_ID`, `RVA_CONFIG`.

## 3. Google OAuth

1. In [Google Cloud Console](https://console.cloud.google.com/), create (or pick) a
   project and **enable the Google Sheets API** and **Google Drive API**.
2. Configure the OAuth consent screen (External is fine; add yourself as a test user).
3. Create credentials → **OAuth client ID** → type **Desktop app**.
4. Authorise once with the scopes below and save the resulting credentials JSON to the
   `token` path in your config:

   ```
   https://www.googleapis.com/auth/spreadsheets
   https://www.googleapis.com/auth/drive.readonly
   ```

The scripts read and rewrite this file to refresh the access token. They never write an
`expiry` field — an expired-looking `expiry` with a valid refresh token causes more
trouble than it solves, and the Google client refreshes on demand.

`drive.readonly` is only needed if you share the sheet by link rather than by id; it is
harmless to include.

## 4. Create the spreadsheet

Create a sheet named **Crashes** with this header row in row 1, columns A–I:

```
Date | Time | Location | Locality | What happened | Injuries | Fatalities | Sources | Article links
```

- Dates are ISO (`2026-11-24`). Column A must stay ISO-sortable.
- One row per **incident**, not per article; multiple outlets go in `Sources` and
  `Article links` (semicolon-separated).
- Columns J and K are deliberately left free — they hold police-report lookup notes in
  the original deployment, and the tooling preserves them.

Put the spreadsheet id (the long string in its URL) in `sheet_id`, or write it to
`$state_dir/rva_crash_sheet_id`. Nothing else in the repo needs to know it.

## 5. First run: backfill

```bash
cd tracker/scripts
python3 rva_crash_tracker.py --mode backfill --days 30
```

This writes `$state_dir/rva_crash_candidates.json` and prints a per-source line:
`wtvr N, nbc12 N, wric N, vpm N, richmonder N, henricocitizen N, rtd N`. A `0` from one
source is usually a transient upstream failure, not "no news" — see
[TROUBLESHOOTING.md](TROUBLESHOOTING.md).

Then perform the classification (stage 2) with the prompt in
[`../prompts/daily.md`](../prompts/daily.md), which appends the rows to the sheet.

## 6. Build and publish the map

```bash
bash tracker/scripts/publish_map.sh --no-push   # build + audit, write into output_dir
bash tracker/scripts/publish_map.sh             # also copy into map_repo, commit, push, verify live
```

The build reads the sheet, assigns coordinates, writes `index.html`,
`rva_crashes.geojson`, and `rva_crash_incidents.json`, then **audits**:

- every pin is tested against the county polygon for its stated locality
- no two incidents may share a coordinate (that means one silently inherited its
  neighbour's address)

`AUDIT_STATUS: clean` means both checks passed. `flagged` prints the offending rows; the
script still exits 0 so the caller can report them, but a wrong-county pin should be
fixed before you accept the publish. [OPERATIONS.md](OPERATIONS.md) explains how.

On first use with your own data you will have **no anchors** — that is expected. New
locations are resolved automatically: verified anchors → geocode cache → Census →
Photon. Anchors are worth adding for any location the audit flags.

## 7. Schedule

Daily, 21:00 local:

1. `python3 tracker/scripts/rva_crash_tracker.py --mode daily`
2. stage 2 classification with [`../prompts/daily.md`](../prompts/daily.md)
3. `bash tracker/scripts/publish_map.sh`

Monthly, on the 1st at 09:00 local:

1. `python3 tracker/scripts/monthly_summary.py` (defaults to the previous month)
2. prose write-up with [`../prompts/monthly.md`](../prompts/monthly.md)

With Hermes, both are ordinary cron jobs whose prompt is the file's contents. With plain
cron, wrap stage 1+3 in a shell script and run an agent CLI for stage 2; the important
part is that stage 2 is *not* skipped — the map only knows what someone decided was a
crash.

## 8. Verify

```bash
python3 tracker/scripts/monthly_summary.py --month 2026-10   # should print a real rollup
curl -s "$LIVE_URL/rva_crash_incidents.json" | python3 -m json.tool | head
```

`publish_map.sh` already polls the live URL after pushing and compares the served
incident count to the local build, so "pushed" and "live" are not confused with each
other.
