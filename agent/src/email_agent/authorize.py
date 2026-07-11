"""One-time Gmail consent flow. Run by a human, never by the service.

    cd agent && uv run python -m email_agent.authorize

Opens a browser, asks you to grant `gmail.modify` (read + send), and writes the
refreshed token to token.json at the repo root.

Note: while the OAuth app's publishing status is "Testing" in Google Cloud Console,
Google expires the refresh token after 7 days and you must re-run this. Set the app
to "In production" (or add yourself as a test user and accept the re-consent cadence)
before relying on it unattended.
"""

from __future__ import annotations

from .config import config
from .gmail_client import gmail_service, load_credentials


def main() -> None:
    load_credentials(allow_interactive=True)
    profile = gmail_service().users().getProfile(userId="me").execute()
    print(f"Authorized as {profile['emailAddress']}")
    print(f"Token written to {config.gmail_token_path}")


if __name__ == "__main__":
    main()
