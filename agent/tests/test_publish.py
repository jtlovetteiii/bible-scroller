"""Unit tests for the deck publish tool (bs-tiz.10).

The S3 client and the build-deck.js subprocess are both injected, so nothing here
touches AWS or spawns Node — except `test_render_invokes_real_build_deck`, which
runs the real renderer against a real deck to keep the CLI contract honest.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from email_agent.config import REPO_ROOT, config
from email_agent.publish import (
    PublishError,
    deck_date,
    publish_deck,
    render_for_publish,
)


class FakeS3:
    """Stands in for boto3's S3 client; records every put_object call."""

    def __init__(self, error: Exception | None = None):
        self.puts: list[dict] = []
        self._error = error

    def put_object(self, **kwargs):
        if self._error is not None:
            raise self._error
        self.puts.append(kwargs)
        return {"ETag": '"fake"'}


class FakeRunner:
    """Stands in for subprocess.run, writing the HTML build-deck.js would write."""

    def __init__(self, returncode: int = 0, stderr: str = "", write: bool = True):
        self.calls: list[list[str]] = []
        self._returncode = returncode
        self._stderr = stderr
        self._write = write

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        if self._write and self._returncode == 0:
            out = Path(cmd[cmd.index("--out") + 1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("<html>slides</html>")
        return subprocess.CompletedProcess(cmd, self._returncode, "", self._stderr)


@pytest.fixture
def deck(tmp_path: Path) -> Path:
    path = tmp_path / "deck.json"
    path.write_text(json.dumps({"date": "2026-08-02", "segments": []}))
    return path


# --- URL / key composition -------------------------------------------------


def test_deck_url_and_key_are_date_keyed():
    assert config.deck_key("2026-08-02") == "decks/2026-08-02/index.html"
    assert config.deck_url("2026-08-02").endswith("/decks/2026-08-02/index.html")


def test_asset_base_matches_template_sync_location():
    # Must agree with where bs-tiz.11 uploads the PNGs, or backgrounds 404.
    assert config.deck_asset_base() == f"{config.deck_base_url.rstrip('/')}/templates/service"


def test_default_origin_is_https_and_not_the_website_endpoint():
    """bs-a4a. Regression: an http origin breaks the deck SILENTLY.

    The origin is baked into every <img src> at render time, so http here means
    http images — which browsers block on an https page, leaving a deck whose
    text and layout are perfect and whose backgrounds are all gone. S3 website
    endpoints cannot serve https at all, so they can never be this value.
    """
    assert config.deck_base_url.startswith("https://")
    assert "s3-website" not in config.deck_base_url


def test_asset_base_and_deck_link_share_one_origin():
    """They must never diverge: same-origin images are why the happy path needs
    no CORS, and a split origin reintroduces the mixed-content trap per-half."""
    from urllib.parse import urlparse

    assert urlparse(config.deck_asset_base()).netloc == urlparse(config.deck_url("2026-08-02")).netloc


def test_origin_trailing_slash_does_not_double_up(monkeypatch):
    from email_agent.config import Config

    monkeypatch.setenv("DECK_BASE_URL", "https://decks.example.org/")
    cfg = Config()
    assert cfg.deck_url("2026-08-02") == "https://decks.example.org/decks/2026-08-02/index.html"
    assert cfg.deck_asset_base() == "https://decks.example.org/templates/service"


# --- render ----------------------------------------------------------------


def test_render_passes_asset_base_explicitly(deck: Path, tmp_path: Path):
    runner = FakeRunner()
    render_for_publish(deck, tmp_path / "index.html", runner=runner)

    cmd = runner.calls[0]
    # The whole point: the asset base reaches Node as an ARGUMENT. Nothing loads
    # .env into the subprocess, so an env-only asset base would silently render
    # local-only image paths.
    assert "--asset-base" in cmd
    assert cmd[cmd.index("--asset-base") + 1] == config.deck_asset_base()


def test_render_surfaces_build_deck_failure(deck: Path, tmp_path: Path):
    runner = FakeRunner(returncode=1, stderr="segment 3: unknown song", write=False)
    with pytest.raises(PublishError, match="unknown song"):
        render_for_publish(deck, tmp_path / "index.html", runner=runner)


def test_render_fails_when_no_html_written(deck: Path, tmp_path: Path):
    runner = FakeRunner(write=False)
    with pytest.raises(PublishError, match="wrote no"):
        render_for_publish(deck, tmp_path / "index.html", runner=runner)


def test_render_rejects_missing_deck(tmp_path: Path):
    with pytest.raises(PublishError, match="not found"):
        render_for_publish(tmp_path / "nope.json", tmp_path / "out.html", runner=FakeRunner())


# --- deck_date -------------------------------------------------------------


def test_deck_date_reads_the_date_field(deck: Path):
    assert deck_date(deck) == "2026-08-02"


def test_deck_date_rejects_dateless_deck(tmp_path: Path):
    path = tmp_path / "d.json"
    path.write_text(json.dumps({"segments": []}))
    with pytest.raises(PublishError, match="no `date`"):
        deck_date(path)


# --- publish ---------------------------------------------------------------


def test_publish_uploads_exactly_one_html_object(deck: Path):
    s3, runner = FakeS3(), FakeRunner()
    result = publish_deck(deck, client=s3, runner=runner)

    assert len(s3.puts) == 1, "one deck == one object; templates sync separately"
    put = s3.puts[0]
    assert put["Bucket"] == config.deck_bucket
    assert put["Key"] == "decks/2026-08-02/index.html"
    assert put["Body"] == b"<html>slides</html>"
    assert put["ContentType"].startswith("text/html")
    assert result["url"] == config.deck_url("2026-08-02")


def test_publish_sends_no_acl(deck: Path):
    # The bucket is BucketOwnerEnforced (bs-crp): any ACL argument hard-fails
    # with AccessControlListNotSupported. Public read comes from the policy.
    s3, runner = FakeS3(), FakeRunner()
    publish_deck(deck, client=s3, runner=runner)
    assert "ACL" not in s3.puts[0]


def test_publish_does_not_disturb_the_local_preview(deck: Path):
    runner = FakeRunner()
    publish_deck(deck, client=FakeS3(), runner=runner)

    out = Path(runner.calls[0][runner.calls[0].index("--out") + 1])
    assert not str(out).startswith(str(config.passages_dir)), (
        "publish must render to a temp path; the operator's local preview keeps "
        "its local asset base"
    )


def test_publish_cleans_up_its_temp_render(deck: Path):
    runner = FakeRunner()
    publish_deck(deck, client=FakeS3(), runner=runner)
    out = Path(runner.calls[0][runner.calls[0].index("--out") + 1])
    assert not out.exists()


def test_publish_surfaces_upload_failure(deck: Path):
    s3 = FakeS3(error=RuntimeError("AccessDenied"))
    with pytest.raises(PublishError, match="AccessDenied"):
        publish_deck(deck, client=s3, runner=FakeRunner())


def test_publish_skips_upload_when_render_fails(deck: Path):
    s3 = FakeS3()
    with pytest.raises(PublishError):
        publish_deck(deck, client=s3, runner=FakeRunner(returncode=1, write=False))
    assert s3.puts == [], "a broken deck must never reach the bucket"


# --- contract with the real renderer ---------------------------------------


def test_render_invokes_real_build_deck(tmp_path: Path):
    """Guards the CLI contract: the flags publish.py passes must really exist.

    The mocked tests above would keep passing if build-deck.js renamed
    --asset-base tomorrow. This one would not.
    """
    deck = tmp_path / "deck.json"
    deck.write_text(json.dumps({
        "date": "2026-08-02",
        "segments": [{"type": "welcome"}],
    }))
    out = tmp_path / "index.html"
    render_for_publish(deck, out, asset_base="https://example.test/templates/service")

    html = out.read_text()
    assert "https://example.test/templates/service/" in html
    # Cross-origin asset base => the <img> must opt into CORS, or html2canvas
    # export throws SecurityError on a tainted canvas (bs-517).
    assert 'crossorigin="anonymous"' in html
