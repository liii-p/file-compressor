import io
import os
import subprocess
import tempfile
from pathlib import Path

import pikepdf

from . import SkipFile
from .presets import Preset
from .sandbox import SandboxUnavailable, run_offline

# Homebrew's Ghostscript on Apple silicon and Intel. Not looked up on PATH, so a
# planted `gs` earlier on PATH is never run.
GS_PATHS = ("/opt/homebrew/bin/gs", "/usr/local/bin/gs")
# Generous enough for a 1 GB PDF (about 12 minutes); only runaway inputs should hit it.
GS_BASE_TIMEOUT = 120  # seconds
GS_TIMEOUT_PER_100MB = 60


def find_ghostscript() -> str | None:
    return next((p for p in GS_PATHS if os.access(p, os.X_OK)), None)


def compress_pdf(path: Path, preset: Preset) -> bytes:
    """Return the smallest of: Ghostscript's lossy rewrite or a lossless pikepdf pass."""
    try:
        with pikepdf.open(path) as pdf:
            if pdf.is_encrypted:
                raise SkipFile("PDF is encrypted")
    except pikepdf.PasswordError:
        raise SkipFile("PDF is password-protected")

    candidates = [_optimize(path)]
    gs = find_ghostscript()
    if gs and _starts_as_pdf(path):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp).resolve() / "out.pdf"
            try:
                # Absolute paths: gs treats a bare name starting with "@" as a file of
                # extra arguments, and one starting with "-" as an option.
                run_offline([
                    gs, "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.6",
                    f"-dPDFSETTINGS={preset.pdf_setting}",
                    "-dSAFER", "-dNOPAUSE", "-dBATCH", "-dQUIET",
                    f"-sOutputFile={out}", str(path.resolve()),
                ], writable=out.parent,
                    readable=[Path(gs).parent.parent, path.resolve()],  # Homebrew prefix, the input
                    timeout=GS_BASE_TIMEOUT + GS_TIMEOUT_PER_100MB * path.stat().st_size / 100_000_000)
                candidates.append(_optimize(out))
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, SandboxUnavailable):
                pass  # fall back to the lossless result
    return min(candidates, key=len)


def _starts_as_pdf(path: Path) -> bool:
    # gs picks its interpreter from the content, not the name: a PostScript file
    # (or polyglot) named .pdf would run the full PostScript interpreter.
    with open(path, "rb") as f:
        return f.read(5) == b"%PDF-"


def _optimize(path: Path) -> bytes:
    with pikepdf.open(path) as pdf:
        pdf.remove_unreferenced_resources()
        out = io.BytesIO()
        pdf.save(out, compress_streams=True, recompress_flate=True,
                 object_stream_mode=pikepdf.ObjectStreamMode.generate)
        return out.getvalue()
