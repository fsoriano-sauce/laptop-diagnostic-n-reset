# CLAUDE.md — project rules for any Claude Code session

This repo prepares batches of used Dell laptops (Vostro 7620 / 15 7510 / 7500
so far) for resale: two USB sticks (Auditor on SystemRescue, Restorer on
Windows 11) plus a small eBay listing pipeline. Read `README.md` first; it
describes the per-unit flow and the design rules.

## Hard safety rules

- **Never run `auditor/audit.py` on a workstation.** It secure-erases the largest internal disk it finds. It refuses to erase unless it is running from the SystemRescue live USB (`/run/archiso` exists), and it must stay that way. Only pure functions from it may be imported for tests.
- **Never write to any drive other than a removable volume labelled `ESD-ISO`** (Restorer) or the SystemRescue stick (Auditor). `build_restorer.ps1` only touches `ESD-ISO` volumes; keep it so. Ask before formatting anything.
- **Never commit driver payloads.** `restorer/Dell/Drivers/`, `Downloads/`, `BIOS/`, `Catalog/`, `Reports/` are git-ignored on purpose (multi-GB, redistributable only from Dell).
- **Never store the full OEM Windows key.** The auditor keeps only presence and the last five characters. Keep it so.
- The repo is public. Service tags are already public via listings; do not add anything more sensitive.

## Where things live

| Area | Path | Runs on |
|---|---|---|
| Auditor script | `auditor/audit.py` (+ `auditor/autorun`) | SystemRescue on the laptop |
| Audit evidence | `auditor/audits/<TAG>.json`, `<TAG>/raw/` | copied from the USB |
| Hand-entered state | `auditor/inventory.csv` | any |
| Listing CSV build | `auditor/build_master_csv.py` → `audit_master_local.csv` | any (Python 3) |
| eBay generator | `auditor/generate_ebay_drafts_v2.py`, `verify_listings.py` | any (Python 3) |
| Restorer answer file | `restorer/autounattend.xml` | Windows Setup |
| Restorer specialize scripts | `restorer/Dell/Scripts/stage.cmd`, `stage.ps1` | Windows Setup (SYSTEM) |
| Restorer stick build | `restorer/build_restorer.ps1` | Windows, admin |
| Driver download | `restorer/get_dell_drivers.ps1` | Windows |
| Windows build + test guide | `restorer/BUILD_ON_WINDOWS.md` | Windows |

## Platform split

- **macOS/Linux session**: Python work, README, updating `audit.py` on the Auditor stick (FAT32), building the master CSV and listings.
- **Windows session** (Surface, Precision, any PC with a USB-A port): everything under `restorer/`. Follow `restorer/BUILD_ON_WINDOWS.md`. The PowerShell and batch files there were authored on macOS and first run on Windows; expect to fix small issues, fix them minimally, commit, push.

## Conventions

- Line endings are enforced by `.gitattributes`: LF for anything that runs on SystemRescue, CRLF for `.cmd`/`.ps1`. Do not fight it.
- `audit_master_local.csv` is generated. Edit `inventory.csv` or the JSON, then rebuild.
- Legacy v2 audit rows are frozen in `auditor/legacy/`. Do not edit them; re-audit the unit instead.
- Do not add lookup tables that assert hardware specs. If a value cannot be measured it is `null`.
- Commit messages: imperative, one line of what and one of why.
