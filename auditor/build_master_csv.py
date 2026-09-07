#!/usr/bin/env python3
"""
build_master_csv.py — merge audit evidence into the listing-ready CSV
=====================================================================

Inputs (all relative to this file):
    audits/<TAG>.json          measured facts written by audit.py v3 (copy the
                               audits/ folder from the Auditor USB into here)
    inventory.csv              hand-entered per-unit state: cosmetic grades,
                               colour, charger, status, sale price, notes,
                               list_price (asking price; blank = generator estimate)
    legacy/audit_master_v2.csv rows for units audited before v3 (frozen)

Output:
    audit_master_local.csv     what generate_ebay_drafts_v2.py reads.
                               Legacy columns first (unchanged names), new
                               evidence columns appended after them.

Rules: a v3 JSON beats a legacy row for the same service tag; inventory.csv
supplies grades and business state for every unit; derived values
(recommendation) are computed here, never stored in the audit.

    python3 auditor/build_master_csv.py            # writes the CSV
    python3 auditor/build_master_csv.py --check    # report only, no write
"""

import argparse
import csv
import glob
import json
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
AUDITS_DIR = os.path.join(HERE, "audits")
INVENTORY = os.path.join(HERE, "inventory.csv")
LEGACY = os.path.join(HERE, "legacy", "audit_master_v2.csv")
OUTPUT = os.path.join(HERE, "audit_master_local.csv")

LEGACY_COLUMNS = [
    "timestamp", "service_tag", "model", "cpu", "cores", "ram_gb", "ram_type",
    "storage_type", "storage_gb", "smart_status", "battery_health_pct",
    "battery_charge_pct", "battery_cycles", "gpu", "resolution",
    "resolution_class", "screen_size_in", "touchscreen", "fingerprint_reader",
    "backlit_keyboard", "wifi_standard", "bluetooth", "webcam", "screen_grade",
    "chassis_grade", "color", "charger", "recommendation", "status",
    "sale_price", "sale_date", "notes",
]
NEW_COLUMNS = [
    "audit_version", "express_service_code", "sku", "bios_version", "cpu_cores_physical",
    "ram_config", "ssd_model", "ssd_wear_pct", "ssd_power_on_hours", "ssd_data_written_tb",
    "battery_design_wh", "battery_full_wh", "display_aspect", "wifi_card",
    "oem_key_present", "test_display", "test_keyboard", "test_speaker",
    "erase_method", "erase_verified", "condition_notes", "warnings", "list_price", "photo_notes",
]
INVENTORY_COLUMNS = ["screen_grade", "chassis_grade", "color", "charger",
                     "status", "sale_price", "sale_date", "notes", "list_price", "photo_notes"]


def yn(v):
    if v in (True, "yes", "Yes", "true"):
        return "Yes"
    if v in (False, "no", "No", "false"):
        return "No"
    return "N/A"


def na(v):
    return "N/A" if v is None or v == "" else v


def recommendation(row):
    """Human hint only. Pricing lives in the listing generator."""
    try:
        batt = int(row.get("battery_health_pct") or 0)
    except ValueError:
        batt = 0
    if row.get("smart_status") == "FAILED" or "C" in (row.get("screen_grade", ""), row.get("chassis_grade", "")):
        return "PARTS/REPAIR"
    has_gpu = row.get("gpu") not in ("", "None", None)
    if batt and batt < 60:
        return "HIGH VALUE — BAD BATTERY (Discount)" if has_gpu else "Bad Battery (Discount)"
    return "HIGH VALUE (Gaming/Creator)" if has_gpu else "Standard Resale"


def row_from_json(rec):
    i, c, m, s, b, d, g, f, l = (rec.get(k) or {} for k in
                                 ("identity", "cpu", "memory", "storage", "battery",
                                  "display", "gpu", "features", "license"))
    t, e = rec.get("tests") or {}, rec.get("erase") or {}
    gr = rec.get("grades") or {}
    try:
        ts = datetime.fromisoformat(rec["audited_at"]).strftime("%Y-%m-%d %H:%M:%S")
    except (KeyError, ValueError):
        ts = ""
    modules = m.get("modules") or []
    ram_config = " + ".join(f"{x.get('size_gb')}GB" for x in modules) if modules else ""
    return {
        "timestamp": ts,
        "service_tag": i.get("service_tag") or "",
        "model": i.get("model") or "",
        "cpu": c.get("model") or "",
        "cores": na(c.get("threads")),
        "ram_gb": na(m.get("total_gb")),
        "ram_type": na(m.get("type")),
        "storage_type": "NVMe" if (s.get("transport") == "nvme") else ("SATA" if s.get("present") else "N/A"),
        "storage_gb": na(s.get("size_gb")),
        "smart_status": "PASSED" if s.get("smart_passed") is True else ("FAILED" if s.get("smart_passed") is False else "N/A"),
        "battery_health_pct": na(b.get("health_pct")),
        "battery_charge_pct": na(b.get("charge_pct")),
        "battery_cycles": na(b.get("cycles")),
        "gpu": g.get("discrete") or "None",
        "resolution": na(d.get("resolution")),
        "resolution_class": na(d.get("resolution_class")),
        "screen_size_in": na(d.get("diagonal_in")),
        "touchscreen": yn(f.get("touchscreen")),
        "fingerprint_reader": yn(f.get("fingerprint_reader")),
        "backlit_keyboard": yn(f.get("backlit_keyboard")),
        "wifi_standard": na(f.get("wifi_standard")),
        "bluetooth": yn(f.get("bluetooth")),
        "webcam": yn(f.get("webcam")),
        # graded at the laptop by the auditor (inventory.csv can still override)
        "screen_grade": gr.get("screen_grade") or "",
        "chassis_grade": gr.get("chassis_grade") or "",
        "color": gr.get("color") or "",
        "charger": gr.get("charger") or "",
        "condition_notes": "; ".join(x for x in (gr.get("screen_note"), gr.get("chassis_note")) if x),
        # new evidence columns
        "audit_version": rec.get("auditor_version", ""),
        "express_service_code": na(i.get("express_service_code")),
        "sku": na(i.get("sku")),
        "bios_version": na(i.get("bios_version")),
        "cpu_cores_physical": na(c.get("cores")),
        "ram_config": ram_config,
        "ssd_model": na(s.get("model")),
        "ssd_wear_pct": na(s.get("percentage_used")),
        "ssd_power_on_hours": na(s.get("power_on_hours")),
        "ssd_data_written_tb": na(s.get("data_written_tb")),
        "battery_design_wh": na(b.get("design_wh")),
        "battery_full_wh": na(b.get("full_wh")),
        "display_aspect": na(d.get("aspect")),
        "wifi_card": na(f.get("wifi_card")),
        "oem_key_present": yn(l.get("oem_key_present")),
        "test_display": (t.get("display") or {}).get("result", ""),
        "test_keyboard": (t.get("keyboard") or {}).get("result", ""),
        "test_speaker": (t.get("speaker") or {}).get("result", ""),
        "erase_method": na(e.get("method")),
        "erase_verified": yn(e.get("verified_blank")),
        "warnings": "; ".join(rec.get("warnings") or []),
    }


def load_inventory():
    inv = {}
    if os.path.isfile(INVENTORY):
        with open(INVENTORY, newline="") as f:
            for r in csv.DictReader(f):
                if r.get("service_tag"):
                    inv[r["service_tag"].strip().upper()] = r
    return inv


def load_legacy():
    rows = {}
    if os.path.isfile(LEGACY):
        with open(LEGACY, newline="") as f:
            for r in csv.DictReader(f):
                if r.get("service_tag"):
                    rows[r["service_tag"].strip().upper()] = r
    return rows


def load_audits():
    recs, skipped = {}, []
    for path in sorted(glob.glob(os.path.join(AUDITS_DIR, "*.json"))):
        try:
            with open(path) as f:
                rec = json.load(f)
        except (OSError, ValueError) as e:
            skipped.append(f"{os.path.basename(path)}: unreadable ({e})")
            continue
        tag = ((rec.get("identity") or {}).get("service_tag") or "").upper()
        if rec.get("status") != "audited" or not tag:
            skipped.append(f"{os.path.basename(path)}: status={rec.get('status')}")
            continue
        recs[tag] = rec
    return recs, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report only, do not write")
    args = ap.parse_args()

    inventory = load_inventory()
    legacy = load_legacy()
    audits, skipped = load_audits()

    merged = {}
    for tag, r in legacy.items():
        merged[tag] = {k: r.get(k, "") for k in LEGACY_COLUMNS}
        merged[tag]["audit_version"] = "2"
    for tag, rec in audits.items():
        merged[tag] = row_from_json(rec)

    missing_inventory = []
    for tag, row in merged.items():
        inv = inventory.get(tag)
        if inv:
            for k in INVENTORY_COLUMNS:
                if inv.get(k, "") != "":
                    row[k] = inv[k]
        else:
            missing_inventory.append(tag)
        row.setdefault("status", "audited")
        for k in INVENTORY_COLUMNS:
            row.setdefault(k, "")
        row["recommendation"] = recommendation(row)
        for k in NEW_COLUMNS:
            row.setdefault(k, "")

    ordered = sorted(merged.values(), key=lambda r: r.get("timestamp", ""))
    print(f"legacy rows: {len(legacy)}   v3 audits: {len(audits)}   inventory rows: {len(inventory)}")
    for s in skipped:
        print(f"  skipped {s}")
    if missing_inventory:
        print(f"  not in inventory.csv (grades come from the audit; add a row only for price/status): {', '.join(missing_inventory)}")
    ungraded = [r["service_tag"] for r in ordered if not r.get("chassis_grade")]
    if ungraded:
        print(f"  NO BODY GRADE (audited with --skip-tests or before v3.1): {', '.join(ungraded)}")
    no_key = [r["service_tag"] for r in ordered if r.get("oem_key_present") == "No"]
    if no_key:
        print(f"  NO OEM WINDOWS KEY: {', '.join(no_key)}")
    not_erased = [r["service_tag"] for r in ordered if r.get("audit_version") == "3.0" and r.get("erase_method") in ("N/A", "")]
    if not_erased:
        print(f"  NOT ERASED: {', '.join(not_erased)}")

    if args.check:
        return
    with open(OUTPUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LEGACY_COLUMNS + NEW_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in ordered:
            w.writerow(r)
    print(f"wrote {OUTPUT} ({len(ordered)} rows)")


if __name__ == "__main__":
    sys.exit(main())
