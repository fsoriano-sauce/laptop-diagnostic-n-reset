# ============================================================
# Windows 11 Restorer USB Upgrade Script
# ============================================================
# Upgrades existing Windows 10 Restorer USBs to Windows 11.
#
# Prerequisites:
#   1. Download Windows 11 ISO via Media Creation Tool
#      https://www.microsoft.com/en-us/software-download/windows11
#      Save to C:\Temp\Win11.iso
#   2. Dell drivers already extracted at C:\Temp\DellDrivers\Extracted
#   3. Run this script as Administrator
#
# What this script does:
#   - Mounts the Win 11 ISO
#   - Exports Win 11 Pro image from install.esd to install.wim
#   - Injects Intel RST/VMD drivers into boot.wim + install.wim
#   - Copies the updated images + autounattend.xml to all 3 USBs
# ============================================================

#Requires -RunAsAdministrator
$ErrorActionPreference = "Stop"

# ─── Configuration ─────────────────────────────────────────────
$Win11ISO     = "C:\Temp\Win11.iso"
$DriverPath   = "C:\Temp\DellDrivers\Extracted"
$MountDir     = "C:\Temp\WinMount"
$TempDir      = "C:\Temp\Win11Prep"
$LogFile      = "C:\Temp\win11_upgrade.log"
$RepoRoot     = "$PSScriptRoot\.."
$AutounattendSrc = "$RepoRoot\restorer\autounattend-win11.xml"

# USB drives to update (ESD-ISO labeled Restorer drives)
$USBDrives = @()
Get-Volume | Where-Object { $_.FileSystemLabel -eq "ESD-ISO" -and $_.DriveType -eq "Removable" } | ForEach-Object {
    if ($_.DriveLetter) { $USBDrives += "$($_.DriveLetter):" }
}

function Log($msg) {
    $ts = Get-Date -Format "HH:mm:ss"
    $line = "[$ts] $msg"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line
}

# ─── Preflight Checks ─────────────────────────────────────────
Log "============================================"
Log "  WINDOWS 11 RESTORER USB UPGRADE"
Log "============================================"

if (-not (Test-Path $Win11ISO)) {
    Log "ERROR: Windows 11 ISO not found at $Win11ISO"
    Log ""
    Log "Please download it first:"
    Log "  1. Go to https://www.microsoft.com/en-us/software-download/windows11"
    Log "  2. Under 'Download Windows 11 Disk Image (ISO)', select 'Windows 11 (multi-edition ISO)'"
    Log "  3. Click Download, select English, and save to C:\Temp\Win11.iso"
    Read-Host "Press ENTER to exit"
    exit 1
}

if (-not (Test-Path $DriverPath)) {
    Log "ERROR: Dell drivers not found at $DriverPath"
    Read-Host "Press ENTER to exit"
    exit 1
}

if (-not (Test-Path $AutounattendSrc)) {
    Log "ERROR: autounattend-win11.xml not found at $AutounattendSrc"
    Read-Host "Press ENTER to exit"
    exit 1
}

if ($USBDrives.Count -eq 0) {
    Log "ERROR: No ESD-ISO USB drives detected. Plug in Restorer USBs."
    Read-Host "Press ENTER to exit"
    exit 1
}

Log "Found $($USBDrives.Count) Restorer USB(s): $($USBDrives -join ', ')"
Log "Win 11 ISO: $Win11ISO"
Log "Drivers: $DriverPath ($(Get-ChildItem $DriverPath -Recurse -Filter '*.inf' | Measure-Object | Select-Object -ExpandProperty Count) .inf files)"
Log ""

$confirm = Read-Host "This will REPLACE Windows 10 images on ALL $($USBDrives.Count) USBs. Continue? [Y/N]"
if ($confirm -ne "Y") { Log "Aborted."; exit 0 }

# ─── Prepare directories ──────────────────────────────────────
if (Test-Path $MountDir) { Remove-Item $MountDir -Recurse -Force }
New-Item -ItemType Directory -Path $MountDir -Force | Out-Null
New-Item -ItemType Directory -Path $TempDir -Force | Out-Null

# ─── Step 1: Mount Win 11 ISO ─────────────────────────────────
Log ""
Log "=== Step 1: Mounting Windows 11 ISO ==="
$isoMount = Mount-DiskImage -ImagePath $Win11ISO -PassThru
$isoDrive = ($isoMount | Get-Volume).DriveLetter + ":"
Log "ISO mounted at $isoDrive"

# Determine if install is .esd or .wim
$installEsd = "$isoDrive\sources\install.esd"
$installWim = "$isoDrive\sources\install.wim"
$isoBootWim = "$isoDrive\sources\boot.wim"

if (Test-Path $installEsd) {
    $sourceInstall = $installEsd
    $sourceType = "ESD"
    Log "Found install.esd - will export Win 11 Pro to WIM"
} elseif (Test-Path $installWim) {
    $sourceInstall = $installWim
    $sourceType = "WIM"
    Log "Found install.wim"
} else {
    Log "ERROR: No install.esd or install.wim found in ISO!"
    Dismount-DiskImage -ImagePath $Win11ISO
    exit 1
}

# ─── Step 2: List available images and find Win 11 Pro ────────
Log ""
Log "=== Step 2: Finding Windows 11 Pro image ==="
$imageInfo = Dism /Get-WimInfo /WimFile:$sourceInstall
Log $imageInfo

# Find the index for Windows 11 Pro
$proIndex = $null
$currentIndex = $null
foreach ($line in ($imageInfo -split "`n")) {
    if ($line -match "Index\s*:\s*(\d+)") {
        $currentIndex = $matches[1]
    }
    if ($line -match "Name\s*:\s*Windows 11 Pro\s*$") {
        $proIndex = $currentIndex
    }
}

if (-not $proIndex) {
    # Try "Windows 11 Pro" with any trailing whitespace
    foreach ($line in ($imageInfo -split "`n")) {
        if ($line -match "Index\s*:\s*(\d+)") {
            $currentIndex = $matches[1]
        }
        if ($line -match "Name\s*:.*Windows 11 Pro") {
            $proIndex = $currentIndex
        }
    }
}

if (-not $proIndex) {
    Log "ERROR: Could not find 'Windows 11 Pro' image in the ISO."
    Log "Available images:"
    Log $imageInfo
    Dismount-DiskImage -ImagePath $Win11ISO
    Read-Host "Press ENTER to exit"
    exit 1
}

Log "Found Windows 11 Pro at Index $proIndex"

# ─── Step 3: Export Win 11 Pro to standalone WIM ──────────────
$preparedInstallWim = "$TempDir\install.wim"
Log ""
Log "=== Step 3: Exporting Win 11 Pro (Index $proIndex) to install.wim ==="
Log "    This takes 5-10 minutes..."

if (Test-Path $preparedInstallWim) { Remove-Item $preparedInstallWim -Force }
Dism /Export-Image /SourceImageFile:$sourceInstall /SourceIndex:$proIndex /DestinationImageFile:$preparedInstallWim /Compress:max
Log "Export complete: $([math]::Round((Get-Item $preparedInstallWim).Length / 1MB)) MB"

# ─── Step 4: Copy boot.wim from ISO ──────────────────────────
$preparedBootWim = "$TempDir\boot.wim"
Log ""
Log "=== Step 4: Copying boot.wim from ISO ==="
Copy-Item $isoBootWim $preparedBootWim -Force
attrib -R $preparedBootWim
Log "boot.wim copied: $([math]::Round((Get-Item $preparedBootWim).Length / 1MB)) MB"

# Dismount ISO - we're done with it
Dismount-DiskImage -ImagePath $Win11ISO
Log "ISO dismounted."

# ─── Step 5: Inject drivers into boot.wim ─────────────────────
Log ""
Log "=== Step 5: Injecting drivers into boot.wim ==="

# Index 1: WinPE
Log "  Mounting boot.wim Index 1 (WinPE)..."
Dism /Mount-Wim /WimFile:$preparedBootWim /index:1 /MountDir:$MountDir
Log "  Injecting drivers..."
Dism /Image:$MountDir /Add-Driver /Driver:$DriverPath /recurse /ForceUnsigned
Log "  Committing..."
Dism /Unmount-Wim /MountDir:$MountDir /Commit
Log "  boot.wim Index 1 DONE"

# Index 2: Windows Setup
Log "  Mounting boot.wim Index 2 (Windows Setup)..."
Dism /Mount-Wim /WimFile:$preparedBootWim /index:2 /MountDir:$MountDir
Log "  Injecting drivers..."
Dism /Image:$MountDir /Add-Driver /Driver:$DriverPath /recurse /ForceUnsigned
Log "  Committing..."
Dism /Unmount-Wim /MountDir:$MountDir /Commit
Log "  boot.wim Index 2 DONE"

# ─── Step 6: Inject drivers into install.wim ──────────────────
Log ""
Log "=== Step 6: Injecting drivers into install.wim (Win 11 Pro) ==="
Log "  This takes 5-10 minutes..."
Dism /Mount-Wim /WimFile:$preparedInstallWim /index:1 /MountDir:$MountDir
Log "  Injecting drivers..."
Dism /Image:$MountDir /Add-Driver /Driver:$DriverPath /recurse /ForceUnsigned
Log "  Committing..."
Dism /Unmount-Wim /MountDir:$MountDir /Commit
Log "  install.wim DONE"

Log ""
Log "Driver injection complete!"
Log "  boot.wim:    $([math]::Round((Get-Item $preparedBootWim).Length / 1MB)) MB"
Log "  install.wim: $([math]::Round((Get-Item $preparedInstallWim).Length / 1MB)) MB"

# ─── Step 7: Deploy to all USBs ──────────────────────────────
Log ""
Log "=== Step 7: Deploying to $($USBDrives.Count) USB drive(s) ==="

foreach ($usb in $USBDrives) {
    Log ""
    Log "  --- Updating $usb ---"

    # Backup old install.wim (if it exists)
    $usbInstallWim = "$usb\sources\install.wim"
    $usbInstallEsd = "$usb\sources\install.esd"
    $usbBootWim = "$usb\sources\boot.wim"

    # Remove old images
    if (Test-Path $usbInstallWim) {
        Log "  Removing old install.wim..."
        Remove-Item $usbInstallWim -Force
    }
    if (Test-Path $usbInstallEsd) {
        Log "  Removing old install.esd..."
        Remove-Item $usbInstallEsd -Force
    }
    if (Test-Path "$usb\sources\install.esd.bak") {
        Remove-Item "$usb\sources\install.esd.bak" -Force
    }

    # Copy new images
    Log "  Copying boot.wim to $usb (~470MB)..."
    attrib -R $usbBootWim 2>$null
    Copy-Item $preparedBootWim $usbBootWim -Force

    Log "  Copying install.wim to $usb (~5GB, this takes a few minutes)..."
    Copy-Item $preparedInstallWim $usbInstallWim -Force

    # Copy autounattend.xml
    Log "  Copying autounattend-win11.xml as autounattend.xml..."
    Copy-Item $AutounattendSrc "$usb\autounattend.xml" -Force

    # Verify
    $bootSize = [math]::Round((Get-Item $usbBootWim).Length / 1MB)
    $installSize = [math]::Round((Get-Item $usbInstallWim).Length / 1MB)
    $hasAutounattend = Test-Path "$usb\autounattend.xml"
    Log "  Verified: boot.wim=${bootSize}MB, install.wim=${installSize}MB, autounattend.xml=$hasAutounattend"
    Log "  --- $usb COMPLETE ---"
}

# ─── Done ─────────────────────────────────────────────────────
Log ""
Log "============================================"
Log "  ALL $($USBDrives.Count) RESTORER USB(s) UPGRADED TO WIN 11"
Log "============================================"
Log ""
Log "Each USB now contains:"
Log "  - Windows 11 Pro install image (with Intel RST/VMD drivers)"
Log "  - Updated autounattend.xml (with BypassNRO for local accounts)"
Log ""
Log "Test by booting a laptop from any Restorer USB (F12 > select ESD-ISO)."
Log "It should install Windows 11 Pro and stop at the OOBE region screen."
Log ""
Log "Log saved to: $LogFile"

Read-Host "Press ENTER to exit"
