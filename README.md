# Laptop Diagnostic & Reset Toolkit
### The "20-Laptop Factory Line"

Two USB tools to **audit, grade, and factory-reset** a batch of Dell laptops for resale.

| USB Stick | Purpose | OS |
|-----------|---------|-----|
| **Auditor** | Scan hardware, grade condition, export CSV | SystemRescue (Linux) |
| **Restorer** | Clean Windows 10 install → stops at OOBE | Windows 10 Pro |

---

## Quick Start: Batch Workflow

```
For each laptop:
  1. Boot from Auditor USB  →  auto-runs audit.py
  2. Review scan results  →  grade screen & chassis
  3. (Optional) Wipe drive from the audit script
  4. Swap to Restorer USB  →  boots & installs Windows automatically
  5. Pull USB when install starts  →  laptop lands at "Hi there" screen
  6. Move to next laptop
```

Your audit results accumulate in `audit_master.csv` on the Auditor USB.

---

## What's In This Repo

```
├── auditor/
│   └── audit.py               # Python auditor (stdlib only, runs on SystemRescue)
├── restorer/
│   └── autounattend.xml       # Windows 10 Pro unattended answer file
└── README.md                  # ← You are here
```

---

## USB #1 — Building the Auditor

### Requirements
- **USB drive**: 2 GB+ (SystemRescue is ~800 MB)
- **Software**: [Rufus](https://rufus.ie) (Windows) or `dd` (Linux/Mac)

### Steps

1. **Download SystemRescue ISO**
   - Go to [https://www.system-rescue.org/Download/](https://www.system-rescue.org/Download/)
   - Download the latest `.iso` (e.g., `systemrescue-11.xx-amd64.iso`)

2. **Flash the ISO to USB with Rufus**
   - Open Rufus → select your USB drive
   - Click **SELECT** → pick the SystemRescue ISO
   - Partition scheme: **GPT**
   - Target system: **UEFI**
   - Click **START**, choose **Write in ISO image mode**
   - Wait for completion

3. **Copy `audit.py` to the USB**
   - Open the USB drive in File Explorer
   - Copy `auditor/audit.py` from this repo to the **root** of the USB
   - The file should be at `X:\audit.py` (where X is your USB drive letter)

4. **Set up autorun (SystemRescue auto-launch)**
   - Create a file on the USB at `X:\autorun` with this content:
     ```bash
     #!/bin/bash
     # Auto-launch the laptop auditor on boot
     sleep 3
     python3 /livemnt/boot/audit.py
     ```
   - Make sure the file has no `.txt` extension — it must be named exactly `autorun`

5. **Test it**
   - Plug into a laptop → enter BIOS (F12 on Dell) → boot from USB
   - The audit script should launch automatically after boot

### SystemRescue autorun notes
> SystemRescue looks for `/livemnt/boot/autorun` on boot. The USB filesystem
> is typically mounted at `/livemnt/boot/`. If the script doesn't auto-launch,
> you can always run it manually:
> ```bash
> sudo python3 /livemnt/boot/audit.py
> ```

---

## USB #2 — Building the Restorer

### Requirements
- **USB drive**: 8 GB+ (Windows ISO is ~5–6 GB)
- **Software**: [Rufus](https://rufus.ie)
- **ISO**: Windows 10 (download from [Microsoft](https://www.microsoft.com/en-us/software-download/windows10ISO))

### Steps

1. **Download Windows 10 ISO**
   - Go to [Microsoft's download page](https://www.microsoft.com/en-us/software-download/windows10ISO)
   - Select **Windows 10** → language **English** → **64-bit Download**

2. **Flash the ISO to USB with Rufus**
   - Open Rufus → select your USB drive
   - Click **SELECT** → pick the Windows 10 ISO
   - Partition scheme: **GPT**
   - Target system: **UEFI**
   - File system: **NTFS**
   - Click **START** and wait

3. **Copy `autounattend.xml` to the USB root**
   - Open the USB drive in File Explorer
   - Copy `restorer/autounattend.xml` to the **root** of the USB
   - The file should be at `X:\autounattend.xml`
   - ⚠️ The filename must be exactly `autounattend.xml` (the Windows installer auto-detects it)

4. **Test it**
   - Plug into a laptop → boot from USB (F12 on Dell)
   - Windows should install silently:
     - Disk gets wiped and partitioned automatically
     - OS installs without any prompts
     - Laptop reboots and lands on the **"Hi there, let's get started"** region selection screen
   - **Done** — the new owner takes it from here

---

## Dell BIOS Tips

| Action | Key |
|--------|-----|
| One-time boot menu | **F12** (tap repeatedly on power-on) |
| Enter BIOS setup | **F2** |
| Enable UEFI boot | BIOS → Boot → set **UEFI** mode |
| Secure Boot | May need to **disable** for SystemRescue |

> 💡 For batch processing: set the boot order to USB-first in BIOS so you
> don't have to press F12 on every laptop.

---

## audit_master.csv — Output Format

Each audited laptop adds one row with these columns:

| Column | Example |
|--------|---------|
| `timestamp` | 2026-02-15 10:30:00 |
| `service_tag` | ABC1234 |
| `model` | Latitude 5520 |
| `cpu` | Intel Core i7-1185G7 |
| `cores` | 8 |
| `ram_gb` | 16 |
| `ram_type` | DDR4 |
| `storage_type` | NVMe |
| `storage_gb` | 512 |
| `smart_status` | PASSED |
| `battery_pct` | 82 |
| `gpu` | None |
| `resolution` | 1920x1080 |
| `resolution_class` | Standard |
| `screen_grade` | A |
| `chassis_grade` | B |
| `charger` | Y |
| `recommendation` | Standard Resale |

### Recommendation Logic

| Condition | Recommendation |
|-----------|---------------|
| SMART failed OR Screen=C OR Chassis=C | **PARTS/REPAIR** |
| Discrete NVIDIA/AMD GPU detected | **HIGH VALUE (Gaming/Creator)** |
| CPU ≥ 8th Gen AND Battery > 65% | **Standard Resale** |
| Battery < 60% | **Bad Battery (Discount)** |
| Everything else | **Standard Resale** |

---

## License

MIT
