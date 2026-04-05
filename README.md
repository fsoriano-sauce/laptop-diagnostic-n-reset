# Laptop Diagnostic & Reset Toolkit
### The "20-Laptop Factory Line"

Two USB tools to **audit, grade, and factory-reset** a batch of Dell laptops for resale.

| USB Stick | Purpose | OS |
|-----------|---------|-----|
| **Auditor** | Scan hardware, grade condition, export CSV | SystemRescue (Linux) |
| **Restorer** | Wipe disk + clean Windows 10 install → stops at OOBE | Windows 10 Pro |

---

## Quick Start: Batch Workflow

```
For each laptop:
  1. Boot from Auditor USB  →  auto-runs audit.py
  2. Review scan results  →  grade screen & chassis
  3. Results saved to audit_master.csv on the USB
  4. Swap to Restorer USB  →  boots & installs Windows automatically
     (disk is wiped and repartitioned by autounattend.xml)
  5. Laptop reboots to "Hi there" OOBE screen  →  take resale photo
  6. Move to next laptop
```

Your audit results accumulate in `audit_master.csv` on the Auditor USB.

---

## What's In This Repo

```
├── auditor/                   # → Copy contents to Auditor USB root
│   ├── audit.py               # Python auditor (stdlib only, runs on SystemRescue)
│   └── autorun                # SystemRescue autorun script (auto-launches audit.py)
├── restorer/                  # → Copy contents to Restorer USB root
│   └── autounattend.xml       # Windows 10 Pro unattended answer file
└── README.md                  # ← You are here
```

> **Each folder = one USB.** Copy everything inside `auditor/` to the Auditor USB root.
> Copy everything inside `restorer/` to the Restorer USB root.

---

## USB #1 — Building the Auditor

### Requirements
- **USB drive**: 2 GB+ (SystemRescue is ~1.2 GB)
- **Software**: [Rufus 4.x](https://rufus.ie) (Windows)

### Steps

1. **Download SystemRescue ISO**
   - Go to [https://www.system-rescue.org/Download/](https://www.system-rescue.org/Download/)
   - Download the latest `.iso` (e.g., `systemrescue-13.00-amd64.iso`)

2. **Flash the ISO to USB with Rufus**

   Open Rufus and set each field:

   | Rufus Field | Set To |
   |-------------|--------|
   | **Device** | Select your Auditor USB drive (e.g., `ESD-USB (F:) [32 GB]`) |
   | **Boot selection** | `Disk or ISO image` → click **SELECT** → pick the SystemRescue `.iso` |
   | **Partition scheme** | **MBR** |
   | **Target system** | **BIOS (or UEFI-CSM)** ← Rufus auto-sets this when you pick MBR |
   | **Volume label** | `RESCUE` (or leave default) |
   | **File system** | **FAT32** (default) |
   | **Cluster size** | Leave default |

   Click **START**:
   - When prompted, choose **Write in ISO image mode (Recommended)**
   - Click **OK** to confirm the drive will be wiped
   - Wait for completion (~2 min)

3. **Copy files from `auditor/` to the USB**
   - Open the USB drive in File Explorer (Rufus creates an `autorun/` folder automatically)
   - Copy `audit.py` → USB **root** (`X:\audit.py`)
   - Copy `autorun` → **inside** the existing `X:\autorun\` folder (`X:\autorun\autorun`)
   - ⚠️ Make sure `autorun` has no `.txt` extension — it must be named exactly `autorun`

4. **Test it**
   - Plug into a laptop → enter BIOS (F12 on Dell) → boot from USB
   - The audit script should launch automatically after boot

### SystemRescue autorun notes
> SystemRescue v12+ mounts the USB at `/run/archiso/bootmnt/`. The `autorun`
> script is configured for this path. If the script doesn't auto-launch,
> you can always run it manually:
> ```bash
> sudo python3 /run/archiso/bootmnt/audit.py
> ```

---

## USB #2 — Building the Restorer

### Requirements
- **USB drive**: 8 GB+ (Windows ISO is ~5–6 GB)
- **Software**: [Rufus 4.x](https://rufus.ie)
- **ISO**: Windows 10 (download from [Microsoft](https://www.microsoft.com/en-us/software-download/windows10ISO))

### Steps

1. **Download Windows 10 ISO**
   - Go to [Microsoft's download page](https://www.microsoft.com/en-us/software-download/windows10ISO)
   - Select **Windows 10** → language **English** → **64-bit Download**

2. **Flash the ISO to USB with Rufus**

   Open Rufus and set each field:

   | Rufus Field | Set To |
   |-------------|--------|
   | **Device** | Select your Restorer USB drive (e.g., `ASolid USB (D:) [64 GB]`) |
   | **Boot selection** | `Disk or ISO image` → click **SELECT** → pick the Windows 10 `.iso` |
   | **Partition scheme** | **GPT** |
   | **Target system** | **UEFI (non CSM)** ← Rufus auto-sets this when you pick GPT |
   | **Volume label** | `WIN10-RESTORE` (or leave default) |
   | **File system** | **NTFS** |
   | **Cluster size** | Leave default |

   Click **START**:
   - ⚠️ **When the "Windows User Experience" dialog appears**: uncheck **all** options and click **OK**. Our `autounattend.xml` handles everything — Rufus's customizations create a conflicting `unattend.xml`.
   - Click **OK** to confirm the drive will be wiped
   - Wait for completion (~5 min)

3. **Copy `autounattend.xml` to the USB root**
   - Open the USB drive in File Explorer
   - Copy `restorer/autounattend.xml` to the **root** of the USB
   - The file should be at `X:\autounattend.xml`
   - ⚠️ The filename must be exactly `autounattend.xml` (the Windows installer auto-detects it)

4. **(Optional) Inject drivers for Dell hardware**
   - If the Windows installer can't see NVMe drives, you may need to inject Dell WinPE drivers
   - Download [Dell Command | Deploy WinPE Driver Pack](https://www.dell.com/support/home/en-us/drivers/driversdetails?driverid=2V5TD)
   - Use DISM to inject into `boot.wim` (both indexes) and `install.wim`
   - See the driver injection walkthrough in the project history for step-by-step

5. **Test it**
   - Plug into a laptop → boot from USB (F12 on Dell)
   - Windows should install silently:
     - Disk gets wiped and partitioned automatically
     - OS installs without any prompts
     - BitLocker auto-encryption is prevented
     - Laptop reboots and lands on the **"Hi there, let's get started"** region selection screen
   - **Done** — the new owner takes it from here

### What the `autounattend.xml` does
> - **windowsPE pass**: Wipes Disk 0, creates GPT partitions (EFI + MSR + Primary), selects Windows 10 Pro, accepts EULA
> - **specialize pass**: Sets timezone to Eastern, prevents BitLocker auto-encryption, disables TPM auto-activation
> - **oobeSystem pass**: Skips EULA and machine OOBE, hides Wi-Fi setup (prevents forced Microsoft account), stops at user creation screen

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
