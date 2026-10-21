import io
import zipfile

from . import SkipFile
from .images import compress_image, format_for
from .presets import Preset

MEDIA_DIRS = ("word/media/", "ppt/media/", "xl/media/")


def compress_office(data: bytes, preset: Preset) -> bytes:
    """Recompress embedded images and rezip at maximum deflate.

    Images keep their names and formats because the document's .rels files
    point at them. Entry order is preserved so [Content_Types].xml stays first.
    """
    try:
        src = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise SkipFile("not a ZIP-based Office file (password-protected or legacy format?)")

    out = io.BytesIO()
    with src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as dst:
        for info in src.infolist():
            content = src.read(info)
            fmt = format_for(info.filename)
            if fmt and info.filename.startswith(MEDIA_DIRS):
                try:
                    smaller = compress_image(content, fmt, preset, embedded=True)
                    if len(smaller) < len(content):
                        content = smaller
                except Exception:
                    pass  # keep the original image
            entry = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            entry.external_attr = info.external_attr
            dst.writestr(entry, content, zipfile.ZIP_DEFLATED, compresslevel=9)
    return out.getvalue()
