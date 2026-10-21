"""Run external binaries under the macOS sandbox.

The sandbox denies network access, starting any program other than the one
we launched, and writing anywhere except a single scratch directory. A
malicious input file that exploits the binary is then contained.
"""

import os
import subprocess
import sys
from pathlib import Path

SANDBOX_EXEC = "/usr/bin/sandbox-exec"

PROFILE = """(version 1)
(allow default)
(deny network*)
(deny process-fork)
(deny process-exec)
(allow process-exec (literal {exe}))
(deny file-write*)
(allow file-write* (subpath {writable}))
"""


class SandboxUnavailable(RuntimeError):
    pass


_warned = False


def _quote(path: str) -> str:
    return '"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"'


def run_offline(cmd: list[str], writable: Path) -> subprocess.CompletedProcess:
    """Run cmd sandboxed; it may only write inside `writable`, which is also its TMPDIR."""
    global _warned
    if not os.path.exists(SANDBOX_EXEC):
        if not _warned:
            print("warning: sandbox-exec not found; skipping external tools", file=sys.stderr)
            _warned = True
        raise SandboxUnavailable("sandbox-exec not found")
    # The sandbox matches real paths, so resolve symlinks (e.g. Homebrew's bin/gs, /var -> /private/var).
    writable = os.path.realpath(writable)
    profile = PROFILE.format(exe=_quote(os.path.realpath(cmd[0])), writable=_quote(writable))
    env = {**os.environ, "TMPDIR": writable}
    return subprocess.run([SANDBOX_EXEC, "-p", profile, *cmd], check=True, capture_output=True, env=env)
