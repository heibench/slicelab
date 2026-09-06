"""A bogus flag must MEASURE 64, not declare it.

``notes/evidence.md`` V14: netspec and gerberdiff both define
``EXIT_USAGE = 64`` and both return argparse's ``2``. A test asserting the
constant passes in exactly that state. So these run a real process and read its
status.

Both entry points are covered, because the console script and ``python -m``
reach ``main`` by different paths and only one of them was ever going to be
tested by accident.
"""

from __future__ import annotations

import subprocess
import sys

EXPECTED_USAGE = 64


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "slicelab", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_a_bogus_flag_exits_64_not_argparse_2() -> None:
    proc = _run(["--definitely-not-a-flag"])
    assert proc.returncode == EXPECTED_USAGE, (
        f"expected {EXPECTED_USAGE} (EX_USAGE), got {proc.returncode}. "
        "argparse's own 2 means 'could not tell' under the org contract 6.2, "
        "so it must be remapped -- see slicelab/cli.py."
    )


def test_no_verb_is_a_usage_error_not_a_verdict() -> None:
    proc = _run([])
    assert proc.returncode == EXPECTED_USAGE
    assert proc.stdout == "", "a usage error must not write to stdout"


def test_the_outcome_word_leads_stderr_when_there_is_one() -> None:
    """D14's first-token rule, measured on a real invocation."""
    proc = _run([])
    outcome_lines = [
        ln for ln in proc.stderr.splitlines() if ln and not ln.startswith(("usage:", " "))
    ]
    assert outcome_lines, f"expected an outcome line in stderr, got: {proc.stderr!r}"
    assert outcome_lines[0].split(":")[0] == "error"


def test_version_exits_zero() -> None:
    proc = _run(["--version"])
    assert proc.returncode == 0
    assert proc.stdout.startswith("slicelab ")


def test_help_exits_zero() -> None:
    """--help is a successful run, not a usage error."""
    proc = _run(["--help"])
    assert proc.returncode == 0


def test_the_console_script_agrees_with_python_dash_m() -> None:
    """The two entry points must not disagree about the exit contract."""
    module = _run(["--definitely-not-a-flag"])
    script = subprocess.run(
        ["slicelab", "--definitely-not-a-flag"], capture_output=True, text=True, check=False
    )
    assert script.returncode == module.returncode == EXPECTED_USAGE
