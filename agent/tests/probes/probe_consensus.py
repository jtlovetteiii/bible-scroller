"""N one-shot calls to the local model, merged by consensus (bs-8qs).

Goes DIRECT to llama.cpp, not through UniClaudeProxy — the proxy drops
chat_template_kwargs (so reasoning cannot be disabled) and drops llama.cpp's
separate reasoning_content field (so a truncated call looks like an empty answer).
See specs/lyric-ingestion.md §4.

Run from agent/:
  uv run python -u tests/probes/probe_consensus.py
  uv run python -u tests/probes/probe_consensus.py -n 5 -k 1 --sweep
  LOCAL_LLM_BASE_URL=http://host:8080 uv run python -u tests/probes/probe_consensus.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(REPO_ROOT / ".env")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lyric_consensus import consensus  # noqa: E402
from lyric_offsets import (  # noqa: E402
    Section,
    Song,
    SpecError,
    build_prompt,
    parse_spec,
    redact,
    render_song,
    repair_spec,
    uniquify_section_names,
    validate_spec,
)
from probe_intermediary import DECOYS, PROSE, build_email  # noqa: E402
import fixture_0726  # noqa: E402

#: Volatile. Tailnet address survives Thomas being away from the LAN; the
#: 192.168.x address does not. Never hardcode either into production.
BASE_URL = os.getenv("LOCAL_LLM_BASE_URL", "http://100.66.185.49:8080")
MODEL = os.getenv("LOCAL_LLM_MODEL", "Bonsai-27B-Q1_0.gguf")


def one_shot(prompt: str, *, timeout: float = 600.0) -> tuple[str, int]:
    """One call, reasoning DISABLED. Returns (text, completion_tokens).

    enable_thinking=False is the only knob that works: it takes the real task from
    159s/7111 tokens to ~6s/~250. reasoning_budget, reasoning_effort and an
    Anthropic-style thinking block all measured as no-ops.
    """
    r = httpx.post(
        f"{BASE_URL.rstrip('/')}/v1/chat/completions",
        json={
            "model": MODEL,
            "max_tokens": 16000,
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=timeout,
    )
    r.raise_for_status()
    d = r.json()
    choice = d["choices"][0]
    msg = choice["message"]
    # A truncated reply is an ERROR, never "no lyrics found" — failing open here
    # would silently disable the whole protection.
    if choice.get("finish_reason") == "length":
        raise RuntimeError("local model hit max_tokens; treat as failure, not as empty")
    return (msg.get("content") or ""), d.get("usage", {}).get("completion_tokens", 0)


#: A "<Song> lyrics:" label the minister wrote above each pasted block. Prose: it
#: names the song but is not a lyric, and swallowing it costs the title.
LABEL_RE = __import__("re").compile(r"lyrics\s*:\s*$", __import__("re").I)


def load_fixture(name: str) -> tuple[str, list[str], list[str], int]:
    """Return (email_text, lyric_lines, prose_lines, expected_caesuras).

    `lyric_lines` and `prose_lines` are GROUND TRUTH, used only for scoring. Production
    has neither — the whole point is that nothing downstream knows which is which.
    """
    if name == "synthetic":
        email_text, all_lyrics = build_email()
        return email_text, all_lyrics, list(PROSE + DECOYS), 3

    if name == "0726":
        email_text = fixture_0726.minister_lyrics()
        lines = email_text.splitlines()
        # Ground truth by rule, not by hand: the minister's reply is one prose line
        # followed by six labelled lyric blocks. Prose is line 1 plus the six labels;
        # every other non-blank line is a pasted lyric.
        prose = [lines[0]] + [l for l in lines[1:] if LABEL_RE.search(l)]
        assert len(prose) == 7, f"expected 1 prose + 6 labels, got {len(prose)}"
        prose_set = set(prose)
        lyrics = [l for l in lines[1:] if l.strip() and l not in prose_set]
        return email_text, lyrics, prose, 0

    raise SystemExit(f"unknown fixture {name!r}")


def merged(specs, email_text, *, line_threshold, song_threshold):
    """Consensus, then the SAME de-confliction each individual spec already went through.

    consensus() votes on each song's lines independently, so two songs can come out
    of the vote claiming the same line even though no single spec did — and the
    result then fails validate_spec. Measured on the real 7/26 email: the merged
    `how-firm-a-foundation` swallowed the whole of `All Hail King Jesus`, because one
    spec had run its range long and the union kept it.

    repair_spec is union-preserving, so re-running it here cannot leak; it only
    decides which song owns a contested line.
    """
    rep = consensus(specs, email_text, line_threshold=line_threshold,
                    song_threshold=song_threshold)
    rep.songs, repairs = repair_spec(rep.songs, email_text)
    repairs += uniquify_section_names(rep.songs)
    validate_spec(rep.songs, email_text)  # the merged spec must be as valid as its parts
    return rep, repairs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--runs", type=int, default=7)
    ap.add_argument("-k", "--line-threshold", type=int, default=1)
    ap.add_argument("--song-threshold", type=int, default=1)
    ap.add_argument("--sweep", action="store_true", help="report every K, not just -k")
    ap.add_argument("--fixture", choices=["synthetic", "0726"], default="synthetic",
                    help="'0726' is the REAL email that blocked in production")
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="write the redacted thread and songs/*.md here (for the §7.1 gate)")
    ap.add_argument("--no-repair", action="store_true",
                    help="reject specs outright instead of repairing them (the old behaviour)")
    ap.add_argument("--save-specs", type=Path, default=None,
                    help="cache the accepted specs as JSON")
    ap.add_argument("--load-specs", type=Path, default=None,
                    help="re-score cached specs offline instead of calling the model")
    args = ap.parse_args()

    email_text, all_lyrics, prose_lines, n_caesura = load_fixture(args.fixture)
    prompt = build_prompt(email_text)
    lines = email_text.splitlines()

    print("=" * 72)
    print(f"{BASE_URL}  model={MODEL}")
    print(f"fixture={args.fixture}  N={args.runs}  K={args.line_threshold}  "
          f"email={len(lines)} lines ({len(set(all_lyrics))} distinct lyric lines)")
    print("=" * 72)

    specs: list[list[Song]] = []  # noqa: F821 — Song imported transitively
    n_repaired = 0

    if args.load_specs:
        raw = json.loads(args.load_specs.read_text())
        specs = [
            [
                Song(slug=s["slug"], title=s["title"],
                     sections=[Section(**sec) for sec in s["sections"]])
                for s in spec
            ]
            for spec in raw
        ]
        print(f"loaded {len(specs)} cached specs from {args.load_specs} (no model calls)")

    t0 = time.monotonic()
    for i in range(0 if not args.load_specs else args.runs, args.runs):
        try:
            raw, tok = one_shot(prompt)
            spec = parse_spec(raw)
            note = ""
            if not args.no_repair:
                spec, repairs = repair_spec(spec, email_text)
                if repairs:
                    n_repaired += 1
                    note = f"  repaired({len(repairs)}): {repairs[0]}"
            validate_spec(spec, email_text)
            specs.append(spec)
            print(f"  run {i + 1}: ok   tok={tok:5}  songs={len(spec)}{note}")
        except (SpecError, RuntimeError, httpx.HTTPError) as exc:
            print(f"  run {i + 1}: REJECTED  {type(exc).__name__}: {str(exc)[:90]}")
    elapsed = time.monotonic() - t0
    if not args.load_specs:
        print(f"\n{args.runs} calls in {elapsed:.1f}s ({elapsed / args.runs:.1f}s each), "
              f"{len(specs)} usable ({n_repaired} needed repair)")

    if args.save_specs and specs:
        args.save_specs.parent.mkdir(parents=True, exist_ok=True)
        args.save_specs.write_text(json.dumps(
            [[{"slug": s.slug, "title": s.title,
               "sections": [vars(sec) for sec in s.sections]} for s in spec]
             for spec in specs], indent=1))
        print(f"cached {len(specs)} specs to {args.save_specs}")

    if not specs:
        print("VERDICT: FAIL — no usable spec. Fail CLOSED; do not proceed unredacted.")
        return 0

    # Ground truth, for scoring only. Production has none of this.
    lyric_set = set(all_lyrics)
    prose_set = set(prose_lines)
    truth = {i for i, l in enumerate(lines, 1) if l.strip() and l in lyric_set}
    prose_idx = {i for i, l in enumerate(lines, 1) if l in prose_set}
    # A line that is PART prose and PART lyric: line granularity cannot express it
    # (spec §4.4), so it is scored separately rather than counted as either.
    mixed = {
        i for i, l in enumerate(lines, 1)
        if i not in truth and i not in prose_idx
        and any(x and x in l for x in lyric_set)
    }
    src = set(lines)

    ks = range(1, len(specs) + 1) if args.sweep else [args.line_threshold]
    for k in ks:
        rep, _ = merged(specs, email_text, line_threshold=k,
                        song_threshold=args.song_threshold)
        claimed = {i for s in rep.songs for sec in s.sections
                   for i in range(sec.start, sec.end + 1)}
        red = redact(rep.songs, email_text)
        # Line-exact, not substring: redact() removes whole lines, so an exact match
        # is what a leak looks like, and substring matching invents false positives
        # on short repeated lines like "(2x)".
        red_lines = set(red.splitlines())
        leaked = sorted(l for l in lyric_set if l in red_lines)
        lost = [p for p in prose_lines if p not in red_lines]
        tot = 0
        nonverbatim: list[str] = []
        for s in rep.songs:
            for ln in render_song(s, email_text).split("---", 2)[-1].splitlines():
                if ln.strip() and not ln.startswith("##"):
                    tot += 1
                    if ln not in src:
                        nonverbatim.append(ln)
        bad = len(nonverbatim)
        caes = sum(
            1 for s in rep.songs
            for ln in render_song(s, email_text).splitlines()
            if "|" in ln and not ln.startswith("#")
        )
        print(
            f"  K>={k}: claimed={len(claimed):3} "
            f"prose_destroyed={len(claimed & prose_idx):2} mixed_taken={len(claimed & mixed)} "
            f"leaked={len(leaked):2} lost_prose={len(lost)} "
            f"verbatim={tot - bad}/{tot} caesura={caes}/{n_caesura} "
            f"songs={len(rep.songs)}"
        )
        if leaked:
            print(f"        LEAKED: {leaked[:4]}")
        if nonverbatim:
            print(f"        NOT VERBATIM: {nonverbatim[:4]}")
        if lost:
            print(f"        lost prose: {[p[:60] for p in lost]}")

    rep, repairs = merged(specs, email_text, line_threshold=args.line_threshold,
                          song_threshold=args.song_threshold)
    if repairs:
        print(f"\nmerge repairs ({len(repairs)}): " + "; ".join(str(r) for r in repairs[:4]))
    print(f"\ntitles @K={args.line_threshold}: {[s.title for s in rep.songs]}")
    print(f"title votes: {rep.title_votes}")
    if rep.below_threshold:
        print(f"dropped below threshold (near-misses): {rep.below_threshold}")

    if args.out_dir:
        out = args.out_dir
        (out / "songs").mkdir(parents=True, exist_ok=True)
        for s in rep.songs:
            (out / "songs" / f"{s.slug}.md").write_text(
                render_song(s, email_text), encoding="utf-8"
            )
        (out / "redacted.txt").write_text(redact(rep.songs, email_text), encoding="utf-8")
        (out / "raw.txt").write_text(email_text, encoding="utf-8")
        print(f"\nwrote {len(rep.songs)} songs + redacted.txt + raw.txt to {out}")
    return 0


if __name__ == "__main__":
    from lyric_offsets import Song  # noqa: F401,E402  — for the annotation above

    sys.exit(main())
