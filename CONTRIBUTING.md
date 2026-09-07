# Contributing

## Getting set up

```sh
just setup          # sync the environment
just check          # format check + lint + typecheck
just test           # the suite
```

`just check && just test` is what CI runs. Run it before every commit, and never
bypass hooks.

## Read these first

This repository is still mostly documents. Two verbs are implemented --
`slicelab which` and `slicelab presets` -- and the design was expensive to
arrive at, so the documents remain the larger half.

- [`docs/DECISIONS.md`](docs/DECISIONS.md) — D1–D23. **Do not relitigate a
  numbered decision.** If one is wrong, add a superseding entry saying why.
- [`docs/RESEARCH.md`](docs/RESEARCH.md) — what was established with a command,
  what was refuted, and what is still unverified. Read the third list before
  proposing anything.
- [`notes/`](notes/) — frozen. Do not edit these to match later findings; that
  destroys the record of what was believed when a decision was made.

## The bar for a claim

This project exists because slicers report success they did not establish. The
same standard applies to us.

**Reproduce before reporting.** Inferring a failure mode from reading code is a
guess, and a wrong guess sends the fix in the wrong direction.

**Never state a number you did not produce.** Any figure that reaches a
docstring, a commit message, an issue or a decision carries the command that
produced it. An estimate is fine when labelled as one and misleading when
presented as a measurement.

**A check whose red state you have not observed is not a check.** Break the thing
it checks, watch it go red, put it back. Say in the pull request that you did.

**Clear `__pycache__` before every measurement**, or the observation can lie to
you — in either direction.

Python invalidates a `.pyc` by comparing the source's mtime and size against what
the `.pyc` records, both at one-second granularity. A red-state edit that changes
a single character — `return 3` to `return 0`, flipping a comparison, swapping a
constant — keeps the size **identical**. If the next run lands in the same second,
the stale bytecode is reused and you measure the previous state.

**The dangerous direction is the false green.** Write the broken version, run
within the same second, and the interpreter uses bytecode compiled from the
*good* source: the break appears not to break anything, so you conclude the check
does not cover the case and go looking for a better one. That is
silence-reading-as-success landing inside the procedure we use to prove a check
can fail. It has been reproduced deterministically on this estate.

The false red is the same mechanism reversed: restore the good source inside the
same second and the tree still reports broken. Both directions were observed here,
the green one by a reviewer on a different repository within an hour of the red
one being written up.

What makes it hard to see: `inspect.getsource` shows the **correct** source while
the interpreter runs the **old** bytecode, because `getsource` reads the file and
the interpreter does not. Do not use it to confirm what is executing.

```sh
find . -name __pycache__ -type d -exec rm -rf {} +
```

Run that between every break and every restore, not once at the end.


**A skipped test is not a passing test.** If you add a `skipif` for a missing
tool, make it possible for CI to demand that tool, and never gate a test module
at import — that reports as one skipped line and takes every test in the file
with it.

## Tests and the engine

There is no engine code yet, and therefore no engine workflow in CI — a job that
installed a slicer and ran today's suite would exercise nothing and report green.
It lands with the first verb that talks to an engine, together with
`SLICELAB_REQUIRE_ENGINE=1` so a failed engine install is loud rather than a
silent skip.

If you have PrusaSlicer, OrcaSlicer, SuperSlicer or CuraEngine installed —
especially on macOS or Windows, or as a native package rather than a Flatpak —
that is genuinely useful. Several findings in `notes/evidence.md` are marked
Flatpak-only on one Linux host and need a second observer.

## Conventions

- Conventional Commits: `type(scope): description`, imperative, lowercase, no
  trailing period, subject <= 72 characters.
- One logical change per commit; branch and open a pull request.
- No AI attribution anywhere — no co-author trailers, no generated-with footers,
  no session URLs in a commit message or pull request body.
- The org-wide contract at
  <https://github.com/heibench/.github/blob/main/AGENTS.md> is the floor;
  [`AGENTS.md`](AGENTS.md) in this repository carries what is specific to
  slicelab and wins where they conflict.
