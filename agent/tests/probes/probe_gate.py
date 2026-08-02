"""THE GATE (specs/lyric-ingestion.md §7.1 / §7.2, bs-2pn).

The one experiment that can invalidate the whole lyric-ingestion design, and the
reason it should be run before a line of tools.py is touched.

    REDACTED ARM (§7.1) — the design's core assumption, never yet tested.
        Give cloud Sonnet the 7/26 thread with every lyric line sliced out and
        replaced by a `[LYRICS: ...]` reference, with the six songs already sitting
        in songs/. The model still sees the TITLES of six copyrighted songs and still
        has to reason about a service built from them. If the content filter triggers
        on that much, then zero leaked lyric lines does not buy safety and the design
        is wrong regardless of how good the extraction is.

    RAW ARM (§7.2) — nearly free, run alongside.
        Same thread, unredacted. This is the shape that killed 2026-07-26 in
        production. If it 400s we finally have a reproduction, which is a regression
        test we have never had. It may well NOT reproduce — the synthetic cloud arm
        of probe_filter.py passed — and a negative result is informative, not a
        blocker.

Costs two real agent runs on the subscription-billed cloud model. Nothing is emailed:
send_reply is the eval harness's stand-in, which only records the body.

Run from agent/ (build the redacted input first):

    LOCAL_LLM_BASE_URL=http://<host>:8080 uv run python -u tests/probes/probe_consensus.py \
        --fixture 0726 -n 7 --out-dir /tmp/gate
    uv run python -u tests/probes/probe_gate.py --in-dir /tmp/gate --arm both
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))

import fixture_0726  # noqa: E402
from eval_harness import _stage, run_gen_service, seed_library  # noqa: E402

TODAY = "2026-07-22"  # the Wednesday before the 7/26 service
DATE = "2026-07-26"


async def run_arm(name: str, flowchart: str, songs_dir: Path | None,
                  dump: Path | None = None) -> dict:
    """One full agent run. Returns what we need to judge the gate."""
    with tempfile.TemporaryDirectory() as tmp:
        ws = _stage(Path(tmp))
        # Strip the library to nothing, then seed only what this arm should start
        # with. The raw arm starts with NO songs (as production did on the day);
        # the redacted arm starts with the six the ingest step already extracted.
        seed_library(ws, keep=set())
        seeded = []
        if songs_dir:
            for f in sorted(songs_dir.glob("*.md")):
                shutil.copy(f, ws / "songs" / f.name)
                seeded.append(f.stem)

        print(f"\n{'=' * 72}\n{name}\n{'=' * 72}")
        print(f"flowchart: {len(flowchart.splitlines())} lines, {len(flowchart)} chars")
        print(f"seeded songs: {seeded or '(none)'}")

        try:
            run = await run_gen_service(ws, flowchart, subject="Slides for Sunday", today=TODAY)
        except Exception as exc:  # noqa: BLE001 — the whole point is to see what it is
            print(f"RUN RAISED: {type(exc).__name__}: {exc}")
            return {"arm": name, "raised": f"{type(exc).__name__}: {exc}",
                    "filtered": "content filtering" in str(exc)}

        err = run.error
        if dump:
            dump.write_text(
                "\n\n---8<--- assistant block ---8<---\n\n".join(run.transcript),
                encoding="utf-8",
            )
            print(f"transcript ({len(run.transcript)} blocks) -> {dump}")
        result = {
            "arm": name,
            "raised": None,
            "filtered": bool(err and "content filtering" in err),
            "error": err,
            "replied": bool(run.replies),
            "built_deck": run.built_a_deck(DATE),
            "songs_after": sorted(f.stem for f in (ws / "songs").glob("*.md")),
        }
        print(f"content-filter error : {err or 'NONE'}")
        print(f"replied              : {result['replied']}")
        print(f"built a deck         : {result['built_deck']}")
        print(f"songs/ after run     : {result['songs_after']}")
        if run.replies:
            print(f"\n--- reply ---\n{run.reply[:1500]}")
        return result


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in-dir", type=Path, required=True,
                    help="output of probe_consensus.py --out-dir (redacted.txt + songs/)")
    ap.add_argument("--arm", action="append",
                    choices=["redacted", "redacted-noseed", "raw"],
                    help="repeatable; default is all three")
    ap.add_argument("--dump-dir", type=Path, default=None,
                    help="write each arm's assistant transcript here")
    args = ap.parse_args()

    redacted = (args.in_dir / "redacted.txt").read_text(encoding="utf-8")
    songs_dir = args.in_dir / "songs"

    # Both arms get the same surrounding thread; only the lyric-bearing final
    # message differs. Otherwise the arms would not be comparable.
    def thread(final_message: str) -> str:
        return (
            f"{fixture_0726.initial_request()}\n\n"
            "--- my earlier reply ---\n\n"
            f"{fixture_0726.agent_first_reply()}\n\n"
            "--- the minister's response ---\n\n"
            f"{final_message}\n"
        )

    arms = args.arm or ["redacted", "redacted-noseed", "raw"]

    def dump_for(slug: str) -> Path | None:
        if not args.dump_dir:
            return None
        args.dump_dir.mkdir(parents=True, exist_ok=True)
        return args.dump_dir / f"{slug}.transcript.txt"

    results = []
    if "redacted" in arms:
        results.append(await run_arm(
            "REDACTED ARM (§7.1) — the gate",
            thread(redacted), songs_dir, dump_for("redacted")))
    if "redacted-noseed" in arms:
        # Same redacted thread, but songs/ is EMPTY. Disambiguates the gate: if the
        # seeded arm is filtered and this one is not, the trigger is the model
        # reading lyrics out of songs/*.md, not the titles in the thread.
        results.append(await run_arm(
            "REDACTED, NO SEEDED SONGS — is songs/*.md the trigger?",
            thread(redacted), None, dump_for("redacted-noseed")))
    if "raw" in arms:
        results.append(await run_arm(
            "RAW ARM (§7.2) — reproduction attempt",
            thread(fixture_0726.minister_lyrics()), None, dump_for("raw")))

    print(f"\n{'=' * 72}\nVERDICT\n{'=' * 72}")
    for r in results:
        state = "CONTENT-FILTERED" if r["filtered"] else ("RAISED" if r["raised"] else "completed")
        print(f"  {r['arm']:44} {state}")
    gate = next((r for r in results if r["arm"].startswith("REDACTED")), None)
    if gate:
        if gate["filtered"]:
            print("\n  GATE FAILED — the redacted thread is filtered too. The design does "
                  "not buy safety; do not implement §5 as written.")
        elif gate["raised"]:
            print("\n  GATE INCONCLUSIVE — the run raised before finishing. Re-run.")
        else:
            print("\n  GATE PASSED — a fully redacted 7/26 thread clears the filter.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
