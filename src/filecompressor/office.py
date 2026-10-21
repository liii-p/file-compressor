import io
import zipfile

from . import SkipFile
from .images import compress_image, format_for
from .presets import Preset

MEDIA_DIRS = ("word/media/", "ppt/media/", "xl/media/")

# Zip bomb limits. Real documents are mostly already-compressed media and expand
# 1-3x; bombs expand 1000x or more. Sizes are the ones declared in the zip, which
# zipfile enforces when reading (more data fails the CRC check).
MAX_ENTRIES = 50_000
MAX_TOTAL_RATIO = 100  # total uncompressed size vs the file's size...
MIN_TOTAL_LIMIT = 256 << 20  # ...but small files may always expand to this


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
        infos = src.infolist()
        _check_expansion(infos, len(data))
        for info in infos:
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


def _check_expansion(infos: list[zipfile.ZipInfo], size: int) -> None:
    if len(infos) > MAX_ENTRIES:
        raise SkipFile(f"has {len(infos)} entries, more than {MAX_ENTRIES}")
    total = sum(i.file_size for i in infos)
    if total > max(MAX_TOTAL_RATIO * size, MIN_TOTAL_LIMIT):
        raise SkipFile(f"expands to {total} bytes, which looks like a zip bomb")
