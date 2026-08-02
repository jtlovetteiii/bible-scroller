"""The real 2026-07-26 thread, parsed out of examples/flowcharts.md (bs-2pn).

NO NETWORK. The fixture is not duplicated here on purpose: examples/flowcharts.md is
the committed record of what actually happened, and a second copy would drift from it.
This module only slices that file.

The thread that matters is `minister_lyrics()` — the minister's reply pasting all six
songs. That is the message that blocked 6/6 on the day.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
FLOWCHARTS = REPO_ROOT / "examples" / "flowcharts.md"

EXAMPLE_HEADING = "## Example: 7/26/2026"

#: The six songs the minister ended up asking for. "No Body" was dropped in the reply
#: and must NOT appear; "All Hail King Jesus" replaced it.
EXPECTED_SONGS = [
    "The Lord Will Provide",
    "One Day",
    "How Firm a Foundation",
    "All Hail King Jesus",
    "Goodness of God",
    "Jesus, Keep Me Near the Cross",
]


def _sections() -> dict[str, str]:
    """Split the 7/26 example into its `### ` subsections, in order."""
    text = FLOWCHARTS.read_text(encoding="utf-8")
    start = text.index(EXAMPLE_HEADING)
    # The example runs until the next `## ` heading, or EOF.
    nxt = re.search(r"^## ", text[start + len(EXAMPLE_HEADING):], re.M)
    body = text[start:start + len(EXAMPLE_HEADING) + nxt.start()] if nxt else text[start:]

    out: dict[str, str] = {}
    parts = re.split(r"^### (.+)$", body, flags=re.M)
    # parts[0] is the preamble before the first ###; then (heading, body) pairs.
    for i in range(1, len(parts), 2):
        out[parts[i].strip()] = parts[i + 1].strip("\n")
    return out


def initial_request() -> str:
    return _sections()["Initial Email to the Agent"].strip()


def agent_first_reply() -> str:
    return _sections()["First Reply from the Agent"].strip()


def minister_lyrics() -> str:
    """The minister's reply with all six songs' lyrics pasted in.

    Kept with its exact whitespace — trailing spaces and blank lines included. The
    slicing design's whole claim is that it is byte-exact, so the fixture must be too.
    """
    return _sections()["First Reply from the Minister"].strip("\n")


def full_thread() -> str:
    """The thread as the agent would see it, oldest first."""
    return (
        "From: Quentin <minister@example.org>\n"
        "Subject: Slides for Sunday\n\n"
        f"{initial_request()}\n\n"
        "---\n\n"
        "From: Calvary AI <agent@example.org>\n"
        "Subject: Re: Slides for Sunday\n\n"
        f"{agent_first_reply()}\n\n"
        "---\n\n"
        "From: Quentin <minister@example.org>\n"
        "Subject: Re: Slides for Sunday\n\n"
        f"{minister_lyrics()}\n"
    )


if __name__ == "__main__":
    lyr = minister_lyrics()
    thread = full_thread()
    print(f"minister_lyrics: {len(lyr.splitlines())} lines, {len(lyr)} chars")
    print(f"full_thread:     {len(thread.splitlines())} lines, {len(thread)} chars")
    print("\nfirst 5 lines of minister reply:")
    for ln in lyr.splitlines()[:5]:
        print(f"  {ln!r}")
    print("\nlast 3 lines:")
    for ln in lyr.splitlines()[-3:]:
        print(f"  {ln!r}")
