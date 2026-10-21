"""Run external binaries under the macOS sandbox.

The sandbox denies network access, lookups of system services (which could
otherwise fetch URLs or launch apps on our behalf), starting any program other
than the one we launched, reading files outside a short allow list, and writing
anywhere except a single scratch directory. A malicious input file that exploits
the binary is then contained.
"""

import os
import subprocess
import sys
from pathlib import Path

SANDBOX_EXEC = "/usr/bin/sandbox-exec"

# What any macOS program needs to start: system frameworks and libraries, the dyld cache, devices.
SYSTEM_READABLE = ("/System", "/usr/lib", "/usr/share", "/private/var/db/dyld", "/dev")

PROFILE = """(version 1)
(allow default)
(deny network*)
(deny mach-lookup)
(deny process-fork)
(deny process-exec)
(allow process-exec {exe})
(deny file-write*)
(allow file-write* {writable})
(deny file-read*)
; stat() anywhere is needed to resolve paths; it shows names and sizes, never contents.
(allow file-read-metadata)
; dyld lists the root folder at startup (a process without it aborts); that's top-level names only.
(allow file-read* (literal "/") {readable})
"""


class SandboxUnavailable(RuntimeError):
    pass


_warned = False


def _quote(path: str) -> str:
    return '"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _rules(kind: str, paths) -> str:
    # The sandbox may see a path as given or symlink-resolved (/var -> /private/var), so allow both.
    expanded = sorted({p for path in paths for p in (os.fspath(path), os.path.realpath(path))})
    return " ".join(f"({kind} {_quote(p)})" for p in expanded)


def run_offline(cmd: list[str], writable: Path, readable: list[Path],
                timeout: float) -> subprocess.CompletedProcess:
    """Run cmd sandboxed; it may read only `readable` and write only inside `writable` (its TMPDIR)."""
    global _warned
    if not os.path.exists(SANDBOX_EXEC):
        if not _warned:
            print("warning: sandbox-exec not found; skipping external tools", file=sys.stderr)
            _warned = True
        raise SandboxUnavailable("sandbox-exec not found")
    profile = PROFILE.format(
        exe=_rules("literal", [cmd[0]]),
        writable=_rules("subpath", [writable]),
        readable=_rules("subpath", [*SYSTEM_READABLE, *readable, writable]),
    )
    # Nothing inherited, so variables like GS_OPTIONS (which can turn off -dSAFER) have no effect.
    env = {"PATH": "/usr/bin:/bin", "HOME": os.fspath(writable), "TMPDIR": os.fspath(writable)}
    return subprocess.run([SANDBOX_EXEC, "-p", profile, *cmd], check=True, capture_output=True,
                          env=env, timeout=timeout)
