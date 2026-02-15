#!/usr/bin/env python3
"""
audit.py — The "20-Laptop Factory Line" Auditor
=================================================
Boots on a SystemRescue Live USB, scans Dell laptop hardware,
collects an interactive quality grade, and exports results to
audit_master.csv on the physical USB stick.

Requires: Python 3.6+  (stdlib only — no pip installs)
Must run as root (for dmidecode, smartctl, blkdiscard, nwipe).
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
    "timestamp", "service_tag", "model", "cpu", "cores",
    "ram_gb", "ram_type", "storage_type", "storage_gb",
    "smart_status", "battery_pct", "gpu", "resolution",
    "resolution_class", "screen_grade", "chassis_grade",
    "charger", "recommendation",
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


def get_primary_disk() -> str:
    """
    Return the primary internal disk device (e.g. /dev/nvme0n1 or /dev/sda).
    Skips the boot USB and removable devices.
    """
    boot_usb = find_boot_usb_partition()
    # Strip partition number to get parent device
    boot_parent = re.sub(r"p?\d+$", "", boot_usb) if boot_usb else ""

    out = run("lsblk -dnpo NAME,TYPE,RM")
    for line in out.splitlines():
        cols = line.split()
        if len(cols) >= 3 and cols[1] == "disk" and cols[2] == "0":
            if cols[0] != boot_parent:
                return cols[0]
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

    # SMART health
    smart_out = run(f"smartctl -H {disk}")
    if "PASSED" in smart_out:
        smart = "PASSED"
    elif "FAILED" in smart_out:
        smart = "FAILED"
    else:
        smart = "N/A"

    return stor_type, capacity_gb, smart


def get_battery_health() -> str:
    """Return battery health percentage, or 'N/A'."""
    out = run("upower -i /org/freedesktop/UPower/devices/battery_BAT0")
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
    if full and design and design > 0:
        return str(round((full / design) * 100))
    return "N/A"


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
    print("  LAPTOP AUDITOR — Hardware Scan")
    print("=" * 60)
    print()

    data = {}

    print("  [1/8] Reading system identity...", end="", flush=True)
    data["service_tag"] = get_service_tag()
    data["model"] = get_model_name()
    print(f" {data['service_tag']} / {data['model']}")

    print("  [2/8] Scanning CPU...", end="", flush=True)
    data["cpu"], data["cores"] = get_cpu_info()
    print(f" {data['cpu']} ({data['cores']} threads)")

    print("  [3/8] Scanning RAM...", end="", flush=True)
    data["ram_gb"] = get_ram_total_gb()
    data["ram_type"] = get_ram_type()
    print(f" {data['ram_gb']} GB {data['ram_type']}")

    print("  [4/8] Scanning storage...", end="", flush=True)
    disk = get_primary_disk()
    data["storage_type"], data["storage_gb"], data["smart_status"] = get_storage_info(disk)
    data["_disk"] = disk  # internal use for wipe
    print(f" {data['storage_type']} {data['storage_gb']} GB — SMART: {data['smart_status']}")

    print("  [5/8] Checking battery...", end="", flush=True)
    data["battery_pct"] = get_battery_health()
    print(f" {data['battery_pct']}%")

    print("  [6/8] Detecting GPU...", end="", flush=True)
    data["gpu"] = get_discrete_gpu()
    print(f" {data['gpu']}")

    print("  [7/8] Detecting display...", end="", flush=True)
    data["resolution"], data["resolution_class"] = get_screen_resolution()
    print(f" {data['resolution']} ({data['resolution_class']})")

    print("  [8/8] Parsing CPU generation...", end="", flush=True)
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
    print("  DISPLAY TEST — Press any key to cycle through colors.\n")
    time.sleep(1)

    term_lines = os.get_terminal_size().lines
    for name, code in COLORS_ANSI.items():
        # Fill entire terminal with the color
        sys.stdout.write(code)
        for _ in range(term_lines):
            sys.stdout.write(" " * 200 + "\n")
        # Show label in contrasting text
        label_color = "\033[30m" if name == "White" else "\033[97m"
        sys.stdout.write(f"\033[{term_lines // 2};5H{label_color}  [ {name} — press any key ]  ")
        sys.stdout.flush()
        getch()
    # Reset
    sys.stdout.write(RESET_ANSI)
    clear_screen()


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


def run_interactive_grading() -> dict:
    """Run the interactive grading phase and return grade data."""
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

    return {
        "screen_grade": screen_grade,
        "chassis_grade": chassis_grade,
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
        batt = int(data.get("battery_pct", "0"))
    except ValueError:
        batt = 0

    # Decision tree (order matters)
    if smart == "FAILED" or screen == "C" or chassis == "C":
        return "PARTS/REPAIR"
    if gpu != "None":
        return "HIGH VALUE (Gaming/Creator)"
    if cpu_gen >= 8 and batt > 65:
        return "Standard Resale"
    if batt < 60:
        return "Bad Battery (Discount)"
    return "Standard Resale"


# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE 4 — CSV EXPORT & OPTIONAL WIPE
# ═══════════════════════════════════════════════════════════════════════════════

def export_to_csv(data: dict, save_dir: str):
    """Append one row to audit_master.csv in the given directory."""
    csv_path = os.path.join(save_dir, CSV_FILENAME)
    file_exists = os.path.isfile(csv_path)

    row = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "service_tag": data.get("service_tag", "N/A"),
        "model": data.get("model", "N/A"),
        "cpu": data.get("cpu", "N/A"),
        "cores": data.get("cores", 0),
        "ram_gb": data.get("ram_gb", 0),
        "ram_type": data.get("ram_type", "N/A"),
        "storage_type": data.get("storage_type", "N/A"),
        "storage_gb": data.get("storage_gb", 0),
        "smart_status": data.get("smart_status", "N/A"),
        "battery_pct": data.get("battery_pct", "N/A"),
        "gpu": data.get("gpu", "None"),
        "resolution": data.get("resolution", "N/A"),
        "resolution_class": data.get("resolution_class", "N/A"),
        "screen_grade": data.get("screen_grade", ""),
        "chassis_grade": data.get("chassis_grade", ""),
        "charger": data.get("charger", ""),
        "recommendation": data.get("recommendation", ""),
    }

    with open(csv_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

    print(f"\n  [✓] Results saved to {csv_path}")


def offer_wipe(data: dict):
    """
    Offer to wipe the internal drive.
    Double confirmation required: type Y, then type CONFIRM.
    """
    disk = data.get("_disk", "")
    stor_type = data.get("storage_type", "")
    if not disk:
        print("\n  [!] No internal disk detected — skipping wipe option.")
        return

    print()
    print("=" * 60)
    print("  ⚠  DRIVE WIPE")
    print("=" * 60)
    print(f"  Target: {disk} ({stor_type} — {data.get('storage_gb', '?')} GB)")
    print()

    answer1 = input("  WIPE DRIVE NOW?  (Warning: Irreversible)  [Y/N] > ").strip().upper()
    if answer1 != "Y":
        print("  Wipe cancelled.")
        return

    print()
    print("  ╔══════════════════════════════════════════╗")
    print("  ║  THIS WILL DESTROY ALL DATA ON THE DISK  ║")
    print("  ╚══════════════════════════════════════════╝")
    answer2 = input("  Type CONFIRM to proceed > ").strip().upper()
    if answer2 != "CONFIRM":
        print("  Wipe cancelled.")
        return

    print(f"\n  Wiping {disk}...")
    if "nvme" in disk:
        ret = os.system(f"blkdiscard -f {disk}")
    else:
        ret = os.system(f"nwipe --autonuke --method=zero {disk}")

    if ret == 0:
        print("  [✓] Drive wipe complete.")
    else:
        print("  [!] Wipe command returned a non-zero exit code. Check manually.")


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def print_summary(data: dict):
    """Print a human-readable summary of the audit."""
    print()
    print("╔" + "═" * 58 + "╗")
    print("║" + "  AUDIT SUMMARY".center(58) + "║")
    print("╠" + "═" * 58 + "╣")
    print(f"║  Service Tag:   {data['service_tag']:<40}║")
    print(f"║  Model:         {data['model']:<40}║")
    print(f"║  CPU:           {data['cpu'][:38]:<40}║")
    print(f"║  Cores/Threads: {str(data['cores']):<40}║")
    print(f"║  RAM:           {str(data['ram_gb']) + ' GB ' + data['ram_type']:<40}║")
    storage_str = f"{data['storage_type']} {data['storage_gb']} GB (SMART: {data['smart_status']})"
    print(f"║  Storage:       {storage_str:<40}║")
    print(f"║  Battery:       {data['battery_pct'] + '%':<40}║")
    print(f"║  GPU:           {data['gpu'][:38]:<40}║")
    res_str = f"{data['resolution']} ({data['resolution_class']})"
    print(f"║  Display:       {res_str:<40}║")
    print("╠" + "═" * 58 + "╣")
    print(f"║  Screen Grade:  {data['screen_grade']:<40}║")
    print(f"║  Chassis Grade: {data['chassis_grade']:<40}║")
    print(f"║  Charger:       {data['charger']:<40}║")
    print("╠" + "═" * 58 + "╣")
    rec = data["recommendation"]
    print(f"║  >> {rec:<54}║")
    print("╚" + "═" * 58 + "╝")
    print()


def main():
    # Must run as root
    if os.geteuid() != 0:
        print("[!] This script must be run as root (sudo).")
        sys.exit(1)

    clear_screen()
    print()
    print("  ╔═══════════════════════════════════════════════════╗")
    print("  ║       LAPTOP AUDITOR  v1.0                       ║")
    print("  ║       20-Laptop Factory Line Toolkit              ║")
    print("  ╚═══════════════════════════════════════════════════╝")
    print()

    # Phase 0 — Mount USB R/W
    save_dir = mount_usb_rw()

    # Phase 1 — Hardware Scan
    data = run_hardware_scan()

    # Phase 2 — Interactive Grading
    grades = run_interactive_grading()
    data.update(grades)

    # Phase 3 — Recommendation
    data["recommendation"] = compute_recommendation(data)

    # Summary
    print_summary(data)

    # Phase 4 — Export
    export_to_csv(data, save_dir)

    # Sync writes
    sync_and_unmount()

    # Optional Wipe
    offer_wipe(data)

    print("\n  Audit complete. You may now power off or audit the next laptop.\n")
    pause("  Press ENTER to exit...")


if __name__ == "__main__":
    main()
