#!/usr/bin/env python3
r"""Give a freshly installed engine the configuration its verbs need, for CI.

A fresh install has no configuration, and D29 makes that an environment fault:
`slicelab resolve` and `slicelab slice` refuse at exit 4 rather than asking an
unconfigured engine to dump a configuration it does not have. On a developer
machine the engine has been launched at least once, so the directory is there and
nothing notices; on a runner it never has. `engine.yml` installed four engines and
configured none, and every engine-backed test that reaches `configuration_state`
failed from 2026-09-14 onward (#43).

**Running the engine once does not fix it.** Measured against the Flathub
PrusaSlicer 2.9.6 on 2026-10-13, with a scratch `--datadir`:

- `--help` with a fresh datadir exits 0 and creates **nothing**; the directory
  is still empty afterwards.
- A real `--export-gcode` with a fresh datadir does not create one either. It
  refuses: `Configuration wasn't found. Check your 'datadir' value.` followed by
  `Error while loading config from profiles: Failed to load data from the datadir`,
  and writes no G-code. The same message is what the macOS leg fails with, so the
  "second, separate shape" #43 saw there is this one root cause.

So the configuration has to be seeded, which is what this script does: the vendor
profile bundles the install already ships, plus the marker file. Measured with the
same engine: a datadir holding `vendor/PrusaResearch.{ini,idx}` and an EMPTY
`PrusaSlicer.ini` slices a 20 mm cube against the stock MK3S triple and exports a
576,670-byte G-code. The marker's content is not read -- `configuration_state`
documents the marker as saying "nothing about whether it is any good" -- but the
vendor bundle is, because the profile names the tests ask for live in it.

**The datadir is the caller's to name, and slicelab's resolver is a cross-check**
rather than the source. That is deliberate and not the obvious way round: slicelab
declares a location for the Flatpak form only, so on macOS, Windows and a PATH
install `where_configuration_should_be` answers `None` -- UNDETERMINED, meaning
"did not look" -- and a seeder driven by it could not seed the three legs that need
it most. The engine's datadir is a packaging fact the leg already knows.

Where slicelab DOES declare one, this compares the two and fails on a mismatch, so
the directory seeded and the directory the refusal checks cannot drift apart --
the defect `where_configuration_should_be`'s own docstring records, where one
answered the engine's default while the other checked the override.

The datadirs, each measured rather than assumed -- the first from the installed
engine, the other two from the engine naming them itself in a failing CI run:

- Flatpak: `~/.var/app/com.prusa3d.PrusaSlicer/config/PrusaSlicer`
- macOS: `~/Library/Application Support/PrusaSlicer`
- Windows: `%APPDATA%\PrusaSlicer` (`C:\Users\runneradmin\AppData\Roaming\PrusaSlicer`)

Where the install PUT its profiles is the caller's too, for the same reason: a
Flatpak deploy, an `.app` bundle's `Resources`, the portable zip's `resources`.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from slicelab.adapters import spec_for
from slicelab.engine.configured import (
    ConfigState,
    configuration_state,
    where_configuration_should_be,
)
from slicelab.engine.discover import discover

#: Where each engine keeps the bundles it reads profile names from, relative to its
#: configuration directory, and how the shipped layout maps onto it.
#:
#: PrusaSlicer reads `vendor/<Vendor>.ini` with a sibling `.idx`, and the install ships
#: those as flat files. OrcaSlicer reads a `system/` tree and ships one.
LAYOUT = {"prusaslicer": ("vendor", False), "orcaslicer": ("system", True)}


def _declare_installed_models(bundles: Path) -> str:
    """PrusaSlicer's marker, declaring every printer model the copied bundles define.

    An EMPTY marker is not neutral, which is the thing to know here. slicelab's check
    reads only the file's presence -- `configuration_state` says so -- but the ENGINE
    reads the file, and with nothing in it the triple resolves only part of the way:
    it slices, and the artifact comes out missing things that are not obviously
    related to configuration.

    Measured on this engine, one 20 mm cube against the stock MK3S triple, the only
    difference being this file:

    | | empty marker | models declared |
    | --- | --- | --- |
    | `; max_layer_z` in the footer | absent | present |
    | `; total filament used [g]` | 0.00 | 3.73 |
    | artifact | 576,670 B | 604,319 B |

    So an empty marker silently costs the lock its `plated_height_mm` and gives every
    mass a density of zero. The first version of this script wrote one, and the engine
    legs reported exactly that: `KeyError: 'plated_height_mm'` on all three, and the
    stats fixtures disagreeing with the artifact.

    Derived from the bundles rather than written out here, so the models declared are
    the models present and a bundle update cannot leave this behind.
    """
    sections = []
    for bundle in sorted(bundles.glob("*.ini")):
        models: list[str] = []
        model: str | None = None
        for line in bundle.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("["):
                model = line[15:-1] if line.startswith("[printer_model:") else None
            elif model is not None and line.startswith("variants"):
                variants = line.partition("=")[2].replace(" ", "").strip()
                if variants:
                    models.append(f"model:{model} = {variants}")
                model = None
        if models:
            sections.append(f"[vendor:{bundle.stem}]\n" + "\n".join(models) + "\n")
    return "".join(sections)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("engine", help="the engine to configure, as `slicelab which` names it")
    parser.add_argument(
        "--profiles",
        required=True,
        type=Path,
        help="the profiles directory this install shipped",
    )
    parser.add_argument(
        "--datadir",
        required=True,
        type=Path,
        help="the engine's configuration directory on this platform",
    )
    args = parser.parse_args()

    spec = spec_for(args.engine)
    if spec is None:
        print(f"error: no adapter named {args.engine}", file=sys.stderr)
        return 64
    if spec.config_location is None:
        print(f"error: {args.engine} declares no configuration location", file=sys.stderr)
        return 64
    if not args.profiles.is_dir():
        print(f"error: no profiles directory at {args.profiles}", file=sys.stderr)
        return 4

    found = discover(spec)
    if found.form is None:
        print(f"error: {args.engine} is not installed here: {found.reason}", file=sys.stderr)
        return 4

    directory = args.datadir.expanduser()
    # Where slicelab declares one, it has to be the same directory. Where it does not,
    # the refusal cannot fire on this platform anyway and the seed is for the engine's
    # benefit rather than the check's -- which is worth saying out loud in the log.
    declared = where_configuration_should_be(spec, found)
    if declared is None:
        print(
            f"note: slicelab declares no configuration location for {args.engine} on "
            f"this platform, so D29 cannot refuse here and this seed is for the engine"
        )
    elif declared.resolve() != directory.resolve():
        print(
            f"error: slicelab checks {declared} and this would seed {directory}",
            file=sys.stderr,
        )
        return 1

    subdirectory, as_tree = LAYOUT[args.engine]
    bundles = directory / subdirectory
    bundles.mkdir(parents=True, exist_ok=True)
    if as_tree:
        shutil.copytree(args.profiles, bundles, dirs_exist_ok=True)
        copied = sum(1 for _ in bundles.rglob("*") if _.is_file())
    else:
        copied = 0
        for shipped in sorted(args.profiles.iterdir()):
            if shipped.is_file():
                shutil.copy2(shipped, bundles / shipped.name)
                copied += 1

    marker = directory / spec.config_location.marker
    if args.engine == "prusaslicer":
        models = _declare_installed_models(bundles)
        marker.write_text(models, encoding="utf-8")
        print(f"{args.engine}: declared {models.count('model:')} models in the marker")
    elif not marker.exists():
        # OrcaSlicer reads a `system/` tree and needed nothing in its marker: its
        # engine-backed tests passed against an empty one on run 38497422988.
        marker.touch()

    state = configuration_state(spec, found)
    print(f"{args.engine}: {copied} profile files -> {bundles}")
    print(f"{args.engine}: marker {marker} ({marker.stat().st_size} bytes)")
    print(f"{args.engine}: configuration_state is now {state}")
    if declared is not None and state is not ConfigState.PRESENT:
        print(
            f"error: seeding did not satisfy the check it exists for ({state})",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
