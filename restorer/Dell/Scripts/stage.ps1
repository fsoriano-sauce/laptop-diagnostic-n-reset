<#
  stage.ps1 -Usb X:  [-NoInstall]
  Runs during the Windows specialize pass (SYSTEM, no user, before OOBE),
  or by hand from a Shift+F10 prompt at the OOBE screen.

  1. Copies this model's driver folders from the USB to C:\Dell\Drivers.
     Installing straight from the USB proved fragile: chipset / USB /
     Thunderbolt driver installs re-enumerate the stick mid-run, pnputil
     loses its source and every later write to the stick is lost.
  2. Installs each package with pnputil from the local copy, logging the
     result per package (exit 0 = installed, 259 = no matching device,
     3010 = installed, needs the reboot that follows anyway).
  3. Writes C:\Dell\Reports\<ServiceTag>.txt: edition, OEM key presence,
     Secure Boot state, disk bus type, every device without a driver.
  4. Re-finds the USB by scanning drive letters and copies the reports to
     <USB>\Dell\Reports\, then deletes C:\Dell\Drivers. C:\Dell\Reports is
     kept only if the USB could not be found.

  -NoInstall (test on any PC): skips 1, 2 and the cleanup; writes the
  report straight to the USB so nothing is left on the test machine.
#>
param(
    [Parameter(Mandatory = $true)][string]$Usb,
    [switch]$NoInstall
)

$ErrorActionPreference = "Continue"
$Usb = $Usb.TrimEnd("\")

function Get-Model { try { (Get-CimInstance Win32_ComputerSystem -ErrorAction Stop).Model.Trim() } catch { "" } }
function Get-Tag   { try { (Get-CimInstance Win32_BIOS -ErrorAction Stop).SerialNumber.Trim() } catch { "UNKNOWN" } }
function Normalize([string]$s) { ($s -replace "[^A-Za-z0-9]", "").ToLower() }
function Find-Usb {
    foreach ($l in "D","E","F","G","H","I","J","K","L","M","N") {
        if (Test-Path "${l}:\Dell\Scripts\stage.cmd") { return "${l}:" }
    }
    return $null
}

$tag   = Get-Tag
$model = Get-Model
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

# Where to work. Live: local disk. NoInstall test: straight on the USB.
if ($NoInstall) { $work = Join-Path $Usb "Dell" } else { $work = Join-Path $env:SystemDrive "Dell" }
$localDrv = Join-Path $work "Drivers"
$reports  = Join-Path $work "Reports"
New-Item -ItemType Directory -Force -Path $reports | Out-Null
$report = Join-Path $reports "$tag.txt"
$pnpLog = Join-Path $reports "$tag-pnputil.log"

function R($line) { $line | Add-Content $report }

"=== Restorer stage report  $stamp ===" | Set-Content $report
R "Service tag : $tag"
R "Model       : $model"
R "USB         : $Usb"
R "Work dir    : $work$(if ($NoInstall) {'  [NoInstall test mode]'})"

# ── 1. Match + copy driver folders ───────────────────────────────────────────
$srcRoot = Join-Path $Usb "Dell\Drivers"
$matched = @()
if (Test-Path $srcRoot) {
    $nm = Normalize $model
    foreach ($d in Get-ChildItem -Directory $srcRoot) {
        $nd = Normalize $d.Name
        if ($nd -eq "common" -or ($nd -and ($nm -like "*$nd*" -or $nd -like "*$nm*"))) { $matched += $d }
    }
}
R ""
R "Driver folders matched for this model:"
if (-not $matched) { R "  (none)  -> Windows Update will supply drivers after the buyer connects" }
$packages = @()
foreach ($d in $matched) {
    $infs = @(Get-ChildItem -Path $d.FullName -Recurse -Filter *.inf -ErrorAction SilentlyContinue)
    if ($NoInstall) {
        R "  $($d.FullName)  ($($infs.Count) .inf)  [NoInstall: not copied, not installed]"
        continue
    }
    $dest = Join-Path $localDrv $d.Name
    $t0 = Get-Date
    & robocopy.exe $d.FullName $dest /E /R:2 /W:2 /NFL /NDL /NJH /NJS /NP | Out-Null
    $rc = $LASTEXITCODE   # robocopy: <8 = success
    $copied = @(Get-ChildItem -Path $dest -Recurse -Filter *.inf -ErrorAction SilentlyContinue).Count
    R ("  {0}  ({1} .inf) -> copied {2} .inf to {3} in {4:N0}s (robocopy rc {5})" -f $d.FullName, $infs.Count, $copied, $dest, ((Get-Date) - $t0).TotalSeconds, $rc)
    if ($copied -eq 0) { R "  !! copy produced no .inf files; skipping install for this folder"; continue }
    # one package per sub-folder; a bare .inf directly in the folder counts as its own package
    $subs = @(Get-ChildItem -Directory $dest -ErrorAction SilentlyContinue)
    if ($subs) { $packages += $subs } else { $packages += Get-Item $dest }
}

# ── 2. Install per package ───────────────────────────────────────────────────
if (-not $NoInstall -and $packages) {
    R ""
    R "Driver install (pnputil, per package; 0 = installed, 259 = no matching device, 3010 = installed + reboot pending):"
    "=== pnputil run $stamp  tag $tag  model $model ===" | Set-Content $pnpLog
    foreach ($p in $packages) {
        $n = @(Get-ChildItem -Path $p.FullName -Recurse -Filter *.inf -ErrorAction SilentlyContinue).Count
        if ($n -eq 0) { continue }
        "--- $($p.Name) ($n .inf) ---" | Add-Content $pnpLog
        $t0 = Get-Date
        $out = & pnputil.exe /add-driver "$($p.FullName)\*.inf" /subdirs /install 2>&1
        $rc = $LASTEXITCODE
        $out | ForEach-Object { "$_" } | Add-Content $pnpLog
        "exit code: $rc" | Add-Content $pnpLog
        $added = @($out | Where-Object { "$_" -match "Driver package added successfully|Total driver packages:\s*\d+" }).Count
        R ("  rc {0,4}  {1,3} inf  {2,5:N0}s  {3}" -f $rc, $n, ((Get-Date) - $t0).TotalSeconds, $p.Name)
    }
}

# ── 3. System report ─────────────────────────────────────────────────────────
R ""
try {
    $os = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
    $cv = Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion" -ErrorAction Stop
    R "Windows     : $($os.Caption)  $($cv.DisplayVersion)  build $($cv.CurrentBuild).$($cv.UBR)  edition $($cv.EditionID)"
} catch { R "Windows     : (query failed: $_)" }

try {
    $oa3 = (Get-CimInstance SoftwareLicensingService -ErrorAction Stop).OA3xOriginalProductKey
    if ($oa3) { R "OEM key     : present, ends ...$($oa3.Substring($oa3.Length-5))  (activates on first internet connection)" }
    else      { R "OEM key     : NONE IN FIRMWARE - this unit will not activate" }
} catch { R "OEM key     : (query failed: $_)" }

try { R "Secure Boot : $(if (Confirm-SecureBootUEFI -ErrorAction Stop) {'ON'} else {'OFF - turn on in BIOS before shipping'})" }
catch { R "Secure Boot : unknown ($_)" }

try {
    $tpm = Get-CimInstance -Namespace root\cimv2\security\microsofttpm -ClassName Win32_Tpm -ErrorAction Stop
    R "TPM         : present=$($tpm.IsEnabled_InitialValue) spec=$($tpm.SpecVersion)"
} catch { R "TPM         : unknown" }

try {
    R "Disks       :"
    Get-PhysicalDisk -ErrorAction Stop | ForEach-Object { R "  $($_.FriendlyName)  $([math]::Round($_.Size/1GB)) GB  bus=$($_.BusType)  media=$($_.MediaType)" }
} catch { R "Disks       : unknown" }

R ""
R "Devices with problems (empty = driver set complete):"
try {
    $bad = Get-PnpDevice -PresentOnly -ErrorAction Stop | Where-Object { $_.Status -ne "OK" -and $_.Class -notin @("SoftwareDevice","Volume","VolumeSnapshot") }
    if ($bad) { $bad | ForEach-Object { R "  [$($_.Status)] $($_.Class): $($_.FriendlyName)  ($($_.InstanceId))" } }
    else { R "  (none)" }
} catch { R "  (query failed: $_)" }

R ""
R "Key devices:"
try {
    foreach ($cls in @("Net","Bluetooth","Biometric","Camera","Image","MEDIA","Display","HIDClass")) {
        Get-PnpDevice -PresentOnly -Class $cls -ErrorAction SilentlyContinue |
            Where-Object { $_.FriendlyName -notmatch "Miniport|Virtual|Microsoft|WAN|Root Hub|Generic" } |
            ForEach-Object { R "  [$($_.Status)] $($cls): $($_.FriendlyName)" }
    }
} catch {}

R ""
R "=== end $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ==="

# ── 4. Hand the reports back to the USB, clean up ────────────────────────────
if (-not $NoInstall) {
    $usbNow = Find-Usb
    if ($usbNow) {
        $dstRep = Join-Path $usbNow "Dell\Reports"
        New-Item -ItemType Directory -Force -Path $dstRep | Out-Null
        Copy-Item (Join-Path $reports "*") $dstRep -Force -ErrorAction SilentlyContinue
        if (Test-Path (Join-Path $dstRep "$tag.txt")) {
            Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue     # drivers + local reports gone
        } else {
            Remove-Item $localDrv -Recurse -Force -ErrorAction SilentlyContinue # keep C:\Dell\Reports for Shift+F10 retrieval
        }
    } else {
        Remove-Item $localDrv -Recurse -Force -ErrorAction SilentlyContinue
        "USB not found at the end of staging; reports left in $reports" | Add-Content $report
    }
}
exit 0
