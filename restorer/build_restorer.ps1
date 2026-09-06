<#
.SYNOPSIS
  Turn a Rufus-flashed Windows 11 USB into a Restorer stick.

.DESCRIPTION
  Run on the Windows machine (Dell Precision) as Administrator after flashing
  each stick with Rufus from the stock Windows 11 ISO (GPT, UEFI non-CSM,
  NTFS, volume label ESD-ISO, all "Windows User Experience" boxes unchecked).

  For every removable volume labelled ESD-ISO this script:
    1. copies restorer\autounattend.xml to the root
    2. mirrors restorer\Dell\Scripts  -> X:\Dell\Scripts
    3. mirrors restorer\Dell\Drivers  -> X:\Dell\Drivers   (per-model folders)
    4. removes leftovers from the old injected-image workflow (\drivers, *.bak)
    5. verifies the result and prints a per-stick summary

  Optional -ExtractDups: before step 3, extracts every Dell Update Package
  .exe found under restorer\Dell\Downloads\<Model>\ into
  restorer\Dell\Drivers\<Model>\<PackageName>\ using the DUP "/s /e=" switch.
  Packages that do not support /e are listed so you can open them with 7-Zip.

.EXAMPLE
  .\build_restorer.ps1
  .\build_restorer.ps1 -ExtractDups
  .\build_restorer.ps1 -ExtractDups -ExtractOnly    # no stick needed yet
  .\build_restorer.ps1 -Drive E:
#>
#Requires -RunAsAdministrator
[CmdletBinding()]
param(
    [switch]$ExtractDups,
    [switch]$ExtractOnly,
    [string]$Drive
)
$ErrorActionPreference = "Stop"
$root      = $PSScriptRoot
$xmlSrc    = Join-Path $root "autounattend.xml"
$scriptsSrc= Join-Path $root "Dell\Scripts"
$driversSrc= Join-Path $root "Dell\Drivers"
$dupsSrc   = Join-Path $root "Dell\Downloads"

function Say($m) { Write-Host "[$(Get-Date -Format HH:mm:ss)] $m" }

foreach ($p in @($xmlSrc, $scriptsSrc)) {
    if (-not (Test-Path $p)) { throw "Missing $p (run from the repo's restorer folder)" }
}
New-Item -ItemType Directory -Force -Path $driversSrc | Out-Null

# ── Optional: extract Dell Update Packages ────────────────────────────────
if ($ExtractDups) {
    if (-not (Test-Path $dupsSrc)) { throw "No $dupsSrc folder. Create Dell\Downloads\<Model>\ and drop the .exe files there." }
    $manual = @()
    foreach ($modelDir in Get-ChildItem -Directory $dupsSrc) {
        foreach ($exe in Get-ChildItem -Path $modelDir.FullName -Filter *.exe) {
            $dest = Join-Path $driversSrc "$($modelDir.Name)\$($exe.BaseName)"
            if ((Test-Path $dest) -and (Get-ChildItem $dest -Recurse -Filter *.inf -ErrorAction SilentlyContinue | Measure-Object).Count -gt 0) {
                Say "skip (already extracted): $($modelDir.Name)\$($exe.Name)"; continue
            }
            New-Item -ItemType Directory -Force -Path $dest | Out-Null
            Say "extracting $($modelDir.Name)\$($exe.Name)"
            $p = Start-Process -FilePath $exe.FullName -ArgumentList "/s","/e=`"$dest`"" -Wait -PassThru -WindowStyle Hidden
            $inf = (Get-ChildItem $dest -Recurse -Filter *.inf -ErrorAction SilentlyContinue | Measure-Object).Count
            if ($inf -eq 0) {
                # Some packages use /extract, some are plain self-extractors.
                $p = Start-Process -FilePath $exe.FullName -ArgumentList "/extract","`"$dest`"","/s" -Wait -PassThru -WindowStyle Hidden -ErrorAction SilentlyContinue
                $inf = (Get-ChildItem $dest -Recurse -Filter *.inf -ErrorAction SilentlyContinue | Measure-Object).Count
            }
            if ($inf -eq 0) { $manual += "$($modelDir.Name)\$($exe.Name)"; Remove-Item $dest -Recurse -Force -ErrorAction SilentlyContinue }
            else { Say "   $inf .inf files" }
        }
    }
    if ($manual) {
        Write-Warning "These packages did not extract with /s /e=. Open each with 7-Zip and copy the folder containing the .inf files into Dell\Drivers\<Model>\:"
        $manual | ForEach-Object { Write-Warning "   $_" }
    }
}
if ($ExtractOnly) {
    Get-ChildItem -Directory $driversSrc -ErrorAction SilentlyContinue | ForEach-Object {
        Say ("{0}: {1} .inf" -f $_.Name, (Get-ChildItem $_.FullName -Recurse -Filter *.inf -ErrorAction SilentlyContinue | Measure-Object).Count)
    }
    Say "Extract-only run complete."
    return
}

# ── Find sticks ───────────────────────────────────────────────────────────
$targets = @()
if ($Drive) { $targets = @($Drive.TrimEnd("\").TrimEnd(":") + ":") }
else {
    Get-Volume | Where-Object { $_.FileSystemLabel -eq "ESD-ISO" -and $_.DriveType -eq "Removable" -and $_.DriveLetter } |
        ForEach-Object { $targets += "$($_.DriveLetter):" }
}
if (-not $targets) { throw "No removable volume labelled ESD-ISO found. Flash the stick with Rufus first." }
Say "Restorer sticks: $($targets -join ', ')"

$driverSummary = Get-ChildItem -Directory $driversSrc -ErrorAction SilentlyContinue | ForEach-Object {
    "$($_.Name)=$((Get-ChildItem $_.FullName -Recurse -Filter *.inf -ErrorAction SilentlyContinue | Measure-Object).Count) inf"
}
Say "Driver folders: $($driverSummary -join '; ')"
if (-not $driverSummary) { Write-Warning "Dell\Drivers is empty. Wi-Fi will only work after the buyer plugs in Ethernet. See Dell\Drivers\README.md." }

# ── Build each stick ──────────────────────────────────────────────────────
foreach ($t in $targets) {
    Say "=== $t ==="
    if (-not (Test-Path "$t\sources\install.wim") -and -not (Test-Path "$t\sources\install.esd")) {
        Write-Warning "$t has no sources\install.wim or install.esd. Not a Windows install stick. Skipping."; continue
    }
    if ((Test-Path "$t\sources\install.esd.bak") -or (Test-Path "$t\drivers")) {
        Write-Warning "$t still carries the old injected-image layout (install.esd.bak / \drivers). It will work, but re-flash from the stock ISO so Setup can match the edition to the OEM key."
    }
    Copy-Item $xmlSrc "$t\autounattend.xml" -Force
    Say "  autounattend.xml copied"
    & robocopy $scriptsSrc "$t\Dell\Scripts" /MIR /NFL /NDL /NJH /NJS /R:2 /W:2 | Out-Null
    Say "  Dell\Scripts mirrored"
    & robocopy $driversSrc "$t\Dell\Drivers" /MIR /NFL /NDL /NJH /NJS /R:2 /W:2 /XF README.md | Out-Null
    Say "  Dell\Drivers mirrored"
    New-Item -ItemType Directory -Force -Path "$t\Dell\Reports" | Out-Null
    foreach ($stale in @("$t\drivers", "$t\sources\install.esd.bak", "$t\sources\install.wim.bak")) {
        if (Test-Path $stale) { Remove-Item $stale -Recurse -Force -ErrorAction SilentlyContinue; Say "  removed stale $stale" }
    }
    # verify
    $ok = (Test-Path "$t\autounattend.xml") -and (Test-Path "$t\Dell\Scripts\stage.cmd") -and (Test-Path "$t\Dell\Scripts\stage.ps1")
    $free = [math]::Round((Get-Volume -DriveLetter $t.TrimEnd(':')).SizeRemaining / 1GB, 1)
    $inf = (Get-ChildItem "$t\Dell\Drivers" -Recurse -Filter *.inf -ErrorAction SilentlyContinue | Measure-Object).Count
    Say ("  verify: files={0}  drivers={1} inf  free={2} GB" -f $(if ($ok) {'ok'} else {'MISSING'}), $inf, $free)
}
Say "Done. Eject the sticks safely."
