"""The command line, and the only place a process exit code is chosen.

No verb is implemented yet. What exists is the exit contract: this module is
the single point at which slicelab's vocabulary becomes a process status, so
that when the verbs arrive there is one place to be wrong rather than seven.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from slicelab import __version__
from slicelab.report import render
from slicelab.status import EXIT_USAGE, Outcome

__all__ = ["main"]

_DESCRIPTION = """\
Drive a Slic3r-descended slicer and record exactly what it resolved.

No verb is implemented yet. This build carries the exit contract and nothing
else; see docs/DECISIONS.md and the issue tracker.
"""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="slicelab",
        description=_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"slicelab {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code.

    argparse exits ``2`` on a usage error, and ``2`` is *could not tell* under
    the org contract's section 6.2 -- so an unremapped argparse reports "I
    could not decide" for "you typed the flag wrong". A consumer branching on
    ``2`` reads a typo as an indeterminate result.

    netspec and gerberdiff both declare ``EXIT_USAGE = 64`` and return ``2``
    (``notes/evidence.md`` V14), which is why the test for this measures a real
    process's status rather than asserting the constant.
    """
    parser = _parser()
    try:
        parser.parse_args(argv)
    except SystemExit as exc:
        # --help and --version raise SystemExit(0); that is a successful run.
        code = exc.code
        if code in (0, None):
            return 0
        return EXIT_USAGE

    # Reaching here means valid arguments naming no verb. That is a usage
    # error, not an environment fault and not a verdict: slicelab was asked
    # nothing it knows how to do.
    parser.print_usage(sys.stderr)
    print(
        render(
            Outcome.ERROR,
            "no verb given, and none is implemented in this build",
            ["see https://github.com/heibench/slicelab/issues for what is coming"],
        ),
        file=sys.stderr,
    )
    return EXIT_USAGE


def _entrypoint() -> int:  # pragma: no cover - thin console-script shim
    return main()


if __name__ == "__main__":  # pragma: no cover - exercised via __main__.py
    raise SystemExit(main())
