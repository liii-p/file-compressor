import argparse
import os
import sys
from pathlib import Path

from . import SkipFile, netguard, presets
from .images import FORMATS, compress_image
from .office import compress_office
from .pdf import compress_pdf

OFFICE_EXTS = {".docx", ".pptx", ".xlsx"}
SUPPORTED = set(FORMATS) | {".pdf"} | OFFICE_EXTS
OUTPUT_TAG = ".compressed"


def compress_file(path: Path, preset: presets.Preset) -> bytes:
    ext = path.suffix.lower()
    if ext in FORMATS:
        return compress_image(path.read_bytes(), FORMATS[ext], preset)
    if ext == ".pdf":
        return compress_pdf(path, preset)
    if ext in OFFICE_EXTS:
        return compress_office(path.read_bytes(), preset)
    raise SkipFile("unsupported file type")


def discover(paths: list[Path], recursive: bool):
    """Yield (file, path relative to the argument it came from)."""
    for root in paths:
        if root.is_file():
            yield root, Path(root.name)
        elif root.is_dir():
            files = root.rglob("*") if recursive else root.iterdir()
            for f in sorted(files):
                if (f.is_file() and f.suffix.lower() in SUPPORTED
                        and not f.name.startswith(".") and not f.stem.endswith(OUTPUT_TAG)):
                    yield f, f.relative_to(root)
        else:
            yield root, Path(root.name)  # reported as missing below


def output_path(path: Path, rel: Path, out_dir: Path | None) -> Path:
    if out_dir:
        return out_dir / rel
    return path.with_name(f"{path.stem}{OUTPUT_TAG}{path.suffix}")


def write_new(dest: Path, data: bytes, replace: bool) -> None:
    """Write dest as a fresh file, never through a symlink or hard link at that name."""
    if replace:
        dest.unlink(missing_ok=True)  # removes the link itself, not what it points to
    # O_EXCL refuses any existing entry, including a symlink planted after the checks in main().
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    with os.fdopen(fd, "wb") as f:
        f.write(data)


def human(n: int) -> str:
    for unit in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def parse_args(argv):
    p = argparse.ArgumentParser(
        prog="fcompress",
        description="Compress images, PDFs and Office documents locally. Never contacts the network.",
        epilog="Output: NAME.compressed.EXT next to each original, or with -o DIR, the original name "
               "inside DIR (keeping subfolders). Originals are never modified.",
    )
    p.add_argument("paths", nargs="+", type=Path, help="files or directories")
    p.add_argument("-p", "--preset", choices=presets.PRESETS, default="medium")
    p.add_argument("-q", "--quality", type=int, choices=range(1, 101), metavar="1-100",
                   help="override the preset's image quality")
    p.add_argument("--max-dim", type=int, metavar="PX", help="override the preset's max image dimension")
    p.add_argument("-o", "--output", type=Path, metavar="DIR",
                   help="write results here instead of NAME.compressed.EXT next to each file")
    p.add_argument("-r", "--recursive", action="store_true", help="descend into subdirectories")
    p.add_argument("-f", "--force", action="store_true", help="overwrite existing output files")
    p.add_argument("-n", "--dry-run", action="store_true", help="report savings without writing files")
    return p.parse_args(argv)


def main(argv=None) -> int:
    netguard.install()
    args = parse_args(argv)
    preset = presets.get(args.preset, args.quality, args.max_dim)

    rows, failed = [], False
    total_before = total_after = 0
    for path, rel in discover(args.paths, args.recursive):
        before = after = None
        try:
            if not path.exists():
                raise FileNotFoundError("no such file")
            dest = output_path(path, rel, args.output)
            if dest.is_symlink():
                raise SkipFile(f"{dest} is a symlink")
            if dest.resolve() == path.resolve():
                raise SkipFile("output would overwrite the input")
            if dest.exists() and not args.force:
                raise SkipFile(f"{dest} exists (use --force)")
            before = path.stat().st_size
            data = compress_file(path, preset)
            note = ""
            if len(data) >= before:
                data, note = path.read_bytes(), "already optimal"
            after = len(data)
            if not args.dry_run:
                dest.parent.mkdir(parents=True, exist_ok=True)
                write_new(dest, data, replace=args.force)
            total_before += before
            total_after += after
        except SkipFile as e:
            note = f"skipped: {e}"
        except Exception as e:
            note, failed = f"error: {e}", True
        rows.append((str(path), before, after, note))

    _print_table(rows, total_before, total_after, args.dry_run)
    return 1 if failed else 0


def _print_table(rows, total_before, total_after, dry_run):
    if not rows:
        print("no supported files found")
        return

    def saved(b, a):
        return f"{(1 - a / b) * 100:.0f}%" if b else "-"

    lines = [("file", "before", "after", "saved", "")]
    for name, b, a, note in rows:
        if b is None or a is None:
            lines.append((name, "-", "-", "-", note))
        else:
            lines.append((name, human(b), human(a), saved(b, a), note))
    lines.append(("total", human(total_before), human(total_after), saved(total_before, total_after),
                  "(dry run, nothing written)" if dry_run else ""))
    widths = [max(len(line[i]) for line in lines) for i in range(4)]
    for line in lines:
        print("  ".join([line[0].ljust(widths[0])] + [c.rjust(w) for c, w in zip(line[1:4], widths[1:])]
                        + [line[4]]).rstrip())


if __name__ == "__main__":
    sys.exit(main())
