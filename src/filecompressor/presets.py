from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Preset:
    quality: int  # JPEG / WebP / AVIF quality, 1-100
    max_dim: int | None  # longest side in pixels; None keeps the original size
    png_colors: int | None  # palette size for lossy PNG; None means lossless only
    pdf_setting: str  # Ghostscript -dPDFSETTINGS value
    lossless_webp: bool = False  # keep lossless WebP sources lossless


PRESETS = {
    "high": Preset(quality=85, max_dim=None, png_colors=None, pdf_setting="/printer", lossless_webp=True),
    "medium": Preset(quality=75, max_dim=2560, png_colors=256, pdf_setting="/ebook"),
    "low": Preset(quality=60, max_dim=1600, png_colors=128, pdf_setting="/screen"),
}


def get(name: str, quality: int | None = None, max_dim: int | None = None) -> Preset:
    preset = PRESETS[name]
    if quality is not None:
        preset = replace(preset, quality=quality)
    if max_dim is not None:
        preset = replace(preset, max_dim=max_dim)
    return preset
