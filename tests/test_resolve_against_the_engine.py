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
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

try:  # POSIX only. Importing it unguarded reddened the Windows leg at collection,
    import resource  # which is the leg that exists to catch exactly that.
except ImportError:  # pragma: no cover - Windows
    resource = None  # type: ignore[assignment]

from slicelab.adapters import EngineSpec
from slicelab.engine.characterise import SCHEMA, _baseline, _probe_one, cache_path_for
from slicelab.engine.discover import LaunchKind, argv_for, discover
from slicelab.engine.identity import identify
from slicelab.engine.launch import run
from slicelab.redact import REDACTED, Redacted
from slicelab.resolve import ResolveError, _promote
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


#: Substrings that make a key name worth ruling on. Deliberately broader than any
#: one engine's family, because the point is to catch a name nobody listed.
CREDENTIAL_NAME_WORDS = (
    "host",
    "apikey",
    "api_key",
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "cafile",
    "_user",
    "auth",
)

#: Keys whose NAMES match the pattern above and which are not credentials, each
#: with the reason. An entry here is a claim that someone looked; a key reaching
#: neither this nor `secret_keys` reddens the test rather than passing quietly.
NAMED_LIKE_A_CREDENTIAL_BUT_IS_NOT = {
    # The print-host PROTOCOL, an enum. Set to a marker via --load it comes back
    # `prusalink` at rc=0 with nothing on stderr, so it cannot carry an author's
    # value. It names which protocol the host speaks and nothing about which host.
    #
    # This key is why the name scan exists: it was in no hand-written list, and the
    # first run of the scan found it.
    "host_type",
    # Coerced to the fixed word `key` whatever it is set to. An enum naming the
    # authorization scheme, not a credential under it.
    "printhost_authorization_type",
    # Coerced to `0`. A boolean.
    "printhost_ssl_ignore_revoke",
}

MARKER = "SLICELABMEASURE"


def _engine_binary(spec: EngineSpec, found) -> Path | None:
    """The engine executable on this host, or `None` if it cannot be located.

    Needed because the credential family cannot be read out of any dump: the keys
    that matter are precisely the ones an unconfigured engine does not emit. The
    build's own string table is the only enumeration of them available, and
    `--help-fff` is not it -- 411 options, none of these names.
    """
    assert found.form is not None
    if found.form.kind is LaunchKind.PATH:
        return Path(found.form.argv_prefix[0])
    if spec.flatpak_app_id is None:
        return None
    located = run(["flatpak", "info", "--show-location", spec.flatpak_app_id], timeout=60.0)
    if located.exit_status != 0:
        return None
    binary = Path(located.stdout.strip()) / "files" / "bin" / spec.posix_exec
    return binary if binary.is_file() else None


def _candidates_from_the_build(binary: Path) -> tuple[str, ...]:
    """Config-key-shaped names in the binary whose spelling reads like a credential.

    A CANDIDATE list, not an answer -- the same distinction `OptionProbe.candidates`
    draws. It decides what gets SET; what gets ruled on is every credential-shaped
    key in the resulting dump, which is a different and larger population. Over-
    producing costs one ignored line in a `--load`ed ini, because the engine drops
    keys it does not know (V2, asserted as this test's control).

    The two populations are separate because this scan under-produces in a way worth
    naming: `re.findall` takes maximal runs, so a name that also appears inside a
    longer identifier is swallowed. `print_host` is exactly that -- present in the
    binary as its own NUL-terminated string, and absent from this function's output
    because `print_host_queue_dialog_width` and friends consume it. Ruling on the
    dump rather than on this list is what keeps the most important key of the family
    in scope.
    """
    blob = binary.read_bytes()
    shaped = set(re.findall(rb"[a-z][a-z0-9_]{3,48}", blob))
    return tuple(
        sorted(
            name
            for name in (raw.decode("ascii") for raw in shaped)
            if any(word in name for word in CREDENTIAL_NAME_WORDS)
        )
    )


def _dump_with_credentials_set(
    spec: EngineSpec, found, candidates: tuple[str, ...]
) -> tuple[dict[str, str], str]:
    """The engine's dump with every candidate set to a marker. Returns (dump, marker).

    `tempfile` rather than `tmp_path`, so this can be called from a module-scoped
    context.
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
            "".join(f"{key}{separator}{MARKER}-{i}\n" for i, key in enumerate(candidates))
            + f"slicelab_not_a_real_key{separator}{MARKER}-CONTROL\n",
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
    """Every credential-shaped key THIS BUILD carries is declared secret, or reviewed.

    `secret_keys` names what to remove, so it is only as complete as the day it was
    measured -- the project's whitelist-over-blacklist rule, inverted. Making that
    honest needs the candidate population to come from the build rather than from a
    list someone maintains:

    **The population is the binary's own string table**, filtered to names that read
    like a credential. A hand-written tuple was the first attempt and it reproduced
    the defect one level up -- a name nobody listed is never set, never appears in
    any dump, and no downstream check can see it. Removing `printhost_password` from
    both that tuple and `secret_keys` left this test green, which is exactly the
    thirteenth-name case it claimed to catch.

    **Each candidate is SET**, because the keys that matter are the ones an
    unconfigured engine does not emit. A stock preset sets no digest credentials, so
    a check reading a stock dump finds three of six and looks complete -- which is
    how the adapter came to declare three.

    Then: a key that comes back carrying the marker holds an author's value and must
    be declared. A key that comes back coerced holds nothing authored and must be
    named in `NAMED_LIKE_A_CREDENTIAL_BUT_IS_NOT` with the measurement.

    The control is the fabricated key. The engine drops keys it does not know (V2),
    so if `slicelab_not_a_real_key` survived, "it came back" would mean "`--load`
    echoed it" and every conclusion here would be about the fixture.
    """
    spec, found = seeded[1], seeded[2]
    binary = _engine_binary(spec, found)
    if binary is None:
        skip_or_fail(f"could not locate the {spec.name} binary, so its namespace cannot be read")

    candidates = _candidates_from_the_build(binary)
    assert len(candidates) > 5, (
        f"only {len(candidates)} credential-shaped names in {binary}; the scan found "
        "almost nothing, which is a broken scan rather than a clean engine"
    )

    dump, marker = _dump_with_credentials_set(spec, found, candidates)
    declared = set(spec.secret_keys or ())

    assert "slicelab_not_a_real_key" not in dump, (
        "a fabricated key survived into the dump, so `--load` is echoing rather than "
        "the engine accepting -- nothing below would be a fact about the engine"
    )

    # The population to rule on is the DUMP's credential-shaped keys, not the
    # candidate list. The list only decides what was set; a key the engine emits
    # whose name reads like a credential has to be decided about however it got there.
    emitted = sorted(key for key in dump if any(word in key for word in CREDENTIAL_NAME_WORDS))
    assert emitted, "no credential-shaped key was emitted at all, so this proved nothing"
    assert "print_host" in emitted, (
        "print_host is not in the population being ruled on, and it is the key this "
        "whole mechanism exists for -- the scan or the dump parse has regressed"
    )

    carries_a_value = [key for key in emitted if marker in dump[key]]
    assert carries_a_value, (
        "no candidate survived with the value that was set, so the fixture never "
        "reached the engine and every conclusion below would be about the fixture"
    )

    undeclared = sorted(key for key in carries_a_value if key not in declared)
    assert undeclared == [], (
        f"{spec.name} emits {undeclared} carrying the value that was set, and the "
        "adapter does not redact them. They reach the file the author commits."
    )

    unreviewed = sorted(
        key
        for key in emitted
        if key not in carries_a_value
        and key not in declared
        and key not in NAMED_LIKE_A_CREDENTIAL_BUT_IS_NOT
    )
    assert unreviewed == [], (
        f"{spec.name} emits {unreviewed}, which no one has decided about. Each is a "
        "credential-shaped name this build carries that came back coerced. Confirm "
        "that, then add it to NAMED_LIKE_A_CREDENTIAL_BUT_IS_NOT with the measurement."
    )


def test_resolve_hands_the_engine_a_staged_path_that_does_not_outlive_the_call(
    seeded, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D31's property, pinned where it can actually be broken.

    Asserting the directory listing afterwards does not establish this: the final
    state is identical whether the engine wrote the destination and slicelab
    overwrote it, or the engine wrote a staging path and slicelab promoted. That is
    the PRE-D31 behaviour, and the test named for the property passed under a
    mutation reinstating it.

    What has to hold is that `resolve` gives `plan_resolve` two *different* paths,
    that the engine's is somewhere slicelab owns, and that it is gone afterwards.
    All three are observable only from inside the call, so this one runs in-process
    against the real engine rather than through the console script.
    """
    from slicelab import resolve as resolve_module

    monkeypatch.setenv("XDG_CACHE_HOME", seeded[0]["XDG_CACHE_HOME"])
    seen: list[tuple[Path, Path]] = []
    real = resolve_module.plan_resolve

    def capture(intent, spec, destination, staged):
        seen.append((destination, staged))
        return real(intent, spec, destination, staged)

    monkeypatch.setattr(resolve_module, "plan_resolve", capture)

    intent = tmp_path / "slice.toml"
    intent.write_text(TRIPLE + "\n[prusaslicer.set]\nperimeters = 4\n", encoding="utf-8")
    destination = tmp_path / "out.ini"
    resolve_module.resolve(intent, destination)

    assert len(seen) == 1
    asked_for, given_to_engine = seen[0]
    assert given_to_engine != asked_for, (
        "the engine was told to write the author's own path, so its unredacted dump "
        "lands there and every failure before the redacted overwrite leaves it"
    )
    assert destination not in given_to_engine.parents
    assert not given_to_engine.exists(), "the engine's unredacted dump outlived the call"
    assert not given_to_engine.parent.exists(), "the staging directory outlived the call"
    assert destination.is_file()


def test_a_failed_promote_leaves_the_previous_readback_byte_for_byte(tmp_path: Path) -> None:
    """The destination holds the old bytes or the new ones, never a mixture.

    `write_text` truncates at open, so a failure part-way through -- a full disk, a
    quota, an I/O error -- left a half-written file where the author's committed
    evidence had been, while the run reported exit 4 and "nothing was established".
    Reproduced below with a write limit rather than argued from the code.
    """
    if resource is None or not hasattr(resource, "RLIMIT_FSIZE"):  # pragma: no cover - Windows
        pytest.skip("no RLIMIT_FSIZE on this platform, so a mid-write failure cannot be staged")

    destination = tmp_path / "slice.readback.ini"
    previous = "PREVIOUS-RUN-READBACK-LINE\n" * 40
    destination.write_text(previous, encoding="utf-8")
    before = destination.read_bytes()

    soft, hard = resource.getrlimit(resource.RLIMIT_FSIZE)
    resource.setrlimit(resource.RLIMIT_FSIZE, (8192, hard))
    try:
        with pytest.raises(ResolveError, match="cannot write the readback"):
            _promote(Redacted(text="NEW-REDACTED-READBACK\n" * 2000, keys=()), destination)
    finally:
        resource.setrlimit(resource.RLIMIT_FSIZE, (soft, hard))

    assert destination.read_bytes() == before, "a failed promote destroyed the previous readback"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["slice.readback.ini"], (
        "the partial file was left beside the destination"
    )


def test_a_destination_that_is_not_a_regular_file_is_never_replaced(tmp_path: Path) -> None:
    """A rename replaces; `write_text` did not.

    `--readback /dev/null` used to discard the bytes harmlessly. Renaming onto it
    would substitute a regular file for the device node — only for a caller who can
    write `/dev`, and only for a path they named, but a fix must not make an edge
    case worse than it found it. A fifo stands in for the device node here so the
    test needs no privilege.
    """
    if not hasattr(os, "mkfifo"):  # pragma: no cover - Windows
        pytest.skip("no mkfifo on this platform")
    destination = tmp_path / "readback.ini"
    os.mkfifo(destination)

    with pytest.raises(ResolveError, match="not a regular file"):
        _promote(Redacted(text="anything\n", keys=()), destination)

    assert destination.is_fifo(), "the promote replaced a device-like destination"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["readback.ini"]


def test_a_directory_where_the_readback_goes_is_refused_not_replaced(tmp_path: Path) -> None:
    """A directory reaches the same guard as a fifo, and nothing is left beside it.

    Portable, unlike the two above: no resource limits and no mkfifo.
    """
    destination = tmp_path / "readback.ini"
    destination.mkdir()

    with pytest.raises(ResolveError, match="not a regular file"):
        _promote(Redacted(text="anything\n", keys=()), destination)

    assert sorted(entry.name for entry in tmp_path.iterdir()) == ["readback.ini"]
    assert destination.is_dir()
