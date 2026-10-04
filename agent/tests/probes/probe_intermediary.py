"""Can Bonsai act as the email->library intermediary? (bs-8qs, Thomas's design)

THE DESIGN UNDER TEST: a local model reads the incoming mail, pulls any lyrics into
songs/*.md, and hands the frontier model a version of the email with the lyrics
REPLACED BY REFERENCES. The frontier model then never has lyric text in context, so
neither Anthropic's content filter nor any provider's copyright refusal can fire —
and the fragile part (deciding what IS a lyric) is done by a model rather than a
regex.

This probe builds a DELIBERATELY MESSY email to attack that weak point:
  - lyrics butted directly against prose with no blank line
  - an instruction sentence buried BETWEEN two stanzas
  - two songs' lyrics adjacent with only a bare title between them
  - a song mentioned by TITLE ONLY, with no lyrics (must NOT be invented)
  - short prose lines that superficially look like lyrics (must NOT be redacted)

The lyric text is read from the repo's own songs/*.md so nothing new is introduced;
the scenario is that these two songs are NOT yet in the library.

Checks, all mechanical:
  1. no lyric line survives anywhere in the redacted text        (under-redaction)
  2. every prose/instruction line survives in the redacted text  (over-redaction)
  3. every lyric line written to the library appears VERBATIM in
     the source email                                            (hallucination)
  4. the title-only song gets no fabricated lyrics

Run from agent/:
  uv run python tests/probes/probe_intermediary.py --model bonsai
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import time
from pathlib import Path

import anyio
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(REPO_ROOT / ".env")

from claude_agent_sdk import (  # noqa: E402
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    query,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from probe_filter import proxy_env  # noqa: E402

#: Prose the minister writes. Every one of these MUST survive redaction.
PROSE = [
    "Hi - here's the order of service for Sunday the 9th.",
    "We'll open with the call to worship as usual, then two congregational songs.",
    "Sorry for the mess, I'm copying these out of the CCLI site on my phone.",
    "Please put the second one AFTER the offering, not before.",
    "The choir is doing an arrangement of Days of Elijah for special music - you",
    "already have that one I think.",
    "Also we need the baptism slide for the Whitaker twins.",
    "Thanks!",
]

#: Short prose that LOOKS lyric-ish. Must NOT be redacted.
DECOYS = [
    "Short version:",
    "Two songs, one special.",
    "Nothing else changed.",
]


def lyric_lines(slug: str) -> list[str]:
    """Lyric lines of a repo song, headings and frontmatter stripped."""
    text = (REPO_ROOT / "songs" / f"{slug}.md").read_text()
    body = text.split("---", 2)[-1]
    return [
        ln.strip()
        for ln in body.splitlines()
        if ln.strip() and not ln.strip().startswith(("#", "<!--"))
    ]


def build_email() -> tuple[str, list[str]]:
    a, b = lyric_lines("waymaker"), lyric_lines("revelation-song")
    parts: list[str] = []
    parts.append(PROSE[0])
    parts.append(PROSE[1])
    parts.append("")
    parts.append(DECOYS[0])
    parts.append(DECOYS[1])
    parts.append("")
    # Lyrics butted straight onto a sentence, no blank line.
    parts.append(PROSE[2] + " " + a[0])
    parts.extend(a[1:6])
    # Instruction buried mid-stanza.
    parts.append(PROSE[3])
    parts.extend(a[6:])
    # Second song, only a bare title separating it.
    parts.append("Revelation Song")
    parts.extend(b)
    parts.append("")
    parts.append(PROSE[4])
    parts.append(PROSE[5])
    parts.append(PROSE[6])
    parts.append(DECOYS[2])
    parts.append(PROSE[7])
    return "\n".join(parts), a + b


PROMPT = """\
You are a preprocessing step. A minister has emailed the order of service for a
church worship service. The email is in the file: {email}

Your job has two parts.

PART 1 — extract lyrics into the song library.
Some of this email is song lyrics the minister pasted in. Some of it is ordinary
prose: instructions, greetings, notes about who is singing. Work out which is which.
For each song whose LYRICS are actually present in the email, write a file to:
    {libdir}/<slug>.md
where <slug> is the song title lowercased with spaces replaced by hyphens.
The file must be:

---
title: <Song Title>
public_domain: false
verified: false
---

## Verse 1
<the lyric lines>

## Chorus
<the lyric lines>

Copy the lyric lines EXACTLY as they appear in the email, character for character.
Do not correct, reword, reformat or complete them. If the email contains a `|`
character inside a lyric line, keep it exactly where it is — it is a formatting
marker, not punctuation.

If a song is only MENTIONED BY NAME and its lyrics are not in the email, do NOT
create a file for it and do NOT write any lyrics for it from memory.

PART 2 — write the redacted email.
Write to: {outfile}
This must be the SAME email with every block of song lyrics REMOVED and replaced by
a single reference line of exactly this form:

    [LYRICS: "<Song Title>" -> {libdir}/<slug>.md]

Every line of ordinary prose — every instruction, greeting, note and aside — must be
preserved EXACTLY as it appears in the original, in the original order. Do not
summarise the email. Do not drop short lines. Do not reword anything. The only
change you make is replacing lyric blocks with reference lines.

When both parts are done, stop.
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="bonsai")
    ap.add_argument("--backend", choices=["cloud", "proxy"], default="proxy")
    args = ap.parse_args()

    work = Path(tempfile.mkdtemp(prefix="intermediary-"))
    libdir = work / "songs"
    libdir.mkdir()
    email_path = work / "email.txt"
    out_path = work / "redacted.txt"

    email_text, all_lyrics = build_email()
    email_path.write_text(email_text)

    env = proxy_env() if args.backend == "proxy" else {}
    options = ClaudeAgentOptions(
        model=args.model,
        cwd=str(work),
        allowed_tools=["Read", "Write", "Bash", "Glob"],
        permission_mode="bypassPermissions",
        env=env,
    )

    print("=" * 72)
    print(f"MODEL: {args.model}   WORK: {work}")
    print(f"email: {len(email_text.splitlines())} lines, {len(all_lyrics)} of them lyrics")
    print("=" * 72)

    t0 = time.monotonic()
    tools: list[str] = []

    async def run() -> None:
        async for m in query(
            prompt=PROMPT.format(email=email_path, libdir=libdir, outfile=out_path),
            options=options,
        ):
            if isinstance(m, AssistantMessage):
                for b in m.content:
                    if isinstance(b, ToolUseBlock):
                        tools.append(b.name)
                        print(f"  TOOL {b.name}")
                    elif isinstance(b, TextBlock) and b.text.strip():
                        print(f"  TEXT {b.text.strip()[:160]}")

    try:
        anyio.run(run)
    except BaseException as e:  # noqa: BLE001
        print(f"EXCEPTION: {type(e).__name__}: {str(e)[:300]}")

    print("-" * 72)
    print(f"elapsed: {time.monotonic() - t0:.1f}s   tools: {len(tools)}")

    fails: list[str] = []

    # --- CHECK 1: under-redaction -----------------------------------------
    if not out_path.exists():
        fails.append("redacted file was never written")
        redacted = ""
    else:
        redacted = out_path.read_text()
        leaked = [l for l in all_lyrics if l in redacted]
        print(f"CHECK 1 under-redaction : {len(leaked)} lyric line(s) leaked")
        for l in leaked[:5]:
            print(f"    LEAKED: {l!r}")
        if leaked:
            fails.append(f"{len(leaked)} lyric lines survived redaction")

    # --- CHECK 2: over-redaction ------------------------------------------
    if redacted:
        lost = [p for p in PROSE + DECOYS if p not in redacted]
        print(f"CHECK 2 over-redaction  : {len(lost)} prose line(s) lost")
        for p in lost[:5]:
            print(f"    LOST: {p!r}")
        if lost:
            fails.append(f"{len(lost)} prose lines destroyed")

    # --- CHECK 3: hallucination in the library ----------------------------
    src_set = {l.strip() for l in email_text.splitlines() if l.strip()}
    written = sorted(libdir.glob("*.md"))
    print(f"CHECK 3 library files   : {[f.name for f in written]}")
    total, bad = 0, []
    for f in written:
        for ln in f.read_text().splitlines():
            s = ln.strip()
            if not s or s.startswith(("#", "---")) or re.match(r"^\w+:\s", s):
                continue
            total += 1
            if s not in src_set:
                bad.append((f.name, s))
    print(f"        lyric lines written: {total}, NOT verbatim from email: {len(bad)}")
    for n, s in bad[:5]:
        print(f"    HALLUCINATED in {n}: {s!r}")
    if bad:
        fails.append(f"{len(bad)} library lines not verbatim from the email")

    # --- CHECK 4: title-only song must not be fabricated ------------------
    fabricated = [f.name for f in written if "elijah" in f.name.lower()]
    print(f"CHECK 4 title-only song : {'FABRICATED ' + str(fabricated) if fabricated else 'correctly skipped'}")
    if fabricated:
        fails.append("fabricated lyrics for a song only mentioned by name")

    print("=" * 72)
    print("VERDICT: PASS" if not fails else "VERDICT: FAIL")
    for f in fails:
        print(f"  - {f}")
    print(f"artifacts: {work}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
