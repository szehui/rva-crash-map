# Monthly summary prompt

Use this on the 1st of each month, after the previous month's data is complete. The
script produces every number; the prompt only turns them into prose.

---

Write the monthly Richmond-area crash summary.

1. Run `python3 tracker/scripts/monthly_summary.py`. It defaults to the previous calendar
   month, prints the facts as markdown, and saves `output_dir/monthly/YYYY-MM.md`. Read
   the output carefully.

2. If it reports no incidents for the month, say so in one or two lines and stop — do not
   pad.

3. Write the summary (markdown, no tables, under ~350 words):
   - **Headline:** incidents, deaths, injuries, and the change vs the prior month.
   - **Where:** jurisdiction split, plus the most frequent roads/corridors — only those
     the script printed with a count ≥ 2, otherwise note there was no repeat corridor.
   - **Who:** the vulnerable-road-user share — walking, biking, two wheels — as a share
     of incidents *and* of deaths.
   - **Every fatal crash** as a bullet: date, location, number killed.
   - **Two or three sentences of interpretation** tied to street design (corridor
     concentration, VRU share, highway vs surface street split). Mark interpretation as
     interpretation — never present it as data.
   - Link the map, and one line of caveat: media-derived dataset, not an official crash
     census; injuries as reported.

4. Never invent or recompute numbers. Use only what the script printed. If a number looks
   wrong, say so instead of smoothing it over.

---

## Notes for the operator

- **Led with what changed.** A monthly number means little alone; the prior-month delta
  is the signal.
- **Corridors are the actionable finding** for a streets group. If three crashes happened
  on one road, that is a design conversation, not a statistic.
- **VRU share is usually the strongest argument** for a livable-streets audience, and it
  is under-counted more than anything else in media data — so say "at least".
- **Resist ranking jurisdictions by raw count.** Exposure differs enormously between a
  dense city and a suburban county; counts without vehicle-miles or population are not a
  comparison.
