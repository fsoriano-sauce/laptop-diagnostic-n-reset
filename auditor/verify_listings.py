#!/usr/bin/env python3
"""Cross-reference audit_master_local.csv against ebay_listings_upload.csv
to verify every field matches accurately."""

import csv
import os
import re

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)

AUDIT_PATH = os.path.join(SCRIPT_DIR, "audit_master_local.csv")
EBAY_PATH = os.path.join(ROOT_DIR, "ebay_listings_upload.csv")
PHOTOS_DIR = os.path.join(ROOT_DIR, "listing-photos")
ICLOUD_DIR = r"C:\Users\frank\iCloudPhotos\Shared"

issues = []
checks = 0


def check(tag, field, expected, actual, exact=True):
    global checks, issues
    checks += 1
    if exact:
        if str(expected).strip() != str(actual).strip():
            issues.append(f"  [{tag}] {field}: AUDIT={expected!r} vs EBAY={actual!r}")
            return False
    else:
        if str(expected).strip().lower() not in str(actual).strip().lower():
            issues.append(f"  [{tag}] {field}: AUDIT={expected!r} not found in EBAY={actual!r}")
            return False
    return True


# Load audit source
with open(AUDIT_PATH, "r", encoding="utf-8") as f:
    audit = {r["service_tag"]: r for r in csv.DictReader(f)}

# Load generated CSV (skip header comment line)
with open(EBAY_PATH, "r", encoding="utf-8") as f:
    lines = f.readlines()
    reader = csv.DictReader(lines[1:])
    ebay = {}
    for r in reader:
        ebay[r["CustomLabel"]] = r

print("=" * 70)
print("  LISTING VERIFICATION AUDIT")
print("  Audit Source: audit_master_local.csv")
print("  eBay Upload:  ebay_listings_upload.csv")
print("=" * 70)

for tag in sorted(audit.keys()):
    a = audit[tag]
    e = ebay.get(tag, {})
    model = a["model"]
    print(f"\n--- {tag} | {model} ---")

    if not e:
        issues.append(f"  [{tag}] CRITICAL: Not found in eBay CSV!")
        continue

    # 1. TITLE - should contain model, CPU shortname, RAM, storage, GPU
    title = e.get("*Title", "")
    print(f"  Title: {title}")
    check(tag, "Title contains model", model, title, exact=False)
    check(tag, "Title contains RAM", f"{a['ram_gb']}GB", title.replace(" ", ""), exact=False)
    check(tag, "Title contains SSD", f"{a['storage_gb']}GB", title.replace(" ", ""), exact=False)

    # 2. CPU
    cpu_audit = a["cpu"]
    cpu_ebay = e.get("C:Processor", "")
    print(f"  CPU audit:  {cpu_audit}")
    print(f"  CPU eBay:   {cpu_ebay}")
    # Check generation is correct
    gen_match = re.search(r"(\d+)th Gen", cpu_audit)
    if gen_match:
        gen = gen_match.group(1)
        check(tag, "CPU generation", f"{gen}th Gen", cpu_ebay, exact=False)
    # Check i7
    if "i7" in cpu_audit:
        check(tag, "CPU i7", "i7", cpu_ebay, exact=False)

    # 3. RAM
    ram_audit = a["ram_gb"]
    ram_ebay = e.get("C:RAM Size", "")
    print(f"  RAM audit:  {ram_audit} GB {a['ram_type']}")
    print(f"  RAM eBay:   {ram_ebay}")
    check(tag, "RAM size", f"{ram_audit} GB", ram_ebay)

    # 4. STORAGE
    storage_audit = a["storage_gb"]
    ssd_ebay = e.get("C:SSD Capacity", "")
    hdd_ebay = e.get("C:Hard Drive Capacity", "")
    storage_type_ebay = e.get("C:Storage Type", "")
    print(f"  Storage audit: {storage_audit} GB {a['storage_type']}")
    print(f"  Storage eBay:  SSD={ssd_ebay}, HDD={hdd_ebay}, Type={storage_type_ebay}")
    check(tag, "SSD capacity", f"{storage_audit} GB", ssd_ebay)
    if a["storage_type"] == "NVMe":
        check(tag, "Storage type", "SSD", storage_type_ebay, exact=False)

    # 5. GPU
    gpu_audit = a["gpu"]
    gpu_ebay = e.get("C:GPU", "")
    print(f"  GPU audit:  {gpu_audit}")
    print(f"  GPU eBay:   {gpu_ebay}")
    if "3050 Ti" in gpu_audit:
        check(tag, "GPU model", "3050 Ti", gpu_ebay, exact=False)
    elif "3050" in gpu_audit:
        check(tag, "GPU model", "3050", gpu_ebay, exact=False)

    # 6. SCREEN
    screen_audit = a["screen_size_in"]
    res_audit = a["resolution"]
    screen_ebay = e.get("C:Screen Size", "")
    res_ebay = e.get("C:Max. Resolution", "")
    print(f"  Screen audit: {screen_audit} in, {res_audit}")
    print(f"  Screen eBay:  {screen_ebay}, {res_ebay}")
    # Check screen size number is in the value
    check(tag, "Screen size", screen_audit, screen_ebay, exact=False)
    # Check resolution numbers
    res_nums = re.findall(r"\d+", res_audit)
    for num in res_nums:
        check(tag, f"Resolution contains {num}", num, res_ebay, exact=False)

    # 7. CONDITION
    sg = a["screen_grade"]
    cg = a["chassis_grade"]
    cond = e.get("*ConditionID", "")
    print(f"  Grades: Screen={sg}, Chassis={cg} -> ConditionID={cond}")
    # A/B grades should map to 3000 (Seller Refurbished)
    if sg in ("A", "B") and cg in ("A", "B"):
        check(tag, "Condition ID for A/B grades", "3000", cond)

    # 8. PRICE & BEST OFFER
    price = e.get("*StartPrice", "")
    bo_accept = e.get("BestOfferAutoAcceptPrice", "")
    bo_min = e.get("MinimumBestOfferPrice", "")
    print(f"  Price: ${price}")
    if bo_accept:
        expected_accept = round(float(price) * 0.9, 2)
        actual_accept = float(bo_accept)
        print(f"  Best Offer: Accept=${bo_accept} (expected ~${expected_accept:.2f})")
        print(f"  Best Offer: Min=${bo_min} (expected ~${float(price)*0.8:.2f})")

    # 9. SHIPPING
    ship1 = e.get("ShippingService-1:Option", "")
    ship1_cost = e.get("ShippingService-1:Cost", "")
    ship2 = e.get("ShippingService-2:Option", "")
    ship2_cost = e.get("ShippingService-2:Cost", "")
    print(f"  Shipping: {ship1} @ ${ship1_cost}, {ship2} @ ${ship2_cost}")
    check(tag, "USPS shipping", "USPSParcel", ship1)
    check(tag, "UPS shipping", "UPSGround", ship2)
    check(tag, "USPS cost", "14.99", ship1_cost)
    check(tag, "UPS cost", "18.99", ship2_cost)

    # 10. RETURNS & LOCATION
    returns = e.get("*ReturnsAcceptedOption", "")
    location = e.get("*Location", "")
    handling = e.get("*DispatchTimeMax", "")
    print(f"  Returns: {returns} | Location: {location} | Handling: {handling} days")
    check(tag, "Returns", "ReturnsNotAccepted", returns)
    check(tag, "Location", "Boca Raton, FL", location)
    check(tag, "Handling time", "3", handling)

    # 11. PHOTOS - check count and that they come from right service tag folder
    pics = e.get("PicURL", "")
    pic_urls = pics.split("|") if pics else []
    print(f"  Photos: {len(pic_urls)} URLs")
    # Verify all URLs contain the correct service tag
    wrong_tag_photos = [u for u in pic_urls if f"/{tag}/" not in u]
    if wrong_tag_photos:
        issues.append(f"  [{tag}] PHOTO MISMATCH: {len(wrong_tag_photos)} photos don't reference tag {tag}!")
    else:
        checks += 1
        print(f"  Photos: All {len(pic_urls)} URLs correctly reference /{tag}/")

    # Verify local photo count matches
    local_photos_dir = os.path.join(PHOTOS_DIR, tag)
    if os.path.isdir(local_photos_dir):
        local_count = len([f for f in os.listdir(local_photos_dir)
                          if f.lower().endswith((".jpg", ".jpeg", ".png"))])
        checks += 1
        if local_count != len(pic_urls):
            issues.append(f"  [{tag}] PHOTO COUNT: {local_count} local files vs {len(pic_urls)} URLs in CSV!")
        else:
            print(f"  Photos: Local count ({local_count}) matches CSV URL count")

    # Verify iCloud source exists and matches
    icloud_dir = os.path.join(ICLOUD_DIR, tag)
    if os.path.isdir(icloud_dir):
        icloud_count = len([f for f in os.listdir(icloud_dir)
                           if f.lower().endswith((".jpg", ".jpeg", ".png"))])
        icloud_files = set(f for f in os.listdir(icloud_dir)
                          if f.lower().endswith((".jpg", ".jpeg", ".png")))
        local_files = set(f for f in os.listdir(local_photos_dir)
                         if f.lower().endswith((".jpg", ".jpeg", ".png")))
        checks += 1
        if icloud_files != local_files:
            missing = icloud_files - local_files
            extra = local_files - icloud_files
            if missing:
                issues.append(f"  [{tag}] MISSING from repo: {missing}")
            if extra:
                issues.append(f"  [{tag}] EXTRA in repo (not in iCloud): {extra}")
        else:
            print(f"  Photos: iCloud ({icloud_count}) matches repo ({local_count}) - verified identical")
    else:
        issues.append(f"  [{tag}] iCloud folder not found: {icloud_dir}")

    # 12. FEATURES
    os_ebay = e.get("C:Operating System", "")
    print(f"  OS: {os_ebay}")
    check(tag, "OS contains Windows 11", "Windows 11", os_ebay, exact=False)

    brand = e.get("C:Brand", "")
    check(tag, "Brand is Dell", "Dell", brand)

    color = e.get("C:Color", "")
    check(tag, "Color", a["color"], color, exact=False)

    model_ebay = e.get("C:Model", "")
    print(f"  Model: audit={a['model']}, eBay={model_ebay}")
    check(tag, "Model contains model name", a["model"], model_ebay, exact=False)


# ─── SUMMARY ────────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print(f"  AUDIT COMPLETE: {checks} checks performed")

if issues:
    print(f"  ISSUES FOUND: {len(issues)}")
    print("=" * 70)
    for issue in issues:
        print(issue)
else:
    print(f"  ALL CHECKS PASSED")
print("=" * 70)
