# Golden-unit run: one laptop per model, the real sequence, with a checklist

Do this once before production. Same steps as production; the only extras
are step 5 (finish Windows and check it) and step 6 (restore again).

Units: JV25GS3 (Vostro 7620), H1N3R93 (Vostro 7500), any Vostro 15 7510.
Sticks: the Auditor (RESCUE1302, **DRYRUN file removed**) and one Restorer (ESD-ISO).
Rule: while one unit installs, audit the next. Plan ~2 hours for three.

## Per unit

| # | Step | Attended | Pass looks like |
|---|---|---|---|
| 1 | F2: Secure Boot **Off**, SATA/NVMe Operation **AHCI/NVMe**, boot order **USB first**. Save. | 1 min | lands in the auditor, not Windows |
| 2 | Auditor: colour screens + screen grade, keyboard map, speaker prompt, fingerprint, body grade, charger, colour. Then it scans, erases, powers off. | 2–3 min, then leave | summary shows `Erase nvme_format_ses1 blank:True`, no ⚠ lines except battery/wear if real |
| 3 | Swap to the Restorer. Power on, F2, Secure Boot **On**, save. Leave. | 1 min | ~20 min later: "Is this the right country or region?" |
| 4 | Pull the Restorer stick. Read `Dell\Reports\<TAG>.txt` (Mac can read the stick; Surface too). | 2 min | `edition` matches the OEM key · `OEM key: present` · `Secure Boot: ON` · `Devices with problems: (none)` · Wi-Fi listed under Key devices |
| 5 | Finish setup with a throwaway Microsoft account, then check: | 10 min | |
|   | Settings → System → Activation | | **Active** |
|   | Wi-Fi | | networks listed, connects |
|   | Bluetooth | | toggles on, scans |
|   | Windows Hello | | fingerprint enrolment offered and works |
|   | Camera app | | live video |
|   | Speakers | | sound from both sides (the only speaker test we have on 11th/12th gen) |
|   | Device Manager | | NVIDIA GPU present, no yellow marks |
| 6 | Restorer again to wipe the throwaway account. Leave. | 1 min | clean region screen; unit is sale-ready |
| 7 | Bring the Auditor stick to the Mac; the unit's JSON gets folded into the repo. | | |

## If something fails

| Symptom | Where to look | Likely fix |
|---|---|---|
| Auditor stops with a red STOP box | its message | BIOS still RAID/VMD: set AHCI and reboot |
| Erase line says `NOT erased` | `audits/<TAG>.json` → `erase.error` | bring the stick to the Mac |
| Setup cannot see the disk | | AHCI not set; the auditor would have refused, so check the BIOS |
| Setup asks for a product key | | no OEM key in firmware; the audit's `oem_key_present` says so |
| No `Dell\Reports\<TAG>.txt` | `Dell\Reports\_stage-cmd.log` | stick not found by letter; try another USB port |
| A device listed under "Devices with problems" | that line | add the matching Dell package to `Dell\Drivers\<Model>\`, rebuild the stick |
| No speakers / no camera in Windows | Device Manager | same: missing driver |

When all three pass, delete nothing and change nothing: that is production.
