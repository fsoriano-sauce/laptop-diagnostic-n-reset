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
  1. BIOS prep (one-time): F2 → disable Secure Boot
  2. Boot from Auditor USB (F12 → select SanDisk/RESCUE)
     → auto-runs audit.py, scans hardware, prompts for grades
     → auto-shuts down when complete
  3. Swap to Restorer USB → boot (F12 → select ESD-ISO)
     → wipes disk, installs Windows 10 automatically
  4. Laptop reboots to "Let's start with region" OOBE screen
     → take resale photo, then hold power to shut down
  5. Move to next laptop
```

Your audit results accumulate in `audit_master.csv` on the Auditor USB.

---

## What's In This Repo

```
├── auditor/                   # → Copy contents to Auditor USB root
│   ├── audit.py               # Python auditor v2.0 (stdlib only, runs on SystemRescue)
│   └── autorun                # SystemRescue autorun script (auto-launches audit.py)
├── restorer/                  # → Copy contents to Restorer USB root
│   └── autounattend.xml       # Windows 10 Pro unattended answer file
├── .gitattributes             # Forces LF line endings for Linux scripts
└── README.md                  # ← You are here
```

> **Each folder = one USB.** Copy everything inside `auditor/` to the Auditor USB root.
> Copy everything inside `restorer/` to the Restorer USB root.

---

## USB #1 — Building the Auditor

### Requirements
- **USB drive**: 4 GB+ (SystemRescue is ~1.2 GB)
- **Software**: [Rufus 4.x](https://rufus.ie) (Windows)
- **ISO**: [SystemRescue](https://www.system-rescue.org/Download/) (latest, e.g., `systemrescue-13.00-amd64.iso`)

### Steps

1. **Download SystemRescue ISO**
   - Go to [https://www.system-rescue.org/Download/](https://www.system-rescue.org/Download/)
   - Download the latest `.iso` (e.g., `systemrescue-13.00-amd64.iso`)

2. **Flash the ISO to USB with Rufus**

   | Rufus Field | Set To |
   |-------------|--------|
   | **Device** | Select your Auditor USB drive |
   | **Boot selection** | `Disk or ISO image` → click **SELECT** → pick the SystemRescue `.iso` |
   | **Partition scheme** | **MBR** |
   | **Target system** | **BIOS (or UEFI-CSM)** ← auto-set by Rufus |
   | **Volume label** | `RESCUE` (or leave default) |
   | **File system** | **FAT32** (default) |
   | **Cluster size** | Leave default |
   | **Persistence** | 0 (no persistence) |

   Click **START** → **Write in ISO image mode** → **OK**.

3. **Copy repo files to the USB**
   - Copy `auditor/audit.py` → USB **root** (`X:\audit.py`)
   - Copy `auditor/autorun` → **inside** the existing `X:\autorun\` folder (`X:\autorun\autorun`)
   - ⚠️ `autorun` must have **no file extension** — just `autorun`, not `autorun.txt`
   - ⚠️ `autorun` must have **LF line endings** (not CRLF). The repo's `.gitattributes` handles this, but if copying manually, verify with a text editor.

4. **Test it**
   - Plug into a laptop → **F2** to disable Secure Boot → **F12** → boot from USB
   - SystemRescue boots → audit.py auto-launches → scans hardware → prompts for grades
   - After completion, laptop auto-shuts down and CSV is saved to USB

### SystemRescue notes
> - SystemRescue v13+ looks for autorun scripts in `/run/archiso/bootmnt/autorun/`
> - **Secure Boot must be disabled** in BIOS for SystemRescue to boot on Dell hardware
> - If autorun fails, run manually: `python3 /run/archiso/bootmnt/audit.py`
> - Errors are saved to `audit_error.log` on the USB root

---

## USB #2 — Building the Restorer

### Requirements
- **USB drive**: 16 GB+ (Windows image with drivers is ~5 GB)
- **Software**: [Rufus 4.x](https://rufus.ie)
- **ISO**: Windows 10 via [Media Creation Tool](https://www.microsoft.com/en-us/software-download/windows10ISO)

### Option A: Clone from an Existing Restorer (Recommended)

If you already have a working Restorer USB, this is the **fastest and most reliable** method.
The working USB has Intel drivers injected into `boot.wim` and `install.wim` — a stock ISO will NOT work on Dell NVMe laptops.

1. **Flash the new USB with Rufus** using the stock Windows 10 ISO:

   | Rufus Field | Set To |
   |-------------|--------|
   | **Device** | Select the new USB drive |
   | **Boot selection** | `Disk or ISO image` → click **SELECT** → pick `Windows.iso` |
   | **Partition scheme** | **GPT** |
   | **Target system** | **UEFI (non CSM)** |
   | **Volume label** | **ESD-ISO** |
   | **File system** | **NTFS** |
   | **Cluster size** | Leave default (4096 bytes) |

   Click **START** → **Uncheck ALL** on "Windows User Experience" → **OK**.

   > ⚠️ Rufus may show "Revoked UEFI bootloader detected" — click **OK**, this is safe for official Microsoft ISOs.

2. **Copy the driver-injected images from the working USB** (this is the critical step):

   ```powershell
   # Plug in both USBs. Find drive letters:
   Get-Volume | Where-Object { $_.FileSystemLabel -match 'ESD' }

   # Replace X: with the WORKING Restorer, Y: with the NEW one:
   Copy-Item "X:\sources\boot.wim" "Y:\sources\boot.wim" -Force
   Rename-Item "Y:\sources\install.esd" "install.esd.bak" -Force
   Copy-Item "X:\sources\install.wim" "Y:\sources\install.wim" -Force
   ```

   > The `install.wim` copy takes ~5 minutes per USB (4.6 GB file).

3. **Copy `autounattend.xml` to the new USB root**:
   ```powershell
   Copy-Item "restorer\autounattend.xml" "Y:\autounattend.xml" -Force
   ```

4. **Verify** — the new USB should have:
   - `Y:\autounattend.xml` (8,747 bytes)
   - `Y:\sources\boot.wim` (~468 MB — with Intel drivers)
   - `Y:\sources\install.wim` (~4,599 MB — with Intel drivers)
   - `Y:\sources\install.esd.bak` (original, unused backup)

### Option B: Build from Scratch (First Time Only)

Use this only if you have no working Restorer USB to clone from.

1. **Download Windows 10 ISO**
   - Download [Media Creation Tool](https://www.microsoft.com/en-us/software-download/windows10ISO) (~18 MB .exe)
   - Run it → **Create installation media** → English, Windows 10, 64-bit → **ISO file**
   - Save to Downloads (~5.8 GB download, 10 min)

2. **Flash with Rufus** using the same settings as Option A above.

3. **Inject Intel drivers** into `boot.wim` and `install.wim` using DISM:
   - Download [Intel RST/VMD drivers](https://www.intel.com/content/www/us/en/download/720755/intel-rapid-storage-technology-driver-installation-software-with-intel-optane-memory.html) or [Dell WinPE Driver Pack](https://www.dell.com/support/home/en-us/drivers/driversdetails?driverid=2V5TD)
   - Inject into `boot.wim` (both indexes) and `install.wim` (Index 1) via DISM

   > ⚠️ **Without driver injection, the Windows installer will NOT see the NVMe drive** on Dell laptops. You'll get error `0x80300025: disk 0 does not exist`. This is because Dell ships laptops with Intel RST/VMD mode enabled.

4. **Copy `autounattend.xml`** to the USB root.

### What the `autounattend.xml` does
> - **windowsPE pass**: Wipes Disk 0, creates GPT partitions (EFI + MSR + Primary), selects Windows 10 Pro using Microsoft's generic setup key, accepts EULA
> - **specialize pass**: Sets timezone to Eastern, prevents BitLocker auto-encryption, disables TPM auto-activation
> - **oobeSystem pass**: Skips EULA, hides Wi-Fi setup (prevents forced Microsoft account), stops at **"Let's start with region"** screen

### Windows Licensing
> The `autounattend.xml` uses Microsoft's public generic Windows 10 Pro setup key (`VK7JG-NPHTM-C97JM-9MPGT-3V66T`). This is NOT a piracy key — it only tells the installer which edition to install. The actual activation happens automatically via the **OEM product key embedded in the laptop's BIOS** (MSDM table). If the laptop originally had Windows 10 Pro, it will auto-activate on first internet connection.

---

## Dell BIOS Prerequisites

Before booting **either** USB, check these BIOS settings (F2 at power-on):

| Setting | Required For | Location |
|---------|-------------|----------|
| **Secure Boot** → Disabled | Auditor (SystemRescue) | Security → Secure Boot |
| **Boot Mode** → UEFI | Both USBs | Boot Configuration → Boot Mode |

> 💡 **Tip**: For batch processing, set USB-first in the boot order so you don't have to press F12 on every laptop.

---

## audit_master.csv — Output Format (v2.0)

Each audited laptop adds one row. Duplicate service tags are detected and prompt for update.

### Hardware Fields (auto-detected)
| Column | Example |
|--------|---------|
| `timestamp` | 2026-04-05 12:33:04 |
| `service_tag` | 9P81KL3 |
| `model` | Vostro 15 7510 |
| `cpu` | 11th Gen Intel i7-11800H |
| `cores` | 16 |
| `ram_gb` | 15 |
| `ram_type` | DDR4 |
| `storage_type` | NVMe |
| `storage_gb` | 512 |
| `smart_status` | PASSED |
| `battery_health_pct` | 100 |
| `battery_charge_pct` | 82 |
| `battery_cycles` | N/A |
| `gpu` | NVIDIA RTX 3050 |
| `resolution` | 1920x1080 |
| `resolution_class` | Standard |
| `screen_size_in` | 15.6 |
| `touchscreen` | No |
| `fingerprint_reader` | Yes |
| `backlit_keyboard` | Yes |
| `wifi_standard` | Wi-Fi 6 (802.11ax) |
| `bluetooth` | Yes |
| `webcam` | Yes |

### Grading Fields (interactive prompts)
| Column | Example |
|--------|---------|
| `screen_grade` | A |
| `chassis_grade` | B |
| `color` | Silver |
| `charger` | Y |

### Output Fields
| Column | Example |
|--------|---------|
| `recommendation` | HIGH VALUE (Gaming/Creator) |
| `status` | audited |
| `sale_price` | *(fill manually)* |
| `sale_date` | *(fill manually)* |
| `notes` | *(fill manually)* |

### Recommendation Logic

| Condition | Recommendation |
|-----------|---------------|
| SMART failed OR Screen=C OR Chassis=C | **PARTS/REPAIR** |
| Discrete NVIDIA/AMD GPU detected | **HIGH VALUE (Gaming/Creator)** |
| CPU ≥ 8th Gen AND Battery Health > 65% | **Standard Resale** |
| Battery Health < 60% | **Bad Battery (Discount)** |
| Everything else | **Standard Resale** |

### Inventory Tracking
The `status`, `sale_price`, `sale_date`, and `notes` columns are for manual tracking in Excel/Sheets:
- `audited` → `listed` → `sold`

---

## License

MIT
