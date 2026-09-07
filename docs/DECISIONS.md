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
`test_vocabulary_empty.py` asserts `CORE_KEYS == frozenset()`.

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
evidence. `len(vocab.CORE_KEYS)` is asserted against a committed constant so
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
mechanism (a 626-key JSON export rather than a 376-key ini).

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
the preset catalogue, the option-to-key map (D5, [G2]). Pinned by
`test_no_engine_data.py`.

Tests that consume a generated corpus **skip loudly** when it is absent, never
pass vacuously.

*Cost:* first use of an uncharacterised build takes a few extra engine
invocations.

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
`/tmp/tmp.GRYOi6pQ0O` puts the process in `/home/cam` instead. (`pwd` alone
would not have settled it: the builtin reports `$PWD` when it is set, so it
cannot distinguish a real working directory from an inherited one.)

**Two further ways back in, both found by review of the fix.** Falling back to
`tempfile`'s default on any `OSError` meant a single stray file at
`~/.cache/slicelab` reinstated the whole defect, at exit 0, on a host whose home
and whose Flatpak were both healthy — the argument in the first draft, that such
a host "has bigger problems than litter", was about a case the code did not
detect. And a **relative** `XDG_CACHE_HOME` was resolved against the process
working directory, so `mkdir(parents=True)` created
`./mycache/slicelab/engine-cwd` where the user was standing: the same litter,
authored by slicelab rather than by the engine. The basedir spec says a relative
value must be ignored, and it now is. Every rung of the fallback ladder is
inside the home directory; only a host with no usable home reaches `tempfile`'s
default, and that rung is named as the degradation it is rather than argued
away. `engine.yml` had already written the reason down — *"a Flatpak
is a materially different execution environment — sandboxed filesystem, its own
/tmp, translated paths"* — which is the cost of a fact living in a CI comment
rather than in the code it constrains. Scratch lives under `XDG_CACHE_HOME`,
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

**Also outstanding, smaller:** `TemporaryDirectory` cleans up on normal exit, on
exception and on `KeyboardInterrupt`, but a `SIGKILL` leaks a `run-XXXXXX` under
the scratch root that nothing ever sweeps. It costs an empty directory, not
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
