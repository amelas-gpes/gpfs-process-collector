import sys, json, re
pages = json.load(open(sys.argv[1])); out = sys.argv[2]
toc = pages[0] + "\n" + pages[1]
ents = re.findall(r'((?:FA|MC|GP)-\d{2}[A-Z]?) — (.+?) (\d+)\s*$', toc, re.M)
ents = [(i, t.strip(), int(p)) for i, t, p in ents]
allp = sorted(set(int(x) for x in re.findall(r' (\d+)\s*$', toc, re.M)))
res = {}
for i, t, p in ents:
    nxt = min([q for q in allp if q > p], default=len(pages) + 1)
    text = "\n".join(pages[p-1:nxt-1])
    res[i] = {"id": i, "title": t, "start": p, "end": nxt - 1, "chars": len(text), "text": text}
    print(i, t, p, nxt - 1, len(text))
json.dump(res, open(out, "w"))
print(len(res))
