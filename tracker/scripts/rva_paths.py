#!/usr/bin/env python3
"""Central path + credential resolution for the RVA crash tracker.

Every script in this package asks this module where things live, so the pipeline can
run on someone else's machine without editing code. Resolution order, highest first:

  1. environment variable (see below)
  2. key in the JSON config file at $RVA_CONFIG
     (default: ~/.config/rva-crash-tracker/config.json)
  3. built-in default (the original author's layout)

Environment variables
  RVA_STATE_DIR    scratch/state dir (seen-URL state, geocode cache, sheet-id file)
  RVA_TOKEN        Google OAuth token JSON
  RVA_OUTPUT_DIR   where the map artefacts and monthly summaries are written
  RVA_TEMPLATE     Leaflet HTML template (default: map_template.html next to this file)
  RVA_MAP_REPO     git checkout that GitHub Pages serves
  RVA_LIVE_URL     public base URL of the published map (no trailing slash)
  RVA_SHEET_ID     spreadsheet id; otherwise read from $RVA_STATE_DIR/rva_crash_sheet_id

Config file example
  {"state_dir": "/srv/rva/state",
   "token": "/srv/rva/token.json",
   "output_dir": "/srv/rva/output",
   "map_repo": "/srv/rva/map",
   "live_url": "https://example.github.io/rva-crash-map",
   "sheet_id": "1AbC..."}
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.expanduser(
    os.environ.get("RVA_CONFIG", "~/.config/rva-crash-tracker/config.json"))

_cfg = {}
if os.path.exists(CONFIG_PATH):
    try:
        _cfg = json.load(open(CONFIG_PATH))
    except (OSError, ValueError) as exc:  # a broken config must not fail silently
        raise SystemExit(f"rva_paths: cannot read {CONFIG_PATH}: {exc}")


def _get(env, key, default):
    return os.environ.get(env) or _cfg.get(key) or default


STATE_DIR = os.path.expanduser(_get("RVA_STATE_DIR", "state_dir", "~/.hermes/state"))
TOKEN = os.path.expanduser(_get("RVA_TOKEN", "token", "~/.hermes/google_token.json"))
OUTPUT_DIR = os.path.expanduser(
    _get("RVA_OUTPUT_DIR", "output_dir", os.path.join(os.path.dirname(HERE), "output")))
TEMPLATE = os.path.expanduser(
    _get("RVA_TEMPLATE", "template", os.path.join(HERE, "map_template.html")))
MAP_REPO = os.path.expanduser(_get("RVA_MAP_REPO", "map_repo", "~/repos/rva-crash-map"))
LIVE_URL = _get("RVA_LIVE_URL", "live_url", "https://szehui.github.io/rva-crash-map").rstrip("/")
SHEET_ID_FILE = os.path.join(STATE_DIR, "rva_crash_sheet_id")
MONTHLY_DIR = os.path.join(OUTPUT_DIR, "monthly")

# Intermediates that the build writes and reads back.
ANCHORS_JSON = os.path.join(STATE_DIR, "rva_map_row_anchors.json")
GEOCODE_CACHE = os.path.join(STATE_DIR, "rva_map_geocode.json")
OSM_GEOMETRY = os.path.join(STATE_DIR, "osm_geometry.json")
OSM_JUNCTIONS = os.path.join(STATE_DIR, "osm_junctions.json")
MM_POINTS = os.path.join(STATE_DIR, "rva_mm_points.json")
OVERPASS_ANCHORS = os.path.join(STATE_DIR, "rva_overpass_anchors.json")
OSM_LOOKUP_CACHE = os.path.join(STATE_DIR, "osm_lookup_cache.json")
CRASH_STATE = os.path.join(STATE_DIR, "rva_crash_state.json")
CANDIDATES = os.path.join(STATE_DIR, "rva_crash_candidates.json")
INCIDENTS_JSON = os.path.join(OUTPUT_DIR, "rva_crash_incidents.json")
GEOJSON = os.path.join(OUTPUT_DIR, "rva_crashes.geojson")
MAP_HTML = os.path.join(OUTPUT_DIR, "rva_crash_map.html")

# Tracking began with a 30-day backfill at launch; anything older is a pre-window case
# kept for reference and excluded from "tracked" counts and monthly rollups.
WINDOW_START = "2026-08-01"


def sheet_id():
    """Spreadsheet id from $RVA_SHEET_ID, else the state file. Raises a clear error."""
    sid = os.environ.get("RVA_SHEET_ID") or _cfg.get("sheet_id")
    if sid:
        return sid.strip()
    try:
        return open(SHEET_ID_FILE).read().strip()
    except OSError:
        raise SystemExit(
            "no spreadsheet id: set RVA_SHEET_ID, put \"sheet_id\" in "
            f"{CONFIG_PATH}, or write the id to {SHEET_ID_FILE}")


def ensure_dirs():
    for d in (STATE_DIR, OUTPUT_DIR, MONTHLY_DIR):
        os.makedirs(d, exist_ok=True)
