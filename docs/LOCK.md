# `slice.lock`, schema version 1

What `slicelab slice` records about a run it stands behind. This is the file
`slicespec` reads (D22) — as a **file**, never by importing slicelab — so it is a
contract rather than an implementation detail.

**Read `schema_version` first.** It is the first key in the file and it is not inside
a table, so a consumer can decide whether it understands the document before parsing
the rest. Version 1 is what this page describes. A reader that finds a number it does
not know should stop rather than guess which fields still mean what they did.

## When a lock exists

Only for a run that exited **0** (`sliced`). The file's presence is the claim, which
is why there is no `outcome` field: a value that cannot vary tells a reader nothing
and invites branching on it as though it could.

In particular `empty` (exit 3) writes **no lock** while still handing over its
artifact — D24, because a lock records a resolution slicelab verified and `empty`
verified none. So a G-code file with no lock beside it is a real state, and it means
the intent asserted nothing.

The lock is named after the intent: `slice.toml` → `slice.lock`, `part-a.toml` →
`part-a.lock`. Two intents in one directory therefore cannot overwrite each other's
record.

## The three ways a value can be absent

TOML has no null, so absence is expressed structurally and the three cases are
distinct on the wire:

| what you see | what it means |
| --- | --- |
| the field is missing | this engine reports nothing of the kind |
| the field is a table with `reason` and no `value` | the engine reported something that is not a measurement |
| the field is missing **and** `unknowns` names it | slicelab could not establish it, and says why |

The second is the one worth dwelling on. `filament_g` with
`reason = "filament_density_zero"` means the engine printed a mass and that mass was
`0.00` because the filament profile declares no density. The extrusion length beside
it is real. Reading the zero as a mass is the mistake the structure exists to prevent.

## Top level

| key | type | meaning |
| --- | --- | --- |
| `schema_version` | integer | this document's version. Read it first. |
| `values_resolved` | boolean | always `false`. See below. |

`values_resolved = false` is D6, and it is not a placeholder. Both supported engines
export a resolved *configuration document*, not resolved values: PrusaSlicer reports
`extrusion_width = 0` and `first_layer_extrusion_width = 200%` while the toolpaths
were generated at 0.45 mm and 0.70 mm. Those real numbers exist only as free-text
header comments in a different vocabulary. Treating `effective_config` as "the
numbers the engine used" is wrong, and this field says so in the file.

## `[reproducibility]`

| key | type |
| --- | --- |
| `scope` | string — `cross_machine` |
| `state` | string — `not_established` |
| `reason` | string |

`slice` always writes `not_established` (D8). No single host can establish that a
normalized hash is portable; only a second machine can. A later `probe` verb writes
the same two fields with a state it measured and the observed hash set, so a consumer
branches on `state` and does not need to know which verb produced the file.

## `[intent]`, `[engine]`, `[readback]`

`[intent]` carries `path` and `sha256` — slicelab hashing the `slice.toml` it read.

`[engine]` carries `name` and `launch` (the launch form, verbatim, because which
launcher works differs per package and slicelab measures rather than assumes), plus
`version` and `digest` when the engine stated them.

`[readback]` carries `path` and `redacted_keys`: the credential-bearing keys that were
found and removed. **An empty list is a real answer** — under no preset the engine
emits none of them — and it is not the same as not having looked.

## `[artifact]`

| key | type | meaning |
| --- | --- | --- |
| `path` | string | where the G-code was promoted |
| `container` | string | `gcode` or `bgcode`, sniffed from the file's first four bytes |
| `raw_sha256` | string | every byte of that file |
| `destination_prehash` | string | sha256 of what this run displaced, absent when nothing was there |
| `[artifact.normalized]` | table | see below |

`container` is measured from the artifact, never assumed from a flag slicelab passed
(D10). `bgcode` is the stock default across the current Prusa line, so it is the
common case and not an edge one, and slicelab never silently forces it off — that
would change the artifact the author asked for.

`destination_prehash` exists because "this file is here" does not establish "this run
wrote it" (D7). An mtime check was measured and rejected: 198 of 200 tmpfs writes had
identical `st_mtime_ns`.

### `[artifact.normalized]`

| key | type |
| --- | --- |
| `substitutions` | integer |
| `sha256` | string, absent when `substitutions` is 0 |
| `reason` | string, present instead of `sha256` |

The hash of the artifact with its run-to-run variation removed, which is what makes
two runs comparable. `substitutions` travels with it because the count is what makes
it interpretable: measured on PrusaSlicer 2.9.6, two slices of one mesh differ in
exactly one line of 23422 — the generation timestamp — and the byte counts are
identical, so comparing sizes would call the two files the same.

A count of **0** means the pattern matched nothing, so the artifact is not in the
format the rule was measured against. The hash is then withheld and the run is
`incomplete` rather than `sliced` (D9) — which means no lock is written at all. Never
a silent fallback to publishing the raw hash under the normalized name.

The whole table is **absent** when the container carries no text footer, with
`container_carries_no_text_footer` in `unknowns`. That is D10 and not a failure.

## `[geometry]`

| key | type | coordinates |
| --- | --- | --- |
| `mesh_sha256` | string | — |
| `[geometry.mesh_bbox]` | table | **model** |
| `[geometry.plated_footprint]` | table | **plate** |

There is no field called `bounding_box`, deliberately. The two boxes answer different
questions and a reader who conflates them gets a part in the wrong place with a lock
that agrees.

`mesh_sha256` is slicelab hashing the mesh file. It needs no engine, so the input is
identified even when the engine describes nothing.

`mesh_bbox` carries `source`, `key`, `min_mm`, `max_mm`, and optionally `facets`,
`volume_mm3` and `manifold` — the fingerprint. In **model** coordinates, before the
engine placed anything. No size is recorded: it is `max_mm - min_mm`, and a difference
slicelab computed sitting beside its own inputs invites a reader to check one against
the other and call the agreement evidence. `manifold` is absent rather than `false`
when the engine's spelling is unrecognised: a mesh reported in words slicelab does not
know is not a mesh reported as open.

`plated_footprint` carries `source`, `key` and `objects`, each an array-of-tables entry
with `name` and `polygon`. **Plate** coordinates, XY only — the engine reports no
plated Z extent, and combining the polygon with a height would produce a box half
measured and half derived with nothing marking which half. The polygon is the engine's
own, point for point: an extent cannot tell a rotated part from an axis-aligned one.

## `[stats]`

One table per reported number, each carrying its provenance:

| key | type |
| --- | --- |
| `source` | string — where the number came from, as a category |
| `key` | string — the producing system's own name for it, verbatim |
| `value` | number, absent when there is none |
| `reason` | string, present instead of `value` |

The field names are a closed set: `filament_mm`, `filament_cm3`, `filament_g`,
`print_time_s`, `layers`. Closed because an open set is how a field nobody measured
arrives — a consumer can ask whether a name belongs.

`source` is a category, never an engine key. `gcode_footer` means the artifact's own
comments. `slicer_marker_count` means slicelab counted a marker because the engine
reports no total: PrusaSlicer states no layer count at all, so `layers` is
`;LAYER_CHANGE` counted, and the lock says that rather than letting a counted number
read as a stated one.

`key` is the engine's spelling kept verbatim, which is what lets a reader check the
claim against the artifact without knowing how slicelab is built.

A note for whoever writes a checker: comparing `stats` against the artifact's footer
is **circular**, because both are the same slicer utterance (D22). The lock is a
check's premise, never its evidence.

## `[[unknowns]]`

An array of tables, one per thing slicelab could not establish:

| key | type |
| --- | --- |
| `code` | string, from a closed set |
| `detail` | string, for a human |
| `fields` | array of strings — the lock paths this cost |

An empty array is a real answer and means nothing was unestablished. Codes in use:

- `container_carries_no_text_footer` — the artifact is a binary container, so no
  artifact-derived stat and no normalized hash. D10 makes `verify --tier artifact`
  exit 2 on this.
- `filament_density_zero` — a mass was printed and is not a measurement.
- `artifact_header_not_recognised` — normalization matched nothing.
- `engine_described_no_mesh` — no mesh facts; `mesh_sha256` is still present.
- `artifact_stated_no_placement` — the artifact named no object placement.

Branch on `code`. `detail` is prose and may be reworded; `fields` names what is
missing so a reader does not have to infer it from an absent key.

## `[effective_config]`

The engine's resolved configuration document, embedded — every key it emitted, with
credential-bearing values replaced by `<redacted>` and those keys listed in
`[readback].redacted_keys`.

Embedded rather than referenced on purpose: the readback file beside the intent is
rewritten by the next run, so a lock pointing at it would start disagreeing with
itself while nothing about its own slice had changed. A premise with a dangling
reference is not a premise. The readback file still exists (D31) because it is the
engine's own bytes; this is slicelab's transcription of them.

Read it as configuration, not as a public artifact, until you have looked at it. It is
redacted against a measured list of credential keys, and a key the engine adds in a
future build is a key nothing has measured yet.
