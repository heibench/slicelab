# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.0.1] — 2026-09-06

The name claim. Two verbs work; `0.1.0` remains what issue #12 scopes (D25).

### Fixed

- **Engines no longer run in the directory you invoked slicelab from, nor in
  your home directory** — on any host where a scratch directory can be made
  inside the home directory at all, which is the condition the fallback ladder
  descends through. D20 said every engine runs in a slicelab-owned scratch
  CWD; `run()` defaulted to `cwd=None` and no call site passed one, so the
  decision was recorded and never implemented. Measured: `slicelab which
  orcaslicer` in an empty directory left a 180-byte `result.json` behind **at
  exit 0** — V13 had recorded that litter only for failing runs.

  The first fix used `tempfile`'s default and **moved the problem instead of
  removing it**: a Flatpak sandbox has its own `/tmp`, so a host `/tmp` cwd
  cannot be translated, and `bwrap` silently starts the engine in `$HOME`
  instead. Litter in the directory you were standing in became litter in your
  home directory, which is persistent, global, and unwatched. Scratch now lives
  under `$XDG_CACHE_HOME/slicelab/engine-cwd`, which every Flatpak engine can
  see — verified by writing a file from inside both sandboxes and finding it
  from the host, and pinned by an engine-gated test that watches the working
  directory *and* `$HOME`.

  Two further ways back in, both found by review and both reproduced: falling
  back to `$TMPDIR` on any `OSError` meant one stray file at `~/.cache/slicelab`
  restored the defect **at exit 0** on an otherwise healthy host, and a relative
  `XDG_CACHE_HOME` was resolved against the working directory, so slicelab
  itself created `./mycache/slicelab/engine-cwd` where the user was standing.
  Every fallback is now inside the home directory, relative values are ignored
  as the basedir spec requires, and `_scratch_root` has tests that need no
  engine.
- **`SECURITY.md` said the tool writes nothing.** It was false while the litter
  was landing in the caller's directory, and false again while it was landing in
  `$HOME`. The section now says what is written and where, including slicelab's
  own scratch directory.
- **`result.json` removed from the repository, and added to `.gitignore`.** An
  OrcaSlicer artifact, committed by accident in #17, present for five commits.
  D11 forbids shipping engine-derived bytes and names `test_no_engine_data.py`
  as its pin; that file did not exist and now does. `.gitignore` named
  `00000.log` but not `result.json`, so nothing objected when it arrived.
- **The D11 guards were both narrower than they read.** The packaging half
  inspected the wheel only — and `packages = ["slicelab"]` means the wheel can
  never carry a root-level file, so it was green over a stray it structurally
  could not see. The repository half checked *tracked* files, while an sdist
  takes everything git does not **ignore**: an uncommitted stray ships just as
  surely as a committed one. Both now read what the sdist actually takes, the
  vocabulary includes `.log` for `00000.log`, and the workflow step fails when
  it finds no artifacts rather than passing on an empty glob.
- **`--datadir ''` reported the default datadir's inventory at exit 0.** The
  flag was applied under a truthiness test, so an empty string was dropped
  entirely and the engine answered from its own default — a real answer to a
  question nobody asked. It is now passed through and refused, at exit 2, with
  the engine's reason. A relative path resolves against your directory, not the
  scratch one.

### Changed

- The version has one home: `slicelab/__init__.py`, read by hatchling. It was two
  literals with nothing pinning them together, and the release workflow reads the
  version off the built filename — so a stale `__version__` would have published
  green while `slicelab --version` reported a number that was never released.
- `ci.yml` no longer claims there is deliberately no engine workflow. There is:
  `engine.yml`, on four host shapes.
- Three remaining "nothing is implemented" claims corrected — `slicelab/cli.py`
  twice and `CONTRIBUTING.md` — which AGENTS.md §2.5 treats as code.
- `tests/test_no_engine_data.py` skips loudly outside a git checkout instead of
  failing with a `CalledProcessError` traceback. It ships in the sdist, so a
  distro packager running the suite from the tarball was the one person
  guaranteed to see it fail.

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

[Unreleased]: https://github.com/heibench/slicelab/compare/v0.0.1...HEAD
[0.0.1]: https://github.com/heibench/slicelab/releases/tag/v0.0.1
