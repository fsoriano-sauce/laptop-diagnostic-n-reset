#!/usr/bin/env python3
"""
audit.py — The "20-Laptop Factory Line" Auditor
=================================================
Boots on a SystemRescue Live USB, scans laptop hardware,
collects an interactive quality grade, and exports results to
audit_master.csv on the physical USB stick.

v2.0 — Added eBay listing-optimized fields: screen size (inches),
       color, touchscreen, fingerprint reader, backlit keyboard,
       WiFi standard, Bluetooth, and webcam detection.

Requires: Python 3.6+  (stdlib only — no pip installs)
Must run as root (for dmidecode, smartctl).
"""

import csv
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ─── Constants ───────────────────────────────────────────────────────────────

CSV_FILENAME = "audit_master.csv"
USB_MOUNT_POINT = "/mnt/usb_data"
CSV_HEADERS = [
    "timestamp", "service_tag", "express_service_code",
    "model", "manufacture_year", "cpu", "cores",
    "ram_gb", "ram_type", "storage_type", "storage_gb",
    "smart_status", "battery_health_pct", "battery_charge_pct",
    "battery_cycles", "gpu", "resolution",
    "resolution_class", "screen_size_in",
    "touchscreen", "fingerprint_reader",
    "backlit_keyboard", "wifi_standard", "bluetooth", "webcam",
    "screen_grade", "chassis_grade", "color",
    "charger", "recommendation",
    "status", "sale_price", "sale_date", "notes",
]

COLORS_ANSI = {
    "White":  "\033[107m",   # bright white background
    "Red":    "\033[41m",
    "Green":  "\033[42m",
    "Blue":   "\033[44m",
    "Black":  "\033[40m",
}
RESET_ANSI = "\033[0m"


# ═══════════════════════════════════════════════════════════════════════════════
#  UTILITY HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def run(cmd: str, timeout: int = 15) -> str:
    """Run a shell command and return stripped stdout, or '' on failure."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return result.stdout.strip()
    except Exception:
        return ""


def read_file(path: str) -> str:
    """Read a text file and return its contents, or '' on failure."""
    try:
        return Path(path).read_text().strip()
    except Exception:
        return ""


def clear_screen():
    os.system("clear")


def pause(prompt: str = "Press ENTER to continue..."):
    input(prompt)


def getch() -> str:
    """Read a single keypress (no echo, no ENTER needed)."""
    try:
        import tty
        import termios
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        return ch
    except (ImportError, termios.error, OSError):
        # Fallback when no TTY (e.g., launched via autorun pipe)
        return input()


# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE 0 — MOUNT USB READ/WRITE  (Revision A)
# ═══════════════════════════════════════════════════════════════════════════════

def find_boot_usb_partition() -> str:
    """
    Identify the USB partition that SystemRescue booted from.
    Strategy: look through /proc/mounts for the live-media mount,
    then fall back to scanning for removable block devices.
    Returns a device path like '/dev/sdb1' or '' if not found.
    """
    # Strategy 1: SystemRescue mounts the USB as /run/archiso/bootmnt
    mounts = read_file("/proc/mounts")
    for line in mounts.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] in (
            "/run/archiso/bootmnt", "/run/initramfs/live",
            "/cdrom", "/live/image"
        ):
            return parts[0]

    # Strategy 2: find removable USB block devices via lsblk
    out = run("lsblk -nrpo NAME,RM,TYPE | grep '1 part'")
    for line in out.splitlines():
        cols = line.split()
        if cols:
            return cols[0]

    return ""


def mount_usb_rw() -> str:
    """
    Make the boot USB writable and return the path to save CSV data.
    SystemRescue v12 mounts the USB at /run/archiso/bootmnt (read-only).
    We remount it in-place rather than creating a new mount point.
    """
    # Strategy 1: SystemRescue v12 native mount point
    ARCHISO_MNT = "/run/archiso/bootmnt"
    if os.path.ismount(ARCHISO_MNT):
        ret = os.system(f"mount -o remount,rw {ARCHISO_MNT} 2>/dev/null")
        if ret == 0:
            print(f"[✓] Remounted {ARCHISO_MNT} as R/W")
            return ARCHISO_MNT
        print(f"[!] WARNING: Failed to remount {ARCHISO_MNT} as R/W.")

    # Strategy 2: detect partition and try a fresh mount
    partition = find_boot_usb_partition()
    if partition:
        os.makedirs(USB_MOUNT_POINT, exist_ok=True)
        ret = os.system(f"mount -o remount,rw {partition} {USB_MOUNT_POINT} 2>/dev/null")
        if ret != 0:
            ret = os.system(f"mount -o rw {partition} {USB_MOUNT_POINT} 2>/dev/null")
        if ret == 0:
            print(f"[✓] USB partition {partition} mounted R/W at {USB_MOUNT_POINT}")
            return USB_MOUNT_POINT
        print(f"[!] WARNING: Failed to mount {partition} as R/W.")

    # Fallback: /tmp (RAM-backed, lost on reboot)
    print("[!] WARNING: Could not make USB writable.")
    print("    CSV will be saved to /tmp (may be lost on reboot).")
    return "/tmp"


def sync_and_unmount():
    """Flush writes to disk."""
    os.system("sync")


# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE 1 — SILENT HARDWARE SCAN
# ═══════════════════════════════════════════════════════════════════════════════

def get_service_tag() -> str:
    return run("dmidecode -s system-serial-number") or "N/A"


def compute_express_service_code(service_tag: str) -> str:
    """Convert Dell service tag (base-36) to Express Service Code (base-10)."""
    if not service_tag or service_tag == "N/A":
        return "N/A"
    try:
        express = 0
        for c in service_tag.upper():
            if c.isdigit():
                val = int(c)
            elif c.isalpha():
                val = ord(c) - ord('A') + 10
            else:
                return "N/A"
            express = express * 36 + val
        return str(express)
    except Exception:
        return "N/A"


def get_manufacture_year() -> str:
    """Get manufacture/ship year from BIOS release date via dmidecode."""
    # Try the BIOS release date first
    bios_date = run("dmidecode -s bios-release-date")
    if bios_date:
        # Format is typically MM/DD/YYYY or YYYY-MM-DD
        import re
        m = re.search(r'(20\d{2})', bios_date)
        if m:
            return m.group(1)
    # Fallback: chassis manufacture date
    chassis_info = run("dmidecode -t chassis")
    if chassis_info:
        import re
        m = re.search(r'(20\d{2})', chassis_info)
        if m:
            return m.group(1)
    return "N/A"


def get_model_name() -> str:
    return run("dmidecode -s system-product-name") or "N/A"


def get_cpu_info() -> tuple:
    """Return (model_name, core_count)."""
    cpuinfo = read_file("/proc/cpuinfo")
    model = "N/A"
    cores = 0
    for line in cpuinfo.splitlines():
        if line.startswith("model name") and model == "N/A":
            model = line.split(":", 1)[1].strip()
        if line.startswith("processor"):
            cores += 1
    return model, cores


def get_ram_total_gb() -> int:
    """Return total RAM in GB (rounded)."""
    meminfo = read_file("/proc/meminfo")
    for line in meminfo.splitlines():
        if line.startswith("MemTotal"):
            kb = int(re.findall(r"\d+", line)[0])
            return round(kb / 1_048_576)  # kB → GB
    return 0


def get_ram_type() -> str:
    """Return DDR type via dmidecode."""
    out = run("dmidecode -t memory")
    for line in out.splitlines():
        if "Type:" in line and "DDR" in line:
            return line.split(":", 1)[1].strip()
    return "N/A"


def try_load_vmd_module():
    """
    Attempt to load the Intel VMD (Volume Management Device) kernel module.
    On Dell laptops with Intel RST enabled, the NVMe SSD is hidden behind
    a VMD/RAID controller. Loading 'vmd' exposes the NVMe as /dev/nvme*.
    Also tries 'nvme' module as a fallback.
    """
    for module in ["vmd", "nvme", "nvme_core"]:
        ret = os.system(f"modprobe {module} 2>/dev/null")
        if ret == 0:
            time.sleep(1)  # give kernel time to enumerate devices


def get_primary_disk() -> str:
    """
    Return the primary internal disk device (e.g. /dev/nvme0n1 or /dev/sda).
    Skips the boot USB and removable devices.
    Prefers the LARGEST non-removable disk to avoid picking up small
    Optane/eMMC cache modules instead of the main SSD.
    """
    boot_usb = find_boot_usb_partition()
    # Strip partition number to get parent device
    boot_parent = re.sub(r"p?\d+$", "", boot_usb) if boot_usb else ""

    # Collect all non-removable, non-USB disks with their sizes
    candidates = []
    out = run("lsblk -dnpo NAME,TYPE,RM,SIZE --bytes")
    for line in out.splitlines():
        cols = line.split()
        if len(cols) >= 4 and cols[1] == "disk" and cols[2] == "0":
            if cols[0] != boot_parent:
                try:
                    size = int(cols[3])
                except ValueError:
                    size = 0
                candidates.append((cols[0], size))

    # Pick the LARGEST disk (avoids Optane/eMMC cache modules)
    if candidates:
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0][0]

    # Fallback: just pick nvme0n1 or sda
    if os.path.exists("/dev/nvme0n1"):
        return "/dev/nvme0n1"
    if os.path.exists("/dev/sda"):
        return "/dev/sda"
    return ""


def get_storage_info(disk: str) -> tuple:
    """Return (type_str, capacity_gb, smart_status)."""
    if not disk:
        return "N/A", 0, "N/A"

    # Type
    stor_type = "NVMe" if "nvme" in disk else "SATA"

    # Capacity
    size_bytes = run(f"lsblk -bdn -o SIZE {disk}")
    try:
        capacity_gb = round(int(size_bytes) / 1_000_000_000)
    except ValueError:
        capacity_gb = 0

    # Sanity check: if drive is suspiciously small (<64GB), it's likely
    # an Intel Optane cache module or eMMC, not the primary SSD.
    # Try loading VMD module and re-scanning.
    if capacity_gb < 64:
        print(f"\n    [!] WARNING: Detected {capacity_gb}GB {stor_type} — too small for primary drive.")
        print(f"        Attempting Intel RST/VMD module load...")
        try_load_vmd_module()
        # Re-scan for the real drive
        new_disk = get_primary_disk()
        if new_disk and new_disk != disk:
            print(f"        Found new disk: {new_disk}")
            disk = new_disk
            stor_type = "NVMe" if "nvme" in disk else "SATA"
            size_bytes = run(f"lsblk -bdn -o SIZE {disk}")
            try:
                capacity_gb = round(int(size_bytes) / 1_000_000_000)
            except ValueError:
                capacity_gb = 0
            print(f"        Updated: {stor_type} {capacity_gb}GB")
        else:
            print(f"        No additional drives found after VMD load.")
            print(f"        This may be an Optane/eMMC module. Check BIOS for RST mode.")

    # SMART health
    smart_out = run(f"smartctl -H {disk}")
    if "PASSED" in smart_out:
        smart = "PASSED"
    elif "FAILED" in smart_out:
        smart = "FAILED"
    else:
        # Try smartctl with NVMe-specific flag
        smart_out = run(f"smartctl -H -d nvme {disk}")
        if "PASSED" in smart_out:
            smart = "PASSED"
        elif "FAILED" in smart_out:
            smart = "FAILED"
        else:
            smart = "N/A"

    return stor_type, capacity_gb, smart


def get_battery_info() -> dict:
    """
    Return battery health data:
      - health_pct: current max capacity vs design capacity (wear level)
      - charge_pct: current charge level
      - cycles: charge cycle count
    """
    result = {"health_pct": "N/A", "charge_pct": "N/A", "cycles": "N/A"}

    # Try upower first
    out = run("upower -i /org/freedesktop/UPower/devices/battery_BAT0")
    if not out:
        # Try BAT1 (some Dells use BAT1)
        out = run("upower -i /org/freedesktop/UPower/devices/battery_BAT1")

    full = None
    design = None
    for line in out.splitlines():
        line_s = line.strip()
        if "energy-full:" in line_s and "design" not in line_s:
            nums = re.findall(r"[\d.]+", line_s)
            if nums:
                full = float(nums[0])
        if "energy-full-design:" in line_s:
            nums = re.findall(r"[\d.]+", line_s)
            if nums:
                design = float(nums[0])
        if "percentage:" in line_s:
            nums = re.findall(r"[\d.]+", line_s)
            if nums:
                result["charge_pct"] = str(round(float(nums[0])))

    if full and design and design > 0:
        result["health_pct"] = str(round((full / design) * 100))

    # Cycle count — try /sys first (most reliable on Dell)
    for bat in ["BAT0", "BAT1"]:
        cycle_path = f"/sys/class/power_supply/{bat}/cycle_count"
        cycles = read_file(cycle_path).strip()
        if cycles and cycles != "0" and cycles != "":
            result["cycles"] = cycles
            break

    # Fallback: upower sometimes has cycle_count
    if result["cycles"] == "N/A":
        for line in out.splitlines():
            if "cycle" in line.lower() and "count" in line.lower():
                nums = re.findall(r"\d+", line)
                if nums:
                    result["cycles"] = nums[0]

    return result


def get_discrete_gpu() -> str:
    """Return GPU name if NVIDIA/AMD discrete GPU detected, else 'None'."""
    out = run("lspci")
    for line in out.splitlines():
        lower = line.lower()
        if "nvidia" in lower or ("amd" in lower and "radeon" in lower):
            # Extract the description after the colon
            parts = line.split(": ", 1)
            return parts[1].strip() if len(parts) > 1 else "Discrete GPU"
    return "None"


def get_screen_resolution() -> tuple:
    """Return (resolution_str, class_str)."""
    # Try xrandr first
    out = run("xrandr 2>/dev/null")
    max_w, max_h = 0, 0
    for line in out.splitlines():
        match = re.search(r"(\d{3,5})x(\d{3,5})", line)
        if match:
            w, h = int(match.group(1)), int(match.group(2))
            if w * h > max_w * max_h:
                max_w, max_h = w, h

    # Fallback: /sys/class/drm
    if max_w == 0:
        drm_cards = Path("/sys/class/drm")
        if drm_cards.exists():
            for modes_file in drm_cards.glob("*/modes"):
                content = read_file(str(modes_file))
                for line in content.splitlines():
                    match = re.search(r"(\d{3,5})x(\d{3,5})", line)
                    if match:
                        w, h = int(match.group(1)), int(match.group(2))
                        if w * h > max_w * max_h:
                            max_w, max_h = w, h

    if max_w == 0:
        return "N/A", "N/A"

    res_str = f"{max_w}x{max_h}"
    res_class = "4K/Retina Class" if max_w > 2500 else "Standard"
    return res_str, res_class


def get_screen_size_inches() -> str:
    """
    Calculate physical screen diagonal in inches from EDID data via xrandr.
    xrandr reports physical dimensions in mm for connected displays.
    Returns a string like '15.6' or 'N/A' if not detected.
    """
    out = run("xrandr 2>/dev/null")
    for line in out.splitlines():
        if " connected" not in line:
            continue
        # Match pattern like "309mm x 174mm"
        match = re.search(r'(\d+)mm\s+x\s+(\d+)mm', line)
        if match:
            w_mm = int(match.group(1))
            h_mm = int(match.group(2))
            if w_mm > 0 and h_mm > 0:
                diagonal_mm = (w_mm**2 + h_mm**2) ** 0.5
                diagonal_in = round(diagonal_mm / 25.4, 1)
                return str(diagonal_in)

    # Fallback: parse EDID binary from /sys/class/drm for physical size
    drm_path = Path("/sys/class/drm")
    if drm_path.exists():
        for edid_file in drm_path.glob("*/edid"):
            try:
                raw = edid_file.read_bytes()
                if len(raw) >= 68:
                    # EDID bytes 21-22 contain physical size in cm
                    w_cm = raw[21]
                    h_cm = raw[22]
                    if w_cm > 0 and h_cm > 0:
                        diagonal_cm = (w_cm**2 + h_cm**2) ** 0.5
                        diagonal_in = round(diagonal_cm / 2.54, 1)
                        return str(diagonal_in)
            except Exception:
                continue

    return "N/A"


def get_fingerprint_reader() -> str:
    """
    Detect fingerprint reader hardware.
    Many Dell laptops use SPI-connected fingerprint readers that do NOT
    appear in lsusb. Auto-detection is attempted first, but for reliability
    this falls back to an interactive prompt during grading.
    Returns 'Yes', 'No', or 'Check' (to be resolved during grading).
    """
    out = run("lsusb")

    # Keywords that are ONLY used for fingerprint devices
    exact_keywords = [
        "fingerprint", "biometric", "fprint", "finger print",
    ]

    # Vendor:Product ID prefixes known to be fingerprint readers
    fingerprint_usb_ids = [
        "27c6:",    # Goodix
        "04f3:0c",  # Elan fingerprint (0c** range, not touchpad range)
        "138a:",    # Validity Sensors (now Synaptics fingerprint)
        "06cb:00b", # Synaptics fingerprint (specific range)
        "06cb:00f", # Synaptics fingerprint
        "1c7a:",    # LighTuning (fingerprint)
        "2808:",    # AuthenTec / Upek
    ]

    for line in out.splitlines():
        lower = line.lower()
        for kw in exact_keywords:
            if kw in lower:
                return "Yes"
        for usb_id in fingerprint_usb_ids:
            if usb_id in lower:
                return "Yes"

    # Check udev for fingerprint class devices
    udev_out = run("udevadm info --export-db 2>/dev/null | grep -i fingerprint")
    if "fingerprint" in udev_out.lower():
        return "Yes"

    # Not auto-detected — many Dell models use SPI-based readers
    # that are invisible to lsusb. Mark for interactive confirmation.
    return "Check"


def get_touchscreen() -> str:
    """
    Detect touchscreen input device.
    IMPORTANT: Must distinguish 'touchscreen' from 'touchpad' — every laptop
    has a touchpad, but few have a touchscreen.
    Returns 'Yes' or 'No'.
    """
    # Method 1: xinput (if X is running)
    # Look specifically for 'touchscreen', exclude 'touchpad'
    out = run("xinput list 2>/dev/null")
    for line in out.lower().splitlines():
        if "touchscreen" in line and "touchpad" not in line:
            return "Yes"

    # Method 2: libinput — look for devices with 'touch' capability
    # that are NOT touchpads
    out = run("libinput list-devices 2>/dev/null")
    if out:
        # Split into device blocks and check each
        blocks = out.split("\n\n")
        for block in blocks:
            lower = block.lower()
            # A touchscreen will have 'touch' in capabilities but NOT 'touchpad'
            if "touchscreen" in lower:
                return "Yes"

    # Method 3: kernel input devices
    input_devs = read_file("/proc/bus/input/devices")
    blocks = input_devs.split("\n\n")
    for block in blocks:
        lower = block.lower()
        # Look for 'touchscreen' specifically, skip touchpad blocks
        if "touchscreen" in lower and "touchpad" not in lower:
            return "Yes"

    # Method 4: check udev for touchscreen tag (most reliable)
    udev_out = run("udevadm info --export-db 2>/dev/null | grep ID_INPUT_TOUCHSCREEN=1")
    if "TOUCHSCREEN=1" in udev_out:
        return "Yes"

    return "No"


def get_backlit_keyboard() -> str:
    """
    Detect backlit keyboard via /sys/class/leds.
    Dell and most laptops expose keyboard backlight LEDs here.
    Returns 'Yes' or 'No'.
    """
    leds_path = Path("/sys/class/leds")
    if leds_path.exists():
        for led_dir in leds_path.iterdir():
            if "kbd" in led_dir.name.lower() or "backlight" in led_dir.name.lower():
                # Check if it's a keyboard LED (not screen backlight)
                if "kbd" in led_dir.name.lower():
                    return "Yes"

    # Fallback: check for dell-specific backlight
    out = run("ls /sys/class/leds/ 2>/dev/null")
    if "kbd" in out.lower():
        return "Yes"

    return "No"


def get_wifi_standard() -> str:
    """
    Detect WiFi adapter and determine the wireless standard.
    Parses 'iw list' for supported bands/protocols or falls back to lspci.
    Returns a string like 'Wi-Fi 6 (802.11ax)' or 'Wi-Fi 5 (802.11ac)'.
    """
    # Method 1: iw list — check for supported standards
    out = run("iw list 2>/dev/null")
    if out:
        out_lower = out.lower()
        # Wi-Fi 7 (802.11be)
        if "eht" in out_lower or "11be" in out_lower:
            return "Wi-Fi 7 (802.11be)"
        # Wi-Fi 6E/6 (802.11ax)
        if "he" in out_lower and ("ht" in out_lower or "vht" in out_lower):
            # Check for 6GHz band → Wi-Fi 6E
            if "6 ghz" in out_lower or "6ghz" in out_lower:
                return "Wi-Fi 6E (802.11ax)"
            return "Wi-Fi 6 (802.11ax)"
        # Wi-Fi 5 (802.11ac)
        if "vht" in out_lower:
            return "Wi-Fi 5 (802.11ac)"
        # Wi-Fi 4 (802.11n)
        if "ht" in out_lower:
            return "Wi-Fi 4 (802.11n)"

    # Method 2: lspci — identify the card name for known models
    out = run("lspci")
    for line in out.splitlines():
        lower = line.lower()
        if "network" in lower or "wireless" in lower or "wifi" in lower or "wi-fi" in lower:
            if "ax" in lower or "wifi 6" in lower or "wi-fi 6" in lower:
                if "6e" in lower:
                    return "Wi-Fi 6E (802.11ax)"
                return "Wi-Fi 6 (802.11ax)"
            if "ac" in lower or "wifi 5" in lower or "wi-fi 5" in lower:
                return "Wi-Fi 5 (802.11ac)"
            if "wireless-n" in lower or "wifi 4" in lower:
                return "Wi-Fi 4 (802.11n)"
            # Generic — has WiFi but unknown standard
            return "Wi-Fi"

    return "N/A"


def get_bluetooth() -> str:
    """
    Detect Bluetooth adapter presence and version.
    Returns 'Yes' or 'No'. (Version detection is unreliable in live env.)
    """
    # Method 1: hciconfig
    out = run("hciconfig 2>/dev/null")
    if "hci" in out.lower() and ("up" in out.lower() or "down" in out.lower()):
        return "Yes"

    # Method 2: bluetoothctl
    out = run("bluetoothctl show 2>/dev/null")
    if "controller" in out.lower():
        return "Yes"

    # Method 3: check for Bluetooth in lsusb or lspci
    for cmd in ["lsusb", "lspci"]:
        out = run(cmd)
        if "bluetooth" in out.lower():
            return "Yes"

    # Method 4: /sys/class/bluetooth
    bt_path = Path("/sys/class/bluetooth")
    if bt_path.exists() and any(bt_path.iterdir()):
        return "Yes"

    return "No"


def get_webcam() -> str:
    """
    Detect built-in webcam.
    Checks /dev/video* devices and lsusb for camera hardware.
    Returns 'Yes' or 'No'.
    """
    # Method 1: check for video devices
    import glob
    video_devs = glob.glob("/dev/video*")
    if video_devs:
        return "Yes"

    # Method 2: lsusb for camera keywords
    out = run("lsusb")
    camera_keywords = ["camera", "webcam", "video", "imaging", "cam"]
    for line in out.splitlines():
        lower = line.lower()
        for kw in camera_keywords:
            if kw in lower:
                return "Yes"

    # Method 3: check /sys/class/video4linux
    v4l_path = Path("/sys/class/video4linux")
    if v4l_path.exists() and any(v4l_path.iterdir()):
        return "Yes"

    return "No"


def parse_cpu_generation(cpu_model: str) -> int:
    """
    Extract Intel CPU generation from model string.
    Examples:
        i7-8565U   → 8
        i7-1185G7  → 11
        i5-13500H  → 13
        i7-14700H  → 14
    For AMD Ryzen, return the series number (e.g., Ryzen 7 5800H → 5).
    Returns 0 if not detected.
    """
    # Intel: i[3579]-XXYY or i[3579]-XXXYY
    m = re.search(r"i[3579]-(\d{2,5})", cpu_model)
    if m:
        model_num = m.group(1)
        if len(model_num) == 4:
            return int(model_num[0])       # e.g., 8565 → 8
        elif len(model_num) == 5:
            return int(model_num[:2])      # e.g., 11850 → 11, 13500 → 13
    # AMD Ryzen
    m = re.search(r"Ryzen\s+\d\s+(\d)", cpu_model)
    if m:
        return int(m.group(1))
    return 0


def run_hardware_scan() -> dict:
    """Execute the full silent hardware scan and return a data dict."""
    print("=" * 60)
    print("  LAPTOP AUDITOR v2.0 — Hardware Scan")
    print("=" * 60)
    print()

    data = {}

    print("  [ 1/15] Reading system identity...", end="", flush=True)
    data["service_tag"] = get_service_tag()
    data["express_service_code"] = compute_express_service_code(data["service_tag"])
    data["model"] = get_model_name()
    data["manufacture_year"] = get_manufacture_year()
    print(f" {data['service_tag']} / {data['model']} ({data['manufacture_year']})")

    print("  [ 2/15] Scanning CPU...", end="", flush=True)
    data["cpu"], data["cores"] = get_cpu_info()
    print(f" {data['cpu']} ({data['cores']} threads)")

    print("  [ 3/15] Scanning RAM...", end="", flush=True)
    data["ram_gb"] = get_ram_total_gb()
    data["ram_type"] = get_ram_type()
    print(f" {data['ram_gb']} GB {data['ram_type']}")

    print("  [ 4/15] Scanning storage...", end="", flush=True)
    disk = get_primary_disk()
    data["storage_type"], data["storage_gb"], data["smart_status"] = get_storage_info(disk)
    data["_disk"] = disk  # internal use for wipe
    print(f" {data['storage_type']} {data['storage_gb']} GB — SMART: {data['smart_status']}")

    print("  [ 5/15] Checking battery...", end="", flush=True)
    batt = get_battery_info()
    data["battery_health_pct"] = batt["health_pct"]
    data["battery_charge_pct"] = batt["charge_pct"]
    data["battery_cycles"] = batt["cycles"]
    print(f" Health: {batt['health_pct']}% | Charge: {batt['charge_pct']}% | Cycles: {batt['cycles']}")

    print("  [ 6/15] Detecting GPU...", end="", flush=True)
    data["gpu"] = get_discrete_gpu()
    print(f" {data['gpu']}")

    print("  [ 7/15] Detecting display resolution...", end="", flush=True)
    data["resolution"], data["resolution_class"] = get_screen_resolution()
    print(f" {data['resolution']} ({data['resolution_class']})")

    print("  [ 8/15] Measuring screen size...", end="", flush=True)
    data["screen_size_in"] = get_screen_size_inches()
    print(f" {data['screen_size_in']}\"" if data["screen_size_in"] != "N/A" else " N/A")

    print("  [ 9/15] Checking for touchscreen...", end="", flush=True)
    data["touchscreen"] = get_touchscreen()
    print(f" {data['touchscreen']}")

    print("  [10/15] Checking fingerprint reader...", end="", flush=True)
    data["fingerprint_reader"] = get_fingerprint_reader()
    print(f" {data['fingerprint_reader']}")

    print("  [11/15] Checking backlit keyboard...", end="", flush=True)
    data["backlit_keyboard"] = get_backlit_keyboard()
    print(f" {data['backlit_keyboard']}")

    print("  [12/15] Detecting WiFi standard...", end="", flush=True)
    data["wifi_standard"] = get_wifi_standard()
    print(f" {data['wifi_standard']}")

    print("  [13/15] Checking Bluetooth...", end="", flush=True)
    data["bluetooth"] = get_bluetooth()
    print(f" {data['bluetooth']}")

    print("  [14/15] Checking webcam...", end="", flush=True)
    data["webcam"] = get_webcam()
    print(f" {data['webcam']}")

    print("  [15/15] Parsing CPU generation...", end="", flush=True)
    data["_cpu_gen"] = parse_cpu_generation(data["cpu"])
    print(f" Gen {data['_cpu_gen']}" if data["_cpu_gen"] else " Unknown")

    print()
    print("-" * 60)
    print("  Hardware scan complete.")
    print("-" * 60)
    print()
    return data


# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE 2 — INTERACTIVE GRADING
# ═══════════════════════════════════════════════════════════════════════════════

def display_test():
    """Cycle full-screen colors for dead-pixel / backlight bleed inspection."""
    print("  DISPLAY TEST — Press ENTER to cycle through colors.\n")
    input("  Press ENTER to start...")

    try:
        term_lines = os.get_terminal_size().lines
        term_cols = os.get_terminal_size().columns
    except OSError:
        term_lines = 50
        term_cols = 200

    try:
        for name, code in COLORS_ANSI.items():
            # Clear screen, set background color, fill uniformly
            sys.stdout.write("\033[2J\033[H")  # clear screen, cursor to top
            sys.stdout.write(code)
            # Fill screen with spaces in the background color
            line = " " * term_cols
            for _ in range(term_lines):
                sys.stdout.write(line)
            # Show label centered
            label_color = "\033[30m" if name == "White" else "\033[97m"
            row = term_lines // 2
            col = (term_cols - len(name) - 20) // 2
            sys.stdout.write(f"\033[{row};{col}H{label_color}  [ {name} — press ENTER ]  ")
            sys.stdout.flush()
            input()
        # Reset
        sys.stdout.write(RESET_ANSI)
        sys.stdout.write("\033[2J\033[H")  # clear screen
        sys.stdout.flush()
    except (OSError, EOFError):
        sys.stdout.write(RESET_ANSI)
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()
        print("\n  [!] Display test skipped (no interactive terminal)")


def prompt_choice(question: str, options: dict) -> str:
    """
    Prompt the user with a question and validate answer against options dict.
    options: {'A': 'Perfect', 'B': 'White Spots/Dead Pixel', ...}
    Returns the chosen key (uppercase).
    """
    while True:
        print(f"\n  {question}")
        for key, label in options.items():
            print(f"    [{key}] {label}")
        answer = input("\n  > ").strip().upper()
        if answer in options:
            return answer
        print(f"  Invalid. Please enter one of: {', '.join(options.keys())}")


def run_interactive_grading(hw_data: dict = None) -> dict:
    """Run the interactive grading phase and return grade data."""
    if hw_data is None:
        hw_data = {}
    print()
    print("=" * 60)
    print("  INTERACTIVE GRADING")
    print("=" * 60)

    display_test()

    screen_grade = prompt_choice(
        "Rate Screen Condition?",
        {"A": "Perfect", "B": "White Spots / Dead Pixel", "C": "Scratched"},
    )

    chassis_grade = prompt_choice(
        "Rate Chassis Condition?",
        {"A": "Mint", "B": "Minor Scuffs", "C": "Dents / Cracks"},
    )

    charger = prompt_choice(
        "Charger Included?",
        {"Y": "Yes", "N": "No"},
    )

    # Fingerprint: resolve if auto-detection was inconclusive (SPI-based readers)
    fingerprint = hw_data.get("fingerprint_reader", "Check")
    if fingerprint == "Check":
        fp_answer = prompt_choice(
            "Fingerprint Reader? (look for biometric sticker/sensor)",
            {"Y": "Yes", "N": "No"},
        )
        fingerprint = "Yes" if fp_answer == "Y" else "No"

    color = prompt_choice(
        "Laptop Color?",
        {"1": "Black", "2": "Silver", "3": "Gray",
         "4": "White", "5": "Blue", "6": "Other"},
    )
    # Map number keys to actual color names
    color_map = {"1": "Black", "2": "Silver", "3": "Gray",
                 "4": "White", "5": "Blue", "6": "Other"}
    color = color_map.get(color, color)

    return {
        "screen_grade": screen_grade,
        "chassis_grade": chassis_grade,
        "fingerprint_reader": fingerprint,
        "color": color,
        "charger": charger,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE 3 — VALUE LOGIC & RECOMMENDATION
# ═══════════════════════════════════════════════════════════════════════════════

def compute_recommendation(data: dict) -> str:
    """Apply the value-logic decision tree and return a recommendation string."""
    smart = data.get("smart_status", "N/A")
    screen = data.get("screen_grade", "")
    chassis = data.get("chassis_grade", "")
    gpu = data.get("gpu", "None")
    cpu_gen = data.get("_cpu_gen", 0)

    try:
        batt_health = int(data.get("battery_health_pct", "0"))
    except ValueError:
        batt_health = 0

    # Decision tree (order matters)
    if smart == "FAILED" or screen == "C" or chassis == "C":
        return "PARTS/REPAIR"
    # Battery check BEFORE GPU — a dead battery affects value regardless of GPU
    if batt_health < 60:
        if gpu != "None":
            return "HIGH VALUE — BAD BATTERY (Discount)"
        return "Bad Battery (Discount)"
    if gpu != "None":
        return "HIGH VALUE (Gaming/Creator)"
    if cpu_gen >= 8 and batt_health > 65:
        return "Standard Resale"
    return "Standard Resale"


# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE 4 — CSV EXPORT & OPTIONAL WIPE
# ═══════════════════════════════════════════════════════════════════════════════

def export_to_csv(data: dict, save_dir: str):
    """Append one row to audit_master.csv, with duplicate detection and header migration."""
    csv_path = os.path.join(save_dir, CSV_FILENAME)

    row = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "service_tag": data.get("service_tag", "N/A"),
        "express_service_code": data.get("express_service_code", "N/A"),
        "model": data.get("model", "N/A"),
        "manufacture_year": data.get("manufacture_year", "N/A"),
        "cpu": data.get("cpu", "N/A"),
        "cores": data.get("cores", 0),
        "ram_gb": data.get("ram_gb", 0),
        "ram_type": data.get("ram_type", "N/A"),
        "storage_type": data.get("storage_type", "N/A"),
        "storage_gb": data.get("storage_gb", 0),
        "smart_status": data.get("smart_status", "N/A"),
        "battery_health_pct": data.get("battery_health_pct", "N/A"),
        "battery_charge_pct": data.get("battery_charge_pct", "N/A"),
        "battery_cycles": data.get("battery_cycles", "N/A"),
        "gpu": data.get("gpu", "None"),
        "resolution": data.get("resolution", "N/A"),
        "resolution_class": data.get("resolution_class", "N/A"),
        "screen_size_in": data.get("screen_size_in", "N/A"),
        "touchscreen": data.get("touchscreen", "No"),
        "fingerprint_reader": data.get("fingerprint_reader", "No"),
        "backlit_keyboard": data.get("backlit_keyboard", "No"),
        "wifi_standard": data.get("wifi_standard", "N/A"),
        "bluetooth": data.get("bluetooth", "No"),
        "webcam": data.get("webcam", "No"),
        "screen_grade": data.get("screen_grade", ""),
        "chassis_grade": data.get("chassis_grade", ""),
        "color": data.get("color", ""),
        "charger": data.get("charger", ""),
        "recommendation": data.get("recommendation", ""),
        "status": "audited",
        "sale_price": "",
        "sale_date": "",
        "notes": "",
    }

    # Read existing rows (if any) and migrate to current headers
    existing_rows = []
    if os.path.isfile(csv_path):
        try:
            with open(csv_path, "r", newline="") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    # Migrate old 'battery_pct' field to new names
                    if "battery_pct" in r and "battery_health_pct" not in r:
                        r["battery_health_pct"] = r.pop("battery_pct", "N/A")
                        r.setdefault("battery_charge_pct", "N/A")
                        r.setdefault("battery_cycles", "N/A")
                    # Migrate v1 → v2: add defaults for new eBay fields
                    r.setdefault("screen_size_in", "N/A")
                    r.setdefault("touchscreen", "N/A")
                    r.setdefault("fingerprint_reader", "N/A")
                    r.setdefault("backlit_keyboard", "N/A")
                    r.setdefault("wifi_standard", "N/A")
                    r.setdefault("bluetooth", "N/A")
                    r.setdefault("webcam", "N/A")
                    r.setdefault("color", "")
                    # Migrate v2 → v3: add express code and manufacture year
                    r.setdefault("express_service_code", "N/A")
                    r.setdefault("manufacture_year", "N/A")
                    existing_rows.append(r)
        except Exception:
            pass  # corrupted CSV — start fresh

    # Check for duplicate service tag
    service_tag = row["service_tag"]
    duplicate_idx = None
    for i, existing in enumerate(existing_rows):
        if existing.get("service_tag") == service_tag:
            duplicate_idx = i
            break

    if duplicate_idx is not None:
        prev = existing_rows[duplicate_idx]
        prev_time = prev.get("timestamp", "unknown time")
        print(f"\n  ⚠  DUPLICATE: {service_tag} was already audited on {prev_time}")
        answer = input("  Update existing record? [Y/N] > ").strip().upper()
        if answer == "Y":
            # Preserve manually-entered inventory fields from old record
            row["status"] = prev.get("status", "audited")
            row["sale_price"] = prev.get("sale_price", "")
            row["sale_date"] = prev.get("sale_date", "")
            row["notes"] = prev.get("notes", "")
            existing_rows[duplicate_idx] = row
            print("  [✓] Record updated (inventory fields preserved).")
        else:
            print("  [–] Skipped — keeping original record.")
            return
    else:
        existing_rows.append(row)

    # Write all rows with current headers
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS, extrasaction="ignore")
        writer.writeheader()
        for r in existing_rows:
            writer.writerow(r)

    count = len(existing_rows)
    print(f"\n  [✓] Results saved to {csv_path} ({count} laptop{'s' if count != 1 else ''} total)")





# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def print_summary(data: dict):
    """Print a human-readable summary of the audit."""
    W = 58  # inner width
    print()
    print("╔" + "═" * W + "╗")
    print("║" + "  AUDIT SUMMARY v2.0".center(W) + "║")
    print("╠" + "═" * W + "╣")
    print(f"║  Service Tag:   {data['service_tag']:<40}║")
    print(f"║  Express Code:  {data.get('express_service_code', 'N/A'):<40}║")
    print(f"║  Model:         {data['model']:<40}║")
    print(f"║  Mfg Year:      {data.get('manufacture_year', 'N/A'):<40}║")
    print(f"║  CPU:           {data['cpu'][:38]:<40}║")
    print(f"║  Cores/Threads: {str(data['cores']):<40}║")
    print(f"║  RAM:           {str(data['ram_gb']) + ' GB ' + data['ram_type']:<40}║")
    storage_str = f"{data['storage_type']} {data['storage_gb']} GB (SMART: {data['smart_status']})"
    print(f"║  Storage:       {storage_str:<40}║")
    batt_str = f"Health: {data.get('battery_health_pct', 'N/A')}% | Cycles: {data.get('battery_cycles', 'N/A')}"
    print(f"║  Battery:       {batt_str:<40}║")
    print(f"║  GPU:           {data['gpu'][:38]:<40}║")
    screen_in = data.get('screen_size_in', 'N/A')
    res_str = f"{screen_in}\" {data['resolution']} ({data['resolution_class']})"
    print(f"║  Display:       {res_str:<40}║")
    print("╠" + "═" * W + "╣")
    print("║" + "  FEATURES".center(W) + "║")
    print("╠" + "═" * W + "╣")
    print(f"║  Touchscreen:   {data.get('touchscreen', 'N/A'):<40}║")
    print(f"║  Fingerprint:   {data.get('fingerprint_reader', 'N/A'):<40}║")
    print(f"║  Backlit KB:    {data.get('backlit_keyboard', 'N/A'):<40}║")
    print(f"║  WiFi:          {data.get('wifi_standard', 'N/A'):<40}║")
    print(f"║  Bluetooth:     {data.get('bluetooth', 'N/A'):<40}║")
    print(f"║  Webcam:        {data.get('webcam', 'N/A'):<40}║")
    print("╠" + "═" * W + "╣")
    print("║" + "  GRADING".center(W) + "║")
    print("╠" + "═" * W + "╣")
    print(f"║  Screen Grade:  {data['screen_grade']:<40}║")
    print(f"║  Chassis Grade: {data['chassis_grade']:<40}║")
    print(f"║  Color:         {data.get('color', ''):<40}║")
    print(f"║  Charger:       {data['charger']:<40}║")
    print("╠" + "═" * W + "╣")
    rec = data["recommendation"]
    print(f"║  >> {rec:<54}║")
    print("╚" + "═" * W + "╝")
    print()


def main():
    # Must run as root
    if os.geteuid() != 0:
        print("[!] This script must be run as root (sudo).")
        sys.exit(1)

    clear_screen()
    print()
    print("  ╔═══════════════════════════════════════════════════╗")
    print("  ║       LAPTOP AUDITOR  v2.0                       ║")
    print("  ║       20-Laptop Factory Line Toolkit              ║")
    print("  ║       + eBay Listing Optimization                 ║")
    print("  ╚═══════════════════════════════════════════════════╝")
    print()

    # Phase 0 — Mount USB R/W
    save_dir = mount_usb_rw()

    try:
        # Phase 1 — Hardware Scan
        data = run_hardware_scan()

        # Phase 2 — Interactive Grading
        grades = run_interactive_grading(data)
        data.update(grades)

        # Phase 3 — Recommendation
        data["recommendation"] = compute_recommendation(data)

        # Summary
        print_summary(data)

        # Phase 4 — Export
        export_to_csv(data, save_dir)

        # Sync writes
        sync_and_unmount()

        print("\n  ✓ Audit complete. Shutting down in 5 seconds...")
        print("    (Swap to Restorer USB for Windows install)\n")
        time.sleep(5)
        os.system("poweroff")

    except Exception as e:
        # Save error log to USB for later review
        import traceback
        error_log = traceback.format_exc()
        print(f"\n  [!!] ERROR: {e}")
        print(f"  Saving error log to {save_dir}/audit_error.log\n")
        try:
            log_path = os.path.join(save_dir, "audit_error.log")
            with open(log_path, "a") as f:
                f.write(f"\n{'='*60}\n")
                f.write(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(error_log)
            sync_and_unmount()
            print(f"  Error log saved. Retrieve USB to review.")
        except Exception:
            print(f"  Could not save log. Error was:\n{error_log}")
        print("\n  Shutting down in 10 seconds...")
        time.sleep(10)
        os.system("poweroff")


if __name__ == "__main__":
    main()
