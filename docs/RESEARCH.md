# Research

What the research established, what it refuted, and what it could not settle.

The third list is not an appendix. Per the org contract's section 7, an
unverified claim presented as fact is the defect this organisation exists to
prevent — so it is here, with the command that would close each gap.

**Provenance.** 2026-09-06, a 10-track pass (37 agents) briefed to prefer running
a command over reading a document. 20 load-bearing claims went to adversarial
verifiers; 16 came back changed. Reproductions are tagged `V1`–`V15` in
`notes/evidence.md`; gaps found by attacking the result are `G1`–`G9` in
`notes/critique.md`.

**Everything below is one x86_64 Debian 13 host**, PrusaSlicer 2.9.6 and
OrcaSlicer 2.4.2, both Flatpak.

---

## 1. Established, with a command

| Finding | Tag |
|---|---|
| PrusaSlicer silently coerces an out-of-type override at exit 0 with zero bytes on stderr (`--perimeters 4.7` becomes `4`). | V1 |
| An unknown key in a `--load`ed ini is silently discarded, exit 0, zero stderr. | V2 |
| `--config-compatibility=disable` catches the value case and is blind to the key case. It does not exist on OrcaSlicer. | V3 |
| `--save` runs before the slice block: an out-of-bounds object gives exit 0, no G-code, and a complete 9957-byte config anyway. | V4 |
| `--query-printer-models` returns **exit 1** with 6550 bytes of valid JSON — the same code as "not found". | V5 |
| A partial preset triple is a deterministic SIGSEGV: rc=139, 0 bytes on both streams, 6/6 runs. The same signature arises from an unrelated flag, so it carries no cause. | V6 |
| `binary_gcode = 1` is the stock default for the current Prusa line. An MK4IS slice emits a `GCDE` container with **zero** config-footer keys; MK3S emits ASCII with 375. | V7 |
| Determinism is per-option. `--fuzzy-skin all` gives 3 distinct normalized hashes and 3 distinct filament-used values in 3 runs. | V8 |
| `--key=value` works for every option type probed. The space form fails. An **empty** value is not expressible for any string-valued option. | V9 |
| Flatpak launch-form exit fidelity differs per package: PrusaSlicer's entrypoint always returns 0 and needs the `--command=` bypass; OrcaSlicer's does not and is harmed by it. | V10 |
| OrcaSlicer 2.4.2 slices stock non-Bambu profiles at exit 0 with no synthesis, and exports a 626-key JSON readback. **The readback seam is engine-neutral.** | V11 |
| Orca reflects CLI overrides in that readback, and rejects unknown ones loudly at rc=254. | V12 |
| Orca writes `00000.log` into the process CWD on a failing run; `result.json` is conditional and its `return_code` is branchable. | V13 |
| netspec and gerberdiff both declare `EXIT_USAGE = 64` and return 2. `orlab which` returns 1 for a missing engine. The org contract's section 6.2 table is stale. | V14 |
| **New upstream defect:** a post-process script in the *config* makes PrusaSlicer 2.9.6 print an interactive prompt to stdout and read stdin — headless, exit 0, no artifact, zero stderr. Reachable from data, not only from a flag. | V15 |

## 2. Refuted — do not build on these

Full text with the sharpened version of each is in `notes/refuted.md`.

| The proposal assumed | What is actually true |
|---|---|
| The G-code config footer is the complete resolved configuration, so the lock can be derived from the artifact. | Only for ASCII output, which is **not** the default for the current Prusa line [V7]. And the footer/`--save` cross-check is tautological: both are serializations of the same in-memory object. |
| Slicing is deterministic, so a G-code SHA256 is an identity. | False per-option [V8]. Reproducibility must be a **measured value** (D8), and even a normalized hash is same-machine-only. |
| Preset names plus an engine version pin the configuration. | The datadir's *selected GUI presets* leak into CLI resolution, and the vendor bundle auto-updates over the network while still declaring the same `config_version`. Addressable is not sufficient. |
| The five outcome names (`sliced`/`engine_error`/`unsupported_version`/`invalid_profile`/`incomplete`) are implementable. | Two of the causes are empirically indistinguishable [V6]. Causes are demoted to a `reason` field (D14). |
| An Apache-2.0 slicelab cannot import GPL-3.0 FullControl. | Apache-2.0 is one-way compatible with GPLv3. The constraint is on a conveyed distributable, and the integration mode was never decided. The real blocker for a native backend is artifact kind, not licence. |
| No non-Bambu Orca profile can be sliced as shipped. | 1944 of 2333 non-BBL instantiable process profiles carry their own `compatible_printers` [V11]. The real gate hits ~16.7%. |
| prusaslicer-py's extracted CLI-surface corpus is reusable. | It is gitignored and absent by its own D8. Its parser, run against Orca's help, produced 53 plausible records with `value` populated on **0 of 34** placeholder lines — and exited clean. |
| A lock that stores a hash instead of the settings inline is a licensing measure. | It is not. The committed `part.gcode` already carries the same vendor payload. The surviving reasons are diff noise, lock size, and secret hygiene — `--save` emits `printhost_apikey` in cleartext where the G-code footer strips it. |

## 3. Corrections applied before any code

From `notes/critique.md`. These are constraints on the implementation, not
suggestions.

- **G1 — `sliced` must be unreachable with an empty subject set.** "Every
  requested key came back applied" is vacuously true with zero requested keys, and
  a base-only `slice.toml` is the first file anyone writes. The mechanism
  adjudicates the *authored delta* and only *records* the base; the design must
  say so, and the outcome must distinguish the two cases.
- **G2 — Map option names to config keys by probing, not by string transform.**
  411 CLI options, 343 config keys, 70 options with no matching key, 2 keys with
  no option. `--after-layer-gcode` writes `layer_gcode`, producing a false
  `absent` on a perfect run.
- **G3 — Adjudicate discovery on parsed *and non-empty and shaped*.** A datadir
  with the bundle but no models returns `{"printer_models": ""}`, which parses.
- **G4 — Split `coerced` from `normalized`.** slicelab cannot distinguish "the
  engine ignored you" from "the engine applied a documented dependent
  constraint"; a correct spiral-vase slice coerces three keys. Claiming
  "established" for both asserts a cause slicelab did not establish.
- **G5 — Let the second engine vote early.** The Orca readback is the issue that
  decides the architecture, so it must land before `slice`, `probe` and `verify`
  are built on the seam it tests.

## 4. Could not establish

Every item is a real gap, and none of it is designed around as though settled.

| Open question | What would close it |
|---|---|
| Is any normalized hash portable **across machines or architectures**? | Run the probe on a second host with a different CPU. Until then `verify --tier artifact` is contractually a same-machine check and every lock carries `cross_machine_reproducibility_unestablished`. **There is no way to close this by reasoning.** |
| Are V6 (SIGSEGV) and V15 (post-process prompt) present in a **native**, non-Flatpak PrusaSlicer 2.9.6? | An upstream AppImage. Debian trixie ships 2.9.2 — a different version, so a weak control. Required before either is reported upstream as a general defect. |
| Is the set of nondeterministic settings complete? | It has exactly one confirmed member per engine build. A systematic sweep over the FFF option space, **per build** — a fact that must be re-measured, never assumed. |
| Does the OrcaSlicer **GUI** resolve `inherits` correctly for the files its CLI fails on? | One headless-X GUI run exporting project settings, diffed against a hand-flattened chain. Established from source so far, not from a GUI run. Required before D21's probe can be trusted. |
| Does the datadir preset-selection leak extend beyond one key? | The same triple across N datadir selections including a multi-extruder target; diff all 376 keys. |
| Can the vendor bundle be pinned against auto-update? | Re-run first launch and a CLI slice with the network denied, watching the index mtime. Known: a pure CLI `--save` does not touch it; the GUI rewrote it on startup. |
| Is `--key=value` exhaustive across list-valued options? | Enumerate every placeholder option from `--help-fff` and probe each with `=`. This is the same sweep that settles G2, so do them together. |
| What is slicelab's actual **refusal rate**? | A corpus of >= 50 real `slice.toml` files. Unmeasured, and it is the single number that most determines whether the tool is usable rather than merely correct. |
| Would the engine vendors consider a lock embedding resolved profile values a redistribution? | Ask them. Their READMEs assert a maximalist AGPL reading their licence text does not support. Cheap to settle before shipping the embed. |
| CuraEngine — **anything at all**. | `apt-get install cura-engine` and run it. Every claim about its CLI shape or setting vocabulary is unverified. It is also the strongest test of whether `readback_source = "unavailable"` is a real branch or a theoretical one. |
| SuperSlicer's *installed* behaviour. | Not installed. Every statement about it comes from source and release metadata. D23 keeps it as a test fixture precisely because that is cheap and an adapter is not. |
