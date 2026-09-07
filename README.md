# slicelab

**A reproducible control plane over the Slic3r-descended slicers.** Declare a
small configuration delta, slice with a real engine, and get back G-code plus a
lock file recording exactly what that engine resolved — or a non-zero exit
saying why slicelab will not stand behind the result.

> **Status: pre-alpha. Two verbs work: `slicelab which` and `slicelab presets`.**
> `which` finds an installed slicer and establishes whether its exit status can be
> believed; `presets` enumerates its printer presets. Nothing slices yet — the `slice.toml` example below is
> what the tool is *for*, not what it currently does. See
> [`docs/DECISIONS.md`](docs/DECISIONS.md) and
> [`docs/RESEARCH.md`](docs/RESEARCH.md).

## The problem

Slicers resolve your configuration silently, and tell you nothing when the answer
differs from what you asked for. Reproduced on PrusaSlicer 2.9.6:

```console
$ prusa-slicer --export-gcode cube.stl -o out.gcode --save out.ini --perimeters 4.7
rc=0   stdout=555B   stderr=0B

$ grep '^perimeters = ' out.ini
perimeters = 4
```

You asked for 4.7. You got 4. The exit code is 0 and stderr is empty. An
unknown key in a `--load`ed config disappears the same way, and
`--config-compatibility=disable` catches neither.

A person eyeballing the preview notices. A script does not glance, and neither
does an agent — so the tool's own honesty is the only thing left holding the
result up.

## What slicelab does about it

Ask the engine what it *actually resolved*, diff that against what was
requested, per key, and refuse to call the run green when they disagree.

```toml
# slice.toml — what you intended
engine     = "prusaslicer"
engine_req = ">=2.9.6,<3"

[geometry] path = "part.stl"
[output]   path = "part.gcode"

[prusaslicer.base]
printer  = "Original Prusa i3 MK3S & MK3S+"
print    = "0.20mm QUALITY @MK3"
filament = "Prusament PLA"

[prusaslicer.set]
perimeters   = 4
fill_density = "60%"
```

```console
$ slicelab slice
refused: 1 requested override was not honoured
  perimeters: requested 4.7, engine resolved 4          [coerced]
  artifact staged at ~/.cache/slicelab/run-8f21/part.gcode
  destination part.gcode NOT written
  fix: set perimeters = 4 in slice.toml
$ echo $?
1
```

The intended git model is four files: `part.stl` (the geometry), `slice.toml`
(what you intended), `slice.lock` (exactly what produced it), `part.gcode` (the
result).

## Install

```console
$ uv tool install slicelab     # or: pipx install slicelab
$ slicelab which
```

Zero runtime dependencies, Python 3.11+. The slicer itself is **not** bundled and
is not a dependency: slicelab drives whatever PrusaSlicer or OrcaSlicer is already
on the machine, across a process boundary, and ships nothing an engine produced
(D11). `slicelab which` tells you what it found and whether it can be driven
honestly; if it finds nothing, that is exit 4 and a reason, not exit 0.

## What works today

```console
$ slicelab which
orcaslicer 2.4.2
  launch = Flatpak com.orcaslicer.OrcaSlicer via its default entrypoint
  exit_fidelity = established (rejected --definitely-not-a-slicelab-option with exit 254)
  version_exact = true

prusaslicer 2.9.6
  launch = Flatpak com.prusa3d.PrusaSlicer via --command=prusa-slicer
  exit_fidelity = established (rejected --definitely-not-a-slicelab-option with exit 1)
  version_exact = true
  rejected Flatpak com.prusa3d.PrusaSlicer via its default entrypoint:
    returned 0 for a flag it does not accept, so its exit status carries no information
```

That last line is why the verb exists. PrusaSlicer's Flathub entrypoint ends in a
backgrounded child, so it returns **0 for every invocation** — including ones that
failed. Anything driving it through that launcher gets a green for every run.
OrcaSlicer's wrapper does not have the problem, and bypassing it would throw away
the packager's locale fix, so the right launcher differs per package and slicelab
measures rather than assumes.

## Exit codes

| | |
|---|---|
| `0` | `sliced` — artifact produced and promoted, every requested key applied |
| `1` | `refused` — slicelab established the intent was not honoured |
| `2` | `incomplete` — slicelab ran but cannot stand behind the result |
| `3` | `empty` — the run completed and verified nothing, because nothing was requested |
| `4` | `error` — environment fault; **not** a verdict on your configuration |
| `64` | usage — slicelab's own argv |

`2` and `4` are the point. A check that could not run must never be reportable
as one that looked and found nothing.

## Scope

slicelab is a **driver**. It puts an engine under program control and is honest
about what it established. It does not adjudicate the emitted G-code — that is a
separate tool that does not exist yet.

**In v0.1.0:** PrusaSlicer >= 2.9.6, and a deliberately narrow readback-only
OrcaSlicer adapter whose job is to prove the mechanism is not PrusaSlicer-shaped.

**Deliberately not in v0.1.0:** any normalized cross-engine setting vocabulary.
`CORE_KEYS` is empty and a test asserts it. Authored keys are the engine's own
native names. You cannot build a PrusaSlicer-shaped abstraction if you decline to
write the abstraction until a second engine has voted on it.

**Not planned:** authoring or design generation, G-code post-processing, machine
control at runtime, and BambuStudio.

## Part of heibench

[heibench](https://github.com/heibench) is a hardware engineering integration
bench: drive the engine, check the result. The org-wide rule every member follows
is that **silence must never read as success**, and the case record for how often
that is violated — including by us — is at <https://heibench.com/silence.html>.

Siblings: [`prusaslicer-py`](https://github.com/heibench/prusaslicer-py) (a
narrow single-engine PrusaSlicer driver, maintained separately),
[`orlab`](https://github.com/heibench/orlab) (OpenRocket),
[`partspec`](https://github.com/heibench/partspec) (CAD-as-code parts),
[`netspec`](https://github.com/heibench/netspec) (PCB connectivity),
[`gerberdiff`](https://github.com/heibench/gerberdiff) (fabrication output).

## Licence

Apache-2.0. The engines are AGPL-3.0 and are reached only across a process
boundary; slicelab ships zero engine-derived bytes. The reasoning is
[D12](docs/DECISIONS.md), carried as a decision with an owner rather than as an
established fact.
