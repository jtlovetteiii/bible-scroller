"""Central configuration for the email agent.

Subject pattern and poll interval are config, not code (spec §3, "Configurability").
Everything is overridable by environment variable so the deployment host can tune
it without a code change.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Repo root == parent of agent/
REPO_ROOT = Path(__file__).resolve().parents[3]

load_dotenv(REPO_ROOT / ".env")

# Gmail scopes the agent needs. `gmail.modify` covers read + send + label.
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


@dataclass(frozen=True)
class Config:
    # --- Email gate (bs-tiz.1) ---
    #: Messages whose Subject matches this are for the agent. Case-insensitive.
    subject_pattern: re.Pattern[str] = field(
        default_factory=lambda: re.compile(
            os.getenv("AGENT_SUBJECT_PATTERN", r"^\s*(re:\s*)*\s*(AI:|Calvary AI)"),
            re.IGNORECASE,
        )
    )
    #: Heartbeat interval in seconds.
    poll_interval_seconds: int = int(os.getenv("AGENT_POLL_INTERVAL", "60"))
    #: Only consider mail newer than this many days (avoids replaying the archive).
    lookback_days: int = int(os.getenv("AGENT_LOOKBACK_DAYS", "7"))

    # --- Credentials (never committed; see .gitignore) ---
    gmail_credentials_path: Path = REPO_ROOT / os.getenv(
        "GMAIL_CREDENTIALS_PATH", "gmail_credentials.json"
    )
    gmail_token_path: Path = REPO_ROOT / os.getenv("GMAIL_TOKEN_PATH", "token.json")

    # --- State (bs-tiz.2) ---
    state_db_path: Path = REPO_ROOT / os.getenv("AGENT_STATE_DB", "agent/state.db")

    # --- Deck output / links (bs-tiz.5, bs-tiz.6, bs-tiz.10) ---
    #: Where gen_service writes decks; served by Express during local development.
    passages_dir: Path = REPO_ROOT / "passages"

    #: Public origin of the deck bucket (or a CDN in front of it). Everything the
    #: minister's browser fetches — the deck HTML and the template images it
    #: references — hangs off this one origin, so there is a single thing to
    #: change when the bucket moves behind a custom domain.
    #:
    #: The S3 REST endpoint, NOT the static-website endpoint, and the https on it
    #: is load-bearing (bs-a4a). Website endpoints cannot serve https at all. The
    #: asset base is composed from this same origin and baked into the deck's
    #: <img src> at render time, so an http origin yields http images — and a
    #: browser BLOCKS insecure images on an https page. The deck then renders with
    #: text and layout intact and every background silently missing, which is the
    #: hardest kind of broken to notice. https works from either endpoint: mixed
    #: content only bites secure pages loading insecure subresources, never the
    #: reverse.
    #:
    #: default_factory, not a plain default: a bare `os.getenv(...)` default is
    #: evaluated once at import and would make a later `Config()` ignore the
    #: environment (see `subject_pattern` above, same reason).
    deck_base_url: str = field(
        default_factory=lambda: os.getenv(
            "DECK_BASE_URL",
            "https://cbc-wilm-agent-public.s3.us-east-1.amazonaws.com",
        )
    )
    #: Bucket the publish tool writes to. Named separately from `deck_base_url`
    #: because the two stop being derivable from each other the moment a CDN or
    #: custom domain fronts the bucket.
    deck_bucket: str = field(
        default_factory=lambda: os.getenv("DECK_BUCKET", "cbc-wilm-agent-public")
    )
    #: Key prefix for published decks. Paths are PERMANENT: an emailed link lives
    #: in the mailbox forever, so this changing means old links rot.
    deck_prefix: str = field(
        default_factory=lambda: os.getenv("DECK_PREFIX", "decks").strip("/")
    )

    #: Hard cap on a single agent run, so a wedged run can't hold its thread lock forever.
    agent_timeout_seconds: int = int(os.getenv("AGENT_TIMEOUT_SECONDS", "1800"))
    #: The model the agent runs on. Sonnet keeps API cost down — the point of the epic.
    #:
    #: default_factory, not a plain default: see `deck_base_url` above. A bare
    #: os.getenv default is evaluated once at import, so a test that sets the
    #: environment and then builds a fresh Config() would silently get the value
    #: captured at import time instead of the one it just set.
    agent_model: str = field(
        default_factory=lambda: os.getenv("AGENT_MODEL", "claude-sonnet-5")
    )

    # --- Alternate backend (bs-dox) ---
    #: Anthropic-compatible endpoint to route the agent at instead of api.anthropic.com.
    #: Unset (the normal case) means the subscription, via CLAUDE_CODE_OAUTH_TOKEN.
    #:
    #: This exists because the content-filter 400 of bs-a1f is a property of the
    #: *endpoint*, not of the model: per bs-a1f lyrics merely being in context is
    #: enough to trip it, so no amount of prompt or output shaping avoids it. The
    #: only fix that generalises is to send the run somewhere else, so the backend
    #: is configuration rather than code.
    #:
    #: Must speak Anthropic's /v1/messages — an OpenAI-shaped endpoint will not
    #: work directly, it needs a translating proxy in front (bs-dox).
    agent_base_url: str | None = field(
        default_factory=lambda: os.getenv("AGENT_BASE_URL") or None
    )
    #: Bearer token for `agent_base_url`. Optional: a proxy on a trusted LAN may
    #: not require one, and an empty value is passed through as "no credential"
    #: rather than as an empty header.
    agent_auth_token: str | None = field(
        default_factory=lambda: os.getenv("AGENT_AUTH_TOKEN") or None
    )

    @property
    def uses_alternate_backend(self) -> bool:
        """True when runs are routed somewhere other than the Anthropic API."""
        return self.agent_base_url is not None

    def agent_env(self) -> dict[str, str]:
        """Environment overlay for the CLI subprocess that runs one agent turn.

        Returned as `ClaudeAgentOptions.env`, which the SDK merges OVER the
        inherited environment (`subprocess_cli.py`), so what we put here wins over
        anything in the service's own env. That is the whole point: the parent
        process keeps its subscription credentials for every other purpose, and
        only the child is redirected.

        Empty on the default path — an empty overlay leaves the inherited
        environment, and therefore the subscription auth, exactly as it is today.
        """
        if not self.uses_alternate_backend:
            return {}

        env = {
            "ANTHROPIC_BASE_URL": self.agent_base_url or "",
            # Blank rather than absent. The overlay is merged, not substituted, so
            # a key we simply omit keeps the INHERITED value — and an inherited
            # subscription token pointed at a third-party endpoint is a credential
            # leak, not just a misconfiguration. Setting it empty is the only way
            # this dict can suppress something.
            "CLAUDE_CODE_OAUTH_TOKEN": "",
            # Same reasoning, plus: ANTHROPIC_API_KEY outranks ANTHROPIC_AUTH_TOKEN,
            # so a stray one would silently shadow the token we set below.
            "ANTHROPIC_API_KEY": "",
        }
        if self.agent_auth_token:
            # AUTH_TOKEN (Authorization: Bearer), not API_KEY (x-api-key): setting
            # both makes the client send both headers, which Anthropic-compatible
            # servers reject. Pick exactly one.
            env["ANTHROPIC_AUTH_TOKEN"] = self.agent_auth_token
        return env

    #: How many times one message may be attempted before the dispatcher gives up
    #: on it, apologises once, and drops it from the retry pool (bs-9ed).
    #:
    #: Why 3. The bound exists because a failing message is otherwise retried
    #: every heartbeat for the whole `lookback_days` window — at a 60s poll, up to
    #: thousands of Sonnet runs against a *subscription* quota, which starves the
    #: agent of the capacity to answer the real request on Saturday night. So the
    #: number has to be small. It cannot be 1: the failures we actually see are
    #: transient (a Gmail 503, a network blip, content filtering, which bs-a1f
    #: measures at ~12% and is nondeterministic), and one retry of a ~12% flake
    #: still fails 12% of the time. 3 attempts takes that to ~0.2% while capping
    #: the worst case at 3 wasted runs per poison message — cheap enough that a
    #: mailbox full of them cannot meaningfully dent the quota. Beyond 3 the
    #: marginal rescue is negligible and the minister just waits longer to hear
    #: that something went wrong.
    max_attempts_per_message: int = int(os.getenv("AGENT_MAX_ATTEMPTS", "3"))

    @property
    def _origin(self) -> str:
        return self.deck_base_url.rstrip("/")

    def deck_key(self, service_date: str) -> str:
        """S3 key for a published deck. The tool uploads EXACTLY this one object."""
        return f"{self.deck_prefix}/{service_date}/index.html"

    def deck_url(self, service_date: str) -> str:
        """Public URL emailed to the minister."""
        return f"{self._origin}/{self.deck_key(service_date)}"

    def deck_asset_base(self) -> str:
        """Asset base passed to build-deck.js so backgrounds resolve from the bucket.

        Must match where bs-tiz.11's template-sync script uploads the PNGs. It is
        passed to Node as an explicit CLI argument, never via the environment:
        nothing loads .env into the Node subprocess's process.env, so relying on
        DECK_ASSET_BASE bleeding through would silently render a deck with
        local-only image paths that 404 for the minister.
        """
        return f"{self._origin}/templates/service"


def assert_agent_auth() -> None:
    """Check that the configured backend has credentials it can actually use.

    Two backends, two different checks — the subscription foot-gun below is a
    statement about *Anthropic's* billing, so it does not apply when the run is
    not going to Anthropic at all.
    """
    if config.uses_alternate_backend:
        # An ANTHROPIC_API_KEY in the environment is harmless here: agent_env()
        # blanks it in the child, and nothing bills a subscription that isn't
        # being used. The token is optional (a LAN proxy may not want one), so
        # there is nothing left to require.
        return

    # Guard the billing foot-gun from spec §4.6. If ANTHROPIC_API_KEY is set it
    # silently wins over CLAUDE_CODE_OAUTH_TOKEN and bills a pay-per-token API
    # account instead of the subscription. Fail loudly.
    if os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is set — it overrides CLAUDE_CODE_OAUTH_TOKEN and would "
            "bill a pay-per-token API account instead of the subscription. Unset it, or "
            "set AGENT_BASE_URL to route this run at a different backend on purpose."
        )
    if not os.getenv("CLAUDE_CODE_OAUTH_TOKEN"):
        raise RuntimeError(
            "CLAUDE_CODE_OAUTH_TOKEN is not set. Generate one with `claude setup-token` "
            "and put it in .env at the repo root."
        )


config = Config()
