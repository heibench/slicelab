# Security Policy

## Supported versions

Nothing is released yet. When there are releases, only the latest is supported.

## Reporting a vulnerability

**Do not open a public issue for security vulnerabilities.**

Report them through
[GitHub private security advisories](https://github.com/heibench/slicelab/security/advisories/new).

Include what you did, what happened, what you expected, and the versions of this
package and of the slicer involved.

## Current attack surface: none

**slicelab implements no verb today.** The package exports `__version__` and
nothing else, spawns no process, reads no file, and parses no input. There is no
runtime attack surface to report against. This section is a status claim and is
part of the gate (org AGENTS.md 2.5): the moment a verb runs, it is false, and
the change that made it run is not finished until this is rewritten.

## Intended posture, once there is code

Stated now so the design is reviewable before it exists, not to describe
behaviour that ships today.

**Arguments will reach an external program.** Values authored in `slice.toml`
become arguments to a slicer. They will be passed as an argv list, never through
a shell. A caller who forwards untrusted input is still choosing what a local
binary is asked to do.

**Configuration is data, and data can execute.** PrusaSlicer honours a
`post_process` key that runs an arbitrary command, and it is reachable from a
`--load`ed config file rather than only from a flag — see `notes/evidence.md`
V15, where it also causes the engine to block on stdin at exit 0 while producing
no artifact. slicelab therefore refuses a resolved configuration carrying a
post-processing script rather than slicing and hoping. An authored `slice.toml`
from an untrusted source must be read as executable input, because the engine
treats it that way.

**Flatpak filesystem grants.** Where the engine is a Flatpak, only the specific
directories slicelab computed from the run's own path set are granted, never
`--filesystem=host`. A caller who passes paths in sensitive locations is granting
the engine access to them.

**Secrets in resolved configuration.** A slicer's exported configuration can
contain print-host credentials in cleartext — `--save` emits `printhost_apikey`
where the G-code footer strips it. slicelab redacts those before anything is
written, and records that it redacted them. A `slice.lock` should still be read
as configuration, not as a public artifact, until you have looked at it.

Vulnerabilities in the slicers themselves belong upstream:
[PrusaSlicer](https://github.com/prusa3d/PrusaSlicer/security),
[OrcaSlicer](https://github.com/SoftFever/OrcaSlicer/security).
