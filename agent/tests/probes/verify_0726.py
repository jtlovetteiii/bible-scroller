"""Check a finished 7/26 run against the acceptance criteria in bs-2pn.

NO NETWORK. Pure inspection of a workspace plus the reply text, so it can be pointed
at a probe_gate run today and reused verbatim by the eval once `ingest_thread` exists.

The criteria are bs-2pn's, not invented here. The one that matters most and is easiest
to fake is VERBATIM: it is checked line by line against the minister's actual email,
not by eyeball and not by counting. Wrong words on a sanctuary screen is the worst
outcome this system can produce, and no amount of green elsewhere excuses it.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fixture_0726  # noqa: E402

CAESURA = "|"


@dataclass
class Result:
    passed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    def check(self, ok: bool, label: str, detail: str = "") -> None:
        (self.passed if ok else self.failed).append(label + (f" — {detail}" if detail and not ok else ""))

    @property
    def ok(self) -> bool:
        return not self.failed

    def report(self) -> str:
        out = [f"{'PASS' if self.ok else 'FAIL'}  ({len(self.passed)} passed, {len(self.failed)} failed)"]
        out += [f"  ok   {p}" for p in self.passed]
        out += [f"  FAIL {f}" for f in self.failed]
        return "\n".join(out)


def _email_lines() -> list[str]:
    return fixture_0726.minister_lyrics().splitlines()


def verify(ws: Path, *, reply: str | None, date: str = "2026-07-26") -> Result:
    r = Result()
    raw = _email_lines()
    raw_set = set(raw)
    # The lines the minister actually pasted, minus his one prose line and the six
    # "<Song> lyrics:" labels.
    labels = {ln for ln in raw if ln.strip().lower().endswith("lyrics:")}
    lyric_lines = {ln.strip() for ln in raw[1:] if ln.strip() and ln not in labels}

    songs_dir = ws / "songs"
    present = sorted(f.stem for f in songs_dir.glob("*.md")) if songs_dir.is_dir() else []

    # --- all six songs exist -------------------------------------------------
    for title in fixture_0726.EXPECTED_SONGS:
        slug_like = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        hit = [p for p in present if p == slug_like or p.replace("-", "") == slug_like.replace("-", "")]
        r.check(bool(hit), f"songs/{slug_like}.md exists", f"have {present}")
    # "No Body" was swapped out in the minister's reply and must NOT be there.
    r.check(not any("body" in p and "no" in p for p in present),
            "'No Body' was not created (the minister swapped it out)", f"have {present}")

    # --- verbatim, line by line ---------------------------------------------
    nonverbatim: list[str] = []
    dupe_headings: list[str] = []
    invented_caesura: list[str] = []
    for f in sorted(songs_dir.glob("*.md")) if songs_dir.is_dir() else []:
        body = f.read_text(encoding="utf-8").split("---", 2)[-1]
        headings = [ln for ln in body.splitlines() if ln.startswith("## ")]
        if len(headings) != len(set(headings)):
            dupe_headings.append(f.name)
        for ln in body.splitlines():
            if not ln.strip() or ln.startswith("##"):
                continue
            if ln in raw_set:
                continue
            # A caesura the model added is legal — but only as a marker inside a line
            # that is otherwise byte-identical to the email.
            if CAESURA in ln:
                stripped = " ".join(p.strip() for p in ln.split(CAESURA) if p.strip())
                if stripped in {x.strip() for x in raw}:
                    continue
                invented_caesura.append(ln)
            else:
                nonverbatim.append(ln)

    r.check(not nonverbatim, "every lyric line is verbatim from the email",
            f"{len(nonverbatim)} not in the email, e.g. {nonverbatim[:3]}")
    r.check(not invented_caesura, "caesuras only mark lines that are otherwise verbatim",
            f"e.g. {invented_caesura[:3]}")
    r.check(not dupe_headings, "no duplicated stanza headings", f"in {dupe_headings}")

    # --- the deck ------------------------------------------------------------
    deck_path = ws / "passages" / date / "service.deck.json"
    r.check(deck_path.exists(), "deck JSON was written")
    if deck_path.exists():
        deck = json.loads(deck_path.read_text())
        blob = json.dumps(deck)
        in_deck = sorted(l for l in lyric_lines if l in blob)
        r.check(not in_deck, "deck JSON contains no lyric text", f"{len(in_deck)}, e.g. {in_deck[:2]}")
    r.check((ws / "passages" / date / "service-preview.html").exists(),
            "the deck was actually BUILT, not just written")

    # --- the reply -----------------------------------------------------------
    if reply is not None:
        named = [t for t in fixture_0726.EXPECTED_SONGS if t.lower() in reply.lower()]
        r.check(len(named) == len(fixture_0726.EXPECTED_SONGS),
                "the reply names all six songs", f"named {len(named)}: {named}")
        quoted = sorted(l for l in lyric_lines if len(l) > 15 and l in reply)
        r.check(not quoted, "the reply quotes no lyrics", f"{len(quoted)}, e.g. {quoted[:2]}")
    return r


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("workspace", type=Path)
    ap.add_argument("--reply", type=Path, default=None)
    args = ap.parse_args()
    reply = args.reply.read_text(encoding="utf-8") if args.reply else None
    res = verify(args.workspace, reply=reply)
    print(res.report())
    return 0 if res.ok else 1


if __name__ == "__main__":
    sys.exit(main())
