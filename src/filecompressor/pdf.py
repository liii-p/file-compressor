import io
import shutil
import subprocess
import tempfile
from pathlib import Path

import pikepdf

from . import SkipFile
from .presets import Preset
from .sandbox import SandboxUnavailable, run_offline


def compress_pdf(path: Path, preset: Preset) -> bytes:
    """Return the smallest of: Ghostscript's lossy rewrite or a lossless pikepdf pass."""
    try:
        with pikepdf.open(path) as pdf:
            if pdf.is_encrypted:
                raise SkipFile("PDF is encrypted")
    except pikepdf.PasswordError:
        raise SkipFile("PDF is password-protected")

    candidates = [_optimize(path)]
    gs = shutil.which("gs")
    if gs:
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
                ], writable=out.parent)
                candidates.append(_optimize(out))
            except (subprocess.CalledProcessError, SandboxUnavailable):
                pass  # fall back to the lossless result
    return min(candidates, key=len)


def _optimize(path: Path) -> bytes:
    with pikepdf.open(path) as pdf:
        pdf.remove_unreferenced_resources()
        out = io.BytesIO()
        pdf.save(out, compress_streams=True, recompress_flate=True,
                 object_stream_mode=pikepdf.ObjectStreamMode.generate)
        return out.getvalue()
