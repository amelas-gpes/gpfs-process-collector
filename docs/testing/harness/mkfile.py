"""mkfile.py OUT.csv|OUT.xlsx SPEC.json
CSV:  SPEC is a list of rows (each a list of cells).
XLSX: SPEC is {"sheets": {"Sheet name": [[row], ...], ...}, "hidden": ["Sheet name", ...]}"""
import csv, json, sys
out, spec = sys.argv[1], json.load(open(sys.argv[2]))
if out.lower().endswith(".csv"):
    with open(out, "w", newline="", encoding="utf-8-sig") as f: csv.writer(f).writerows(spec)
else:
    from openpyxl import Workbook
    wb = Workbook(); wb.remove(wb.active)
    for name, rows in spec["sheets"].items():
        ws = wb.create_sheet(name[:31])
        for r in rows: ws.append(r)
        if name in spec.get("hidden", []): ws.sheet_state = "hidden"
    wb.save(out)
print("wrote", out)
