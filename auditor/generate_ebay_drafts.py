#!/usr/bin/env python3
"""
generate_ebay_drafts.py
========================
Reads audit_master.csv and generates an eBay Seller Hub-compatible CSV
for bulk draft upload via Seller Hub > Reports > Upload.

Usage:
    python generate_ebay_drafts.py audit_master.csv

Output:
    ebay_drafts_YYYYMMDD_HHMMSS.csv — ready to upload to Seller Hub
"""

import csv
import os
import sys
from datetime import datetime


# ─── eBay Category & Condition Constants ─────────────────────────────────────

EBAY_CATEGORY_ID = "177"  # PC Laptops & Netbooks

# eBay condition IDs
CONDITION_MAP = {
    # screen_grade + chassis_grade → eBay condition
    ("A", "A"): ("3000", "Seller refurbished"),   # Like New
    ("A", "B"): ("3000", "Seller refurbished"),   # Minor cosmetic
    ("B", "A"): ("3000", "Seller refurbished"),
    ("B", "B"): ("7000", "Good - Refurbished"),   # Noticeable wear
    ("A", "C"): ("7000", "Good - Refurbished"),
    ("B", "C"): ("7000", "Good - Refurbished"),
    ("C", "A"): ("7000", "Good - Refurbished"),
    ("C", "B"): ("7000", "Good - Refurbished"),
    ("C", "C"): ("7000", "Good - Refurbished"),
}

# ─── Title Builder ───────────────────────────────────────────────────────────

def clean_cpu_name(raw_cpu: str) -> str:
    """Shorten verbose CPU string for the 80-char title."""
    cpu = raw_cpu
    # Remove "12th Gen Intel(R) Core(TM) " prefix
    for prefix in ["12th Gen ", "11th Gen ", "13th Gen ", "14th Gen ",
                    "Intel(R) Core(TM) ", "Intel(R) Core(R) ",
                    "Intel(R) ", "Core(TM) ", "Core(R) "]:
        cpu = cpu.replace(prefix, "")
    # Remove trailing " @ X.XXGHz"
    if " @ " in cpu:
        cpu = cpu[:cpu.index(" @ ")]
    return cpu.strip()


def clean_gpu_name(raw_gpu: str) -> str:
    """Extract short GPU name like 'RTX 3050 Ti'."""
    if not raw_gpu or raw_gpu == "None":
        return ""
    # Look for GeForce pattern
    import re
    m = re.search(r"GeForce\s+((?:RTX|GTX|MX)\s+\d+(?:\s+Ti)?)", raw_gpu, re.IGNORECASE)
    if m:
        return m.group(1)
    # Look for Radeon
    m = re.search(r"Radeon\s+(\S+\s*\d+\S*)", raw_gpu, re.IGNORECASE)
    if m:
        return f"Radeon {m.group(1)}"
    return ""


def build_title(row: dict) -> str:
    """
    Build an eBay-optimized listing title (max 80 chars).
    Template: Dell {Model} {Screen}" {CPU} {RAM}GB {Storage}GB {GPU} Laptop
    """
    model = row.get("model", "Laptop")
    cpu = clean_cpu_name(row.get("cpu", ""))
    gpu_short = clean_gpu_name(row.get("gpu", ""))
    ram = row.get("ram_gb", "")
    storage = row.get("storage_gb", "")
    storage_type = row.get("storage_type", "")
    screen = row.get("screen_size_in", "")

    # Build parts
    parts = [f"Dell {model}"]
    if screen and screen != "N/A":
        parts.append(f'{screen}"')
    if cpu:
        parts.append(cpu)
    if ram:
        parts.append(f"{ram}GB RAM")
    if storage:
        st = "SSD" if "nvme" in storage_type.lower() or "ssd" in storage_type.lower() else storage_type
        parts.append(f"{storage}GB {st}")
    if gpu_short:
        parts.append(gpu_short)

    title = " ".join(parts)

    # Trim to 80 chars
    if len(title) > 80:
        # Drop GPU if too long
        parts_no_gpu = [p for p in parts if p != gpu_short]
        title = " ".join(parts_no_gpu)
    if len(title) > 80:
        title = title[:77] + "..."

    return title


# ─── Condition Notes Builder ─────────────────────────────────────────────────

def build_condition_notes(row: dict) -> str:
    """Build eBay condition description from audit data."""
    parts = []

    # Screen
    screen_map = {"A": "Screen in excellent condition — no dead pixels or blemishes.",
                  "B": "Screen has minor white spots or dead pixels.",
                  "C": "Screen has scratches."}
    sg = row.get("screen_grade", "")
    if sg in screen_map:
        parts.append(screen_map[sg])

    # Chassis
    chassis_map = {"A": "Chassis is in mint condition.",
                   "B": "Minor scuffs on chassis — normal use.",
                   "C": "Chassis has dents or cracks."}
    cg = row.get("chassis_grade", "")
    if cg in chassis_map:
        parts.append(chassis_map[cg])

    # Battery
    bh = row.get("battery_health_pct", "N/A")
    if bh and bh != "N/A":
        parts.append(f"Battery health: {bh}%.")

    # Charger
    ch = row.get("charger", "")
    if ch == "Y":
        parts.append("Includes OEM charger.")
    else:
        parts.append("No charger included.")

    parts.append("Fresh Windows 11 Pro installation — no bloatware, ready to use.")

    return " ".join(parts)


# ─── HTML Description Builder ────────────────────────────────────────────────

def build_html_description(row: dict) -> str:
    """Build professional HTML listing description from audit data."""
    model = row.get("model", "Laptop")
    cpu = row.get("cpu", "N/A")
    ram = row.get("ram_gb", "N/A")
    ram_type = row.get("ram_type", "")
    storage = row.get("storage_gb", "N/A")
    storage_type = row.get("storage_type", "")
    gpu = row.get("gpu", "None")
    if gpu == "None":
        gpu = "Integrated Intel Graphics"
    screen_size = row.get("screen_size_in", "N/A")
    resolution = row.get("resolution", "N/A")
    battery = row.get("battery_health_pct", "N/A")
    smart = row.get("smart_status", "N/A")
    screen_grade = row.get("screen_grade", "N/A")
    chassis_grade = row.get("chassis_grade", "N/A")
    charger = "Yes — OEM charger included" if row.get("charger") == "Y" else "No"

    # Feature badges
    features = []
    if row.get("wifi_standard", "N/A") != "N/A":
        features.append(row["wifi_standard"])
    if row.get("bluetooth") == "Yes":
        features.append("Bluetooth")
    if row.get("webcam") == "Yes":
        features.append("Webcam")
    if row.get("fingerprint_reader") == "Yes":
        features.append("Fingerprint Reader")
    if row.get("backlit_keyboard") == "Yes":
        features.append("Backlit Keyboard")
    if row.get("touchscreen") == "Yes":
        features.append("Touchscreen")
    features_str = " &bull; ".join(features) if features else "N/A"

    grade_map = {"A": "Excellent", "B": "Good — minor wear", "C": "Fair — visible wear"}

    return f"""<div style="max-width:800px;margin:0 auto;font-family:Arial,Helvetica,sans-serif;color:#333;">
<div style="background:#1a1a2e;color:white;padding:20px;border-radius:8px 8px 0 0;text-align:center;">
<h1 style="margin:0;font-size:22px;">Dell {model}</h1>
<p style="margin:5px 0 0;color:#a0a0c0;font-size:14px;">Professionally Audited &amp; Restored</p>
</div>
<table style="width:100%;border-collapse:collapse;margin:0;">
<tr style="background:#f8f8fc;"><td style="padding:10px 15px;border-bottom:1px solid #eee;font-weight:bold;width:40%;">Processor</td><td style="padding:10px 15px;border-bottom:1px solid #eee;">{cpu}</td></tr>
<tr><td style="padding:10px 15px;border-bottom:1px solid #eee;font-weight:bold;">RAM</td><td style="padding:10px 15px;border-bottom:1px solid #eee;">{ram} GB {ram_type}</td></tr>
<tr style="background:#f8f8fc;"><td style="padding:10px 15px;border-bottom:1px solid #eee;font-weight:bold;">Storage</td><td style="padding:10px 15px;border-bottom:1px solid #eee;">{storage} GB {storage_type}</td></tr>
<tr><td style="padding:10px 15px;border-bottom:1px solid #eee;font-weight:bold;">Graphics</td><td style="padding:10px 15px;border-bottom:1px solid #eee;">{gpu}</td></tr>
<tr style="background:#f8f8fc;"><td style="padding:10px 15px;border-bottom:1px solid #eee;font-weight:bold;">Display</td><td style="padding:10px 15px;border-bottom:1px solid #eee;">{screen_size}" {resolution}</td></tr>
<tr><td style="padding:10px 15px;border-bottom:1px solid #eee;font-weight:bold;">Operating System</td><td style="padding:10px 15px;border-bottom:1px solid #eee;">Windows 11 Pro (Fresh Install)</td></tr>
<tr style="background:#f8f8fc;"><td style="padding:10px 15px;border-bottom:1px solid #eee;font-weight:bold;">Connectivity</td><td style="padding:10px 15px;border-bottom:1px solid #eee;">{features_str}</td></tr>
</table>
<div style="margin-top:20px;padding:15px;background:#f0fdf4;border-left:4px solid #22c55e;border-radius:0 4px 4px 0;">
<h2 style="margin:0 0 10px;font-size:16px;color:#16a34a;">&check; Condition Report</h2>
<table style="width:100%;font-size:14px;">
<tr><td style="padding:4px 0;"><strong>Screen:</strong></td><td>{grade_map.get(screen_grade, screen_grade)}</td></tr>
<tr><td style="padding:4px 0;"><strong>Chassis:</strong></td><td>{grade_map.get(chassis_grade, chassis_grade)}</td></tr>
<tr><td style="padding:4px 0;"><strong>Battery Health:</strong></td><td>{battery}%</td></tr>
<tr><td style="padding:4px 0;"><strong>SMART Status:</strong></td><td>{smart}</td></tr>
</table>
</div>
<div style="margin-top:15px;padding:15px;background:#f8f8fc;border-radius:4px;">
<h2 style="margin:0 0 8px;font-size:16px;">&boxbox; What's Included</h2>
<ul style="margin:0;padding-left:20px;font-size:14px;">
<li>Dell {model} Laptop</li>
<li>Charger: {charger}</li>
<li>Fresh Windows 11 Pro installation (no bloatware)</li>
</ul>
</div>
<div style="margin-top:15px;padding:12px;background:#1a1a2e;color:#a0a0c0;border-radius:0 0 8px 8px;text-align:center;font-size:12px;">
Professionally audited, securely wiped, and restored. Ships within 3 business days.
</div>
</div>"""


# ─── Price Estimator ─────────────────────────────────────────────────────────

def estimate_price(row: dict) -> str:
    """
    Estimate listing price based on eBay sold comps (researched April 2026).

    Market data anchors (median sold, last 90 days):
      - Vostro 7620, i7-12700H, 16GB DDR5, 512GB, RTX 3050 Ti: $415 median
        Range: $415 (median) to $479 (excellent+charger) to $549 (eBay Refurb)
      - Vostro 7510, i7-11800H, 16GB DDR4, 512GB, RTX 3050:    $405 median
        Range: $350 (poor/no SSD) to $424 (no charger) to $540 (32GB)

    Strategy: Start from model median, adjust for battery, storage, condition.
    """
    # ── Model-specific base prices (from eBay sold comps) ──
    model = row.get("model", "")
    cpu = row.get("cpu", "")
    gpu = row.get("gpu", "None")

    if "7620" in model:
        base = 435  # Slightly above median ($415) for our fresh Windows + charger advantage
    elif "7510" in model:
        base = 400  # Slightly below 7620; 11th gen + DDR4
    elif "7530" in model or "7540" in model:
        base = 450  # 13th gen Vostros
    elif "latitude" in model.lower():
        base = 320  # Business Latitudes sell lower
    elif "inspiron" in model.lower():
        base = 300  # Consumer line
    else:
        # Fallback: rule-based for unknown models
        base = 300
        if "12th Gen" in cpu or "13th Gen" in cpu:
            base += 60
        elif "11th Gen" in cpu:
            base += 40
        if "i7" in cpu:
            base += 30
        elif "i5" in cpu:
            base += 10

    # ── GPU adjustment (if not already in model base) ──
    if gpu == "None" or gpu == "":
        base -= 50  # No discrete GPU = significant discount
    elif "3060" in gpu:
        base += 40  # Above 3050 tier
    elif "3070" in gpu or "3080" in gpu:
        base += 80

    # ── Storage premium ──
    try:
        storage = int(row.get("storage_gb", "512"))
        if storage >= 1000:
            base += 40  # 1TB SSD = +$40 (comps confirm $479-489 for 1TB vs $415 for 512GB)
        elif storage <= 256:
            base -= 30
    except ValueError:
        pass

    # ── RAM premium (above 16GB) ──
    try:
        ram = int(row.get("ram_gb", "16"))
        if ram >= 32:
            base += 50  # 32GB comps sell ~$540 vs $415 median
        elif ram >= 64:
            base += 80
        elif ram <= 8:
            base -= 40
    except ValueError:
        pass

    # ── Battery health adjustment (key differentiator for identical models) ──
    try:
        batt = int(row.get("battery_health_pct", "85"))
        if batt >= 95:
            base += 20  # Premium for near-new battery
        elif batt >= 85:
            base += 10  # Above average
        elif batt >= 75:
            pass  # Average, no adjustment
        elif batt >= 65:
            base -= 15  # Below average
        elif batt >= 50:
            base -= 30  # Noticeable degradation
        else:
            base -= 50  # Poor battery
    except ValueError:
        pass

    # ── Condition grade adjustment ──
    screen = row.get("screen_grade", "A")
    chassis = row.get("chassis_grade", "A")
    if screen == "A" and chassis == "A":
        base += 15  # Mint condition premium
    elif screen == "B" or chassis == "B":
        pass  # Minor wear, standard pricing
    elif screen == "C" or chassis == "C":
        base -= 25  # Visible damage discount

    # ── Charger included ──
    if row.get("charger", "Y") != "Y":
        base -= 20  # No charger penalty (comps confirm $20-25 difference)

    # ── Fresh Windows advantage ──
    # Already baked into base (most comps are as-is or need setup)

    # Round to .99
    price = max(base, 149)
    return f"{price}.99"



# ─── Main ────────────────────────────────────────────────────────────────────

def build_item_specifics(row: dict) -> dict:
    """Build eBay item specifics columns."""
    specs = {}
    specs["Brand"] = "Dell"
    specs["Type"] = "Notebook/Laptop"
    specs["Model"] = f"Dell {row.get('model', '')}"
    specs["Processor"] = row.get("cpu", "")
    specs["RAM Size"] = f"{row.get('ram_gb', '')} GB"
    specs["SSD Capacity"] = f"{row.get('storage_gb', '')} GB"
    specs["Storage Type"] = row.get("storage_type", "")
    specs["Screen Size"] = f'{row.get("screen_size_in", "")} in'
    specs["Resolution"] = row.get("resolution", "")
    specs["GPU"] = row.get("gpu", "Integrated")
    specs["Color"] = row.get("color", "")
    specs["Operating System"] = "Windows 11 Pro"
    specs["Features"] = build_features_list(row)
    specs["Connectivity"] = row.get("wifi_standard", "")
    specs["Memory Type"] = row.get("ram_type", "")
    return specs


def build_features_list(row: dict) -> str:
    """Build pipe-separated features list for eBay item specifics."""
    features = []
    if row.get("backlit_keyboard") == "Yes":
        features.append("Backlit Keyboard")
    if row.get("fingerprint_reader") == "Yes":
        features.append("Fingerprint Reader")
    if row.get("webcam") == "Yes":
        features.append("Built-in Webcam")
    if row.get("bluetooth") == "Yes":
        features.append("Bluetooth")
    if row.get("touchscreen") == "Yes":
        features.append("Touchscreen")
    return "|".join(features) if features else ""


def generate_ebay_csv(input_path: str, output_path: str):
    """Main function to generate eBay draft CSV from audit data."""

    with open(input_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # Filter to only 'audited' status rows (skip sold, etc.)
    rows = [r for r in rows if r.get("status", "") == "audited"]

    if not rows:
        print("[!] No audited laptops found in the CSV.")
        return

    # eBay Seller Hub draft upload columns
    ebay_headers = [
        "Action", "Category ID", "Title", "ConditionID", "ConditionDescription",
        "Price", "Quantity", "Format", "Duration",
        "Description",
        "C:Brand", "C:Type", "C:Model", "C:Processor",
        "C:RAM Size", "C:SSD Capacity", "C:Storage Type",
        "C:Screen Size", "C:Resolution", "C:GPU", "C:Color",
        "C:Operating System", "C:Features", "C:Connectivity",
        "C:Memory Type",
        "CustomLabel",
    ]

    ebay_rows = []
    for row in rows:
        # Condition mapping
        sg = row.get("screen_grade", "A")
        cg = row.get("chassis_grade", "A")
        cond_id, _ = CONDITION_MAP.get((sg, cg), ("3000", "Seller refurbished"))

        # Build item specifics
        specs = build_item_specifics(row)

        ebay_row = {
            "Action": "Draft",
            "Category ID": EBAY_CATEGORY_ID,
            "Title": build_title(row),
            "ConditionID": cond_id,
            "ConditionDescription": build_condition_notes(row),
            "Price": estimate_price(row),
            "Quantity": "1",
            "Format": "FixedPrice",
            "Duration": "GTC",
            "Description": build_html_description(row),
            "C:Brand": specs["Brand"],
            "C:Type": specs["Type"],
            "C:Model": specs["Model"],
            "C:Processor": specs["Processor"],
            "C:RAM Size": specs["RAM Size"],
            "C:SSD Capacity": specs["SSD Capacity"],
            "C:Storage Type": specs["Storage Type"],
            "C:Screen Size": specs["Screen Size"],
            "C:Resolution": specs["Resolution"],
            "C:GPU": specs["GPU"],
            "C:Color": specs["Color"],
            "C:Operating System": specs["Operating System"],
            "C:Features": specs["Features"],
            "C:Connectivity": specs["Connectivity"],
            "C:Memory Type": specs["Memory Type"],
            "CustomLabel": row.get("service_tag", ""),  # SKU = service tag
        }
        ebay_rows.append(ebay_row)

    # Write output
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ebay_headers)
        writer.writeheader()
        for r in ebay_rows:
            writer.writerow(r)

    print(f"\n  [OK] Generated {len(ebay_rows)} eBay draft listings")
    print(f"  [OK] Saved to: {output_path}")
    print()
    print("  Next steps:")
    print("  1. Go to Seller Hub > Reports > Upload")
    print("  2. Click 'Upload template'")
    print("  3. Select this CSV file")
    print("  4. After upload, find your drafts in Seller Hub > Listings > Drafts")
    print("  5. Add photos and review each listing before publishing")
    print()

    # Print summary table
    print(f"  {'Service Tag':<12} {'Title':<55} {'Price':>8}")
    print(f"  {'-'*12:<12} {'-'*55:<55} {'-'*8:>8}")
    for row, ebay_row in zip(rows, ebay_rows):
        tag = row.get("service_tag", "")
        title = ebay_row["Title"][:53]
        price = ebay_row["Price"]
        print(f"  {tag:<12} {title:<55} ${price:>7}")
    print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python generate_ebay_drafts.py <path_to_audit_master.csv>")
        print("       python generate_ebay_drafts.py L:\\audit_master.csv")
        sys.exit(1)

    input_csv = sys.argv[1]
    if not os.path.isfile(input_csv):
        print(f"[!] File not found: {input_csv}")
        sys.exit(1)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_csv = os.path.join(os.path.dirname(input_csv) or ".", f"ebay_drafts_{timestamp}.csv")

    generate_ebay_csv(input_csv, output_csv)
