"""Shared Gmail authentication + service construction.

Both the gate (bs-tiz.1, metadata-only polling) and the agent's tools (bs-tiz.3,
message/attachment/reply) build on the single authorized service returned here.

Credentials live at the repo root and are gitignored:
  - gmail_credentials.json : OAuth client (installed-app) from Google Cloud Console
  - token.json             : the user's authorized refresh token
"""

from __future__ import annotations

import functools

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from .config import GMAIL_SCOPES, config


def load_credentials(*, allow_interactive: bool = False) -> Credentials:
    """Load stored credentials, refreshing them if expired.

    `allow_interactive=True` runs the one-time browser consent flow. The service
    (gate/dispatcher/agent) must never do this — it runs headless, so a missing or
    unrefreshable token is a hard error there.
    """
    creds: Credentials | None = None

    if config.gmail_token_path.exists():
        creds = Credentials.from_authorized_user_file(
            str(config.gmail_token_path), GMAIL_SCOPES
        )

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        config.gmail_token_path.write_text(creds.to_json())
        return creds

    if not allow_interactive:
        raise RuntimeError(
            f"No valid Gmail credentials at {config.gmail_token_path} and interactive "
            "consent is disabled. Run `uv run python -m email_agent.authorize` once."
        )

    flow = InstalledAppFlow.from_client_secrets_file(
        str(config.gmail_credentials_path), GMAIL_SCOPES
    )
    creds = flow.run_local_server(port=0)
    config.gmail_token_path.write_text(creds.to_json())
    return creds


@functools.cache
def gmail_service():
    """Authorized Gmail API service. Cached — one per process."""
    return build("gmail", "v1", credentials=load_credentials(), cache_discovery=False)


def granted_scopes() -> list[str]:
    """Scopes actually present on the stored token.

    Diagnostic only: returns scope URLs, never token material. The stored token
    predates this project, so it may not carry `gmail.modify` — without send
    permission `sendReply` (bs-tiz.3) cannot work.
    """
    creds = Credentials.from_authorized_user_file(
        str(config.gmail_token_path), GMAIL_SCOPES
    )
    return list(creds.scopes or [])
