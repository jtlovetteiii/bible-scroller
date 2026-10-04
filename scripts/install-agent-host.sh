#!/usr/bin/env bash
#
# install-agent-host.sh — wire the email agent (bs-tiz) onto a Debian/Ubuntu box.
#
#   sudo ./scripts/install-agent-host.sh            # install / converge
#   sudo ./scripts/install-agent-host.sh --check    # report drift, change nothing
#
# The operator's whole job is three steps:
#   1. git clone this repo somewhere permanent
#   2. create the `cbc-wilm-agent` AWS profile by hand (aws configure --profile ...)
#   3. run this script
#
# IDEMPOTENCY IS THE POINT. thomas re-runs this whenever anything changes, so
# every step below is check-then-act and a converged box must produce a series of
# no-ops and exit 0: no second timer, no appended env line, no clobbered token.
# Where a step writes a file it renders the desired content to a temp file, `cmp`s
# it against what is on disk, and only installs (and only then reloads systemd) if
# they differ. Where a step mutates the system (apt, uv) it first asks whether the
# post-state already holds.
#
# THIS SCRIPT IS UNVERIFIED ON THE TARGET until it runs on the box: it was written
# on darwin, the target is Debian + systemd. It is therefore written to fail loudly
# and early rather than half-succeed, and to be recoverable by re-running.
#
# See agent/README.md for the host story and specs/email-agent.md §4.6.

set -euo pipefail

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

readonly SERVICE_NAME="cbc-email-agent"
readonly TIMER_UNIT="${SERVICE_NAME}.timer"
readonly SERVICE_UNIT="${SERVICE_NAME}.service"
readonly HEALTH_UNIT="${SERVICE_NAME}-healthcheck.service"
readonly UNIT_DIR="/etc/systemd/system"

readonly NODE_MAJOR_MIN=18
readonly NODE_MAJOR_INSTALL=20      # NodeSource LTS line to install when node is missing/old
readonly PY_MIN="3.11"              # must match agent/pyproject.toml requires-python
readonly AWS_PROFILE_NAME="cbc-wilm-agent"
readonly EXAMPLE_DECK="examples/2026-06-28.deck.json"

REPO=""
SERVICE_USER=""
SERVICE_HOME=""
CHECK_ONLY=0
CHANGES=0            # count of things a --check run would change
TMPDIR_SELF=""

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

if [ -t 1 ]; then
  C_RED=$'\033[31m'; C_GRN=$'\033[32m'; C_YEL=$'\033[33m'; C_DIM=$'\033[2m'; C_OFF=$'\033[0m'
else
  C_RED=""; C_GRN=""; C_YEL=""; C_DIM=""; C_OFF=""
fi

step() { printf '\n%s==>%s %s\n' "$C_DIM" "$C_OFF" "$1"; }
ok()   { printf '  %sok%s    %s\n' "$C_GRN" "$C_OFF" "$1"; }
act()  { printf '  %sdo%s    %s\n' "$C_YEL" "$C_OFF" "$1"; }
skip() { printf '  %s--%s    %s\n' "$C_DIM" "$C_OFF" "$1"; }
warn() { printf '  %swarn%s  %s\n' "$C_YEL" "$C_OFF" "$1" >&2; }

die() {
  printf '\n%sFATAL%s %s\n' "$C_RED" "$C_OFF" "$1" >&2
  shift || true
  for line in "$@"; do printf '      %s\n' "$line" >&2; done
  exit 1
}

# In --check mode, record that something is not converged instead of doing it.
# Returns 0 when the caller should proceed with the change, 1 when it must not.
would() {
  CHANGES=$((CHANGES + 1))
  if [ "$CHECK_ONLY" -eq 1 ]; then
    printf '  %sWOULD%s %s\n' "$C_YEL" "$C_OFF" "$1"
    return 1
  fi
  act "$1"
  return 0
}

# `return 0` is load-bearing, not defensive habit. Under `set -e` the EXIT trap's
# final status REPLACES the script's own exit code, and `[ -n "" ]` is a failure
# when TMPDIR_SELF was never created — which silently turned `--help` into exit 1.
# It would do the same to any successful path where the rm failed, and `--check`
# promises exit 0 on a converged host. Never let cleanup decide the exit code.
cleanup() { [ -n "$TMPDIR_SELF" ] && rm -rf "$TMPDIR_SELF"; return 0; }
trap cleanup EXIT

# Run a command as the service user with a sane HOME (sudo -u alone keeps root's).
as_user() {
  runuser -u "$SERVICE_USER" -- env HOME="$SERVICE_HOME" PATH="/usr/local/bin:/usr/bin:/bin:${SERVICE_HOME}/.local/bin" "$@"
}

usage() {
  cat <<'EOF'
install-agent-host.sh — install and wire the email agent on a Debian/Ubuntu host.

Usage:
  sudo ./scripts/install-agent-host.sh [options]

Options:
  --check, --dry-run   Report what is not converged. Makes NO changes. Exits 0
                       when the host is already fully converged, 1 otherwise.
  --user USER          Unix user the service runs as. Defaults to the owner of
                       the repo checkout (or $SUDO_USER).
  -h, --help           This text.

Re-running without --check is safe and expected: it is how you apply a config
change, and on an unchanged host it is a series of no-ops.
EOF
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

while [ $# -gt 0 ]; do
  case "$1" in
    --check|--dry-run) CHECK_ONLY=1 ;;
    --user) SERVICE_USER="${2:-}"; shift || die "--user needs a value" ;;
    --user=*) SERVICE_USER="${1#*=}" ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "unknown argument: $1" ;;
  esac
  shift
done

# ---------------------------------------------------------------------------
# 0. Preflight — refuse early rather than half-install
# ---------------------------------------------------------------------------

step "Preflight"

[ "$(uname -s)" = "Linux" ] || die \
  "this installer targets Debian/Ubuntu Linux; this host is $(uname -s)." \
  "The agent itself runs anywhere, but the systemd wiring below does not."

command -v systemctl >/dev/null 2>&1 || die \
  "systemctl not found — this installer wires a systemd service + timer."

command -v apt-get >/dev/null 2>&1 || die \
  "apt-get not found — this installer targets Debian/Ubuntu."

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -f "$REPO/agent/pyproject.toml" ] || die \
  "cannot locate the repo root (looked at: $REPO)" \
  "Run this script from inside the checkout: sudo ./scripts/install-agent-host.sh"
ok "repo root: $REPO"

if [ "$CHECK_ONLY" -eq 0 ] && [ "$(id -u)" -ne 0 ]; then
  die "must run as root (it installs packages and writes ${UNIT_DIR})." \
      "Try: sudo $0 $*"
fi

# Service user: explicit flag > the sudo caller > the owner of the checkout.
if [ -z "$SERVICE_USER" ]; then
  SERVICE_USER="${SUDO_USER:-}"
  [ -z "$SERVICE_USER" ] && SERVICE_USER="$(stat -c '%U' "$REPO")"
fi
id "$SERVICE_USER" >/dev/null 2>&1 || die \
  "service user '$SERVICE_USER' does not exist. Pass --user with a real account."
[ "$SERVICE_USER" != "root" ] || die \
  "refusing to run the agent as root. Pass --user with an unprivileged account." \
  "The AWS profile, the Gmail token and the Claude token all live in that user's home."

SERVICE_HOME="$(getent passwd "$SERVICE_USER" | cut -d: -f6)"
[ -n "$SERVICE_HOME" ] && [ -d "$SERVICE_HOME" ] || die \
  "service user '$SERVICE_USER' has no usable home directory (got: '${SERVICE_HOME}')." \
  "boto3 resolves ~/.aws/credentials out of it; the agent cannot work without one."
ok "service user: $SERVICE_USER (home: $SERVICE_HOME)"

TMPDIR_SELF="$(mktemp -d)"

# ---------------------------------------------------------------------------
# 1. Node >= 18 — a HARD RUNTIME DEP that is easy to miss
#
# publish.py shells out to `node scripts/build-deck.js`. A Python-only box
# installs cleanly, passes every Python check, and then fails at publish time —
# after the deck is built, which is the worst possible moment. So: install it,
# verify it, and actually exercise build-deck.js once (step 4).
#
# Idempotency: if `node -v` already reports >= 18 the whole step is skipped —
# no apt repo is touched, no package is installed. When it does run, the
# NodeSource list/keyring are content-compared before writing, and `apt-get
# install` is itself idempotent for an already-current package.
# ---------------------------------------------------------------------------

node_major() {
  command -v node >/dev/null 2>&1 || return 1
  local v; v="$(node -v 2>/dev/null)" || return 1
  v="${v#v}"; printf '%s' "${v%%.*}"
}

install_nodesource() {
  local keyring="/usr/share/keyrings/nodesource.gpg"
  local listfile="/etc/apt/sources.list.d/nodesource.list"
  local want="deb [signed-by=${keyring}] https://deb.nodesource.com/node_${NODE_MAJOR_INSTALL}.x nodistro main"

  command -v curl >/dev/null 2>&1 || apt-get install -y curl ca-certificates gnupg
  command -v gpg  >/dev/null 2>&1 || apt-get install -y gnupg

  if [ ! -s "$keyring" ]; then
    act "fetching the NodeSource signing key"
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
      | gpg --dearmor -o "$keyring"
    chmod 0644 "$keyring"
  else
    skip "NodeSource signing key already present"
  fi

  # Content-compare, do not append: appending is how you end up with the repo
  # declared three times and apt warning on every run forever.
  printf '%s\n' "$want" > "$TMPDIR_SELF/nodesource.list"
  if ! cmp -s "$TMPDIR_SELF/nodesource.list" "$listfile" 2>/dev/null; then
    act "writing $listfile"
    install -m 0644 "$TMPDIR_SELF/nodesource.list" "$listfile"
  else
    skip "$listfile already correct"
  fi

  apt-get update -qq
  apt-get install -y nodejs
}

step "Node >= ${NODE_MAJOR_MIN} (required at runtime by publish.py -> scripts/build-deck.js)"
NODE_MAJOR="$(node_major || true)"
if [ -n "${NODE_MAJOR:-}" ] && [ "$NODE_MAJOR" -ge "$NODE_MAJOR_MIN" ] 2>/dev/null; then
  ok "node $(node -v) already satisfies >= ${NODE_MAJOR_MIN}"
else
  if would "install Node ${NODE_MAJOR_INSTALL}.x from NodeSource (found: ${NODE_MAJOR:-none})"; then
    install_nodesource
    NODE_MAJOR="$(node_major || true)"
    [ -n "${NODE_MAJOR:-}" ] && [ "$NODE_MAJOR" -ge "$NODE_MAJOR_MIN" ] 2>/dev/null || die \
      "node is still missing or too old after installing (got: ${NODE_MAJOR:-none})."
    ok "node $(node -v) installed"
  fi
fi

# ---------------------------------------------------------------------------
# 2. uv — installed system-wide so root and the service user see the same binary
#
# Idempotency: skipped outright if `uv` is already on PATH. The upstream
# installer is itself re-runnable, but we don't even call it when uv exists —
# re-running must not silently upgrade a working toolchain under him.
# ---------------------------------------------------------------------------

step "uv"
UV_BIN=""
for candidate in /usr/local/bin/uv "${SERVICE_HOME}/.local/bin/uv" "$(command -v uv 2>/dev/null || true)"; do
  [ -n "$candidate" ] && [ -x "$candidate" ] && { UV_BIN="$candidate"; break; }
done

if [ -n "$UV_BIN" ]; then
  ok "uv already present: $UV_BIN ($("$UV_BIN" --version 2>/dev/null || echo '?'))"
else
  if would "install uv to /usr/local/bin"; then
    command -v curl >/dev/null 2>&1 || apt-get install -y curl ca-certificates
    # UV_INSTALL_DIR + NO_MODIFY_PATH: a fixed, predictable path and no shell-rc
    # edits — an installer that appends to .bashrc on every run is the exact
    # anti-pattern this script exists to avoid.
    curl -fsSL https://astral.sh/uv/install.sh \
      | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
    UV_BIN=/usr/local/bin/uv
    [ -x "$UV_BIN" ] || die "uv install reported success but $UV_BIN is not executable."
    ok "uv installed: $("$UV_BIN" --version)"
  fi
fi

# ---------------------------------------------------------------------------
# 3. Python >= 3.11 and the venv
#
# We do NOT apt-install a python: Ubuntu 22.04 ships 3.10, which is below
# agent/pyproject.toml's requires-python, and bolting on a PPA to fix that is
# more moving parts than the job needs. uv can fetch its own interpreter, so we
# let it — `uv python install` and `uv sync` are both idempotent by design.
#
# Everything here runs AS THE SERVICE USER so the venv and uv's interpreter
# cache land in the home the service will actually run out of, owned correctly.
# A root-owned .venv is a classic "worked during install, EACCES as a service".
# ---------------------------------------------------------------------------

py_ok() {
  command -v python3 >/dev/null 2>&1 || return 1
  python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null
}

step "Python >= ${PY_MIN} + agent dependencies"
if py_ok; then
  ok "system python3 $(python3 -V 2>&1 | cut -d' ' -f2) satisfies >= ${PY_MIN}"
else
  if would "have uv fetch a managed Python ${PY_MIN} (system python3 is missing or < ${PY_MIN})"; then
    as_user "$UV_BIN" python install "$PY_MIN"
  fi
fi

VENV="$REPO/agent/.venv"
if [ "$CHECK_ONLY" -eq 1 ] && [ ! -x "$VENV/bin/email-agent-healthcheck" ]; then
  CHANGES=$((CHANGES + 1))
  printf '  %sWOULD%s %s\n' "$C_YEL" "$C_OFF" "run 'uv sync' in $REPO/agent"
else
  # `uv sync` IS the idempotency: it reconciles .venv to uv.lock and is a no-op
  # when they already agree. We always run it rather than guessing whether a
  # dependency changed — guessing is how a re-run after `git pull` silently keeps
  # running the old code.
  act "uv sync (reconciles .venv to uv.lock; no-op when already in sync)"
  ( cd "$REPO/agent" && as_user "$UV_BIN" sync --frozen ) || die \
    "uv sync failed in $REPO/agent — the agent has no usable environment."
  ok "agent venv synced: $VENV"
fi

HEARTBEAT_BIN="$VENV/bin/email-agent-heartbeat"
HEALTH_BIN="$VENV/bin/email-agent-healthcheck"
if [ "$CHECK_ONLY" -eq 0 ]; then
  for b in "$HEARTBEAT_BIN" "$HEALTH_BIN"; do
    [ -x "$b" ] || die \
      "expected console script missing: $b" \
      "agent/pyproject.toml should declare it under [project.scripts]." \
      "If you just added it, re-run — uv sync must rebuild the package."
  done
  ok "entry points resolve: email-agent-heartbeat, email-agent-healthcheck"
fi

# ---------------------------------------------------------------------------
# 4. Exercise build-deck.js once — prove the Node dep for real
#
# Read-only: renders a real deck to a temp file and throws it away. This is the
# check that would have caught a Python-only box before publish time.
# ---------------------------------------------------------------------------

step "Exercise scripts/build-deck.js (proves the Node runtime dep end to end)"
if [ ! -f "$REPO/$EXAMPLE_DECK" ]; then
  warn "no $EXAMPLE_DECK in the checkout; skipping the render probe"
elif ! command -v node >/dev/null 2>&1; then
  skip "node not installed yet (--check); skipping the render probe"
else
  if ( cd "$REPO" && node scripts/build-deck.js "$EXAMPLE_DECK" \
        --out "$TMPDIR_SELF/probe.html" --asset-base /templates/service --quiet ) \
     && [ -s "$TMPDIR_SELF/probe.html" ]; then
    ok "build-deck.js rendered $EXAMPLE_DECK ($(wc -c < "$TMPDIR_SELF/probe.html") bytes)"
  else
    die "node scripts/build-deck.js FAILED on $EXAMPLE_DECK." \
        "The agent would build a deck and then fail at publish time. Fix this first."
  fi
fi

# ---------------------------------------------------------------------------
# 5. Secrets and credentials — checked, never invented, never clobbered
#
# The script does not write secrets. It asserts they are in place and tells the
# operator exactly what to do when they are not. Rationale: a token typed into a
# prompt cannot be re-run unattended, and a token generated by the script would
# clobber a working one on the next run — which the acceptance criteria forbid.
# ---------------------------------------------------------------------------

ENV_FILE="$REPO/.env"

env_value() {
  # Last assignment wins, matching python-dotenv. Strips optional quotes.
  local key="$1" v
  [ -f "$ENV_FILE" ] || return 1
  v="$(grep -E "^[[:space:]]*(export[[:space:]]+)?${key}=" "$ENV_FILE" 2>/dev/null | tail -n1)" || return 1
  [ -n "$v" ] || return 1
  v="${v#*=}"
  v="${v%\"}"; v="${v#\"}"
  v="${v%\'}"; v="${v#\'}"
  printf '%s' "$v"
}

step "Credentials"

[ -f "$ENV_FILE" ] || die \
  "no .env at $ENV_FILE." \
  "It is gitignored and holds CLAUDE_CODE_OAUTH_TOKEN. Create it:" \
  "  printf 'CLAUDE_CODE_OAUTH_TOKEN=%s\\n' \"\$(claude setup-token)\" > $ENV_FILE" \
  "See agent/README.md."

# CLAUDE_CODE_OAUTH_TOKEN — present and non-empty. Never rewritten: if it is
# already there and correct, this step touches nothing.
if [ -n "$(env_value CLAUDE_CODE_OAUTH_TOKEN || true)" ]; then
  ok ".env declares CLAUDE_CODE_OAUTH_TOKEN (left untouched)"
else
  die "CLAUDE_CODE_OAUTH_TOKEN is missing or empty in $ENV_FILE." \
      "Generate one on a machine with a browser and copy it over:" \
      "  claude setup-token" \
      "The agent authenticates against the SUBSCRIPTION with this token."
fi

# THE BILLING FOOT-GUN, second door. The unit scrubs ANTHROPIC_API_KEY from the
# process environment, but config.py calls load_dotenv(REPO_ROOT/.env) at import
# — so a key sitting in .env is injected into os.environ AFTER systemd has
# scrubbed it, silently outranks the OAuth token, and bills pay-per-token.
# UnsetEnvironment= cannot save you from this. Refuse to install.
if [ -n "$(env_value ANTHROPIC_API_KEY || true)" ]; then
  die "ANTHROPIC_API_KEY is set in $ENV_FILE — remove that line." \
      "config.py load_dotenv()s this file, so the key would be re-injected into" \
      "the environment AFTER the systemd unit scrubs it, silently outrank" \
      "CLAUDE_CODE_OAUTH_TOKEN, and bill a pay-per-token account instead of the" \
      "subscription. The unit's UnsetEnvironment= cannot prevent this."
fi
ok ".env does not declare ANTHROPIC_API_KEY"

# .env is a secret file. Tighten perms only when they are wrong.
ENV_MODE="$(stat -c '%a' "$ENV_FILE")"
ENV_OWNER="$(stat -c '%U' "$ENV_FILE")"
if [ "$ENV_MODE" != "600" ] || [ "$ENV_OWNER" != "$SERVICE_USER" ]; then
  if would "tighten $ENV_FILE to ${SERVICE_USER}:0600 (currently ${ENV_OWNER}:${ENV_MODE})"; then
    chown "$SERVICE_USER" "$ENV_FILE"
    chmod 0600 "$ENV_FILE"
  fi
else
  ok "$ENV_FILE is ${SERVICE_USER}:0600"
fi

# --- AWS: the operator's step 2. We verify, we do not create. ---
AWS_CREDS="$SERVICE_HOME/.aws/credentials"
if [ -f "$AWS_CREDS" ] && grep -qE "^\[${AWS_PROFILE_NAME}\]" "$AWS_CREDS"; then
  ok "AWS profile [${AWS_PROFILE_NAME}] found in $AWS_CREDS"
else
  die "no [${AWS_PROFILE_NAME}] profile in $AWS_CREDS." \
      "That is the one thing you create by hand before running this script:" \
      "  sudo -u $SERVICE_USER aws configure --profile ${AWS_PROFILE_NAME}" \
      "(or write the file directly — the aws CLI is not otherwise needed here)." \
      "The agent's identity is asserted by healthcheck: it must be *:user/${AWS_PROFILE_NAME}."
fi

# --- Gmail: consent is a HUMAN act, in a browser, exactly once. ---
# The service must never attempt it: load_credentials(allow_interactive=True) is
# authorize.py's business. A missing token here is a stop, not something to fix.
for f in gmail_credentials.json token.json; do
  if [ -s "$REPO/$f" ]; then
    ok "$f present"
  else
    die "missing $REPO/$f — Gmail is not authorized on this host." \
        "A human must do this once, in a browser, as $SERVICE_USER:" \
        "  cd $REPO/agent && uv run python -m email_agent.authorize" \
        "The service will never do it for you; it would just fail every minute."
  fi
done

# ---------------------------------------------------------------------------
# 6. The systemd units
#
# THE UNIT IS WHERE THIS IS WON OR LOST.
#
#   * ANTHROPIC_API_KEY — scrubbed with UnsetEnvironment=. Belt and braces with
#     the .env check above and config.assert_subscription_auth(); we do not rely
#     on the process dying to catch a billing mistake.
#   * HOME — systemd does NOT give a unit the invoking shell's HOME, and boto3
#     resolves ~/.aws/credentials through it. Set explicitly. This is the bug
#     class that works perfectly by hand and fails as a service.
#   * AWS_SHARED_CREDENTIALS_FILE — the same fact, said a second way, so the
#     profile resolves even if something else redefines HOME.
#   * AWS_PROFILE — without it boto3 takes [default], which on a box that ever
#     grows a second profile means publishing as the wrong identity. healthcheck
#     asserts the identity precisely because that failure otherwise SUCCEEDS.
#   * PATH — publish.py shells out to `node`; systemd's default PATH is minimal.
#
# The env block is generated ONCE and shared by the heartbeat and the healthcheck
# units, so the verification in step 8 provably runs in the service's own
# environment rather than something that merely resembles it.
# ---------------------------------------------------------------------------

env_block() {
  cat <<EOF
Environment=HOME=${SERVICE_HOME}
Environment=AWS_PROFILE=${AWS_PROFILE_NAME}
Environment=AWS_SHARED_CREDENTIALS_FILE=${SERVICE_HOME}/.aws/credentials
Environment=AWS_CONFIG_FILE=${SERVICE_HOME}/.aws/config
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
Environment=PYTHONUNBUFFERED=1
UnsetEnvironment=ANTHROPIC_API_KEY
EOF
}

render_service_unit() {
  cat <<EOF
# Managed by scripts/install-agent-host.sh — re-run it instead of editing.
[Unit]
Description=Scripture Scroller email agent — one poll->dispatch pass (bs-tiz)
Documentation=file://${REPO}/agent/README.md
Documentation=file://${REPO}/specs/email-agent.md
After=network-online.target
Wants=network-online.target

[Service]
# oneshot, not a daemon: heartbeat.py is cron-shaped by design — one pass, then
# exit 0/1. The timer owns the cadence. dispatcher.py holds a transactional
# SQLite claim, so an overlapping run cannot double-process a thread.
Type=oneshot
User=${SERVICE_USER}
WorkingDirectory=${REPO}/agent
$(env_block)
ExecStart=${HEARTBEAT_BIN}
# A wedged run must not outlive its window; the dispatcher caps the agent itself
# (AGENT_TIMEOUT_SECONDS), this is the backstop around the whole pass.
TimeoutStartSec=2400
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SERVICE_NAME}

[Install]
WantedBy=multi-user.target
EOF
}

render_health_unit() {
  cat <<EOF
# Managed by scripts/install-agent-host.sh — re-run it instead of editing.
#
# Exists so the installer can prove the credentials work IN THE SERVICE'S OWN
# ENVIRONMENT. Its env block is generated from the same function as
# ${SERVICE_UNIT}, so a pass here is evidence about the real service and not
# about the operator's login shell. Run it any time:
#
#   sudo systemctl start --wait ${HEALTH_UNIT}; journalctl -u ${HEALTH_UNIT} -n 40
[Unit]
Description=Scripture Scroller email agent — credential healthcheck (bs-tiz)
Documentation=file://${REPO}/agent/README.md

[Service]
Type=oneshot
User=${SERVICE_USER}
WorkingDirectory=${REPO}/agent
$(env_block)
ExecStart=${HEALTH_BIN}
TimeoutStartSec=180
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SERVICE_NAME}-healthcheck
EOF
}

render_timer_unit() {
  cat <<EOF
# Managed by scripts/install-agent-host.sh — re-run it instead of editing.
[Unit]
Description=Scripture Scroller email agent heartbeat (every minute)
Documentation=file://${REPO}/agent/README.md

[Timer]
Unit=${SERVICE_UNIT}
# Every minute, on the minute. OnCalendar rather than a monotonic OnUnitActiveSec
# specifically so Persistent= is meaningful: it only applies to calendar timers.
OnCalendar=*:0/1
# Survive reboots: run once immediately if the box was down over a due tick.
Persistent=true
AccuracySec=1s
RandomizedDelaySec=0

[Install]
WantedBy=timers.target
EOF
}

# Write a unit only if its content differs. This is the whole no-duplicate,
# no-churn story: a converged host produces zero writes and zero daemon-reloads.
DAEMON_RELOAD_NEEDED=0
install_unit() {
  local name="$1" renderer="$2" dest="${UNIT_DIR}/$1" tmp="$TMPDIR_SELF/$1"
  "$renderer" > "$tmp"
  if cmp -s "$tmp" "$dest" 2>/dev/null; then
    ok "$name already up to date"
    return 0
  fi
  if would "write ${dest}"; then
    install -m 0644 "$tmp" "$dest"
    DAEMON_RELOAD_NEEDED=1
  fi
}

step "systemd units"
install_unit "$SERVICE_UNIT" render_service_unit
install_unit "$HEALTH_UNIT"  render_health_unit
install_unit "$TIMER_UNIT"   render_timer_unit

if [ "$DAEMON_RELOAD_NEEDED" -eq 1 ]; then
  act "systemctl daemon-reload"
  systemctl daemon-reload
elif [ "$CHECK_ONLY" -eq 0 ]; then
  skip "daemon-reload not needed (no unit changed)"
fi

# ---------------------------------------------------------------------------
# 7. Enable + start the timer
#
# Idempotency: `systemctl enable` is already idempotent (it manages one symlink),
# but we gate on is-enabled/is-active anyway so a converged run says "ok" instead
# of implying it did something. There is exactly one timer unit by name, so there
# is no way to end up with two.
# ---------------------------------------------------------------------------

step "Timer"
if [ "$CHECK_ONLY" -eq 1 ] && [ ! -f "${UNIT_DIR}/${TIMER_UNIT}" ]; then
  CHANGES=$((CHANGES + 1))
  printf '  %sWOULD%s %s\n' "$C_YEL" "$C_OFF" "enable and start ${TIMER_UNIT}"
else
  if [ "$(systemctl is-enabled "$TIMER_UNIT" 2>/dev/null || true)" = "enabled" ]; then
    ok "${TIMER_UNIT} already enabled"
  elif would "enable ${TIMER_UNIT}"; then
    systemctl enable "$TIMER_UNIT"
  fi

  if [ "$(systemctl is-active "$TIMER_UNIT" 2>/dev/null || true)" = "active" ]; then
    # Restart only when a unit actually changed, so a no-op run does not reset
    # the schedule out from under a run in flight.
    if [ "$DAEMON_RELOAD_NEEDED" -eq 1 ]; then
      act "restarting ${TIMER_UNIT} (unit content changed)"
      systemctl restart "$TIMER_UNIT"
    else
      ok "${TIMER_UNIT} already active"
    fi
  elif would "start ${TIMER_UNIT}"; then
    systemctl start "$TIMER_UNIT"
  fi
fi

# ---------------------------------------------------------------------------
# 8. VERIFICATION — part of the deliverable, not an afterthought
#
# Run healthcheck THROUGH SYSTEMD, as the service user, with the unit's env. An
# install that "succeeds" without this proof is the precise failure this epic
# exists to prevent: everything green until fifteen minutes before a service.
#
# healthcheck already covers Claude auth, Gmail (a live API call + send scope)
# and AWS (sts:GetCallerIdentity asserted to be *:user/cbc-wilm-agent, plus a
# real Put+Get against the bucket). Do not duplicate it here — call it.
# ---------------------------------------------------------------------------

if [ "$CHECK_ONLY" -eq 1 ]; then
  step "Summary (--check: nothing was changed)"
  if [ "$CHANGES" -eq 0 ]; then
    ok "host is converged; a real run would be a series of no-ops"
    exit 0
  fi
  printf '\n%s%d item(s) would change.%s Re-run without --check to apply.\n' \
    "$C_YEL" "$CHANGES" "$C_OFF"
  exit 1
fi

step "Verifying — healthcheck, in the service's own environment"
printf '  %s(systemctl start --wait %s)%s\n' "$C_DIM" "$HEALTH_UNIT" "$C_OFF"

set +e
systemctl start --wait "$HEALTH_UNIT"
health_rc=$?
set -e

# `systemctl start --wait` propagates the unit's failure, but read the recorded
# exit status too rather than trusting one signal about the thing whose whole
# job is to be trustworthy.
health_status="$(systemctl show -p ExecMainStatus --value "$HEALTH_UNIT" 2>/dev/null || echo "?")"

printf '\n'
journalctl -u "$HEALTH_UNIT" --since "-2 min" --no-pager -o cat 2>/dev/null | sed 's/^/  /' || true
printf '\n'

if [ "$health_rc" -ne 0 ] || [ "$health_status" != "0" ]; then
  die "healthcheck did NOT report HEALTHY (rc=${health_rc} exit=${health_status})." \
      "The timer is installed but the agent CANNOT work until this passes." \
      "Read the output above, then re-run this script after fixing it." \
      "" \
      "Common causes, in the order they bite:" \
      "  * AWS identity is not *:user/${AWS_PROFILE_NAME} — the [${AWS_PROFILE_NAME}]" \
      "    profile is missing/wrong in ${AWS_CREDS}, or a [default] profile is" \
      "    shadowing it. Env vars outrank ~/.aws/credentials." \
      "  * Gmail token expired -> cd $REPO/agent && uv run python -m email_agent.authorize" \
      "  * CLAUDE_CODE_OAUTH_TOKEN expired -> claude setup-token, update $ENV_FILE" \
      "" \
      "  journalctl -u ${HEALTH_UNIT} -n 50 --no-pager"
fi

ok "HEALTHY — Claude, Gmail and AWS all verified as ${SERVICE_USER} under systemd"

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

step "Installed"
systemctl list-timers "$TIMER_UNIT" --no-pager 2>/dev/null | sed 's/^/  /' || true

cat <<EOF

  ${C_GRN}The agent is live.${C_OFF} It polls Gmail every minute as ${SERVICE_USER}.

  Watch it:      journalctl -u ${SERVICE_UNIT} -f
  Timer status:  systemctl list-timers ${TIMER_UNIT}
  Re-healthcheck: sudo systemctl start --wait ${HEALTH_UNIT} && journalctl -u ${HEALTH_UNIT} -n 30
  One pass now:  sudo systemctl start ${SERVICE_UNIT}
  Pause it:      sudo systemctl stop ${TIMER_UNIT}

  Re-run this script after any change (git pull, new token, edited .env).
  It is idempotent: on an unchanged host it does nothing and exits 0.
EOF
