"""Harness for the gen_service batch-mode evals.

(Deliberately NOT named conftest.py: pytest puts this directory on sys.path, and a
second module called `conftest` shadows tests/conftest.py for the unit tests.)

These are EVALS, not unit tests: they run the real model against the real skill
and cost real time and tokens. They are excluded from the default suite
(`-m "not eval"` in pyproject) — run them deliberately:

    uv run pytest -m eval -s

What makes them repeatable, despite a nondeterministic model, is that the model's
only output is a small deck JSON: everything downstream of it (slide numbering,
backgrounds, splitting, the report) is deterministic, and build-deck.js is pinned
by its own golden tests. So an eval never grades prose. It asserts on structure —
the deck's segment types in order, and the machine-readable service-report.json.

Two things this harness deliberately controls:

1. THE SONG LIBRARY. Every fixture's expected behaviour depends on what the agent
   already knows: a song in songs/ is reused, a public-domain hymn is looked up
   and saved, a modern praise song can be neither and must be asked about. Run
   against the live songs/ and the eval's meaning would drift every time someone
   adds a hymn. So each eval gets a fresh workspace with a seeded library.

2. THE TERMINAL BOUNDARY. In production a run ends in send_reply or skip_reply
   (harness.TERMINAL_TOOLS). Here send_reply is a stand-in that just records the
   body, so the eval exercises the same seam bs-tiz.5 will build on: we assert on
   what the agent *would have emailed*, and on what it left on disk.
"""

from __future__ import annotations

import json
import re
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    TextBlock,
    create_sdk_mcp_server,
    tool,
)

from email_agent.config import REPO_ROOT, assert_agent_auth, config

# Directories the skill and build script need. `scripts/` must be COPIED, not
# symlinked: build-deck.js derives its root from its own __dirname, so a symlink
# would resolve back to the real repo and the agent would write its deck into
# the actual passages/ directory. templates/ is 194MB of PNGs and is only ever
# read, so it gets a symlink.
_COPY = ("scripts", "schemas", ".claude", "examples")
_LINK = ("templates",)


@dataclass
class EvalRun:
    """What the agent did: what it left on disk, and what it would have emailed."""

    workspace: Path
    replies: list[str] = field(default_factory=list)
    transcript: list[str] = field(default_factory=list)

    @property
    def reply(self) -> str:
        assert self.replies, (
            "the agent never sent a reply — it must always end in one."
            + (f"\n\nThe run ERRORED: {self.error}" if self.error else "")
        )
        return "\n\n".join(self.replies)

    @property
    def error(self) -> str | None:
        """An API-level failure, as distinct from the agent choosing not to reply.

        These are not the same thing and must not be diagnosed as if they were. The
        one we actually hit is `400 Output blocked by content filtering policy` — an
        agent that writes lyrics out verbatim will sometimes have its output refused
        (see bs-a1f). Surface it, don't let it masquerade as a reasoning failure.

        bs-1mf removed the reason this happened: lyric text now reaches a slide only
        from `songs/*.md`, so the model emits slugs, not words. Which makes this error
        diagnostic rather than expected — if it fires again, the first thing to check
        is whether the model went back to supplying lyrics itself.
        """
        for text in self.transcript:
            if "API Error" in text or "content filtering" in text:
                return text.strip()
        return None

    def deck_path(self, date: str) -> Path:
        return self.workspace / "passages" / date / "service.deck.json"

    def built_a_deck(self, date: str) -> bool:
        """A deck is only real if it was BUILT — a JSON file nobody rendered is not a deck."""
        return (self.workspace / "passages" / date / "service-preview.html").exists()

    def deck(self, date: str) -> dict:
        return json.loads(self.deck_path(date).read_text())

    def report(self, date: str) -> dict:
        return json.loads((self.workspace / "passages" / date / "service-report.json").read_text())

    def segment_types(self, date: str) -> list[str]:
        return [s["type"] for s in self.deck(date)["segments"]]

    def music(self, date: str) -> list[dict]:
        return [
            s
            for s in self.deck(date)["segments"]
            if s["type"] in ("song", "special_music", "prelude")
        ]

    def find_music(self, date: str, needle: str) -> dict:
        """The segment for one piece of music, by slug OR title.

        Both matter: a library song is referenced by `song` slug, but special
        music and the prelude are often just a `title` — nothing is added to
        songs/ for a number the congregation doesn't sing.
        """
        # Slugs are hyphenated ("tell-me-the-story-of-jesus") and titles are spaced
        # ("Tell Me the Story of Jesus"). Flatten both so one needle matches either.
        def flatten(s: str) -> str:
            return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()

        needle = flatten(needle)
        for seg in self.music(date):
            haystack = flatten(f"{seg.get('song', '')} {seg.get('title', '')}")
            if needle in haystack:
                return seg
        raise AssertionError(
            f"no segment for {needle!r} in the deck: {json.dumps(self.music(date), indent=2)}"
        )


def _stage(root: Path) -> Path:
    """A throwaway repo with its own song library, so the agent cannot see or
    touch the real one."""
    ws = root / "repo"
    ws.mkdir()

    for name in _COPY:
        shutil.copytree(REPO_ROOT / name, ws / name)
    for name in _LINK:
        (ws / name).symlink_to(REPO_ROOT / name)

    # Seeded from the real library: these are the songs the agent "has done
    # before". Each eval then prunes it down to set up its scenario.
    shutil.copytree(REPO_ROOT / "songs", ws / "songs")
    (ws / "passages").mkdir()
    return ws


@pytest.fixture(scope="module")
def stage(tmp_path_factory):
    """Hands back a factory, not a workspace: each flowchart needs its OWN repo,
    because they seed different song libraries and the agent writes new songs into
    the one it is given. Sharing one would let the first run contaminate the second.

    Module-scoped because an agent run takes minutes and costs tokens — each
    flowchart is run once, and every assertion about it reads that same run.
    """

    def make(name: str) -> Path:
        return _stage(tmp_path_factory.mktemp(name))

    return make


def seed_library(ws: Path, *, keep: set[str]) -> None:
    """Restrict the workspace library to `keep` (song slugs). Everything else is
    a song the agent has never seen, and must look up or ask about."""
    for f in (ws / "songs").glob("*.md"):
        if f.stem not in keep:
            f.unlink()


BATCH_PROMPT = """\
The minister of music has emailed you this week's order of service (the "flowchart").
Handle it end to end with the `gen_service` skill. Today is {today}.

There is NO interactive user: never ask a question and wait, because nobody will
answer. When you have something to say — a question, a deck link, a list of what to
check — call `send_reply`. Every run ends in exactly one `send_reply`.

--- the email ---
Subject: AI: {subject}

{flowchart}
--- end of email ---
"""


async def run_gen_service(ws: Path, flowchart: str, *, subject: str, today: str) -> EvalRun:
    """Run the real skill, on the real model, against one flowchart."""
    assert_agent_auth()
    run = EvalRun(workspace=ws)

    @tool(
        "send_reply",
        (
            "Reply to the minister of music. This ENDS the run — call it exactly once, "
            "when you have either built the deck or determined you cannot proceed "
            "without more information.\n"
            "Input: body (the text of your reply, written as a person would write it)."
        ),
        {
            "type": "object",
            "properties": {"body": {"type": "string"}},
            "required": ["body"],
        },
    )
    async def send_reply(args: dict) -> dict:
        run.replies.append(args["body"])
        return {"content": [{"type": "text", "text": "Reply sent."}]}

    options = ClaudeAgentOptions(
        model=config.agent_model,
        cwd=str(ws),
        mcp_servers={"eval": create_sdk_mcp_server(name="eval", version="0.1.0", tools=[send_reply])},
        # Without setting_sources=["project"] the SDK cannot see .claude/ and the
        # agent silently has no gen_service to call. It fails quietly, not loudly.
        setting_sources=["project"],
        allowed_tools=[
            "mcp__eval__send_reply",
            "Read", "Write", "Edit", "Bash", "Glob", "Grep", "WebSearch", "WebFetch",
        ],
        permission_mode="bypassPermissions",  # headless: nobody can approve a prompt
    )

    prompt = BATCH_PROMPT.format(today=today, subject=subject, flowchart=flowchart)

    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt)
        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        run.transcript.append(block.text)

    return run


def read_flowchart(name: str) -> str:
    """Pull one flowchart out of examples/flowcharts.md by its heading date.

    The fixtures live in that document rather than in a tests/ directory of their
    own, because it is also the human-readable record of what these emails look
    like and how they are meant to be handled. One copy, not two.
    """
    text = (REPO_ROOT / "examples" / "flowcharts.md").read_text()
    marker = f"## Example: {name}"
    assert marker in text, f"no flowchart for {name} in examples/flowcharts.md"

    section = text.split(marker, 1)[1]
    body = section.split("### Actual Flowchart", 1)[1]
    return body.split("###", 1)[0].strip()


def validate_deck(ws: Path, deck: dict) -> None:
    """The deck must conform to the schema the build script enforces."""
    import jsonschema

    schema = json.loads((ws / "schemas" / "deck.schema.json").read_text())
    jsonschema.validate(deck, schema)


def rebuild(ws: Path, date: str) -> subprocess.CompletedProcess:
    """Re-run the build ourselves. If the agent's deck cannot be rebuilt from
    scratch, it is not reproducible and the artifact it emailed is a fluke."""
    return subprocess.run(
        ["node", "scripts/build-deck.js", f"passages/{date}/service.deck.json"],
        cwd=ws,
        capture_output=True,
        text=True,
    )
