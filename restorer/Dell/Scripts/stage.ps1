<#
  stage.ps1 -Usb X:
  Runs during the Windows specialize pass (SYSTEM, no user, before OOBE).

  1. Installs every driver package under X:\Dell\Drivers\<Model>\ and
     X:\Dell\Drivers\Common\ with pnputil, so Wi-Fi, Bluetooth, fingerprint,
     audio, GPU and touchpad are present at the first OOBE screen.
  2. Writes X:\Dell\Reports\<ServiceTag>.txt: edition, OEM key presence,
     Secure Boot state, disk bus type, and every device without a working
     driver. An empty "Devices with problems" section means the driver set
     is complete for that model.
#>
param(
    [Parameter(Mandatory = $true)][string]$Usb,
    [switch]$NoInstall     # test mode: match folders and write the report, install nothing
)

$ErrorActionPreference = "Continue"
$Usb = $Usb.TrimEnd("\")
$reports = Join-Path $Usb "Dell\Reports"
New-Item -ItemType Directory -Force -Path $reports | Out-Null

function Get-Model {
    try { (Get-CimInstance Win32_ComputerSystem).Model.Trim() } catch { "" }
}
function Get-Tag {
    try { (Get-CimInstance Win32_BIOS).SerialNumber.Trim() } catch { "UNKNOWN" }
}
function Normalize([string]$s) { ($s -replace "[^A-Za-z0-9]", "").ToLower() }

$tag   = Get-Tag
$model = Get-Model
$report = Join-Path $reports "$tag.txt"
$pnpLog = Join-Path $reports "$tag-pnputil.log"
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

"=== Restorer stage report  $stamp ===" | Set-Content $report
"Service tag : $tag"    | Add-Content $report
"Model       : $model"  | Add-Content $report
"USB         : $Usb"    | Add-Content $report

# ── 1. Drivers ───────────────────────────────────────────────────────────────
$driverRoot = Join-Path $Usb "Dell\Drivers"
$folders = @()
if (Test-Path $driverRoot) {
    $nm = Normalize $model
    foreach ($d in Get-ChildItem -Directory $driverRoot) {
        $nd = Normalize $d.Name
        if ($nd -eq "common" -or ($nd -and ($nm -like "*$nd*" -or $nd -like "*$nm*"))) { $folders += $d.FullName }
    }
}
"" | Add-Content $report
"Driver folders matched for this model:" | Add-Content $report
if (-not $folders) { "  (none)  -> Windows Update will supply drivers after the buyer connects" | Add-Content $report }
foreach ($f in $folders) {
    $infs = @(Get-ChildItem -Path $f -Recurse -Filter *.inf -ErrorAction SilentlyContinue)
    "  $f  ($($infs.Count) .inf)$(if ($NoInstall) {'  [NoInstall: skipped]'})" | Add-Content $report
    if ($infs.Count -gt 0 -and -not $NoInstall) {
        "=== pnputil $f ===" | Add-Content $pnpLog
        & pnputil.exe /add-driver "$f\*.inf" /subdirs /install 2>&1 | Add-Content $pnpLog
        "exit code: $LASTEXITCODE" | Add-Content $pnpLog
    }
}

# ── 2. Report ────────────────────────────────────────────────────────────────
"" | Add-Content $report
try {
    $os = Get-CimInstance Win32_OperatingSystem
    $cv = Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion"
    "Windows     : $($os.Caption)  $($cv.DisplayVersion)  build $($cv.CurrentBuild).$($cv.UBR)  edition $($cv.EditionID)" | Add-Content $report
} catch { "Windows     : (query failed: $_)" | Add-Content $report }

try {
    $oa3 = (Get-CimInstance SoftwareLicensingService).OA3xOriginalProductKey
    if ($oa3) { "OEM key     : present, ends ...$($oa3.Substring($oa3.Length-5))  (activates on first internet connection)" | Add-Content $report }
    else      { "OEM key     : NONE IN FIRMWARE - this unit will not activate" | Add-Content $report }
} catch { "OEM key     : (query failed: $_)" | Add-Content $report }

try { "Secure Boot : $(if (Confirm-SecureBootUEFI) {'ON'} else {'OFF - turn on in BIOS before shipping'})" | Add-Content $report }
catch { "Secure Boot : unknown ($_)" | Add-Content $report }

try {
    $tpm = Get-CimInstance -Namespace root\cimv2\security\microsofttpm -ClassName Win32_Tpm
    "TPM         : present=$($tpm.IsEnabled_InitialValue) spec=$($tpm.SpecVersion)" | Add-Content $report
} catch { "TPM         : unknown" | Add-Content $report }

try {
    "Disks       :" | Add-Content $report
    Get-PhysicalDisk | ForEach-Object { "  $($_.FriendlyName)  $([math]::Round($_.Size/1GB)) GB  bus=$($_.BusType)  media=$($_.MediaType)" } | Add-Content $report
} catch { "Disks       : unknown" | Add-Content $report }

"" | Add-Content $report
"Devices with problems (empty = driver set complete):" | Add-Content $report
try {
    $bad = Get-PnpDevice -PresentOnly | Where-Object { $_.Status -ne "OK" -and $_.Class -notin @("SoftwareDevice","Volume","VolumeSnapshot") }
    if ($bad) { $bad | ForEach-Object { "  [$($_.Status)] $($_.Class): $($_.FriendlyName)  ($($_.InstanceId))" } | Add-Content $report }
    else { "  (none)" | Add-Content $report }
} catch { "  (query failed: $_)" | Add-Content $report }

"" | Add-Content $report
"Key devices:" | Add-Content $report
try {
    foreach ($cls in @("Net","Bluetooth","Biometric","Camera","Image","MEDIA","Display","HIDClass")) {
        Get-PnpDevice -PresentOnly -Class $cls -ErrorAction SilentlyContinue |
            Where-Object { $_.FriendlyName -notmatch "Miniport|Virtual|Microsoft|WAN|Root Hub|Generic" } |
            ForEach-Object { "  [$($_.Status)] $($cls): $($_.FriendlyName)" } | Add-Content $report
    }
} catch {}

"" | Add-Content $report
"=== end ===" | Add-Content $report
exit 0
