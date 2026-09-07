# Security Policy

## Supported versions

Only the latest release is supported. That is `0.0.1`, which claims the name and
implements two verbs; nothing before it was published.

## Reporting a vulnerability

**Do not open a public issue for security vulnerabilities.**

Report them through
[GitHub private security advisories](https://github.com/heibench/slicelab/security/advisories/new).

Include what you did, what happened, what you expected, and the versions of this
package and of the slicer involved.

## Current attack surface

**Two verbs are implemented: `slicelab which` and `slicelab presets`.** Together
they:

- spawn slicer processes, always as an **argv list, never through a shell**, and
  always with `stdin` connected to `/dev/null`
- read files: candidate executables (to digest them), Flatpak deployment
  directories, and — for `presets` — whatever profile bundle the engine reads
  under the `--datadir` you name
- perform **no network access** and read **no configuration file of their own**

**What gets written, and where.** slicelab writes scratch directories under
`~/.cache/slicelab/engine-cwd`, or under `$XDG_CACHE_HOME` when that is set to
an absolute path **inside your home directory** — a value outside it is ignored,
for the reason below, so a host with `XDG_CACHE_HOME=/var/cache/me` still gets
`~/.cache`. One directory is made per engine launch and removed after it; the
two parents are created once and **persist**.

If neither can be created, slicelab tries the home directory itself, and only
if *that* fails does it fall back to `$TMPDIR` — which under a Flatpak means
the engine runs in `$HOME` after all. That last rung is a real degradation
rather than a guarantee, and it is stated here as one. It is reached only when
nothing inside the home directory can hold a directory, and on such a host
Flatpak itself fails first: every attempt to reach it with a working engine
gave exit 4 before slicelab got that far.

The engines it starts write more. OrcaSlicer drops a `result.json` on any run,
including a *successful* `which` probe, and a `00000.log` on a failing one. Both
land in the engine's process working directory, which is why slicelab gives it
one it owns rather than letting it inherit yours.

**The scratch directory cannot be in `/tmp`, and that is a security-relevant
detail rather than a tidiness one.** A Flatpak sandbox has its own `/tmp`, so a
host `/tmp` path cannot be translated into it — and `bwrap` does not refuse the
request, it drops it and starts the engine in `$HOME`. Measured by writing a
file from inside both sandboxes and looking for it from the host: a cwd under
`~/.cache` is honoured and the file appears there; a `/tmp` cwd puts the process
in `/home/cam` instead.

The first attempt at this fix did exactly that — it stopped the litter landing
in the directory you were standing in and started it landing in your home
directory instead, where it persists and where nobody is looking. The second
attempt fell back to `$TMPDIR` on any `OSError`, so a single stray file at
`~/.cache/slicelab` put the whole defect back **at exit 0** on a host that was
otherwise healthy. Every fallback *above the last rung* is now inside the home
directory — the last rung is still `$TMPDIR`, and is described above as the
degradation it is. A relative `XDG_CACHE_HOME` is ignored rather than resolved
against your working directory, which is what the basedir spec requires and
what stopped slicelab creating `./mycache/slicelab/engine-cwd` where you were
standing; a relative `HOME` did the same thing through the other variable,
because `Path.home()` hands back `$HOME` verbatim.

Two more routes in were found after that, both of them *absolute* paths: an
`XDG_CACHE_HOME` outside the home directory, and a symlink inside the home
directory pointing out of it. Neither is exotic — `/var/cache/$USER` is an
ordinary setting — and both put `result.json` back in `$HOME` at exit 0. A
candidate now qualifies only if it is under the home directory **after
resolution**, and the home directory must itself be absolute before it is
resolved, because `Path.home()` hands back `$HOME` verbatim and resolving a
relative one would anchor it to your working directory.

Until 0.0.1 none of this was true. `slicelab which orcaslicer`, run in an empty
directory, left a 180-byte `result.json` behind at exit 0 — and this section
said the tool wrote nothing. An identical file reached this repository that way
and was committed for five commits before anyone noticed.

Neither verb yet reads a `slice.toml`, slices a model, or writes a lock.

The inputs they accept are their own `argv` — including a `--datadir` path,
which is resolved to an absolute path and handed to the engine, never
interpreted by slicelab — and whatever the engines print. Engine output is
decoded with `errors="replace"` and is never evaluated: it is matched against a
version pattern, or parsed as JSON and checked for shape, and printed.

**Processes they will start.** `which` invokes discovered engines with `--help`
and with one flag they are expected to reject. `presets` invokes them with the
adapter's enumeration flag. On a host where an untrusted binary is earlier on
`PATH` than the real slicer, that binary is what gets executed — ordinary `PATH`
semantics, but worth stating for a tool whose job is finding executables.

This section is a status claim and part of the gate (org AGENTS.md 2.5). It has
been rewritten every time one of its own sentences turned out to be false: when
the CLI began parsing arguments; when `which` began launching engines; when a
measurement showed the "writes nothing" sentence had been false since `which`
shipped; when the fix for *that* relocated the problem rather than removing it;
when review found further routes back into it; and when the correction for
**those** was found to have left the same claim standing twenty lines further
down.

There is deliberately no count here any more. This paragraph carried one, and it
kept being the false sentence — including in the commit written to fix a stale
self-referential count. The commit written to remove the counter then replaced
it with a fresh integer ("stale three revisions running") that no command could
settle, which is how a fourth review round came to be spent on arithmetic. An integer that has to be incremented by hand is a
claim like any other, and this one kept being the false one. The causes are the
record; adding a cause is the same action as rewriting the section, which is
what the counter kept failing to be.

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
