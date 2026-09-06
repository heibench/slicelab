# notes/

**Frozen analysis that the decisions and the tracker cite.** Nothing here is
maintained. Each file records what was observed on a specific date, on a specific
host, against specific engine builds — and it is useful precisely because it does
not get quietly updated when the world moves.

If something here is wrong, it stays wrong and a decision supersedes it. Do not
edit these files to match later findings; that destroys the record of what was
believed when a decision was made.

| File | What it holds |
|---|---|
| `evidence.md` | Reproductions, tagged `V1`–`V15`. Cited by tag from `docs/DECISIONS.md`, `AGENTS.md` and issues. |
| `refuted.md` | The load-bearing claims that did **not** survive adversarial checking, with the sharpened version of each. |
| `critique.md` | Gaps `G1`–`G9` found by attacking the finished plan, including a reproduced exit-0-establishing-nothing scenario in slicelab's own design. |

## Provenance

Produced 2026-09-06 by a 10-track research pass (37 agents, ~4.6M tokens) whose
brief was to prefer running a command over reading a document. Twenty
load-bearing claims were handed to adversarial verifiers instructed to refute
them; **sixteen came back changed**. `refuted.md` is that output.

Engines under test throughout:

- PrusaSlicer **2.9.6**, Flatpak `com.prusa3d.PrusaSlicer`
- OrcaSlicer **2.4.2**, Flatpak `com.orcaslicer.OrcaSlicer`
- One **x86_64 Debian 13** host, GNOME 50 runtime

SuperSlicer, CuraEngine and FullControl were **not installed**. Every statement
about them comes from source and release metadata, not from a run. See
`docs/RESEARCH.md` for the full unverified list.

## The one caveat that reaches every file here

Every determinism, identity and normalization measurement is **one host, one
build, one architecture**. Nothing in these notes establishes that a normalized
hash is portable across machines, and no amount of reasoning can close that —
only a second machine can.
