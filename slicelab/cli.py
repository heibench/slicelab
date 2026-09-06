"""The command line, and the only place a process exit code is chosen.

One verb exists: ``which``. This module is the single point at which
slicelab's vocabulary becomes a process status, so there is one place to be
wrong rather than seven.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from slicelab import __version__
from slicelab.adapters import REGISTRY, spec_for
from slicelab.engine.discover import discover
from slicelab.engine.identity import identify
from slicelab.report import render
from slicelab.status import EXIT_USAGE, Outcome, exit_code_for

__all__ = ["main"]

_DESCRIPTION = """\
Drive a Slic3r-descended slicer and record exactly what it resolved.

Only `which` is implemented. It reports which engine build slicelab would talk
to, how it would launch it, and whether that engine's exit status can be
believed. See docs/DECISIONS.md and the issue tracker.
"""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="slicelab",
        description=_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"slicelab {__version__}")

    verbs = parser.add_subparsers(dest="verb", metavar="VERB")
    which = verbs.add_parser(
        "which",
        help="report the engine build slicelab would use, and whether its exit code means anything",
    )
    which.add_argument(
        "engine",
        nargs="?",
        choices=sorted(REGISTRY),
        help="engine to look for; omit to report on every engine slicelab knows",
    )
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

    args = parser.parse_args(argv)

    if args.verb == "which":
        return _which(args.engine)

    # Valid arguments naming no verb. A usage error, not an environment fault
    # and not a verdict: slicelab was asked nothing it knows how to do.
    parser.print_usage(sys.stderr)
    print(
        render(Outcome.ERROR, "no verb given", ["try: slicelab which"]),
        file=sys.stderr,
    )
    return EXIT_USAGE


def _which(engine: str | None) -> int:
    """Report the engine build slicelab would use, and whether to believe it.

    Exits 0 only when an engine was found AND a launch form was proved to
    report failure as failure. An engine that is installed but whose exit
    status carries no information is exit 4, not 0: it is an environment that
    cannot be driven honestly (D18).

    ``which`` never exits 1. It adjudicates nothing about a design, so it has
    no finding to report.
    """
    names = [engine] if engine else sorted(REGISTRY)
    worst = 0
    for index, name in enumerate(names):
        if index:
            print()
        spec = spec_for(name)
        if spec is None:  # pragma: no cover - argparse constrains the choices
            print(render(Outcome.ERROR, f"unknown engine {name!r}"), file=sys.stderr)
            worst = max(worst, exit_code_for(Outcome.ERROR))
            continue

        found = discover(spec)
        if found.form is None:
            detail = [found.reason]
            detail += [f"rejected {form.description}: {why}" for form, why in found.rejected]
            print(
                render(Outcome.ERROR, f"{name}: {found.fidelity.value}", detail),
                file=sys.stderr,
            )
            worst = max(worst, exit_code_for(Outcome.ERROR))
            continue

        who = identify(spec, found)
        version = who.version or "version could not be read"
        detail = [
            f"launch = {found.form.description}",
            f"exit_fidelity = {found.fidelity.value} ({found.reason})",
            f"version_exact = {str(who.exact).lower()}",
        ]
        if who.digest:
            detail.append(f"digest = {who.digest[:16]}... ({who.digest_of})")
        detail += [f"rejected {form.description}: {why}" for form, why in found.rejected]
        # NOT render(): `which` adjudicates nothing, so it has no outcome word
        # to lead with. Printing `sliced` for a discovery report would claim a
        # slice that never happened -- the over-claim this project refuses,
        # aimed at our own output. partspec draws the same line: its verbs that
        # answer without deciding do not emit a verdict.
        print("\n".join([f"{name} {version}", *(f"  {line}" for line in detail)]))
    return worst


def _entrypoint() -> int:  # pragma: no cover - thin console-script shim
    return main()


if __name__ == "__main__":  # pragma: no cover - exercised via __main__.py
    raise SystemExit(main())
