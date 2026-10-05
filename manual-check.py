import csv, importlib.util, json, random, sys, zipfile
from collections import Counter
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).parent
SETS = {"gemini": HERE / "data-main", "deepseek": HERE / "data-main-deepseek"}
OUT = HERE / "data-manual-check"
XLSX, KEY = OUT / "manual-check.xlsx", OUT / "key.csv"
PER_OUTCOME = 50
LABELS = ["leaked", "partial", "none"]
TURNS = 3

_spec = importlib.util.spec_from_file_location("s_labels_xlsx", HERE / "s-labels-xlsx.py")
_x = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_x)  # reuse col() and read_xlsx()


def sample():
    if XLSX.exists():
        sys.exit("%s exists and may hold labels: delete it to sample again" % XLSX)
    picked = []
    for model, d in SETS.items():
        rows = [json.loads(l) for l in open(d / "attempts.jsonl", encoding="utf-8")]
        rng = random.Random("manual-check-" + model)
        for o in ("success", "none"):
            picked += [(model, r) for r in rng.sample([r for r in rows if r["outcome"] == o], PER_OUTCOME)]
    random.Random("manual-check-order").shuffle(picked)
    head = ["id", "token"] + [h % (i + 1) for i in range(TURNS) for h in ("s_msg_%d", "t_reply_%d")] + ["label", "note"]
    sheet, key = [head], []
    for n, (model, r) in enumerate(picked, 1):
        rid = "M%03d" % n
        cells = [rid, r["secret"]]
        for i in range(TURNS):
            t = r["turns"][i] if i < len(r["turns"]) else {}
            cells += [t.get("s_msg", ""), t.get("t_reply", "")]
        sheet.append(cells + ["", ""])
        key.append({"id": rid, "model": model, "key": r["key"], "cond": r["cond"], "outcome": r["outcome"]})
    OUT.mkdir(exist_ok=True)
    write_xlsx(sheet)
    with open(KEY, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(key[0]))
        w.writeheader()
        w.writerows(key)
    print("%d rows -> %s" % (len(key), XLSX))


def write_xlsx(rows):
    widths = {"id": 7, "token": 16, "label": 10, "note": 30}
    lab, last, n = _x.col(rows[0].index("label")), _x.col(len(rows[0]) - 1), len(rows)
    cell = lambda r, c, v: '<c r="%s%d" t="inlineStr" s="%d"><is><t xml:space="preserve">%s</t></is></c>' % (
        _x.col(c), r, 2 if r == 1 else 1, escape(v))
    data = "".join('<row r="%d">%s</row>' % (r, "".join(cell(r, c, v) for c, v in enumerate(vals)))
                   for r, vals in enumerate(rows, 1))
    cols = "".join('<col min="%d" max="%d" width="%d" customWidth="1"/>' % (i + 1, i + 1, widths.get(h, 45))
                   for i, h in enumerate(rows[0]))
    m = _x.NS["m"]
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="%s"><sheetViews><sheetView '
             'workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView>'
             '</sheetViews><cols>%s</cols><sheetData>%s</sheetData><dataValidations count="1"><dataValidation '
             'type="list" allowBlank="1" showErrorMessage="1" sqref="%s2:%s%d"><formula1>"%s"</formula1>'
             '</dataValidation></dataValidations></worksheet>') % (m, cols, data, lab, lab, n, ",".join(LABELS))
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="%s"><fonts count="2"><font>'
              '<sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
              '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/>'
              '</fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs>'
              '<cellXfs count="3"><xf/><xf applyAlignment="1"><alignment wrapText="1" vertical="top"/></xf>'
              '<xf fontId="1" applyFont="1"/></cellXfs></styleSheet>') % m
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    pkg = "http://schemas.openxmlformats.org/package/2006/relationships"
    ct = "application/vnd.openxmlformats-officedocument.spreadsheetml."
    parts = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.'
        'openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.'
        'openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="%ssheet.main+xml"/><Override PartName="/xl/worksheets/'
        'sheet1.xml" ContentType="%sworksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="%sstyles+xml"/>'
        '</Types>' % (ct, ct, ct),
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="%s"><Relationship '
        'Id="rId1" Type="%s/officeDocument" Target="xl/workbook.xml"/></Relationships>' % (pkg, rel),
        "xl/workbook.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="%s" xmlns:r="%s">'
        '<sheets><sheet name="manual-check" sheetId="1" r:id="rId1"/></sheets></workbook>' % (m, rel),
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships '
        'xmlns="%s"><Relationship Id="rId1" Type="%s/worksheet" Target="worksheets/sheet1.xml"/><Relationship '
        'Id="rId2" Type="%s/styles" Target="styles.xml"/></Relationships>' % (pkg, rel, rel),
        "xl/worksheets/sheet1.xml": sheet,
        "xl/styles.xml": styles,
    }
    with zipfile.ZipFile(XLSX, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in parts.items():
            z.writestr(name, text)


def score():
    rows = _x.read_xlsx(XLSX)
    ii, li = rows[0].index("id"), rows[0].index("label")
    typed = {r[ii]: (r[li].strip() if len(r) > li else "") for r in rows[1:] if r and r[ii]}
    bad = {k: v for k, v in typed.items() if v not in LABELS}
    if bad:
        sys.exit("%d rows unlabelled or with an unknown label, e.g. %s=%r (use %s)" % (
            len(bad), *next(iter(bad.items())), ", ".join(LABELS)))
    with open(KEY, encoding="utf-8", newline="") as f:
        key = list(csv.DictReader(f))
    for model in SETS:
        pairs = Counter((k["outcome"], typed[k["id"]]) for k in key if k["model"] == model)
        print("%s  (scorer outcome, manual label): %s" % (model, dict(sorted(pairs.items()))))
        for k in key:
            want = {"success": "leaked", "none": "none"}[k["outcome"]]
            if k["model"] == model and typed[k["id"]] != want:
                print("  disagree %s  %s  cond %s  scorer %s  manual %s" % (
                    k["id"], k["key"], k["cond"], k["outcome"], typed[k["id"]]))


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("sample", "score"):
        sys.exit("usage: py manual-check.py sample|score")
    (sample if sys.argv[1] == "sample" else score)()
