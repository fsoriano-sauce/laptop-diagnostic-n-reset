# Building and testing the Restorer on any Windows PC

Works on a Surface Pro, the Dell Precision, or any Windows 10/11 machine
with a USB-A port (or a USB-C to A adapter). Nothing here needs the
laptops themselves until the final golden-unit test. Every step says whether
it needs a human at the keyboard or can be done by a Claude Code session.

## 0. What you need

| Item | Who | Notes |
|---|---|---|
| Windows 11 multi-edition ISO | human or agent | https://www.microsoft.com/software-download/windows11 → "Windows 11 (multi-edition ISO for x64 devices)", English (United States). About 8 GB (25H2 is 7.9 GB). The page generates a link that is valid for 24 hours and lists SHA256 hashes under "Verify your download"; check the English 64-bit one. Save as `C:\Temp\Win11.iso`. |
| Rufus | human | https://rufus.ie, the portable `.exe` is fine; on an ARM64 PC (Surface Pro 11) take the `_arm64` build. Keep it in `C:\Temp` and start it from there: Rufus drops a `rufus.com` helper into its working folder, which must not be the repo. |
| Git + Claude Code | human, once | Claude Code on Windows needs Git for Windows. |
| Free disk space | | ~40 GB (ISO 8 + driver downloads 9 + extracted drivers ~17). |
| 7-Zip | optional | for the rare Dell package that will not self-extract. |
| The Restorer USB sticks | | 32 GB minimum, 64 GB comfortable: the Windows media is about 8 GB and the driver set about 17 GB. Write speed matters more than size: a cheap 64 GB stick writing at 5 MB/s takes an hour per build, a decent one 13 minutes. |

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

A Claude Code session in the desktop app is **not** elevated and cannot
elevate itself. Only two steps need it: extracting Dell packages
(`-ExtractDups`, the `.exe` files are manifested `requireAdministrator`) and
anything that runs `build_restorer.ps1` (it carries `#Requires
-RunAsAdministrator`). For those the agent writes a small runner, for example
`C:\Temp\restorer-build.ps1`, that starts a transcript to `C:\Temp\*.log` and
calls the build script, launches it with `Start-Process powershell -Verb RunAs
-ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','C:\Temp\restorer-build.ps1'`,
and you click Yes on the UAC prompt within two minutes (Windows cancels it
after that). The agent then polls `Get-Process` and reads the log;
`Wait-Process` on an elevated process errors with "Access is denied" from an
unelevated shell, so poll instead.
Downloads, catalog parsing, the section 2 checks, the section 6 checks and
the `-NoInstall` dry run all run without elevation.

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

Then pre-flight the whole set on this PC, no laptop needed. Every package is
staged into this PC's driver store with `pnputil /add-driver` (never
installed on a device) and removed again; anything pnputil refuses here
would fail on the laptop:

```powershell
.\build_restorer.ps1 -ValidateDrivers -ExtractOnly
```

Expect one `ok` line per package that holds `.inf` files: 45 with the
curated set (1 in `Common\`, 18 for the 7620, 14 for the 7510, 12 for the
7500). A package that fails with
"cannot find the file specified" during Setup is one of Dell's newer
MUP-layout NVIDIA packages (a `14393\Drivers\NV\` tree); do not try to
repair it by expanding its stubs, that makes it stage on a build PC but it
still fails during Setup. Ship the one proven NVIDIA package from `Common\`
instead, as `Dell\Drivers\README.md` describes. A `FAIL ... rc 87` with
nothing staged is the build PC's own path length (the Killer Bluetooth
package nests its INFs 252 to 259 characters deep under the repo, at the
MAX_PATH limit); the validator
stages through a short `C:\_dv` junction to avoid it, and the same package
installs fine from `C:\Dell\Drivers` on the laptop.

Expect a few packages to refuse `/s /e=`; the script names them. Open those
in 7-Zip and copy the folder holding the `.inf` files into
`Dell\Drivers\<Model>\<name>\`. Priorities are in `Dell\Drivers\README.md`:
Wi-Fi and Bluetooth are must-haves, the rest can come from Windows Update.

Dell's `CatalogPC.cab` (the Dell Command | Update feed) lists no Vostro
models at all. The script therefore reads `CatalogIndexPC.cab` and, from it,
one small per-model catalog per Vostro (`Vostro_Notebook_<systemID>.cab`,
200 to 400 KB each, 4 to 9 MB once expanded to `.xml`: 7620 = 0B3F,
15 7510 = 0A82, 7500 = 09F0), all cached for seven days under
`Dell\Catalog\`. The default model names match those
catalogs exactly. If a model still matches nothing, search
`Dell\Catalog\CatalogIndexPC.xml` for its number and pass the exact display
name with `-Models`.

Also expected: six of the 53 packages never self-extract and contain no
`.inf` at all (three Waves MaxxAudio apps, the 7500's two Intel ME
installers, the 7620's Intel Processor Power Management package 01XGJ; the
similarly named Intel PPM Provisioning package 8DG2H extracts and installs
fine). Ignore them; 7-Zip finds nothing useful inside either.

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

Two traps. Rufus pre-fills **Volume label** with the ISO's own name
(`CCCOMA_X64FRE_EN-US_DV9`); retype it as `ESD-ISO` before START or the
build script will not see the stick. And the status bar reads READY both
before you start and after it finishes: writing takes about six minutes, and
the finished state is the green bar with an elapsed time in the corner.
Rufus also leaves a small `RUFUS_BOOT` / `UEFI_NTFS` partition next to the
stick; that is its NTFS boot shim and is expected.

## 5. Build the stick (agent)

```powershell
.\build_restorer.ps1            # every ESD-ISO stick that is plugged in
.\build_restorer.ps1 -Drive E:  # one stick
```

Prints per stick: files ok, edition count, number of `.inf` drivers, free
space. With the 25H2 ISO expect `editions=11`, and the `.inf` count must be
the same on every stick. Several sticks can be attached at once; one run
handles them in sequence. To build a stick that was plugged in while another
run is still copying, start a second run with `-Drive X:`; each run touches
only the sticks it enumerated at start, so they do not interfere. A rebuild
after a script or driver change copies only what changed and takes seconds
on the mirror step.

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
found the USB by letter, and wrote a readable report of several dozen lines
ending in `=== end ... ===`, with nothing left in `C:\Dell` on this PC. From
an unelevated shell the report says `Secure Boot : unknown` and
`TPM : unknown`; under Setup, which runs as SYSTEM, both resolve. Delete the
dry-run `<this PC's tag>.txt` and `_stage-cmd.log` afterwards so the first
laptop report is clean, but keep any real laptop reports the stick carries.
With more than one Restorer stick attached, `stage.cmd`'s final loop appends
its end line to the first drive letter that holds `Dell\Scripts\stage.cmd`,
which may be a different stick: check every attached stick's `Dell\Reports`
before ejecting.

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
   - Per-package lines: `rc 0` installed, `rc 259` package added but no
     matching device on this unit (normal for multi-model packages, e.g. the
     Killer Bluetooth package on a 7620), `rc 3010` installed and waiting for
     the reboot that follows anyway, `rc 2` file not found (a broken package,
     see section 3). On a Vostro 7500 five chipset entries under "Devices with
     problems" are normal and Windows Update fills them (PCI `DEV_1911`,
     `06A3`, `06A4`, `06E0`, `06F9`). On any model a `3D Video Controller`
     entry (`10DE:25A0` on the RTX 3050 Ti units, `10DE:1F95` on the 7500's
     GTX 1650 Ti) means the NVIDIA package did not stage. `Secure Boot : OFF`
     means the unit was installed with it off: turn it on before shipping.
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
| Report ends right after "Driver folders matched" | USB re-enumerated during a chipset/USB driver install and the stick vanished mid-run | fixed in stage.ps1 (drivers copy to `C:\Dell` first, reports written locally and copied back). Recover a unit at its OOBE screen with Shift+F10 and run `<usb>\Dell\Scripts\stage.cmd <usb>` by hand. |
| OOBE has no Wi-Fi networks | Wi-Fi driver not staged | add the Intel Wi-Fi package to `Dell\Drivers\Common\` and rebuild. |
| Rufus: "revoked UEFI bootloader" | Microsoft's own boot files | OK, expected. |
| build script says `SINGLE edition` and skips the stick | stick was not re-flashed; it still carries the April injected Pro-only image | Rufus from `C:\Temp\Win11.iso` (section 4), then rerun the build. Drivers are already extracted, so it is copy-only. |
| `get_dell_drivers.ps1` lists nothing for a model | the model is not in Dell's per-model catalog index under that name | search `Dell\Catalog\CatalogIndexPC.xml` for the model number and pass the exact display name with `-Models` (section 3). |
| Build says "No removable volume labelled ESD-ISO" although the stick is in | Rufus kept the ISO's own volume label | rename the volume to `ESD-ISO` or re-flash with the label typed in (section 4). |
| `Dell\Reports\<TAG>.txt` is a single header line | the report helper was named `R`, which PowerShell's built-in `r` alias (Invoke-History) shadows | fixed in 669c7a6 (helper renamed `Rpt`); pull and rebuild the stick. |
| `C:\Dell` left on the unit after a successful install | cmd's `>>` redirect kept `_stage-cmd.log` open, so stage.ps1's cleanup could not empty the folder | fixed in 2bb27b0 (stage.cmd finishes the cleanup after PowerShell exits). |
| `-ValidateDrivers` reports `FAIL ... rc 87` with 0 staged | the package's INFs sit at 252 to 259 characters under the repo path, at the MAX_PATH limit | fixed in ce80b09 (validation runs through a `C:\_dv` junction); the same package installs from `C:\Dell\Drivers` on the laptop. |
| Killer Bluetooth package shows fewer `.inf` files under the repo path than on the stick (1 of 11 in the `Vostro 15 7510` copy, 10 of 11 in the others) | same path length: PowerShell 5.1 cannot open files past 260 characters | harmless; robocopy and the stick see all the files. |
| Setup blue-screens (`0x1D5 DRIVER_PNP_WATCHDOG`) during specialize | an Intel RST/VMD storage driver was staged; the units run in AHCI mode | remove every `*Rapid-Storage*` package from `Dell\Drivers` and `Dell\Downloads` and rebuild; `stage.ps1` also skips them by name (d5c2914). |
| Stick build takes an hour | slow flash stick (5 MB/s) | wait, or buy sticks that write at 20 MB/s or better; the build is the same. |
