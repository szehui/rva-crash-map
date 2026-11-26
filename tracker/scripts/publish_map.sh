#!/usr/bin/env bash
# Rebuild the crash map from the sheet, audit placements, and publish to GitHub Pages.
#
# Exits 0 when the pipeline ran, even if the audit flags something — the caller reports
# findings rather than dying silently. Exits non-zero only when a build step itself
# failed, or the push could not be completed.
#
# Usage: publish_map.sh [--no-push]
#
# Configuration (env vars, all optional):
#   RVA_SCRIPTS   directory holding these scripts   (default: dirname of this file)
#   RVA_OUTPUT_DIR  build artefacts                (default: ../output)
#   RVA_MAP_REPO    git checkout Pages serves      (default: ~/repos/rva-crash-map)
#   RVA_LIVE_URL    public base URL                (default: https://szehui.github.io/rva-crash-map)
set -uo pipefail

SCRIPTS="${RVA_SCRIPTS:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
OUT="${RVA_OUTPUT_DIR:-$(dirname "$SCRIPTS")/output}"
DEST="${RVA_MAP_REPO:-$HOME/repos/rva-crash-map}"
LIVE="${RVA_LIVE_URL:-https://szehui.github.io/rva-crash-map}"
PUSH=1
[[ "${1:-}" == "--no-push" ]] && PUSH=0

cd "$SCRIPTS" || { echo "FAIL: scripts dir missing"; exit 1; }

echo "== build"
python3 map_anchors.py || { echo "FAIL: map_anchors.py"; exit 1; }
START=$(date +%s)
python3 build_crash_map.py 2>&1 | grep -v FutureWarning | grep -v "warnings.warn" | tail -6
# the pipe masks the exit status, so verify the build actually rewrote its artefacts —
# a stale JSON left over from a previous run would otherwise get published.
[[ -s "$OUT/rva_crash_incidents.json" ]] || { echo "FAIL: no incidents output"; exit 1; }
BUILT_AT=$(stat -c %Y "$OUT/rva_crash_incidents.json")
if (( BUILT_AT < START - 2 )); then
  echo "FAIL: build_crash_map.py did not refresh its output (stale artefact)"
  exit 1
fi

echo "== audit"
AUDIT_OUT=$(python3 locality_audit.py 2>&1)
AUDIT_CODE=$?
echo "$AUDIT_OUT" | tail -14
if [[ $AUDIT_CODE -eq 0 ]]; then
  echo "AUDIT_STATUS: clean"
else
  echo "AUDIT_STATUS: flagged"
fi

if [[ $PUSH -eq 0 ]]; then
  echo "PUBLISH: skipped (--no-push)"
  exit 0
fi

echo "== publish"
[[ -d "$DEST/.git" ]] || { echo "FAIL: $DEST is not a git checkout"; exit 1; }
cp "$OUT/rva_crash_map.html" "$DEST/index.html" || exit 1
cp "$OUT/rva_crashes.geojson" "$OUT/rva_crash_incidents.json" "$DEST/" || exit 1

cd "$DEST" || exit 1
if [[ -z "$(git status --porcelain)" ]]; then
  echo "PUBLISH: no changes since last publish"
else
  git add -A
  git commit -q -m "Crash data refresh $(date +%F)" || { echo "FAIL: commit"; exit 1; }
  if ! git push -q 2>/tmp/rva_push_err.txt; then
    # the GnuTLS -12 failure documented in docs/TROUBLESHOOTING.md; retry over HTTP/1.1
    git config http.version HTTP/1.1
    git config http.postBuffer 52428800
    if ! git push -q 2>>/tmp/rva_push_err.txt; then
      echo "FAIL: git push"
      tail -3 /tmp/rva_push_err.txt
      exit 1
    fi
  fi
  echo "PUBLISH: pushed $(git rev-parse --short HEAD)"
fi

echo "== verify live"
EXPECT=$(python3 -c "import json;print(len(json.load(open('$DEST/rva_crash_incidents.json'))))")
for i in 1 2 3 4 5 6; do
  GOT=$(curl -s -m 20 "$LIVE/rva_crash_incidents.json" | python3 -c "import json,sys;print(len(json.load(sys.stdin)))" 2>/dev/null)
  if [[ "$GOT" == "$EXPECT" ]]; then
    echo "LIVE: $GOT incidents (matches local)"
    exit 0
  fi
  sleep 20
done
echo "LIVE: served $GOT incidents, local build has $EXPECT (Pages may still be building)"
exit 0
