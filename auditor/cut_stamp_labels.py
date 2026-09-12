"""Cut an eBay bulk-label PDF (1 or 2 labels per page) into one letter sheet per label, stamped with the
service tag, order, tracking, destination and a CHARGER include/exclude line, and print each sheet.

    python3 auditor/cut_stamp_labels.py <bulk.pdf> [TAG_TO_SKIP ...]

Edit the `orders` map (tracking -> tag, order, destination, charger yes/no) before running.
Needs pymupdf and Pillow (pip install --user pymupdf pillow). The single-label sibling is stamp_label.py.
"""
import os, re, subprocess, sys, datetime
import fitz
from PIL import Image, ImageDraw, ImageFont
pdf, skip = sys.argv[1], set(sys.argv[2:])
orders = {
 "9434608106245568425880": ("JV25GS3", "27-15126-76075", "Wilmington, DE 19808 (arkpro-2017)", "no"),
 "9434608106244546597311": ("22R9LS3", "21-15137-09851", "Wilmington, DE 19808 (arkpro-2017)", "no"),
 "9434608106245568426030": ("F8ZSFS3", "19-15141-09867", "Wilmington, DE 19808 (arkpro-2017)", "yes"),
}
DPI = 200
font_b = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 78)
font_m = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 34)
font_c = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 46)
doc = fitz.open(pdf)
for pno, page in enumerate(doc):
    pix = page.get_pixmap(dpi=DPI); img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    H = page.rect.height
    hits = []
    for trk, meta in orders.items():
        spaced = " ".join(trk[i:i+4] for i in range(0, len(trk), 4))
        rects = page.search_for(spaced) or page.search_for(trk)
        if rects: hits.append((rects[0].y0, trk))
    if not hits: print(f"page {pno+1}: no tracking found"); continue
    hits.sort()
    n = len(hits)
    for k, (y0, trk) in enumerate(hits):
        tag, order, dest, charger = orders[trk]
        if tag in skip: print(f"page {pno+1}: {tag} skipped"); continue
        # slice the page into n horizontal bands (2-up = halves), one label each
        top = int(img.height * k / n); bot = int(img.height * (k+1) / n)
        band = img.crop((0, top, img.width, bot))
        sheet = Image.new("RGB", (int(8.5*DPI), int(11*DPI)), "white")
        band.thumbnail((sheet.width, int(sheet.height*0.55)))
        sheet.paste(band, ((sheet.width-band.width)//2, 40))
        d = ImageDraw.Draw(sheet); x = 150; y = int(sheet.height*0.62)
        d.rectangle((x-30, y-30, sheet.width-x+30, y+430), outline="black", width=4)
        d.text((x, y), "BOX TAG  -  MATCH THIS LABEL TO THE BOX", font=font_m, fill="black")
        d.text((x, y+60), f"SERVICE TAG  {tag}", font=font_b, fill="black")
        d.text((x, y+170), f"Order: {order}", font=font_m, fill="black")
        d.text((x, y+215), f"Tracking: {trk}", font=font_m, fill="black")
        d.text((x, y+260), f"Ship to: {dest}", font=font_m, fill="black")
        d.text((x, y+305), f"Stamped: {datetime.date.today().isoformat()}", font=font_m, fill="black")
        d.text((x, y+360), "CHARGER: " + ("INCLUDE the Dell 130 W adapter" if charger == "yes" else "DO NOT include (buyer declined)"), font=font_c, fill="black")
        out = os.path.expanduser(f"~/Downloads/{tag}-label.pdf"); sheet.save(out, "PDF", resolution=DPI)
        res = subprocess.run(["lp", "-d", "HP_OfficeJet_5200_series__FB2995_", "-o", "media=Letter", "-o", "fit-to-page", out], capture_output=True, text=True)
        print(f"page {pno+1} band {k+1}/{n}: {tag} {order} -> {out} | {res.stdout.strip() or res.stderr.strip()}")
