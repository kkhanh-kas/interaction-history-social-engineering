import csv, re, sys, zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

import pilot

LABELS = list(pilot.LABELS)
WIDTHS = {"s_msg": 70, "prev_t_reply": 70, "label": 22, "hash": 18}
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def col(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def to_xlsx(d):
    src, dst = d / "s-messages.csv", d / "s-messages.xlsx"
    rows = read_csv(src)
    if dst.exists() and dst.stat().st_mtime > src.stat().st_mtime:
        # the xlsx may hold labels typed after the last to-csv, and overwriting would lose them
        sys.exit("%s is newer than the CSV: run to-csv first, or delete it to start over" % dst.name)
    head = list(rows[0])
    lab = col(head.index("label"))
    cell = lambda r, c, v: '<c r="%s%d" t="inlineStr" s="%d"><is><t xml:space="preserve">%s</t></is></c>' % (
        col(c), r, 1 if r > 1 else 2, escape(v))
    data = "".join('<row r="%d">%s</row>' % (r, "".join(cell(r, c, v) for c, v in enumerate(vals)))
                   for r, vals in enumerate([head] + [[x[h] for h in head] for x in rows], 1))
    cols = "".join('<col min="%d" max="%d" width="%d" customWidth="1"/>' % (i + 1, i + 1, WIDTHS.get(h, 9))
                   for i, h in enumerate(head))
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<worksheet xmlns="%s"><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
             'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols>%s</cols><sheetData>%s</sheetData>'
             '<autoFilter ref="A1:%s%d"/><dataValidations count="1"><dataValidation type="list" allowBlank="1" '
             'showErrorMessage="1" sqref="%s2:%s%d"><formula1>"%s"</formula1></dataValidation></dataValidations>'
             '</worksheet>') % (NS["m"], cols, data, col(len(head) - 1), len(rows) + 1, lab, lab, len(rows) + 1,
                                ",".join(LABELS))
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="%s">'
              '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/>'
              '<name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill>'
              '<fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border/></borders>'
              '<cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="3"><xf/>'
              '<xf applyAlignment="1"><alignment wrapText="1" vertical="top"/></xf>'
              '<xf fontId="1" applyFont="1"/></cellXfs></styleSheet>') % NS["m"]
    parts = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="%s" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="s-messages" sheetId="1" r:id="rId1"/></sheets><definedNames><definedName name="_xlnm._FilterDatabase" localSheetId="0" hidden="1">\'s-messages\'!$A$1:$%s$%d</definedName></definedNames></workbook>' % (NS["m"], col(len(head) - 1), len(rows) + 1),
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": sheet,
        "xl/styles.xml": styles,
    }
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in parts.items():
            z.writestr(name, text)
    print("%d rows -> %s" % (len(rows), dst))


def read_xlsx(path):
    """Rows of the first sheet as lists of strings. Handles both inline strings and the shared strings table
    Excel switches to when it saves."""
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
                shared.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])))
        sheet = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    out = []
    for row in sheet.iter("{%s}row" % NS["m"]):
        vals = {}
        for c in row.findall("m:c", NS):
            letters = re.match(r"[A-Z]+", c.get("r")).group()
            idx = 0
            for ch in letters:
                idx = idx * 26 + ord(ch) - 64
            t, v = c.get("t"), c.find("m:v", NS)
            if t == "inlineStr":
                text = "".join(x.text or "" for x in c.iter("{%s}t" % NS["m"]))
            elif t == "s":
                text = shared[int(v.text)]
            else:
                text = v.text if v is not None and v.text else ""
            vals[idx - 1] = text
        out.append([vals.get(i, "") for i in range(max(vals) + 1)] if vals else [])
    return out


def to_csv(d):
    src, dst = d / "s-messages.xlsx", d / "s-messages.csv"
    xrows = read_xlsx(src)
    head = xrows[0]
    hi, li = head.index("hash"), head.index("label")
    labels = {}
    for r in xrows[1:]:
        if len(r) <= hi or not r[hi]:
            continue
        lab = r[li].strip() if len(r) > li else ""
        if lab and lab not in LABELS:
            sys.exit("unknown label %r on hash %s (use %s)" % (lab, r[hi], ", ".join(LABELS)))
        if labels.setdefault(r[hi], lab) != lab:
            sys.exit("hash %s has two different labels in the xlsx" % r[hi])
    rows = read_csv(dst)
    missing = sorted(set(labels) - {x["hash"] for x in rows})
    if missing:  # a hash Excel altered, or an xlsx from an older export
        sys.exit("hashes in the xlsx not found in the CSV: %s" % ", ".join(missing[:5]))
    lost = [x["hash"] for x in rows if x["label"].strip() and not labels.get(x["hash"])]
    if lost:
        sys.exit("%d CSV labels would be blanked (e.g. %s): the xlsx is older than the CSV, run to-xlsx" % (
            len(lost), lost[0]))
    for x in rows:
        x["label"] = labels.get(x["hash"], "")
    with open(dst, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    done = sum(bool(x["label"]) for x in rows)
    print("%d/%d labelled -> %s" % (done, len(rows), dst))


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("to-xlsx", "to-csv"):
        sys.exit("usage: py s-labels-xlsx.py to-xlsx|to-csv [data dir]")
    d = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).parent / "data-pilot-v2"
    (to_xlsx if sys.argv[1] == "to-xlsx" else to_csv)(d)
