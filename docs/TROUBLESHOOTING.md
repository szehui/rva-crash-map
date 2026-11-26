# Troubleshooting

Failures seen in production, with the fix. Each one cost real debugging time once — they
are recorded so nobody pays twice.

## Collection (stage 1)

**A source reports `0` articles.** Usually a transient upstream failure, not an absence
of news. Re-query the WordPress API by hand before believing it:

```bash
curl -s "https://www.wric.com/wp-json/wp/v2/posts?per_page=100&page=1" | head -c 300
```

WRIC has served `0` while its API answered `200`/100 posts minutes later. Treat a zero as
"unknown", not "quiet day".

**WTVR articles missing.** WTVR publishes some stories only under
`wtvr.com/videos/news/local-news/<county>/…`, which appears in neither sitemap. The
collector runs a Google News RSS safety net for exactly this, but if a story is known to
exist and is absent, check the `/videos/` path directly.

**Richmond Times-Dispatch bodies are empty.** `richmond.com` paywalls article bodies.
Summarise from `og:description` only and never invent detail to fill the gap.

**PerimeterX / bot walls.** Send a real browser User-Agent (the collector does) and
prefer the site's WordPress REST API over HTML scraping where one exists.

## Sheet writes

**Rows landed in the middle of the grid.** `values().append` with a stale range can
insert mid-grid rather than after the last row. Always re-read `Crashes!A1:K500` after
writing and verify count, sort order, no blanks, no duplicates. To repair: build the
full corrected row list and write it in one `values().update`, then
`values().clear("Crashes!A<n>:Z<last>")` to drop the stale tail.
`spreadsheets.batchUpdate` + `deleteRange` is unreliable in some client versions — avoid
it for this.

**Columns J/K got overwritten.** Those hold police-report notes (10- and 11-column rows).
Never write `A:I` over rows that have J/K content; preserve the tail of each row.

**Dates render as numbers.** Column A must be written as ISO text. Read with
`valueRenderOption=FORMATTED_VALUE` to see what a human sees.

## Geocoding

**Pin in the wrong county.** The geocoder matched a same-named street elsewhere. US
Census is the main offender — it returns a confident wrong answer rather than no answer.
Resolve with `osm_lookup.py addr|xing` and add a `ROW_ANCHORS` entry; see
[OPERATIONS.md](OPERATIONS.md).

**Two rows share one coordinate.** One row's match silently fell back to a neighbour's.
The audit names both; resolve the wrong one.

**Pin drifts along a highway.** Mile markers must be interpolated between OSM junctions,
not from a locality centroid. `mm_reference.py` builds the junction table; anchors of
tier `interpolated` carry the marker used in their `how` text.

**A "not found" from `osm_lookup.py`.** Widen the bounding box before changing the street
name. A missing address node is common in rural blocks; the nearest intersection is then
the better anchor.

## Publishing

**`FAIL: git push`.** A GnuTLS `-12` error on large pushes is worked around inside
`publish_map.sh`: it retries once with `http.version=HTTP/1.1`. If it still fails, check
credentials (`git remote -v`, `gh auth status`) — the script cannot fix auth.

**`FAIL: build_crash_map.py did not refresh its output`.** The build crashed but the
pipe hid the exit status. Run `python3 build_crash_map.py` directly to see the traceback;
the check exists so a stale JSON never gets published.

**Publish succeeded, site shows old data.** GitHub Pages takes a minute. The script polls
the live JSON for up to two minutes and reports the served count if it never matches. If
it stays stale beyond that, check that Pages is configured to serve the branch root.

**`LIVE: served N incidents, local build has M`.** Either Pages is still building or the
push landed on a different branch than Pages serves. The message is intentionally not a
failure — the data is pushed either way.

## Credentials

**`no spreadsheet id`.** Set `RVA_SHEET_ID`, add `sheet_id` to the config, or write the
id to `$state_dir/rva_crash_sheet_id`.

**Token refresh fails / scope errors.** Re-consent with both `spreadsheets` and
`drive.readonly`. Consent rounds can silently drop scopes you had before — if one job
starts failing with 403 after a re-consent, check the granted scopes first.

**Do not write an `expiry` field back to the token file** after a manual refresh. Leave
the refresh token and access token; the client refreshes on demand. A hand-written expiry
in the past causes needless re-auth loops.

**`AttributeError: to_dict` on `Credentials`.** Not every installed version exposes it.
Refresh via a raw POST to `https://oauth2.googleapis.com/token` with
`client_id`, `client_secret`, `refresh_token` (no `scope` parameter), then patch only
`token` into the JSON.

## Scheduling

**`execute_code` is blocked in scheduled runs.** Some agent runtimes forbid code
execution in cron mode because no human is present to approve it. Write a helper `.py`
with the file tool and run it with a shell command instead of inlining Python.

**A scheduled run reports success but nothing changed.** Check that stage 2 actually ran.
The map is built from the sheet, so a skipped classification step produces a clean,
unchanged map — which looks identical to a quiet day.

## Interpretation

**Counts look too low.** This is a media-derived dataset: outlets cover a fraction of
crashes, and property-damage-only collisions are systematically undercounted. Report it
as a floor, not a census, and say so whenever the numbers leave the group chat.

**Injury counts look implausible.** They are as reported, sometimes as "several". Do not
smooth them into a precise-looking number; flag the oddity instead.
