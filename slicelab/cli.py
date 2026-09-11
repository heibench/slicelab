"""The command line, and the only place a process exit code is chosen.

Two verbs exist: ``which`` and ``presets``. This module is the single point at
which slicelab's vocabulary becomes a process status, so there is one place to
be wrong rather than seven.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from slicelab import __version__
from slicelab.adapters import REGISTRY, spec_for
from slicelab.engine.characterise import CharacterisationError
from slicelab.engine.discover import discover
from slicelab.engine.identity import identify
from slicelab.engine.launch import run
from slicelab.intent import IntentError, IntentUnreadable
from slicelab.preflight import PreflightError
from slicelab.presets import adjudicate
from slicelab.redact import RedactionError
from slicelab.report import render
from slicelab.resolve import ResolveError, resolve
from slicelab.status import EXIT_USAGE, Outcome, exit_code_for

__all__ = ["main"]

_DESCRIPTION = """\
Drive a Slic3r-descended slicer and record exactly what it resolved.

`which` reports which engine build slicelab would talk to, how it would launch
it, and whether that engine's exit status can be believed. `presets` enumerates
an engine's printer presets. Nothing slices yet. See docs/DECISIONS.md and the
issue tracker.
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

    presets = verbs.add_parser(
        "presets",
        help="list the printer presets an engine knows about, as JSON on stdout",
    )
    presets.add_argument("engine", choices=sorted(REGISTRY))
    presets.add_argument(
        "--datadir",
        help="engine configuration directory to query instead of the default",
    )

    resolve_verb = verbs.add_parser(
        "resolve",
        help="ask the engine what it would resolve this intent to, and diff that against it",
    )
    resolve_verb.add_argument("intent", type=Path, help="path to a slice.toml")
    resolve_verb.add_argument(
        "--readback",
        type=Path,
        help="where to write the engine's configuration dump (default: alongside the intent)",
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

    if args.verb == "presets":
        return _presets(args.engine, args.datadir)

    if args.verb == "resolve":
        return _resolve(args.intent, args.readback)

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


def _presets(engine: str, datadir: str | None) -> int:
    """Enumerate an engine's printer presets, adjudicated on the artifact.

    Exit 0 requires JSON that parsed, is shaped as promised, and is **not
    empty**. The engine's own exit code is not an input: PrusaSlicer returns 1
    on complete success, the same code it returns for "not found"
    (``notes/evidence.md`` V5, D17).

    An engine with no enumeration verb is exit 2 -- slicelab could not tell you
    what presets exist. It is not exit 1: nothing about the request was wrong,
    and it is not exit 0 with an empty list, which would report our ignorance as
    the engine's inventory.
    """
    spec = spec_for(engine)
    if spec is None:  # pragma: no cover - argparse constrains the choices
        print(render(Outcome.ERROR, f"unknown engine {engine!r}"), file=sys.stderr)
        return exit_code_for(Outcome.ERROR)

    query = spec.preset_query
    if query is None:
        print(
            render(
                Outcome.INCOMPLETE,
                f"{engine} has no preset-enumeration verb",
                [
                    "slicelab will not present its own reading of the engine's "
                    "profile directories as the engine's answer",
                    "reason = engine_has_no_preset_query",
                ],
            ),
            file=sys.stderr,
        )
        return exit_code_for(Outcome.INCOMPLETE)

    found = discover(spec)
    if found.form is None:
        print(
            render(Outcome.ERROR, f"{engine}: {found.fidelity.value}", [found.reason]),
            file=sys.stderr,
        )
        return exit_code_for(Outcome.ERROR)

    argv = [*found.form.argv_prefix, *query.argv]
    if datadir is not None:
        # `is not None`, not truthiness. `--datadir ''` is a request slicelab
        # cannot honour; dropping the flag made the engine answer from its
        # DEFAULT datadir and slicelab print that inventory at exit 0, as
        # though it were the answer to what was asked. Passing the empty string
        # through lets the engine refuse it, which is a reason, not a silence.
        #
        # Absolute, always. `run` gives the engine a scratch working directory
        # rather than the user's, so a relative --datadir would otherwise
        # resolve somewhere neither of them meant.
        resolved = str(Path(datadir).expanduser().resolve()) if datadir else datadir
        argv += ["--datadir", resolved]
    completed = run(argv)

    verdict = adjudicate(completed.stdout, query.root_key)
    if not verdict.ok:
        detail = [
            verdict.reason,
            f"engine exit status was {completed.exit_status}, which carries no "
            "information for this verb (discovery_exit_code_uninformative = true)",
        ]
        if completed.stderr.strip():
            detail.append(f"engine stderr: {completed.stderr.strip().splitlines()[0][:160]}")
        print(
            render(Outcome.INCOMPLETE, f"{engine}: {verdict.verdict.value}", detail),
            file=sys.stderr,
        )
        return exit_code_for(Outcome.INCOMPLETE)

    json.dump({query.root_key: verdict.entries}, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _resolve(intent_path: Path, readback: Path | None) -> int:
    """Ask the engine what it would resolve, and adjudicate the answer.

    The exit codes are the whole point, so they are listed rather than inferred:

    * **0** `sliced` -- every authored override came back as written.
    * **1** `refused` -- slicelab established the intent cannot be honoured. The
      intent file was not understood, or slicelab declined to compose the argv
      (D15), or the engine denies an option exists.
    * **2** `incomplete` -- slicelab ran and cannot stand behind the answer. An
      override came back changed with no cause established (D27), or a key could
      not be adjudicated.
    * **3** `empty` -- the run verified nothing because nothing was requested. The
      configuration was still dumped and kept (D24).
    * **4** `error` -- an environment fault. Not a verdict on the intent.

    **The first run against a build is slow**, because the option-to-key map is
    measured by probing and there is no derivable shortcut (`notes/critique.md` G2,
    D30). It is cached per engine and version afterwards.
    """
    destination = readback or intent_path.with_suffix(".readback.ini")
    try:
        resolved = resolve(intent_path, destination)
    except (IntentError, PreflightError) as refusal:
        print(render(Outcome.REFUSED, str(refusal)), file=sys.stderr)
        return exit_code_for(Outcome.REFUSED)
    except (ResolveError, RedactionError, CharacterisationError, IntentUnreadable) as fault:
        print(render(Outcome.ERROR, str(fault)), file=sys.stderr)
        return exit_code_for(Outcome.ERROR)

    outcome = resolved.outcome
    detail = [f"{v.option}: {v.status.value} -- {v.reason}" for v in resolved.adjudication.verdicts]
    detail.append(f"readback written to {resolved.sidecar}")
    if resolved.readback.keys:
        detail.append(f"redacted {', '.join(resolved.readback.keys)}")

    summary = f"{resolved.adjudication.keys_checked} override(s) checked"
    stream = sys.stdout if outcome is Outcome.SLICED else sys.stderr
    print(render(outcome, summary, detail), file=stream)
    return exit_code_for(outcome)
