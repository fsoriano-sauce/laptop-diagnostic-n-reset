#!/usr/bin/env python3
"""
photos_mac.py — iPhone photo albums per laptop, via Photos on this Mac
=======================================================================

Photos on this Mac and the iPhone share one iCloud Photos library, so:

  albums   For every audited unit in auditor/audits/*.json, create an album
           "<TAG> <model>" inside the Photos folder "Laptop Line". It shows
           up on the iPhone within a minute. Shoot the unit's photos into
           that album (see README: a two-action Shortcut, or select the
           shots and "Add to Album").

  export   For each album that has photos, export them into
           listing-photos/<TAG>/ as 01.jpg, 02.jpg, ... in the order they
           were taken, resized to 2000 px on the long edge for eBay. The
           first shot becomes the listing's gallery image, so take the
           hero shot first. Re-running only exports albums whose photo
           count changed.

  status   Album -> photo count, and whether listing-photos/<TAG>/ is
           up to date.

    python3 auditor/photos_mac.py albums
    python3 auditor/photos_mac.py status
    python3 auditor/photos_mac.py export            # every album with photos
    python3 auditor/photos_mac.py export JV25GS3    # one unit

macOS only. First run pops a permission dialog to let this control Photos.
"""

import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
AUDITS = os.path.join(HERE, "audits")
PHOTOS_DIR = os.path.join(REPO, "listing-photos")
FOLDER = "Laptop Line"
MAX_EDGE = 2000
JPEG_QUALITY = 85


def osa(script, timeout=600):
    p = subprocess.run(["osascript", "-"], input=script, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip() or "osascript failed")
    return p.stdout.rstrip("\n")


def audited_units():
    units = {}
    for path in sorted(glob.glob(os.path.join(AUDITS, "*.json"))):
        try:
            d = json.load(open(path))
        except (OSError, ValueError):
            continue
        tag = (d.get("identity") or {}).get("service_tag")
        if d.get("status") == "audited" and tag:
            units[tag] = (d.get("identity") or {}).get("model") or ""
    return units


def album_name(tag, model):
    return f"{tag} {model}".strip()


def existing_albums():
    """{album name: photo count} for albums inside the Laptop Line folder."""
    out = osa(f'''
tell application "Photos"
  if not (exists folder "{FOLDER}") then return ""
  set res to ""
  repeat with a in albums of folder "{FOLDER}"
    set res to res & (name of a) & tab & (count of media items of a) & linefeed
  end repeat
  return res
end tell''')
    result = {}
    for line in out.splitlines():
        if "\t" in line:
            n, c = line.rsplit("\t", 1)
            result[n] = int(c)
    return result


def cmd_albums():
    units = audited_units()
    if not units:
        print("no audited units in auditor/audits/")
        return
    have = existing_albums()
    made = []
    for tag, model in units.items():
        name = album_name(tag, model)
        if any(n.startswith(tag) for n in have):
            continue
        osa(f'''
tell application "Photos"
  if not (exists folder "{FOLDER}") then make new folder named "{FOLDER}"
  make new album named "{name}" at folder "{FOLDER}"
end tell''')
        made.append(name)
    print(f"albums in '{FOLDER}': {len(have) + len(made)}   created now: {', '.join(made) or 'none'}")
    print("They appear on the iPhone under Albums > Laptop Line within a minute.")


def cmd_status():
    have = existing_albums()
    units = audited_units()
    for tag, model in units.items():
        name = next((n for n in have if n.startswith(tag)), None)
        count = have.get(name, 0) if name else None
        local = len(glob.glob(os.path.join(PHOTOS_DIR, tag, "*.jpg")))
        state = "no album" if name is None else f"{count} in album, {local} exported" + ("" if count == local else "  <- run export")
        print(f"  {tag:8} {model:16} {state}")


def export_album(tag, name, count):
    dest = os.path.join(PHOTOS_DIR, tag)
    tmp = tempfile.mkdtemp(prefix=f"photos-{tag}-")
    # Ordered filenames straight from Photos (iPhone names are sequential = capture order)
    order = osa(f'''
tell application "Photos"
  set res to ""
  repeat with m in media items of album "{name}" of folder "{FOLDER}"
    set res to res & (filename of m) & linefeed
  end repeat
  return res
end tell''').splitlines()
    osa(f'''
tell application "Photos"
  export (get media items of album "{name}" of folder "{FOLDER}") to POSIX file "{tmp}"
end tell''', timeout=1800)
    exported = {os.path.splitext(f)[0]: f for f in os.listdir(tmp)}
    if not exported:
        print(f"  {tag}: export produced no files")
        return 0
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    os.makedirs(dest)
    n = 0
    seq = [os.path.splitext(o)[0] for o in order] + [k for k in exported if k not in {os.path.splitext(o)[0] for o in order}]
    for key in seq:
        src = exported.get(key)
        if not src:
            continue
        n += 1
        out = os.path.join(dest, f"{n:02d}.jpg")
        subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", str(JPEG_QUALITY),
                        "-Z", str(MAX_EDGE), os.path.join(tmp, src), "--out", out],
                       capture_output=True, check=False)
        if not os.path.exists(out):
            shutil.copy(os.path.join(tmp, src), out)
    shutil.rmtree(tmp, ignore_errors=True)
    sizes = sum(os.path.getsize(os.path.join(dest, f)) for f in os.listdir(dest)) / 1e6
    print(f"  {tag}: {n} photos -> listing-photos/{tag}/ ({sizes:.1f} MB)")
    return n


def cmd_export(only):
    have = existing_albums()
    units = audited_units()
    total = 0
    for tag, model in units.items():
        if only and tag not in only:
            continue
        name = next((n for n in have if n.startswith(tag)), None)
        if not name or not have[name]:
            continue
        local = len(glob.glob(os.path.join(PHOTOS_DIR, tag, "*.jpg")))
        if local == have[name] and not only:
            continue
        total += export_album(tag, name, have[name])
    print(f"exported {total} photos. Next: git add listing-photos && commit && push, then regenerate listings.")


if __name__ == "__main__":
    if sys.platform != "darwin":
        sys.exit("macOS only (drives the Photos app)")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "albums":
        cmd_albums()
    elif cmd == "status":
        cmd_status()
    elif cmd == "export":
        cmd_export(set(a.upper() for a in sys.argv[2:]))
    else:
        sys.exit(__doc__)
