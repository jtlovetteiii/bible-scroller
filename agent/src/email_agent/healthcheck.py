"""Preflight: is the agent actually able to run right now?

    cd agent && uv run python -m email_agent.healthcheck

Exists because both of this agent's credentials fail **silently and on a delay**:

  * A Gmail refresh token dies with `invalid_grant` — and if the OAuth app's
    publishing status is "Testing", Google kills it after 7 days. A Testing token
    and a production one are indistinguishable for the first week, so the only way
    to know publishing really took is to still be working on day 8+.
  * `ANTHROPIC_API_KEY` appearing in the environment silently outranks
    `CLAUDE_CODE_OAUTH_TOKEN` and bills a pay-per-token account instead of the
    subscription.

Neither shows up until the agent is mid-run. Run this on a schedule so it fails on
a Tuesday, not fifteen minutes before a service.
"""

from __future__ import annotations

import datetime as dt
import json
import sys

from .config import config, assert_subscription_auth
from .gmail_client import gmail_service


def _token_age_days() -> float | None:
    """Days since the refresh token was issued, inferred from the file's mtime.

    Crude, but the number that matters: crossing ~7 days while still working is
    the evidence that the OAuth app is genuinely published.
    """
    if not config.gmail_token_path.exists():
        return None
    mtime = dt.datetime.fromtimestamp(config.gmail_token_path.stat().st_mtime)
    return (dt.datetime.now() - mtime).total_seconds() / 86400


def main() -> int:
    failures: list[str] = []

    # --- Claude auth ---
    try:
        assert_subscription_auth()
        print("OK    claude: CLAUDE_CODE_OAUTH_TOKEN set, ANTHROPIC_API_KEY unset")
    except RuntimeError as exc:
        failures.append(f"claude: {exc}")
        print(f"FAIL  claude: {exc}")

    # --- Gmail auth: a live call, not just a file read ---
    try:
        profile = gmail_service().users().getProfile(userId="me").execute()
        print(f"OK    gmail: authenticated as {profile['emailAddress']}")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"gmail: {type(exc).__name__}: {exc}")
        print(f"FAIL  gmail: {type(exc).__name__}: {exc}")
        print("      -> re-run: uv run python -m email_agent.authorize")

    # --- Send scope: without it the whole reply loop is dead ---
    try:
        scopes = json.loads(config.gmail_token_path.read_text()).get("scopes", [])
        can_send = any(
            s.endswith(("gmail.send", "gmail.modify")) or s == "https://mail.google.com/"
            for s in scopes
        )
        print(f"{'OK   ' if can_send else 'FAIL '} gmail: send scope {'present' if can_send else 'MISSING'}")
        if not can_send:
            failures.append("gmail: token lacks send scope; send_reply cannot work")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"gmail scopes unreadable: {exc}")

    # --- The 7-day tell ---
    age = _token_age_days()
    if age is not None:
        if age >= 7:
            print(f"OK    gmail: refresh token is {age:.1f} days old and still valid")
            print("      -> past the 7-day Testing-status cliff; the OAuth app is genuinely published")
        else:
            print(f"WARN  gmail: refresh token is only {age:.1f} days old")
            print("      -> too young to prove the OAuth app is published. If it dies around day 7,")
            print("         the app is still in 'Testing' status in Google Cloud Console (bs-xy9).")

    print()
    if failures:
        print(f"UNHEALTHY — {len(failures)} problem(s). The agent will NOT work.")
        return 1
    print("HEALTHY — the agent can read mail, send mail, and reach Claude.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
