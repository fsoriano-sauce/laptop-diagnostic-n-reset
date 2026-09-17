#!/bin/bash
# mac_audit.sh — read-only spec report for a Mac that is being prepared for sale.
#
# Run it ON THE MAC BEING SOLD (no admin rights needed, nothing is changed):
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/fsoriano-sauce/laptop-diagnostic-n-reset/v3-line-toolkit/auditor/mac_audit.sh)
#
# It writes two files on the Desktop, mac-audit-<serial>.txt and .json, holding
# model, chip, memory, storage, macOS version, battery cycle count / condition /
# maximum capacity, display, Activation Lock status (Apple silicon and T2 Macs),
# MDM enrollment and FileVault state. AirDrop both files to the listing Mac.
# Account names, e-mail addresses and Wi-Fi network names are left out.
set -u

serial=$(system_profiler SPHardwareDataType 2>/dev/null | awk -F': ' '/Serial Number/ {print $2; exit}')
out="$HOME/Desktop/mac-audit-${serial:-unknown}"

# Structured copy for the listing Mac (SPSoftwareDataType is skipped: it carries the user name).
system_profiler -json SPHardwareDataType SPMemoryDataType SPStorageDataType SPNVMeDataType \
    SPSerialATADataType SPPowerDataType SPDisplaysDataType > "$out.json" 2>/dev/null

{
  echo "mac_audit $(date '+%Y-%m-%d %H:%M %Z')"
  echo "== macOS =="
  sw_vers
  echo
  system_profiler SPHardwareDataType SPMemoryDataType SPStorageDataType SPPowerDataType SPDisplaysDataType 2>/dev/null \
    | grep -vE 'User Name|Computer Name|Host Name'
  echo "== MDM / device enrollment =="
  profiles status -type enrollment 2>&1
  echo
  echo "== Apple Account signed in =="
  if defaults read MobileMeAccounts Accounts >/dev/null 2>&1; then
    echo "yes (sign out and turn off Find My before erasing)"
  else
    echo "none found"
  fi
  echo
  echo "== FileVault =="
  fdesetup status 2>&1
} > "$out.txt" 2>&1

echo "Written:"
echo "  $out.txt"
echo "  $out.json"
echo "AirDrop both files to the listing Mac."
