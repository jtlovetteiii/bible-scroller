"""Consensus over N one-shot specs (bs-8qs).

NO NETWORK. Pure functions, like lyric_offsets.py.

WHY THIS EXISTS: a single call to the local model is not reliable. Three identical
think-off calls on the same email leaked 6, 4 and 0 lyric lines, and one run missed
a whole song. But with reasoning disabled a call costs ~6s, so N calls are
affordable, and the runs miss DIFFERENT lines — so unioning their claimed ranges
covers all of them.

Measured on the hostile fixture, 7 calls / 44s / 6 valid specs:

    threshold      claimed   prose destroyed   LYRICS LEAKED
    K>=1 .. K>=4      45            3                0
    K>=5              42            2                2
    K>=6              38            0                4

THE BIAS IS DELIBERATE. The two error directions are not symmetric:
  - over-claiming destroys a prose line -> visible to the minister in the reply,
    correctable, costs one email;
  - under-claiming leaks a lyric -> content-filter 400, the run dies, and it is the
    exact failure this whole design exists to prevent.
So default low (union-ish) and surface the over-claim rather than hiding it.

N and K are CONFIGURABLE ON PURPOSE. They are tuned to the model currently served
at home (a 1-bit quant). A stronger model should need fewer runs; do not bake these
numbers into code.
"""

from __future__ import annotations

import collections
import re
import unicodedata
from dataclasses import dataclass, field

from lyric_offsets import Section, Song

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")


def title_key(title: str) -> str:
    """Cluster key for 'these are the same song'.

    Songs are grouped by TITLE, not by the slug the model emitted. Measured on the
    real 7/26 email: one run of seven typed the slug `james-keep-me-near-the-cross`
    while giving the title as "Jesus, Keep Me Near the Cross". Keyed on slug that
    became a seventh song and a duplicate songs/*.md; keyed on title it merges. The
    same key also folds "How Firm a Foundation" into "How Firm A Foundation".
    """
    t = unicodedata.normalize("NFKD", title).casefold()
    return _WS.sub(" ", _PUNCT.sub(" ", t)).strip()


def slugify(title: str) -> str:
    """Derive the canonical slug from the winning title, so a typo cannot name a file."""
    t = unicodedata.normalize("NFKD", title).casefold()
    t = "".join(c for c in t if not unicodedata.combining(c))
    return _WS.sub("-", _PUNCT.sub(" ", t).strip()) or "untitled"


@dataclass
class ConsensusReport:
    """What the vote decided, and how confident it was. Meant to be logged."""

    songs: list[Song]
    valid_specs: int
    total_specs: int
    #: line -> how many specs claimed it. The audit trail for a disputed line.
    votes: dict[int, int]
    #: Lines claimed by some specs but below the threshold — i.e. deliberately
    #: dropped. Worth logging: these are the near-misses.
    below_threshold: list[int]
    #: title -> vote count, per slug. Surfaces disagreement about what a song IS.
    title_votes: dict[str, dict[str, int]]
    #: Claimed lines a MINORITY of specs agreed on, as (line, votes, total) — the
    #: over-claim candidates, so the reply can say "check these" without quoting the
    #: line, which is what §4.2 asks for and the tool otherwise cannot express.
    #:
    #: MEASURED on the real 7/26 email (5 specs): recall 4/5, precision 4/5. It flags
    #: four of the five swallowed "<Song> lyrics:" labels, misses one, and falsely
    #: flags one genuine lyric ('Singing "Holy", singing "Holy"' — a real line that
    #: only some runs claimed).
    #:
    #: DIAGNOSTIC ONLY. Nothing is dropped on the strength of it, and at 4/5 precision
    #: nothing should be: dropping un-claims a line, which is the leak direction, and
    #: a genuine one-line stanza is indistinguishable from a swallowed label here.
    low_confidence: list[tuple[int, int, int]] = field(default_factory=list)


def _runs(sorted_lines: list[int]) -> list[tuple[int, int]]:
    """Collapse a sorted line list into contiguous (start, end) runs."""
    if not sorted_lines:
        return []
    out: list[tuple[int, int]] = []
    start = prev = sorted_lines[0]
    for n in sorted_lines[1:]:
        if n != prev + 1:
            out.append((start, prev))
            start = n
        prev = n
    out.append((start, prev))
    return out


def consensus(
    specs: list[list[Song]],
    email_text: str,
    *,
    line_threshold: int = 1,
    song_threshold: int = 1,
) -> ConsensusReport:
    """Merge N independently-produced specs into one.

    `line_threshold` — a line is treated as lyric if at least this many specs
    claimed it. 1 is the union: maximally safe against leakage, maximally likely to
    swallow a prose line.

    `song_threshold` — a song must be proposed by at least this many specs to
    survive. Guards against one run inventing a song the others did not see.
    """
    total = len(specs)

    # --- vote on lines, and remember which slug claimed each ------------------
    line_votes: collections.Counter[int] = collections.Counter()
    slug_votes: collections.Counter[str] = collections.Counter()
    lines_by_slug: dict[str, collections.Counter[int]] = collections.defaultdict(
        collections.Counter
    )
    titles_by_slug: dict[str, collections.Counter[str]] = collections.defaultdict(
        collections.Counter
    )
    # Section names keyed by the line they start on, so a merged run can be named
    # from whatever the specs actually called it rather than "Section 1".
    names_at: dict[str, dict[int, collections.Counter[str]]] = collections.defaultdict(
        lambda: collections.defaultdict(collections.Counter)
    )

    for spec in specs:
        seen_keys = {title_key(s.title) for s in spec}
        for key in seen_keys:
            slug_votes[key] += 1
        for song in spec:
            key = title_key(song.title)
            titles_by_slug[key][song.title] += 1
            for sec in song.sections:
                names_at[key][sec.start][sec.name] += 1
                for ln in range(sec.start, sec.end + 1):
                    line_votes[ln] += 1
                    lines_by_slug[key][ln] += 1

    # --- decide WHICH LINES are lyrics, and separately WHO OWNS each one ------
    #
    # These are two different questions and merging them with one rule is what broke
    # on the real 7/26 email.
    #
    #   * "is this line a lyric?" must be biased towards YES — a miss is a leak, and
    #     a leak is the failure this design exists to prevent. So: union, K=1.
    #   * "which song is it part of?" must be the MAJORITY view. Under the union rule
    #     a single run whose range ran long captured everything inside it: one spec
    #     claimed `the-lord-will-provide` as lines 5-106, which contains the whole of
    #     One Day, so One Day's lyrics were filed under The Lord Will Provide.
    #     Majority ownership outvotes that run 4:1.
    #
    # Ownership is decided per line, so no two songs can claim the same line and the
    # merged spec is valid by construction — no repair pass needed for cross-song
    # conflicts.
    eligible = {key for key, v in slug_votes.items() if v >= song_threshold}
    starts_by_key = {
        key: sorted(names_at[key].keys()) for key in eligible
    }

    def owner(line: int) -> str | None:
        best, best_rank = None, None
        for key in eligible:
            votes = lines_by_slug[key].get(line, 0)
            if not votes:
                continue
            # Tie-break towards the song whose section START is closest at or before
            # this line — the same "the later-starting block owns it" intuition that
            # resolves a range running a few lines into the next song.
            preceding = [s for s in starts_by_key[key] if s <= line]
            rank = (votes, max(preceding) if preceding else -1)
            if best_rank is None or rank > best_rank:
                best, best_rank = key, rank
        return best

    # A BLANK line is never claimed, whoever voted for it. Two reasons, and they
    # point the same way: it carries no lyric, so leaving it in the email cannot
    # leak anything; and it is the stanza separator, so claiming it fuses every
    # stanza of a song into one contiguous run. Measured on the real 7/26 email:
    # with blanks claimed, all of Goodness of God came out as a single "Verse 1"
    # covering the whole song; without them the stanzas split where the minister
    # put the breaks.
    blank = {i for i, l in enumerate(email_text.splitlines(), 1) if not l.strip()}

    lines_owned: dict[str, list[int]] = collections.defaultdict(list)
    for ln, total in sorted(line_votes.items()):
        if total < line_threshold or ln in blank:
            continue
        who = owner(ln)
        if who is not None:
            lines_owned[who].append(ln)

    songs: list[Song] = []
    for key, claimed in lines_owned.items():
        sections: list[Section] = []
        for i, (start, end) in enumerate(_runs(sorted(claimed)), 1):
            named = names_at[key].get(start)
            name = named.most_common(1)[0][0] if named else f"Section {i}"
            sections.append(Section(name=name, start=start, end=end))
        title = titles_by_slug[key].most_common(1)[0][0]
        songs.append(Song(slug=slugify(title), title=title, sections=sections))

    songs.sort(key=lambda s: s.first_line)

    below = sorted(ln for ln, c in line_votes.items() if 0 < c < line_threshold)

    # Over-claim candidates: a claimed line that a MINORITY of specs voted for. Scored
    # against the number of specs that saw the owning song, not the total, so a song
    # only two runs found is not judged as if all seven had disagreed about it.
    low: list[tuple[int, int, int]] = []
    for key, owned in lines_owned.items():
        seen = slug_votes[key]
        for ln in owned:
            v = lines_by_slug[key].get(ln, 0)
            if seen > 1 and v * 2 <= seen:
                low.append((ln, v, seen))
    low.sort()
    return ConsensusReport(
        songs=songs,
        valid_specs=total,
        total_specs=total,
        votes=dict(line_votes),
        below_threshold=below,
        title_votes={k: dict(v) for k, v in titles_by_slug.items()},
        low_confidence=low,
    )
