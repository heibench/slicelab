# Evidence

Reproductions, tagged. Cited by tag from `docs/DECISIONS.md` and `AGENTS.md`.

Observed **2026-09-06** on one x86_64 Debian 13 host.
`P` = `flatpak run --command=prusa-slicer --filesystem=$S com.prusa3d.PrusaSlicer`,
`O` = `flatpak run --command=orca-slicer com.orcaslicer.OrcaSlicer`,
`$S` = a scratch directory, `cube.stl` = a generated 20 mm ASCII-STL cube.

---

## V1 — Silent coercion: exit 0, zero diagnostic

```console
$ $P --export-gcode $S/cube.stl -o $S/v1.gcode --save $S/v1.ini --perimeters 4.7
rc=0   stdout=555B   stderr=0B
$ grep '^perimeters = ' $S/v1.ini
perimeters = 4
```

The request and the result differ, and nothing says so. **This is the defect the
whole project exists to catch.**

## V2 — Silent key drop from a `--load`ed ini: exit 0, zero diagnostic

```console
$ cp $S/v1.ini $S/v2in.ini && echo 'not_a_real_key = 42' >> $S/v2in.ini
$ $P --export-gcode $S/cube.stl -o $S/v2.gcode --load $S/v2in.ini --save $S/v2.ini
rc=0   stderr=0B
$ grep -c not_a_real_key $S/v2.ini
0
```

## V3 — `--config-compatibility=disable` does NOT catch V2

```console
$ $P --export-gcode ... --load $S/v2in.ini --config-compatibility=disable
rc=0   stderr=0B
```

It converts an unknown *value* into exit 1. It is blind to an unknown *key*. It
also does not exist on OrcaSlicer, so it can never be the family-wide answer.

## V4 — `--save` is not evidence a slice happened

```console
$ $P --export-gcode $S/cube.stl -o $S/v4.gcode --save $S/v4.ini --scale 30
rc=0
stderr: All objects are outside of the print volume.
$ ls $S/v4.gcode
ls: cannot access: No such file or directory
$ wc -c $S/v4.ini
9957 $S/v4.ini
```

Exit 0, no G-code, and a complete config written anyway. `--save` executes before
the slice block and is not conditioned on it.

## V5 — The discovery verbs exit 1 on complete success

```console
$ $P --query-printer-models > $S/q.json
rc=1   stdout=6550B   stderr=0B
$ python3 -c "import json;print(list(json.load(open('$S/q.json'))))"
['printer_models']
```

The same exit code is returned for "that printer profile was not found". The exit
code carries no information for these verbs.

## V6 — A partial preset triple is a deterministic SIGSEGV with no diagnostic

```console
$ $P --export-gcode $S/cube.stl -o $S/v6.gcode \
    --printer-profile "Original Prusa i3 MK3S & MK3S+"
rc=139   stdout=0B   stderr=0B
```

6/6 runs, every action including `--info`. All six proper non-empty subsets of the
three profile flags do this. The byte-identical signature was also reproduced from
`--duplicate-grid` with a fully valid triple, so **the observation carries no
cause** and must never be attributed to the user's preset names.

Passing *none* of the three is worse: accepted at exit 0, yielding generic Slic3r
built-ins (`layer_height 0.3`, `gcode_flavor reprap`, empty `printer_model`).

## V7 — Binary G-code is the stock default for the current Prusa line

```console
$ # MK4IS triple, no --binary-gcode override
$ head -c 4 $S/v7.gcode
GCDE
$ grep -ac prusaslicer_config $S/v7.gcode
0

$ # MK3S triple
$ head -c 4 $S/v7_mk3.gcode
; ge
$ # footer keys: 375
```

The config-footer half of any artifact-derived lock exists **only** for
MK3S-class ASCII output.

## V8 — Determinism is per-option, not per-engine

Three runs each, hashed as `tail -n +2 | sha256sum`:

```
default              -> 1 distinct normalized hash
--fuzzy-skin all     -> 3 distinct normalized hashes
                        ; filament used [mm] = 1503.18 / 1502.93 / 1503.59
```

Material and time estimates move with the hash, so the lock's *summary* fields are
poisoned too, not just the hash. Cause, read from source: `FuzzySkin.cpp` in 2.9.6
seeds an unseeded `thread_local std::mt19937` from `std::random_device`.

## V9 — `--key=value` works for every option type found, with one boundary class

`rc=0` for all of:

```
--perimeters=4                    --layer-height=0.15
--fill-density=60%                --fill-pattern=gyroid
--binary-gcode=0                  --bed-shape=0x0,250x0,250x210,0x210
--thumbnails=160x120/PNG          --start-gcode=G28
--first-layer-height=0.25         --nozzle-diameter=0.6
--z-offset=-0.15                  --nozzle-diameter=0.4,0.6
--filament-type=PLA;PETG          --wiping-volumes-matrix=0,140,140,0
```

The space form is the trap:

```console
$ $P --binary-gcode 0 --save $S/b.ini
rc=1   No such file: 0
```

**Boundary class:** an *empty* value is not expressible. `--post-process=`,
`--filament-notes=` and `--bed-custom-texture=` all give
`rc=1  No value supplied for --X`.

## V10 — Launch-form exit fidelity differs per package and must be probed

```console
$ flatpak run                       com.prusa3d.PrusaSlicer  --definitely-not-an-option
rc=0
$ flatpak run --command=prusa-slicer com.prusa3d.PrusaSlicer --definitely-not-an-option
rc=1
$ flatpak run                       com.orcaslicer.OrcaSlicer --definitely-not-an-option
rc=254
$ flatpak run --command=orca-slicer com.orcaslicer.OrcaSlicer --definitely-not-an-option
rc=254
```

Cause, from the packaged scripts: PrusaSlicer's entrypoint ends
`$(/app/bin/set-dark-theme-variant.py) &` — a backgrounded child, so the wrapper
always returns 0. OrcaSlicer's is `export LC_NUMERIC=C` + `exec`.

So the `--command=` bypass is **mandatory** for PrusaSlicer and **harmful** for
OrcaSlicer, which discards the packager's numeric-locale workaround.

## V11 — OrcaSlicer can be read back, at exit 0, from stock non-Bambu profiles with no synthesis

```console
$ $O --datadir $S/odata \
    --load-settings "$PR/Creality/machine/Creality K2 Plus 0.4 nozzle.json;\
$PR/Creality/process/0.16mm Optimal @Creality K2 Plus 0.4 nozzle.json" \
    --load-filaments "$PR/Creality/filament/Creality Generic PLA @K2-all.json" \
    --export-settings $S/orca.json --slice 0 --outputdir $S/oout $S/cube.stl
rc=0
plate_1.gcode  263527 B
result.json    {"return_code": 0, "error_string": "Success."}
orca.json      626 keys, incl. printer_settings_id, wall_loops = 2, version = "2.4.2"
```

**This is the fact that makes the readback seam real rather than a PrusaSlicer
trick:** two engines, two mechanisms (a 376-key ini vs a 626-key JSON), one
question.

1944 of 2333 non-BBL instantiable process profiles carry their own
`compatible_printers` and need no synthesis.

## V12 — Orca honours and reflects CLI overrides, and is loud about unknown ones

```console
$ $O ... --wall-loops 5 --export-settings $S/orca.json
rc=0     orca.json: wall_loops = 5
$ $O ... --wall-loopz 9
rc=254   Invalid option --wall-loopz
```

Unlike PrusaSlicer's ini path [V2], Orca's *override* path is loud.

## V13 — Orca's litter and `result.json` are conditional; its failures are branchable

```console
$ # success with --outputdir       -> no CWD litter
$ # failure                        -> 00000.log written into the process CWD
$ # stock MK4S + 0.20mm SPEED @MK4S
rc=239   result.json: return_code -17
         "The selected printer is not compatible with the process preset in the 3mf."
$ # with a non-existent --outputdir
rc=205   no result.json anywhere
```

Never infer from the shell status; never assume the artifact exists; always create
and verify the output directory first.

## V14 — Org state, verified locally

```console
$ # adjudications.html: A1-A4, all resolved  -> slicelab's candidate is A5, not A4
$ partspec   --bogus-flag ; echo $?   -> 64
$ netspec    --bogus-flag ; echo $?   -> 2
$ gerberdiff --bogus-flag ; echo $?   -> 2
$ orlab which   # with no jar         -> 1
```

netspec and gerberdiff both declare `EXIT_USAGE = 64` and return argparse's 2,
leaking a usage error into "could not tell". `orlab which` returns the verify
members' *violated* code for what org section 2.2 defines as an environment fault.

The org contract's section 6.2 (line 218) lists only `0/1/4`; section 6.3
(line 234) lists `0/1/2/4/64`. **Cite 6.3. Never 6.2.**

## V15 — PrusaSlicer 2.9.6 exits 0 and produces nothing when the config carries a post-process script

Found while checking V9. It prints an interactive prompt to **stdout** and reads
stdin — headless, in CI.

```console
$ $P --export-gcode $S/cube.stl -o $S/D.gcode --post-process=/bin/true </dev/null
rc=0
$S/D.gcode: does not exist
stderr: 0 bytes
stdout: "A post-processing script has been detected in the config data:
         > /bin/true  Continue(Y/N) ?"

$ echo Y | $P ... --post-process=/bin/true    -> rc=0, 133504-byte G-code
$ echo N | $P ... --post-process=/bin/true    -> rc=0, no file
$ $P ... --save $S/B.ini --post-process=/bin/true  -> rc=0, no ini either
```

**It is reachable from data, not only from a flag.** An ini containing
`post_process = /bin/true` fed via `--load` reproduces it exactly: rc=0, no
artifact, 0 bytes stderr. No flag in `--help` suppresses it.

Consequences: it is a second independent reason D7's artifact gate is
non-negotiable, and it invalidates any unqualified claim that `--save` always
writes.

**This is a candidate external case for <https://heibench.com/silence.html> and an
upstream bug report. Neither has been filed.** Confirm against a native
(non-Flatpak) build first — Flatpak-only is not established.
