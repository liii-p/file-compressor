import io
import os
import warnings

from PIL import Image, ImageOps, ImageSequence, features

from . import SkipFile
from .presets import Preset

# Decompression bomb limits, in pixels rather than bytes: 300 MP covers large
# scans and panoramas (about 1.2 GB as RGBA). Pillow only warns between 1x and
# 2x its limit, so compress_image turns that warning into a skip.
Image.MAX_IMAGE_PIXELS = 300_000_000
MAX_FRAMES = 2000
MAX_FRAME_PIXELS = 1_000_000_000  # summed over all frames

FORMATS = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
    ".gif": "GIF",
    ".tif": "TIFF",
    ".tiff": "TIFF",
    ".avif": "AVIF",
}


def format_for(name: str) -> str | None:
    return FORMATS.get(os.path.splitext(name)[1].lower())


def compress_image(data: bytes, fmt: str, preset: Preset, embedded: bool = False) -> bytes:
    """Re-encode an image in its own format.

    `embedded` is for images inside Office documents: their on-page size is
    fixed by the document XML, so we keep EXIF orientation as-is rather than
    rotating pixels.
    """
    if fmt == "AVIF" and not features.check("avif"):
        raise SkipFile("this Pillow build has no AVIF support")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            im = Image.open(io.BytesIO(data))
    except (Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise SkipFile(f"image is larger than {Image.MAX_IMAGE_PIXELS} pixels") from None

    with im:
        if getattr(im, "n_frames", 1) > 1:
            return _save_frames(im, fmt, preset)

        im.load()
        icc = im.info.get("icc_profile")
        exif = im.info.get("exif") if embedded else None
        if not embedded:
            im = ImageOps.exif_transpose(im)
        im = _resize(im, preset.max_dim)

        if fmt == "JPEG":
            return _save_jpeg(im, preset, icc, exif)
        if fmt == "PNG":
            return _save_png(im, preset, icc)
        if fmt == "WEBP":
            lossless = preset.lossless_webp and _is_lossless_webp(data)
            return _save(im if _has_alpha(im) else im.convert("RGB"), "WEBP",
                         lossless=lossless, quality=100 if lossless else preset.quality,
                         method=6, icc_profile=icc, exif=exif)
        if fmt == "AVIF":
            return _save(_to_rgb(im), "AVIF", quality=preset.quality, icc_profile=icc, exif=exif)
        if fmt == "GIF":
            return _save(im, "GIF", optimize=True)
        if fmt == "TIFF":
            return _save(im, "TIFF", compression="tiff_adobe_deflate", icc_profile=icc)
    raise SkipFile(f"unsupported image format {fmt}")


def _save(im: Image.Image, fmt: str, **params) -> bytes:
    out = io.BytesIO()
    im.save(out, fmt, **{k: v for k, v in params.items() if v is not None})
    return out.getvalue()


def _save_jpeg(im, preset, icc, exif) -> bytes:
    if im.mode not in ("RGB", "L", "CMYK"):
        im = im.convert("RGB")
    return _save(im, "JPEG", quality=preset.quality, optimize=True, progressive=True,
                 icc_profile=icc, exif=exif)


def _save_png(im, preset, icc) -> bytes:
    if im.mode not in ("1", "L", "LA", "P", "RGB", "RGBA"):
        im = _to_rgb(im)
    candidates = [_save(im, "PNG", optimize=True, icc_profile=icc)]
    if preset.png_colors:
        if _has_alpha(im):
            quantized = im.convert("RGBA").quantize(preset.png_colors, method=Image.Quantize.FASTOCTREE)
        else:
            quantized = im.convert("RGB").quantize(preset.png_colors)
        candidates.append(_save(quantized, "PNG", optimize=True, icc_profile=icc))
    return min(candidates, key=len)


def _save_frames(im: Image.Image, fmt: str, preset: Preset) -> bytes:
    """Animated GIF/WebP and multi-page TIFF: re-encode every frame."""
    if im.n_frames > MAX_FRAMES:
        raise SkipFile(f"has {im.n_frames} frames, more than {MAX_FRAMES}")
    frames, durations, pixels = [], [], 0
    for frame in ImageSequence.Iterator(im):
        pixels += frame.width * frame.height
        if pixels > MAX_FRAME_PIXELS:
            raise SkipFile(f"frames add up to more than {MAX_FRAME_PIXELS} pixels")
        durations.append(frame.info.get("duration", 100))
        frames.append(_resize(frame.convert("RGBA"), preset.max_dim))
    first, rest = frames[0], frames[1:]
    if fmt == "TIFF":
        return _save(first, "TIFF", save_all=True, append_images=rest, compression="tiff_adobe_deflate")
    params = dict(save_all=True, append_images=rest, duration=durations, loop=im.info.get("loop", 0))
    if fmt == "WEBP":
        return _save(first, "WEBP", quality=preset.quality, method=6, **params)
    if fmt == "GIF":
        return _save(first, "GIF", optimize=True, disposal=2, **params)
    raise SkipFile(f"multi-frame {fmt} is not supported")


def _resize(im: Image.Image, max_dim: int | None) -> Image.Image:
    if max_dim and max(im.size) > max_dim:
        im = im.copy()
        im.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
    return im


def _has_alpha(im: Image.Image) -> bool:
    return im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info


def _to_rgb(im: Image.Image) -> Image.Image:
    return im.convert("RGBA" if _has_alpha(im) else "RGB")


def _is_lossless_webp(data: bytes) -> bool:
    return b"VP8L" in data[:4096]
