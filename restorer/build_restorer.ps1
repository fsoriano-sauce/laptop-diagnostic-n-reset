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
  .\build_restorer.ps1 -ValidateDrivers -ExtractOnly # pre-flight every package on this PC
  .\build_restorer.ps1 -Drive E:
#>
#Requires -RunAsAdministrator
[CmdletBinding()]
param(
    [switch]$ExtractDups,
    [switch]$ExtractOnly,
    [string]$Drive,
    [switch]$AllowSingleEdition,  # build onto a one-edition (injected) image anyway
    [switch]$ValidateDrivers      # stage every package into this PC's driver store (no install), report failures, remove again
)
$ErrorActionPreference = "Stop"
$root      = $PSScriptRoot
$xmlSrc    = Join-Path $root "autounattend.xml"
$scriptsSrc= Join-Path $root "Dell\Scripts"
$driversSrc= Join-Path $root "Dell\Drivers"
$dupsSrc   = Join-Path $root "Dell\Downloads"

function Say($m) { Write-Host "[$(Get-Date -Format HH:mm:ss)] $m" }

function Expand-Stubs([string]$root) {
    # Dell MUP packages ship makecab stubs (nvlddmkm.sy_, nvapi64.dl_, mcu.ex_). Newer
    # NVIDIA packages fail to stage from stubs ('cannot find the file specified'), so
    # restore the originals. expand -r takes the real name from the cab header.
    # Idempotent: a stub is removed only once its expanded twin exists.
    $stubs = @(Get-ChildItem -Path $root -Recurse -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '\.[A-Za-z0-9]{2}_$' })
    if (-not $stubs) { return }
    $n = 0
    foreach ($st in $stubs) {
        & expand.exe -r $st.FullName $st.DirectoryName 2>&1 | Out-Null
        $stem = [IO.Path]::GetFileNameWithoutExtension($st.Name)
        $twin = Get-ChildItem -Path $st.DirectoryName -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -ne $st.Name -and [IO.Path]::GetFileNameWithoutExtension($_.Name) -ieq $stem }
        if ($twin) { Remove-Item $st.FullName -Force -ErrorAction SilentlyContinue; $n++ }
    }
    Say "expanded $n of $($stubs.Count) compressed driver files"
}

function Test-DriverPackages([string]$root) {
    # Pre-flight without a laptop: pnputil /add-driver (no /install) per package into
    # this PC's driver store, then /delete-driver what it added. A package pnputil
    # refuses here will fail on the laptop too.
    $skip = 'Rapid-Storage|Rapid_Storage|RapidStorage|-RST-|_RST_|VMD|iaStor|Optane'
    $failed = @()
    # Stage through a short junction: the repo path plus Dell's package names pushes the Killer
    # Bluetooth INFs past MAX_PATH here (pnputil rc 87), while C:\Dell\Drivers on the laptop is fine.
    $short = Join-Path $env:SystemDrive "_dv"
    if (Test-Path $short) { [IO.Directory]::Delete($short) }
    New-Item -ItemType Junction -Path $short -Target $root | Out-Null
    foreach ($model in Get-ChildItem -Directory $short -ErrorAction SilentlyContinue) {
        foreach ($pkg in Get-ChildItem -Directory $model.FullName -ErrorAction SilentlyContinue) {
            if ($pkg.Name -match $skip) { Say ("  skip  {0}\{1}" -f $model.Name, $pkg.Name); continue }
            $infs = @(Get-ChildItem -Path $pkg.FullName -Recurse -Filter *.inf -ErrorAction SilentlyContinue)
            if (-not $infs) { continue }
            $out = @(& pnputil.exe /add-driver "$($pkg.FullName)\*.inf" /subdirs 2>&1 | ForEach-Object { "$_" })
            $rc = $LASTEXITCODE
            $added = @(); $bad = 0
            foreach ($line in $out) {
                if ($line -match 'Published Name:\s*(oem\d+\.inf)') { $added += $Matches[1] }
                if ($line -match 'Failed to add driver package') { $bad++ }
            }
            $ok = ($bad -eq 0) -and ($rc -in 0, 259)
            Say ("  {0}  {1}\{2}  ({3} inf, {4} staged, {5} failed, rc {6})" -f $(if ($ok) {'ok  '} else {'FAIL'}), $model.Name, $pkg.Name, $infs.Count, $added.Count, $bad, $rc)
            if (-not $ok) {
                $failed += "$($model.Name)\$($pkg.Name)"
                $out | Where-Object { $_ -match 'Adding driver package|Failed' } | ForEach-Object { Write-Host "          $_" }
            }
            foreach ($o in $added) { & pnputil.exe /delete-driver $o /force 2>&1 | Out-Null }
        }
    }
    [IO.Directory]::Delete($short)   # drops the junction only, never its target
    return $failed
}

function Get-WimImageCount([string]$path) {
    # WIM and ESD share the header: "MSWIM" magic, image count as UInt32 at 0x2C.
    try {
        $fs = [IO.File]::OpenRead($path); $b = New-Object byte[] 0x30
        $null = $fs.Read($b, 0, 0x30); $fs.Close()
        if ([Text.Encoding]::ASCII.GetString($b, 0, 5) -ne "MSWIM") { return $null }
        return [BitConverter]::ToUInt32($b, 0x2C)
    } catch { return $null }
}

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
# Expand-Stubs is deliberately NOT run. Dell/NVIDIA stubs (nvlddmkm.sy_) are handled
# natively by Windows driver setup and installed cleanly on three laptops; expanding
# them yields underscore-stripped names (nvlddmkm.sy) that stage on a build PC but are
# unproven during Setup. Keep the packages exactly as Dell extracts them.
if ($ValidateDrivers) {
    Say "validating every driver package against this PC's driver store (no install)..."
    $bad = @(Test-DriverPackages $driversSrc)
    if ($bad) {
        Write-Warning ("{0} package(s) pnputil refuses; they will fail on the laptop too. Re-extract with 7-Zip, then rerun -ValidateDrivers:" -f $bad.Count)
        $bad | ForEach-Object { Write-Warning "   $_" }
        return
    }
    Say "all driver packages stage cleanly"
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
    # A stock ISO flash carries 8+ editions; the April injected image carries exactly one (Pro).
    $img = if (Test-Path "$t\sources\install.wim") { "$t\sources\install.wim" } else { "$t\sources\install.esd" }
    $editions = Get-WimImageCount $img
    if ($editions -eq 1 -and -not $AllowSingleEdition) {
        Write-Warning "$t : $(Split-Path $img -Leaf) holds a SINGLE edition ($([math]::Round((Get-Item $img).Length/1GB,2)) GB, $((Get-Item $img).LastWriteTime.ToString('yyyy-MM-dd'))). This stick was not re-flashed from the stock ISO; Setup would install that one edition regardless of the OEM key. Re-flash with Rufus (BUILD_ON_WINDOWS.md section 4) and rerun. Use -AllowSingleEdition to build anyway."
        continue
    }
    if ($editions) { Say "  install image: $editions edition(s) in $(Split-Path $img -Leaf)" }
    Copy-Item $xmlSrc "$t\autounattend.xml" -Force
    Say "  autounattend.xml copied"
    & robocopy $scriptsSrc "$t\Dell\Scripts" /MIR /NFL /NDL /NJH /NJS /R:2 /W:2 | Out-Null
    Say "  Dell\Scripts mirrored"
    & robocopy $driversSrc "$t\Dell\Drivers" /MIR /NFL /NDL /NJH /NJS /R:2 /W:2 /XF README.md | Out-Null
    Say "  Dell\Drivers mirrored"
    New-Item -ItemType Directory -Force -Path "$t\Dell\Reports" | Out-Null
    foreach ($stale in @("$t\drivers", "$t\sources\install.esd.bak", "$t\sources\install.wim.bak", "$t\autounattend.xml.bak", "$t\`$WinPEDriver`$")) {
        if (Test-Path $stale) { Remove-Item $stale -Recurse -Force -ErrorAction SilentlyContinue; Say "  removed stale $stale" }
    }
    # verify
    $ok = (Test-Path "$t\autounattend.xml") -and (Test-Path "$t\Dell\Scripts\stage.cmd") -and (Test-Path "$t\Dell\Scripts\stage.ps1")
    $free = [math]::Round((Get-Volume -DriveLetter $t.TrimEnd(':')).SizeRemaining / 1GB, 1)
    $inf = (Get-ChildItem "$t\Dell\Drivers" -Recurse -Filter *.inf -ErrorAction SilentlyContinue | Measure-Object).Count
    Say ("  verify: files={0}  editions={1}  drivers={2} inf  free={3} GB" -f $(if ($ok) {'ok'} else {'MISSING'}), $editions, $inf, $free)
}
Say "Done. Eject the sticks safely."
