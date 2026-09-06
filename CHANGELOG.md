# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- The outcome vocabulary and the exit map, before any engine exists to muddy
  them. `Outcome` is `sliced` / `refused` / `incomplete` / `error`, mapped to
  the org contract's settled `0` / `1` / `2` / `4`, with `64` for usage.
  `exit_code_for` is an exhaustive `match` ending in `assert_never`, so adding
  an outcome without an exit code is a **type error** rather than a runtime
  surprise — a dict with a default would hand a new outcome a plausible number.
- `KeyStatus` and the outcome each status forces, plus the precedence rule:
  `refused` outranks `incomplete`, so a finding survives a partial inability to
  look.
- A CLI carrying the one thing worth carrying before there are verbs: argparse's
  usage exit is remapped from `2` to `64`, because `2` means *could not tell*
  and a typo is not an indeterminate result. Measured against a real process,
  not asserted against the constant — two sibling members declare `64` and
  return `2`.
- `render`, whose first token is always the outcome word.
- `empty` at exit **3**, for a run that completed and verified nothing because
  nothing was requested. A `slice.toml` with preset names and no overrides is the
  first file anyone writes, and under the previous table it exited `0` having
  checked zero keys. It is not `sliced`, because that sentence would be untrue of
  the run; it is not `refused`, because nothing was dishonoured. The artifact is
  still promoted and no lock is written. Same code partspec uses for the same
  idea. See D24.

- The repository, its contract, and the research that produced them. No verb is
  implemented: `docs/DECISIONS.md` carries D1–D23, `docs/RESEARCH.md` separates
  what was empirically established from what was refuted and what remains
  unverified, and `notes/` holds the frozen dossier those decisions cite.
- A public-surface test asserting `slicelab` exports only `__version__`, so the
  org's "the stable surface is never the Python API" rule has a mechanism rather
  than an intention.

[Unreleased]: https://github.com/heibench/slicelab/compare/HEAD...HEAD
