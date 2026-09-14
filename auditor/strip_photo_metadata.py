#!/usr/bin/env python3
"""
strip_photo_metadata.py — remove EXIF/GPS and other metadata from listing photos
=================================================================================

The repo is public and eBay pulls listing photos straight from GitHub, so no
photo may say where it was taken. iPhone JPEGs carry GPS in EXIF, and again in
the MPF gain-map image appended after the main one.

  JPEG   keeps JFIF, the ICC colour profile and the image data byte for byte;
         drops EXIF, XMP, IPTC/Photoshop, MPF images and comments. A shot whose
         EXIF orientation is not upright is rotated and re-encoded (needs Pillow).
  PNG    drops eXIf, text and time chunks.
  HEIC, TIFF, WebP, DNG, AVIF are refused: export or convert them to JPEG.

    python3 auditor/strip_photo_metadata.py              # all of listing-photos/
    python3 auditor/strip_photo_metadata.py --check      # report only, exit 1 if any
    python3 auditor/strip_photo_metadata.py a.jpg dir/   # specific files or folders

.githooks/pre-commit runs this on every staged photo; enable it once per clone
with `git config core.hooksPath .githooks`.
"""

import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PHOTOS_DIR = os.path.join(os.path.dirname(HERE), "listing-photos")
JPEG = (".jpg", ".jpeg")
PNG = (".png",)
REFUSED = (".heic", ".heif", ".tif", ".tiff", ".webp", ".dng", ".avif")
JPEG_QUALITY = 85  # as photos_mac.py
PNG_DROP = {b"eXIf", b"tEXt", b"iTXt", b"zTXt", b"tIME"}


def exif_orientation(app1):
    """Orientation tag from an APP1 'Exif' body; 1 when absent or unreadable."""
    t = app1[6:]
    if len(t) < 8 or t[:2] not in (b"II", b"MM"):
        return 1
    e = "<" if t[:2] == b"II" else ">"
    ifd = struct.unpack(e + "I", t[4:8])[0]
    if ifd + 2 > len(t):
        return 1
    for k in range(struct.unpack(e + "H", t[ifd:ifd + 2])[0]):
        at = ifd + 2 + 12 * k
        if at + 12 > len(t):
            break
        tag = struct.unpack(e + "H", t[at:at + 2])[0]
        if tag == 0x0112:
            return struct.unpack(e + "H", t[at + 8:at + 10])[0]
    return 1


def clean_jpeg(data, path):
    if data[:2] != b"\xff\xd8":
        raise ValueError("not a JPEG")
    out, i, orientation = bytearray(data[:2]), 2, 1
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            raise ValueError(f"unreadable JPEG marker at byte {i}")
        m = data[i + 1]
        if m == 0xFF:  # fill byte
            i += 1
            continue
        if 0xD0 <= m <= 0xD7 or m == 0x01:  # markers without a length
            out += data[i:i + 2]
            i += 2
            continue
        ln = struct.unpack(">H", data[i + 2:i + 4])[0]
        body = data[i + 4:i + 2 + ln]
        if m == 0xDA:  # image data: keep through the main image's end, drop anything appended (MPF)
            eoi = data.find(b"\xff\xd9", i + 2 + ln)
            out += data[i:eoi + 2 if eoi >= 0 else len(data)]
            break
        if m == 0xE1 and body.startswith(b"Exif\0"):
            orientation = exif_orientation(body)
        is_meta = 0xE0 <= m <= 0xEF or m == 0xFE
        if not is_meta or (m == 0xE0 and body.startswith(b"JFIF\0")) or (m == 0xE2 and body.startswith(b"ICC_PROFILE\0")):
            out += data[i:i + 2 + ln]
        i += 2 + ln
    if orientation in (0, 1):
        return bytes(out)
    return rotated_jpeg(path)


def rotated_jpeg(path):
    """Dropping the orientation tag would show the shot sideways: rotate the pixels, re-encode."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        raise ValueError("needs rotating; install Pillow: python3 -m pip install --user Pillow")
    from io import BytesIO
    with Image.open(path) as im:
        icc = im.info.get("icc_profile")
        im = ImageOps.exif_transpose(im)
        if im.mode != "RGB":
            im = im.convert("RGB")
        im.info = {}
        buf = BytesIO()
        im.save(buf, "JPEG", quality=JPEG_QUALITY, icc_profile=icc)
    return buf.getvalue()


def clean_png(data):
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    out, i = bytearray(data[:8]), 8
    while i + 12 <= len(data):
        ln, kind = struct.unpack(">I4s", data[i:i + 8])
        if kind not in PNG_DROP:
            out += data[i:i + 12 + ln]
        i += 12 + ln
        if kind == b"IEND":
            break
    return bytes(out)


def photos(paths):
    for p in paths:
        if os.path.isdir(p):
            for root, dirs, files in os.walk(p):
                dirs.sort()
                for f in sorted(files):
                    if f.lower().endswith(JPEG + PNG + REFUSED):
                        yield os.path.join(root, f)
        else:
            yield p


def main(argv):
    check = "--check" in argv
    paths = [a for a in argv if a != "--check"] or [PHOTOS_DIR]
    dirty = failed = total = 0
    for path in photos(paths):
        ext = os.path.splitext(path)[1].lower()
        total += 1
        if ext in REFUSED:
            print(f"  refused   {path}: convert to JPEG first", file=sys.stderr)
            failed += 1
            continue
        if ext not in JPEG + PNG:
            continue
        try:
            data = open(path, "rb").read()
            clean = clean_png(data) if ext in PNG else clean_jpeg(data, path)
        except (OSError, ValueError) as e:
            print(f"  failed    {path}: {e}", file=sys.stderr)
            failed += 1
            continue
        if clean == data:
            continue
        dirty += 1
        if check:
            print(f"  metadata  {path}")
        else:
            open(path, "wb").write(clean)
            print(f"  stripped  {path}")
    verb = "carry metadata" if check else "stripped"
    print(f"{total} photos, {dirty} {verb}, {failed} failed")
    return 1 if failed or (check and dirty) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
