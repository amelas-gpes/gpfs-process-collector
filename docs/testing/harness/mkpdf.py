"""mkpdf.py SRC OUT first last  -> PDF with source pages first..last (1-based, inclusive), link annotations dropped."""
import sys
from pypdf import PdfReader, PdfWriter
src, out, a, b = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
r = PdfReader(src); w = PdfWriter()
for n in range(a, b + 1):
    p = r.pages[n - 1]
    if "/Annots" in p: del p["/Annots"]
    w.add_page(p)
w.write(out)
