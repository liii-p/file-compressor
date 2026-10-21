"""Run external binaries with network access denied by the macOS sandbox."""

import shutil
import subprocess
import sys

PROFILE = "(version 1)(allow default)(deny network*)"

_warned = False


def run_offline(cmd: list[str]) -> subprocess.CompletedProcess:
    global _warned
    sandbox = shutil.which("sandbox-exec")
    if sandbox:
        cmd = [sandbox, "-p", PROFILE, *cmd]
    elif not _warned:
        print("warning: sandbox-exec not found; running external tools unsandboxed", file=sys.stderr)
        _warned = True
    return subprocess.run(cmd, check=True, capture_output=True)
