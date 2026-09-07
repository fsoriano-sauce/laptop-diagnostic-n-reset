#!/usr/bin/env python3
"""
audit.py v3.0 — Laptop line auditor (runs on SystemRescue, stdlib only)
=======================================================================

Per unit, in this order:

  ATTENDED  (about one minute at the keyboard)
    1. Preflight: identity, BIOS storage mode must be AHCI/NVMe, internal
       disk must be visible. Stops here with instructions if not.
    2. Display test (solid colours), keyboard test (every key), speaker
       tone, fingerprint confirmation if not auto-detected.

  UNATTENDED  (walk away after the tests)
    3. Hardware scan. Every command's raw output is saved next to the JSON
       so any value can be re-derived later without rebooting the laptop.
    4. Secure erase of the internal disk (NVMe format / TRIM / sanitize),
       with a 10 second abort window and a post-erase zero check.
    5. Write audits/<SERVICE_TAG>.json and audits/<SERVICE_TAG>/raw/*,
       then power off.

Nothing here grades cosmetics or computes prices. Those live in
inventory.csv and the listing generator respectively.

Usage (normally launched by the autorun script):
    python3 audit.py                 # full run
    python3 audit.py --dry-run       # no erase, no poweroff
    python3 audit.py --no-erase      # everything except the erase
    python3 audit.py --skip-tests    # unattended only (bench testing)

Requires root. Tested against SystemRescue 13.x (Python 3.14, nvme-cli,
smartmontools, alsa-utils, dmidecode, pciutils, usbutils, util-linux).
"""

import argparse
import fcntl
import glob
import json
import os
import re
import select
import struct
import subprocess
import sys
import termios
import time
from datetime import datetime, timezone

VERSION = "3.1"
MIN_PLAUSIBLE_DATE = "2026-09-01"    # a system clock before this means the laptop's RTC is wrong
MIN_INTERNAL_DISK_GB = 64            # anything smaller is a USB stick or cache module
ERASE_ABORT_WINDOW_S = 10
KEYBOARD_TEST_TIMEOUT_S = 240
ARCHISO_MNT = "/run/archiso/bootmnt"
FALLBACK_SAVE_DIR = "/tmp"

ANSI_RESET = "\033[0m"
ANSI_GREEN = "\033[42m\033[30m"
ANSI_DIM = "\033[2m"
ANSI_RED = "\033[41m\033[97m"
ANSI_BOLD = "\033[1m"


# ═══════════════════════════════════════════════════════════════════════════════
#  SMALL HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def run(cmd, timeout=30):
    """Run a shell command. Returns (rc, stdout, stderr). Never raises."""
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           errors="replace", timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"
    except Exception as e:  # noqa: BLE001
        return 1, "", str(e)


def out(cmd, timeout=30):
    """Stdout of a shell command, stripped, '' on failure."""
    return run(cmd, timeout)[1].strip()


def read_text(path, default=""):
    try:
        with open(path, "r", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return default


def read_bytes(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return b""


def to_int(s, default=None):
    try:
        return int(str(s).strip())
    except (TypeError, ValueError):
        return default


def to_float(s, default=None):
    try:
        return float(str(s).strip())
    except (TypeError, ValueError):
        return default


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def clear_screen():
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


def banner(text, char="═", width=64):
    print()
    print(char * width)
    print(f"  {text}")
    print(char * width)


def wait_key(prompt="Press ENTER to continue..."):
    try:
        input(prompt)
    except EOFError:
        pass


def prompt_choice(question, options):
    """options: dict of single-key -> label. Returns the chosen key (upper)."""
    while True:
        print(f"\n  {question}")
        for k, label in options.items():
            print(f"    [{k}] {label}")
        try:
            ans = input("  > ").strip().upper()
        except EOFError:
            return list(options.keys())[0]
        if ans in options:
            return ans
        print(f"  Enter one of: {', '.join(options.keys())}")


def key_within(seconds):
    """Wait up to `seconds` for any keypress on stdin. True if pressed."""
    try:
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        new = termios.tcgetattr(fd)
        new[3] = new[3] & ~(termios.ICANON | termios.ECHO)
        termios.tcsetattr(fd, termios.TCSANOW, new)
        try:
            termios.tcflush(fd, termios.TCIFLUSH)
            end = time.time() + seconds
            while time.time() < end:
                remaining = max(0.0, end - time.time())
                sys.stdout.write(f"\r    {int(remaining) + 1:2d}s ")
                sys.stdout.flush()
                r, _, _ = select.select([fd], [], [], min(1.0, remaining))
                if r:
                    os.read(fd, 64)
                    return True
            return False
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
            sys.stdout.write("\r        \r")
    except (termios.error, OSError, ValueError):
        time.sleep(seconds)
        return False


class Tee:
    """Mirror stdout to a log file so the console transcript is evidence too."""

    def __init__(self, path):
        self.stream = sys.stdout
        self.f = open(path, "a", buffering=1, errors="replace")

    def write(self, s):
        self.stream.write(s)
        self.f.write(s)

    def flush(self):
        self.stream.flush()
        self.f.flush()

    def fileno(self):
        return self.stream.fileno()

    def isatty(self):
        return self.stream.isatty()


class RawStore:
    """Every raw command output lands here. Derive later, never re-boot."""

    def __init__(self, directory):
        self.dir = directory
        os.makedirs(directory, exist_ok=True)
        self.files = []

    def save(self, name, content):
        path = os.path.join(self.dir, name)
        mode = "wb" if isinstance(content, bytes) else "w"
        try:
            with open(path, mode) as f:
                f.write(content)
            self.files.append(name)
        except OSError:
            pass

    def capture(self, name, cmd, timeout=30):
        """Run cmd, save stdout(+stderr) as name, return stdout."""
        rc, so, se = run(cmd, timeout)
        body = so if not se else f"{so}\n--- stderr (rc={rc}) ---\n{se}"
        self.save(name, body)
        return so


# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE 0 — WRITABLE USB
# ═══════════════════════════════════════════════════════════════════════════════

def boot_device():
    """Device the live system booted from, e.g. /dev/sdb1, or ''."""
    for line in read_text("/proc/mounts").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == ARCHISO_MNT:
            return parts[0]
    return ""


def parent_disk(dev):
    """/dev/sdb1 -> /dev/sdb, /dev/nvme0n1p1 -> /dev/nvme0n1."""
    if not dev:
        return ""
    real = os.path.realpath(dev)
    name = os.path.basename(real)
    for cand in os.listdir("/sys/block") if os.path.isdir("/sys/block") else []:
        if name == cand or os.path.isdir(f"/sys/block/{cand}/{name}"):
            return f"/dev/{cand}"
    return re.sub(r"p?\d+$", "", real)


def mount_usb_rw():
    if os.path.ismount(ARCHISO_MNT):
        rc, _, _ = run(f"mount -o remount,rw {ARCHISO_MNT}")
        if rc == 0:
            print(f"  [✓] USB writable at {ARCHISO_MNT}")
            return ARCHISO_MNT
        print(f"  [!] Could not remount {ARCHISO_MNT} read-write")
    print("  [!] USB not writable. Results go to /tmp and are LOST on poweroff.")
    return FALLBACK_SAVE_DIR


# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE 1 — PREFLIGHT (identity, storage mode, internal disk)
# ═══════════════════════════════════════════════════════════════════════════════

def express_service_code(tag):
    if not tag or not re.fullmatch(r"[A-Z0-9]+", tag.upper()):
        return None
    n = 0
    for c in tag.upper():
        n = n * 36 + (int(c) if c.isdigit() else ord(c) - ord("A") + 10)
    return str(n)


def read_identity(raw):
    dmi = "/sys/class/dmi/id"
    ident = {
        "service_tag": read_text(f"{dmi}/product_serial") or out("dmidecode -s system-serial-number") or None,
        "manufacturer": read_text(f"{dmi}/sys_vendor") or None,
        "model": read_text(f"{dmi}/product_name") or None,
        "sku": read_text(f"{dmi}/product_sku") or None,
        "family": read_text(f"{dmi}/product_family") or None,
        "bios_version": read_text(f"{dmi}/bios_version") or None,
        "bios_date": read_text(f"{dmi}/bios_date") or None,
        "chassis_type": read_text(f"{dmi}/chassis_type") or None,
    }
    if ident["service_tag"]:
        ident["service_tag"] = ident["service_tag"].strip().upper()
    ident["express_service_code"] = express_service_code(ident["service_tag"])
    raw.capture("dmidecode.txt", "dmidecode", timeout=20)
    return ident


def storage_controller_mode(raw):
    """
    Returns ('ahci'|'rst_or_vmd'|'unknown', description).
    Intel RST RAID and Intel VMD both present a PCI class 0104 (RAID)
    controller with vendor 8086. In that mode the NVMe SSD is hidden from
    Linux (10th gen) and from stock Windows media (all gens).
    """
    lspci_n = raw.capture("lspci-n.txt", "lspci -n")
    lspci_nn = raw.capture("lspci-nn.txt", "lspci -nn")
    raw.capture("lspci-vvv.txt", "lspci -vvv", timeout=20)
    raid = []
    for line in lspci_n.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[1].startswith("0104") and parts[2].startswith("8086:"):
            raid.append(parts[0])
    if raid:
        desc = [l for l in lspci_nn.splitlines() if l.split()[0] in raid]
        return "rst_or_vmd", "; ".join(desc) or ", ".join(raid)
    if not lspci_n:
        return "unknown", "lspci produced no output"
    return "ahci", "no Intel RAID/VMD controller present"


def list_block_devices(raw):
    js = raw.capture("lsblk.json",
                     "lsblk -J -b -o NAME,PATH,TYPE,RM,HOTPLUG,SIZE,TRAN,ROTA,MODEL,SERIAL,VENDOR,MOUNTPOINTS")
    try:
        return json.loads(js).get("blockdevices", [])
    except (ValueError, AttributeError):
        return []


def find_internal_disks(devices, boot_parent):
    """Non-removable NVMe/SATA disks >= MIN_INTERNAL_DISK_GB, largest first."""
    found = []
    for d in devices:
        if d.get("type") != "disk":
            continue
        path = d.get("path") or f"/dev/{d.get('name')}"
        if path == boot_parent:
            continue
        tran = (d.get("tran") or "").lower()
        if tran == "usb" or d.get("rm") in (True, "1", 1):
            continue
        if tran not in ("nvme", "sata", "ata", ""):
            continue
        size_gb = (to_int(d.get("size"), 0) or 0) / 1e9
        if size_gb < MIN_INTERNAL_DISK_GB:
            continue
        found.append({
            "device": path,
            "transport": tran or ("nvme" if "nvme" in path else "sata"),
            "size_gb": round(size_gb),
            "size_bytes": to_int(d.get("size"), 0),
            "model": (d.get("model") or "").strip() or None,
            "serial": (d.get("serial") or "").strip() or None,
            "rotational": d.get("rota") in (True, "1", 1),
        })
    found.sort(key=lambda x: x["size_gb"], reverse=True)
    return found


def preflight(raw):
    """Returns (identity, disks, problems). problems non-empty => stop."""
    problems = []
    ident = read_identity(raw)
    print(f"  Service tag : {ident['service_tag']}   Model: {ident['model']}   BIOS: {ident['bios_version']}")

    mode, desc = storage_controller_mode(raw)
    if mode == "rst_or_vmd":
        problems.append(
            "Storage controller is in Intel RST/VMD (RAID) mode.\n"
            f"      {desc}\n"
            "      Reboot, press F2, set  SATA/NVMe Operation  (or  SATA Operation)  to  AHCI/NVMe,\n"
            "      save, and boot this USB again. Both the audit and the Windows install need this.")
    boot = boot_device()
    bparent = parent_disk(boot)
    disks = find_internal_disks(list_block_devices(raw), bparent)
    if not disks and mode != "rst_or_vmd":
        problems.append(
            f"No internal disk of at least {MIN_INTERNAL_DISK_GB} GB is visible.\n"
            "      Check BIOS storage mode (AHCI/NVMe) and that the SSD is seated.")
    if disks:
        d = disks[0]
        print(f"  Internal SSD: {d['device']}  {d['size_gb']} GB  {d['transport'].upper()}  {d['model'] or ''}")
    if len(disks) > 1:
        others = ", ".join(f"{x['device']} {x['size_gb']}GB" for x in disks[1:])
        print(f"  [!] More than one internal disk: {others}. Only the largest is audited and erased.")
    return ident, disks, problems


# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE 2 — ATTENDED TESTS
# ═══════════════════════════════════════════════════════════════════════════════

COLOR_SCREENS = [
    ("WHITE", "\033[107m", "\033[30m"),
    ("RED", "\033[41m", "\033[97m"),
    ("GREEN", "\033[42m", "\033[30m"),
    ("BLUE", "\033[44m", "\033[97m"),
    ("BLACK", "\033[40m", "\033[97m"),
]


def display_test():
    """Solid colour screens. Operator looks for dead pixels, bleed, lines."""
    banner("DISPLAY TEST")
    print("  Each screen fills with one colour. Look for dead pixels, bright spots,")
    print("  lines, backlight bleed, and yellowing. Press ENTER to advance.")
    wait_key("  Press ENTER to start...")
    try:
        size = os.get_terminal_size()
        lines, cols = size.lines, size.columns
    except OSError:
        lines, cols = 50, 200
    scr = sys.__stdout__          # screen only; keep the fills out of console.log
    try:
        for name, bg, fg in COLOR_SCREENS:
            scr.write("\033[2J\033[H" + bg)
            for _ in range(lines):
                scr.write(" " * cols)
            row, col = lines // 2, max(0, (cols - len(name) - 24) // 2)
            scr.write(f"\033[{row};{col}H{fg}  [ {name} — ENTER for next ]  ")
            scr.flush()
            input()
    except (EOFError, OSError):
        pass
    finally:
        scr.write(ANSI_RESET + "\033[2J\033[H")
        scr.flush()
    grade = prompt_choice("Rate the SCREEN (colours still fresh in mind):",
                          {"A": "Flawless — no dead pixels, no marks, no bleed",
                           "B": "Good — minor: 1-2 dead pixels, faint scuff, light wear",
                           "C": "Damaged — cracked, scratched, backlight bleed, many dead pixels"})
    note = None
    if grade in ("B", "C"):
        try:
            note = input("  Note the screen issue (what / where) > ").strip() or None
        except EOFError:
            note = None
    return {"result": "pass" if grade in ("A", "B") else "fail", "grade": grade, "note": note}


# Linux input keycodes. Required = main block + arrows. Optional groups are
# reported but never fail the unit (F-row is Fn-dependent on Dell firmware).
KEY_ROWS = [
    [("ESC", 1, "opt"), ("F1", 59, "opt"), ("F2", 60, "opt"), ("F3", 61, "opt"), ("F4", 62, "opt"),
     ("F5", 63, "opt"), ("F6", 64, "opt"), ("F7", 65, "opt"), ("F8", 66, "opt"), ("F9", 67, "opt"),
     ("F10", 68, "opt"), ("F11", 87, "opt"), ("F12", 88, "opt"), ("PRTSC", 99, "opt"),
     ("INS", 110, "opt"), ("DEL", 111, "req")],
    [("`", 41, "req"), ("1", 2, "req"), ("2", 3, "req"), ("3", 4, "req"), ("4", 5, "req"),
     ("5", 6, "req"), ("6", 7, "req"), ("7", 8, "req"), ("8", 9, "req"), ("9", 10, "req"),
     ("0", 11, "req"), ("-", 12, "req"), ("=", 13, "req"), ("BKSP", 14, "req")],
    [("TAB", 15, "req"), ("Q", 16, "req"), ("W", 17, "req"), ("E", 18, "req"), ("R", 19, "req"),
     ("T", 20, "req"), ("Y", 21, "req"), ("U", 22, "req"), ("I", 23, "req"), ("O", 24, "req"),
     ("P", 25, "req"), ("[", 26, "req"), ("]", 27, "req"), ("\\", 43, "req")],
    [("CAPS", 58, "req"), ("A", 30, "req"), ("S", 31, "req"), ("D", 32, "req"), ("F", 33, "req"),
     ("G", 34, "req"), ("H", 35, "req"), ("J", 36, "req"), ("K", 37, "req"), ("L", 38, "req"),
     (";", 39, "req"), ("'", 40, "req"), ("ENTER", 28, "req")],
    [("LSHIFT", 42, "req"), ("Z", 44, "req"), ("X", 45, "req"), ("C", 46, "req"), ("V", 47, "req"),
     ("B", 48, "req"), ("N", 49, "req"), ("M", 50, "req"), (",", 51, "req"), (".", 52, "req"),
     ("/", 53, "req"), ("RSHIFT", 54, "req")],
    [("LCTRL", 29, "req"), ("WIN", 125, "req"), ("LALT", 56, "req"), ("SPACE", 57, "req"),
     ("RALT", 100, "req"), ("RCTRL", 97, "req"), ("←", 105, "req"), ("↑", 103, "req"),
     ("↓", 108, "req"), ("→", 106, "req")],
    [("HOME", 102, "opt"), ("END", 107, "opt"), ("PGUP", 104, "opt"), ("PGDN", 109, "opt"),
     ("MENU", 127, "opt")],
    [("NUMLK", 69, "pad"), ("KP/", 98, "pad"), ("KP*", 55, "pad"), ("KP-", 74, "pad"),
     ("KP7", 71, "pad"), ("KP8", 72, "pad"), ("KP9", 73, "pad"), ("KP+", 78, "pad"),
     ("KP4", 75, "pad"), ("KP5", 76, "pad"), ("KP6", 77, "pad"), ("KP1", 79, "pad"),
     ("KP2", 80, "pad"), ("KP3", 81, "pad"), ("KP0", 82, "pad"), ("KP.", 83, "pad"),
     ("KPENT", 96, "pad")],
]
EVIOCGRAB = 0x40044590
INPUT_EVENT = struct.Struct("llHHi")
EV_KEY = 1


def find_keyboard_devices(raw):
    text = read_text("/proc/bus/input/devices")
    raw.save("proc_bus_input_devices.txt", text)
    devs = []
    skip = ("power button", "sleep button", "lid switch", "video bus", "hotkey", "wmi")
    for block in text.split("\n\n"):
        name_m = re.search(r'N: Name="(.*)"', block)
        h_m = re.search(r"H: Handlers=(.*)", block)
        ev_m = re.search(r"B: EV=([0-9a-f]+)", block)
        if not (name_m and h_m and ev_m):
            continue
        name = name_m.group(1)
        if "kbd" not in h_m.group(1):
            continue
        if any(s in name.lower() for s in skip):
            continue
        ev = int(ev_m.group(1), 16)
        if not ev & (1 << EV_KEY):
            continue
        e = re.search(r"event(\d+)", h_m.group(1))
        if e:
            devs.append((name, f"/dev/input/event{e.group(1)}"))
    # Internal keyboard first (i8042 / AT Translated), then anything else.
    devs.sort(key=lambda d: 0 if "at translated" in d[0].lower() else 1)
    return devs


def _draw_keyboard(pressed, remaining_req, elapsed):
    scr = sys.__stdout__          # screen only; redraws stay out of console.log
    status = (f"{ANSI_GREEN} all required keys seen {ANSI_RESET} finish the numpad / F-row if present, then ESC ESC ESC"
              if remaining_req == 0 else f"{remaining_req} required keys left")
    buf = ["\033[H",
           f"{ANSI_BOLD}  KEYBOARD TEST{ANSI_RESET}  press every key · ESC×3 when done · {int(elapsed)}s   \n"
           f"  {status}   \n\n"]
    for row in KEY_ROWS:
        line = "  "
        for label, code, group in row:
            cell = f" {label} "
            if code in pressed:
                line += ANSI_GREEN + cell + ANSI_RESET
            elif group == "req":
                line += ANSI_RED + cell + ANSI_RESET
            else:
                line += ANSI_DIM + cell + ANSI_RESET
            line += " "
        buf.append(line + "   \n")
    buf.append(f"\n  {ANSI_RED} red {ANSI_RESET} required  {ANSI_DIM} dim {ANSI_RESET} optional (F-row needs Fn held)  "
               f"{ANSI_GREEN} green {ANSI_RESET} seen        \n")
    scr.write("".join(buf))
    scr.flush()


def keyboard_test(raw):
    banner("KEYBOARD TEST")
    devs = find_keyboard_devices(raw)
    if not devs:
        print("  [!] No keyboard input device found. Test skipped.")
        return {"result": "not_tested", "reason": "no evdev keyboard device"}
    print("  Reading: " + "; ".join(f"{n} ({p})" for n, p in devs))
    print("  Press every key, including Shift/Ctrl/Alt on both sides, the arrows, the numpad and the F-row.")
    print("  The test does NOT end on its own: when you have pressed everything, press ESC three times.")
    wait_key("  Press ENTER to start...")

    required = {code for row in KEY_ROWS for _, code, g in row if g == "req"}
    pad = {code for row in KEY_ROWS for _, code, g in row if g == "pad"}
    labels = {code: label for row in KEY_ROWS for label, code, _ in row}
    pressed, extra = set(), set()
    fds = []
    for _, path in devs:
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            fcntl.ioctl(fd, EVIOCGRAB, 1)
            fds.append(fd)
        except OSError:
            continue
    if not fds:
        print("  [!] Could not open keyboard devices. Test skipped.")
        return {"result": "not_tested", "reason": "could not open evdev devices"}

    clear_screen()
    start = time.time()
    last_event = start
    esc_streak = 0
    finished_reason = "esc"
    try:
        _draw_keyboard(pressed, len(required), 0)
        while True:
            r, _, _ = select.select(fds, [], [], 0.5)
            changed = False
            for fd in r:
                try:
                    data = os.read(fd, INPUT_EVENT.size * 64)
                except (BlockingIOError, OSError):
                    continue
                for off in range(0, len(data) - INPUT_EVENT.size + 1, INPUT_EVENT.size):
                    _, _, typ, code, val = INPUT_EVENT.unpack_from(data, off)
                    if typ != EV_KEY or val != 1:
                        continue
                    last_event = time.time()
                    changed = True
                    esc_streak = esc_streak + 1 if code == 1 else 0
                    (pressed if code in labels else extra).add(code)
            if changed:
                _draw_keyboard(pressed, len(required - pressed), time.time() - start)
            if esc_streak >= 3:
                break
            # No auto-finish: the operator decides when every key has been
            # pressed (numpad and F-row included) and ends with ESC x3.
            if time.time() - last_event > KEYBOARD_TEST_TIMEOUT_S:
                finished_reason = "timeout"
                break
    finally:
        for fd in fds:
            try:
                fcntl.ioctl(fd, EVIOCGRAB, 0)
                os.close(fd)
            except OSError:
                pass
        try:
            termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
        except (termios.error, ValueError):
            pass
        clear_screen()

    missing_req = sorted(labels[c] for c in required - pressed)
    pad_used = bool(pad & pressed)
    missing_pad = sorted(labels[c] for c in pad - pressed) if pad_used else []
    missing_opt = sorted(labels[c] for c in
                         {code for row in KEY_ROWS for _, code, g in row if g == "opt"} - pressed)
    result = "pass" if not missing_req and not missing_pad else "fail"
    print(f"  Keys seen: {len(pressed)}   required missing: {missing_req or 'none'}")
    if pad_used:
        print(f"  Numpad missing: {missing_pad or 'none'}")
    if result == "fail":
        ans = prompt_choice("Required keys did not register. Confirm:",
                            {"F": "Keyboard FAIL (dead keys)", "P": "Pass anyway (operator skipped keys)"})
        if ans == "P":
            result = "pass_operator_override"
    return {
        "result": result,
        "finished_by": finished_reason,
        "keys_seen": len(pressed),
        "missing_required": missing_req,
        "numpad_present": pad_used,
        "missing_numpad": missing_pad,
        "missing_optional": missing_opt,
        "devices": [n for n, _ in devs],
    }


def speaker_test(raw):
    banner("SPEAKER TEST")
    cards = raw.capture("proc_asound_cards.txt", "cat /proc/asound/cards")
    if not cards.strip() or "no soundcards" in cards:
        print("  [i] No ALSA sound card in this live environment (Intel SOF firmware is not")
        print("      shipped with SystemRescue). Speakers get checked in Windows instead.")
        return {"result": "not_tested", "reason": "no sound card exposed in live environment"}
    for ctl in ("Master", "Speaker", "PCM", "Headphone"):
        run(f"amixer -q sset '{ctl}' unmute 2>/dev/null; amixer -q sset '{ctl}' 80% 2>/dev/null", timeout=5)
    raw.capture("amixer.txt", "amixer")
    while True:
        print("  Playing a tone on left then right...")
        rc = 1
        for dev in ("default", "plughw:0,0", "plughw:1,0"):
            rc, _, _ = run(f"timeout 8 speaker-test -D {dev} -t sine -f 523 -c 2 -l 1", timeout=12)
            if rc in (0, 124):
                break
        if rc not in (0, 124):
            print("  [!] speaker-test could not open a playback device.")
            return {"result": "not_tested", "reason": "no playback device"}
        ans = prompt_choice("Did you hear the tone from BOTH speakers?",
                            {"Y": "Yes, both", "N": "No / only one / distorted", "R": "Replay"})
        if ans == "R":
            continue
        return {"result": "pass" if ans == "Y" else "fail"}


FINGERPRINT_USB_IDS = ("27c6:", "138a:", "06cb:00", "1c7a:", "2808:", "04f3:0c", "10a5:", "298d:")


def detect_fingerprint(raw):
    lsusb = raw.capture("lsusb.txt", "lsusb")
    low = lsusb.lower()
    if "fingerprint" in low or any(i in low for i in FINGERPRINT_USB_IDS):
        return "yes"
    if "fingerprint" in out("udevadm info --export-db 2>/dev/null | grep -i fingerprint").lower():
        return "yes"
    return "unknown"


BATCH_DEFAULTS_FILE = "batch_defaults.cfg"   # lives in audits/ on the stick; not *.json so the CSV builder ignores it
COLOR_CHOICES = {"1": "Black", "2": "Silver", "3": "Gray", "4": "White", "5": "Blue", "6": "Other"}


def load_batch_defaults(audits_dir):
    try:
        with open(os.path.join(audits_dir, BATCH_DEFAULTS_FILE)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_batch_defaults(audits_dir, defaults):
    try:
        with open(os.path.join(audits_dir, BATCH_DEFAULTS_FILE), "w") as f:
            json.dump(defaults, f)
    except OSError:
        pass


def prompt_yn(question, default="Y"):
    d = default if default in ("Y", "N") else "Y"
    while True:
        try:
            ans = input(f"\n  {question} [Y/N]  (ENTER = {d}) > ").strip().upper()
        except EOFError:
            return d
        if ans == "":
            return d
        if ans in ("Y", "N"):
            return ans
        print("  Enter Y or N.")


def prompt_color(default=None):
    print("\n  Laptop colour?")
    for k, v in COLOR_CHOICES.items():
        print(f"    [{k}] {v}")
    hint = f"  (ENTER = {default})" if default else ""
    while True:
        try:
            ans = input(f"  >{hint} ").strip()
        except EOFError:
            return default
        if ans == "" and default:
            return default
        if ans in COLOR_CHOICES:
            return COLOR_CHOICES[ans]
        print(f"  Enter 1-{len(COLOR_CHOICES)}" + (" or ENTER" if default else ""))


def run_grading(audits_dir, skip):
    """Cosmetic grades. Attended, so they run before the walk-away message.
    Colour and charger defaults persist on the stick across units; screen
    (asked in the display test) and body are asked fresh every time."""
    if skip:
        return {}
    banner("CONDITION")
    defaults = load_batch_defaults(audits_dir)
    chassis = prompt_choice("Rate the BODY — lid, deck, bottom, hinges, ports:",
                            {"A": "Mint — no marks",
                             "B": "Good — minor scuffs/scratches, normal wear",
                             "C": "Rough — dents, cracks, deep scratches, missing parts"})
    chassis_note = None
    if chassis in ("B", "C"):
        try:
            chassis_note = input("  Note the damage (where / how bad) > ").strip() or None
        except EOFError:
            chassis_note = None
    charger = prompt_yn("Charger included?", defaults.get("charger", "Y"))
    color = prompt_color(defaults.get("color"))
    save_batch_defaults(audits_dir, {"color": color, "charger": charger})
    return {"chassis_grade": chassis, "chassis_note": chassis_note,
            "charger": charger, "color": color}


def run_attended_tests(raw, skip):
    tests = {}
    if skip:
        return {"display": {"result": "not_tested"}, "keyboard": {"result": "not_tested"},
                "speaker": {"result": "not_tested"}}
    tests["display"] = display_test()
    tests["keyboard"] = keyboard_test(raw)
    tests["speaker"] = speaker_test(raw)
    return tests


# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE 3 — UNATTENDED HARDWARE SCAN
# ═══════════════════════════════════════════════════════════════════════════════

def cpu_generation(model):
    m = re.search(r"i[3579]-(\d{4,5})", model or "")
    if m:
        n = m.group(1)
        return int(n[:2]) if len(n) == 5 else int(n[0])
    m = re.search(r"Core\(TM\) Ultra \d+ (\d)", model or "")
    if m:
        return 100 + int(m.group(1))     # Core Ultra series 1/2 -> 101/102
    m = re.search(r"Ryzen\s+\d\s+(\d)", model or "")
    if m:
        return int(m.group(1))
    return None


def scan_cpu(raw):
    info = read_text("/proc/cpuinfo")
    raw.save("proc_cpuinfo.txt", info)
    raw.capture("lscpu.txt", "lscpu")
    model, threads, cores = None, 0, set()
    for line in info.splitlines():
        if line.startswith("model name") and model is None:
            model = line.split(":", 1)[1].strip()
        elif line.startswith("processor"):
            threads += 1
        elif line.startswith("core id"):
            cores.add(line.split(":", 1)[1].strip())
    return {"model": model, "cores": len(cores) or None, "threads": threads or None,
            "generation": cpu_generation(model)}


def scan_memory(raw):
    text = raw.capture("dmidecode-memory.txt", "dmidecode -t 17", timeout=20)
    raw.save("proc_meminfo.txt", read_text("/proc/meminfo"))
    modules, slots = [], 0
    for block in text.split("\n\n"):
        if "Memory Device" not in block:
            continue
        slots += 1
        # dmidecode prints "Size: 8 GiB" (or GB / MB / MiB); empty slots say
        # "Size: No Module Installed" and are skipped.
        size_m = re.search(r"^\s*Size:\s*(\d+)\s*(GB|GiB|MB|MiB)", block, re.M)
        if not size_m:
            continue
        val, unit = int(size_m.group(1)), size_m.group(2)
        size_gb = val if unit in ("GB", "GiB") else val // 1024
        def field(name):
            m = re.search(rf"^\s*{name}:\s*(.+)$", block, re.M)
            v = m.group(1).strip() if m else ""
            return None if v in ("", "Unknown", "Not Specified", "None") else v
        speed = field("Configured Memory Speed") or field("Speed")
        modules.append({
            "size_gb": size_gb,
            "type": field("Type"),
            "speed_mts": to_int(speed.split()[0]) if speed else None,
            "form_factor": field("Form Factor"),
            "manufacturer": field("Manufacturer"),
            "part_number": field("Part Number"),
        })
    total = sum(m["size_gb"] for m in modules)
    if not total:
        # DMI unavailable: fall back to MemTotal, rounded UP to the next
        # power of two so 15.4 GB reports as 16 and not 15.
        m = re.search(r"MemTotal:\s*(\d+)", read_text("/proc/meminfo") or "")
        gb = int(m.group(1)) / 1048576 if m else 0
        total = 1 << (int(gb - 1).bit_length()) if gb else 0
    types = {m["type"] for m in modules if m["type"]}
    return {"total_gb": total or None, "type": next(iter(types)) if types else None,
            "slots_total": slots or None, "slots_used": len(modules) or None, "modules": modules}


def scan_gpu(raw):
    text = raw.capture("lspci-vga.txt", "lspci -nn -d ::0300; lspci -nn -d ::0302; lspci -nn -d ::0380")
    discrete, integrated = None, None
    for line in text.splitlines():
        if not line.strip():
            continue
        desc = line.split(": ", 1)[1] if ": " in line else line
        if "[10de:" in line or "NVIDIA" in line or "[1002:" in line:
            discrete = discrete or desc.strip()
        elif "[8086:" in line:
            integrated = integrated or desc.strip()
    return {"discrete": discrete, "integrated": integrated}


STANDARD_DIAGONALS = (10.1, 11.6, 12.5, 13.3, 13.4, 14.0, 15.6, 16.0, 17.3)


def parse_edid(raw_edid):
    if len(raw_edid) < 128 or raw_edid[:8] != b"\x00\xff\xff\xff\xff\xff\xff\x00":
        return None
    r = {"width_px": None, "height_px": None, "width_mm": None, "height_mm": None, "name": None}
    d = raw_edid[54:72]
    if d[0] or d[1]:
        r["width_px"] = d[2] | ((d[4] & 0xF0) << 4)
        r["height_px"] = d[5] | ((d[7] & 0xF0) << 4)
        r["width_mm"] = d[12] | ((d[14] & 0xF0) << 4)
        r["height_mm"] = d[13] | ((d[14] & 0x0F) << 8)
    if not r["width_mm"] and raw_edid[21] and raw_edid[22]:
        r["width_mm"], r["height_mm"] = raw_edid[21] * 10, raw_edid[22] * 10
    for off in (54, 72, 90, 108):
        blk = raw_edid[off:off + 18]
        if blk[0:3] == b"\x00\x00\x00" and blk[3] == 0xFC:
            r["name"] = blk[5:18].decode("ascii", "replace").strip()
    return r


def scan_display(raw):
    best = None
    for conn in sorted(glob.glob("/sys/class/drm/card*-*")):
        status = read_text(f"{conn}/status")
        edid = read_bytes(f"{conn}/edid")
        if not edid:
            continue
        raw.save(f"edid-{os.path.basename(conn)}.bin", edid)
        parsed = parse_edid(edid)
        if not parsed:
            continue
        internal = any(k in conn for k in ("eDP", "LVDS", "DSI"))
        cand = {"connector": os.path.basename(conn), "status": status, "internal": internal, **parsed}
        if best is None or (internal and not best["internal"]):
            best = cand
    raw.capture("xrandr.txt", "xrandr 2>&1")
    if not best:
        return {"width_px": None, "height_px": None, "diagonal_in": None, "note": "no EDID readable"}
    diag = None
    if best["width_mm"] and best["height_mm"]:
        d_in = ((best["width_mm"] ** 2 + best["height_mm"] ** 2) ** 0.5) / 25.4
        snap = min(STANDARD_DIAGONALS, key=lambda s: abs(s - d_in))
        diag = snap if abs(snap - d_in) <= 0.35 else round(d_in, 1)
    w, h = best["width_px"], best["height_px"]
    return {
        "connector": best["connector"], "panel_name": best["name"],
        "width_px": w, "height_px": h, "resolution": f"{w}x{h}" if w and h else None,
        "physical_mm": [best["width_mm"], best["height_mm"]],
        "diagonal_in": diag,
        "aspect": "16:10" if w and h and abs(w / h - 1.6) < 0.02 else ("16:9" if w and h and abs(w / h - 16 / 9) < 0.02 else None),
        "resolution_class": "4K/Retina Class" if (w or 0) > 2500 else "Standard",
    }


def scan_battery(raw):
    raw.capture("upower.txt", "upower -d", timeout=15)
    for bat in sorted(glob.glob("/sys/class/power_supply/BAT*")):
        def rd(n):
            return read_text(f"{bat}/{n}") or None
        dump = "\n".join(f"{os.path.basename(p)}={read_text(p)}" for p in sorted(glob.glob(f"{bat}/*")) if os.path.isfile(p))
        raw.save(f"sysfs-{os.path.basename(bat)}.txt", dump)
        full = to_int(rd("energy_full")) or to_int(rd("charge_full"))
        design = to_int(rd("energy_full_design")) or to_int(rd("charge_full_design"))
        unit = "wh" if rd("energy_full") else "ah"
        health = round(100 * full / design) if full and design else None
        cycles = to_int(rd("cycle_count"))
        # Dell reports charge in uAh; convert to Wh with the design voltage so
        # the listing can say "97 Wh battery, 80% health" on every model.
        volts = (to_int(rd("voltage_min_design")) or 0) / 1e6
        def wh(v):
            if not v:
                return None
            return round(v / 1e6, 1) if unit == "wh" else (round(v / 1e6 * volts, 1) if volts else None)
        return {
            "present": True, "health_pct": health, "charge_pct": to_int(rd("capacity")),
            "cycles": cycles if cycles else None,
            "design_wh": wh(design),
            "full_wh": wh(full),
            "status": rd("status"), "manufacturer": rd("manufacturer"),
            "model": rd("model_name"), "serial": rd("serial_number"),
        }
    return {"present": False, "health_pct": None, "charge_pct": None, "cycles": None}


def scan_storage(raw, disk):
    if not disk:
        return {"present": False}
    dev = disk["device"]
    info = dict(disk)
    info["present"] = True
    js = raw.capture("smartctl.json", f"smartctl -j -a {dev}", timeout=60)
    try:
        sm = json.loads(js)
    except ValueError:
        sm = {}
    info["smart_passed"] = (sm.get("smart_status") or {}).get("passed")
    info["model"] = sm.get("model_name") or info.get("model")
    info["firmware"] = sm.get("firmware_version")
    info["temperature_c"] = (sm.get("temperature") or {}).get("current")
    info["power_on_hours"] = (sm.get("power_on_time") or {}).get("hours")
    nv = sm.get("nvme_smart_health_information_log") or {}
    if nv:
        info["percentage_used"] = nv.get("percentage_used")
        duw = nv.get("data_units_written")
        info["data_written_tb"] = round(duw * 512000 / 1e12, 2) if isinstance(duw, (int, float)) else None
        info["media_errors"] = nv.get("media_errors")
        info["unsafe_shutdowns"] = nv.get("unsafe_shutdowns")
        info["critical_warning"] = nv.get("critical_warning")
        info["power_cycles"] = nv.get("power_cycles")
        raw.capture("nvme-id-ctrl.json", f"nvme id-ctrl {dev} -o json", timeout=15)
        raw.capture("nvme-smart-log.txt", f"nvme smart-log {dev}", timeout=15)
    else:
        table = ((sm.get("ata_smart_attributes") or {}).get("table")) or []
        for a in table:
            if a.get("id") in (177, 231, 233) and info.get("percentage_used") is None:
                v = (a.get("value"))
                info["percentage_used"] = 100 - v if isinstance(v, int) else None
            if a.get("id") == 241:
                lba = (a.get("raw") or {}).get("value")
                info["data_written_tb"] = round(lba * 512 / 1e12, 2) if isinstance(lba, int) else None
        raw.capture("hdparm-I.txt", f"hdparm -I {dev}", timeout=15)
    return info


def scan_features(raw):
    lspci = read_text(os.path.join(raw.dir, "lspci-nn.txt")) or out("lspci -nn")
    lsusb = read_text(os.path.join(raw.dir, "lsusb.txt")) or raw.capture("lsusb.txt", "lsusb")
    iw = raw.capture("iw-list.txt", "iw list 2>&1", timeout=15)
    raw.capture("rfkill.txt", "rfkill list 2>&1")
    raw.capture("bluetoothctl.txt", "timeout 5 bluetoothctl list 2>&1")
    raw.capture("sys-class-leds.txt", "ls -1 /sys/class/leds")
    raw.capture("udev-input.txt", "udevadm info --export-db 2>/dev/null | grep -E 'ID_INPUT_(TOUCHSCREEN|TOUCHPAD|KEYBOARD)=1|^N: '")

    wifi_card = None
    for line in lspci.splitlines():
        if re.search(r"Network controller|Wireless", line):
            wifi_card = line.split(": ", 1)[1].strip() if ": " in line else line.strip()
            break
    wl = (wifi_card or "").lower() + " " + iw.lower()
    if re.search(r"\bbe\d{3}\b|wi-fi 7", wl) or " eht" in iw.lower():
        wifi_std = "Wi-Fi 7 (802.11be)"
    elif re.search(r"ax2(10|11)|ax4\d\d|wi-fi 6e|6 ghz", wl):
        wifi_std = "Wi-Fi 6E (802.11ax)"
    elif re.search(r"\bax\d{3}\b|wi-fi 6|802\.11ax", wl) or " he " in iw.lower():
        wifi_std = "Wi-Fi 6 (802.11ax)"
    elif re.search(r"\bac\b|802\.11ac|vht", wl):
        wifi_std = "Wi-Fi 5 (802.11ac)"
    elif wifi_card:
        wifi_std = "Wi-Fi"
    else:
        wifi_std = None

    bt = "yes" if (os.path.isdir("/sys/class/bluetooth") and os.listdir("/sys/class/bluetooth")) \
        or "bluetooth" in lsusb.lower() else "no"
    webcam = "yes" if glob.glob("/dev/video*") or re.search(r"camera|webcam", lsusb, re.I) else "no"
    leds = out("ls /sys/class/leds")
    backlit = "yes" if "kbd_backlight" in leds else "no"
    udev_touch = out("udevadm info --export-db 2>/dev/null | grep -c ID_INPUT_TOUCHSCREEN=1")
    touch = "yes" if to_int(udev_touch, 0) else "no"
    return {
        "wifi_card": wifi_card, "wifi_standard": wifi_std, "bluetooth": bt,
        "webcam": webcam, "backlit_keyboard": backlit, "touchscreen": touch,
    }


def scan_license(raw):
    """OEM Windows key lives in the ACPI MSDM table. Only presence and the
    last 5 characters are recorded; the full key stays on the machine."""
    data = read_bytes("/sys/firmware/acpi/tables/MSDM")
    if not data:
        raw.save("msdm.txt", "MSDM table absent")
        return {"oem_key_present": False, "oem_key_suffix": None}
    key = data[56:85].decode("ascii", "replace") if len(data) >= 85 else ""
    ok = bool(re.fullmatch(r"[A-Z0-9]{5}(-[A-Z0-9]{5}){4}", key))
    raw.save("msdm.txt", f"MSDM table present, {len(data)} bytes, key format {'valid' if ok else 'unrecognised'}, ends ...{key[-5:] if ok else '?'}")
    return {"oem_key_present": ok, "oem_key_suffix": key[-5:] if ok else None}


def hardware_scan(raw, disk):
    banner("HARDWARE SCAN (unattended)")
    steps = [
        ("CPU", lambda: scan_cpu(raw)),
        ("Memory", lambda: scan_memory(raw)),
        ("GPU", lambda: scan_gpu(raw)),
        ("Display", lambda: scan_display(raw)),
        ("Battery", lambda: scan_battery(raw)),
        ("Storage", lambda: scan_storage(raw, disk)),
        ("Features", lambda: scan_features(raw)),
        ("License", lambda: scan_license(raw)),
    ]
    data = {}
    for i, (name, fn) in enumerate(steps, 1):
        print(f"  [{i}/{len(steps)}] {name:<9}", end="", flush=True)
        try:
            data[name.lower()] = fn()
            print(" ok")
        except Exception as e:  # noqa: BLE001
            data[name.lower()] = {"error": str(e)}
            print(f" ERROR {e}")
    raw.capture("dmesg.txt", "dmesg", timeout=15)
    raw.capture("uname.txt", "uname -a; cat /etc/os-release")
    return data


# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE 4 — SECURE ERASE
# ═══════════════════════════════════════════════════════════════════════════════

def read_sample(dev, offset, length=4 * 1024 * 1024):
    try:
        with open(dev, "rb", buffering=0) as f:
            f.seek(offset)
            return f.read(length)
    except OSError:
        return None


def is_blank(dev, size_bytes):
    """Sample start, middle and end of the device for zeros."""
    for off in (0, size_bytes // 2, max(0, size_bytes - 8 * 1024 * 1024)):
        chunk = read_sample(dev, off)
        if chunk is None:
            return None
        if any(chunk):
            return False
    return True


def secure_erase(disk, allow):
    dev, tran = disk["device"], disk["transport"]
    size_bytes = disk.get("size_bytes") or disk["size_gb"] * 10 ** 9
    result = {"performed": False, "method": None, "verified_blank": None, "duration_s": None, "error": None}
    banner("SECURE ERASE")
    if not allow:
        result["error"] = "erase disabled by flag"
        print("  Skipped (flag).")
        return result
    print(f"  Target: {dev}  {disk['size_gb']} GB  {disk.get('model') or ''}")
    print(f"  Erasing in {ERASE_ABORT_WINDOW_S}s. Press any key to ABORT.")
    if key_within(ERASE_ABORT_WINDOW_S):
        result["error"] = "aborted by operator"
        print("  ABORTED by operator. Disk untouched.")
        return result

    run(f"umount -l {dev}* 2>/dev/null; swapoff {dev}* 2>/dev/null", timeout=20)
    run(f"wipefs -a {dev} 2>/dev/null", timeout=20)   # kill signatures first so a failed erase still leaves no bootable OS
    attempts = []
    if tran == "nvme":
        attempts.append(("nvme_format_ses1", f"nvme format {dev} --ses=1 --force", 600))
        attempts.append(("blkdiscard", f"blkdiscard -f {dev}", 600))
        ctrl = re.sub(r"n\d+$", "", dev)
        attempts.append(("nvme_sanitize_block", f"nvme sanitize {ctrl} --sanact=2", 60))
    else:
        attempts.append(("blkdiscard", f"blkdiscard -f {dev}", 900))
        attempts.append(("ata_security_erase",
                         f"hdparm --user-master u --security-set-pass p {dev} && hdparm --user-master u --security-erase p {dev}", 3600))

    t0 = time.time()
    for name, cmd, tmo in attempts:
        print(f"  Trying {name}...", end="", flush=True)
        rc, so, se = run(cmd, timeout=tmo)
        if rc == 0:
            if name == "nvme_sanitize_block":
                # sanitize runs in the background; poll the log until it finishes
                for _ in range(240):
                    log = out(f"nvme sanitize-log {ctrl} 2>/dev/null")
                    m = re.search(r"\(SSTAT\)\s*:\s*0x?([0-9a-f]+)", log, re.I)
                    if m and (int(m.group(1), 16) & 0x7) in (1, 3):   # 1 = completed, 3 = failed
                        break
                    time.sleep(5)
            print(" done")
            result.update(performed=True, method=name)
            break
        print(f" failed (rc={rc}) {se.strip()[:120]}")
    result["duration_s"] = round(time.time() - t0, 1)
    if not result["performed"]:
        result["error"] = "all erase methods failed"
        print("  [!!] ALL ERASE METHODS FAILED. Do not ship this unit without a manual wipe.")
        return result
    run(f"blockdev --rereadpt {dev} 2>/dev/null; udevadm settle", timeout=30)
    blank = is_blank(dev, size_bytes)
    result["verified_blank"] = blank
    print(f"  Zero check: {'blank' if blank else 'NOT blank (drive may not return zeros after discard)' if blank is False else 'unreadable'}")
    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE 5 — REPORT
# ═══════════════════════════════════════════════════════════════════════════════

def build_warnings(rec):
    w = []
    b = rec.get("battery") or {}
    s = rec.get("storage") or {}
    t = rec.get("tests") or {}
    gr = rec.get("grades") or {}
    if (rec.get("audited_at") or "9999")[:10] < MIN_PLAUSIBLE_DATE:
        w.append(f"laptop clock reads {rec['audited_at'][:10]}: RTC not holding time (CMOS cell / flat battery). FIX BEFORE SHIPPING: Windows setup and updates fail on a wrong clock")
    if gr.get("screen_grade") == "C":
        w.append("screen grade C (cracked/scratched/bleed)")
    if gr.get("chassis_grade") == "C":
        w.append("body grade C (dents/cracks)")
    if b.get("health_pct") is not None and b["health_pct"] < 60:
        w.append(f"battery health {b['health_pct']}%")
    if s.get("smart_passed") is False:
        w.append("SMART health FAILED")
    if isinstance(s.get("percentage_used"), int) and s["percentage_used"] >= 50:
        w.append(f"SSD wear {s['percentage_used']}% used")
    if s.get("media_errors"):
        w.append(f"SSD media errors: {s['media_errors']}")
    if not (rec.get("license") or {}).get("oem_key_present"):
        w.append("no OEM Windows key in firmware (unit will not activate)")
    for name in ("display", "keyboard", "speaker"):
        if (t.get(name) or {}).get("result") == "fail":
            w.append(f"{name} test failed")
    e = rec.get("erase") or {}
    if not e.get("performed"):
        w.append(f"disk NOT erased ({e.get('error')})")
    if rec.get("preflight", {}).get("other_internal_disks"):
        w.append("more than one internal disk")
    return w


def print_summary(rec):
    i, c, m, s, b, d, g, f = (rec.get(k) or {} for k in
                              ("identity", "cpu", "memory", "storage", "battery", "display", "gpu", "features"))
    W = 60
    print()
    print("╔" + "═" * W + "╗")
    print("║" + f"  AUDIT v{VERSION}  {i.get('service_tag') or '?'}  {i.get('model') or ''}".ljust(W) + "║")
    print("╠" + "═" * W + "╣")
    rows = [
        ("CPU", f"{c.get('model') or '?'}  ({c.get('cores')}C/{c.get('threads')}T)"),
        ("RAM", f"{m.get('total_gb')} GB {m.get('type') or ''}  ({m.get('slots_used')}/{m.get('slots_total')} slots)"),
        ("SSD", f"{s.get('size_gb')} GB {(s.get('transport') or '').upper()}  {s.get('model') or ''}"),
        ("SSD health", f"SMART {'ok' if s.get('smart_passed') else s.get('smart_passed')}  wear {s.get('percentage_used')}%  {s.get('power_on_hours')} h  {s.get('data_written_tb')} TB written"),
        ("Battery", f"health {b.get('health_pct')}%  charge {b.get('charge_pct')}%  cycles {b.get('cycles')}"),
        ("Display", f"{d.get('diagonal_in')}\"  {d.get('resolution')}  {d.get('aspect') or ''}"),
        ("GPU", f"{g.get('discrete') or 'integrated only'}"),
        ("Wi-Fi", f"{f.get('wifi_standard')}  BT:{f.get('bluetooth')}  cam:{f.get('webcam')}  backlit:{f.get('backlit_keyboard')}  fp:{f.get('fingerprint_reader')}"),
        ("License", "OEM key present" if (rec.get('license') or {}).get('oem_key_present') else "NO OEM KEY"),
        ("Condition", f"screen {(rec.get('grades') or {}).get('screen_grade')}  body {(rec.get('grades') or {}).get('chassis_grade')}  "
                      f"{(rec.get('grades') or {}).get('color')}  charger {(rec.get('grades') or {}).get('charger')}"),
        ("Tests", "  ".join(f"{k}:{(v or {}).get('result')}" for k, v in (rec.get('tests') or {}).items())),
        ("Erase", f"{(rec.get('erase') or {}).get('method') or 'none'}  blank:{(rec.get('erase') or {}).get('verified_blank')}"),
    ]
    for k, v in rows:
        print("║" + f"  {k:<11}{v}"[:W].ljust(W) + "║")
    if rec.get("warnings"):
        print("╠" + "═" * W + "╣")
        for wmsg in rec["warnings"]:
            print("║" + f"  ⚠ {wmsg}"[:W].ljust(W) + "║")
    print("╚" + "═" * W + "╝")


def write_record(rec, audits_dir):
    tag = (rec.get("identity") or {}).get("service_tag") or f"UNKNOWN-{int(time.time())}"
    path = os.path.join(audits_dir, f"{tag}.json")
    with open(path, "w") as f:
        json.dump(rec, f, indent=2, sort_keys=True, default=str)
    line = (f"{rec['audited_at']}  {tag:<8} {((rec.get('identity') or {}).get('model') or '')[:18]:<18} "
            f"batt {(rec.get('battery') or {}).get('health_pct')}%  "
            f"ssd {(rec.get('storage') or {}).get('size_gb')}GB wear {(rec.get('storage') or {}).get('percentage_used')}%  "
            f"scr/body {(rec.get('grades') or {}).get('screen_grade') or '-'}/{(rec.get('grades') or {}).get('chassis_grade') or '-'}  "
            f"erase {(rec.get('erase') or {}).get('method') or 'NONE'}  "
            f"warn {len(rec.get('warnings') or [])}\n")
    with open(os.path.join(audits_dir, "summary.txt"), "a") as f:
        f.write(line)
    return path


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def parse_args():
    ap = argparse.ArgumentParser(description="Laptop line auditor")
    ap.add_argument("--dry-run", action="store_true", help="no erase, no poweroff")
    ap.add_argument("--no-erase", action="store_true")
    ap.add_argument("--no-poweroff", action="store_true")
    ap.add_argument("--skip-tests", action="store_true", help="skip attended display/keyboard/speaker tests")
    ap.add_argument("--outdir", help="directory for audits/ (default: the boot USB)")
    return ap.parse_args()


def main():
    args = parse_args()
    if os.geteuid() != 0:
        print("[!] Run as root.")
        sys.exit(1)
    # Stop the kernel console from blanking mid-audit (belt-and-suspenders;
    # the boot entry also passes consoleblank=0).
    for tty in ("/dev/tty0", "/dev/console"):
        try:
            with open(tty, "w") as t:
                t.write("\033[9;0]\033[14;0]")   # disable blank + monitor powerdown
            break
        except OSError:
            continue
    erase_allowed = not (args.dry_run or args.no_erase)
    poweroff = not (args.dry_run or args.no_poweroff)
    # Hard guard: the erase targets the largest internal disk. Only ever do
    # that from the SystemRescue live USB, never on a workstation.
    if erase_allowed and not os.path.isdir("/run/archiso"):
        print("  [!] Not running from SystemRescue live media. Erase and poweroff disabled.")
        erase_allowed, poweroff = False, False

    clear_screen()
    print(f"  ╔══════════════════════════════════════════════╗")
    print(f"  ║   LAPTOP AUDITOR v{VERSION}   {'DRY RUN' if args.dry_run else 'LIVE   '}             ║")
    print(f"  ╚══════════════════════════════════════════════╝")
    save_dir = args.outdir or mount_usb_rw()
    audits_dir = os.path.join(save_dir, "audits")
    os.makedirs(audits_dir, exist_ok=True)

    # Identity first so raw evidence has a home before anything else runs.
    scratch = RawStore(os.path.join(audits_dir, "_pending", "raw"))
    banner("PREFLIGHT")
    ident, disks, problems = preflight(scratch)
    tag = ident.get("service_tag") or f"UNKNOWN-{int(time.time())}"
    unit_dir = os.path.join(audits_dir, tag)
    raw_dir = os.path.join(unit_dir, "raw")
    os.makedirs(raw_dir, exist_ok=True)
    for name in os.listdir(scratch.dir):
        os.replace(os.path.join(scratch.dir, name), os.path.join(raw_dir, name))
    try:
        os.rmdir(scratch.dir)
        os.rmdir(os.path.dirname(scratch.dir))
    except OSError:
        pass
    raw = RawStore(raw_dir)
    raw.files = list(scratch.files)
    sys.stdout = Tee(os.path.join(raw_dir, "console.log"))

    rec = {
        "schema": 3, "auditor_version": VERSION, "audited_at": now_iso(),
        "identity": ident, "preflight": {"storage_mode": None, "other_internal_disks": [d["device"] for d in disks[1:]]},
        "tests": {}, "erase": {"performed": False, "method": None, "error": "not attempted"},
        "warnings": [],
    }
    rec["preflight"]["storage_mode"] = "rst_or_vmd" if any("RST/VMD" in p for p in problems) else "ahci"

    if problems:
        banner("STOP — FIX BEFORE AUDITING", char="!")
        for p in problems:
            print(f"  ✗ {p}")
        rec["status"] = "blocked"
        rec["blocked_reason"] = problems
        write_record(rec, audits_dir)
        run("sync")
        wait_key("\n  Press ENTER to power off...")
        if poweroff:
            run("poweroff")
        return

    disk = disks[0]
    try:
        # Attended tests up front. Fingerprint check is a quick lsusb, so it rides along.
        rec["tests"] = run_attended_tests(raw, args.skip_tests)
        fp = detect_fingerprint(raw)
        if fp == "unknown" and not args.skip_tests:
            ans = prompt_choice("Fingerprint reader? (sensor in the power button or next to the touchpad)",
                                {"Y": "Yes", "N": "No"})
            fp = "yes" if ans == "Y" else "no"
            rec["tests"]["fingerprint_confirm"] = "operator"
        grades = run_grading(audits_dir, args.skip_tests)
        grades["screen_grade"] = (rec["tests"].get("display") or {}).get("grade")
        grades["screen_note"] = (rec["tests"].get("display") or {}).get("note")
        rec["grades"] = grades
        print()
        print("  ────────────────────────────────────────────────────────")
        print("  Attended part is done. Scan, erase and power-off run on their own.")
        print("  You can move to the next machine.")
        print("  ────────────────────────────────────────────────────────")

        scan = hardware_scan(raw, disk)
        rec.update(scan)
        rec.setdefault("features", {})["fingerprint_reader"] = fp
        rec["erase"] = secure_erase(disk, erase_allowed)
        rec["warnings"] = build_warnings(rec)
        rec["status"] = "audited"
        rec["raw_files"] = sorted(set(raw.files + os.listdir(raw_dir)))
        print_summary(rec)
        path = write_record(rec, audits_dir)
        run("sync")
        print(f"  [✓] Saved {path}")
    except Exception:  # noqa: BLE001
        import traceback
        tb = traceback.format_exc()
        rec["status"] = "error"
        rec["error"] = tb
        print(f"\n  [!!] ERROR\n{tb}")
        try:
            write_record(rec, audits_dir)
            with open(os.path.join(audits_dir, f"{tag}_error.log"), "a") as f:
                f.write(f"\n{'=' * 60}\n{now_iso()}\n{tb}")
            run("sync")
        except OSError:
            pass
        if poweroff:
            print("  Powering off in 20s so the log can be read...")
            time.sleep(20)

    if poweroff:
        print("\n  Powering off in 5s.")
        time.sleep(5)
        run("sync; poweroff")
    else:
        # Dry run / bench: hold the summary on screen instead of letting the
        # login banner scroll it away.
        wait_key("\n  Dry run complete (no erase, no poweroff). Press ENTER for the shell...")


if __name__ == "__main__":
    main()
