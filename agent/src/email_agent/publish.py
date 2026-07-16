"""bs-tiz.10 — publish a rendered deck to S3 and return its public URL.

Same two-layer split as `tools.py`: pure functions that take an injectable S3
client and runner, plus a thin Claude Agent SDK wrapper.

Why this re-renders instead of uploading the deck the operator already has on
disk: `passages/<date>/service-preview.html` is built with the DEFAULT asset base
(`/templates/service`, served by Express), so its background images are
root-relative paths that only resolve against a local server. Uploading that file
produces a deck that loads with every background missing. Publishing therefore
means "render again, with the asset base pointed at the bucket, and upload THAT" —
the local preview is left untouched for the operator to keep using.

Exactly ONE HTML object goes up per deck. Templates are synced separately and
rarely (bs-tiz.11); there are no per-deck images and no data-URIs.
"""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from .config import REPO_ROOT, config

logger = logging.getLogger(__name__)

BUILD_DECK = REPO_ROOT / "scripts" / "build-deck.js"

#: Cache published decks briefly rather than forever. A deck gets corrected and
#: re-published at the same URL after the minister writes back, and an
#: immutable-style max-age would leave him staring at the old one.
CACHE_CONTROL = "public, max-age=300"


class PublishError(RuntimeError):
    """Raised when a deck cannot be rendered or uploaded."""


def _s3_client(client: Any | None = None) -> Any:
    if client is not None:
        return client
    import boto3  # local import: keeps the dependency off the import path of tests

    return boto3.client("s3")


def render_for_publish(
    deck_path: str | Path,
    out_path: str | Path,
    *,
    asset_base: str | None = None,
    runner: Any = subprocess.run,
) -> Path:
    """Render `deck_path` to `out_path` with backgrounds pointed at the bucket."""
    deck_path = Path(deck_path).expanduser().resolve()
    out_path = Path(out_path).expanduser().resolve()
    if not deck_path.is_file():
        raise PublishError(f"deck JSON not found: {deck_path}")

    base = asset_base or config.deck_asset_base()
    # --asset-base is passed EXPLICITLY. See config.deck_asset_base().
    proc = runner(
        [
            "node", str(BUILD_DECK), str(deck_path),
            "--out", str(out_path),
            "--asset-base", base,
            "--quiet",
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    if proc.returncode != 0:
        raise PublishError(
            f"build-deck.js failed (exit {proc.returncode}) for {deck_path.name}:\n"
            f"{(proc.stderr or proc.stdout or '').strip()}"
        )
    if not out_path.is_file():
        raise PublishError(f"build-deck.js reported success but wrote no {out_path}")
    return out_path


def deck_date(deck_path: str | Path) -> str:
    """The `date` field the deck's published path is keyed by."""
    try:
        deck = json.loads(Path(deck_path).expanduser().read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise PublishError(f"cannot read deck JSON {deck_path}: {exc}") from exc
    date = deck.get("date")
    if not date:
        raise PublishError(f"deck {deck_path} has no `date`; cannot key its URL")
    return str(date)


def publish_deck(
    deck_path: str | Path,
    *,
    client: Any | None = None,
    runner: Any = subprocess.run,
) -> dict[str, str]:
    """Render `deck_path` for hosting, upload one HTML object, return its URL."""
    date = deck_date(deck_path)
    key = config.deck_key(date)
    s3 = _s3_client(client)

    with tempfile.TemporaryDirectory() as tmp:
        html = render_for_publish(deck_path, Path(tmp) / "index.html", runner=runner)
        try:
            # No ACL argument: the bucket is BucketOwnerEnforced (bs-crp), so
            # `--acl public-read` hard-fails with AccessControlListNotSupported.
            # Objects are public via the bucket policy alone.
            s3.put_object(
                Bucket=config.deck_bucket,
                Key=key,
                Body=html.read_bytes(),
                ContentType="text/html; charset=utf-8",
                CacheControl=CACHE_CONTROL,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to the agent as text
            raise PublishError(
                f"upload to s3://{config.deck_bucket}/{key} failed: {exc}"
            ) from exc

    url = config.deck_url(date)
    logger.info("published deck %s -> %s", date, url)
    return {"url": url, "bucket": config.deck_bucket, "key": key, "date": date}


# ---------------------------------------------------------------------------
# Claude Agent SDK tool layer
# ---------------------------------------------------------------------------


def _ok(payload: Any) -> dict[str, Any]:
    text = payload if isinstance(payload, str) else json.dumps(payload, indent=2)
    return {"content": [{"type": "text", "text": text}]}


def _err(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": f"ERROR: {message}"}], "is_error": True}


@tool(
    "publish_deck",
    (
        "Upload a finished deck to the public web and return the https URL to put in "
        "your reply. Call this AFTER the deck JSON is final, and put the URL it "
        "returns in your email.\n"
        "Input: deck_path — path to the deck JSON file (NOT the HTML). The date the "
        "URL is keyed by is read from the deck's own `date` field.\n"
        "Returns JSON: url (give this to the minister), bucket, key, date.\n"
        "This re-renders the deck with its backgrounds pointed at the public asset "
        "root, so do NOT pass it a service-preview.html — that local file's image "
        "paths only work against a local server. Your local preview is left alone.\n"
        "Publishing the same date twice replaces the deck at the same URL, which is "
        "what you want after a correction: the link already in the minister's inbox "
        "keeps working and now shows the fixed deck."
    ),
    {
        "type": "object",
        "properties": {
            "deck_path": {
                "type": "string",
                "description": "Path to the deck JSON file to publish.",
            },
        },
        "required": ["deck_path"],
    },
)
async def publish_deck_tool(args: dict[str, Any]) -> dict[str, Any]:
    try:
        return _ok(publish_deck(args["deck_path"]))
    except Exception as exc:  # noqa: BLE001 - surface the failure to the model
        return _err(f"publish_deck failed: {exc}")


PUBLISH_TOOLS = [publish_deck_tool]

#: MCP-qualified names, for `ClaudeAgentOptions(allowed_tools=...)` in the harness.
PUBLISH_TOOL_NAMES = [f"mcp__deck__{t.name}" for t in PUBLISH_TOOLS]


def publish_tools_server():
    """In-process SDK MCP server exposing the publish tool."""
    return create_sdk_mcp_server(name="deck", version="0.1.0", tools=PUBLISH_TOOLS)
