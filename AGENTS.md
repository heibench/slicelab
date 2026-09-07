# AGENTS.md — slicelab

Instructions for humans and AI coding agents working in this repository.

The org-wide contract at <https://github.com/heibench/.github/blob/main/AGENTS.md>
is the floor. This file carries what is specific to slicelab; where the two
conflict, this file wins.

## Project

`slicelab` is a **driver**, not a checker. It puts a Slic3r-descended slicer under
program control and records exactly what that engine resolved. It does not
adjudicate G-code — that is `slicespec`'s job, and it does not exist yet.

**One mechanism justifies the whole tool and nothing else does:** ask the engine
what it *actually resolved*, diff that against what was requested, per key, and
refuse to call the run green when they disagree.

Everything else — the lock file, the multi-engine story, a native backend —
is downstream of that one move. If the readback diff is ever weakened, delete
the project rather than ship it.

**Status: pre-alpha. Two verbs work: `slicelab which` and `slicelab presets`.**
`which` discovers an installed engine, probes whether that engine's exit status
can be believed, and reports its identity. `presets` enumerates an engine's
printer presets, adjudicated on the JSON rather than the exit code. Nothing
slices, reads a `slice.toml`, or writes a lock.

Treat this section as code: the moment another verb works, this paragraph is
false and the change that made it work is not finished until it is corrected
(org AGENTS.md 2.5). It has been corrected once when the exit map landed, once
when `which` did, and once when `presets` did — stated as causes rather than as
a tally, because the tally in `SECURITY.md` kept being the stale claim.

## Start here

1. `docs/DECISIONS.md` — numbered decisions, with the reasoning that produced each.
   Do not relitigate a numbered decision; if it is wrong, add a superseding entry.
2. `docs/RESEARCH.md` — what was empirically established, what was refuted, and
   what remains unverified. Read the third list before planning anything.
3. `notes/` — the frozen dossier the decisions cite. `notes/evidence.md` carries
   the reproductions; issues and decisions cite them by tag.

## Stack

- **Python >= 3.11** (`tomllib`), packaged with `hatchling`, `uv` against a
  committed `uv.lock`.
- **No runtime dependencies.** `tomllib`, `hashlib`, `subprocess` and `argparse`
  are stdlib. Adding one is org AGENTS.md section 10 — escalate, do not decide.
- **Tooling** — `ruff` (format + lint), `mypy` (types), `pytest`, `just`,
  `pre-commit`.

## Commands

```sh
just setup          # uv sync
just fmt            # format + autofix
just check          # fmt-check + lint + typecheck (CI-equivalent)
just test           # run tests; engine tests skip when no slicer is installed
just test-engine    # run tests and FAIL if no engine is installed
just hooks          # every pre-commit hook over the whole tree
```

Run `just check && just test` before every commit. Never `--no-verify`.

## The rules that are not negotiable

Each is a decision with evidence behind it. The tag in brackets is the
reproduction in `notes/evidence.md`.

1. **The readback diff is the mechanism; a compatibility flag is not** (D4).
   Every authored override is compared against the engine's own resolved output.
   PrusaSlicer silently coerces `--perimeters 4.7` to `4` at exit 0 with zero
   bytes on stderr [V1], and silently drops an unknown key from a `--load`ed ini
   the same way [V2]. `--config-compatibility=disable` catches neither [V3], and
   does not exist on OrcaSlicer.
2. **Capture is gated on the artifact; the artifact is staged then promoted**
   (D7). `--save` runs before the slice block and is not conditioned on it: an
   out-of-bounds object gives exit 0, no G-code, and a complete ini anyway [V4].
   A run that did not write the file must never report as one that did.
3. **The core vocabulary is EMPTY** (D2). Authored keys are the engine's own
   native names under an engine-namespaced table. `CORE_KEYS == frozenset()`,
   asserted by a test. A key enters only through D3's recorded admission
   procedure. A vocabulary written from one engine *is* the PrusaSlicer-shaped
   abstraction this project exists to avoid.
4. **Never adjudicate on an engine's exit code without probing it first** (D17,
   D18). `--query-printer-models` returns exit 1 with 6550 bytes of valid JSON —
   the same code it returns for "not found" [V5]. And the Flatpak entrypoint
   backgrounds its child, so *every* invocation returns 0 unless the
   `--command=` bypass is used [V10]. That bypass is mandatory for PrusaSlicer
   and harmful for OrcaSlicer. Probe per package; never copy it as a constant.
5. **Reproducibility is a measured value, never an assumption** (D8). Three runs
   of one part with `--fuzzy-skin all` gave three distinct normalized hashes and
   three distinct filament-used values [V8]. Without the measurement, a hash
   mismatch from fuzzy skin is indistinguishable from real drift and `verify`
   reports *violated* — a false red, which is the silence rule inverted.
6. **Ship zero engine-derived bytes** (D11). Engine help text, default key sets,
   preset catalogues and option metadata are generated on the user's machine into
   XDG cache and gitignored. The subprocess argument settles *linking* and says
   nothing about *copying*.
7. **No escape hatches** (org 2.1). No `--allow-coercion`, no
   `--allow-engine-drift`, no `--force-lock`. Shipping the escape hatch alongside
   the discipline means the discipline is never tested. `--report PATH` is the
   answer: machine-readable, naming exactly which key diverged.

## Outcomes and exit codes

Two levels, never one flat list — matching partspec's Status-per-check /
Verdict-per-part and netspec's D9/D26 split.

| Outcome | Exit | Meaning |
|---|---|---|
| `sliced` | 0 | Artifact exists, non-empty, **promoted by this run**, its config export captured in the *same invocation*, every requested key `applied`, `adapter.exact` true. |
| `refused` | 1 | slicelab established the intent was not honoured. The driver's analogue of *violated*: we looked, the answer is no. |
| `incomplete` | 2 | slicelab ran but cannot stand behind the result. **Never reachable from an unexamined success path.** |
| `empty` | 3 | The run verified nothing, because nothing was requested. Neither success nor a finding (D24). |
| `error` | 4 | Environment fault. Not a verdict on the intent. |
| — | 64 | Usage: slicelab's own argv. |

These are org contract **section 6.2**'s codes, which is now the settled org-wide
vocabulary: A1, A2 and A3 closed on 2026-09-06 and partspec, netspec and gerberdiff
all answer on the same five. slicelab conforms rather than chooses. Only the *words*
diverge, and deliberately — see D14.

**`empty` (3) is not `sliced`.** A `slice.toml` with a `[base]` triple and no
`[set]` keys produces a real artifact and verifies nothing — "every requested key
was applied" is vacuously true over zero keys. That run is `empty`, the artifact
is still promoted, and no lock is written. `3` is partspec's code for the same
idea and is **not** in §6.2's table; slicelab is the second member using it, and
that is escalated rather than assumed. See D24.

**`refused` outranks `incomplete`.** When one requested key is `coerced` and another
is `absent`, the run is `refused` (1), not `incomplete` (2). A finding about the
request stays a finding even when some other key could not be evaluated; the reverse
would let one unreadable key mask a real one. Taken from netspec D26, which settled
the same precedence for the verify layer — this is the driver's form of it, adopted
rather than re-derived.

The renderer prints the outcome word as the **first token** of output (D14). A
past-tense verb leading a non-zero run reads green to a human skimming CI logs.

## Constraints

- **`readback.py` knows no engine's option names.** Engine-specific logic lives
  under `adapters/<engine>/`. A structural test confirms it — scoped to the FFF
  config-key namespace, not to every string constant.
- **The `sliced` outcome must be unreachable with an empty subject set.** With
  zero requested keys, "every requested key was applied" is vacuously true, and
  a base-only `slice.toml` is the first file anyone writes. See G1 in
  `notes/critique.md`; this is the highest-priority correctness constraint in
  the project.
- **Map option names to config keys by probing, never by string transform.**
  411 CLI options, 343 config keys, 70 options with no matching key.
  `--after-layer-gcode` writes `layer_gcode`, so dash-to-underscore reports a
  false `absent` on a perfect run. See G2 in `notes/critique.md`.
- **Do not reimplement the engine's arithmetic.** The premise is that the engine
  knows what the slice is and we do not.
- **Do not write a test that reads a doc, reads the code, and diffs them**, and
  do not assert that a phrase appears in prose. A doc test must assert something
  executable.
- Always name an encoding when reading or writing engine output, and decode the
  engine itself with `errors="replace"` (inherited from prusaslicer-py D5).
- Do not add AI attribution to commits or PR descriptions — no co-author
  trailers, session links, or "generated with" footers.
- Do not name, link, or describe any private repository in public output.

## Related

Siblings, deliberately non-overlapping:

- `prusaslicer-py` — a narrow, finished, single-engine PrusaSlicer driver. It is
  **maintained separately and slicelab does not import it** (org section 5: the
  stable surface is never the Python API). Two files' worth of Flatpak path
  handling were copied with attribution and one fix; see D19.
- `partspec` — verifies CAD-as-code parts. `netspec` — PCB connectivity.
  `gerberdiff` — fabrication output. `orlab` — the reference DRIVE-layer member.
- `slicespec` — does not exist. When it does, it reads `slice.lock` as a **file**
  and never imports slicelab (D22).
