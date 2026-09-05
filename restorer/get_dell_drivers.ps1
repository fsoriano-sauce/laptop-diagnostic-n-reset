<#
.SYNOPSIS
  Download the driver packages for the fleet models straight from Dell's
  public update catalog (the same feed Dell Command | Update reads).

.DESCRIPTION
  1. Fetches https://downloads.dell.com/catalog/CatalogPC.cab and expands
     CatalogPC.xml (cached for 7 days in restorer\Dell\Catalog\).
  2. For each model name, selects driver packages (ComponentType DRVR) that
     list that model and Windows 11 (falls back to Windows 10), in the
     requested categories, newest release per component name.
  3. Downloads them to restorer\Dell\Downloads\<Model>\ with MD5 check.
     -IncludeBios also downloads the latest BIOS to restorer\Dell\BIOS\<Model>\
     for the F12 "BIOS Flash Update" step.

  Afterwards run:  .\build_restorer.ps1 -ExtractDups -ExtractOnly

.PARAMETER Models
  Model display names as they appear in the catalog. Partial match, case-insensitive.
.PARAMETER Categories
  Catalog category display names (prefix match). Default covers what a retail
  first boot needs; Video is large (NVIDIA ~1 GB per model) but worth it.
.PARAMETER ListOnly
  Print the selection and sizes, download nothing.

.EXAMPLE
  .\get_dell_drivers.ps1 -ListOnly
  .\get_dell_drivers.ps1
  .\get_dell_drivers.ps1 -Models "Vostro 7620" -Categories Network,Audio -IncludeBios
#>
[CmdletBinding()]
param(
    [string[]]$Models = @("Vostro 7620", "Vostro 15 7510", "Vostro 7500"),
    [string[]]$Categories = @("Network", "Audio", "Chipset", "Security", "Video", "Mouse", "Input", "Serial ATA", "Storage"),
    [switch]$ListOnly,
    [switch]$IncludeBios
)
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$root     = $PSScriptRoot
$catDir   = Join-Path $root "Dell\Catalog"
$dlRoot   = Join-Path $root "Dell\Downloads"
$biosRoot = Join-Path $root "Dell\BIOS"
New-Item -ItemType Directory -Force -Path $catDir, $dlRoot | Out-Null

function Say($m) { Write-Host "[$(Get-Date -Format HH:mm:ss)] $m" }
function T($n) {
    # Catalog text lives in CDATA; PowerShell's XML adapter exposes it inconsistently.
    if ($null -eq $n) { return "" }
    if ($n -is [string]) { return $n.Trim() }
    if ($n.PSObject.Properties["#cdata-section"]) { return ([string]$n.'#cdata-section').Trim() }
    if ($n.PSObject.Properties["InnerText"]) { return ([string]$n.InnerText).Trim() }
    return ([string]$n).Trim()
}
function Safe([string]$s) { ($s -replace '[\\/:*?"<>|]', "_").Trim() }

# ── 1. Catalog ────────────────────────────────────────────────────────────
$cab = Join-Path $catDir "CatalogPC.cab"
$xml = Join-Path $catDir "CatalogPC.xml"
if (-not (Test-Path $xml) -or ((Get-Item $xml).LastWriteTime -lt (Get-Date).AddDays(-7))) {
    Say "downloading CatalogPC.cab"
    Invoke-WebRequest -Uri "https://downloads.dell.com/catalog/CatalogPC.cab" -OutFile $cab -UseBasicParsing
    if (Test-Path $xml) { Remove-Item $xml -Force }
    & expand.exe $cab $xml | Out-Null
    if (-not (Test-Path $xml)) { throw "expand.exe did not produce CatalogPC.xml" }
}
Say "parsing catalog ($([math]::Round((Get-Item $xml).Length/1MB)) MB, this takes a minute)"
$doc = New-Object System.Xml.XmlDocument
$doc.Load($xml)
$base = $doc.Manifest.baseLocation
if (-not $base) { $base = "downloads.dell.com" }
$all = @($doc.Manifest.SoftwareComponent)
Say "catalog has $($all.Count) components"

# ── 2. Select ─────────────────────────────────────────────────────────────
function Get-Selection($model, $type) {
    $hits = foreach ($c in $all) {
        if ((T $c.ComponentType.value) -ne $type -and $c.ComponentType.value -ne $type) { continue }
        $modelMatch = $false
        foreach ($b in @($c.SupportedSystems.Brand)) {
            foreach ($m in @($b.Model)) {
                if ((T $m.Display) -like "*$model*") { $modelMatch = $true; break }
            }
            if ($modelMatch) { break }
        }
        if (-not $modelMatch) { continue }
        $osCodes = @(@($c.SupportedOperatingSystems.OperatingSystem) | ForEach-Object { $_.osCode })
        $osRank = if ($osCodes -contains "W11") { 2 } elseif ($osCodes -contains "W10") { 1 } else { 0 }
        if ($type -eq "DRVR" -and $osRank -eq 0) { continue }
        $cat = T $c.Category.Display
        if ($type -eq "DRVR") {
            $catOk = $false
            foreach ($want in $Categories) { if ($cat -like "$want*") { $catOk = $true; break } }
            if (-not $catOk) { continue }
        }
        $when = $null
        try { $when = [datetime]$c.dateTime } catch { try { $when = [datetime]$c.releaseDate } catch { $when = [datetime]"2000-01-01" } }
        [pscustomobject]@{
            Name     = T $c.Name.Display
            Category = $cat
            Version  = $c.vendorVersion
            Date     = $when
            OsRank   = $osRank
            SizeMB   = [math]::Round([double]$c.size / 1MB, 1)
            Path     = $c.path
            MD5      = $c.hashMD5
            File     = Split-Path $c.path -Leaf
        }
    }
    # newest per component name, preferring Windows 11 packages
    $hits | Group-Object Name | ForEach-Object {
        $_.Group | Sort-Object OsRank, Date -Descending | Select-Object -First 1
    } | Sort-Object Category, Name
}

# ── 3. Download ───────────────────────────────────────────────────────────
function Fetch($item, $dir) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $dest = Join-Path $dir $item.File
    $url  = "https://$base/$($item.Path)".Replace("//", "/").Replace("https:/", "https://")
    if (Test-Path $dest) {
        if ($item.MD5 -and ((Get-FileHash $dest -Algorithm MD5).Hash -ieq $item.MD5)) { Say "  ok (cached) $($item.File)"; return }
        Remove-Item $dest -Force
    }
    Say "  get $($item.File)  $($item.SizeMB) MB"
    Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
    if ($item.MD5 -and ((Get-FileHash $dest -Algorithm MD5).Hash -ine $item.MD5)) {
        Remove-Item $dest -Force
        throw "MD5 mismatch for $($item.File) from $url"
    }
}

$manifest = @()
foreach ($model in $Models) {
    Say "=== $model ==="
    $sel = @(Get-Selection $model "DRVR")
    if (-not $sel) { Write-Warning "no driver packages matched '$model'. Check the model name against the catalog (e.g. search CatalogPC.xml for '7620')."; continue }
    $sel | Format-Table Category, Name, Version, @{n="Date";e={$_.Date.ToString("yyyy-MM-dd")}}, SizeMB, File -AutoSize | Out-String -Width 200 | Write-Host
    Say ("{0} packages, {1} MB total" -f $sel.Count, [math]::Round(($sel | Measure-Object SizeMB -Sum).Sum))
    $bios = @()
    if ($IncludeBios) {
        $bios = @(Get-Selection $model "BIOS" | Sort-Object Date -Descending | Select-Object -First 1)
        if ($bios) { Say ("BIOS: {0} {1} ({2:yyyy-MM-dd}) {3}" -f $bios[0].Name, $bios[0].Version, $bios[0].Date, $bios[0].File) }
    }
    if ($ListOnly) { continue }
    $dir = Join-Path $dlRoot (Safe $model)
    foreach ($item in $sel) { Fetch $item $dir; $manifest += [pscustomobject]@{ Model=$model; Kind="driver"; Category=$item.Category; Name=$item.Name; Version=$item.Version; File=$item.File } }
    foreach ($item in $bios) { Fetch $item (Join-Path $biosRoot (Safe $model)); $manifest += [pscustomobject]@{ Model=$model; Kind="bios"; Category="BIOS"; Name=$item.Name; Version=$item.Version; File=$item.File } }
}
if (-not $ListOnly -and $manifest) {
    $manifest | Export-Csv (Join-Path $dlRoot "manifest.csv") -NoTypeInformation
    Say "manifest written to Dell\Downloads\manifest.csv"
    Say "next:  .\build_restorer.ps1 -ExtractDups -ExtractOnly"
}
