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
- `slicelab which` — discovery, launch-form fidelity, and engine identity. It
  reports which engine build slicelab would talk to, how it would launch it, and
  **whether that engine's exit status can be believed**. Exit 0 requires both an
  engine and a launch form proved to report failure as failure; an installed
  engine that cannot be driven honestly is exit 4, not 0.
- `slicelab presets` — enumerate an engine's printer presets, adjudicated on the
  **artifact and not the exit code**. PrusaSlicer returns exit 1 on complete
  success, the same code it returns for "not found", so branching on it would
  treat every successful query as an error. Exit 0 requires JSON that parsed, is
  shaped as promised, and is **not empty**: a datadir with the bundle but no
  models answers `{"printer_models": ""}`, which parses and enumerates nothing.
  An engine with no enumeration verb — OrcaSlicer 2.4.2 has none — is exit 2,
  because slicelab presenting its own reading of the engine's profile
  directories as the engine's answer would be a plausible substitute for one the
  engine never gave.
- The engine boundary: `subprocess` is confined to `slicelab/engine/launch.py`
  and engine identifiers to `slicelab/adapters/`, both enforced by tests. The
  second has a red state only because a second engine exists.
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
