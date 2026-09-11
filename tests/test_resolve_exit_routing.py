"""Every exception `resolve` can raise, mapped to the code a consumer branches on.

Run as a real process, because org contract §5 makes the exit status the stable
surface and a test that called `main()` in-process would not establish what a shell
sees. These cases need no engine: each one is decided before the engine is reached,
which is also why they are the cheap half of the routing and had no coverage at all.

The gap this closes is specific. An unrouted exception still *exits* -- CPython
gives 1 for an uncaught traceback -- so a wrong route is invisible to any test that
checks only "it failed". 1 is `refused`, which asserts slicelab looked at the intent
and found it wanting; every case here established nothing of the kind.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

TRIPLE = """[prusaslicer.base]
printer-profile = "Original Prusa i3 MK3S & MK3S+"
print-profile = "0.20mm QUALITY @MK3"
material-profile = "Prusament PLA"
"""


def _resolve(intent: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "slicelab", "resolve", str(intent)],
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_an_intent_file_that_cannot_be_read_is_an_environment_fault(tmp_path: Path) -> None:
    """4, not 1. The distinction the exception split exists to make, at the CLI.

    `IntentUnreadable` is deliberately not an `IntentError`, and `cli._resolve` has
    to catch it in the right clause for that to mean anything. Previously the split
    was asserted only at the exception level -- `not issubclass(...)` -- so dropping
    `IntentUnreadable` from the CLI's ERROR tuple left all 288 tests green while
    `slicelab resolve` answered an unreadable file with a traceback at exit 1.

    Exit 1 here would say slicelab read an intent and found it wanting. It never
    opened the file.
    """
    intent = tmp_path / "slice.toml"
    intent.write_text(TRIPLE, encoding="utf-8")
    intent.chmod(0o000)
    if os.access(intent, os.R_OK):  # pragma: no cover - root ignores the mode bits
        pytest.skip("this user can read a mode-000 file, so unreadable cannot be staged")
    try:
        done = _resolve(intent)
    finally:
        intent.chmod(0o600)

    assert done.returncode == 4, f"rc={done.returncode}\n{done.stdout}{done.stderr}"
    assert done.stderr.startswith("error"), done.stderr
    assert "Traceback" not in done.stderr
    assert "refused" not in done.stderr


def test_an_intent_file_that_is_not_valid_is_a_verdict(tmp_path: Path) -> None:
    """1, and the other half of the same split. Read fine, understood not at all."""
    intent = tmp_path / "slice.toml"
    intent.write_text("this is not TOML at all\x00", encoding="utf-8")
    done = _resolve(intent)
    assert done.returncode == 1, f"rc={done.returncode}\n{done.stdout}{done.stderr}"
    assert done.stderr.startswith("refused"), done.stderr
    assert "Traceback" not in done.stderr


def test_a_missing_intent_file_is_an_environment_fault(tmp_path: Path) -> None:
    done = _resolve(tmp_path / "nothing-here.toml")
    assert done.returncode == 4, f"rc={done.returncode}\n{done.stdout}{done.stderr}"
    assert done.stderr.startswith("error"), done.stderr
    assert "Traceback" not in done.stderr


@pytest.mark.parametrize("argument", [".", "/", "", ".."])
def test_a_path_that_is_not_a_file_is_an_environment_fault(argument: str) -> None:
    """4, and no traceback, for every shape of "that is not an intent file".

    `Path(".").with_suffix(...)` raises `ValueError` -- an empty name -- and the
    call that derives the default readback path sat one line ABOVE the handlers, so
    `slicelab resolve .` was an uncaught traceback at exit 1. Exit 1 is `refused`,
    asserting slicelab read an intent and found it wanting, over a path it never
    opened.

    `..` is in the list because it takes a different route (`with_suffix` succeeds,
    the open fails with `IsADirectoryError`) and reached 4 correctly all along. The
    point of parametrizing is that a consumer cannot tell these apart and neither
    should the exit code.
    """
    done = subprocess.run(
        [sys.executable, "-m", "slicelab", "resolve", argument],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert done.returncode == 4, f"rc={done.returncode}\n{done.stdout}{done.stderr}"
    assert done.stderr.startswith("error"), done.stderr
    assert "Traceback" not in done.stderr
    assert "refused" not in done.stderr


def test_an_unknown_engine_table_is_a_verdict(tmp_path: Path) -> None:
    """1. slicelab read the intent and established it cannot be honoured."""
    intent = tmp_path / "slice.toml"
    intent.write_text('[notaslicer.base]\nx = "y"\n', encoding="utf-8")
    done = _resolve(intent)
    assert done.returncode == 1, f"rc={done.returncode}\n{done.stdout}{done.stderr}"
    assert done.stderr.startswith("refused"), done.stderr
    assert "Traceback" not in done.stderr


def test_a_partial_preset_triple_is_refused_without_touching_the_engine(tmp_path: Path) -> None:
    """1, from pre-flight (D15). V6: the engine's answer to this is a SIGSEGV with
    nothing on either stream, so slicelab declines to compose the argv rather than
    reporting a signal it caused."""
    intent = tmp_path / "slice.toml"
    intent.write_text(
        '[prusaslicer.base]\nprinter-profile = "Original Prusa i3 MK3S & MK3S+"\n',
        encoding="utf-8",
    )
    done = _resolve(intent)
    assert done.returncode == 1, f"rc={done.returncode}\n{done.stdout}{done.stderr}"
    assert done.stderr.startswith("refused"), done.stderr
    assert "Traceback" not in done.stderr


def test_a_plan_that_cannot_be_composed_is_a_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    """`PlanError` -> 1 `refused`, through the exit map rather than by accident.

    In-process, and deliberately so. `PlanError`'s only raise site is "this engine
    declares no way to dump its configuration", and both registered adapters declare
    one -- so there is no `slice.toml` that reaches it and no process-level test that
    can. Left unrouted it escapes as a traceback, which CPython exits 1 for: the
    right number, reached by accident, printing `Traceback` where D14 requires the
    outcome word. The routing is the unit, so the routing is what is exercised.

    If a future adapter makes it reachable, this stays correct and the process-level
    case becomes writable.
    """
    from slicelab import cli
    from slicelab.plan import PlanError

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise PlanError("this engine has no measured way to dump its configuration")

    monkeypatch.setattr(cli, "resolve", refuse)
    code = cli.main(["resolve", "slice.toml"])
    assert code == 1


def test_an_engine_that_answered_with_nothing_to_adjudicate_is_incomplete(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`ResolveIncomplete` -> 2, and the engine's own words survive to the author.

    The engine-backed case is covered against a real PrusaSlicer; this pins the
    mapping itself, which is the half that can be changed without any engine noticing.
    """
    from slicelab import cli
    from slicelab.resolve import ResolveIncomplete

    def unfinished(*_args: object, **_kwargs: object) -> None:
        raise ResolveIncomplete("prusaslicer exited 1: stderr: Unknown option --nope")

    monkeypatch.setattr(cli, "resolve", unfinished)
    code = cli.main(["resolve", "slice.toml"])
    assert code == 2
    assert capsys.readouterr().err.startswith("incomplete")
