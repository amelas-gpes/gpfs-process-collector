import sys, json, re
from pypdf import PdfReader
src, out = sys.argv[1], sys.argv[2]
r = PdfReader(src)
pages = []
for i, p in enumerate(r.pages):
    try: t = p.extract_text() or ""
    except Exception as e: t = ""
    pages.append(t)
json.dump(pages, open(out, "w"))
print(len(pages), sum(len(t) for t in pages))
def walk(o, d=0):
    for x in o:
        if isinstance(x, list): walk(x, d+1)
        else:
            try: pn = r.get_destination_page_number(x)
            except Exception: pn = -1
            if d <= 1: print("  "*d + f"{x.title} @p{pn+1}")
try: walk(r.outline)
except Exception as e: print("no outline", e)
