# file-compressor
Local app to compress files/images. Runs entirely on your machine and never contacts a server.

Supports JPEG, PNG, WebP, AVIF, GIF (including animated), TIFF, PDF, and Office documents (docx/pptx/xlsx, by recompressing their embedded images).

Built with Claude Code.

## Install (macOS)
```sh
brew install uv ghostscript
uv sync
```
Ghostscript is optional but strongly recommended. Without it, PDFs only get lossless cleanup.

## Usage
```sh
uv run fcompress photo.jpg report.pdf deck.pptx      # writes photo.compressed.jpg etc.
uv run fcompress ~/Pictures -r -p low -o ~/smaller   # whole tree into another folder
uv run fcompress scan.pdf -n                         # dry run: show savings only
```
| Option | Meaning |
|---|---|
| `-p low\|medium\|high` | Quality preset (default `medium`) |
| `-q 1-100` | Override image quality |
| `--max-dim PX` | Override max image width/height |
| `-o DIR` | Output directory (keeps subfolder structure) |
| `-r` | Recurse into subdirectories |
| `-f` | Overwrite existing outputs |
| `-n` | Dry run |

## Where the output goes
Originals are never modified or moved.

**By default**, each compressed file is saved in the same folder as its original, with `.compressed` added before the extension:
```
~/Desktop/photo.jpg        →  ~/Desktop/photo.compressed.jpg
~/Docs/report.pdf          →  ~/Docs/report.compressed.pdf
```

**With `-o DIR`**, files keep their original names and go into `DIR`, which is created if needed:
- A file you name directly goes straight into `DIR`: `fcompress ~/Desktop/photo.jpg -o ~/smaller` → `~/smaller/photo.jpg`
- A folder's files keep their subfolder layout inside `DIR`: `fcompress ~/Pictures -r -o ~/smaller` turns `~/Pictures/2024/trip/a.jpg` into `~/smaller/2024/trip/a.jpg`

Other rules:
- Existing output files are never overwritten. The file is skipped with a message unless you pass `-f`.
- When scanning a folder, `*.compressed.*` files are ignored, so running the tool again doesn't compress its own output.
- If a file can't be made smaller, the output is an unchanged copy, marked "already optimal".
- With `-n` (dry run), nothing is written anywhere.

| Preset | Image quality | Max dimension | PNG | PDF images |
|---|---|---|---|---|
| high | 85 | original | lossless | 300 dpi |
| medium | 75 | 2560 px | ≤256 colours if smaller | 150 dpi |
| low | 60 | 1600 px | ≤128 colours | 72 dpi |

## How it stays offline
- Dependencies (Pillow, pikepdf) only perform local work. The network is needed only for `uv sync` and `brew install`.
- On startup, `netguard` replaces Python's socket functions, so an internet connection attempted through Python's `socket` module raises an error. This is a tripwire against accidental network use, not a hard guarantee: native code and low-level APIs don't go through it.
- Ghostscript runs under macOS `sandbox-exec` with network access denied. The sandbox also stops it from starting other programs or writing anywhere except a temporary folder, so a malicious PDF can't use it to reach the rest of your files. If `sandbox-exec` is missing, Ghostscript is not run and PDFs get lossless cleanup only.

For a hard guarantee, run the whole tool in a network-denying sandbox:
```sh
sandbox-exec -p '(version 1)(allow default)(deny network*)' .venv/bin/fcompress FILES...
```

## Development
```sh
uv run pytest
```
