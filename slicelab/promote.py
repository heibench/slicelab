"""D7's promote step: stage first, then replace the author's file in one operation.

Used by every verb that hands the author a file, because the failure it prevents is
the same each time and a second copy of it would be a second place to get wrong.

`write_text` opens for writing, which truncates at open, so a failure part-way
through -- ENOSPC, EDQUOT, EIO, a signal -- left the author holding a half-written
file where their previous one had been, while slicelab reported that nothing was
established. Reproduced under an 8192-byte write limit: a 1080-byte readback came
back as 8192 bytes of the new one, the old content gone.
"""

from __future__ import annotations

import contextlib
import os
import stat
import tempfile
from pathlib import Path

__all__ = ["PromotionError", "promote"]


class PromotionError(Exception):
    """The file could not be written. An environment fault, never a verdict."""


def promote(payload: bytes, destination: Path) -> None:
    """Write `payload` where the author asked for it. D7's promote step.

    Promoted on every adjudicated outcome, not only on `sliced` -- which is where
    this parts from D7's letter, and D31 says why: for G-code a partial artifact is
    dangerous, whereas the readback IS the evidence for `incomplete` and for the
    `empty` run D24 requires be kept. A run that reached adjudication has a complete,
    engine-written dump; withholding it would leave the author with a verdict and
    nothing to check it against.

    **Written beside, then renamed.** `write_text` opens for writing, which truncates
    at open, so a failure part-way through -- ENOSPC, EDQUOT, EIO, a signal -- left
    the author holding a half-written file where their previous readback had been,
    while slicelab reported exit 4 and "nothing was established". Reproduced under an
    8192-byte write limit: a 1080-byte readback came back as 8192 bytes of the new
    one, the old content gone. An earlier revision of this docstring asserted there
    was no such window; there was, and D7 says stage-then-promote for this reason.

    `os.replace` is atomic on POSIX and on Windows, so the destination holds the old
    bytes or the new ones and never a mixture. The temporary lives in the
    destination's OWN directory, because a rename across filesystems is not atomic
    and the staging directory is often on a different one.

    Three things a rename does that writing in place did not, the first two handled
    here rather than left to be discovered:

    * **It replaces.** Writing to `/dev/null` discarded the bytes; renaming onto it
      would substitute a regular file for the device node. So a destination that
      exists and is not a regular file is refused above.
    * **It substitutes a new inode**, which takes the temporary's mode -- 0600 from
      `NamedTemporaryFile` -- where an in-place write kept whatever the file had.
      Measured: a destination at 0644 came back 0600. `_mode_for` puts that back.
    * **It leaves a window.** A hard link to the destination keeps the old content
      instead of following, and a signal between the write and the rename leaves the
      temporary beside the destination. Both are inherent to renaming; the temporary
      holds redacted bytes, so it is litter rather than exposure, and the alternative
      is writing in place, which is the defect above.
    """
    # A rename REPLACES what is there, which `write_text` did not: writing to
    # `/dev/null` discarded the bytes harmlessly, whereas renaming onto it would
    # substitute a regular file for the device node. Only reachable for a caller who
    # can write the containing directory -- root, in a container -- and only for a
    # destination they named explicitly, but the old behaviour was harmless and the
    # new one is not.
    #
    # `exists()`/`is_file()` FOLLOW symlinks, so this declines a link to a device and
    # allows a link to a regular file, whose target is then replaced rather than the
    # link. That is the behaviour wanted, and it is also moot through the product:
    # `plan_resolve` resolves the destination, so what arrives here is never a link.
    if destination.exists() and not destination.is_file():
        raise PromotionError(
            f"{destination} is not a regular file, and promoting onto it would replace it"
        )

    try:
        handle = tempfile.NamedTemporaryFile(  # noqa: SIM115 - closed by the `with` below
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".slicelab-partial",
            delete=False,
        )
    except OSError as exc:
        # Could not write the evidence. That establishes nothing about the intent,
        # so it is an environment fault -- an uncaught traceback here exited 1,
        # which is `refused`, and put `Traceback` where D14 requires the outcome
        # word.
        raise PromotionError(f"cannot write {destination}: {exc}") from exc

    beside = Path(handle.name)
    try:
        with handle:
            handle.write(payload)
        os.chmod(beside, _mode_for(destination))
        os.replace(beside, destination)
    except OSError as exc:
        # Whatever failed, the partial file does not survive. `delete=False` is what
        # lets the rename happen at all, and it also means nothing else removes this.
        with contextlib.suppress(OSError):
            beside.unlink()
        raise PromotionError(f"cannot write {destination}: {exc}") from exc


def _mode_for(destination: Path) -> int:
    """The mode the promoted readback should end up with.

    The destination's own, when it has one, so a file the author has already chmod'd
    keeps what they set. Otherwise the mode an ordinary create would produce, because
    `NamedTemporaryFile`'s 0600 is a silent change to a file the README says you
    commit -- nobody asked for it, and a fix should not alter what it was not fixing.

    Reading the umask means setting it and putting it back; there is no query. Safe
    here because nothing in slicelab changes it concurrently.
    """
    with contextlib.suppress(OSError):
        return stat.S_IMODE(destination.stat().st_mode)
    mask = os.umask(0)
    os.umask(mask)
    return 0o666 & ~mask
