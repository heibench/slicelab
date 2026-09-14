"""D20's second clause: what the engine left behind is recorded, not just swept.

> Every engine runs in a slicelab-owned scratch CWD, and stray files are recorded.
>
> Sweeping is the fix; recording `engine_run.stray_files` is the honesty. **Cleaning
> up and hiding evidence are the same action without the field.**

#23 implemented the first clause and #25 recorded that the second had nothing behind
it: the scratch directory was created, handed to the engine, and deleted with whatever
was in it unexamined and unreported.

Driven by a **stand-in process**, not an engine. The guarantee is about slicelab's
bookkeeping rather than about any slicer, so it has to hold on a runner with no slicer
installed -- and an engine-backed version of this test would skip exactly where the
recording is least likely to have been checked by hand.
"""

from __future__ import annotations

import hashlib
import sys

import pytest

from slicelab.engine.launch import run


def _writer(*names: str) -> list[str]:
    """Argv for a process that drops the named files in its working directory."""
    script = "import pathlib\n" + "".join(
        f"pathlib.Path({name!r}).write_text({name!r} * 3)\n" for name in names
    )
    return [sys.executable, "-c", script]


def test_a_file_the_process_left_behind_is_reported() -> None:
    completed = run(_writer("result.json"), timeout=60.0)
    assert completed.exit_status == 0
    assert [s.name for s in completed.stray_files] == ["result.json"]

    left = completed.stray_files[0]
    assert left.size == len("result.json") * 3
    assert left.digest == hashlib.sha256(b"result.json" * 3).hexdigest()


def test_it_is_recorded_on_a_run_that_SUCCEEDED() -> None:
    """The half #25 named explicitly: `slicelab which orcaslicer` litters at exit 0.

    A record populated only on failure would miss every ordinary run, which is most
    of them, and the litter that matters most is the litter nobody went looking for.
    """
    completed = run(_writer("quiet.log"), timeout=60.0)
    assert completed.exit_status == 0
    assert [s.name for s in completed.stray_files] == ["quiet.log"]


def test_a_run_that_left_nothing_is_distinguishable_from_one_nobody_looked_at() -> None:
    """Empty is a real answer here, and it is the answer for a clean engine."""
    completed = run([sys.executable, "-c", "pass"], timeout=60.0)
    assert completed.stray_files == ()


def test_files_in_subdirectories_are_reported_too() -> None:
    """An engine that makes a directory is still an engine that left something.

    `rglob`, not `iterdir`: OrcaSlicer's `--export-slicedata` writes a directory, and
    a top-level listing would report the run clean over a tree of files.
    """
    script = (
        "import pathlib\n"
        "d = pathlib.Path('cache/inner'); d.mkdir(parents=True)\n"
        "(d / 'deep.bin').write_bytes(b'x' * 7)\n"
    )
    completed = run([sys.executable, "-c", script], timeout=60.0)
    by_name = {s.name: s for s in completed.stray_files}
    assert by_name["cache/inner/deep.bin"].size == 7

    # The directories are recorded too, at size -1. An engine that made a directory
    # left something, and an inventory that lists only the leaves cannot say whether
    # the tree was the engine's or slicelab's.
    assert sorted(by_name) == ["cache", "cache/inner", "cache/inner/deep.bin"]
    assert by_name["cache"].size == -1
    assert by_name["cache"].digest == ""


def test_the_caller_who_owns_the_directory_is_not_inventoried(tmp_path) -> None:
    """A directory slicelab did not create is not slicelab's to list.

    The slice verb passes its own directory precisely so it can read what the engine
    wrote; inventorying it here would duplicate that and imply slicelab swept a
    directory it never touches.
    """
    completed = run(_writer("theirs.txt"), cwd=tmp_path, timeout=60.0)
    assert completed.stray_files == ()
    assert (tmp_path / "theirs.txt").is_file()


def test_a_symlink_is_not_followed_out_of_the_scratch_directory(tmp_path) -> None:
    """Its target's size and digest are not the engine's to be attributed.

    `is_file()` follows links, so a link the engine left pointing at `/etc/hostname`
    was recorded with that file's size and digest as though the engine had written it.
    An inventory is evidence; evidence about the wrong file is worse than none.
    """
    outside = tmp_path / "outside.txt"
    outside.write_text("not the engine's", encoding="utf-8")
    script = f"import os; os.symlink({str(outside)!r}, 'pointer')"
    completed = run([sys.executable, "-c", script], timeout=60.0)

    assert [s.name for s in completed.stray_files] == ["pointer"]
    left = completed.stray_files[0]
    assert left.size == -1, "the link was followed and its target measured"
    assert left.digest == ""
    assert outside.read_text(encoding="utf-8") == "not the engine's"


def test_something_that_is_not_a_regular_file_is_recorded_rather_than_swept() -> None:
    """A FIFO would block a reader, and skipping it reported the directory clean."""
    script = "import os; os.mkfifo('pipe')"
    completed = run([sys.executable, "-c", script], timeout=60.0)
    if completed.exit_status != 0:  # pragma: no cover - no mkfifo on this platform
        pytest.skip("this platform has no mkfifo")
    assert [s.name for s in completed.stray_files] == ["pipe"]
    assert completed.stray_files[0].size == -1


def test_a_captured_file_is_read_and_an_uncaptured_one_is_only_hashed() -> None:
    """`text` is `None` for everything the caller did not name, and that is the point.

    The digest is streamed, so a stray file is never read whole unless someone asked
    for it: measured before this, a 256 MiB stray file grew slicelab's own RSS by
    227 MiB on a run that had no interest in it.
    """
    completed = run(_writer("result.json", "big.bin"), capture=("result.json",), timeout=60.0)
    by_name = {s.name: s for s in completed.stray_files}
    assert by_name["result.json"].text == "result.json" * 3
    assert by_name["big.bin"].text is None
    assert by_name["big.bin"].digest, "an uncaptured file is still hashed"
