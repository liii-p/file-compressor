import io
import shutil
import subprocess
import tempfile
from pathlib import Path

import pikepdf

from . import SkipFile
from .presets import Preset
from .sandbox import run_offline


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
            out = Path(tmp) / "out.pdf"
            try:
                run_offline([
                    gs, "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.6",
                    f"-dPDFSETTINGS={preset.pdf_setting}",
                    "-dSAFER", "-dNOPAUSE", "-dBATCH", "-dQUIET",
                    f"-sOutputFile={out}", str(path),
                ])
                candidates.append(_optimize(out))
            except subprocess.CalledProcessError:
                pass  # fall back to the lossless result
    return min(candidates, key=len)


def _optimize(path: Path) -> bytes:
    with pikepdf.open(path) as pdf:
        pdf.remove_unreferenced_resources()
        out = io.BytesIO()
        pdf.save(out, compress_streams=True, recompress_flate=True,
                 object_stream_mode=pikepdf.ObjectStreamMode.generate)
        return out.getvalue()
