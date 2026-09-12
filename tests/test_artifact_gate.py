"""The gates between a run that established nothing and a verdict about the intent.

`resolve` adjudicates the engine's configuration dump. Three conditions mean the
dump on disk is not this run's answer, whatever it contains:

* the engine died on a signal, which carries no cause;
* it did not answer in time, so nothing it wrote is finished;
* it exited non-zero having written something, so what it wrote is not what it
  resolved.

Each of those is one `if` in `_artifact`, and each is the only thing standing
between such a run and `sliced` at exit 0 -- the founding defect of this
organisation. Removing any of the three left the whole 308-test suite green, so
none of them had a red state anybody had observed (org contract 2.4).

These are in-process against a fabricated `Completed`, because the states are not
reachable on demand from a real engine: a timeout means waiting out
`DEFAULT_TIMEOUT_S`, a signal means arranging a crash, and five attempts to make
2.9.6 exit non-zero *having written a dump* all produced no dump at all. A gate
that cannot be provoked is still a gate, and the alternative to fabricating the
state is leaving it untested -- which is what was happening.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from slicelab.adapters import PRUSASLICER
from slicelab.engine.launch import Completed
from slicelab.intent import Intent
from slicelab.resolve import ResolveError, ResolveIncomplete, _artifact

INTENT = Intent(engine="prusaslicer", base={}, overrides={}, source=Path("slice.toml"))

TRIPLE = """[prusaslicer.base]
printer-profile = "Original Prusa i3 MK3S & MK3S+"
print-profile = "0.20mm QUALITY @MK3"
material-profile = "Prusament PLA"
"""


@pytest.fixture
def a_dump(tmp_path: Path) -> Path:
    """A staged file that is present and non-empty -- the case the gates must survive.

    An empty or missing file would be caught by the "wrote no configuration" branch
    instead, and every test here would pass for the wrong reason.
    """
    staged = tmp_path / "readback"
    staged.write_text("perimeters = 4\nlayer_height = 0.2\n", encoding="utf-8")
    return staged


def test_a_dump_beside_a_signalled_engine_is_never_adjudicated(a_dump: Path) -> None:
    """Exit 4. A signal carries no cause, so nothing about the intent was established.

    V6: a partial preset triple is a deterministic SIGSEGV with zero bytes on both
    streams. Pre-flight refuses that particular one before the engine runs, so what
    reaches here is every OTHER crash -- and `--save` executes before the slice
    block, so a dump can be sitting there when it happens.
    """
    completed = Completed(exit_status=None, signal=11, stdout="", stderr="")
    with pytest.raises(ResolveError, match="died on signal 11"):
        _artifact(completed, a_dump, PRUSASLICER, INTENT)


def test_a_dump_beside_a_timed_out_engine_is_never_adjudicated(a_dump: Path) -> None:
    """Exit 4. Plainly reachable: `resolve` runs the engine under a 120 s timeout.

    A dump written by a run that was then killed is a partial file that looks exactly
    like a complete one -- `--save` writes it before the work the engine was still
    doing when the clock ran out.
    """
    completed = Completed(exit_status=None, signal=None, timed_out=True)
    with pytest.raises(ResolveError, match="did not answer in time"):
        _artifact(completed, a_dump, PRUSASLICER, INTENT)


def test_a_dump_beside_a_failed_engine_is_never_adjudicated(a_dump: Path) -> None:
    """Exit 2, and the engine's own words. The file exists AND the run failed.

    `incomplete`, not `error`: the engine started, read the request and said no, so
    nothing in the environment is faulty (D32). Not `sliced`: a dump written by a run
    that then failed is not evidence of what that run resolved, and reading it anyway
    is how the stale-artifact defect returns by another route.

    Defensive rather than demonstrated -- five attempts against 2.9.6 (missing model,
    invalid value, out-of-range value, unknown option, unwritable output) each gave a
    non-zero exit with NO dump, which the branch above this one handles. Stated as
    defensive rather than left looking measured.
    """
    completed = Completed(exit_status=1, stderr="Something went wrong late\n")
    with pytest.raises(ResolveIncomplete, match="having written a configuration"):
        _artifact(completed, a_dump, PRUSASLICER, INTENT)


def test_an_empty_dump_is_not_a_configuration(tmp_path: Path) -> None:
    """The fourth condition in the same function, and the only one left unpinned.

    `wrote_something` is `is_file() and st_size`. Dropping the size half left the
    whole suite green: a zero-byte dump parses to `{}`, so a base-only intent would
    report `empty` (3) and promote an empty file as evidence that is "real". Milder
    than the three gates above -- it cannot reach exit 0 -- and it is the same
    sentence of D7, so it gets the same treatment.
    """
    staged = tmp_path / "readback"
    staged.write_text("", encoding="utf-8")
    with pytest.raises(ResolveIncomplete, match="wrote no configuration"):
        _artifact(Completed(exit_status=0), staged, PRUSASLICER, INTENT)


def test_a_missing_dump_is_not_a_configuration(tmp_path: Path) -> None:
    """The other half. Exit 0 is not evidence the engine wrote anything (V15)."""
    with pytest.raises(ResolveIncomplete, match="wrote no configuration"):
        _artifact(Completed(exit_status=0), tmp_path / "never-written", PRUSASLICER, INTENT)


def test_a_clean_run_reaches_the_dump(a_dump: Path) -> None:
    """The control. Without it every test above passes against an `_artifact` that
    refuses everything, which would be three checks that cannot fail in the other
    direction."""
    assert _artifact(Completed(exit_status=0), a_dump, PRUSASLICER, INTENT) == (
        "perimeters = 4\nlayer_height = 0.2\n"
    )


def test_a_run_that_reached_no_verdict_promotes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D31: "A run that did not reach [adjudication] promotes nothing and leaves the
    previous file untouched."

    The ordering is the whole of it -- `diff` runs, then `_promote`. Swapping them
    left the suite green while a run whose adjudication raised would already have
    replaced the author's readback with one it never stood behind.

    Driven by making `diff` raise, rather than by reading the source: an assertion
    about where two calls sit in a file passes the moment someone reformats and says
    nothing about what the code does.
    """
    from slicelab import resolve as resolve_module
    from slicelab.engine.discover import Discovery, ExitFidelity, LaunchForm, LaunchKind

    destination = tmp_path / "slice.readback.ini"
    previous = "PREVIOUS-RUN-READBACK\n"
    destination.write_text(previous, encoding="utf-8")

    staged_dumps: list[Path] = []

    def engine_wrote_a_dump(argv):
        staged = Path(next(a.split("=", 1)[1] for a in argv if a.startswith("--save=")))
        staged.write_text("perimeters = 4\n", encoding="utf-8")
        staged_dumps.append(staged)
        return Completed(exit_status=0)

    def adjudication_that_raises(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("the adjudication could not be completed")

    # Discovery is stubbed as well as the engine call. Without it this test needed a
    # real PrusaSlicer on the host -- it passed here and reddened every CI leg, which
    # is the "the environment a test runs in is part of the test" rule collecting on
    # a test whose subject is the order of two function calls.
    found = Discovery(
        engine="prusaslicer",
        form=LaunchForm(
            kind=LaunchKind.PATH,
            argv_prefix=["prusa-slicer"],
            description="a stub, for an ordering test",
        ),
        fidelity=ExitFidelity.ESTABLISHED,
        reason="stubbed for an ordering test",
    )
    monkeypatch.setattr(resolve_module, "discover", lambda _spec: found)
    monkeypatch.setattr(resolve_module, "_name_map", lambda _spec, _found: {})
    monkeypatch.setattr(resolve_module, "run", engine_wrote_a_dump)
    monkeypatch.setattr(resolve_module, "argv_for", lambda _form, argv, _paths: argv)
    monkeypatch.setattr(resolve_module, "diff", adjudication_that_raises)

    intent = tmp_path / "slice.toml"
    intent.write_text(TRIPLE, encoding="utf-8")

    with pytest.raises(RuntimeError, match="could not be completed"):
        resolve_module.resolve(intent, destination)

    assert staged_dumps, "the engine was never asked for a dump, so nothing was proved"
    assert destination.read_text(encoding="utf-8") == previous, (
        "a run that reached no verdict overwrote the author's readback (D31)"
    )
