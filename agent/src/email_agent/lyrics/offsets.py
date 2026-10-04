"""Deterministic half of the lyric-extraction design (bs-8qs).

NO NETWORK, NO MODEL. Pure functions, so every guarantee here is testable without
spending a token. A model's only contribution is a SPEC of line ranges; everything
that touches lyric bytes happens in this file.

Why it is shaped this way — see bs-8qs. When Bonsai was asked to rewrite the email
itself it appended the reference line and forgot to delete the lyric block, leaking
18 lines. Here, extraction and deletion are the SAME operation over the SAME ranges,
so "extracted but not removed" is not a reachable state.

If this design is adopted, promote this module to src/email_agent/ and pin it with
golden tests, exactly as scripts/build-deck.js is pinned by tests/build-deck.test.js.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

#: What replaces a lyric block in the text handed to the frontier model.
REFERENCE_TMPL = '[LYRICS: "{title}" saved to songs/{slug}.md — sections: {sections}]'


class SpecError(ValueError):
    """The model's spec is unusable. Fail closed; never apply a partial spec."""


@dataclass
class Section:
    name: str
    start: int  # 1-based, inclusive
    end: int    # 1-based, inclusive


@dataclass
class Song:
    slug: str
    title: str
    sections: list[Section] = field(default_factory=list)

    @property
    def first_line(self) -> int:
        return min(s.start for s in self.sections)


def number_lines(text: str) -> str:
    """Prefix each line with its 1-based index.

    The model is bad at counting but fine at reading a number off the page. This is
    the difference between a spec that lands on stanza boundaries and one that is
    off by three.
    """
    return "\n".join(f"{i:04d}| {ln}" for i, ln in enumerate(text.splitlines(), 1))


PROMPT = """\
You are a preprocessing step for a church slide-building system. Below is an email
from a minister, with every line numbered. Some of it is song lyrics the minister
pasted in. The rest is ordinary prose: greetings, instructions, notes about who is
singing what.

Identify every song whose LYRICS ARE ACTUALLY PRESENT in the email, and report the
line ranges those lyrics occupy.

Reply with JSON and NOTHING else. No explanation, no markdown fence, no preamble.
The JSON must have this exact shape:

{{"songs": [
  {{"slug": "way-maker",
    "title": "Way Maker",
    "sections": [
      {{"name": "Verse 1", "start": 12, "end": 15}},
      {{"name": "Chorus",  "start": 17, "end": 20}}
    ]}}
]}}

Rules:
- `start` and `end` are the NUMBERS SHOWN AT THE START OF EACH LINE, inclusive.
  Read them off the page. Do not count lines yourself.
- `end` is the number on the LAST LINE THAT STILL HAS LYRIC TEXT ON IT. It is not the
  blank line after the stanza, and it is NEVER a line belonging to the next song. If
  the next song's heading is on line 75, the previous song cannot end at 75 or later.
- Never let two songs share a line. Ranges must not overlap.
- No line number may be larger than the last line number shown in the email.
- Ranges must cover ONLY lyric lines. Never include a line of prose, an instruction,
  a greeting, or a bare song title in a range.
- `title` is the song's real title. If the email states the title on its own line
  near the lyrics, USE THAT TITLE. Only if no title appears anywhere should you fall
  back to describing the song by its opening line.
- `slug` is the title, lowercased, with spaces replaced by hyphens and punctuation
  removed.
- If a song is only MENTIONED BY NAME and its lyrics are NOT in the email, do not
  include it at all.
- Do not reproduce any lyric text in your reply. Report only numbers and titles.
- If the email contains no lyrics at all, reply exactly: {{"songs": []}}

EMAIL:
{email}
"""


def build_prompt(email_text: str) -> str:
    return PROMPT.format(email=number_lines(email_text))


def parse_spec(raw: str) -> list[Song]:
    """Pull the JSON object out of a model reply and shape it.

    Deliberately tolerant about WRAPPING (small models add fences and preambles) and
    completely intolerant about CONTENT — a malformed spec raises rather than being
    partially applied.
    """
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    if not text.startswith("{"):
        brace = text.find("{")
        if brace == -1:
            raise SpecError(f"no JSON object in reply: {raw[:200]!r}")
        text = text[brace:]
    # Trim anything trailing the final closing brace.
    depth, cut = 0, None
    for i, ch in enumerate(text):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                cut = i + 1
                break
    if cut:
        text = text[:cut]

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SpecError(f"reply is not valid JSON: {exc}") from exc

    if not isinstance(data, dict) or "songs" not in data:
        raise SpecError("spec has no 'songs' key")

    songs: list[Song] = []
    for raw_song in data["songs"]:
        try:
            sections = [
                Section(name=str(s["name"]), start=int(s["start"]), end=int(s["end"]))
                for s in raw_song["sections"]
            ]
            songs.append(
                Song(slug=str(raw_song["slug"]), title=str(raw_song["title"]), sections=sections)
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SpecError(f"malformed song entry {raw_song!r}: {exc}") from exc
    return songs


def validate_spec(songs: list[Song], email_text: str) -> None:
    """Reject anything we would not want applied. Raises SpecError."""
    lines = email_text.splitlines()
    n = len(lines)
    claimed: dict[int, str] = {}

    for song in songs:
        if not SLUG_RE.match(song.slug):
            raise SpecError(f"slug {song.slug!r} is not a clean slug")
        if not song.title.strip():
            raise SpecError(f"song {song.slug!r} has an empty title")
        if not song.sections:
            raise SpecError(f"song {song.slug!r} has no sections")
        for sec in song.sections:
            if sec.start < 1 or sec.end > n:
                raise SpecError(
                    f"{song.slug}/{sec.name}: range {sec.start}-{sec.end} outside 1-{n}"
                )
            if sec.start > sec.end:
                raise SpecError(f"{song.slug}/{sec.name}: start {sec.start} > end {sec.end}")
            body = [lines[i - 1] for i in range(sec.start, sec.end + 1)]
            if not any(ln.strip() for ln in body):
                raise SpecError(f"{song.slug}/{sec.name}: range is entirely blank")
            for i in range(sec.start, sec.end + 1):
                if i in claimed:
                    raise SpecError(
                        f"line {i} claimed by both {claimed[i]} and {song.slug}/{sec.name}"
                    )
                claimed[i] = f"{song.slug}/{sec.name}"


@dataclass
class Repair:
    kind: str  # "clamp" | "truncate" | "drop-contained" | "drop-empty"
    detail: str

    def __str__(self) -> str:  # pragma: no cover - logging sugar
        return f"{self.kind}: {self.detail}"


def repair_spec(songs: list[Song], email_text: str) -> tuple[list[Song], list[Repair]]:
    """Fix the two mechanical errors the local model makes, instead of binning the spec.

    Measured on the real 7/26 email (bs-2pn): 7/7 runs were rejected by validate_spec,
    every one of them for the SAME thing — the `end` of a song's last section ran long,
    either into the next song's first line or past the end of the email. The songs,
    the titles and the bulk of the ranges were right every time. Rejecting the whole
    spec threw away almost all of the signal and made the pipeline fail closed on the
    one email it was built for.

    THE SAFETY INVARIANT, and why these repairs are allowed:

        the set of claimed LINES is never reduced.

    A repair may only change WHICH song owns a line, never whether it is owned. That
    matters because a claimed line is both extracted and redacted (§4.1) — so no repair
    here can turn into a leak, which is the one error direction the design refuses to
    take. Mis-attribution costs a line in the wrong song file and is visible; a leak
    kills the run.

    Repairs are returned, not swallowed. They are evidence about the model and belong
    in the log.
    """
    n = len(email_text.splitlines())
    repairs: list[Repair] = []

    # --- 1. bring every range inside the document ----------------------------
    flat: list[tuple[Song, Section]] = []
    for song in songs:
        for sec in song.sections:
            if sec.start > n:
                repairs.append(Repair("drop-empty", f"{song.slug}/{sec.name} starts at {sec.start} > {n} lines"))
                continue
            if sec.start < 1:
                repairs.append(Repair("clamp", f"{song.slug}/{sec.name} start {sec.start} -> 1"))
                sec.start = 1
            if sec.end > n:
                repairs.append(Repair("clamp", f"{song.slug}/{sec.name} end {sec.end} -> {n}"))
                sec.end = n
            if sec.start > sec.end:
                repairs.append(Repair("drop-empty", f"{song.slug}/{sec.name} start {sec.start} > end {sec.end}"))
                continue
            flat.append((song, sec))

    # --- 2. resolve overlaps in favour of the LATER-starting section ---------
    # A contested line is nearly always the first line of the next song, which the
    # previous song's range overran. The section that STARTS there is the one that
    # actually owns it. Sorting by (start, end) also means that when two sections
    # share a start, the longer one survives — again, never shrinking the union.
    flat.sort(key=lambda pair: (pair[1].start, pair[1].end))
    kept: list[tuple[Song, Section]] = []
    for song, sec in flat:
        if kept:
            prev_song, prev = kept[-1]
            if sec.start <= prev.end:
                if sec.end <= prev.end:
                    # Wholly inside the previous range: dropping it claims nothing
                    # less, since `prev` already covers every one of its lines.
                    repairs.append(Repair(
                        "drop-contained",
                        f"{song.slug}/{sec.name} {sec.start}-{sec.end} inside "
                        f"{prev_song.slug}/{prev.name} {prev.start}-{prev.end}",
                    ))
                    continue
                repairs.append(Repair(
                    "truncate",
                    f"{prev_song.slug}/{prev.name} end {prev.end} -> {sec.start - 1} "
                    f"(overlapped {song.slug}/{sec.name} starting {sec.start})",
                ))
                prev.end = sec.start - 1
                if prev.start > prev.end:
                    # Only reachable when the two shared a start, so `sec` is a
                    # superset of `prev` and the union is still intact.
                    repairs.append(Repair(
                        "drop-empty", f"{prev_song.slug}/{prev.name} emptied by truncation"
                    ))
                    kept.pop()
        kept.append((song, sec))

    # --- 3. drop sections that truncation left holding nothing but blanks ----
    # validate_spec rejects an all-blank range, and a blank line carries no lyric, so
    # this cannot leak. The invariant above is therefore exactly: no NON-BLANK claimed
    # line is ever given up.
    lines = email_text.splitlines()
    surviving: list[tuple[Song, Section]] = []
    for song, sec in kept:
        if any(lines[i - 1].strip() for i in range(sec.start, sec.end + 1)):
            surviving.append((song, sec))
        else:
            repairs.append(Repair(
                "drop-empty", f"{song.slug}/{sec.name} {sec.start}-{sec.end} is all blank"
            ))
    kept = surviving

    # --- 4. rebuild the songs from the surviving sections --------------------
    by_song: dict[int, list[Section]] = {}
    for song, sec in kept:
        by_song.setdefault(id(song), []).append(sec)
    out: list[Song] = []
    for song in songs:
        secs = by_song.get(id(song), [])
        if not secs:
            repairs.append(Repair("drop-empty", f"{song.slug} has no surviving sections"))
            continue
        out.append(Song(slug=song.slug, title=song.title,
                        sections=sorted(secs, key=lambda s: s.start)))
    return out, repairs


def uniquify_section_names(songs: list[Song]) -> list[Repair]:
    """Make every `## Section` heading unique within its song. Mutates in place.

    songs/*.md requires it: schemas/deck.schema.json says a deck's `sections` is an
    "ordered list of `## Section` headings to project, repeats and all" and "every
    name must exist in the song file". So repeats are expressed by NAMING a section
    twice in the deck, and a file with two `## Chorus` headings is ambiguous about
    which one a deck means.

    Duplicates are RENAMED, never dropped. Dropping would be the obvious move — a
    repeated chorus is the same text twice — but `redact()` walks these same sections
    to decide what to delete from the email, so a dropped section is a lyric block
    that never gets removed. That is precisely the leak this design exists to prevent.
    Renaming keeps extraction and deletion over one identical range set (§4.1).
    """
    repairs: list[Repair] = []
    for song in songs:
        seen: dict[str, int] = {}
        for sec in sorted(song.sections, key=lambda s: s.start):
            base = sec.name
            if base not in seen:
                seen[base] = 1
                continue
            seen[base] += 1
            # Parenthesised, because the names being disambiguated often already end
            # in a number: a second "Verse 2" became "Verse 2 2", which the frontier
            # model read as a typo and "fixed" to "Verse 3" — inventing a verse that
            # is not in the email. "Verse 2 (2)" cannot be misread that way.
            sec.name = f"{base} ({seen[base]})"
            repairs.append(Repair(
                "rename", f"{song.slug}: duplicate '{base}' at line {sec.start} -> '{sec.name}'"
            ))
    return repairs


def render_song(song: Song, email_text: str) -> str:
    """Build songs/<slug>.md by SLICING the email. No text is regenerated."""
    lines = email_text.splitlines()
    out = [
        "---",
        f"title: {song.title}",
        "public_domain: false",
        # The agent did not verify these against the church's CCLI copy; saying so
        # is what keeps a wrong lyric off a screen. See gen_service on `verified`.
        "verified: false",
        "source: pasted into the service email by the minister",
        "---",
        "",
    ]
    for sec in sorted(song.sections, key=lambda s: s.start):
        out.append(f"## {sec.name}")
        out.extend(lines[sec.start - 1 : sec.end])
        out.append("")
    # Drop trailing BLANK LINES only. A blanket .rstrip() also eats trailing spaces
    # off the last lyric line, and several lines in the real 7/26 email have them
    # ("(2x) ", "Just beyond the river. ") — which breaks the verbatim guarantee for
    # whichever line happens to land last in the file.
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out) + "\n"


def redact(songs: list[Song], email_text: str) -> str:
    """Remove every claimed range and drop a reference line in its place.

    Same ranges as render_song, walked once. Extraction and deletion cannot disagree.
    """
    lines = email_text.splitlines()
    drop: dict[int, Song | None] = {}
    for song in songs:
        anchor = song.first_line
        for sec in song.sections:
            for i in range(sec.start, sec.end + 1):
                drop[i] = song if i == anchor else None

    out: list[str] = []
    for i, ln in enumerate(lines, 1):
        if i in drop:
            song = drop[i]
            if song is not None:
                out.append(
                    REFERENCE_TMPL.format(
                        title=song.title,
                        slug=song.slug,
                        sections=", ".join(s.name for s in sorted(song.sections, key=lambda s: s.start)),
                    )
                )
            continue
        out.append(ln)
    return "\n".join(out)
