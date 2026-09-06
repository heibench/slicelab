# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- The repository, its contract, and the research that produced them. No verb is
  implemented: `docs/DECISIONS.md` carries D1–D23, `docs/RESEARCH.md` separates
  what was empirically established from what was refuted and what remains
  unverified, and `notes/` holds the frozen dossier those decisions cite.
- A public-surface test asserting `slicelab` exports only `__version__`, so the
  org's "the stable surface is never the Python API" rule has a mechanism rather
  than an intention.

[Unreleased]: https://github.com/heibench/slicelab/compare/HEAD...HEAD
