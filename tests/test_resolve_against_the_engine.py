"""`slicelab resolve`, end to end, as a real process against a real engine.

Everything below runs the console script, so what is asserted is the **exit code a
consumer branches on** — org contract §5 makes that the stable surface, not the
Python API. A test that called `resolve()` directly would not establish that the
verb returns what the table says.

The option map is seeded into an isolated `XDG_CACHE_HOME` by probing the two
options under test. A full characterisation is ~1100 s; two options is seconds, and
seeding a measured map is still a measurement. Every other option is then absent
from the map, which `readback` reports as `unvalidated` rather than `absent` — so
the tests only author the two that were probed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from slicelab.adapters import EngineSpec
from slicelab.engine.characterise import SCHEMA, _baseline, _probe_one, cache_path_for
from slicelab.engine.discover import argv_for, discover
from slicelab.engine.identity import identify
from slicelab.engine.launch import run
from slicelab.redact import REDACTED
from tests.conftest import skip_or_fail

PRESETS = {
    "printer-profile": "Original Prusa i3 MK3S & MK3S+",
    "print-profile": "0.20mm QUALITY @MK3",
    "material-profile": "Prusament PLA",
}

TRIPLE = """[prusaslicer.base]
printer-profile = "Original Prusa i3 MK3S & MK3S+"
print-profile = "0.20mm QUALITY @MK3"
material-profile = "Prusament PLA"
"""


def _engine(usable_engines: list[EngineSpec]) -> EngineSpec:
    for spec in usable_engines:
        if spec.base_keys and spec.option_probe and spec.secret_keys:
            return spec
    # `skip_or_fail`, not a bare skip. Every test in this module needs an engine
    # declaring all three fields, and OrcaSlicer declares none of them -- so on a
    # host whose only usable engine is Orca, a bare skip took the entire module out
    # and reported green. That is the silence this repository exists to refuse,
    # aimed at its own suite.
    skip_or_fail("no engine with declared preset flags, probe and secret keys is installed")


@pytest.fixture(scope="module")
def seeded(usable_engines: list[EngineSpec], tmp_path_factory: pytest.TempPathFactory):
    """An isolated cache holding a map measured for two options on this host."""
    spec = _engine(usable_engines)
    found = discover(spec)
    if found.form is None:
        # Observed here on 2026-09-11: discovery reported `--help exited 1` and the
        # same command succeeded four times a second later. D30 records this
        # transient. An engine that would not start is an environment fault, not a
        # verdict on the code under test (org 2.2) -- erroring would attribute a
        # machine problem to this branch. `SLICELAB_REQUIRE_ENGINE` turns it into a
        # failure where an engine is supposed to be present, which is what
        # `skip_or_fail` is for; the earlier bare `pytest.skip` here claimed that
        # behaviour in this very comment and did not have it.
        skip_or_fail(f"{spec.name} did not start: {found.reason}")
    assert spec.option_probe is not None
    who = identify(spec, found)
    if who.version is None:
        skip_or_fail(f"{spec.name} did not state a readable version")

    home = tmp_path_factory.mktemp("xdg")
    env = dict(os.environ, XDG_CACHE_HOME=str(home))

    scratch = tmp_path_factory.mktemp("probe")
    sidecar = scratch / "probe.ini"
    baseline, volatile = _baseline(spec, found, sidecar, timeout=60.0)
    entries = {}
    for option in ("perimeters", "spiral-vase"):
        entry = _probe_one(
            spec, found, spec.option_probe, option, sidecar, baseline, volatile, timeout=60.0
        )
        entries[option] = {
            "keys": list(entry.keys),
            "side_effects": list(entry.side_effects),
            "tracking": entry.tracking.value if entry.tracking else None,
            "outcome": entry.outcome.value,
        }

    original = os.environ.get("XDG_CACHE_HOME")
    os.environ["XDG_CACHE_HOME"] = str(home)
    try:
        destination = cache_path_for(spec, who.version)
    finally:
        if original is None:
            del os.environ["XDG_CACHE_HOME"]
        else:
            os.environ["XDG_CACHE_HOME"] = original
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(
            {
                "schema": SCHEMA,
                "engine": spec.name,
                "version": who.version,
                "baseline_key_count": len(baseline),
                "volatile_keys": list(volatile),
                "entries": entries,
                "inconclusive": 0,
            }
        ),
        encoding="utf-8",
    )
    return env, spec, found


#: Every `print_host*` / `printhost_*` name PrusaSlicer 2.9.6's binary carries.
#:
#: The probe list, not the answer. Each is SET to a marker so the dump contains
#: what this build can emit rather than what a stock preset happens to set -- a
#: default triple sets no digest credentials, so `printhost_password` and
#: `printhost_user` are simply absent from it, which is how the adapter came to
#: declare three of six. A guard reading a default dump reproduces that defect
#: exactly; the first revision of this one did, and the mutation sweep caught it.
CREDENTIAL_CANDIDATES = (
    "print_host",
    "print_host_webui",
    "printhost_apikey",
    "printhost_authorization_type",
    "printhost_cafile",
    "printhost_group",
    "printhost_password",
    "printhost_path",
    "printhost_port",
    "printhost_ssl_ignore_revoke",
    "printhost_storage",
    "printhost_user",
)

MARKER = "SLICELABMEASURE"


def _dump_with_credentials_set(spec: EngineSpec, found) -> tuple[dict[str, str], str]:
    """The engine's dump with every candidate credential key set to a marker.

    Returns (dump, marker). `tempfile` rather than `tmp_path`, so this can be called
    from a module-scoped context.
    """
    assert found.form is not None
    with tempfile.TemporaryDirectory() as scratch:
        loaded = Path(scratch) / "credentials.ini"
        # Assembled, so this file contains no key-shaped assignment for the secret
        # scanner to match. It matches on the NAME, which a fixture cannot avoid by
        # being obviously fake, and a repository that teaches people to wave that
        # hook through is worse off than one with an awkward fixture.
        separator = " = "
        loaded.write_text(
            "".join(
                f"{key}{separator}{MARKER}-{i}\n" for i, key in enumerate(CREDENTIAL_CANDIDATES)
            ),
            encoding="utf-8",
        )
        out = Path(scratch) / "dump.ini"
        argv = (
            ("--load", str(loaded))
            + tuple(f"--{key}={value}" for key, value in PRESETS.items())
            + (f"--save={out}",)
        )
        completed = run(argv_for(found.form, argv, frozenset({str(out), str(loaded)})))
        assert completed.exit_status == 0, completed.stderr
        assert out.is_file(), "the engine exited 0 and wrote no configuration"
        return {
            line.partition(" = ")[0].strip(): line.partition(" = ")[2]
            for line in out.read_text(encoding="utf-8", errors="replace").splitlines()
            if " = " in line and not line.startswith(("#", "["))
        }, MARKER


def _run(seeded: tuple, intent: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "slicelab", "resolve", str(intent)],
        capture_output=True,
        text=True,
        env=seeded[0],
        timeout=300,
    )


def test_an_honoured_intent_exits_zero(seeded, tmp_path: Path) -> None:
    intent = tmp_path / "slice.toml"
    intent.write_text(TRIPLE + "\n[prusaslicer.set]\nperimeters = 4\n", encoding="utf-8")
    done = _run(seeded, intent)
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("sliced")


def test_v1_exits_two_and_names_both_values(seeded, tmp_path: Path) -> None:
    """The run this whole project exists for, as a process.

    `--perimeters=4.7` resolves to `4` at engine exit 0 with zero bytes on stderr.
    slicelab exits **2**, not 0 -- and not 1, because it cannot tell the engine
    ignoring the request from the engine applying a dependent constraint (D27).
    """
    intent = tmp_path / "slice.toml"
    intent.write_text(TRIPLE + "\n[prusaslicer.set]\nperimeters = 4.7\n", encoding="utf-8")
    done = _run(seeded, intent)
    assert done.returncode == 2, done.stdout + done.stderr
    assert done.stderr.startswith("incomplete")
    assert "4.7" in done.stderr
    assert "coerced" in done.stderr


def test_a_base_only_intent_exits_three(seeded, tmp_path: Path) -> None:
    """G1/D24: the first file anyone writes verifies nothing, and must not say `sliced`."""
    intent = tmp_path / "slice.toml"
    intent.write_text(TRIPLE, encoding="utf-8")
    done = _run(seeded, intent)
    assert done.returncode == 3, done.stdout + done.stderr
    assert done.stderr.startswith("empty")


def test_an_unknown_key_in_the_intent_exits_one(seeded, tmp_path: Path) -> None:
    """Refused before the engine is reached. Never silently dropped, which is what
    the engine itself does to an unknown key in a --load'ed ini [V2]."""
    intent = tmp_path / "slice.toml"
    intent.write_text(TRIPLE + "\n[prusaslicer.nonsense]\nx = 1\n", encoding="utf-8")
    done = _run(seeded, intent)
    assert done.returncode == 1, done.stdout + done.stderr
    assert done.stderr.startswith("refused")


def test_a_partial_preset_triple_exits_one_without_touching_the_engine(
    seeded, tmp_path: Path
) -> None:
    """D15. Any proper non-empty subset is a deterministic SIGSEGV with zero bytes
    on both streams, so slicelab refuses rather than reporting a crash it caused."""
    intent = tmp_path / "slice.toml"
    intent.write_text(
        '[prusaslicer.base]\nprinter-profile = "Original Prusa i3 MK3S & MK3S+"\n',
        encoding="utf-8",
    )
    done = _run(seeded, intent)
    assert done.returncode == 1, done.stdout + done.stderr
    assert "print-profile" in done.stderr


def test_the_readback_is_written_and_its_credentials_are_not(seeded, tmp_path: Path) -> None:
    """The sidecar is the engine's own bytes, minus a named list.

    Measured: a preset triple makes `--save` emit `print_host`,
    `printhost_apikey` and `printhost_cafile`; a bare `--save` emits none of them,
    so a guard written against the default dump would have found nothing and
    reported the file clean.

    **What is measured here is that the keys appear, not that they held a value.**
    On an unconfigured host all three are empty, so this test passes over a dump
    containing no credential -- it establishes that the redaction reaches the right
    lines, and `tests/test_redact.py` is where a value is shown not to survive.
    Saying so because "emits them in cleartext" claims a measurement nobody made.
    """
    intent = tmp_path / "slice.toml"
    intent.write_text(TRIPLE + "\n[prusaslicer.set]\nperimeters = 4\n", encoding="utf-8")
    done = _run(seeded, intent)
    assert done.returncode == 0, done.stderr

    written = tmp_path / "slice.readback.ini"
    assert written.is_file()
    body = written.read_text(encoding="utf-8")
    assert "perimeters = 4" in body
    for secret in ("print_host", "printhost_apikey", "printhost_cafile"):
        assert f"{secret} = <redacted>" in body, body[:400]
    assert "redacted" in done.stdout


def _cube(path: Path) -> Path:
    """A 20 mm ASCII-STL cube, generated rather than committed (D11)."""
    corners = [
        (0, 0, 0),
        (20, 0, 0),
        (20, 20, 0),
        (0, 20, 0),
        (0, 0, 20),
        (20, 0, 20),
        (20, 20, 20),
        (0, 20, 20),
    ]
    faces = [
        (0, 3, 2),
        (0, 2, 1),
        (4, 5, 6),
        (4, 6, 7),
        (0, 1, 5),
        (0, 5, 4),
        (1, 2, 6),
        (1, 6, 5),
        (2, 3, 7),
        (2, 7, 6),
        (3, 0, 4),
        (3, 4, 7),
    ]
    body = ["solid cube"]
    for face in faces:
        body.append("facet normal 0 0 0\n  outer loop")
        body += [f"    vertex {' '.join(str(c) for c in corners[i])}" for i in face]
        body.append("  endloop\nendfacet")
    body.append("endsolid cube")
    path.write_text("\n".join(body) + "\n", encoding="utf-8")
    return path


def test_resolve_matches_slice_config(seeded, tmp_path: Path) -> None:
    """`resolve` previews `slice` faithfully. G7.2 makes this a test, not an assumption.

    `resolve` asks the engine to dump its configuration without slicing, and the
    whole verb rests on that dump being the one a real slice would resolve. That was
    measured once during research and then relied on -- but it is a **per-build fact
    that can regress silently**, which is precisely the class of claim this project
    refuses to carry on a memory.

    Compared here on the same triple and the same override, with and without
    geometry, including the spiral-vase normalisation that makes the comparison
    worth doing: a run where the engine adjusts nothing would prove nothing.
    """
    from slicelab.engine.discover import argv_for
    from slicelab.engine.launch import run

    found = seeded[2]
    model = _cube(tmp_path / "cube.stl")
    triple = [f"--{k}={v}" for k, v in PRESETS.items()]
    overrides = ["--spiral-vase=1", "--perimeters=4"]

    without = tmp_path / "without.ini"
    with_geometry = tmp_path / "with.ini"
    gcode = tmp_path / "out.gcode"

    a = run(argv_for(found.form, [*triple, *overrides, f"--save={without}"], {str(without)}))
    b = run(
        argv_for(
            found.form,
            [
                *triple,
                *overrides,
                "--export-gcode",
                str(model),
                "-o",
                str(gcode),
                f"--save={with_geometry}",
            ],
            {str(with_geometry), str(model), str(gcode)},
        )
    )
    assert a.exit_status == 0, a.stderr
    assert b.exit_status == 0, b.stderr
    assert without.is_file() and with_geometry.is_file()

    left = without.read_text(encoding="utf-8").splitlines()
    right = with_geometry.read_text(encoding="utf-8").splitlines()
    assert len(left) == len(right), (len(left), len(right))

    differing = [(x, y) for x, y in zip(left, right, strict=True) if x != y]

    # Every CONFIG line is identical. The only difference the engine produces is
    # its own generation timestamp, in a comment:
    #   # generated by PrusaSlicer 2.9.6 on 2026-09-11 at 05:15:20 UTC
    #   # generated by PrusaSlicer 2.9.6 on 2026-09-11 at 05:15:22 UTC
    # Asserted as a comment rather than filtered away, because it is also the
    # reason the dump is NOT byte-stable across two runs of the same intent --
    # which anything hashing the sidecar has to know before it hashes it.
    assert all(x.startswith("#") for x, _ in differing), differing[:5]
    config_left = [line for line in left if not line.startswith("#")]
    config_right = [line for line in right if not line.startswith("#")]
    assert config_left == config_right

    # The comparison is only worth making because the engine DID adjust things.
    resolved = dict(line.split(" = ", 1) for line in left if " = " in line)
    assert resolved["spiral_vase"] == "1"
    assert resolved["perimeters"] == "1", "spiral vase did not constrain perimeters"


def test_a_previous_run_s_dump_is_never_adjudicated_as_this_run_s(seeded, tmp_path: Path) -> None:
    """The founding defect, inside the verb written to refuse it.

    `resolve` pointed `--save` at the author's own path and gated on "a non-empty
    file exists". So a run whose engine rejected every preset, wrote nothing, and
    said so on stderr was adjudicated against the PREVIOUS run's configuration --
    reported `sliced` at exit 0, and the sidecar kept as evidence was the earlier
    dump, carrying the earlier timestamp. The default sidecar path derives from the
    intent path, so re-running one `slice.toml` in one directory -- the ordinary
    workflow -- is exactly what armed it.

    Staging closes it structurally (D31): the engine writes into a directory this
    call created, so "the file is there" cannot mean "last run's file is still
    there", and there is no revision of the gate that can confuse the two.

    The property asserted is therefore the one that survives the fix: a run that
    could not be adjudicated neither reports a verdict nor touches the readback the
    author already had. Both halves matter. Asserting only "the marker is gone"
    would now be satisfied by deleting the author's file, which is what the first
    fix did and what D7 calls non-destructive for a reason.
    """
    intent = tmp_path / "slice.toml"
    sidecar = tmp_path / "slice.readback.ini"

    intent.write_text(TRIPLE + "\n[prusaslicer.set]\nperimeters = 4\n", encoding="utf-8")
    first = _run(seeded, intent)
    assert first.returncode == 0, first.stderr
    assert sidecar.is_file()
    sidecar.write_text(
        sidecar.read_text(encoding="utf-8") + "slicelab_stale_marker = FROM-RUN-ONE\n",
        encoding="utf-8",
    )

    # An intent the engine will reject outright: it writes no configuration at all.
    intent.write_text(
        "[prusaslicer.base]\n"
        'printer-profile = "No Such Printer 9000"\n'
        'print-profile = "0.20mm QUALITY @MK3"\n'
        'material-profile = "Prusament PLA"\n'
        "\n[prusaslicer.set]\nperimeters = 4\n",
        encoding="utf-8",
    )
    before = sidecar.read_bytes()
    second = _run(seeded, intent)

    # 2, not 4: the engine started, read the request and said no. Nothing about the
    # machine is faulty, so `error` would assert something nobody measured (D31).
    assert second.returncode == 2, f"rc={second.returncode}\n{second.stdout}{second.stderr}"
    assert "sliced" not in second.stdout
    assert "FROM-RUN-ONE" not in second.stdout, (
        "the previous run's dump was adjudicated and reported as this run's evidence"
    )
    # The engine's own account of why reaches the author. Discarding it left them
    # with a verdict and no hint what to change.
    assert "No Such Printer 9000" in second.stderr or "wasn't found" in second.stderr, (
        f"the engine named the cause and slicelab dropped it: {second.stderr!r}"
    )
    # And the readback they already had is exactly as it was -- not adjudicated,
    # not overwritten, not deleted.
    assert sidecar.read_bytes() == before, (
        "a run that established nothing rewrote the author's readback"
    )


def test_a_readback_that_cannot_be_written_is_an_environment_fault(seeded, tmp_path: Path) -> None:
    """Exit 4, not a traceback at 1.

    The promote step is the one place `resolve` writes a file the author named, and
    a read-only directory, a full disk or a stale NFS handle all arrive there as
    `OSError`. Uncaught, CPython exits 1 -- `refused`, which asserts slicelab looked
    at the intent and found it wanting -- and prints `Traceback` where D14 requires
    the outcome word.

    Previously untested: the handler could be deleted and all 288 tests passed.
    """
    intent = tmp_path / "slice.toml"
    intent.write_text(TRIPLE + "\n[prusaslicer.set]\nperimeters = 4\n", encoding="utf-8")

    locked = tmp_path / "locked"
    locked.mkdir()
    destination = locked / "out.ini"
    locked.chmod(0o500)
    try:
        done = subprocess.run(
            [
                sys.executable,
                "-m",
                "slicelab",
                "resolve",
                str(intent),
                "--readback",
                str(destination),
            ],
            capture_output=True,
            text=True,
            env=seeded[0],
            timeout=300,
        )
    finally:
        locked.chmod(0o700)

    assert done.returncode == 4, f"rc={done.returncode}\n{done.stdout}{done.stderr}"
    assert done.stderr.startswith("error"), done.stderr
    assert "Traceback" not in done.stderr
    assert str(destination) in done.stderr, "the author is not told which file could not be written"


def test_the_engine_s_dump_never_lands_in_the_author_s_directory(seeded, tmp_path: Path) -> None:
    """What the author's directory holds afterwards is the redacted copy and nothing else.

    The engine's dump is unredacted when it is written. Pointing `--save` at the
    destination and overwriting it a moment later leaves cleartext there on every
    path that fails in between -- a non-zero engine exit, a redaction refusal, a
    SIGINT in the window. Staging removes the window rather than narrowing it (D31).
    """
    intent = tmp_path / "slice.toml"
    intent.write_text(TRIPLE + "\n[prusaslicer.set]\nperimeters = 4\n", encoding="utf-8")
    done = _run(seeded, intent)
    assert done.returncode == 0, done.stderr

    written = sorted(p.name for p in tmp_path.iterdir())
    assert written == ["slice.readback.ini", "slice.toml"], written

    readback = (tmp_path / "slice.readback.ini").read_text(encoding="utf-8")
    spec = seeded[1]
    present = [k for k in (spec.secret_keys or ()) if f"{k} = " in readback]
    assert present, "this build emitted no credential key at all, so nothing was proved"
    for key in present:
        assert f"{key} = {REDACTED}\n" in readback, f"{key} reached the author's directory in full"


def test_credentials_are_enumerated_not_sampled(seeded) -> None:
    """Every key of this build's credential family is declared secret, or reviewed.

    `secret_keys` names what to remove, so it is only as complete as the day it was
    measured -- the project's whitelist-over-blacklist rule, inverted. The whitelist
    available here is over the EXCEPTIONS: a key that survives the marker is a
    credential and must be declared; one that coerces to a fixed value carries
    nothing an author set and is named below as reviewed. A key in neither list
    reddens this.

    The control is the marker itself. A key that does not come back carrying it was
    not actually set, so "it is not a credential" would be a conclusion about the
    fixture rather than about the engine.
    """
    spec, found = seeded[1], seeded[2]
    #: Emitted, but the engine coerces them: measured 2026-09-11, `key` and `0`
    #: whatever they are set to. Neither can carry an author's credential.
    reviewed_not_credentials = {"printhost_authorization_type", "printhost_ssl_ignore_revoke"}

    dump, marker = _dump_with_credentials_set(spec, found)
    emitted = sorted(key for key in dump if key in CREDENTIAL_CANDIDATES)
    assert emitted, "no candidate key was emitted at all, so this test proved nothing"

    carries_a_value = [key for key in emitted if marker in dump[key]]
    assert carries_a_value, (
        "no candidate survived with the value that was set, so the fixture never "
        "reached the engine and every conclusion below would be about the fixture"
    )

    undeclared = [key for key in carries_a_value if key not in (spec.secret_keys or ())]
    assert undeclared == [], (
        f"{spec.name} emits {undeclared} carrying the value that was set, and the "
        "adapter does not redact them. They reach the file the author commits."
    )

    unreviewed = [
        key
        for key in emitted
        if key not in carries_a_value
        and key not in (spec.secret_keys or ())
        and key not in reviewed_not_credentials
    ]
    assert unreviewed == [], (
        f"{spec.name} emits {unreviewed}, which no one has decided about. Set each "
        "to a marker and check whether the value survives: if it does, it is a "
        "credential; if it coerces, add it to reviewed_not_credentials saying so."
    )
