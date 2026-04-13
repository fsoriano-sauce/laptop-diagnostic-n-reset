#!/usr/bin/env python3
"""
generate_ebay_drafts_v2.py
===========================
Reads audit_master.csv and generates an eBay Seller Hub-compatible CSV
using the full "Create or Schedule new listings" template format, which
includes all C: item specifics columns (Brand, Processor, RAM, etc.).

This ensures listings are fully populated on upload — no manual dropdown
filling required.

Usage:
    python generate_ebay_drafts_v2.py <path_to_audit_master.csv>

Output:
    ebay_listings_upload.csv — ready to upload via Seller Hub > Reports > Upload
"""

import csv
import os
import sys
from datetime import datetime

# Add parent dir so we can import from generate_ebay_drafts
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generate_ebay_drafts import (
    build_title, build_html_description, build_condition_notes,
    estimate_price, CONDITION_MAP, clean_gpu_name
)


# ─── eBay Template Constants ────────────────────────────────────────────────

# Info line from the full listing template
INFO_LINE = "Info,Version=1.0.0,Template=fx_category_template_EBAY_US"

# Action header with site metadata (from eBay's official template)
ACTION_HEADER = "*Action(SiteID=US|Country=US|Currency=USD|Version=1193|CC=UTF-8)"

# eBay Category ID for PC Laptops & Netbooks
CATEGORY_ID = "177"

# Column order matches the official "Create or Schedule new listings" template
EBAY_COLUMNS = [
    ACTION_HEADER,
    "CustomLabel",
    "*Category",
    "StoreCategory",
    "*Title",
    "Subtitle",
    "Relationship",
    "RelationshipDetails",
    "ScheduleTime",
    "*ConditionID",
    "*C:Brand",
    "*C:Screen Size",
    "*C:Processor",
    "C:Model",
    "C:Operating System",
    "C:SSD Capacity",
    "C:Hard Drive Capacity",
    "C:Features",
    "C:Type",
    "C:GPU",
    "C:Storage Type",
    "C:Release Year",
    "C:Color",
    "C:Maximum Resolution",
    "C:Processor Speed",
    "C:MPN",
    "C:Unit Quantity",
    "C:Unit Type",
    "C:Series",
    "C:RAM Size",
    "C:Most Suitable For",
    "C:Graphics Processing Type",
    "C:Connectivity",
    "C:Country of Origin",
    "C:Manufacturer Warranty",
    "C:California Prop 65 Warning",
    "C:Item Height",
    "C:Item Length",
    "C:Item Weight",
    "C:Item Width",
    "PicURL",
    "GalleryType",
    "VideoID",
    "*Description",
    "*Format",
    "*Duration",
    "*StartPrice",
    "BuyItNowPrice",
    "BestOfferEnabled",
    "BestOfferAutoAcceptPrice",
    "MinimumBestOfferPrice",
    "*Quantity",
    "ImmediatePayRequired",
    "*Location",
    "ShippingType",
    "ShippingService-1:Option",
    "ShippingService-1:Cost",
    "ShippingService-2:Option",
    "ShippingService-2:Cost",
    "*DispatchTimeMax",
    "PromotionalShippingDiscount",
    "ShippingDiscountProfileID",
    "*ReturnsAcceptedOption",
    "ReturnsWithinOption",
    "RefundOption",
    "ShippingCostPaidByOption",
    "AdditionalDetails",
]


# ─── Mapping Helpers ─────────────────────────────────────────────────────────

def get_processor_value(row: dict) -> str:
    """Map CPU string to eBay's accepted Processor value."""
    cpu = row.get("cpu", "")
    # Determine generation from model number
    import re
    m = re.search(r"i([3579])-((\d{2,5})\w*)", cpu)
    if m:
        tier = m.group(1)
        model_num = m.group(3)
        if len(model_num) == 5:
            gen = model_num[:2]  # e.g., 12700 → 12
        elif len(model_num) == 4:
            gen = model_num[0]   # e.g., 8565 → 8
        else:
            gen = ""
        gen_suffix = {
            "1": "1st Gen.", "2": "2nd Gen.", "3": "3rd Gen.",
            "4": "4th Gen.", "5": "5th Gen.", "6": "6th Gen.",
            "7": "7th Gen.", "8": "8th Gen.", "9": "9th Gen.",
            "10": "10th Gen.", "11": "11th Gen.", "12": "12th Gen.",
            "13": "13th Gen.", "14": "14th Gen.",
        }.get(gen, f"{gen}th Gen.")
        return f"Intel Core i{tier} {gen_suffix}"
    return ""


def get_processor_speed(row: dict) -> str:
    """Extract base clock speed from CPU string."""
    cpu = row.get("cpu", "")
    import re
    m = re.search(r"@\s*([\d.]+)\s*GHz", cpu)
    if m:
        return f"{m.group(1)} GHz"
    # Known base clocks for common CPUs
    speed_map = {
        "i7-12700H": "2.30 GHz",
        "i7-11800H": "2.30 GHz",
        "i5-12500H": "2.50 GHz",
        "i5-11400H": "2.70 GHz",
    }
    for model, speed in speed_map.items():
        if model in cpu:
            return speed
    return ""


def get_gpu_ebay_value(row: dict) -> str:
    """Map GPU to eBay's accepted GPU value."""
    gpu = row.get("gpu", "")
    if not gpu or gpu == "None":
        return ""
    import re
    m = re.search(r"(GeForce\s+(?:RTX|GTX|MX)\s+\d+(?:\s+Ti)?)", gpu, re.IGNORECASE)
    if m:
        return f"NVIDIA {m.group(1)}"
    return ""


def get_graphics_processing_type(row: dict) -> str:
    """Return the graphics processing type."""
    gpu = row.get("gpu", "")
    if not gpu or gpu == "None":
        return "Integrated/On-Board Graphics"
    return "Dedicated Graphics"


def get_features(row: dict) -> str:
    """Build pipe-delimited features list from audit data."""
    features = []
    if row.get("backlit_keyboard", "").lower() in ("yes", "true"):
        features.append("Backlit Keyboard")
    if row.get("bluetooth", "").lower() in ("yes", "true"):
        features.append("Bluetooth")
    if row.get("webcam", "").lower() in ("yes", "true"):
        features.append("Built-in Webcam")
    if row.get("touchscreen", "").lower() in ("yes", "true"):
        features.append("Touchscreen")
    if row.get("wifi_standard", ""):
        features.append("Wi-Fi")
    return "|".join(features) if features else ""


def get_connectivity(row: dict) -> str:
    """Build pipe-delimited connectivity list."""
    connectivity = []
    connectivity.append("USB-C")
    connectivity.append("USB 3.0")
    connectivity.append("HDMI")
    connectivity.append("SD Card Slot")
    return "|".join(connectivity)


def get_screen_size(row: dict) -> str:
    """Map screen_size_in to eBay's accepted values."""
    size = row.get("screen_size_in", "")
    try:
        s = float(size)
        # Map to nearest eBay value
        ebay_sizes = [
            10.1, 11.6, 12.5, 13.3, 14, 14.1, 15, 15.3, 15.4, 15.6,
            15.7, 16, 16.1, 17, 17.3
        ]
        closest = min(ebay_sizes, key=lambda x: abs(x - s))
        # eBay uses format like "16 in" or "15.6 in"
        if closest == int(closest):
            return f"{int(closest)} in"
        return f"{closest} in"
    except (ValueError, TypeError):
        return ""


def get_model_value(row: dict) -> str:
    """Extract Dell model name for the C:Model field."""
    model = row.get("model", "")
    if "Vostro" in model:
        return f"Dell {model}"
    return model


def get_series(row: dict) -> str:
    """Extract series name."""
    model = row.get("model", "")
    if "Vostro" in model:
        return "Vostro"
    if "Latitude" in model:
        return "Latitude"
    if "Inspiron" in model:
        return "Inspiron"
    if "XPS" in model:
        return "XPS"
    if "Precision" in model:
        return "Precision"
    return ""


def get_color(row: dict) -> str:
    """Map color to eBay's accepted values."""
    color = row.get("color", "").lower()
    color_map = {
        "silver": "Silver", "gray": "Gray", "grey": "Gray",
        "black": "Black", "white": "White", "blue": "Blue",
        "gold": "Gold", "red": "Red", "green": "Green",
    }
    for key, val in color_map.items():
        if key in color:
            return val
    return "Gray"  # default for Dell laptops


def get_release_year(row: dict) -> str:
    """Get release year from manufacture_year or estimate from CPU generation."""
    year = row.get("manufacture_year", "")
    if year and year != "N/A":
        return year
    # Estimate from CPU generation
    cpu = row.get("cpu", "")
    if "12th Gen" in cpu or "12700" in cpu or "12500" in cpu:
        return "2022"
    if "11th Gen" in cpu or "11800" in cpu or "11400" in cpu:
        return "2021"
    if "13th Gen" in cpu or "13700" in cpu:
        return "2023"
    return ""


# ─── eBay Condition ID ────────────────────────────────────────────────────────

CONDITION_ID_MAP = {
    ("A", "A"): "3000",
    ("A", "B"): "3000",
    ("B", "A"): "3000",
    ("B", "B"): "3000",
    ("A", "C"): "7000",
    ("B", "C"): "7000",
    ("C", "A"): "7000",
    ("C", "B"): "7000",
    ("C", "C"): "7000",
}


# GitHub raw URL base for listing photos
GITHUB_PHOTOS_BASE = "https://raw.githubusercontent.com/fsoriano-sauce/laptop-diagnostic-n-reset/master/listing-photos"


def build_photo_urls(service_tag: str, script_dir: str) -> str:
    """Build pipe-delimited photo URLs from listing-photos/{tag}/ directory.
    eBay PicURL supports up to 24 pipe-delimited URLs.
    """
    photos_dir = os.path.join(script_dir, "..", "listing-photos", service_tag)
    photos_dir = os.path.normpath(photos_dir)
    if not os.path.isdir(photos_dir):
        return ""
    # Get all jpg files sorted
    photos = sorted([
        f for f in os.listdir(photos_dir)
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
    ])[:24]  # eBay max 24 photos
    if not photos:
        return ""
    urls = [f"{GITHUB_PHOTOS_BASE}/{service_tag}/{fname}" for fname in photos]
    return "|".join(urls)


# ─── Main Generator ─────────────────────────────────────────────────────────

def generate_ebay_csv(input_path: str, output_path: str):
    """Generate eBay-compatible full listing CSV from audit_master.csv."""

    with open(input_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [r for r in reader if r.get("status", "") == "audited"]

    if not rows:
        print("[!] No audited laptops found in the CSV.")
        return

    # Build eBay rows
    ebay_rows = []
    for row in rows:
        sg = row.get("screen_grade", "A")
        cg = row.get("chassis_grade", "A")
        condition_id = CONDITION_ID_MAP.get((sg, cg), "3000")
        price = estimate_price(row)

        # Auto-accept best offer at 90% of price, minimum at 80%
        try:
            price_f = float(price)
            auto_accept = f"{price_f * 0.90:.2f}"
            min_offer = f"{price_f * 0.80:.2f}"
        except ValueError:
            auto_accept = ""
            min_offer = ""

        ebay_rows.append({
            ACTION_HEADER: "Add",
            "CustomLabel": row.get("service_tag", ""),
            "*Category": CATEGORY_ID,
            "StoreCategory": "",
            "*Title": build_title(row),
            "Subtitle": "",
            "Relationship": "",
            "RelationshipDetails": "",
            "ScheduleTime": "",
            "*ConditionID": condition_id,
            # Item Specifics (Required)
            "*C:Brand": "Dell",
            "*C:Screen Size": get_screen_size(row),
            "*C:Processor": get_processor_value(row),
            # Item Specifics (Additional)
            "C:Model": get_model_value(row),
            "C:Operating System": "Windows 11 Pro",
            "C:SSD Capacity": f"{row.get('storage_gb', '512')} GB",
            "C:Hard Drive Capacity": f"{row.get('storage_gb', '512')} GB",
            "C:Features": get_features(row),
            "C:Type": "Notebook/Laptop",
            "C:GPU": get_gpu_ebay_value(row),
            "C:Storage Type": "SSD (Solid State Drive)",
            "C:Release Year": get_release_year(row),
            "C:Color": get_color(row),
            "C:Maximum Resolution": __import__('re').sub(r'(\d)x(\d)', r'\1 x \2', row.get("resolution", "1920 x 1200")),
            "C:Processor Speed": get_processor_speed(row),
            "C:MPN": "",
            "C:Unit Quantity": "",
            "C:Unit Type": "",
            "C:Series": get_series(row),
            "C:RAM Size": f"{row.get('ram_gb', '16')} GB",
            "C:Most Suitable For": "Casual Computing",
            "C:Graphics Processing Type": get_graphics_processing_type(row),
            "C:Connectivity": get_connectivity(row),
            "C:Country of Origin": "",
            "C:Manufacturer Warranty": "",
            "C:California Prop 65 Warning": "",
            "C:Item Height": "",
            "C:Item Length": "",
            "C:Item Weight": "",
            "C:Item Width": "",
            # Photos & Media
            "PicURL": build_photo_urls(
                row.get("service_tag", ""),
                os.path.dirname(os.path.abspath(__file__))
            ),
            "GalleryType": "",
            "VideoID": "",
            # Description & Format
            "*Description": build_html_description(row),
            "*Format": "FixedPrice",
            "*Duration": "GTC",
            # Pricing
            "*StartPrice": price,
            "BuyItNowPrice": "",
            "BestOfferEnabled": "1",
            "BestOfferAutoAcceptPrice": auto_accept,
            "MinimumBestOfferPrice": min_offer,
            # Quantity
            "*Quantity": "1",
            "ImmediatePayRequired": "true",
            # Location & Shipping — buyer pays
            "*Location": "Boca Raton, FL",
            "ShippingType": "Flat",
            "ShippingService-1:Option": "USPSParcel",
            "ShippingService-1:Cost": "14.99",
            "ShippingService-2:Option": "UPSGround",
            "ShippingService-2:Cost": "18.99",
            "*DispatchTimeMax": "3",
            "PromotionalShippingDiscount": "",
            "ShippingDiscountProfileID": "",
            # Returns — not accepted
            "*ReturnsAcceptedOption": "ReturnsNotAccepted",
            "ReturnsWithinOption": "",
            "RefundOption": "",
            "ShippingCostPaidByOption": "",
            "AdditionalDetails": "",
        })

    # Write with Info header line + CSV data
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        # Write template info line
        f.write(INFO_LINE + "\n")

        # Write column headers and data rows
        writer = csv.DictWriter(f, fieldnames=EBAY_COLUMNS)
        writer.writeheader()
        for r in ebay_rows:
            writer.writerow(r)

    print(f"\n  [OK] Generated {len(ebay_rows)} eBay full listings")
    print(f"  [OK] Saved to: {output_path}")
    print()
    print("  Upload steps:")
    print("  1. Go to Seller Hub > Reports > Upload")
    print("  2. Click 'Upload template'")
    print("  3. Select this CSV file")
    print("  4. Listings saved as DRAFTS (inactive)")
    print("     Or change Action to 'Draft' to review first")
    print()

    # Print summary table
    print(f"  {'Service Tag':<12} {'Title':<55} {'Price':>8}")
    print(f"  {'-'*12:<12} {'-'*55:<55} {'-'*8:>8}")
    for r in ebay_rows:
        tag = r["CustomLabel"]
        title = r["*Title"][:53]
        price = r["*StartPrice"]
        print(f"  {tag:<12} {title:<55} ${price:>7}")
    print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python generate_ebay_drafts_v2.py <path_to_audit_master.csv>")
        print("       python generate_ebay_drafts_v2.py L:\\audit_master.csv")
        sys.exit(1)

    input_csv = sys.argv[1]
    if not os.path.isfile(input_csv):
        print(f"[!] File not found: {input_csv}")
        sys.exit(1)

    output_csv = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(input_csv))) or ".",
        "ebay_listings_upload.csv"
    )
    generate_ebay_csv(input_csv, output_csv)
