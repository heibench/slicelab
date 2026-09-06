# Critique

Gaps found by attacking the finished plan — the pass that asked "what is missing
or dishonest here", not "is this good".

**Its headline finding is that it built a working exit-0-establishing-nothing
scenario inside slicelab's own design**, on the most ordinary input the tool
accepts. That is the org's founding failure shape, aimed at us, before a line of
code existed. G1 is therefore the highest-priority correctness constraint in the
project and is repeated in `AGENTS.md`.

Frozen 2026-09-06. See `README.md` in this directory for provenance.

---

I have enough reproduced evidence. Writing the report.

---

# COMPLETENESS CRITIC — slicelab plan

**Headline: I built the exit-0-establishing-nothing scenario, and it is not exotic — it is the most common `slice.toml` anyone will write.** Everything below is either a command I ran today or a line-by-line diff of plan against dossier. Where I did not verify, I say so.

Engine under test throughout: `flatpak info com.prusa3d.PrusaSlicer` → 2.9.6, `com.prusa3d.PrusaSlicer`.
`P = flatpak run --command=prusa-slicer --filesystem=$S com.prusa3d.PrusaSlicer`, `$S` = my scratch dir, `cube.stl` = a 20 mm ASCII cube I generated.

---

## G1 — CRITICAL: `sliced`/exit 0 is vacuous whenever `[set]` is empty, and the plan never guards the subject set

**Missing.** The plan's `sliced` condition (§4) is "…**every requested key came back `applied`**…". With zero requested keys that clause is vacuously true. Nothing in `status.py`, `readback.py`, the lock schema, or `test_red_states.py` requires `len(resolution.keys) > 0`. A `slice.toml` carrying only `[prusaslicer.base]` — which D16 makes *mandatory* and which is the natural first file any user writes — exits **0** with `resolution.keys = []`.

**Reproduced** (this is a legal, everyday intent, not a corner case):

```
$P --export-gcode $S/cube.stl -o $S/base_only.gcode --save $S/base_only.ini \
   --printer-profile "Original Prusa i3 MK3S & MK3S+" \
   --print-profile "0.20mm QUALITY @MK3" --material-profile "Prusament PLA"
rc=0   gcode=604407 B   ini_keys=376   stderr=0 B
```

**Why it matters.** This is the org's own recorded failure shape — partspec's "195 passed / 23 skipped", and the dossier's own slicespec track named it *"zero-subject vacuity"* as case-4 flavour 1. The plan's §1 says "*One mechanism justifies the whole tool and nothing else does*". In this run that mechanism ran over an empty set and the tool still printed the green word. Worse, the 376-key resolution it did not check is exactly the half the dossier proved is unstable: the datadir's selected GUI presets leak in, and the vendor bundle auto-updates while still declaring `config_version = 2.4.14`. The lock *records* `selected_presets_hash`, bundle `sha256`, and `declared_config_version` — but records ≠ checks. Two machines, two different G-codes, two locks both saying `outcome = "sliced"`.

**The deeper omission the plan never states:** the readback diff covers `[set]` (2–10 keys) and does not cover `[base]` (the other ~370). The plan presents the mechanism as if it validated the resolution; it validates the delta.

**Action.**
1. Add `resolution.keys_checked = <int>` to the lock and make `sliced` require it to be `> 0`, **or** add a distinct outcome/`unknowns` code `no_requested_keys_to_check` so a base-only run cannot print the same word as a checked one. My recommendation is the `unknowns` code plus a `resolution.subject_set = "empty"` field — exit 0 is defensible (an artifact was produced and promoted), the *silence* is not.
2. Add a test to `test_red_states.py`: base-only intent must not be reportable identically to an intent whose keys were verified.
3. State in D4, in one sentence, that the mechanism adjudicates the authored delta and only records the base — currently the plan reads as though it adjudicates the resolution.

---

## G2 — CRITICAL: the readback diff's name mapping is unstated and provably non-total; I produced a false `absent`

**Missing.** `readback.py` is specified as `dict[str,str] × requested → per-key KeyStatus`. Nowhere does the plan state how an authored/emitted CLI option name becomes a readback config key. The only available rule is dash→underscore, and it is **not total in either direction**.

**Measured** (`--help-fff` option names vs `--save` config keys, 2.9.6):

```
cli options (--help-fff): 411
config keys (--save)    : 343
options whose dash->underscore name IS a --save key: 341
options with NO matching --save key                : 70
config keys with NO CLI option                     : 2   ['idle_temperature', 'layer_gcode']
```

**Reproduced false `absent`** — a CLI option that is an *alias* writing a differently-named key:

```
$P --save $S/alias.ini --after-layer-gcode="M117 SLICELAB"     → rc=0
grep -c '^after_layer_gcode' alias.ini → 0
grep    '^layer_gcode'       alias.ini → layer_gcode = M117 SLICELAB
```

The key was applied **exactly**. A dash→underscore readback finds no `after_layer_gcode`, returns `absent`, which the plan's table forces to `incomplete` → **exit 2** on a perfect run.

**Second, independent failure of the same mechanism: the readback's key SET is value-dependent.** `bed_custom_texture` is absent from the default 343-key dump and present the moment you set it:

```
$P --save $S/bt.ini --bed-custom-texture=/tmp/x.svg → rc=0 ; bed_custom_texture = /tmp/x.svg
```

Key counts I measured on one host, one build: **343** (defaults), **376** (preset triple). The dossier independently reports 345. So "not in the readback" is not evidence of anything — which is precisely why `absent` maps to 2, but the plan treats that as a rare honest state rather than a routine one caused by its own naming assumption.

**Why it matters.** This is the load-bearing module. A silent alias mismatch is a false 2 (annoying); a *collision* — an alias whose underscore form happens to be a different real key — would be a false `applied`, i.e. green on an unhonoured intent. I did not find such a collision, and I did not search exhaustively; that search is the action.

**Action.**
1. Add `readback.py` field `name_mapping` and a per-key `readback_key` in `resolution.keys[]`, so the lock says which resolved key was compared.
2. Generate the option→key map at characterisation time by **probing**, not by string transform: set each option to a sentinel and observe which `--save` key moved. This is ~411 invocations once per build, cached under D11's XDG cache — expensive but it is the only honest construction, and it also settles R6 for free.
3. Add a test asserting the map is total over the options slicelab will emit, and that an unmapped option is refused at **64** (slicelab's own argv is wrong) rather than surfacing as `absent`.

---

## G3 — HIGH: `slicelab presets` exits 0 on an empty enumeration — reproduced

**Missing.** D17/§3.2: "`presets` … 0 = stdout parsed as JSON". Parseability is not non-emptiness.

**Reproduced.** A datadir carrying the vendor bundle but no installed models:

```
$P --datadir $S/dd_empty --query-printer-models
rc=1  stdout=29B  stderr=0B
content: {"printer_models": ""}     ← parses as JSON
```

Under the plan slicelab exits **0** here, having enumerated **zero printers**, at the one verb whose entire job is establishing that a `[base]` name is nameable. A user or CI validating `[base]` against that output gets "there are no printers" delivered as green. Note the payload is an empty *string*, so both `len(...)` and `for m in ...` yield nothing without erroring.

**Action.** `presets` must adjudicate on **parsed and non-empty and shaped as expected**: JSON that parses but yields zero entries, or whose `printer_models` is not a list, is exit **2** with a named reason. Add it to `test_red_states.py` — the repro above is a ready-made fixture (vendor bundle + a `PrusaSlicer.ini` declaring no models).

---

## G4 — HIGH: `coerced → refused (1)` claims knowledge slicelab does not have, and produces false reds on correct slices

**Missing.** §4 asserts `coerced` means "*we **established** the intent was not honoured*". slicelab cannot distinguish "the engine silently ignored you" (V1: `--perimeters 4.7` → 4) from "the engine applied a documented dependent constraint". Both appear identically in the readback.

**Reproduced** — a correct spiral-vase slice, three keys coerced, artifact produced fine:

```
$P --export-gcode $S/cube.stl -o $S/b.gcode --save $S/r_geo.ini \
   --spiral-vase=1 --perimeters=4 --top-solid-layers=5 --fill-density=60%
rc=0   b.gcode = 41106 bytes
resolved: perimeters = 1   top_solid_layers = 0   fill_density = 0%
```

Under the plan: three `coerced` keys → `refused` → **exit 1, no lock written, artifact not promoted**, for a slice PrusaSlicer performed exactly as designed. This is the silence rule inverted — the failure mode the plan itself names for `verify` under D8 — and it is at the tool's front door. R2 frames this as a *usability* risk ("refusal rate"); it is an *epistemic* one: the verdict word is wrong, not merely strict.

I also confirmed the plan is right that `resolve` previews `slice` faithfully here: `--save` with and without geometry produced a **0-line diff** across the full resolution, including the spiral-vase normalization. So `resolve` will reproduce the false red without slicing — cheap to measure, which is the mitigation.

**Action.**
1. Split `coerced` into `coerced` (value changed, no known dependent constraint) and `normalized` (value changed by a constraint slicelab probed and recorded). `normalized` is at most `incomplete` (2) with the constraint named, never `refused`.
2. Failing that, do not claim "established"; state that `coerced` means *requested ≠ resolved, cause unknown* and fold it to **2**, and say why in D14. The current wording asserts a cause slicelab did not establish — the §2.3 pattern one level up.
3. R2's ≥50-file corpus must be run **before** #4 ships, not before 0.1.0. It is the only thing that sizes this.

---

## G5 — HIGH: the epic schedules its architecture-deciding issue last; it is layered, not vertical

Asked directly, so answered directly: **partly vertical, and broken exactly where it matters.**

- #1 self-declares "*Not a release on its own*" — honest, but it means the epic is not fully vertical by its own admission.
- #2, #3, #4, #7 genuinely ship alone. Good.
- **#9 (OrcaSlicer readback) is the problem.** The plan calls it "**The issue that decides the architecture**", and D1's supersede clause says that if the Orca readback cannot be built without engine-specific logic leaking into `readback.py`, "**the core has no reason to exist and slicelab splits into two per-engine tools**". That verdict arrives after `resolve`, `slice`, `explain`, `probe` and `verify` have all been built on the seam it is testing. R1's mitigation — "#9 puts Orca inside v0.1.0 so it votes before the schema is released" — is true about *release* and false about *cost*: it votes after eight issues of implementation.
- #8 `verify` is blocked on #7 `probe`, but `verify --tier config` needs nothing from probe. Artificial serialization.
- #10 (SuperSlicer red-state fixture) is blocked on #9 for no technical reason — it tests `readback.py`, which exists at #4.

**Action.** Split #4 into **#4a readback core + PrusaSlicer** and **#4b Orca readback over the same `readback.py`**, and make #4b a blocker for #5. The dossier already proves #4b is small: the plan's own V11 sliced stock Creality at `rc=0` with zero synthesis and got a 626-key `--export-settings` readback. Moving it forward costs days and buys the architectural vote before `slice`, `probe` and `verify` are written against the seam. Also unblock `verify --tier config` from #7 and #10 from #9.

---

## G6 — MEDIUM: dossier findings the plan dropped or softened

I diffed the plan against every track. These did not land:

1. **The fullcontrol track's four reproduced upstream silence defects are gone entirely.** `check.py`'s bare `exit()` returning **exit code 0** on an error path (reproduced end to end in the dossier); a misspelled `initialization_data` key silently ignored producing the wrong nozzle temperature at exit 0; `printer_name=None` falling back to the `generic` profile with only a `print()` — structurally identical to orlab's `profile_exact`, silence.html case 3; and a `custom` profile emitting a complete print with zero extrusion at exit 0. The plan's escalation #7 lists only the two PrusaSlicer defects. Four reproduced cases, in a library the org may yet depend on, are simply not in the plan. **Action:** add them to escalation #7 as candidate external silence.html cases with their reproductions, or state explicitly that they are out of scope because FullControl is deferred — but do not let them evaporate.
2. **The netspec/gerberdiff argparse exit-2 leak is measured and then abandoned.** V14 records it and uses it to justify `test_usage_exit_64.py`, but nothing proposes filing it. The org contract §2 is emphatic: "*When you file an instance, label it `silence-defect` and add it to the record in the same sitting… The count is the argument, so a record that undercounts makes the case weaker than the evidence supports.*" A caller reading `2` as "could not tell" currently gets it for a typo, in two shipped members. **Action:** add to §9.2 as escalation #8.
3. **The org contract's own §6.2/§6.3 contradiction is noted and left standing.** V14 correctly says "Cite §6.3. Never §6.2." — but §9.2 routes the §9 licence-table omission to the org and leaves the §6.2 stale table unfiled. Both are §2.5 status-claim defects in the same file. Inconsistent handling. **Action:** one line in §9.2.
4. **`layers` provenance is mislabelled.** The lock says `layers = { provenance = "slicelab_derived:count(;LAYER_CHANGE)" }`. The slicespec track established `;LAYER_CHANGE` / `;HEIGHT:` / `;TYPE:` are *the slicer's own segmentation of its own output* — and that `;HEIGHT:` is internally inconsistent under `z_offset` (0.4 at the layer change, 0.3 on the extrusions of the same layer). Counting the slicer's markers is not slicelab-derived. **Action:** `provenance = "slicer_marker_count:;LAYER_CHANGE"`. Trivial fix; the plan polices exactly this overclaim everywhere else.
5. **The `--key=value` empty-value boundary is understated as one option.** The plan states it as "`--post-process=` (empty value) → rc=1". I measured it is a **class**: `--filament-notes=` and `--bed-custom-texture=` both give `rc=1  No value supplied for --X`. "Clear this key" is unexpressible for every string-valued option, not one. Separately, `--compatible-printers-condition=` gives `Unknown option` — a real config key with **no CLI option at all**, which means `[prusaslicer.set]`'s authored surface is the *CLI-option* set, not the *config-key* set, and the plan never says which. **Action:** state the surface in D5; widen the boundary sentence.

**Wasted track?** No track is fully wasted, but **fullcontrol is the closest**: its output reduced to one deferral row and one refuted-claim row, with its four reproduced defects dropped (item 1). Its unique architectural finding — `fc.import_design()` exists, so "no geometry input" was false and the real argument is *artifact kind* — did land correctly in §8. So: not wasted, but under-harvested, and the under-harvested part is exactly the org's own founding subject matter.

---

## G7 — MEDIUM: unverified claims presented as settled

The plan is unusually disciplined here — §2.3 and §10 are genuinely honest and I found no fabricated numbers. Three residual items:

1. **"`--key=value` works for every option type" (V9, D5) is generalized from 11 probes and D5 is load-bearing** — it "deletes the need to vendor an AGPL option catalogue (D11)". I probed 14 more forms and D5 **held** for negatives (`--z-offset=-0.15`), vectors (`--nozzle-diameter=0.4,0.6`, `--extruder-offset=0x0,10x0`, `--first-layer-bed-temperature=60,60`, `--wiping-volumes-matrix=0,140,140,0`), semicolon lists (`--filament-type=PLA;PETG`), multiline G-code, and bracket templates — all rc=0. So D5 survives adversarial probing better than the plan claims. **Say so with the numbers**, and note the empty-value class (G6.5). *Settling command:* the 411-option sweep in G2.2 settles D5 and R6 in the same pass.
2. **"`resolve` previews `slice`" is assumed, never stated or tested.** I settled it: `diff` of `--save` with and without geometry = **0 lines**, including spiral-vase normalization. That is a fact the plan depends on for issue #4 shipping alone and does not assert. **Action:** make it a test (`test_resolve_matches_slice_config`), because it is a per-build fact that can regress silently.
3. **`--info` combined with `--export-gcode` in one invocation** — the plan puts `[inputs.geometry.mesh]` in the lock without saying whether it costs a second, ungated engine call. I settled it: it works in one invocation (`rc=0`, `gcode=604407`, stdout carries `size_x`/`facets`/`manifold`). Good news; state it, so nobody later "optimizes" it into a second call whose result is not gated on the artifact.

**Confirmed by me, independently:** V15 reproduces exactly, including from data rather than a flag — `--post-process=/bin/true </dev/null` → `rc=0`, **no artifact**, **0 bytes stderr**, an interactive `Continue(Y/N)?` on stdout; and `post_process = /bin/true` via `--load` → identical. D7's artifact gate is well founded.

---

## G8 — MEDIUM: questions a competent engineer asks on first reading that the plan does not

1. **"What validates `[base]`?"** Nothing does. See G1. The plan's own dossier established `print_settings_id` is unvalidated free text that a `--load`ed ini can lie about, and that preset names do not determine the configuration. The lock records; it never checks. This is the first question anyone asks and the plan has no section for it.
2. **"What happens on the second run?"** `slice` writes `not_established`; `verify --tier artifact` exits 2 on anything but `reproducible`; `probe` is a separate verb. So the default lifecycle is: slice → lock → verify → **2**, forever, unless the user remembers to run `probe`. R3 spots the cost but not the shape. **Action:** state the intended lifecycle explicitly, or have `slice` run a 2-run probe by default with a documented cost.
3. **"Which engine invocation produces the lock?"** The plan implies one combined `--export-gcode --save --info` call, but never names the invocation count or asserts they are one. Given V4 and V15, "captured in the same invocation" is load-bearing enough to be a field: add `engine_run.invocations = 1` and assert it.
4. **"What is the migration story when the lock's `version` bumps?"** `read.py` says "Newer major → exit 2, never best-effort" — good — but nothing says what an *older* major does, and R1 says a `version` bump is the fatal outcome. No migration path is described.
5. **"Is `refused` distinguishable from `refused-preflight`?"** D15 and D16 both refuse pre-flight at 1 without touching the engine; `coerced` refuses at 1 after a full slice into scratch. Same exit, same word, wildly different cost and evidence. `reason` covers it — but the plan never says the report must distinguish them.

---

## G9 — LOW/MEDIUM: §10 escalation handling

The plan's §9.2 is genuinely good — it routes the six real ones (two-repos-green, A5, §4 deviation, `unsupported` fold, runtime deps, PyPI name) with options and recommendations. Two gaps:

1. **D22 and D13 bind an unbuilt sibling from slicelab's DECISIONS.md.** D22 decides slicespec's dependency direction; D13 makes "*slicespec's contracts must be in Python*" the tripwire proving slicelab's §4 deviation was honest. Recording intent is fine; making another member's design the *test of your own honesty*, from your own repo, is at least adjacent to §10's "extracting shared code / decisions across members". **Action:** move the slicespec-must-be-Python tripwire into escalation #3 (which already goes to the org) rather than leaving it as a slicelab-local decision about a different tool.
2. **Editing the org contract's §9 licence table** is presented in §6 as a to-do, while the §4 amendment in §9.2#3 is correctly routed to the org. Same file, same class of change, two different handlings. **Action:** route both.

Otherwise: the plan correctly identifies option A (import prusaslicer-py) as the §10 trap and declines it, and correctly routes zero-dependencies. No agent decision in the plan reverses a numbered decision in another repo.

---

## What is genuinely sound — stated once each, no manufactured findings

- **D7 (stage-then-promote + `destination_prehash`)** closes prusaslicer-py D5's stated hole structurally, and V4/V15 both reproduce for me. Sound.
- **D2 (empty core vocabulary, engine-namespaced keys from commit one)** is the correct answer to the PrusaSlicer-shaped-abstraction risk, and D3's admission-by-measurement is the right gate. Sound.
- **D10 (container sniff, never silently force `--binary-gcode=0`)** — correct, and correctly identified as the *default* path for the current Prusa line, not an edge case.
- **D8 (reproducibility as a measured value, not an assumption)** and the false-red reasoning behind it are right.
- **D11 (zero engine-derived bytes)** correctly separates linking from copying and inherits prusaslicer-py D8's reasoning rather than the stale org default. Sound.
- **D18/D19 (per-package launch-form probe; stat-and-grant every Plan path; refuse on untranslatable path)** — all three fix real reproduced defects and the fix-on-copy of `_to_engine_path` is exactly right.
- **The `unknowns` field** is the best idea in the document; the under-claim/over-claim asymmetry argument for it is correct.
- **§2.3, §10 and the refuted-claims table** are honest work — the plan drops its own load-bearing claims when they were refuted, which is rarer than it should be.

---

## Prioritised action list

| # | Action | Closes |
|---|---|---|
| 1 | Make `sliced` unreachable with an empty subject set: add `resolution.keys_checked`, an `unknowns` code, and a red-state test for a base-only intent | G1 |
| 2 | Probe the 411-option → config-key map at characterisation; record `readback_key` per key; make an unmapped option exit 64 | G2 (also settles D5/R6) |
| 3 | `presets` adjudicates on parsed **and non-empty and shaped**; add the `{"printer_models": ""}` fixture to `test_red_states.py` | G3 |
| 4 | Split `coerced` from `normalized`; run R2's ≥50-file corpus before issue #4 ships, not before 0.1.0 | G4 |
| 5 | Split #4 into #4a/#4b so Orca votes on `readback.py` before `slice`/`probe`/`verify` are built on it; unblock #8-config and #10 | G5 |
| 6 | Restore the four FullControl silence cases and the netspec/gerberdiff exit-2 leak to escalation #7/#8; file the §6.2 contradiction | G6.1–3 |
| 7 | Relabel `layers` provenance; widen D5's empty-value boundary to a class; state whether `[set]`'s surface is CLI options or config keys | G6.4–5 |
| 8 | Add `test_resolve_matches_slice_config` and `engine_run.invocations`; state the lifecycle and the older-major migration path | G7.2, G8.2–4 |
| 9 | Route the slicespec-Python tripwire and the §9 licence-table edit through the org, not slicelab's DECISIONS.md | G9 |

**If only one thing is done: G1.** The plan's entire claim to membership under §1 test 2 rests on one mechanism, and today that mechanism runs over an empty set on the most ordinary input the tool accepts, and still prints the green word.
