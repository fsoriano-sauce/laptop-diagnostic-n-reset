#!/bin/bash
# build_auditor_mac.sh — build (or rebuild) the Auditor USB from macOS
# =====================================================================
#   bash auditor/build_auditor_mac.sh ~/Downloads/systemrescue-13.02-amd64.iso disk4
#   bash auditor/build_auditor_mac.sh <iso> --dry-run          # no disk touched, output to a temp folder
#
# What it does:
#   1. reads the volume label SystemRescue expects from the ISO header
#   2. extracts the ISO with bsdtar (macOS cannot mount isohybrid images)
#   3. ERASES the given disk as MBR + FAT32 with that label   <- destructive
#   4. copies the ISO contents, adds audit.py and the autorun hook
#   5. adds a GRUB entry that boots straight into the auditor with the
#      nouveau driver blacklisted (Vostro 7500 GTX 1650 Ti panics with it)
#      and a 5 second menu timeout
#   6. verifies the result and ejects the stick
#
# Safety: refuses any disk that is not an external USB device. Find the
# identifier with `diskutil list external physical`.
set -euo pipefail

ISO="${1:-}"
TARGET="${2:-}"
[ -n "$ISO" ] && [ -f "$ISO" ] || { echo "usage: $0 <systemrescue.iso> <diskN | --dry-run>"; exit 2; }
[ -n "$TARGET" ] || { echo "usage: $0 <systemrescue.iso> <diskN | --dry-run>"; exit 2; }
REPO="$(cd "$(dirname "$0")/.." && pwd)"
DRY=0; [ "$TARGET" = "--dry-run" ] && DRY=1

say() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }

# ── 1. label ─────────────────────────────────────────────────────────────
LABEL="$(python3 - "$ISO" <<'EOF'
import sys
with open(sys.argv[1], "rb") as f:
    f.seek(32768); pvd = f.read(2048)
print(pvd[40:72].decode("ascii", "replace").strip())
EOF
)"
[[ "$LABEL" =~ ^[A-Z0-9_]{1,11}$ ]] || { echo "unexpected ISO label '$LABEL'"; exit 1; }
say "ISO label: $LABEL"

# ── 2. extract ───────────────────────────────────────────────────────────
WORK="${TMPDIR:-/tmp}/auditor-build.$$"
mkdir -p "$WORK/iso"
say "extracting ISO to $WORK/iso (about 1.3 GB)"
bsdtar -xf "$ISO" -C "$WORK/iso"
grep -q "archisolabel=$LABEL" "$WORK/iso/boot/grub/grubsrcd.cfg" || { echo "grub config does not reference label $LABEL"; exit 1; }
[ -f "$WORK/iso/EFI/boot/bootx64.efi" ] || { echo "no EFI bootloader in ISO"; exit 1; }

# ── 3. erase ─────────────────────────────────────────────────────────────
if [ "$DRY" = 1 ]; then
    MNT="$WORK/out"; mkdir -p "$MNT"
    say "DRY RUN: writing to $MNT instead of a disk"
else
    DISK="/dev/${TARGET#/dev/}"
    INFO="$(diskutil info "$DISK")"
    echo "$INFO" | grep -E 'Device / Media Name|Disk Size|Protocol|Internal|Device Location|Removable' || true
    echo "$INFO" | grep -qE 'Protocol: +USB' || { echo "REFUSED: $DISK is not a USB device"; exit 1; }
    if echo "$INFO" | grep -qE 'Internal: +Yes'; then echo "REFUSED: $DISK is internal"; exit 1; fi
    say "ERASING $DISK as MBR/FAT32 '$LABEL'"
    diskutil unmountDisk force "$DISK" >/dev/null
    diskutil eraseDisk FAT32 "$LABEL" MBR "$DISK"
    MNT="/Volumes/$LABEL"
    for _ in 1 2 3 4 5 6 7 8 9 10; do [ -d "$MNT" ] && break; sleep 1; done
    [ -d "$MNT" ] || { echo "volume $MNT did not mount"; exit 1; }
fi

# ── 4. copy ──────────────────────────────────────────────────────────────
touch "$MNT/.metadata_never_index"
say "copying SystemRescue files"
/usr/bin/rsync -rt --copy-links --exclude .gitkeep "$WORK/iso/" "$MNT/"
say "adding audit.py and autorun hook"
# strip any CR so the files are LF regardless of how the repo was checked out
tr -d '\r' < "$REPO/auditor/audit.py" > "$MNT/audit.py"
mkdir -p "$MNT/autorun"
tr -d '\r' < "$REPO/auditor/autorun" > "$MNT/autorun/autorun"

# ── 5. boot entry ────────────────────────────────────────────────────────
cat > "$MNT/boot/grub/custom.cfg" <<EOF
# Laptop Auditor boot entry (written by auditor/build_auditor_mac.sh)
# nouveau is blacklisted: the Vostro 7500's GTX 1650 Ti panics the kernel with it.
# nomodeset is NOT used: it would disable the Intel display driver and the
# auditor could not read the panel EDID.
set timeout=5
menuentry 'Laptop Auditor (SystemRescue, autorun audit.py)' --id auditor {
	set gfxpayload=keep
	linux /sysresccd/boot/x86_64/vmlinuz archisobasedir=sysresccd archisolabel=$LABEL iomem=relaxed modprobe.blacklist=nouveau nouveau.modeset=0
	initrd /sysresccd/boot/intel_ucode.img /sysresccd/boot/amd_ucode.img /sysresccd/boot/x86_64/sysresccd.img
}
set default=auditor
EOF

# ── 6. tidy + verify ─────────────────────────────────────────────────────
dot_clean -m "$MNT" 2>/dev/null || true
rm -rf "$MNT/.fseventsd" "$MNT/.Trashes" "$MNT/.Spotlight-V100" 2>/dev/null || true
fail=0
check() { if eval "$2"; then say "ok   $1"; else say "FAIL $1"; fail=1; fi; }
check "EFI bootloader"            "[ -f '$MNT/EFI/boot/bootx64.efi' ]"
check "kernel + initramfs"        "[ -f '$MNT/sysresccd/boot/x86_64/vmlinuz' ] && [ -f '$MNT/sysresccd/boot/x86_64/sysresccd.img' ]"
check "root filesystem image"     "ls '$MNT/sysresccd/x86_64/'*.sfs >/dev/null 2>&1"
check "grub references label"     "grep -q 'archisolabel=$LABEL' '$MNT/boot/grub/grubsrcd.cfg'"
check "custom.cfg auditor entry"  "grep -q 'set default=auditor' '$MNT/boot/grub/custom.cfg'"
check "audit.py matches repo"     "[ \"\$(tr -d '\r' < '$REPO/auditor/audit.py' | shasum)\" = \"\$(shasum < '$MNT/audit.py')\" ]"
check "audit.py compiles"         "python3 -m py_compile '$MNT/audit.py' && rm -rf '$MNT/__pycache__'"
check "autorun is LF"             "! grep -q \$'\r' '$MNT/autorun/autorun'"
check "no AppleDouble files"      "[ -z \"\$(find '$MNT' -name '._*' 2>/dev/null | head -1)\" ]"
if [ "$DRY" = 0 ]; then
    check "volume is FAT32 $LABEL" "diskutil info '$MNT' | grep -q 'File System Personality: *MS-DOS FAT32' && diskutil info '$MNT' | grep -q 'Volume Name: *$LABEL'"
fi
say "stick contents:"; ls "$MNT"
rm -rf "$WORK/iso"
if [ "$fail" = 0 ]; then
    if [ "$DRY" = 0 ]; then diskutil eject "$DISK"; say "DONE. Stick ejected. First boot on a laptop: BIOS Secure Boot off, AHCI, USB first."; else say "DONE (dry run). Output left in $MNT"; fi
else
    say "one or more checks FAILED; stick left mounted for inspection"; exit 1
fi
