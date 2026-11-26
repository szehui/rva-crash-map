# Daily classification prompt (stage 2)

Use this after `rva_crash_tracker.py --mode daily` has written
`$state_dir/rva_crash_candidates.json`. It is written for an LLM agent with shell, file,
and Sheets access. If you are doing this by hand, work through the same decisions.

---

Run the RVA Crash Tracker daily update.

1. Run stage 1 (no LLM): `python3 tracker/scripts/rva_crash_tracker.py --mode daily`
   (covers the last 2 days of articles). If it wrote 0 candidate articles, check stderr
   for collector failures but do not retry more than once.

2. Load `$state_dir/rva_crash_candidates.json`. For each article, classify:
   - **keep** — a traffic crash in City of Richmond, Henrico, Chesterfield, or Hanover
   - **skip, not traffic** — homicide, shooting, policy story, live-traffic page, fire
     with no collision, sentencing/anniversary retrospective with no new event
   - **skip, out of locality** — Goochland, New Kent, Middlesex, Louisa, or wire copy
     from another state

   Extract: exact date/time of the crash, location as reported, what happened (1–3
   sentences from article text only, **no inference**), injuries, fatalities. Articles
   about the same crash are one incident; collect all their URLs.

3. Write rows to the sheet (`Date | Time | Location | Locality | What happened |
   Injuries | Fatalities | Sources | Article links`):
   - Read the existing grid first; skip duplicates on `(Date, Location-prefix)`.
   - Insert by date — a late-filed crash belongs before the newest rows, not at the end.
   - Re-read after writing: no blanks, no duplicate keys, J/K police-note rows intact.

4. Do **not** write a row you cannot confirm is a traffic crash, is in locality, or whose
   date no outlet states. Hold it and say so in the report.

5. Rebuild and publish the map:
   `bash tracker/scripts/publish_map.sh`
   If it prints `AUDIT_STATUS: flagged`, fix each flagged row before accepting the
   publish (see `docs/OPERATIONS.md`, "Fixing a pin"): re-resolve with
   `osm_lookup.py addr|xing`, record the anchor in `map_anchors.py`, re-run. A
   wrong-county pin must not go out; if one genuinely cannot be resolved, publish and
   name it in the report.

6. Report, in at most a few lines:
   `Added N rows / Skipped M articles (not traffic or out-of-locality). N tracked
   incidents (+K pre-window cases). Map: built, audit clean|flagged (<details>),
   published <sha>|no changes, live <N> points.`
   Include each collector's status. If nothing new and the map was already current, say
   that in one line rather than padding.

---

## Notes for the operator

- **The zero-source rule.** A collector reporting 0 is unknown, not empty. Re-query the
  WordPress API; if the API is healthy, recover the links from it rather than accepting
  a blank day.
- **Merging outlets.** Prefer the fullest account for the summary text, merge the rest
  into `Sources`/`Article links`. When outlets disagree on a date or weekday, an explicit
  calendar date beats a weekday word.
- **Retrospectives.** A one-year anniversary piece, a sentencing, or a civil suit is not
  a new incident. Skip it unless it reports a crash that is genuinely missing from the
  sheet.
- **Names.** Victim names only if an outlet published them; never infer identity from a
  partial description.
