"""`resolve` against OrcaSlicer, which is the issue that decides the architecture.

D1's supersede clause: *if the Orca readback adapter cannot be built without
engine-specific logic leaking into `readback.py`, the core has no reason to exist and
slicelab splits into two per-engine tools sharing only the lock schema and the status
enum.* Better to learn that here than after `slice`, `probe` and `verify` are written
against the seam (#6, `notes/critique.md` G5).

Everything runs the console script, because org contract §5 makes the exit code the
stable surface rather than the Python API.

**Readback-only, and profiles that already resolve.** No `flatten.py` and no
`compat.py`: reimplementing Orca's inheritance resolution is forbidden by org
contract §3, and an unconditional workaround for an upstream defect is D21's trap.
Measured on 2.4.2 and the reason neither is needed -- every stock Sovol profile
carries `inherits`, and a triple naming three of them resolves at rc=0 with the
inherited values present. Orca does that resolution itself.

The option map is seeded by probing only the option under test, as
`test_resolve_against_the_engine.py` does. A full Orca characterisation probes every
one of its 616 dump keys and cascades all eight sentinel pairs over each, because
2.4.2 answers the same words at the same status for an unknown option and a bad value
-- seeding one measured option is seconds and is still a measurement.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from slicelab.adapters import ORCASLICER
from slicelab.engine.characterise import SCHEMA, _baseline, _probe_one, cache_path_for
from slicelab.engine.discover import discover
from slicelab.engine.identity import identify
from tests.conftest import skip_or_fail

#: The one option these tests author. Probed, so the readback can adjudicate it;
#: everything else is absent from the map and reports `unvalidated` rather than
#: `absent`, which is why only this one appears below.
OPTION = "wall-loops"

VENDOR = "Sovol"


def _profiles() -> dict[str, Path]:
    """A stock triple this host actually has, or a skip naming what was missing.

    Located rather than hardcoded: which vendor bundles are installed is a property
    of the machine, and a test asserting one particular printer exists would be
    reporting this laptop's configuration as a fact about OrcaSlicer.
    """
    if ORCASLICER.config_location is None or ORCASLICER.config_location.flatpak is None:
        pytest.skip("no measured configuration location for orcaslicer")
    root = (
        Path.home()
        / ".var/app"
        / str(ORCASLICER.flatpak_app_id)
        / "config"
        / ORCASLICER.config_location.flatpak
        / "system"
        / VENDOR
    )
    if not root.is_dir():
        pytest.skip(f"no {VENDOR} profile bundle under {root}")

    # The first machine that has a COMPLETE triple, not the first machine. Orca ships
    # process and filament profiles named for the printer they belong to, and not
    # every machine in a bundle has both -- picking alphabetically found `Sovol SV01`,
    # which has neither, and skipped the whole module. A skip that depends on
    # alphabetical order is the silence this repository exists to refuse.
    for machine in sorted(root.glob("machine/*0.4 nozzle.json")):
        stem = machine.stem.removesuffix(" 0.4 nozzle")
        process = sorted(root.glob(f"process/*@{stem} 0.4 nozzle.json"))
        filament = sorted(root.glob(f"filament/{stem} PLA.json")) or sorted(
            root.glob(f"filament/*{stem}*.json")
        )
        if process and filament:
            return {"machine": machine, "process": process[0], "filament": filament[0]}
    pytest.skip(f"no machine under {root} has both a process and a filament profile")


@pytest.fixture(scope="module")
def seeded(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    """An isolated cache holding a map measured for `OPTION` on this host."""
    found = discover(ORCASLICER)
    if found.form is None:
        skip_or_fail(f"orcaslicer did not start: {found.reason}")
    who = identify(ORCASLICER, found)
    if who.version is None:
        skip_or_fail("orcaslicer did not state a readable version")
    assert ORCASLICER.option_probe is not None

    home = tmp_path_factory.mktemp("xdg")
    scratch = tmp_path_factory.mktemp("probe")
    sidecar = scratch / "probe.json"
    baseline, volatile = _baseline(ORCASLICER, found, sidecar, timeout=120.0)
    entry = _probe_one(
        ORCASLICER,
        found,
        ORCASLICER.option_probe,
        OPTION,
        sidecar,
        baseline,
        volatile,
        timeout=120.0,
    )
    if not entry.conclusive:
        skip_or_fail(f"the probe could not settle {OPTION} on this build: {entry.outcome}")

    path = cache_path_for(ORCASLICER, who.version)
    path = home / path.relative_to(Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": SCHEMA,
                "engine": ORCASLICER.name,
                "version": who.version,
                "baseline_key_count": len(baseline),
                "volatile_keys": sorted(volatile),
                "entries": {
                    OPTION: {
                        "keys": list(entry.keys),
                        "side_effects": list(entry.side_effects),
                        "tracking": entry.tracking.value if entry.tracking else None,
                        "outcome": entry.outcome.value,
                        "conclusive": entry.conclusive,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return dict(os.environ, XDG_CACHE_HOME=str(home))


def _intent(tmp_path: Path, profiles: dict[str, Path], body: str = "") -> Path:
    path = tmp_path / "slice.toml"
    path.write_text(
        "[orcaslicer.base]\n"
        + "".join(f'{kind} = "{profiles[kind]}"\n' for kind in ("machine", "process", "filament"))
        + body,
        encoding="utf-8",
    )
    return path


def _resolve(intent: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "slicelab", "resolve", str(intent)],
        capture_output=True,
        text=True,
        env=env,
        timeout=600,
    )


def test_a_stock_triple_resolves_and_the_override_is_adjudicated(
    seeded: dict[str, str], tmp_path: Path
) -> None:
    """#6's first checkbox, and D1's clause answered in the affirmative.

    Two engines, two mechanisms -- PrusaSlicer's 376-key ini from `--save` and Orca's
    625-key JSON from `--export-settings` -- reaching one adjudication through a core
    that names neither.
    """
    profiles = _profiles()
    intent = _intent(tmp_path, profiles, f"\n[orcaslicer.set]\n{OPTION} = 5\n")
    done = _resolve(intent, seeded)

    assert done.returncode == 0, f"{done.stdout}\n{done.stderr}"
    assert done.stdout.startswith("sliced"), done.stdout
    assert f"{OPTION}: applied" in done.stdout, done.stdout


def test_the_readback_is_written_with_this_engine_s_own_extension(
    seeded: dict[str, str], tmp_path: Path
) -> None:
    """A JSON dump is not an ini, and the sidecar is a file other tools open.

    `cli.py` named every engine's readback `.readback.ini`, so a Sovol triple resolved
    to a 625-key JSON document in a file claiming to be an ini. Nothing in slicelab
    reads it back by extension, which is why it went unnoticed -- and why the suffix
    is the adapter's to state.
    """
    intent = _intent(tmp_path, _profiles())
    done = _resolve(intent, seeded)
    assert done.returncode == 3, f"{done.stdout}\n{done.stderr}"  # `empty`: nothing authored

    written = tmp_path / "slice.readback.json"
    assert written.is_file(), sorted(p.name for p in tmp_path.iterdir())
    assert json.loads(written.read_text(encoding="utf-8")), "the sidecar is not a JSON object"


def test_a_profile_orca_will_not_load_is_incomplete_with_the_engine_s_own_reason(
    seeded: dict[str, str], tmp_path: Path
) -> None:
    """#6's `unsupported` half, and V13's: a named cause, never a guess.

    Orca's `user/` profiles are partial -- they carry `inherits` and no type -- and
    2.4.2 refuses one handed to `--load-settings` directly. That is the case #6 scopes
    out: a profile needing `flatten.py` or `compat.py` is refused with a reason rather
    than silently resolved to something else.

    The engine's own record is what is asserted, not the shell status. 2.4.2 truncates
    its internal code to a byte on the way out, so the shell sees 251 for a `-5` the
    engine chose -- reporting 251 would attribute to the engine a number it never
    stated.
    """
    profiles = _profiles()
    absent = tmp_path / "not-a-profile.json"
    absent.write_text('{"nonsense": true}', encoding="utf-8")
    intent = _intent(tmp_path, {**profiles, "machine": absent})

    done = _resolve(intent, seeded)
    assert done.returncode == 2, f"{done.stdout}\n{done.stderr}"
    assert "incomplete" in done.stderr, done.stderr
    # The engine's own words, carried through rather than discarded (D28).
    assert "preset" in done.stderr or "parse" in done.stderr, done.stderr
    assert not (tmp_path / "slice.readback.json").exists(), "a refused run promoted a readback"


def test_a_prusaslicer_triple_is_refused_with_a_reason_not_silently_wrong(
    seeded: dict[str, str], tmp_path: Path
) -> None:
    """#6's `unsupported` checkbox: the other engine's presets, named the other way.

    PrusaSlicer addresses presets by name and Orca takes paths, so a `[base]` carrying
    a stock MK4S triple is three names Orca reads as filenames and does not find. The
    outcome that matters is that it is a NAMED refusal rather than a run that resolved
    to something else and reported green.

    The code asserted is the ENGINE's. 2.4.2 truncates its internal code to a byte on
    the way out, so the shell sees 253 for the `-3` the engine chose -- and `-3` is
    what its own record says.
    """
    intent = tmp_path / "slice.toml"
    intent.write_text(
        "[orcaslicer.base]\n"
        'machine = "Original Prusa MK4S 0.4 nozzle"\n'
        'process = "0.20mm SPEED @MK4S 0.4 nozzle"\n'
        'filament = "Prusament PLA"\n',
        encoding="utf-8",
    )
    done = _resolve(intent, seeded)

    assert done.returncode == 2, f"{done.stdout}\n{done.stderr}"
    assert done.stderr.startswith("incomplete"), done.stderr
    assert "-3" in done.stderr, f"the engine's own code is not reported: {done.stderr}"
    assert "not found" in done.stderr, f"the engine's own words are not carried: {done.stderr}"
    assert not list(tmp_path.glob("*.readback.*")), "a refused run promoted a readback"


#: Host-family keys 2.4.2 carries into a settings dump that are NOT credentials.
#: Each states how the printer is reached rather than a secret for reaching it, and
#: each is a decision: the engine's own G-code footer KEEPS these and strips the seven
#: on `ORCASLICER.secret_keys`. Adding a name here is a claim that the engine does not
#: treat it as sensitive, made in a diff someone can object to.
NOT_CREDENTIALS = frozenset(
    {
        "host_type",
        "printhost_authorization_type",
        "printhost_ssl_ignore_revoke",
        "bbl_use_printhost",
    }
)


def test_every_host_family_key_this_engine_emits_is_declared_one_way_or_the_other(
    seeded: dict[str, str], tmp_path: Path
) -> None:
    """The guard that was missing, and the reason a credential shipped.

    `secret_keys` was built by name-matching against PrusaSlicer's list, which cannot
    find a key PrusaSlicer does not have -- and `print_host_webui` is one. It reached
    the promoted sidecar in cleartext, carrying `http://user:pass@host/`, under a field
    naming which keys had been removed. The redaction check could not catch it either:
    it proves the DECLARED list was applied and says nothing about the list being
    complete.

    So this pins both lists against a dump that actually carries the family. **It is a
    regression guard, not a completeness guard**, and the difference matters: 2.4.2
    emits a host-family key only when the loaded profile sets it, so what this can see
    is bounded by the profile written below rather than by the engine. A key added in
    a future release is absent from that profile, absent from the dump, and invisible
    here.

    What finds a new one is the G-code footer comparison, which needs a slice and is a
    standing instruction on every engine bump (D1). This is the cheap half: drop a name
    from `secret_keys` or from `NOT_CREDENTIALS` and it goes red.
    """
    profiles = _profiles()
    configured = tmp_path / "machine.json"
    configured.write_text(
        json.dumps(
            {
                **json.loads(profiles["machine"].read_text(encoding="utf-8")),
                # Sentinels, not credentials. Nothing here reaches a network: the
                # engine resolves a configuration and writes it to a file.
                "print_host": "http://slicelab.invalid/",
                "print_host_webui": "http://slicelab:slicelab@webui.invalid/",
                "printhost_apikey": "SLICELABNOTAREALKEY",
                "printhost_user": "slicelab",
                "printhost_password": "SLICELABNOTAREALPASSWORD",
                "printhost_port": "8080",
                "printhost_cafile": "/slicelab/invalid/ca.pem",
                "printhost_authorization_type": "key",
                "host_type": "octoprint",
            }
        ),
        encoding="utf-8",
    )
    intent = _intent(tmp_path, {**profiles, "machine": configured})
    done = _resolve(intent, seeded)
    assert done.returncode == 3, f"{done.stdout}\n{done.stderr}"

    dump = json.loads((tmp_path / "slice.readback.json").read_text(encoding="utf-8"))
    family = {
        key
        for key in dump
        if key.startswith(("print_host", "printhost_")) or key in NOT_CREDENTIALS
    }
    undecided = sorted(family - set(ORCASLICER.secret_keys or ()) - NOT_CREDENTIALS)
    assert undecided == [], (
        f"{undecided} reach this engine's readback and are neither declared "
        "credential-bearing nor declared safe. A host-family key that nobody decided "
        "about defaults to being written out, which is how `print_host_webui` shipped."
    )

    # And the declared ones are actually gone from the promoted file.
    for key in ORCASLICER.secret_keys or ():
        if key in dump:
            assert dump[key] == "<redacted>", f"{key} survived into the sidecar: {dump[key]!r}"
    assert "slicelab:slicelab@" not in (tmp_path / "slice.readback.json").read_text(
        encoding="utf-8"
    ), "a credential embedded in a URL survived into the sidecar"
