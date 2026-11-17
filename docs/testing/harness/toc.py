import sys, json, re, collections
pages = json.load(open(sys.argv[1]))
pat = re.compile(r'\b((?:FA|MC|GP|IR|TX|CO|HR|IT|LG|OP)-\d{2}[A-Z]?)\b')
first = {}; cnt = collections.Counter()
for i, t in enumerate(pages):
    for m in pat.finditer(t):
        cnt[m.group(1)] += 1
        first.setdefault(m.group(1), i+1)
print(len(cnt))
for k in sorted(cnt): print(k, cnt[k], first[k])
for i in range(0, 6):
    print(f"=== page {i+1}"); print(pages[i][:1800])
