#!/usr/bin/env python3
"""Stamp the service tag (and order / tracking / destination) onto an eBay shipping-label PDF
so the shipper can match the label to the box, then optionally print it.

    python3 auditor/stamp_label.py --tag GT3X9S3 --order 07-15145-77219 \
        --tracking 9434608106245556825166 --dest "Bear, DE 19701" [--pdf path] [--out path] [--print]

--pdf defaults to ~/Downloads/eBay label <order>.pdf (eBay's "Download label" file name).
Needs pypdf and reportlab (pip install --user pypdf reportlab).
"""
import argparse
import datetime
import io
import os
import subprocess
import sys

from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas

PRINTER = "HP_OfficeJet_5200_series__FB2995_"


def build_overlay(width, height, tag, order, tracking, dest):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(width, height))
    # eBay's letter-size label sits in the upper-left; the lower half of the page is blank.
    x = 54
    y = height * 0.42
    c.setLineWidth(1.5)
    c.rect(x - 12, y - 118, width - 2 * (x - 12), 168)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(x, y + 30, "BOX TAG  -  MATCH THIS LABEL TO THE BOX")
    c.setFont("Helvetica-Bold", 40)
    c.drawString(x, y - 16, f"SERVICE TAG  {tag}")
    c.setFont("Helvetica", 13)
    line = y - 44
    for label, value in (("Order", order), ("Tracking", tracking), ("Ship to", dest),
                         ("Stamped", datetime.date.today().isoformat())):
        if value:
            c.drawString(x, line, f"{label}: {value}")
            line -= 18
    c.save()
    buf.seek(0)
    return PdfReader(buf).pages[0]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tag", required=True, help="service tag (eBay SKU / custom label)")
    ap.add_argument("--order", default="", help="eBay order number")
    ap.add_argument("--tracking", default="")
    ap.add_argument("--dest", default="", help="destination city/state/ZIP for the sheet")
    ap.add_argument("--pdf", help="label PDF (default: ~/Downloads/eBay label <order>.pdf)")
    ap.add_argument("--out", help="output PDF (default: <pdf dir>/<tag>-label.pdf)")
    ap.add_argument("--print", dest="do_print", action="store_true", help="send the stamped PDF to the printer")
    a = ap.parse_args()

    pdf = a.pdf or os.path.expanduser(f"~/Downloads/eBay label {a.order}.pdf")
    if not os.path.isfile(pdf):
        sys.exit(f"[!] label PDF not found: {pdf}")
    out = a.out or os.path.join(os.path.dirname(pdf), f"{a.tag}-label.pdf")

    reader = PdfReader(pdf)
    writer = PdfWriter()
    for page in reader.pages:
        w, h = float(page.mediabox.width), float(page.mediabox.height)
        page.merge_page(build_overlay(w, h, a.tag, a.order, a.tracking, a.dest))
        writer.add_page(page)
    with open(out, "wb") as f:
        writer.write(f)
    print(f"[OK] stamped {a.tag} -> {out}")

    if a.do_print:
        r = subprocess.run(["lp", "-d", PRINTER, "-o", "media=Letter", "-o", "fit-to-page", out],
                           capture_output=True, text=True)
        print(r.stdout.strip() or r.stderr.strip())


if __name__ == "__main__":
    main()
