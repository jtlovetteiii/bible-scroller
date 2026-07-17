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
    agent_model: str = os.getenv("AGENT_MODEL", "claude-sonnet-5")

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


def assert_subscription_auth() -> None:
    """Guard the billing foot-gun from spec §4.6.

    If ANTHROPIC_API_KEY is set it silently wins over CLAUDE_CODE_OAUTH_TOKEN and
    bills a pay-per-token API account instead of the subscription. Fail loudly.
    """
    if os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is set — it overrides CLAUDE_CODE_OAUTH_TOKEN and would "
            "bill a pay-per-token API account instead of the subscription. Unset it."
        )
    if not os.getenv("CLAUDE_CODE_OAUTH_TOKEN"):
        raise RuntimeError(
            "CLAUDE_CODE_OAUTH_TOKEN is not set. Generate one with `claude setup-token` "
            "and put it in .env at the repo root."
        )


config = Config()
