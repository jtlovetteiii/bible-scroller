#!/usr/bin/env bash
#
# sync-templates.sh — upload templates/service/*.png to the S3 asset root.
# (bs-tiz.11)
#
#   npm run sync-templates            # sync
#   npm run sync-templates -- --dry-run
#
# OPERATOR STEP, NOT AN AGENT STEP. Run this by hand after you add or edit a
# slide template. It is deliberately NOT part of publishing a deck: the
# backgrounds are a small shared set reused across every deck, so publishing
# stays a single HTML upload (bs-tiz.10) and these ~188MB of PNGs move only when
# they actually change.
#
# Wraps `aws s3 sync` rather than hand-rolling uploads, which buys three things
# that are easy to get wrong alone: idempotency (size+mtime, so re-running is a
# no-op), parallel transfer, and Content-Type detection — a hand-rolled
# PutObject defaults to binary/octet-stream, and the images silently fail to
# render while the deck still looks structurally fine.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/templates/service"

# The key prefix MUST match config.deck_asset_base() in agent/src/email_agent/
# config.py, which composes ${DECK_BASE_URL}/templates/service. If these two
# drift, every background 404s on a deck that otherwise looks correct.
PREFIX="templates/service"

# Templates change rarely but weigh ~188MB, so a day of caching saves the
# minister re-downloading them every time he opens a link. The ceiling is a day
# rather than a year because these filenames are NOT content-hashed: editing
# hymn-1.png reuses the same URL, so any cached client keeps the old image until
# this expires. A day bounds how long a corrected template can look uncorrected.
CACHE_CONTROL="public, max-age=86400"

DRY_RUN=()
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=(--dryrun) ;;
    -h|--help) sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

command -v aws >/dev/null 2>&1 || {
  echo "ERROR: the AWS CLI is not installed or not on PATH." >&2
  echo "       Install it: https://aws.amazon.com/cli/" >&2
  exit 2
}

[ -d "$SRC" ] || { echo "ERROR: no templates directory at $SRC" >&2; exit 2; }

# .env is read by the PYTHON side only (agent/src/email_agent/config.py calls
# load_dotenv). Nothing loads it into this shell, so read the value out
# explicitly rather than assuming it is exported — the same seam that makes
# bs-tiz.10 pass --asset-base to Node as an argument instead of via the
# environment. An exported DECK_BUCKET still wins, matching how the agent host
# supplies config.
#
# The `|| true` is load-bearing: grep exits 1 when the key is absent, and under
# `set -e` that aborts the script silently, before any output. A .env predating
# bs-tiz.10 has no DECK_BUCKET line, so this is the common case, not the edge.
if [ -z "${DECK_BUCKET:-}" ] && [ -f "$ROOT/.env" ]; then
  DECK_BUCKET="$(grep -E '^[[:space:]]*DECK_BUCKET=' "$ROOT/.env" | tail -1 | cut -d= -f2- | tr -d '"'"'"' \r' || true)"
fi
DECK_BUCKET="${DECK_BUCKET:-cbc-wilm-agent-public}"

count=$(find "$SRC" -maxdepth 1 -name '*.png' | wc -l | tr -d ' ')
[ "$count" -gt 0 ] || { echo "ERROR: no *.png files in $SRC" >&2; exit 2; }

echo "Syncing $count PNG(s) -> s3://$DECK_BUCKET/$PREFIX/"
echo "  source: $SRC"
[ ${#DRY_RUN[@]} -gt 0 ] && echo "  (dry run — nothing will be uploaded)"

# --exclude '*' then --include '*.png': there is a .DS_Store in this directory,
# and a bare sync would happily publish it.
#
# No --delete, on purpose. bs-crp grants the agent no DeleteObject, and the
# no-delete design is intentional: an unattended run that goes wrong cannot
# unmake past services. Renaming a template therefore orphans its old object in
# the bucket, which is harmless — it just stops being referenced. "Idempotent"
# here means re-running is a no-op, not that the bucket is pruned to match disk.
aws s3 sync "$SRC" "s3://$DECK_BUCKET/$PREFIX/" \
  --exclude '*' \
  --include '*.png' \
  --cache-control "$CACHE_CONTROL" \
  --no-progress \
  ${DRY_RUN[@]+"${DRY_RUN[@]}"}
# ^ that expansion, not a plain "${DRY_RUN[@]}": macOS ships bash 3.2, where
# `set -u` treats expanding an EMPTY array as an unbound variable and aborts.
# Only the real sync hits it — a dry run has an element in there.

echo
echo "Done. Backgrounds should now resolve under:"
echo "  \${DECK_BASE_URL}/$PREFIX/<name>.png"
echo
echo "Spot-check one:"
echo "  curl -sI \"\${DECK_BASE_URL}/$PREFIX/hymn-1.png\" | head -3"
