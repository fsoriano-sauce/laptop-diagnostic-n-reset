# Laptop Diagnostic & Reset Toolkit
### The "20-Laptop Factory Line" — v3

Two USB sticks turn a used Dell laptop into a tested, wiped, retail-style
Windows 11 machine with a JSON evidence file for the eBay listing.

| USB | What it does | Base |
|---|---|---|
| **Auditor** | Attended tests (screen, keyboard, speaker), hardware scan with raw evidence, secure erase, power off | SystemRescue (Linux) |
| **Restorer** | Wipes disk, clean Windows 11 install, stages Dell drivers, stops at the retail out-of-box screen | Windows 11 stock ISO |

Design rules, in order of importance:

1. **The BIOS is set to AHCI/NVMe before anything runs.** Intel RST/VMD mode hid the SSD from Linux and from stock Windows media; every driver-injection and unlock hack in earlier versions existed to work around it. The auditor refuses to run in RST/VMD mode.
2. **Measure, never assume.** No lookup tables. If a value cannot be read it is `null`, and every raw command output is saved next to the JSON so it can be re-derived later without rebooting the laptop.
3. **Facts, state and derived values live apart.** `audits/<TAG>.json` is what the machine reported. `inventory.csv` is what you decide (grades, colour, charger, price, status). Recommendations and prices are computed by scripts, never stored in an audit.
4. **The buyer gets a retail machine.** Stock OOBE (region, Wi-Fi, Microsoft account, Windows Hello, privacy), Secure Boot on, edition matched to the OEM key in firmware, drivers present at first boot.

---

## Per-unit flow

```
1. Power on, F2 (BIOS)                       ~1 min, attended
     Secure Boot ........ Off        (SystemRescue is not Secure-Boot signed)
     SATA/NVMe Operation  AHCI/NVMe  (10th gen: "SATA Operation"; 11th/12th gen: "Storage")
     Boot sequence ...... USB first
   Save, exit. Auditor USB is plugged in.

2. Auditor boots and runs audit.py            ~1 min attended, then hands-off
     preflight  : identity, BIOS mode, SSD visible (stops with instructions if not)
     attended   : colour screens -> keyboard map -> speaker tone -> fingerprint Y/N
     unattended : scan, secure erase (10 s abort window), JSON + raw dumps, power off

3. Swap to Restorer USB, power on, F2         <1 min, attended
     Secure Boot ........ On
   Save, exit. Setup starts from the USB.

4. Windows 11 installs                        ~20 min, unattended
     wipes disk 0, installs the edition matching the OEM key,
     stage.ps1 installs Dell drivers and writes Dell\Reports\<TAG>.txt to the USB,
     reboots to "Is this the right country or region?"

5. Photo of the OOBE screen, pull the USB, hold power to shut down.
```

Three attended visits, each under two minutes. Run Restorer installs three
wide with three sticks; the auditor is never the bottleneck.

**Before the first batch, run one unit of each model end to end**, then
finish OOBE on it with a throwaway Microsoft account and check: activation
(Settings → System → Activation), Wi-Fi, Bluetooth, fingerprint enrolment,
camera, speakers, GPU in Device Manager. Read `Dell\Reports\<TAG>.txt` on the
Restorer USB. Then restore it again. That is the only test that proves the
driver set and the erase/install sequence on your hardware.

---

## What's in the repo

```
auditor/
├── audit.py               v3 auditor (stdlib only, runs on SystemRescue)
├── autorun                SystemRescue autorun hook (LF endings, no extension)
├── audits/                <TAG>.json + <TAG>/raw/*  copied back from the USB
├── inventory.csv          per-unit grades, colour, charger, status, price, notes
├── build_master_csv.py    audits/ + inventory.csv + legacy -> audit_master_local.csv
├── audit_master_local.csv generated; what the eBay generator reads
├── legacy/                v2 audit rows for the first 14 units (frozen)
├── generate_ebay_drafts_v2.py, generate_ebay_drafts.py, verify_listings.py
restorer/
├── autounattend.xml       Windows 11, retail OOBE, edition from OEM key
├── build_restorer.ps1     copies everything onto each ESD-ISO stick (Windows, admin)
├── get_dell_drivers.ps1   downloads the per-model driver packages from Dell's catalog
├── BUILD_ON_WINDOWS.md    step-by-step build + test guide for any Windows PC
├── SURFACE_AGENT_PROMPT.md  paste-in prompt for a Claude Code session on that PC
└── Dell/
    ├── Scripts/stage.cmd, stage.ps1   run by Setup during specialize
    ├── Drivers/<Model>/               driver packages (not in git) — see Drivers/README.md
    ├── Downloads/<Model>/*.exe        Dell packages to extract (not in git)
    └── Reports/                       written by each install (not in git)
listing-photos/<TAG>/      photos for eBay
ebay_listings_upload.csv   last generated eBay upload file
```

---

## USB 1 — Auditor

**Build once** (any OS that can write FAT32; macOS works):

1. Download the latest SystemRescue ISO from https://www.system-rescue.org/Download/
2. Rufus (Windows): device = stick, boot selection = the ISO, partition scheme **MBR**, file system **FAT32**, write in **ISO image mode**. On macOS: format the stick FAT32/MBR with the volume label SystemRescue expects (the `archisolabel=` value in the ISO's `boot/grub/grubsrcd.cfg`, e.g. `RESCUE1302`), then copy the ISO contents onto it.
3. Copy `auditor/audit.py` to the stick root and `auditor/autorun` into the stick's existing `autorun/` folder. The file must be named exactly `autorun` with LF line endings.
4. If a unit with a GTX 1650 Ti (Vostro 7500) panics at boot, add `modprobe.blacklist=nouveau` to the default kernel line in `boot/grub/grubsrcd.cfg`. Do **not** use `nomodeset`; it disables the Intel display driver and the auditor then cannot read the panel's EDID.

**Update later**: replace `audit.py` on the stick. Nothing else changes.

**After a batch**: copy the stick's `audits/` folder into `auditor/audits/`,
fill grades in `auditor/inventory.csv` while photographing, then

```bash
python3 auditor/build_master_csv.py
```

`audits/summary.txt` on the stick is a one-line-per-unit log. A unit that
was blocked (RST mode, no disk) or errored gets a JSON with `status` set
accordingly and is excluded from the master CSV.

Manual run from the SystemRescue console: `python3 /run/archiso/bootmnt/audit.py`
(flags: `--dry-run`, `--no-erase`, `--skip-tests`, `--outdir`).

### What the auditor records

| Group | Fields |
|---|---|
| identity | service tag, express code, model, SKU, BIOS version/date |
| cpu | model, physical cores, threads, generation |
| memory | total GB from DMI (not MemTotal), type, speed, per-module sizes, slots used/total |
| storage | device, transport, model, capacity, SMART pass, wear %, power-on hours, TB written, media errors |
| battery | health % (full/design), charge %, cycles if the firmware reports them, design Wh |
| display | native resolution and physical size from the EDID timing descriptor, diagonal snapped to a standard size, aspect |
| gpu | discrete and integrated strings from lspci |
| features | Wi-Fi card and standard, Bluetooth, webcam, backlit keyboard, touchscreen, fingerprint |
| license | whether an OEM Windows key exists in the ACPI MSDM table (last 5 characters only) |
| tests | display pass/fail + note, keyboard missing keys, speaker pass/fail/not_tested |
| erase | method used, duration, post-erase zero check |
| warnings | battery < 60 %, SMART fail, wear ≥ 50 %, no OEM key, failed tests, not erased |

The speaker test is `not_tested` on 11th/12th gen units because SystemRescue
does not ship Intel SOF audio firmware; speakers get checked on the golden
unit in Windows.

### The erase

Order tried: `nvme format --ses=1` (NVMe user-data erase), `blkdiscard`
(whole-device TRIM), `nvme sanitize` block erase; SATA: `blkdiscard` then
ATA Security Erase. Guards: the target must be non-removable, on the NVMe or
SATA bus, at least 64 GB, and not the boot USB. There is a 10 second
any-key abort. Afterwards the start, middle and end of the device are read
back and must be zeros for `verified_blank` to be true.

---

## USB 2 — Restorer

**Build** (any Windows PC with a USB-A port, as Administrator). The
full guide with tests and troubleshooting is
[restorer/BUILD_ON_WINDOWS.md](restorer/BUILD_ON_WINDOWS.md); the short
version:

1. Download the Windows 11 multi-edition ISO: https://www.microsoft.com/software-download/windows11
2. Rufus: device = stick, boot selection = the ISO, partition scheme **GPT**, target **UEFI (non CSM)**, file system **NTFS**, volume label **ESD-ISO**. Click START and **uncheck every box** in the "Windows User Experience" dialog (those options would inject the local-account and privacy bypasses we are deliberately not using).
3. Fetch and extract the driver packages (Wi-Fi and Bluetooth are the must-haves; see `restorer/Dell/Drivers/README.md`):

```powershell
cd restorer
.\get_dell_drivers.ps1 -IncludeBios
.\build_restorer.ps1 -ExtractDups -ExtractOnly
```

4. Copy everything onto the stick:

```powershell
.\build_restorer.ps1
```

Repeat step 2 and 4 for each stick. No DISM, no image injection, no
cloning between sticks: with the BIOS in AHCI/NVMe mode the stock media sees
the SSD, so a Restorer stick is Rufus output plus the files this script copies.

Sticks built under the old workflow (injected `install.wim`, Pro-only,
`\drivers` folder) still work but always install Pro. Re-flash them so Setup
can match the edition to each unit's OEM key.

### What the answer file does

- **windowsPE**: wipes Disk 0, GPT partitions (EFI 260 MB, MSR 16 MB, rest NTFS), accepts the EULA. No product key and no image name: Setup installs the edition that matches the key in the laptop's firmware. A unit without a firmware key stops at the key prompt; the auditor flags those units beforehand.
- **specialize**: finds the USB by looking for `\Dell\Scripts\stage.cmd`, runs `pnputil /add-driver … /install` over `Dell\Drivers\<Model>` and `Dell\Drivers\Common`, then writes `Dell\Reports\<TAG>.txt` with the edition, OEM-key presence, Secure Boot state, disk bus type, and every device still lacking a driver.
- **oobeSystem**: nothing. The buyer gets the stock Windows 11 experience.

### Activation

Dell embeds the Windows license in firmware (ACPI MSDM). Setup reads it, and
Windows activates on the first internet connection. Corporate units bought
with volume licensing have no firmware key; those show
`oem_key_present: false` in the audit and `NONE IN FIRMWARE` in the report,
and need a purchased key or an honest "no OS license" listing.

---

## BIOS settings reference (Dell, F2 at power-on)

| Setting | Auditor | Restorer | Shipped |
|---|---|---|---|
| Secure Boot | Off | On | **On** |
| SATA / NVMe Operation | AHCI/NVMe | AHCI/NVMe | **AHCI/NVMe** |
| Boot sequence | USB first | USB first | any |

AHCI is not Dell's factory default (RAID On / VMD). It is invisible to the
buyer and means any future reinstall needs no Intel RST driver. The one
support case: a buyer who later "loads BIOS defaults" flips storage back to
RAID and Windows will not boot until they set AHCI again.

Optional: Dell's F12 menu → **BIOS Flash Update** can flash the latest BIOS
from a FAT32 stick (drop the model's BIOS `.exe` on the Auditor stick). Worth
doing on 2020–2022 units for the security fixes; one more attended start.

---

## eBay listing pipeline (unchanged)

```
audits/*.json + inventory.csv ─ build_master_csv.py ─▶ audit_master_local.csv
        ─ generate_ebay_drafts_v2.py ─▶ ebay_listings_upload.csv ─▶ Seller Hub upload
```

```bash
python3 auditor/build_master_csv.py
python3 auditor/generate_ebay_drafts_v2.py auditor/audit_master_local.csv
python3 auditor/verify_listings.py
```

The master CSV keeps the v2 column names first so the generator needs no
changes, and appends evidence columns (`ssd_wear_pct`, `ssd_power_on_hours`,
`oem_key_present`, `erase_method`, `warnings`, …) for the description
template to use later. Photos, pricing tiers and upload steps are as before:
photos in `listing-photos/<TAG>/` served from GitHub raw URLs, first photo
alphabetically is the gallery image, reorder in Seller Hub after upload.

---

## License

MIT
