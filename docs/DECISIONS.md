# Decisions

Numbered decisions and the reasoning that produced them. **Do not relitigate a
numbered decision.** If one is wrong, add a superseding entry that says so and
why.

Tags in brackets (`[V1]`, `[G2]`) cite `notes/evidence.md` and
`notes/critique.md`. Every figure here carries the command that produced it, or
is marked unverified.

All measurements are from **2026-09-06**, on PrusaSlicer 2.9.6 (Flatpak
`com.prusa3d.PrusaSlicer`) and OrcaSlicer 2.4.2 (Flatpak
`com.orcaslicer.OrcaSlicer`), on **one x86_64 Debian 13 host**. That last clause
is load-bearing: see D8 and `docs/RESEARCH.md`.

---

## D1 — v0.1.0 drives PrusaSlicer >= 2.9.6 plus a readback-only OrcaSlicer adapter

The seam is: the Adapter protocol, per-adapter exit tables, per-adapter discovery
policy, engine-namespaced intent keys, and `Plan.materialized_inputs`. Everything
else lives under `adapters/<engine>/`.

Orca is in v0 — not v0.2 — for one reason: the vocabulary-boundary test has **no
red state** until a second engine's native names exist to exclude, and the
readback seam is unproven engine-neutral until a JSON-dumping engine sits in the
same slot as an ini-dumping one. Freezing a released lock schema before that vote
is the fatal risk.

*Supersedes:* if the Orca readback adapter cannot be built without engine-specific
logic leaking into `readback.py`, the core has no reason to exist and slicelab
splits into two per-engine tools sharing only the lock schema and the status enum.

## D2 — The core normalized vocabulary is EMPTY in v0.1.0

Authored keys are the engine's own native names under an engine-namespaced table.
`tests/test_vocabulary_empty.py` asserts `CORE_KEYS == frozenset()`. Both landed
with the intent parser (#5).

This sentence has now been wrong in **both** directions, which is why it says so
rather than reading as though it was always right: it was written in the present
tense before either existed, corrected to the future tense in #27, and corrected
back when #29 made it true. A status claim is part of the gate (org contract 2.5),
and that cuts the same way when a change makes one true.

135 of PrusaSlicer's 343 config keys share a *name* with an Orca key, and at least
five of the first dozen adjudicated are traps: `gcode_label_objects` is an enum in
one and a bool in the other; `ensure_vertical_shell_thickness` has disjoint enum
domains; `bed_temperature` has no single Orca counterpart at all — Orca has six
plate-type pairs plus a `curr_bed_type` selector, so guessing `hot_plate_temp` is
the org contract's section 2.3 violation exactly.

A vocabulary written from one engine **is** the PrusaSlicer-shaped abstraction.

*Supersedes:* a key enters only via D3's admission procedure, one entry per key.

## D3 — Vocabulary admission is a recorded procedure, not a CI test

A candidate core key must be measured on every installed engine: slice the same
part, vary the key, show the toolpath effect moves in the same direction and the
same order of magnitude, and commit the measurement table as the decision's
evidence. `len(vocab.CORE_KEYS)` is to be asserted against a committed constant so
growth is visible in review.

It is deliberately **not** a CI test: it needs every engine installed and would be
either skipped or permanently blocking — and a green check that never ran is
exactly what this org exists to prevent (org 2.4).

*Supersedes:* if after 20 real `slice.toml` files fewer than ~20% of authored keys
would be core, delete `vocab.py` rather than grow it, and say plainly that
slicelab is a lock file for slicers.

## D4 — The readback diff is the honesty mechanism; `--config-compatibility` is not

Every authored override is compared against the engine's own resolved output and
recorded as `applied` / `coerced` / `absent`.

Evidence: [V1] coercion at rc=0 with 0 B stderr; [V2] silent key drop at rc=0 with
0 B stderr; [V3] `--config-compatibility=disable` does not catch V2;
[V11]–[V12] the same diff works on OrcaSlicer through a completely different
mechanism (a JSON export rather than an ini; 626 keys against 376 for the profile
triples V11 measured, both counts being profile-dependent).

`--config-compatibility=disable` is still passed to PrusaSlicer and recorded,
explicitly as belt-and-braces: it converts an unknown *value* into exit 1, is
blind to unknown *keys*, and does not exist on Orca.

*Supersedes:* an engine with no config-dump verb gets
`readback_source = "unavailable"` and its outcome is never `sliced`. Do not
reconstruct the resolution.

## D5 — Overrides are emitted as `--key=value` for every type; slicelab ships no option catalogue

Verified for int, float, percent, enum, bool, comma-list, composite and G-code
string [V9], and confirmed under adversarial probing for negatives, vectors,
semicolon lists, multiline G-code and bracket templates. The space form is the
trap: `--binary-gcode 0` gives `No such file: 0`.

Using `=` universally deletes the need for per-key type knowledge, which deletes
the need to vendor or regenerate an AGPL option catalogue (D11).

**Boundary, stated because it was found:** an *empty* value is not expressible —
`--post-process=`, `--filament-notes=` and `--bed-custom-texture=` all give
rc=1 `No value supplied`. "Clear this key" is refused at exit 1 with a named
reason, never a silent no-op. This is a class, not one option.

**Boundary, corrected 2026-09-10 — the sentence above is true and not general.**
Measured on 2.9.6, and the loud case turned out to be the one already handled:

| argv | rc | resolved |
|---|---|---|
| `--notes=` | 1 | `No value supplied` |
| `--notes="   "` | **0** | `notes = ` — cleared, **0 bytes stderr** |
| `--perimeters=banana` | 1 | `Invalid value supplied` |
| `--spiral-vase=banana` | **0** | `spiral_vase = 0` |
| `--spiral-vase=true` | **0** | `spiral_vase = 0` |
| `--spiral-vase=` | **0** | `spiral_vase = 1` |

Two corrections follow. **Whitespace clears a key silently**, so the refusal D5
describes was being reached by the loud route and missed by the quiet one — the
parser now refuses on `not value.strip()`, and `--notes=` was never the dangerous
form. And **boolean options validate nothing at all**: anything that is not
literally `1` resolves to `0`, and an *empty* value resolves to `1` — the opposite
polarity from every other type, which all reject a bad value at rc=1.

So "empty is not expressible" holds for every type **except** booleans, where empty
is not only expressible but means *on*. A driver that emitted a TOML `true` as
`"true"` would set the flag *off* while the author read the file as setting it on,
at exit 0 with nothing on stderr. That is why `intent.py` preserves the authored
type rather than stringifying: the decision belongs to the adapter, which is the
only layer entitled to know that `1` is the engine's word for true.

The readback diff catches all of this after the fact — requested `true`, resolved
`0` is a `coerced` key and cannot be green. Refusing earlier is better, and knowing
which of the two the tool is relying on is better still.

*Supersedes:* if any option class rejects `=`, D5 collapses into needing
engine-derived option metadata, which D11 forbids shipping, and the fallback is
per-key probing during characterisation — a real cost that would reopen whether
`[set]` should exist at all.

## D6 — The lock field is `effective_config`, never "resolved effective settings"

It carries `values_resolved = false`.

Both engines export the resolved *configuration document*, not resolved values.
PrusaSlicer reports `extrusion_width = 0` and `first_layer_extrusion_width = 200%`
while the toolpaths were generated at 0.45 mm and 0.70 mm, and those real numbers
exist only as free-text header comments in a different vocabulary. `infill_overlap`
and `support_material_interface_speed` stay relative even under a preset.

Calling the document "all resolved effective settings" is itself the section 2.3
plausible-substitute failure — one level above the one the lock was built to catch.

## D7 — Capture is gated on the artifact, and the artifact is staged then promoted

`--save` executes before the slice block and is not conditioned on it: [V4] gives
rc=0, no G-code, and a complete 9957-byte ini. [V15] gives rc=0, no ini **and** no
G-code. So `readback_gated_on_artifact = false` can never yield `sliced`.

slicelab slices into a scratch directory and promotes to the destination only on
`sliced`, recording `destination_prehash`. This closes prusaslicer-py D5's stated
hole ("it does not establish that *this run* wrote the file") structurally, rather
than by an mtime check that D5 already measured and rejected — 198 of 200 tmpfs
writes had identical `st_mtime_ns`.

Non-destructive: the destination is never deleted, and the staged path is named in
every non-sliced report.

Slicing runs **from the declared input path**, never a renamed temp copy, because
the basename is embedded in `objects_info` whenever `gcode_label_objects` is
`firmware` or `octoprint` — which Prusa's shipped system presets set.

## D8 — Reproducibility is a measured value, established by a probe, never assumed

`slice` writes `not_established`. `probe` writes `reproducible` /
`nondeterministic` with the observed hash set. A static screen against the build's
measured nondeterministic-setting list answers `known_nondeterministic` for free
before any re-slice. `verify --tier artifact` exits **2** on anything but
`reproducible`.

Evidence: [V8] — `--fuzzy-skin all`, three runs, 3 distinct normalized hashes and
3 distinct filament-used values (1503.18 / 1502.93 / 1503.59 mm). Cause read from
source: `FuzzySkin.cpp` in 2.9.6 seeds an unseeded `thread_local std::mt19937`
from `std::random_device`.

Without this field, a hash mismatch caused by fuzzy skin is indistinguishable from
real drift and `verify` reports *violated* — a false red, which is the silence rule
inverted.

## D9 — `raw_sha256` is the hash of one FILE; `normalized_sha256` carries its substitution count

A substitution count of 0 on a format slicelab claimed to normalize means the
header was not recognised. The hash is then null, an `unknowns` code is added, and
the outcome is `incomplete` — never a silent fallback to hashing raw bytes.

## D10 — The output container is sniffed from the first four bytes

`GCDE` implies `footer_available = false`, `normalized_sha256 = null`, no
artifact-derived reported stats, and `verify --tier artifact` at exit 2 with an
`unknowns` code.

slicelab **never** silently forces `--binary-gcode=0`, because that changes the
artifact the user asked for.

Verified [V7]: an MK4IS triple with no override emits `GCDE` and
`grep -ac prusaslicer_config` returns **0**; the MK3S triple emits ASCII with 375
footer keys. `binary_gcode = 1` is the stock default for the entire current Prusa
line — this is the default path, not an edge case.

## D11 — slicelab ships zero engine-derived bytes

The subprocess argument settles *linking* and says nothing about *copying*.
prusaslicer-py already decided this once (its D8: AGPL help text "becomes
redistribution the moment it is public"), and the engine's `--help` text is
provably copied expression rather than fact — the typo "depending on printer
tochnology" is a literal inside the AGPL binary.

Everything slicelab needs about an engine is generated on the user's machine into
XDG cache and gitignored: the default key set, the nondeterministic-setting list,
the preset catalogue, the option-to-key map (D5, [G2]).

`test_no_engine_data.py` pins this, and it is worth saying **what** it pins,
because the sentence above once claimed more than the file delivered. Three rules,
each answering a different question:

- **By format** — nothing headed for the sdist may carry a suffix an engine writes
  and slicelab authors none of. Catches an engine's *output* landing in the tree,
  which is how a `result.json` once arrived.
- **By content** — no file's whole content may parse as a **characterisation
  document**: a JSON object carrying `schema`, `engine`, `version` and `entries`.
  The container is irrelevant, which is the point — `keys.txt`, `keys.csv` and an
  extension-free file all pass the format rule and carry the map identically.
- **By location** — `cache_path_for` must resolve outside the repository, so the
  accident has no ordinary route in rather than only being detected once made.

Each of the three is pinned by its own red-capability test. The format rule was not,
for one round: it was marked unchanged while the content rule was being given a
judge/scan split, and emptying its vocabulary left every test green. Fixing one rule
is not a reason to stop looking at its sibling.

**Tests that consume a generated corpus skip loudly when it is absent, and never
pass vacuously.** That sentence was dropped in an earlier rewrite of this entry and
is restored here: it is the other half of generating rather than shipping, and
without it a machine with no engine reports a green it did not earn.

### Why a shape and not a count

A first attempt counted snake_case literals and flagged a file over a threshold.
It was wrong in three ways, and they are worth recording because the shape of the
error recurs:

- **The threshold ratcheted against our own growth.** The densest file slicelab
  writes went from 8 literals to 22 in a single merge. A rule whose ceiling must
  rise as the project becomes more expressive is one that will be raised until it
  catches nothing.
- **It counted the wrong thing.** Measured: the 70 PrusaSlicer options with no
  matching config key score **0** in their natural dashed form, so the partial
  corpus offered as the threshold's justification evaded at every threshold.

  A first version of this entry gave the wrong reason for that — "the pattern
  required a leading letter". **All 70 begin with a lowercase letter.** Re-measured:
  52 carry a hyphen the extractor's character class could not match, and the other
  18 are single words (`center`, `cut`, `datadir`, `extruder`, `info`, `load`, …)
  with no underscore group for the pattern to find. Underscored, those same 52 do
  match. Recorded rather than reworded, because a true figure carrying a false
  reason is the defect this section exists to describe, committed inside the
  description.
- **It could not fail.** Raising the constant to 10000 left every test green,
  because the only red-capable test sized its own fixture from the constant.

The shape rule needs no threshold: a characterisation document either parses as one
or does not.

### What it does not catch, stated rather than implied

A map deliberately re-encoded as a Python literal, a base64 blob or a pickle.
That bound is pinned by a test, so nobody closes it by accident — an earlier
revision that also walked Python dict literals went red on
`slicelab/engine/characterise.py`, the module that *writes* the document, and on
the guard's own fixture. A dict with those keys is how you construct a map, not how
you ship one.

**That is a choice, not an impossibility**, and the difference matters to whoever
reads this next. Requiring `entries` to be a dict literal of two or more items
clears both false positives — `_write_cache` builds `entries` as a comprehension
rather than a literal, and the fixture has one entry — while still catching a real
map written as `MAP = {...}`. It is not taken because it is fragile in exactly the
way this decision distrusts: it starts failing the moment the guard's own fixture
grows a second entry, and the accident being guarded against produces JSON anyway.

The accident this guards against is committing a **generated file**, and
`characterise` writes JSON. Re-encoding it is a deliberate act, and no content rule
survives a determined author.

## D12 — slicelab core is Apache-2.0, argued from the binding, not from a stale org default

The engines are AGPL-3.0 (verified: `flatpak info` reports
`License: AGPL-3.0-only`) and are reached only across a process boundary — the
FSF's own paradigm of separate programs — so nothing is compelled. Apache-2.0 over
MIT for the express patent grant, since slicelab will sit inside other people's
build pipelines.

**Do not cite an org-wide default:** the org contract's section 9 says there is no
such default. What it does say is narrower and is what applies here — pick Apache-2.0
where the binding leaves the choice open, take what the engine compels where it does
not, and record which case you are in. slicelab is the choice-open case; orlab is the
compelled one. Section 9 now lists slicelab explicitly.

The derivative-work conclusion is a legal position no command can verify, and two
of the three upstreams assert the opposite in their READMEs. It is carried as a
decision with an owner, not as an established fact.

*Supersedes:* if slicelab ever conveys a distributable containing engine code or
an in-process GPL/AGPL dependency, the licence follows that binding — the orlab
case.

## D13 — `slice.toml` is TOML and inert, and this is a recorded deviation from org section 4

Org section 4 governs artifacts that **assert**; its consequence clause is "a
contract is code, and running a check executes it". `slice.toml` **requests**.

Making it Python buys none of section 4's three benefits and imports all of
netspec D24's process-isolation cost: `slicelab build part.slice.py` would execute
arbitrary repository code to decide a wall thickness. And section 4's "no schema
to design or version" is unavailable to slicelab regardless, because `slice.lock`
**is** a versioned schema; refusing one for the intent file splits the vocabulary
across a typed lock and an untyped dict.

Two constraints make the distinction load-bearing rather than rhetorical: the
parser is `tomllib.load` plus a validator and nothing else — the moment it can
compute, section 4 applies — and the vocabulary is closed and typed, with an
unknown key refused at exit 1.

**The test of whether this was honest: slicespec's contracts must be in Python.**
If slicespec ships YAML contracts, section 4 was abandoned by the back door and
`slice.toml` was the wedge.

*This is the first member to deviate from an unqualified section 4. It goes in
front of the org, not only in this file.* **Status: raised, not yet settled.**

## D14 — Outcome words are `sliced` / `refused` / `incomplete` / `error`; exit codes are section 6.3's

The original proposal's five names (`sliced`, `engine_error`,
`unsupported_version`, `invalid_profile`, `incomplete`) are **not implementable**
and are cut: they mix one verdict level with three causes, and [V6] shows two of
those causes are empirically indistinguishable. Causes are demoted to a `reason`
field and a closed `degraded_because` enum.

The words diverge from `pass` / `fail` deliberately. Org section 6.1 scopes the
pass/fail/unsupported/skipped core to "every member that adjudicates"; slicelab
adjudicates nothing about the G-code, so calling a slice `pass` claims a check
that did not happen.

The renderer prints the outcome word as the **first token** of output, pinned by a
test: a past-tense verb leading a non-zero run reads green to a human skimming CI
logs.

The exit codes are org contract **section 6.2**'s, which as of 2026-09-06 is the
settled org-wide vocabulary rather than one member's choice: adjudications A1, A2 and
A3 closed that day and partspec, netspec and gerberdiff now answer on the same five.
slicelab **conforms to a settled table; it does not pick numbers.** A1 exists because
two members picked `2` for different meanings and nobody noticed until a consumer
would have.

*Historical note, because `notes/evidence.md` V14 records the opposite and is frozen:*
when that observation was taken, section 6.2 listed only `0/1/4` and contradicted 6.3
in the same file, and this decision said to cite 6.3 and never 6.2. The org fixed 6.2
the same day (`.github` #12). V14 is correct as dated; this entry is the current
instruction.

### Precedence between outcomes

**`refused` (1) outranks `incomplete` (2).** A run with one `coerced` key and one
`absent` key is `refused`.

**Superseded in part by D27:** the `coerced` example above is no longer correct.
`coerced` forces `incomplete`, so a coerced-plus-absent run is `incomplete` on both
counts. The precedence rule itself stands; only its illustration moved.

A finding about the request is a statement slicelab established, and it stays one even
when some other key could not be evaluated. The reverse would let a single unreadable
key mask a real unhonoured override — and exit 2 invites a retry that will never change
the answer.

Adopted from netspec D26's "`fail` outranks `incomplete`" rather than re-derived, so the
drive and verify layers order their outcomes the same way.

## D15 — Signal death is `incomplete` (2), never `refused` (1)

`exit_status` and `signal` are separate fields.

[V6] gives rc=139 with 0 bytes on both streams, and the byte-identical signature
was reproduced from `--duplicate-grid` with a fully valid preset triple — so the
signature carries no cause and must never be attributed to the user's preset
names.

Where slicelab composed the offending argv (a partial `[base]` triple) it refuses
**pre-flight at exit 1** and never sees the 139: the cause is sourced from
slicelab's own request.

## D16 — `[base]` is all three preset names or none, and none is not expressible

Any of the six proper non-empty subsets is a SIGSEGV [V6]. Zero of three is
accepted at exit 0 with generic Slic3r built-ins — `layer_height 0.3`,
`gcode_flavor reprap`, empty `printer_model` — the defaults trap arriving as a
success.

This is a **change from the original proposal**, which treated `[base]` as
optional context.

## D17 — Engine query verbs are adjudicated on artifact parseability, never on exit code

[V5]: `--query-printer-models` returns rc=1 with 6550 bytes of valid JSON and 0
bytes of stderr — the same code it returns for "printer profile not found". The
lock records `discovery_exit_code_uninformative = true`.

An adapter branching on `rc == 0` would treat every successful vendor query as an
error. slicelab absorbs this rather than propagating it.

**Parseability alone is insufficient** [G3]: a datadir with the bundle but no
installed models returns `{"printer_models": ""}`, which parses. Adjudication is
parsed **and** non-empty **and** correctly shaped; anything else is exit 2 with a
named reason.

## D18 — The launch form is probed per package, per host, and recorded

[V10]. `discover.py` invokes a known-invalid flag against each candidate form and
**discards any form that returns 0**.

If no form preserves exit status, that is `error` (4): an engine whose exit code
carries no information is not a usable engine, and pretending otherwise installs
the founding defect at the very bottom of the stack.

`--command=` is never copied as a constant — it is *mandatory* for PrusaSlicer,
whose Flatpak entrypoint ends in a backgrounded child and therefore always returns
0, and *harmful* for OrcaSlicer, whose wrapper sets `LC_NUMERIC=C`.

## D19 — Every Plan path is stat'd host-side before invoking, and every one is granted

A Flatpak grant denial and a genuinely absent file are byte-identical at the engine
boundary — both exit 1 with `No such file: <path>` — so only a pre-stat separates
`error` (4) from a real missing input.

Grants are computed from `Plan.paths_read | paths_written`, never a fixed pair.
prusaslicer-py grants exactly two paths, so a config file elsewhere surfaces as an
*engine* error for a grant the driver forgot. A test asserts every path in the argv
appears in the grant set.

Path translation returns `(path, translated: bool)` and **refuses the launch** when
a path under a known Flatpak root failed to translate. prusaslicer-py's
`_to_engine_path` returns the host path silently, which is a could-not-tell dressed
as a translation. This is the one fix applied on copy.

## D20 — Every engine runs in a slicelab-owned scratch CWD, and stray files are recorded

[V13]: OrcaSlicer writes `00000.log` into the process CWD on a failing run.

Sweeping is the fix; recording `engine_run.stray_files` is the honesty. Cleaning up
and hiding evidence are the same action without the field.

### Written, then not implemented, for the life of the code (2026-09-06)

"Every engine" was the decision. `run()` defaulted to `cwd=None` and **not one of
its five call sites passed a directory**, so every engine ran in whatever
directory the user invoked slicelab from. Measured, not read: `slicelab which
orcaslicer` in an empty directory left a 180-byte `result.json` behind at exit 0
— so the litter is not conditional on failure the way [V13] recorded, and
`SECURITY.md` was simultaneously asserting the tool wrote nothing. An identical
file reached this repository's root and shipped in the sdist (D11).

The default is now a temporary directory `run()` owns and removes; a caller that
needs to *read* what the engine dropped passes its own.

**And it cannot be in `/tmp`.** The first fix used `tempfile`'s default and moved
the litter rather than removing it. A Flatpak sandbox has its own `/tmp`, so a
host `/tmp` path has nothing to translate to; `bwrap` does not refuse, it drops
the request and starts the engine in `$HOME`. Measured against both installed
apps by **writing a file from inside the sandbox and looking for it from the
host** — a cwd under `~/.cache` is honoured and the file appears there, a cwd of
`/tmp/tmp.GRYOi6pQ0O` puts the process in `/home/cam` instead.

An earlier draft justified switching from `pwd` to the write by claiming the
builtin "reports `$PWD` when it is set, so it cannot distinguish a real working
directory from an inherited one". That is **false** and was never measured:
`cd ~/.cache && env PWD=/tmp/a-total-lie sh -c pwd` prints `/home/cam/.cache`
under both dash and bash, which validate `$PWD` against the actual directory.
The write is better evidence because it demonstrates the consequence rather
than the location, not because `pwd` lies. An invented reason for preferring a
measurement is still an unmeasured claim, and it sat in this record for a
commit.

**Four further ways back in, all found by review of the fix**, over three
rounds, all in this one function:

1. Falling back to `tempfile`'s default on any `OSError` meant a single stray
   file at `~/.cache/slicelab` reinstated the whole defect, at exit 0, on a host
   whose home and whose Flatpak were both healthy. The first draft argued such a
   host "has bigger problems than litter" — an argument about a case the code
   did not detect.
2. A **relative** `XDG_CACHE_HOME` was resolved against the process working
   directory, creating `./mycache/slicelab/engine-cwd` where the user was
   standing. The basedir spec says a relative value must be ignored.
3. A relative **`HOME`** did the same through the other variable, because
   `Path.home()` hands back `$HOME` verbatim. The guard covered one of the two.
4. An **absolute** `XDG_CACHE_HOME` outside the home directory was accepted —
   `/var/cache/$USER` is an ordinary setting — and so was a symlink inside
   `$HOME` pointing out of it, which no check on the string can catch.

**So the rule is containment after resolution, and each word earns its place.**
A candidate qualifies only if it resolves to a path under the resolved home
directory; the home must be absolute *before* being resolved, since resolving a
relative one anchors it to the working directory — the defect, not the fallback.
`Path.home()` raising on a host with no home at all is caught, or it would leave
`run` as a traceback rather than an exit code.

Usability is proved by **creating** the scratch directory.
`mkdir(parents=True, exist_ok=True)` returns success on a directory that already
exists and cannot be written, so a ladder that only called `mkdir` settled on a
root it could not use and let the `PermissionError` escape from the launch
instead of descending to the next rung.

**The ladder is three rungs, then a degradation.** `$XDG_CACHE_HOME` when it is
absolute and contained, then `~/.cache/slicelab/engine-cwd`, then **the home
directory itself** — a `run-XXXXXX` created directly in `$HOME` is untidy but
visible to the sandbox, which is the property that matters. A mutation sweep
confirms that third rung is load-bearing: removing it reddens two tests.

The last rung is `tempfile`'s default, and it is a **degradation, not a
guarantee**: under a Flatpak it puts the engine back in `$HOME`. It is reached
only when nothing inside the home directory can hold a directory, and every
attempt to reach it with a working engine hit exit 4 first — Flatpak needs a
usable `$HOME` before slicelab does. Naming it is the point. `SECURITY.md` carried
the opposite claim — "every fallback is now home-visible" — in **two** places,
and the commit written to remove it fixed one and left the other standing
twenty lines away, so the document contradicted itself for two further commits.
That is the same shape of over-claim this entry is about, surviving inside its
own correction. `engine.yml` had already written the reason down — *"a Flatpak
is a materially different execution environment — sandboxed filesystem, its own
/tmp, translated paths"* — which is the cost of a fact living in a CI comment
rather than in the code it constrains. Scratch lives somewhere inside the home
directory — the ladder is set out above — with `~/.cache` as the ordinary answer,
where D11 already puts slicelab's generated data.

**The stand-in tests could not see any of that.** `tests/test_boundaries.py`
pins the guarantee with a `sys.executable` child, which honours `cwd` by
construction — no sandbox, no translation — so the suite was green on a machine
where the real engine was writing into `$HOME`. That is this repository's
founding rule inverted, on the change meant to honour it. A third test launches
every believable engine on the host and watches the working directory *and*
`$HOME`; it is engine-gated, so `engine.yml`'s Flatpak job is what makes it
bite.

Watching `$HOME` by *name* was not enough either: the session fixture's own
discovery had already created `result.json` before the test body took its
snapshot, so the run merely overwrote it and a set difference saw nothing. The
fingerprint is name, mtime and size.

**The recurring shape, worth naming because it cost four rounds.** Every one of
these defects was found by a person constructing an environment, never by the
suite. The tests were sound each time; what was missing was the *environment*
they ran in — an ambient shell, an ambient `$HOME`, an ambient
`XDG_CACHE_HOME`. Two of them were hidden by a variable happening to be set in
the operator's own shell. The engine-gated test is now parametrized over
environments rather than running only in the one it inherits, and a scratch
test that stands outside the home directory was found to be vacuous for exactly
this reason: the containment filter rejected its input before the guard under
test was reached, so deleting that guard left every test green.

**Also outstanding, smaller:** `TemporaryDirectory` cleans up on normal exit, on
exception and on `SIGINT`, but `SIGTERM` and `SIGKILL` both leak a `run-XXXXXX`
under the scratch root that nothing ever sweeps. `SIGTERM` is what `kill`,
systemd and CI timeouts send by default, so this is ordinary rather than rare. It costs an empty directory, not
correctness, and the sweep belongs with the ledger below.

**Still outstanding:** the honesty half. Nothing records `stray_files` yet,
because no verb yet produces an `engine_run` record to put it in. That lands with
the slice verb, not here — this entry now describes a sweep without its ledger,
which is exactly the half D20 warned about.

## D21 — An adapter that works around an upstream defect must detect that defect and refuse rather than apply the workaround blind

Orca's inheritance flattening and `compatible_printers` injection exist because
Orca 2.4.2's CLI does not resolve `inherits`. If a later Orca fixes it, an
unconditional workaround either becomes redundant or double-resolves — silently, at
exit 0. That is the org's founding failure shape aimed at itself.

Characterisation therefore probes for the defect (slice a known delta-shaped preset,
check whether an inherited key survives) and records `workaround_applied` and
`workaround_justified_by_probe` in the lock.

*This gates the v0.2 full Orca adapter. The v0.1.0 readback-only adapter avoids it
entirely by refusing profiles that need flattening.*

## D22 — slicespec reads `slice.lock` as a FILE and never imports slicelab

And slicelab never imports slicespec. Enforced by slicespec's dependency list. The
moment the two want a shared Python module, that is org section 10's "extracting
shared code across members" and it escalates.

**Corollary recorded now, before it can be forgotten:** a slicespec check that
compares the lock to the G-code footer is **circular**, because both are the same
slicer utterance. The lock is a check's *premise*, never its *evidence*. And
`; filament used [mm]` is an arithmetic identity over the E values in the same
file, so comparing them is a post-export integrity check, not independent evidence
about slicing.

## D23 — SuperSlicer is excluded as an adapter and retained as a red-state test fixture

Its config loader silently renames and sign-inverts PrusaSlicer keys —
`elefant_foot_compensation = 0.77` becomes `first_layer_size_compensation = -0.77`
— and discards others entirely, all at exit 0.

Org section 2.4: a check whose red state you have not observed is not a check. One
87 MB AppImage, zero adapter code, and the readback diff gets its best real-world
red state.

It is also not adoptable as an adapter: it has no preset-by-name CLI at all, so
`[base]` would require slicelab to reimplement preset inheritance, which org
section 3 forbids. There has been no stable release in 26 months, and all four
active dev branches build as `Slic3r`, which would move the binary name, version
banner and config footer marker simultaneously.

*Reversal trigger for the adapter:* a non-prerelease release of the rebranded line.
Re-run the config-surface diff before anything else.

## D24 — A run that requested nothing is `empty` (3), not `sliced`

`notes/critique.md` G1, settled. A `slice.toml` carrying a `[base]` triple and an
empty `[set]` runs to completion and produces a real artifact — and **"every
requested key came back `applied`" is vacuously true over zero keys.** Under the
original outcome table that run exited `0`. It is also the first file anyone
writes, so this was not an edge case; it was the default path.

### Why not `sliced` (0)

Because the sentence slicelab would be printing is not true of the run. The
mechanism this whole tool rests on adjudicates the **authored delta**; with an
empty delta it adjudicated nothing, while the ~370 keys of the resolved base went
unchecked. A green there is a claim that cannot fail, which is org contract §2.4
inverted and §2's founding rule aimed at ourselves.

### Why not `refused` (1)

`refused` is defined as *slicelab established the intent was not honoured*. With
zero requested keys **nothing was dishonoured**. Reporting `refused` would assert
a cause slicelab did not establish — the §2.3 plausible-substitute failure one
level up, the same trap D6 exists to avoid, aimed at our own outcome word.

netspec's D26 reaches the opposite conclusion for *its* domain ("an empty contract
is `fail`, because a code nothing branches on is vocabulary without a consumer"),
and that test is the right one. slicelab differs because the consumer exists: a CI
gate asking *"does every `slice.toml` in this repo verify anything at all?"*
branches on `3` and cannot be written against `1` or against `0`-plus-a-field. The
two states also call for **opposite fixes** — `refused` means change your
override, `empty` means add one.

### Decided

Follow partspec. `Outcome.EMPTY` maps to exit **3**, the same code partspec uses
for the same idea (`SPEC-contract.md` §6, "the vacuous-green guard"). Deliberate
alignment, not a coincidence.

Two consequences, recorded because they are not obvious:

- **The artifact is still promoted.** `empty` is not a fault; a valid G-code file
  was produced and nothing was found wrong with it. Withholding it would punish a
  user for not writing overrides. This is a **carve-out from D7**, which promotes
  only on `sliced`: promote on `sliced` *or* `empty`.
- **No lock is written.** A `slice.lock` is the record of a resolution slicelab
  verified. On `empty` it verified none, so there is nothing to lock. The full
  outcome is still rendered to stdout and to `--report PATH`.

`Outcome.EMPTY` does **not** participate in the precedence ordering (D14). It is
the answer to "there was nothing to combine", not a rank among things that were.

### Escalated, not assumed

**`3` is not in the org contract's §6.2 table**, which lists `0/1/2/4/64` and was
written from the settled set on 2026-09-06, deliberately excluding partspec's `3`
as one member's code rather than an agreed one. slicelab adopting it makes a
**second member using it**, which is the threshold at which §6.2 should probably
say so. That amendment is an org-level change under §10 and is raised there, not
decided here.

*Supersedes:* if a second consumer never appears — if after 20 real `slice.toml`
files nobody has branched on `3` — netspec's reasoning wins and this folds into
`refused`. The measurement, not the argument, decides that.

## D25 — 0.0.1 claims the name; the version has exactly one home

Two separate decisions, taken together because the release forced both.

**Why 0.0.1 rather than 0.1.0.** The version had been `0.1.0.dev0`, which the
release workflow's own pre-release guard correctly refuses to publish. `0.1.0` is
not free either: issue #12 scopes it, and its checklist is mostly unmet — six
verbs unimplemented, no cold `pip install` yet proven. Publishing `0.1.0` today
would consume the number that release plans and would say more about the project
than is true. `0.0.1` says the honest thing: the name is claimed and two verbs
work. PyPI versions cannot be reused, so this is the one direction that stays
open.

**Why the version is single-sourced.** It was two literals, `pyproject.toml` and
`slicelab/__init__.py`, with nothing pinning them together. The release workflow
reads the version off the *built dist filename*, so a stale `__version__` would
publish green while `slicelab --version` reported a number that was never
released — the tool disagreeing with its own package, silently, which is the
whole failure this project is named around. `pyproject.toml` now declares
`dynamic = ["version"]` and hatchling reads it from the package. Structural, so
no test is needed: the drift is not possible rather than merely detected.

## D26 — The core's vocabulary boundary is a whitelist of slicelab's own terms

`notes/refuted.md`'s "Fatal flaws (judge panel)" section asked for a **stoplist**
scoped to the FFF config-key namespace — the ~411 `--help-fff` option names — and
said the stoplist itself must be a numbered decision rather than a quietly growing
allowlist. This is that decision, and it inverts the construction.

### Why not the stoplist as specified

A committed 411-name `--help-fff` list is literally the **default key set** D11
names as XDG-cache material, harvested wholesale from help text D11 shows to be
copied expression rather than fact. The line D11 draws is bulk corpus versus
citation: naming `wall_loops` and `perimeters` in a test, as this decision's own
red-state guard does, cites two facts; committing all 411 ships the corpus. The alternatives were both
worse than the problem: read the stoplist from D11's XDG cache and the test skips
on every machine without an engine — a skipped test is not a passing test, and
this is the one test D1's supersede clause is adjudicated by. Hand-author the 411
names and D11 is broken outright, for a list that goes stale on the next engine
release.

There is also a coverage argument the stoplist loses. A blacklist only refuses the
names someone thought to list; OrcaSlicer's `wall_loops`, a future engine's
vocabulary, and any key added by an upstream release all pass it.

### Decided

Invert it. A string literal in a core module is either **prose** — it contains
whitespace — or it is a term named in `DECLARED_VOCABULARY` in
`tests/test_names_confined.py`. Everything else fails.

That works because of an asymmetry in the two vocabularies, which is measured
rather than assumed. Across both installed engines — PrusaSlicer 2.9.6's 343
`--save` config keys and 411 `--help-fff` options, and OrcaSlicer 2.4.2's 616
`--export-settings` keys — **not one key or option contains whitespace**, and not
one collides with a term in `DECLARED_VOCABULARY`, even as a substring. So the
prose rule separates the two vocabularies cleanly on today's engines. (Regenerate
with `--save`, `--help-fff` and `--export-settings`; the corpora themselves are
D11 XDG-cache material and are not committed.)

**What it refuses, stated exactly.** Every engine key that appears in a scanned
module as a string literal, a bytes literal, a class-body assignment target, or an
annotated field name. That covers the idioms a readback actually uses — including
`StrEnum` with `auto()`, where `WALL_LOOPS = auto()` carries the value
`"wall_loops"` with no such literal in the file.

**What it does not refuse**, and this is a real limit rather than a hedge: a key
that reaches a core module by `import` from a module that is neither core nor an
adapter, and a key assembled at run time from fragments. The first is worth
closing if `engine/` or `cli.py` ever grows a key constant; the second is
contrived enough that catching it would cost more than it buys.

**Adding an entry to `DECLARED_VOCABULARY` is this decision being amended**, and it
happens in a diff where someone can object. An engine's key name can never be
added; that is the whole content of the rule.

### What this is scoped to, and what it is not

`test_boundaries.py::test_engine_names_appear_only_in_adapters` confines engine
**identifiers** — the six executable names and Flatpak application ids computed
from `REGISTRY`. It does not look at config keys, and `AGENTS.md` claimed it did
for as long as the sentence existed. Both tests are kept; they make different
claims.

`cli.py` is deliberately **not** scanned, and that is a judgement rather than an
oversight. It adjudicates by the docstring's own criterion, but scanning it flags
nine terms — `--datadir`, `--version`, `VERB`, `__main__`, `presets`, `slicelab`,
`verb`, `version`, `which` — every one argparse plumbing and none engine-derived.
Admitting them is the dumping ground this decision's supersede clause warns about.
`test_every_module_that_exists_and_should_be_core_is_scanned` keeps the exclusion
honest by refusing any module that is neither scanned nor listed.

### Red-capability

The red state of this test cannot be observed by breaking the source tree the way
§2.4 usually asks, because the property under test is that the tree is *clean*. So
the checker is exercised directly against deliberately dirty source in
`test_the_checker_catches_an_engine_key`, and against an error message in
`test_prose_is_not_flagged` so the rule is not merely red on everything.

*Supersedes:* if the prose rule proves too coarse — a core module needing an
unspaced literal that is genuinely not vocabulary, often enough that
`DECLARED_VOCABULARY` becomes a dumping ground rather than a reviewed list — then
narrow the scan to comparison, containment and subscript operands and record that
here. The list growing without objection is the signal, not the list being long.

## D27 — `coerced` folds to `incomplete` (2); it names no cause

`notes/critique.md` G4, settled. Supersedes D14's `COERCED -> REFUSED` mapping and
the sentence in D14 that reads `coerced` as something slicelab *established*.

`refused` is defined as **slicelab established the intent was not honoured**. Over
a coerced key it established no such thing, because two different situations
arrive in the readback as the same bytes. Both reproduced here on PrusaSlicer
2.9.6, Flatpak, 2026-09-09, both `rc=0` with **0 bytes on stderr**:

```console
$ $P --export-gcode cube.stl -o v1.gcode --save v1.ini --perimeters 4.7
rc=0   perimeters = 4
```

Nothing honoured that request; the engine truncated it and said nothing.

```console
$ $P --export-gcode cube.stl -o g4.gcode --save g4.ini \
     --spiral-vase=1 --perimeters=4 --top-solid-layers=5 --fill-density=60%
rc=0   g4.gcode = 41106 B
       perimeters = 1   top_solid_layers = 0   fill_density = 0%
```

That request **was** honoured, correctly. Spiral vase mode has documented
dependent constraints and the engine applied them, producing a real artifact.

From the readback alone the two are indistinguishable: requested != resolved,
`rc=0`, no diagnostic, no stated cause. Under the old mapping the second run
exits **1** with no lock and an unpromoted artifact — a false red on a perfect
slice, at the tool's front door. That is the silence rule inverted, and G4 is
right that it is an epistemic problem rather than a strictness one: the verdict
word was wrong, not merely harsh.

### Decided

`COERCED` forces `INCOMPLETE` (exit 2). `coerced` means **requested != resolved,
cause unknown** — which is what slicelab actually knows.

The mechanism is unweakened. `sliced` still requires every requested key to come
back `applied`, so neither run above can be green. What changes is only the
sentence slicelab prints about a run it did not diagnose.

### Why not the `normalized` split G4 recommends first

G4's preferred fix is a second status: `normalized` for a value changed by a
constraint slicelab **probed and recorded**, at most `incomplete`, never
`refused`. That is the better answer and it is not available. It requires a probe
of the engine's dependent constraints, which does not exist, and `status.py`
already declined to add the enum member before that probe existed. Shipping the
word without the probe would name a cause on no evidence — the substitution one
level up, which is the defect this decision is fixing.

### What this costs, stated rather than skipped

The repo has adjudicated the other way twice, and D27 loses those arguments on
balance rather than dissolving them. D14 and `notes/refuted.md` both object that
"exit 2 means 'could not tell', which is false here and tells a user to retry when
retrying will never change the answer" — naming `--perimeters 4.7 -> 4`
specifically. That objection is correct about V1: it is deterministic, and exit 2
does invite a retry that cannot help. It loses to G4 because the spiral-vase false
red is the worse error and it is the one at the front door — a *correct* slice
reported as a refusal. A misleading retry costs a user a minute; a false red costs
them their trust in the verdict, and `--report PATH` names the diverging key either
way.

### Consequence for `refused`, which is not cosmetic

After D27 the only `KeyStatus` forcing `REFUSED` is `UNSUPPORTED`, and its own
docstring records that as unreachable while the core vocabulary is empty (D2). So no
**readback-derived** route to exit 1 remains. Exit 1 is not dead — D15 and D16 refuse
**pre-flight**, before the engine is touched, and a partial `[base]` triple is a real
user-reachable case — but `Outcome.REFUSED`'s docstring still reads "we looked, and
the answer is no", which is now the one thing it cannot mean by looking at a readback.
Re-read it when `preflight.py` lands.

*Supersedes:* when a constraint probe lands, add `NORMALIZED` and route it to
`incomplete` with the constraint named, leaving `coerced` as the genuinely
unexplained case. At that point `coerced` may become a candidate for `refused`
again, because it will then mean something narrower than it does today.

## D28 — `[set]`'s authored surface is the CLI-option set

`notes/critique.md` G6.5 asked which one it is, and the plan never said.

They are not the same set, though the difference is smaller and differently
shaped than a first count suggests. Measured on 2.9.6: **411** options at the
leading position of a `--help-fff` line, **343** config keys in a default `--save`
dump.

`--compatible-printers-condition=` answers `Unknown option`, yet
`compatible_printers_condition` is a real config key that round-trips through
`--load`/`--save`. It is in **neither** population — not in the 343 and not in the
411 — which is what actually establishes that the two sets differ.

**A first draft of this entry also named `idle_temperature` and `layer_gcode` as
keys with no option. That was wrong, and one command refutes each:**

```console
$ $P --save o1.ini --idle-temperature=175      # rc=0 -> idle_temperature = 175
$ $P --save o2.ini --layer-gcode=";HELLO"      # rc=0 -> layer_gcode = ;HELLO
```

Both have working options. `--layer-gcode` is an **alias**, printed in `--help-fff`
as `--after-layer-gcode ABCD, --layer-gcode ABCD`, and a scan that reads only the
leading option on each line does not see it — which is where the 411 comes from and
why set-subtracting it against the 343 manufactures orphans that do not exist. The
repo had already measured the alias relationship (`AGENTS.md`: "`--after-layer-gcode`
writes `layer_gcode`, so dash-to-underscore reports a false `absent` on a perfect
run"), so this was a claim contradicted by evidence already in the tree.

Recorded rather than quietly corrected, because substituting arithmetic over a
flawed scan for a measurement already in hand is the defect this project is named
after, and a decision entry is exactly where it must not happen.

### Decided

An authored key under `[prusaslicer.set]` is a **CLI option name**.

slicelab emits `--key=value` (D5), so the option set is exactly what it can
express. Authoring the config-key set would let a user write something with no
emittable form, which slicelab could only refuse at run time for a reason the
file gives no hint of.

The consequence is that a config key with no option — `compatible_printers_condition`
is the one confirmed case — is unauthorable through `[set]`. That is honest: there
is no CLI surface for it, and accepting it would mean failing later for a reason the
file gives no hint of.

*Supersedes:* if an engine appears whose config keys are the authored surface and
whose options are derived, this is per-adapter rather than global, and D1's seam
is where that difference belongs.

## D29 — an installed-but-unconfigured engine is an environment fault (4)

Issue #19, settled. Option B of the three it records.

A freshly installed PrusaSlicer has no configuration, and asking it to enumerate
presets gives a log line on **stdout** where JSON was expected, at engine exit 1.
slicelab reports `incomplete` (2). But slicelab *can* tell, and the answer is
specific: **the engine is installed and not configured.** Org contract §2.2 lists
"an engine that will not start, a source file that is not there" as environment
faults, and this is that shape — a fixable condition in the environment, not an
indeterminate result about the request.

### Decided

Exit **4**, established by a **datadir precondition check** living in
`adapters/<engine>/`: ask whether the engine has a configuration before querying
it, rather than inferring it from the engine's error prose.

Option C — matching the prose — is refused. It puts engine-specific strings
outside `adapters/`, it is locale-sensitive, and it breaks on a wording change
upstream can make without notice (§7).

Two things this decision does not get to assume:

- The check must resolve the **effective** datadir for the launch form discovery
  actually chose. Flatpak sandboxes it under `~/.var/app/...`, a native build uses
  the platform default, and `--datadir` overrides both. A hardcoded path would be
  the per-machine constant D18 already refuses for launch forms.
- A datadir can exist and carry no vendor bundle. That is a **third** state, and
  it is the one producing G3's `{"printer_models": ""}`. Absence of a datadir and
  presence of an empty one are not the same fault.

### Status

**Implemented**, by `presets` and `resolve` alike, which is what this entry existed
to ensure. `which` is unaffected and correctly exits 0 on a fresh install, because
discovery asks the engine to identify itself and that needs no configuration.

### What the implementation does differently, and why

Two departures from the text above. Both are deliberate; neither was noticed until
review, because the entry was not read before the code was written — the failure this
repository's own "Read `docs/DECISIONS.md` before changing anything structural" exists
to prevent, and it produced a duplicate numbered decision that has since been removed.

**"in `adapters/<engine>/`" is split.** The engine *facts* are in the adapter — a
`ConfigLocation` naming the directory per launch form and the file that marks it
configured. The *mechanism* that reads them is `slicelab/engine/configured.py`, which
names no engine. That is the shape `OptionProbe` already uses: what differs per engine
is declared on the spec, and the measuring is engine-neutral. Putting the mechanism in
each adapter would duplicate the Flatpak/XDG/platform path logic per engine, and the
first copy to drift would be wrong about a path nobody re-measured.

**The third state is not in `ConfigState`.** This entry names one — a datadir that
exists and carries no vendor bundle, producing G3's `{"printer_models": ""}`. That
case is real and is already refused, by `presets`' own `PresetsVerdict.EMPTY`: "the
bundle is present but no models are installed". Modelling it a second time in
`ConfigState` would mean two places deciding the same thing, and the two would
disagree the first time one changed. `ConfigState` answers only what a directory can
tell you — configured, not configured, or could-not-tell — and the inventory's
emptiness is the adjudication `presets` already performs on the answer.

What the implementation adds, which this entry did not anticipate: **`UNDETERMINED`**.
A location is declared per launch form, and only the Flatpak one is measured, because
only Flatpaks are installed on the machine that measured them. An engine or platform
with no declared location answers "could not tell" and changes nothing. Reporting "not
configured" because slicelab does not know where to look would put a guess behind the
exit code reserved for facts (§2.3), and would make every unmeasured engine a
permanent exit 4.

**The marker is a file, not the directory.** The Flatpak runtime creates a config
directory before the engine has ever run, so testing for the directory reports every
fresh install as configured. Measured: a datadir copied whole with only
`PrusaSlicer.ini` removed makes the engine exit 1 with "Configuration wasn't found",
so that file is exactly what decides.


## D30 — the option-to-key map is probed with two sentinels, cached per build, and its value is a tuple of keys

`notes/critique.md` G2's actions 2 and 3, implemented. G2 called the name mapping
"unstated and provably non-total" and reproduced a false `absent` from the only
available rule; this entry records what replaced it and, more usefully, the four
things measuring it established that reading could not.

### Decided

`load_name_map(spec, version) -> Mapping[str, tuple[str, ...]]`, built by setting
each option to **two** distinct sentinels and observing which config key followed
the value, cached under
`$XDG_CACHE_HOME/slicelab/characterisation/<engine>/<version>/`. Engine **and**
version, because the map is a per-build fact: options are renamed and keys are
added between releases, and a map carried across that boundary is confidently
wrong with nothing to report the gap. D11's half is unchanged — the cache is
generated on the user's machine and slicelab ships none of it.

The engine-neutral part — cascade, artifact gate, timeout, mode-switch rule,
tracking, cache — is `slicelab/engine/characterise.py`. The four engine-shaped
parts are `adapters.base.OptionProbe`: how to enumerate options, how to read a
readback, this engine's sentinel spellings, and its wording for "no such option".

**The value is `tuple[str, ...]`, uniformly, including 1-tuples.** Four options
write more than one key, and `--extruder` writes three (`infill_extruder`,
`perimeter_extruder`, `solid_infill_extruder`). A `str` value would have to pick
one, and a readback comparing only the picked one reports `applied` while two
keys went unchecked — green over a partly honoured intent, which is the worst
outcome in this system. A value whose type depends on how many answers there
happen to be is a second defect handed to the caller, so the 1-tuples stay
tuples.

### Two sentinels, because one cannot tell a write from a constraint

Setting an option once says which keys **moved**. Setting it twice says which of
them **followed the value**. A key tracks when it holds sentinel A after the run
with A and sentinel B after the run with B; only a key the option writes can do
that. Measured on 2.9.6:

```
--extruder      (=2 vs =3)   tracks infill_extruder, perimeter_extruder, solid_infill_extruder
--solid-layers  (=2 vs =5)   tracks bottom_solid_layers, top_solid_layers
                             side effect solid_layers      (0 under both)
--spiral-vase   (=1 vs =0)   tracks spiral_vase
                             side effects perimeters, fill_density, top_solid_layers,
                                          filament_retract_layer_change
```

So `notes/critique.md` G4's dependent constraints are separated. `--extruder` is
an aggregate and all three members are the request; `--spiral-vase` sets one key
and the engine then adjusts four others, which were never requested and must
never be adjudicated against the authored value. Those four are recorded on the
entry as `side_effects`, because they are true, and kept out of `keys`, because
comparing an authored value against them is G4's false red on a slice the engine
performed exactly as designed.

`perimeters` is why one sentinel could never have done it: the constraint sets it
to `1`, which is precisely the value that was sent, so "did this key take my
value" answers yes about a key nobody asked for.

**The separation is contingent on the sentinel table, not structural.** A first
draft of this entry said "structurally, with no heuristic and no threshold", and
that is false. It holds only when some pair in `OptionProbe.sentinels` is carried
*verbatim* by the key the option writes. Refuted by changing nothing but the
pair, on the same option and the same build:

```
--spiral-vase ('1','0')     exact    keys=(spiral_vase,)
                                     side_effects=(perimeters, fill_density,
                                                   top_solid_layers,
                                                   filament_retract_layer_change)
--spiral-vase ('true','1')  inexact  keys=(filament_retract_layer_change,
                                           fill_density, perimeters,
                                           spiral_vase, top_solid_layers)
                                     side_effects=()
```

`true` resolves to `0`, so neither value is echoed and every one of the five keys
merely *responds*. A dependent constraint **does** move differently under two
different values; what separates the populations is the verbatim echo, not the
fact of moving. So `Tracking.INEXACT` carries a second meaning beyond "the value
was normalised": **the separation did not happen for this entry**, its
`side_effects` is empty because none could be established rather than because
there were none, and a readback must not treat its keys as each carrying the
requested value. Normalisation is the diff's problem; an unseparated constraint
is a reason to refuse.

**A one-run value filter was tried first and is refuted**, which is why the
second run rather than a cleverer rule. Keeping only keys whose resolved value
equalled the sentinel verbatim unmapped **89 of the then-330 mapped options**,
because the engine normalises legitimately — `7` resolves to `7%`, `1` to
`enabled`, a string to `0` on every numeric option — and it still kept
`perimeters`. It cost 89 correct answers and did not buy the one thing it was
for. Normalisation is now carried as `Tracking.INEXACT`: the keys responded to
both sentinels but carried neither verbatim, so the tie is real and weaker, and
value normalisation is the readback diff's problem rather than the map's.

**The cost is stated rather than hidden.** One extra invocation per candidate,
and the cascade no longer stops at the first non-empty answer — an inexact pair
is remembered and a later pair of the right type may still track exactly, which
is what `--fill-density` needs. Measured solo on a quiet host, PrusaSlicer went
from **398 s to 1105 s**, about 2.8x rather than the 2x a per-candidate count
suggests, and the confirmation pass below takes it to 1205 s. Once per build,
cached.

### Measured, 2026-09-10, on the two installed engines

Every column below is a **solo run on a host with the process leak fixed**, load
average under 3. The earlier revision of this table was measured on a machine
this probe had itself degraded; see *Reproducibility* below.

| | PrusaSlicer 2.9.6 | OrcaSlicer 2.4.2 |
|---|---|---|
| candidates probed | 416 | 616 |
| baseline readback keys | 343 | 616 |
| **mapped** | **342** | **545** |
| of which tracking is exact | 336 | 374 |
| of which tracking is inexact | 6 | 171 |
| entries with >1 key | 4 | 4 |
| entries carrying side effects | 3 | 0 |
| moved no key | 29 | 8 |
| every sentinel refused | 36 | 63 |
| wrote no readback at exit 0 | 2 | 0 |
| switched key namespace | 2 | 0 |
| never returned | 5 | 0 |
| disagreed on confirmation | 0 | — |
| **inconclusive** | **45** | **63** |
| wall clock | 1205 s | 1165 s |

The PrusaSlicer column includes the confirmation pass described below: **101 s**
of the 1205 s, re-probing 29 options, all 29 confirmed. The Orca column predates
it and is 1165 s without.

`inconclusive` is the count `MapEntry.conclusive` refuses: everything except
`mapped` and `no-key-moved`. On PrusaSlicer all 45 are properties of the option
rather than of the host — the 5 timeouts are `--gcodeviewer` and the four
`--opengl-*` options, every one of which opens a window.

Orca's 171 inexact entries are one cause, not a spread: its per-extruder keys are
**JSON lists**, so `--activate-air-filtration=1` resolves to `["1"]` and responds
to the value without carrying it. A container shape, not a value transform, and
exactly the case `INEXACT` exists to carry rather than discard.

`--after-layer-gcode -> layer_gcode` is the **only** single-key PrusaSlicer entry
whose key is not its own dash-to-underscore form, and there are none on Orca.
That does not make the transform nearly right: see the collision result below.

### Four findings the probe produced that reading the engine did not

**A mode switch is not a mapping, and it needs no threshold.** `--export-sla`
swaps printer technology: it drops 334 of the 343 baseline keys and adds 143 of
its own. Counting moved keys and rejecting "more than N" is a number someone has
to keep true; *did any baseline key disappear* separates the two exactly, because
a config option only ever changes a value or adds a key. `--bed-custom-texture`
adds exactly one and drops none.

**An engine that returns is not an engine that answered, and the probe is not
exempt from D7.** `--post-process` and `--info` exit 0 having written no ini.
Parsing the absent file yields `{}`, every baseline key then reads as moved, and
one option is recorded as writing all 343.

**Accepted-and-moved-nothing is not an answer either.** This probe shipped one
measurement with the cascade stopping at the first accepted sentinel, and it was
wrong in a way only a second run exposed. D5: PrusaSlicer's boolean options
validate nothing and anything that is not literally `1` resolves to `0`, so
`--spiral-vase=SLICELABPROBE` exits 0, resolves to the `0` already in the dump,
and moves no key. That put **110 real options** — `--spiral-vase`,
`--support-material`, `--thin-walls` among them — in a bucket meaning the exact
opposite of the truth.

**How a bare number is read is decided per option, and `--fill-density` reads it
as a fraction.** `=40` and `=7` are refused at rc=1 with `Value out of range:
fill_density` and **no ini written**, while `=0.4` resolves to `40%` and `=60%`
to `60%`. Stated for that option and not as a rule about percent-typed options:
`fill_angle` and `first_layer_speed` accept a bare `40` as `40`, while the
extrusion-width family rejects it on a units check. Three
behaviours across one nominal "type" is why D5 refuses to ship an option
catalogue and why this map is probed.

The relevance to the probe is narrow and it is benign only because D7's artifact
gate is in place: the refused run writes nothing, so the cascade steps past a
*rejection* rather than reading an empty answer as "this option moves no key".

### The collision search G2 named as its own action

G2: "a collision — an alias whose underscore form happens to be a different real
key — would be a false `applied`, i.e. green on an unhonoured intent. I did not
find such a collision, and I did not search exhaustively; that search is the
action."

Searched exhaustively over all 416 PrusaSlicer spellings and all 616 Orca
candidates, aliases included — `--help-fff` is now read past the first name on a
line, which is where D28's five alias-only spellings come from. The test is: for
every candidate, is its dash-to-underscore form a real config key that the probe
established the option does **not** write?

**Result: no collision of the kind G2 feared exists on either engine.** Every
case where the transform points at a real key the option does not write is an
option that writes **no key at all** — 27 on PrusaSlicer, 71 on Orca — which the
map already refuses by leaving those options out of it. (Both counts are against
the default dump; a key absent from the defaults and created by the option, like
`bed_custom_texture`, is not in that population.)

What remains is narrower than "the transform is unsafe", and tracking shrank it:

* **False `absent`** — 4 on PrusaSlicer. `--after-layer-gcode` and `--extruder`
  write differently-named keys; `--solid-layers` and `--solid-min-thickness` now
  join them because their self-named key turned out to be a side effect rather
  than a write.
* **Right key, incomplete check** — **1** on PrusaSlicer, down from 4, and 4 on
  Orca. This is the false `applied` G2 was looking for, reached by a different
  route than the one it proposed: the transform names one member of a genuine
  aggregate and the rest go unchecked. Tracking is what makes the membership
  measured rather than assumed, so the class is now only as large as the
  aggregates really are.

### The probe must not poison the host it measures on

`launch.run` timed out with `subprocess.run(timeout=...)`, which kills the direct
child. For every engine here the direct child is a **launcher**: `flatpak run`
spawns `bwrap` spawns the slicer. Killing the launcher orphaned both, and an
orphaned GUI process never exits.

Measured on this host after repeated sweeps: **75 orphaned engine processes**
alive, oldest 8 h 17 m, at a fifteen-minute load average of 60. The timeout
existed so one hung option could not hang the machine, and without a group kill
it converted one hang into five permanent ones per sweep, cumulatively.

`_spawn` now gives the child its own session and signals the **group** on
timeout: SIGTERM, a grace period, then SIGKILL. POSIX only, and named as a gap
rather than papered over — `setsid` and `killpg` do not exist on Windows, where
this degrades to the old single-process kill; the Flatpak launcher it is written
for is POSIX-only, so the leak it fixes cannot arise there.

**The post-kill drain is bounded, and finding out why is the more useful half.**
The write ends of the captured pipes are inherited by every descendant, so an
unbounded `communicate` waits for the last one to let go — which is exactly the
orphan the kill just targeted. With the group kill disabled, the drain blocked
for the orphan's full 120 s lifetime and then returned normally, so the leak
surfaced as a **slow success**. The first version of the regression test passed
against the broken code for that reason. It now bounds `run`'s wall clock as well
as asserting the grandchild is dead, and it is red at 20 s with the group kill
off.

### Reproducibility, restated as what it is

An earlier revision of this entry reported "2 of 416" from a pair of sweeps, one
of which shared the host with another sweep. Re-measured at load 200 — the load
this probe was itself creating — **308 of 416 outcomes disagree**.
The figure was not wrong about the runs; it was measured on a machine the probe
had degraded, and the entry did not say so.

Re-measured on a host with the leak fixed, two full PrusaSlicer sweeps
back to back, load average under 3:

| | run A | run B |
|---|---|---|
| candidates | 416 | 416 |
| mapped | 342 | 341 |
| inconclusive | 45 | 45 |
| entries differing | **1** | |

The 45 inconclusive are the same 45 in both runs and every one of them is a real
property of the option, not of the host: 5 timeouts (`--gcodeviewer` and the four
`--opengl-*` options, all of which open a window), 36 that refused every
sentinel, 2 that wrote no ini (`--info`, `--post-process`), and 2 that switched
namespace (`--export-sla` and its alias `--sla`).

The one that moved is `--enable-dynamic-overhang-speeds`: `mapped` in A,
`no-key-moved` in B, and `mapped` 3/3 when probed alone. **Its direction is the
uncomfortable part.** `no-key-moved` is a *finding* — `MapEntry.conclusive` is
true for it — so that residue is not caught by the could-not-tell channel. A
transient engine failure on the one pair that discriminates leaves only
inert-looking evidence, and inert is indistinguishable from genuinely inert.

### So the inert set, and only the inert set, is confirmed

A first draft of this entry refused to retry anything, on the argument that a
retry suppresses a real refusal. **That argument is right about `rejected` and
wrong as a generalisation**, and leaving it to cover the whole probe was letting
one true sentence do work it could not.

A confirmation pass over `NO_KEY_MOVED` touches no refusal at all. It re-probes
the 29 of 416 options that appeared to write nothing, and a disagreement demotes
the option to `UNSTABLE`, which is **not** conclusive. Promoting the more
interesting answer would be picking a winner between two runs that disagreed.
`REJECTED` and `TIMED_OUT` are excluded deliberately and for different reasons:
re-probing a refusal hides a genuine "no" behind a lucky second run, and
re-probing a hang is what poisons the host in the first place. Both are already
could-not-tells, so a retry buys nothing there and costs the property.

Cost measured, not estimated: **101 s of a 1205 s sweep**, 29 options re-probed,
all 29 confirming. The sweep without it was 1105 s.

What is claimed is therefore narrow: **keys are stable, presence is
load-dependent, the load-dependence was largely self-inflicted, and the one
negative finding a caller may act on is now established twice.**

### One unattributed test failure, recorded as unattributed

`test_the_engine_writes_a_key_the_options_name_does_not_predict` failed once
across four full suite runs on the fixed host and passes in isolation. Two full
sweeps either side of it were clean, so the transient is rare rather than
routine.

**Which** transient it was is not established: the run captured no output, and a
single failure with nothing recorded does not identify a cause. It is written
down as unattributed rather than filed under the load-sensitivity above, because
attributing it to the nearest known story is the substitution this project is
named after. The action if it recurs is to capture the engine's streams at the
point of failure, not to reason about it further from here.

### A partial map must be able to say so

`load_name_map` returned `{option: keys}`, which threw away everything the probe
knew about the options it could *not* map. An option that timed out was simply
missing — indistinguishable from an option that does not exist — so a readback
would report `absent`, a claim about the engine, for a key it never measured.
That is G2's own defect returning through the cache, and a degraded map is cached
under engine+version and served from then on.

So the value is a `MapEntry` carrying `keys`, `side_effects`, `tracking` and
`outcome`, for **every candidate probed**. `MapEntry.conclusive` is true only for
`MAPPED` and `NO_KEY_MOVED` — this option writes these keys, or this option
writes none. Everything else is a could-not-tell that a caller must refuse rather
than convert into a verdict. `Characterisation.inconclusive` names them, and the
cache records the count, so a partial map says it is partial instead of looking
complete.

This also fixes the quieter half of the same defect: 171 of Orca's 546 entries
are `INEXACT`, and under the old return type they reached the consumer
indistinguishable from exact ones.

*Supersedes:* if `side_effects` turns out to be something a readback should
adjudicate rather than merely record, that is a change to `readback.py` and to
D27, not to this map — the map states which keys followed the value, and that is
the thing that was measured.

## D31 — the readback is staged, redacted, then promoted; the engine never writes the author's path

`resolve` asked the engine for its configuration by pointing `--save` at the path
the author would keep, and overwrote that file with a redacted copy once it came
back. Three things were wrong with that, and they share one cause: the engine's
dump is unredacted at the moment the engine writes it.

**Cleartext at the destination, kept on every failure in between.** Measured on
2.9.6 with a preset triple: the dump carries `print_host`, `printhost_apikey`,
`printhost_cafile`, `printhost_password`, `printhost_port` and `printhost_user`
with the values that were set. Any failure between the engine's write and
slicelab's overwrite leaves those bytes at the author's path permanently — a
non-zero engine exit, an `OSError` on the write, a `RedactionError`, a SIGINT in
the window. Two of those are branches `resolve` itself takes, and the report said
nothing about the file sitting there. The directory in question is the one the
README's git model says you commit.

**A stale dump read as fresh.** Gating on "a non-empty file exists at the
destination" cannot tell "the engine wrote this" from "the engine wrote nothing and
last time's file is still here". The default destination derives from the intent
path, so re-running one `slice.toml` in one directory — the ordinary workflow — was
what armed it, and the run reported `sliced` at exit 0 against the previous run's
configuration. The first fix for this deleted the destination before launching,
which closed the stale read by destroying the author's evidence, and D7 says
non-destructive for a reason.

**So:** the engine is told to write inside a temporary directory `resolve` creates
and destroys; slicelab redacts what it finds there, writes the redacted copy beside
the destination, and renames it into place. The rename matters as much as the
staging: `write_text` truncates at open, so a failure part-way through left the
author holding a half-written file where their previous readback had been, while
the run reported exit 4 and "nothing was established". `os.replace` is atomic on
POSIX and on Windows, and the temporary lives in the destination's own directory
because a cross-filesystem rename is not. `Plan.paths` grants the staged path and **not** the destination, so
a sandboxed engine cannot reach the author's file even if it tried. This is D7's
mechanism — "slices into a scratch directory and promotes to the destination" —
applied to the readback, and it closes the stale read structurally: the staged path
is inside a directory that did not exist a moment ago, so there is no revision of
the gate that can confuse this run's dump with the last one's.

**Where this parts from D7, and why.** D7 promotes *only on `sliced`*. The readback
is promoted on any outcome that was actually adjudicated, including `incomplete` and
the `empty` run D24 requires be kept. For G-code a partial artifact is dangerous and
withholding it is the safe default; the readback is the opposite — it *is* the
evidence for a non-green verdict, and handing the author a finding with nothing to
check it against is the failure mode, not the protection. A run that reached
adjudication has a complete, engine-written dump. A run that did not reach it
promotes nothing and leaves the previous file untouched.

## D32 — an engine that ran, refused, and wrote nothing is `incomplete` (2), not `error` (4)

When the engine starts, reads the request, writes no configuration and exits
non-zero — an unknown option, a preset name that does not exist — slicelab has no
readback to adjudicate. That was reported as `error` at exit 4.

Exit 4 is an environment fault under org contract 2.2, and nothing in the
environment is faulty: the engine was found, launched, and answered. Claiming a
machine problem for a request the engine declined asserts something nobody measured.

`refused` (1) over-claims in the other direction. The exit status alone cannot
separate "your request was wrong" from "this install is broken" — [V5] has 2.9.6
returning 1 on complete success, and [V10] measures that exit fidelity differs per
package and per host. A `refused` here would be slicelab deciding, from a number it
has already established carries little information, that the author's file is at
fault.

`incomplete` is the word for exactly this: slicelab ran and cannot stand behind an
answer. It is what D14 reserves for a run that reached no verdict, and it leaves the
author with the accurate statement rather than a confident wrong one.

**The engine's own account is carried in the message**, every line of it. 2.9.6
names the cause every time, and it does not put it on the first line:

```
Error while loading config from profiles:
Printer profile 'No Such Printer 9000' wasn't found.
```

A `splitlines()[0]` keeps the header and drops the sentence, which was reproduced
inside the first revision of this very fix. Discarding the engine's words leaves the
author with a verdict and no hint what to change — the failure D28 exists to avoid.

*Supersedes:* if an adapter ever declares a **measured** predicate for "this
engine's stderr means it refused the request", that engine's refusals become
`refused` (1) and this stays the answer for every engine that has not measured one.
The classification would live on the adapter, never in `resolve.py` or `readback.py`
— D26's boundary is what keeps an engine's diagnostics out of the core.
