#!/bin/bash
# mac_audit.sh — read-only spec report for a Mac that is being prepared for sale.
#
# Run it ON THE MAC BEING SOLD, before it is erased (no admin rights needed).
# Eject external drives and unplug external displays first, then in Terminal:
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/fsoriano-sauce/laptop-diagnostic-n-reset/mac-audit-v1/auditor/mac_audit.sh)
#
# It writes two report files to the Desktop (mac-audit-<serial>.txt plus .json,
# or .spx on macOS older than 10.15) and changes no settings. They hold model,
# chip, memory, storage, macOS version, battery cycle count / condition /
# capacity, display, Activation Lock status (Apple silicon and T2 Macs only),
# MDM enrollment, whether an Apple Account is signed in, and FileVault state.
# AirDrop both files to the listing Mac, then delete them.
#
# Privacy: the data types are chosen so that no user name, e-mail address,
# computer name, Wi-Fi network or MAC address is collected. The files do carry
# the serial number, hardware UUIDs and the SSD serial, so they are PRIVATE:
# never commit them (mac-audit-* is git-ignored); publish only a summary.

main() {
  set -u
  local serial dir out types al n

  # ioreg is not localized, unlike system_profiler's text output.
  serial=$(ioreg -rd1 -c IOPlatformExpertDevice | awk -F'"' '/IOPlatformSerialNumber/ {print $4; exit}')

  # macOS 10.15+ asks before Terminal may write to the Desktop; fall back to the home folder.
  dir="$HOME/Desktop"
  if ( : > "$dir/.mac_audit_probe" ) 2>/dev/null; then rm -f "$dir/.mac_audit_probe"; else dir="$HOME"; fi
  out="$dir/mac-audit-${serial:-unknown}"

  types="SPHardwareDataType SPiBridgeDataType SPMemoryDataType SPStorageDataType SPNVMeDataType SPSerialATADataType SPPowerDataType SPDisplaysDataType"

  # Structured copy for the listing Mac (keys are not localized). -json needs macOS 10.15.
  system_profiler -json $types > "$out.json" 2>/dev/null
  if [ ! -s "$out.json" ]; then
    rm -f "$out.json"
    system_profiler -xml $types > "$out.spx" 2>/dev/null
  fi

  {
    echo "mac_audit $(date '+%Y-%m-%d %H:%M')  (labels below follow this Mac's language)"
    echo "== macOS =="
    sw_vers
    echo
    system_profiler $types 2>/dev/null \
      | grep -vE 'Hardware UUID|Provisioning UDID|Volume UUID|User Name|Computer Name|Host Name' \
      | sed -E 's#(Mount Point: ).*#\1(hidden)#'
    echo "== Battery raw (ioreg) =="
    echo "Intel: health % = MaxCapacity * 100 / DesignCapacity (both mAh)."
    echo "Apple silicon: MaxCapacity is already a %, AppleRawMaxCapacity is the mAh figure."
    ioreg -rn AppleSmartBattery | grep -E '"(CycleCount|DesignCapacity|MaxCapacity|AppleRawMaxCapacity|NominalChargeCapacity|DesignCycleCount9C)" =' \
      || echo "no battery found"
    echo
    echo "== Activation Lock =="
    al=$(system_profiler SPHardwareDataType 2>/dev/null | grep -i 'Activation Lock')
    echo "${al:-not reported: Intel Mac without a T2 chip, or macOS older than 10.15. Activation Lock does not apply, but Find My can still be on; see the Apple Account section.}"
    echo
    echo "== MDM / device enrollment =="
    profiles status -type enrollment 2>&1 | sed -E 's#(MDM server: ).*#\1present (address hidden)#'
    echo "Note: No here does not rule out an Apple Business Manager assignment. Watch for a"
    echo "Remote Management screen in Setup Assistant after the erase."
    echo
    echo "== Apple Account signed in (this user only; other users on this Mac are not checked) =="
    n=$(defaults read MobileMeAccounts Accounts 2>/dev/null | grep -c 'AccountID')
    if [ "${n:-0}" -gt 0 ]; then
      echo "yes (sign out and turn off Find My before erasing)"
    else
      echo "none found for this user"
    fi
    echo "local user accounts on this Mac: $(dscl . list /Users UniqueID 2>/dev/null | awk '$2>=501' | wc -l | tr -d ' ')"
    echo
    echo "== FileVault =="
    fdesetup status 2>&1
  } > "$out.txt" 2>&1

  if [ -s "$out.txt" ]; then
    echo "Written:"
    for f in "$out.txt" "$out.json" "$out.spx"; do [ -s "$f" ] && echo "  $f"; done
    echo "AirDrop these files to the listing Mac, then delete them."
    open -R "$out.txt" 2>/dev/null
  else
    echo "Could not write the report. If macOS asked whether Terminal may access the"
    echo "Desktop folder, click OK and run the command again."
  fi
}

main "$@"
