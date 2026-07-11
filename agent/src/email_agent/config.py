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

    # --- Deck output / links (bs-tiz.5, bs-tiz.6) ---
    #: Where gen_service writes decks; served by Express.
    passages_dir: Path = REPO_ROOT / "passages"
    #: Base URL the reply link is built from.
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "http://localhost:3000")

    #: Hard cap on a single agent run, so a wedged run can't hold its thread lock forever.
    agent_timeout_seconds: int = int(os.getenv("AGENT_TIMEOUT_SECONDS", "1800"))
    #: The model the agent runs on. Sonnet keeps API cost down — the point of the epic.
    agent_model: str = os.getenv("AGENT_MODEL", "claude-sonnet-5")

    def deck_url(self, service_date: str) -> str:
        return f"{self.public_base_url}/passages/{service_date}/service-preview.html"


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
