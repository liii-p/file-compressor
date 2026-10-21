import io
import os
import random
import socket
import subprocess
import zipfile

import pikepdf
import pytest
from PIL import Image

from filecompressor import SkipFile, cli, images, netguard, office, pdf, presets, sandbox
from filecompressor.images import compress_image
from filecompressor.office import compress_office

MEDIUM = presets.get("medium")


def photo(size=(3000, 2000), mode="RGB") -> Image.Image:
    """A photo-like image: smooth gradient plus noise, so it compresses realistically."""
    rng = random.Random(0)
    w, h = size
    im = Image.linear_gradient("L").resize(size).convert("RGB")
    noise = Image.frombytes("RGB", size, bytes(rng.randrange(40) for _ in range(w * h * 3)))
    im = Image.blend(im, noise, 0.2)
    if mode == "RGBA":
        im.putalpha(Image.linear_gradient("L").resize(size))
    return im


def encode(im: Image.Image, fmt: str, **params) -> bytes:
    out = io.BytesIO()
    im.save(out, fmt, **params)
    return out.getvalue()


def test_jpeg_smaller_and_resized():
    src = encode(photo(), "JPEG", quality=100)
    out = compress_image(src, "JPEG", MEDIUM)
    assert len(out) < len(src)
    assert max(Image.open(io.BytesIO(out)).size) == 2560


def test_jpeg_applies_exif_orientation():
    im = photo((400, 200))
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90° clockwise
    out = compress_image(encode(im, "JPEG", quality=100, exif=exif), "JPEG", MEDIUM)
    assert Image.open(io.BytesIO(out)).size == (200, 400)


def test_png_keeps_alpha():
    src = encode(photo((800, 600), "RGBA"), "PNG", compress_level=0)
    out = compress_image(src, "PNG", MEDIUM)
    assert len(out) < len(src)
    result = Image.open(io.BytesIO(out)).convert("RGBA")
    assert result.getextrema()[3][0] < 50  # still has transparent pixels


def test_png_high_is_lossless():
    im = photo((300, 200))
    out = compress_image(encode(im, "PNG", compress_level=0), "PNG", presets.get("high"))
    assert Image.open(io.BytesIO(out)).convert("RGB").tobytes() == im.tobytes()


@pytest.mark.parametrize("fmt,params", [("WEBP", {"quality": 100}), ("TIFF", {})])
def test_other_formats_shrink(fmt, params):
    src = encode(photo(), fmt, **params)
    out = compress_image(src, fmt, MEDIUM)
    assert len(out) < len(src)
    assert Image.open(io.BytesIO(out)).format == fmt


def test_animated_gif_keeps_frames():
    frames = [photo((200, 200)).rotate(angle).quantize(64) for angle in (0, 90, 180)]
    src = encode(frames[0], "GIF", save_all=True, append_images=frames[1:], duration=100)
    out = compress_image(src, "GIF", MEDIUM)
    assert Image.open(io.BytesIO(out)).n_frames == 3


def make_pdf(path):
    # Pillow embeds the image as a JPEG; 600 dpi gives Ghostscript something to downsample.
    photo().save(path, "PDF", resolution=600, quality=95)


needs_gs = pytest.mark.skipif(not pdf.find_ghostscript(), reason="Ghostscript not installed")
needs_sandbox = pytest.mark.skipif(not os.path.exists(sandbox.SANDBOX_EXEC), reason="needs macOS sandbox-exec")


@needs_gs
def test_pdf_with_ghostscript(tmp_path):
    src = tmp_path / "doc.pdf"
    make_pdf(src)
    out = pdf.compress_pdf(src, MEDIUM)
    assert len(out) < src.stat().st_size / 2
    assert len(pikepdf.open(io.BytesIO(out)).pages) == 1


def test_pdf_without_ghostscript(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf, "find_ghostscript", lambda: None)
    src = tmp_path / "doc.pdf"
    make_pdf(src)
    out = pdf.compress_pdf(src, MEDIUM)
    assert len(pikepdf.open(io.BytesIO(out)).pages) == 1


@pytest.fixture
def gs_calls(monkeypatch):
    """Record Ghostscript command lines instead of running them."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        raise pdf.subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(pdf, "find_ghostscript", lambda: "/opt/homebrew/bin/gs")
    monkeypatch.setattr(pdf, "run_offline", fake_run)
    return calls


def test_pdf_passes_absolute_paths_to_ghostscript(tmp_path, monkeypatch, gs_calls):
    # gs reads a bare "@name" argument as a file of extra options, so never pass a bare name.
    monkeypatch.chdir(tmp_path)
    make_pdf(tmp_path / "@x.pdf")
    pdf.compress_pdf(pdf.Path("@x.pdf"), MEDIUM)
    assert gs_calls[0][-1] == str(tmp_path.resolve() / "@x.pdf")
    assert all(not arg.startswith("@") for arg in gs_calls[0])


def test_pdf_skips_ghostscript_for_postscript(tmp_path, gs_calls):
    # qpdf tolerates junk before the header, so this opens as a PDF; gs would run it as PostScript.
    src = tmp_path / "doc.pdf"
    make_pdf(src)
    src.write_bytes(b"%!PS-Adobe-3.0\n" + src.read_bytes())
    out = pdf.compress_pdf(src, MEDIUM)
    assert gs_calls == []
    assert len(pikepdf.open(io.BytesIO(out)).pages) == 1


def run_bash(script, tmp_path, readable=(), timeout=30):
    allowed = tmp_path / "allowed"
    allowed.mkdir(exist_ok=True)
    return sandbox.run_offline(["/bin/bash", "-c", script], writable=allowed,
                               readable=["/bin", *readable], timeout=timeout)


@needs_sandbox
def test_sandbox_limits_reads_writes_exec_and_network(tmp_path):
    secret, input_file = tmp_path / "secret", tmp_path / "input"
    secret.write_text("secret\n")
    input_file.write_text("input\n")  # `read` fails at a missing final newline
    run_bash(f"echo ok > '{tmp_path}/allowed/f'", tmp_path)
    assert (tmp_path / "allowed" / "f").exists()
    run_bash(f"read line < '{input_file}'", tmp_path, readable=[input_file])
    for script in [f"echo no > '{tmp_path}/new'", f"read line < '{secret}'",
                   "exec /usr/bin/true", "exec 3<>/dev/tcp/1.1.1.1/80"]:
        with pytest.raises(subprocess.CalledProcessError):
            run_bash(script, tmp_path)
    assert not (tmp_path / "new").exists()


@needs_sandbox
def test_sandbox_timeout(tmp_path):
    with pytest.raises(subprocess.TimeoutExpired):
        run_bash("while :; do :; done", tmp_path, timeout=1)


def test_pdf_skips_ghostscript_without_sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "SANDBOX_EXEC", str(tmp_path / "missing"))
    monkeypatch.setattr(pdf, "find_ghostscript", lambda: "/opt/homebrew/bin/gs")
    src = tmp_path / "doc.pdf"
    make_pdf(src)
    out = pdf.compress_pdf(src, MEDIUM)  # lossless fallback, gs never run
    assert len(pikepdf.open(io.BytesIO(out)).pages) == 1


def test_image_pixel_limit(monkeypatch):
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)
    for size in [(40, 40), (100, 100)]:  # Pillow warns above the limit, errors above twice it
        with pytest.raises(SkipFile, match="larger than"):
            compress_image(encode(photo(size), "PNG"), "PNG", MEDIUM)


def test_image_frame_limit(monkeypatch):
    monkeypatch.setattr(images, "MAX_FRAMES", 2)
    frames = [photo((50, 50)).rotate(angle).quantize(64) for angle in (0, 90, 180)]
    src = encode(frames[0], "GIF", save_all=True, append_images=frames[1:], duration=100)
    with pytest.raises(SkipFile, match="frames"):
        compress_image(src, "GIF", MEDIUM)


def test_encrypted_pdf_skipped(tmp_path):
    src = tmp_path / "doc.pdf"
    make_pdf(src)
    with pikepdf.open(src, allow_overwriting_input=True) as p:
        p.save(src, encryption=pikepdf.Encryption(owner="o", user="u"))
    with pytest.raises(SkipFile):
        pdf.compress_pdf(src, MEDIUM)


def make_docx(image: bytes) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("_rels/.rels", "<Relationships/>")
        z.writestr("word/document.xml", "<document/>")
        z.writestr("word/media/image1.png", image)
    return out.getvalue()


def test_office_recompresses_media():
    image = encode(photo((1200, 900)), "PNG", compress_level=0)
    src = make_docx(image)
    out = compress_office(src, MEDIUM)
    assert len(out) < len(src)
    with zipfile.ZipFile(io.BytesIO(out)) as z:
        assert z.namelist() == zipfile.ZipFile(io.BytesIO(src)).namelist()
        assert Image.open(io.BytesIO(z.read("word/media/image1.png"))).format == "PNG"


def test_office_rejects_non_zip():
    with pytest.raises(SkipFile):
        compress_office(b"not a zip", MEDIUM)


def zip_infos(sizes):
    infos = []
    for i, size in enumerate(sizes):
        info = zipfile.ZipInfo(f"f{i}")
        info.file_size = size
        infos.append(info)
    return infos


@pytest.mark.parametrize("sizes,match", [([300 << 20], "zip bomb"), ([1] * 50_001, "entries")])
def test_office_expansion_limits(sizes, match):
    with pytest.raises(SkipFile, match=match):
        office._check_expansion(zip_infos(sizes), size=1 << 20)


def test_office_expansion_allows_large_real_files():
    office._check_expansion(zip_infos([900 << 20, 200 << 20]), size=1 << 30)  # a 1 GB pptx


@pytest.fixture
def guarded(monkeypatch):
    for name in ("socket", "create_connection", "getaddrinfo", "gethostbyname", "gethostbyname_ex"):
        monkeypatch.setattr(socket, name, getattr(socket, name))  # restored after the test
    netguard.install()


def test_netguard_blocks_internet(guarded):
    with pytest.raises(netguard.NetworkBlockedError):
        socket.create_connection(("example.com", 80))
    with pytest.raises(netguard.NetworkBlockedError):
        socket.socket()
    with pytest.raises(netguard.NetworkBlockedError):
        socket.getaddrinfo("example.com", 443)
    socket.socket(socket.AF_UNIX).close()


def test_cli_writes_outputs_without_overwriting(tmp_path, guarded, capsys):
    (tmp_path / "a.jpg").write_bytes(encode(photo(), "JPEG", quality=100))
    (tmp_path / "notes.txt").write_text("ignored")
    original = (tmp_path / "a.jpg").read_bytes()

    assert cli.main([str(tmp_path)]) == 0
    assert (tmp_path / "a.jpg").read_bytes() == original
    assert (tmp_path / "a.compressed.jpg").stat().st_size < len(original)

    # A second run must not overwrite the existing output or recompress it.
    assert cli.main([str(tmp_path)]) == 0
    assert "exists" in capsys.readouterr().out
    assert not (tmp_path / "a.compressed.compressed.jpg").exists()


def test_cli_output_dir_and_dry_run(tmp_path, guarded):
    src = tmp_path / "in"
    (src / "sub").mkdir(parents=True)
    (src / "sub" / "b.png").write_bytes(encode(photo((500, 500)), "PNG", compress_level=0))

    assert cli.main([str(src), "-r", "-o", str(tmp_path / "dry"), "-n"]) == 0
    assert not (tmp_path / "dry").exists()

    assert cli.main([str(src), "-r", "-o", str(tmp_path / "out")]) == 0
    assert (tmp_path / "out" / "sub" / "b.png").exists()


@pytest.mark.parametrize("force", [False, True])
def test_cli_never_writes_through_symlink(tmp_path, guarded, capsys, force):
    (tmp_path / "a.jpg").write_bytes(encode(photo(), "JPEG", quality=100))
    target = tmp_path / "victim"
    (tmp_path / "a.compressed.jpg").symlink_to(target)  # dangling, so exists() is False

    cli.main([str(tmp_path / "a.jpg")] + (["-f"] if force else []))
    assert "symlink" in capsys.readouterr().out
    assert not target.exists()


def test_cli_force_replaces_hard_link_not_target(tmp_path, guarded):
    (tmp_path / "a.jpg").write_bytes(encode(photo(), "JPEG", quality=100))
    victim = tmp_path / "victim"
    victim.write_text("keep me")
    (tmp_path / "a.compressed.jpg").hardlink_to(victim)

    assert cli.main([str(tmp_path / "a.jpg"), "-f"]) == 0
    assert victim.read_text() == "keep me"
    assert (tmp_path / "a.compressed.jpg").read_bytes()[:2] == b"\xff\xd8"


def test_cli_reports_errors(tmp_path, guarded):
    (tmp_path / "broken.jpg").write_bytes(b"not an image")
    assert cli.main([str(tmp_path / "broken.jpg")]) == 1
