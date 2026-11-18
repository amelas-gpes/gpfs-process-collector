"""mktext.py PROCESSES.json OUT_DIR -> one <ID>.txt per process and index.json (title, pages, section names).

PROCESSES.json is what slice.py writes. scripted.py reads OUT_DIR as the text/ folder beside lib/.
"""
import json, os, re, sys

source, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
index = {}
for pid, p in json.load(open(source)).items():
    text = p["text"]
    heads = [(m.start(), int(m.group(1)), m.group(2).strip()) for m in re.finditer(r"^(\d{1,2})\.\s+([A-Z][^\n]{3,80})$", text, re.M)]
    # The first run of headings is the per-process contents list; the body follows it.
    body = [h for h in heads if h[0] > 5000] or heads
    open(os.path.join(out, pid + ".txt"), "w", encoding="utf-8").write(f"{pid} — {p['title']}\n(library pages {p['start']}-{p['end']})\n\n" + text)
    index[pid] = {"title": p["title"], "pages": [p["start"], p["end"]], "chars": len(text), "sections": {str(n): name for _, n, name in body}}
json.dump(index, open(os.path.join(out, "index.json"), "w"), indent=1)
print(len(index), "process text files written to", out)
