#!/usr/bin/env bash
#
# optimize-templates.sh — downscale templates/service-masters/*.png into the
# serving copies in templates/service/. (bs-9x5)
#
#   npm run optimize-templates              # rebuild templates/service/
#   npm run optimize-templates -- --dry-run # report what would change
#   npm run optimize-templates -- --force   # re-encode even if up to date
#
# WHY THIS EXISTS. The masters are stored at ~4496x2475 but the slide box is
# 1456x816, and templates/service-slides-template.html exports with html2canvas
# at scale:1 -> toBlob('image/jpeg', 0.95). The browser therefore ALREADY
# downsamples to 1456x816 and JPEG-encodes on the way to ProPresenter: the extra
# resolution is discarded at export, not preserved. It is paid for only once —
# by the minister opening the preview link on his phone in the parking lot.
#
# THE TWO DIRECTORIES.
#   templates/service-masters/  the high-res originals. EDIT THESE. Never
#                               generated, never overwritten by this script.
#   templates/service/          derived, committed, and what everything else
#                               reads: build-deck.js validates `background`
#                               against this directory and sync-templates.sh
#                               uploads it to S3.
#
# Derived output is committed rather than gitignored on purpose — build-deck.js
# fails validation if a referenced background is missing from templates/service/,
# so a clean checkout must have them without running an image pipeline first.
#
# THE OPERATOR LOOP: edit a master -> npm run optimize-templates -> npm test ->
# npm run sync-templates. Adding a template is the same loop; drop the new PNG in
# templates/service-masters/ and it is picked up automatically.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/templates/service-masters"
DST="$ROOT/templates/service"

# Target width for the derived copies.
#
# 2x the 1456px slide box. The export path only ever needs 1456, but a PREVIEW
# viewed full-screen on a large monitor CSS-scales the slide up, and a 1456px
# source would look soft there. 2912 is immune to that.
#
# This is the single knob worth tuning. Measured on welcome-text-fall.png (18MB
# master), so the trade is not a guess:
#
#     width   PNG     JPEG q90
#     2912    8.7MB   1.8MB
#     1456    2.5MB   656KB
#
# PNG is lossless, and these are photographs, so the format — not the width —
# dominates. Dropping to 1456 here is a ~3.5x further win and costs nothing at
# export; it costs only preview sharpness on a big monitor. See bs-9x5.
MAX_WIDTH="${TEMPLATE_MAX_WIDTH:-2912}"

# Files already at or under MAX_WIDTH are COPIED, not resampled. hymn-1.png is
# 1300x720 / 336KB — it is the model the others should follow, and running it
# through a resample would upscale it into a bigger, blurrier file.

DRY_RUN=0
FORCE=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --force) FORCE=1 ;;
    -h|--help) sed -n '2,30p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

# sips ships with macOS, so there is no install step and no new dependency for an
# operator. If this ever needs to run on CI/Linux, that is the line to replace.
command -v sips >/dev/null 2>&1 || {
  echo "ERROR: sips not found. This script requires macOS." >&2
  exit 2
}

[ -d "$SRC" ] || { echo "ERROR: no masters directory at $SRC" >&2; exit 2; }
mkdir -p "$DST"

count=$(find "$SRC" -maxdepth 1 -name '*.png' | wc -l | tr -d ' ')
[ "$count" -gt 0 ] || { echo "ERROR: no *.png files in $SRC" >&2; exit 2; }

echo "Optimizing $count master(s) -> $DST (max width ${MAX_WIDTH}px)"
[ "$DRY_RUN" -eq 1 ] && echo "  (dry run — nothing will be written)"
echo

png_width() { sips -g pixelWidth "$1" 2>/dev/null | awk '/pixelWidth/{print $2}'; }
size_of()   { stat -f%z "$1" 2>/dev/null || echo 0; }
human()     { awk -v b="$1" 'BEGIN{ if(b>=1048576) printf "%.1fMB", b/1048576; else printf "%.0fKB", b/1024 }'; }

total_in=0
total_out=0

for master in "$SRC"/*.png; do
  name="$(basename "$master")"
  out="$DST/$name"
  w="$(png_width "$master")"
  in_bytes="$(size_of "$master")"
  total_in=$((total_in + in_bytes))

  if [ -z "$w" ]; then
    echo "WARNING: could not read dimensions of $name — skipping" >&2
    continue
  fi

  # Idempotency: skip when the derived copy is newer than its master. Cheap and
  # good enough — the masters are hand-edited, so mtime moves when they change.
  if [ "$FORCE" -eq 0 ] && [ -f "$out" ] && [ "$out" -nt "$master" ]; then
    out_bytes="$(size_of "$out")"
    total_out=$((total_out + out_bytes))
    printf "  %-32s up to date       %8s\n" "$name" "$(human "$out_bytes")"
    continue
  fi

  if [ "$DRY_RUN" -eq 1 ]; then
    if [ "$w" -gt "$MAX_WIDTH" ]; then
      printf "  %-32s would resample   %5spx -> %spx\n" "$name" "$w" "$MAX_WIDTH"
    else
      printf "  %-32s would copy       %5spx (already <= max)\n" "$name" "$w"
    fi
    continue
  fi

  if [ "$w" -gt "$MAX_WIDTH" ]; then
    # --resampleWidth preserves aspect ratio; height follows.
    sips --resampleWidth "$MAX_WIDTH" "$master" --out "$out" >/dev/null
    verb="resampled"
  else
    cp "$master" "$out"
    verb="copied"
  fi

  out_bytes="$(size_of "$out")"
  total_out=$((total_out + out_bytes))
  printf "  %-32s %-9s %8s -> %8s\n" "$name" "$verb" "$(human "$in_bytes")" "$(human "$out_bytes")"
done

[ "$DRY_RUN" -eq 1 ] && exit 0

echo
echo "  masters: $(human "$total_in")"
echo "  derived: $(human "$total_out")"
[ "$total_in" -gt 0 ] && awk -v i="$total_in" -v o="$total_out" \
  'BEGIN{ printf "  saved:   %.1fMB (%.1fx smaller)\n", (i-o)/1048576, i/o }'
echo
echo "Next: npm test && npm run sync-templates"
