# Building and testing the Restorer on any Windows PC

Works on a Surface Pro, the Dell Precision, or any Windows 10/11 machine
with a USB-A port (or a USB-C to A adapter). Nothing here needs the
laptops themselves until the final golden-unit test. Every step says whether
it needs a human at the keyboard or can be done by a Claude Code session.

## 0. What you need

| Item | Who | Notes |
|---|---|---|
| Windows 11 multi-edition ISO | human | https://www.microsoft.com/software-download/windows11 → "Download Windows 11 Disk Image (ISO) for x64 devices". About 6 GB. Save as `C:\Temp\Win11.iso`. |
| Rufus | human | https://rufus.ie, the portable `.exe` is fine. |
| Git + Claude Code | human, once | Claude Code on Windows needs Git for Windows. |
| Free disk space | | ~15 GB (ISO + driver downloads + extraction). |
| 7-Zip | optional | for the rare Dell package that will not self-extract. |
| The Restorer USB sticks | | 16 GB minimum, 32 GB comfortable once drivers are on them. |

## 1. Get the repo

```powershell
cd $HOME\Documents
git clone https://github.com/fsoriano-sauce/laptop-diagnostic-n-reset.git
cd laptop-diagnostic-n-reset
git checkout v3-line-toolkit      # until it is merged to master
```

Open an **elevated** PowerShell (Run as Administrator) for everything below,
and allow local scripts once:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
```

## 2. Static checks (agent, no hardware)

These prove the files parse before anything touches a stick. The scripts
were authored on macOS and this is their first run on Windows, so fix what
fails, minimally, and commit.

```powershell
cd restorer
# PowerShell syntax
foreach ($f in "build_restorer.ps1","get_dell_drivers.ps1","Dell\Scripts\stage.ps1") {
  $t=$null;$e=$null
  [System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path $f),[ref]$t,[ref]$e) | Out-Null
  if ($e) { "FAIL $f"; $e | % { "  line $($_.Extent.StartLineNumber): $($_.Message)" } } else { "OK   $f" }
}
# Answer file is well-formed XML with the three expected passes
[xml]$x = Get-Content autounattend.xml -Raw
$x.unattend.settings.pass          # expect: windowsPE, specialize
# Batch file has CRLF endings (git enforces this; confirm)
(Get-Content Dell\Scripts\stage.cmd -Raw) -match "`r`n"
```

Optional, stronger: install the Windows ADK "Deployment Tools" and open
`autounattend.xml` in Windows System Image Manager against the ISO's
`install.wim`; Validate Answer File must report no errors.

## 3. Drivers (agent, needs internet)

```powershell
.\get_dell_drivers.ps1 -ListOnly              # shows what would be fetched per model
.\get_dell_drivers.ps1 -IncludeBios           # downloads to Dell\Downloads\<Model>\ and Dell\BIOS\<Model>\
.\build_restorer.ps1 -ExtractDups -ExtractOnly   # extracts .exe packages into Dell\Drivers\<Model>\
```

Expect a few packages to refuse `/s /e=`; the script names them. Open those
in 7-Zip and copy the folder holding the `.inf` files into
`Dell\Drivers\<Model>\<name>\`. Priorities are in `Dell\Drivers\README.md`:
Wi-Fi and Bluetooth are must-haves, the rest can come from Windows Update.

If `get_dell_drivers.ps1` matches nothing for a model, the catalog display
name differs from ours. Search `Dell\Catalog\CatalogPC.xml` for `7620` and
pass the exact name with `-Models`.

## 4. Flash a stick with Rufus (human, 2 minutes per stick)

| Rufus field | Value |
|---|---|
| Device | the stick |
| Boot selection | `C:\Temp\Win11.iso` |
| Image option | Standard Windows installation |
| Partition scheme | **GPT** |
| Target system | **UEFI (non CSM)** |
| Volume label | **ESD-ISO** |
| File system | **NTFS** |
| Cluster size | default |

START → in the "Windows User Experience" dialog **uncheck every box** (those
options inject the local-account and privacy bypasses we deliberately do not
want) → OK. If Rufus warns about a revoked UEFI bootloader, click OK; that is
expected for official Microsoft ISOs.

## 5. Build the stick (agent)

```powershell
.\build_restorer.ps1            # every ESD-ISO stick that is plugged in
.\build_restorer.ps1 -Drive E:  # one stick
```

Prints per stick: files ok, number of `.inf` drivers, free space.

## 6. Stick verification (agent, stick plugged in, no laptop)

```powershell
$u = "E:"     # the stick
Test-Path "$u\autounattend.xml"; Test-Path "$u\Dell\Scripts\stage.cmd"; Test-Path "$u\Dell\Scripts\stage.ps1"
(Test-Path "$u\sources\install.esd") -or (Test-Path "$u\sources\install.wim")
# Stock media carries 8+ editions. Exactly 1 means an old injected image: re-flash with Rufus.
$img = Get-Item "$u\sources\install.*" | Select-Object -First 1; $fs=[IO.File]::OpenRead($img.FullName); $b=New-Object byte[] 48; $null=$fs.Read($b,0,48); $fs.Close(); "editions: $([BitConverter]::ToUInt32($b,0x2C))  size: $([math]::Round($img.Length/1GB,2)) GB  dated: $($img.LastWriteTime.ToString('yyyy-MM-dd'))"
Get-ChildItem "$u\Dell\Drivers" -Directory | % { "{0}: {1} inf" -f $_.Name, (Get-ChildItem $_.FullName -Recurse -Filter *.inf | Measure-Object).Count }
# Dry-run the specialize script exactly as Setup will call it, but installing nothing:
& "$u\Dell\Scripts\stage.cmd" $u -NoInstall
Get-Content "$u\Dell\Reports\_stage-cmd.log"
Get-Content "$u\Dell\Reports\*.txt"        # report for THIS PC: model, edition, OEM key, Secure Boot, device list
```

The report will say the driver folders matched nothing (this PC is not a
Vostro), which is correct. What matters is that the script ran end to end,
found the USB by letter, and wrote a readable report. Delete
`$u\Dell\Reports\*` afterwards so the first laptop report is clean.

## 7. Golden unit (human + agent, one laptop per model)

Prerequisite: the unit has been through the Auditor (BIOS in AHCI/NVMe,
disk erased, JSON written). Then:

1. Plug the Restorer in, power on, F2 → Secure Boot **On**, save.
2. Setup runs unattended to "Is this the right country or region?" Note the time.
3. Pull the stick, read `Dell\Reports\<TAG>.txt` on this PC:
   - `Windows : … edition Professional` (or whatever the OEM key is)
   - `OEM key : present`
   - `Secure Boot : ON`
   - `Devices with problems:` ideally `(none)`; anything listed is a driver to add
4. On the laptop, finish OOBE with a throwaway Microsoft account and check: Settings → System → Activation says active; Wi-Fi lists networks; Bluetooth toggles; Windows Hello fingerprint enrolment offered; camera app shows video; speakers play; Device Manager shows the NVIDIA GPU with no warning icons.
5. Boot the Auditor again (Secure Boot off, then on again after) or simply run the Restorer again to wipe the throwaway account.

Record the result per model in the conversation and, if drivers were
missing, add packages and re-run steps 3, 5, 6.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Setup: "disk 0 does not exist" / no drives listed | BIOS still in RAID/VMD | F2 → SATA/NVMe Operation → AHCI/NVMe. The Auditor would have refused this unit; it was skipped. |
| Setup stops at a product-key or edition prompt | no OEM key in firmware | expected on volume-licensed units; the audit JSON shows `oem_key_present: false`. Buy a key or list as unactivated. |
| Setup wiped the wrong disk | a second internal disk enumerated as Disk 0 | unlikely on this fleet (one SSD); check the audit's `other_internal_disks`. |
| No `Dell\Reports\<TAG>.txt` after install | specialize command did not find the stick | check `Dell\Reports\_stage-cmd.log`; if absent, the `for` loop in autounattend.xml did not see the drive letter. Plug the stick into a different port and retry. |
| OOBE has no Wi-Fi networks | Wi-Fi driver not staged | add the Intel Wi-Fi package to `Dell\Drivers\Common\` and rebuild. |
| Rufus: "revoked UEFI bootloader" | Microsoft's own boot files | OK, expected. |
| build script says `SINGLE edition` and skips the stick | stick was not re-flashed; it still carries the April injected Pro-only image | Rufus from `C:\Temp\Win11.iso` (section 4), then rerun the build. Drivers are already extracted, so it is copy-only. |
| `get_dell_drivers.ps1` parse takes minutes or runs out of memory | CatalogPC.xml is ~100 MB | normal on a small PC; wait, or run with `-Models "Vostro 7620"` alone. |
