"""
SETU360 - AI Procurement Reconciliation for Regional Contractors
Three-way matching:  Purchase Order  ->  Delivery Challan  ->  Invoice
Built on Streamlit + Google Gemini (extraction) + rule-based matching engine.
"""

import io
import os
import re
import json
import copy
import html
from collections import OrderedDict

try:
    import pymupdf as fitz  # PyMuPDF (new name)
except ImportError:
    import fitz  # PyMuPDF (old name)
import pdfplumber
import pytesseract
import streamlit as st
import google.generativeai as genai
from dotenv import load_dotenv
from fuzzywuzzy import fuzz
from PIL import Image

load_dotenv()

st.set_page_config(
    page_title="Setu360 | AI Procurement Reconciliation",
    page_icon="🌉",
    layout="wide",
)

# =====================================================================
# SETTINGS
# =====================================================================
QTY_EPS = 0.001        # quantity tolerance
PRICE_TOL = 0.005      # 0.5% price tolerance
FUZZY_MIN = 80         # fuzzy match threshold for names / items
DEMO_MODE = "Demo scenarios (no PDFs needed)"
LIVE_MODE = "Upload PDFs (AI extraction)"

# =====================================================================
# STYLING
# =====================================================================
CSS = """
<style>
#MainMenu {visibility: hidden;} footer {visibility: hidden;}
.block-container {padding-top: 1.5rem; max-width: 1250px;}
section[data-testid="stSidebar"] .stButton > button {width: 100%;}
.s360-hero {background: linear-gradient(120deg,#0f172a 0%,#1e1b4b 55%,#4338ca 100%);
  border-radius: 14px; padding: 26px 32px; margin-bottom: 18px; color: #fff;}
.s360-brand {font-size: 2.1rem; font-weight: 800; letter-spacing: 3px;}
.s360-brand span {color: #5eead4;}
.s360-tag {font-size: 1.05rem; color: #c7d2fe; margin-top: 2px;}
.s360-flow {margin-top: 14px; font-size: .78rem; letter-spacing: 1px; font-weight: 600;}
.s360-flow .pill {background: rgba(255,255,255,.14); border: 1px solid rgba(255,255,255,.25);
  padding: 4px 12px; border-radius: 999px;}
.s360-flow .arr {margin: 0 8px; color: #5eead4;}
.card {background: #fff; color: #0f172a; border: 1px solid #e2e8f0; border-radius: 12px;
  padding: 16px 18px; margin-bottom: 14px; box-shadow: 0 1px 3px rgba(15,23,42,.06);}
.card-title {font-weight: 700; font-size: 1.02rem; margin-bottom: 10px; color: #1e1b4b;}
.kv {display: flex; justify-content: space-between; font-size: .88rem; padding: 3px 0;
  border-bottom: 1px dashed #e2e8f0;}
.kv span {color: #64748b;} .kv b {text-align: right;}
.doc-total {text-align: right; margin-top: 10px; font-size: .95rem;}
.s360-table {width: 100%; border-collapse: collapse; font-size: .84rem; margin-top: 10px; color: #0f172a;}
.s360-table th {background: #f1f5f9; text-align: left; padding: 8px; border: 1px solid #e2e8f0; color: #334155;}
.s360-table td {padding: 8px; border: 1px solid #e2e8f0; background: #fff;}
.s360-table .num {text-align: right; white-space: nowrap;}
.s360-table tr.row-fail td {background: #fef2f2;}
.s360-table tr.row-warn td {background: #fffbeb;}
.s360-table td.bad {color: #b91c1c; font-weight: 700;}
.chip {display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: .72rem; font-weight: 700;}
.chip-ok {background: #dcfce7; color: #166534;}
.chip-fail {background: #fee2e2; color: #991b1b;}
.chip-warn {background: #fef3c7; color: #92400e;}
.verdict {border-radius: 12px; padding: 18px 24px; margin: 6px 0 16px 0; font-size: 1.35rem; font-weight: 800;}
.verdict small {display: block; font-size: .92rem; font-weight: 500; margin-top: 4px;}
.verdict-ok {background: #dcfce7; color: #14532d; border: 2px solid #16a34a;}
.verdict-fail {background: #fee2e2; color: #7f1d1d; border: 2px solid #dc2626;}
.metric {background: #fff; color: #0f172a; border: 1px solid #e2e8f0; border-radius: 12px; padding: 14px 16px; text-align: center;}
.metric .v {font-size: 1.6rem; font-weight: 800; color: #1e1b4b;}
.metric .l {font-size: .78rem; color: #64748b; text-transform: uppercase; letter-spacing: .5px;}
.pipe {display: flex; align-items: stretch; gap: 8px; margin-bottom: 16px;}
.pipe .node {flex: 1; background: #fff; color: #0f172a; border: 1px solid #e2e8f0; border-top: 4px solid #4338ca;
  border-radius: 10px; padding: 12px 14px; font-size: .85rem;}
.pipe .node .t {font-size: .72rem; color: #64748b; font-weight: 700; letter-spacing: 1px;}
.pipe .node .n {font-size: 1.05rem; font-weight: 800; color: #1e1b4b;}
.pipe .link {align-self: center; text-align: center; min-width: 110px; font-size: .75rem; font-weight: 700;}
.pipe .link .a {font-size: 1.4rem; color: #94a3b8;}
.issue {border-left: 5px solid #dc2626; background: #fef2f2; color: #7f1d1d; padding: 10px 14px; border-radius: 6px; margin-bottom: 8px; font-size: .9rem;}
.warnbox {border-left: 5px solid #d97706; background: #fffbeb; color: #78350f; padding: 10px 14px; border-radius: 6px; margin-bottom: 8px; font-size: .9rem;}
.tag {display: inline-block; background: #7f1d1d; color: #fff; font-size: .68rem; padding: 1px 8px; border-radius: 4px; margin-right: 8px; font-weight: 700;}
.tag.w {background: #92400e;}
.agent {border-left: 4px solid #4338ca; background: #eef2ff; color: #1e1b4b; padding: 14px 18px; border-radius: 8px; font-size: .93rem;}
.agent p {margin: 6px 0;}
.how {background: #fff; color: #0f172a; border: 1px solid #e2e8f0; border-radius: 12px; padding: 18px; min-height: 150px;}
.how .num {font-size: 1.6rem; font-weight: 800; color: #4338ca;}
.s360-footer {text-align: center; color: #94a3b8; font-size: .78rem; margin-top: 30px;}
</style>
"""


def H(s):
    """Collapse HTML to one line so Streamlit's markdown never treats it as code."""
    return " ".join(line.strip() for line in s.splitlines() if line.strip())


st.markdown(H(CSS), unsafe_allow_html=True)

# =====================================================================
# SMALL HELPERS
# =====================================================================
CUR = "₹"


def esc(v):
    if v is None or str(v).strip() == "":
        return "—"
    return html.escape(str(v))


def to_float(v):
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[^0-9.,\-]", "", str(v))
    if not re.search(r"\d", s):
        return 0.0
    if "," in s and "." in s:
        s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".") if re.search(r",\d{1,2}$", s) else s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def money(x):
    return f"{CUR}{x:,.2f}"


def qty(x):
    if x is None:
        return "—"
    return f"{x:,.0f}" if float(x).is_integer() else f"{x:,.2f}"


def chip(status, text=None):
    labels = {"ok": "MATCH", "fail": "MISMATCH", "warn": "CHECK"}
    return f'<span class="chip chip-{status}">{text or labels[status]}</span>'


def table(headers, rows, num_cols=()):
    """rows: list of (cells, row_class, bad_cell_indexes)"""
    out = "<table class='s360-table'><thead><tr>"
    out += "".join(f"<th>{h}</th>" for h in headers) + "</tr></thead><tbody>"
    for cells, row_class, bad in rows:
        out += f"<tr class='{row_class}'>"
        for i, c in enumerate(cells):
            cls = []
            if i in num_cols:
                cls.append("num")
            if i in bad:
                cls.append("bad")
            out += f"<td class='{' '.join(cls)}'>{c}</td>"
        out += "</tr>"
    out += "</tbody></table>"
    return out


# =====================================================================
# PDF TEXT EXTRACTION (existing technology: pdfplumber + Tesseract OCR)
# =====================================================================
def get_text_from_pdf(file_bytes):
    try:
        text = ""
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                t = page.extract_text(x_tolerance=2)
                if t:
                    text += t + "\n"
        if text.strip():
            return text.strip()
    except Exception as e:
        st.warning(f"Text extraction failed ({e}). Trying OCR instead.")
    try:
        text = ""
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        for n in range(len(doc)):
            pix = doc.load_page(n).get_pixmap(dpi=300)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            text += pytesseract.image_to_string(img) + "\n"
        doc.close()
        return text.strip()
    except Exception as e:
        st.error(f"OCR failed: {e}")
        return ""


# =====================================================================
# GEMINI EXTRACTION (existing technology)
# =====================================================================
EXTRACTION_PROMPT = """
You are an expert accounts-payable and site-procurement specialist.
You are given the text of THREE documents that belong to one transaction:
1. PURCHASE ORDER (PO) - what the contractor ordered.
2. DELIVERY CHALLAN (DC) - the goods delivery / receipt note. Its quantities are what was ACTUALLY DELIVERED.
3. INVOICE - what the vendor is billing.

The INVOICE text may contain several invoices. Aggregate them: list every unique invoice number separated by commas,
use the latest date, sum the quantities of identical items, and sum the totals.
The DELIVERY CHALLAN may list several trips/challans. Aggregate them the same way.

For each item extract: description, quantity (number), price (UNIT price as a number; use 0 if not shown).
Numbers must be plain numbers without currency symbols or thousands separators.

Return ONLY one minified JSON object with exactly this structure:
{
"po_data": {"po_no": "...", "date": "...", "vendor": "...", "items": [{"description": "...", "quantity": 0, "price": 0}], "total": 0},
"challan_data": {"challan_no": "...", "po_no": "...", "date": "...", "vendor": "...", "items": [{"description": "...", "quantity": 0, "price": 0}]},
"invoice_data": {"invoice_no": "...", "po_no": "...", "date": "...", "vendor": "...", "items": [{"description": "...", "quantity": 0, "price": 0}], "total": 0}
}
In challan_data and invoice_data, "po_no" is the PO number referenced on that document (empty string if none).
"""


def call_gemini(payload):
    key = os.environ.get("GOOGLE_API_KEY")
    if not key:
        try:
            key = st.secrets["GOOGLE_API_KEY"]
        except Exception:
            key = None
    if not key:
        st.error("GOOGLE_API_KEY is not set. Add it as a secret (or .env file), or use the Demo scenarios mode.")
        return None
    genai.configure(api_key=key)
    last_error = None
    for model_name in ("models/gemini-pro-latest", "models/gemini-flash-latest"):
        try:
            model = genai.GenerativeModel(model_name)
            cfg = genai.types.GenerationConfig(temperature=0, response_mime_type="application/json")
            resp = model.generate_content(payload, generation_config=cfg)
            text = re.sub(r"^```(?:json)?|```$", "", resp.text.strip(), flags=re.M).strip()
            data = json.loads(text)
            if isinstance(data, dict) and all(
                isinstance(data.get(k), dict) for k in ("po_data", "challan_data", "invoice_data")
            ):
                return data
            last_error = "AI response was missing one of the three documents."
        except Exception as e:  # try the next model
            last_error = e
    st.error(f"AI extraction failed: {last_error}. Please click the button again.")
    return None


# =====================================================================
# DEMO DATA (so the project can be demonstrated without any PDFs)
# =====================================================================
VENDOR = "Sharma Steel & Cement Traders"
BASE_ITEMS = [
    ("TMT Steel Bar Fe500 12mm (kg)", 5000, 62.00),
    ("OPC Cement 53 Grade, 50kg bag", 400, 385.00),
    ("Red Clay Bricks (nos)", 10000, 8.50),
]


def build_demo(dc_qty=(5000, 400, 10000), inv_qty=(5000, 400, 10000),
               inv_price=(62.00, 385.00, 8.50), inv_vendor=None):
    po = {
        "po_no": "PO-2026-0417", "date": "02-Sep-2026", "vendor": VENDOR,
        "items": [{"description": d, "quantity": q, "price": p} for d, q, p in BASE_ITEMS],
        "total": sum(q * p for _, q, p in BASE_ITEMS),
    }
    dc = {
        "challan_no": "DC-8841", "po_no": "PO-2026-0417", "date": "09-Sep-2026", "vendor": VENDOR,
        "items": [{"description": BASE_ITEMS[i][0], "quantity": dc_qty[i], "price": 0} for i in range(3)],
    }
    inv = {
        "invoice_no": "INV-3302", "po_no": "PO-2026-0417", "date": "12-Sep-2026",
        "vendor": inv_vendor or VENDOR,
        "items": [{"description": BASE_ITEMS[i][0], "quantity": inv_qty[i], "price": inv_price[i]} for i in range(3)],
        "total": sum(inv_qty[i] * inv_price[i] for i in range(3)),
    }
    return {"po_data": po, "challan_data": dc, "invoice_data": inv}


SCENARIOS = OrderedDict([
    ("1 · Clean match — all three documents agree", build_demo()),
    ("2 · Quantity discrepancy — billed for goods not delivered",
     build_demo(dc_qty=(4600, 400, 10000))),
    ("3 · Price discrepancy — invoice rate higher than PO",
     build_demo(inv_price=(62.00, 410.00, 8.50))),
    ("4 · Vendor mismatch — invoice from a different vendor",
     build_demo(inv_vendor="Verma Building Supplies")),
    ("5 · Valid partial delivery — billed only for what arrived",
     build_demo(dc_qty=(5000, 400, 6000), inv_qty=(5000, 400, 6000))),
])

# =====================================================================
# MATCHING ENGINE  (Purchase Order -> Delivery Challan -> Invoice)
# =====================================================================
LEGAL_WORDS = {"pvt", "ltd", "limited", "private", "llp", "co", "company", "inc", "llc", "the", "and", "m", "s", "ms"}


def norm_vendor(name):
    tokens = [t for t in re.findall(r"[a-z0-9]+", str(name or "").lower()) if t not in LEGAL_WORDS]
    return " ".join(tokens)


def vendor_same(a, b):
    na, nb = norm_vendor(a), norm_vendor(b)
    if not na or not nb:
        return None
    return fuzz.token_set_ratio(na, nb) >= FUZZY_MIN


def norm_ref(x):
    return re.sub(r"[^A-Z0-9]", "", str(x or "").upper())


def norm_key(desc):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", str(desc).lower())).strip()


def _nums(k):
    return set(re.findall(r"\d+", k))


def aggregate(items, ref_keys=None):
    out = OrderedDict()
    if not isinstance(items, list):
        return out
    for it in items:
        if not isinstance(it, dict):
            continue
        desc = str(it.get("description") or "").strip()
        if not desc:
            continue
        key = norm_key(desc)
        if ref_keys and key not in ref_keys:
            best, score = None, 0
            for rk in ref_keys:
                if _nums(rk) != _nums(key):
                    continue
                s = fuzz.token_set_ratio(key, rk)
                if s > score:
                    best, score = rk, s
            if best and score >= FUZZY_MIN:
                key = best
        row = out.setdefault(key, {"description": desc, "quantity": 0.0, "price": 0.0})
        row["quantity"] += to_float(it.get("quantity"))
        p = to_float(it.get("price"))
        if p > 0:
            row["price"] = p
    return out


def reconcile(po, dc, inv):
    issues, warnings, checks = [], [], []

    def issue(kind, link, msg):
        issues.append({"type": kind, "link": link, "message": msg})

    def warn(kind, msg):
        warnings.append({"type": kind, "message": msg})

    # ---- vendor ----
    v_po, v_dc, v_inv = (str(d.get("vendor") or "").strip() for d in (po, dc, inv))
    same_dc, same_inv = vendor_same(v_po, v_dc), vendor_same(v_po, v_inv)
    if same_dc is False:
        issue("VENDOR", "PO-DC", f"Vendor mismatch: Delivery Challan is from '{v_dc}' but the PO was placed with '{v_po}'.")
    if same_inv is False:
        issue("VENDOR", "PO-INV", f"Vendor mismatch: Invoice is from '{v_inv}' but the PO was placed with '{v_po}'.")
    if same_dc is None or same_inv is None:
        warn("VENDOR", "Vendor name could not be read from one of the documents - please verify manually.")
    v_status = "fail" if (same_dc is False or same_inv is False) else ("warn" if None in (same_dc, same_inv) else "ok")
    checks.append(("Vendor", v_po, v_dc, v_inv, v_status))

    # ---- PO reference ----
    ref_po, ref_dc, ref_inv = norm_ref(po.get("po_no")), norm_ref(dc.get("po_no")), norm_ref(inv.get("po_no"))
    r_status = "ok"
    if not ref_po:
        warn("PO REF", "PO number could not be read from the Purchase Order.")
        r_status = "warn"
    else:
        if not ref_dc:
            warn("PO REF", "Delivery Challan does not reference a PO number.")
            r_status = "warn"
        elif ref_dc != ref_po:
            issue("PO REF", "PO-DC", f"Challan references PO '{dc.get('po_no')}' but the Purchase Order is '{po.get('po_no')}'.")
            r_status = "fail"
        if not ref_inv:
            warn("PO REF", "Invoice does not reference a PO number.")
            r_status = "warn" if r_status == "ok" else r_status
        elif ref_inv != ref_po:
            issue("PO REF", "PO-INV", f"Invoice references PO '{inv.get('po_no')}' but the Purchase Order is '{po.get('po_no')}'.")
            r_status = "fail"
    checks.append(("PO reference", po.get("po_no"), dc.get("po_no"), inv.get("po_no"), r_status))

    # ---- items ----
    po_items = aggregate(po.get("items"))
    ref = list(po_items.keys())
    dc_items = aggregate(dc.get("items"), ref)
    inv_items = aggregate(inv.get("items"), ref)
    for label, link, agg in (("Purchase Order", "PO-INV", po_items), ("Delivery Challan", "PO-DC", dc_items), ("Invoice", "PO-INV", inv_items)):
        if not agg:
            issue("DATA", link, f"No line items could be read from the {label}. Check the PDF quality or re-run the match.")
    keys = list(po_items) + [k for k in dc_items if k not in po_items] + \
        [k for k in inv_items if k not in po_items and k not in dc_items]

    rows, at_risk, dc_value = [], 0.0, 0.0
    for k in keys:
        p, d, i = po_items.get(k), dc_items.get(k), inv_items.get(k)
        name = (p or d or i)["description"]
        pq = p["quantity"] if p else None
        dq = d["quantity"] if d else None
        iq = i["quantity"] if i else None
        pp = p["price"] if p else 0.0
        ip = i["price"] if i else 0.0
        n_before_i, n_before_w = len(issues), len(warnings)
        bad = set()

        if p is None:
            if i:
                issue("ITEM", "PO-INV", f"'{name}' is billed on the invoice but is not on the Purchase Order.")
                bad.add(3)
            if d:
                issue("ITEM", "PO-DC", f"'{name}' was delivered (challan) but is not on the Purchase Order.")
                bad.add(2)
        else:
            if d is None and i is None:
                warn("DELIVERY", f"'{name}' is on the PO but has not been delivered or invoiced yet.")
            if d and dq > pq + QTY_EPS:
                issue("QUANTITY", "PO-DC", f"Over-delivery on '{name}': challan shows {qty(dq)} but PO ordered only {qty(pq)}.")
                bad.add(2)
            if i:
                dq_eff = dq if d else 0.0
                if iq > dq_eff + QTY_EPS:
                    extra = iq - dq_eff
                    unit = ip if ip > 0 else pp
                    at_risk += extra * unit
                    if d:
                        issue("QUANTITY", "DC-INV", f"Billed for undelivered goods on '{name}': invoice bills {qty(iq)} but challan shows only {qty(dq)} delivered ({qty(extra)} short, about {money(extra * unit)}).")
                    else:
                        issue("QUANTITY", "DC-INV", f"'{name}' is invoiced ({qty(iq)}) but no delivery is recorded on the challan.")
                    bad.add(3)
                if iq > pq + QTY_EPS:
                    issue("QUANTITY", "PO-INV", f"Over-billing on '{name}': invoice bills {qty(iq)} but PO ordered only {qty(pq)}.")
                    bad.add(3)
                if pp > 0 and ip > 0 and abs(ip - pp) / pp > PRICE_TOL:
                    pct = (ip - pp) / pp * 100
                    billed_qty = min(iq, dq) if d else iq
                    if ip > pp:
                        at_risk += (ip - pp) * billed_qty
                    issue("PRICE", "PO-INV", f"Price mismatch on '{name}': invoice rate {money(ip)} vs PO rate {money(pp)} ({pct:+.1f}%).")
                    bad.add(4)
            if d and dq < pq - QTY_EPS:
                warn("DELIVERY", f"Partial delivery on '{name}': {qty(dq)} of {qty(pq)} ordered units delivered.")
            if d and i and iq < dq - QTY_EPS:
                warn("BILLING", f"Under-billed on '{name}': {qty(dq)} delivered but only {qty(iq)} invoiced.")
            if d and not i:
                warn("BILLING", f"'{name}' was delivered ({qty(dq)}) but is not yet invoiced.")
            if d and pp > 0:
                dc_value += dq * pp

        status = "fail" if len(issues) > n_before_i else ("warn" if len(warnings) > n_before_w else "ok")
        rows.append({"item": name, "po_qty": pq, "dc_qty": dq, "inv_qty": iq, "po_price": pp if p else None,
                     "inv_price": ip if i else None, "status": status, "bad": bad})

    # ---- totals ----
    po_total = to_float(po.get("total")) or sum(r["po_qty"] * r["po_price"] for r in rows if r["po_qty"])
    inv_total = to_float(inv.get("total"))
    if inv_total > 0 and dc_value > 0 and abs(inv_total - dc_value) > max(1.0, 0.01 * dc_value):
        warn("TOTAL", f"Invoice total {money(inv_total)} differs from the value of delivered goods at PO prices ({money(dc_value)}) by {money(abs(inv_total - dc_value))}. Taxes or extra charges may explain this.")

    links = {l: ("fail" if any(x["link"] == l for x in issues) else "ok") for l in ("PO-DC", "DC-INV", "PO-INV")}
    return {
        "status": "NEEDS REVIEW" if issues else "APPROVED",
        "issues": issues, "warnings": warnings, "checks": checks, "rows": rows, "links": links,
        "po_total": po_total, "inv_total": inv_total, "dc_value": dc_value, "at_risk": at_risk,
    }


# =====================================================================
# RENDERING
# =====================================================================
def doc_card(icon, title, fields, items, show_price, total=None):
    body = "".join(f'<div class="kv"><span>{k}</span><b>{esc(v)}</b></div>' for k, v in fields)
    rows = []
    for r in items.values():
        cells = [esc(r["description"]), qty(r["quantity"])]
        if show_price:
            cells.append(money(r["price"]) if r["price"] > 0 else "—")
        rows.append((cells, "", set()))
    headers = ["Description", "Qty"] + (["Unit price"] if show_price else [])
    tbl = table(headers, rows, num_cols={1, 2}) if rows else "<p>No items found.</p>"
    foot = f'<div class="doc-total">Total <b>{money(total)}</b></div>' if total is not None else ""
    return H(f'<div class="card"><div class="card-title">{icon} {title}</div>{body}{tbl}{foot}</div>')


def link_html(label, status, n):
    sym = "✓ matched" if status == "ok" else f"✗ {n} issue(s)"
    color = "#16a34a" if status == "ok" else "#dc2626"
    return f'<div class="link"><div class="a">➜</div><div style="color:{color}">{sym}</div><div style="color:#94a3b8">{label}</div></div>'


def render_result(res, docs):
    po, dc, inv = docs["po_data"], docs["challan_data"], docs["invoice_data"]
    ok = res["status"] == "APPROVED"

    if ok:
        st.markdown(H('<div class="verdict verdict-ok">APPROVED ✅<small>All three documents reconcile. Safe to release payment.</small></div>'), unsafe_allow_html=True)
    else:
        st.markdown(H(f'<div class="verdict verdict-fail">NEEDS REVIEW ⚠️<small>{len(res["issues"])} discrepancy(ies) found. Hold payment until resolved.</small></div>'), unsafe_allow_html=True)

    n_issues = {l: sum(1 for x in res["issues"] if x["link"] == l) for l in res["links"]}
    st.markdown(H(f"""
    <div class="pipe">
      <div class="node"><div class="t">1 · PURCHASE ORDER</div><div class="n">{esc(po.get('po_no'))}</div>{esc(po.get('vendor'))}<br>{esc(po.get('date'))}</div>
      {link_html('PO ↔ Challan', res['links']['PO-DC'], n_issues['PO-DC'])}
      <div class="node"><div class="t">2 · DELIVERY CHALLAN</div><div class="n">{esc(dc.get('challan_no'))}</div>{esc(dc.get('vendor'))}<br>{esc(dc.get('date'))}</div>
      {link_html('Challan ↔ Invoice', res['links']['DC-INV'], n_issues['DC-INV'])}
      <div class="node"><div class="t">3 · INVOICE</div><div class="n">{esc(inv.get('invoice_no'))}</div>{esc(inv.get('vendor'))}<br>{esc(inv.get('date'))}</div>
    </div>"""), unsafe_allow_html=True)
    if n_issues["PO-INV"]:
        st.caption(f"PO ↔ Invoice direct check: ✗ {n_issues['PO-INV']} issue(s)")

    m = st.columns(4)
    metrics = [(len(res["rows"]), "Line items checked"), (len(res["issues"]), "Discrepancies"),
               (len(res["warnings"]), "Warnings"), (money(res["at_risk"]), "Estimated amount at risk")]
    for col, (v, l) in zip(m, metrics):
        col.markdown(H(f'<div class="metric"><div class="v">{v}</div><div class="l">{l}</div></div>'), unsafe_allow_html=True)
    st.write("")

    t1, t2, t3 = st.tabs(["📋 Extracted Fields", "⚖️ Three-Way Match", "🚨 Discrepancies & Summary"])

    with t1:
        c1, c2, c3 = st.columns(3)
        po_total = res["po_total"]
        with c1:
            st.markdown(doc_card("📑", "Purchase Order", [("PO number", po.get("po_no")), ("Date", po.get("date")), ("Vendor", po.get("vendor"))],
                                 aggregate(po.get("items")), True, po_total), unsafe_allow_html=True)
        with c2:
            st.markdown(doc_card("🚚", "Delivery Challan", [("Challan number", dc.get("challan_no")), ("PO reference", dc.get("po_no")), ("Date", dc.get("date")), ("Vendor", dc.get("vendor"))],
                                 aggregate(dc.get("items")), False), unsafe_allow_html=True)
        with c3:
            st.markdown(doc_card("🧾", "Invoice", [("Invoice number", inv.get("invoice_no")), ("PO reference", inv.get("po_no")), ("Date", inv.get("date")), ("Vendor", inv.get("vendor"))],
                                 aggregate(inv.get("items")), True, res["inv_total"]), unsafe_allow_html=True)

    with t2:
        st.markdown("#### Header checks")
        crow = [([c[0], esc(c[1]), esc(c[2]), esc(c[3]), chip(c[4])], "row-fail" if c[4] == "fail" else ("row-warn" if c[4] == "warn" else ""), set())
                for c in res["checks"]]
        st.markdown(H(table(["Check", "Purchase Order", "Delivery Challan", "Invoice", "Result"], crow)), unsafe_allow_html=True)

        st.markdown("#### Line-item three-way match")
        irow = []
        for r in res["rows"]:
            cells = [esc(r["item"]), qty(r["po_qty"]), qty(r["dc_qty"]), qty(r["inv_qty"]),
                     money(r["po_price"]) if r["po_price"] else "—", money(r["inv_price"]) if r["inv_price"] else "—",
                     chip(r["status"], {"ok": "OK", "warn": "CHECK", "fail": "DISCREPANCY"}[r["status"]])]
            irow.append((cells, {"fail": "row-fail", "warn": "row-warn", "ok": ""}[r["status"]], r["bad"]))
        st.markdown(H(table(["Item", "PO qty", "Delivered qty", "Invoiced qty", "PO price", "Invoice price", "Result"], irow, num_cols={1, 2, 3, 4, 5})), unsafe_allow_html=True)

        st.markdown("#### Financial summary")
        frow = [([ "PO total (ordered)", money(res["po_total"])], "", set()),
                (["Value of goods delivered (at PO prices)", money(res["dc_value"])], "", set()),
                (["Invoice total (billed)", money(res["inv_total"])], "", set()),
                (["Estimated amount at risk", money(res["at_risk"])], "row-fail" if res["at_risk"] > 0 else "", set())]
        st.markdown(H(table(["Measure", "Amount"], frow, num_cols={1})), unsafe_allow_html=True)

    with t3:
        if res["issues"]:
            st.markdown("#### Discrepancies (cause NEEDS REVIEW)")
            for x in res["issues"]:
                st.markdown(H(f'<div class="issue"><span class="tag">{x["type"]}</span>{html.escape(x["message"])}</div>'), unsafe_allow_html=True)
        else:
            st.success("No discrepancies found across vendor, PO reference, quantities and prices.")
        if res["warnings"]:
            st.markdown("#### Warnings (informational, do not block approval)")
            for x in res["warnings"]:
                st.markdown(H(f'<div class="warnbox"><span class="tag w">{x["type"]}</span>{html.escape(x["message"])}</div>'), unsafe_allow_html=True)
        st.markdown("#### Agent-style summary")
        st.markdown(agent_summary(res, po, dc, inv), unsafe_allow_html=True)


def agent_summary(res, po, dc, inv):
    head = (f"Reviewed Purchase Order <b>{esc(po.get('po_no'))}</b>, Delivery Challan <b>{esc(dc.get('challan_no'))}</b> "
            f"and Invoice <b>{esc(inv.get('invoice_no'))}</b> from <b>{esc(po.get('vendor'))}</b>.")
    if not res["issues"]:
        body = "<p>Vendor, PO reference, delivered quantities and unit prices agree across all three documents.</p>"
        if res["warnings"]:
            body += f"<p>{len(res['warnings'])} informational note(s) were raised (for example partial deliveries) but none block payment.</p>"
        body += "<p><b>Recommendation:</b> ✅ Approve the invoice for payment.</p>"
    else:
        kinds = {x["type"] for x in res["issues"]}
        body = f"<p>{len(res['issues'])} discrepancy(ies) were found, with an estimated <b>{money(res['at_risk'])}</b> at risk of overpayment.</p>"
        steps = []
        if "QUANTITY" in kinds:
            steps.append("confirm physical receipt with the site store and ask the vendor for a corrected invoice or credit note")
        if "PRICE" in kinds:
            steps.append("ask the vendor to re-issue the invoice at PO-agreed rates, or get a PO amendment approved")
        if "VENDOR" in kinds:
            steps.append("verify the vendor identity and bank details before any payment")
        if "PO REF" in kinds or "ITEM" in kinds:
            steps.append("check that the documents belong to the same order and that no unordered items were supplied")
        body += "<p><b>Recommendation:</b> ⚠️ Hold payment. Next steps: " + "; ".join(steps) + ".</p>"
    return H(f'<div class="agent"><p>{head}</p>{body}</div>')


# =====================================================================
# SIDEBAR
# =====================================================================
with st.sidebar:
    st.markdown("### 🌉 SETU360")
    st.caption("AI Procurement Reconciliation")
    CUR = st.selectbox("Currency", ["₹", "SAR "], index=0)
    mode = st.radio("Mode", [DEMO_MODE, LIVE_MODE])
    st.markdown("---")
    scenario, po_file, dc_file, inv_file = None, None, None, None
    if mode == DEMO_MODE:
        scenario = st.selectbox("Choose a scenario", list(SCENARIOS.keys()))
    else:
        po_file = st.file_uploader("📑 Purchase Order (PDF)", type=["pdf"], key="po")
        dc_file = st.file_uploader("🚚 Delivery Challan (PDF)", type=["pdf"], key="dc")
        inv_file = st.file_uploader("🧾 Invoice (PDF)", type=["pdf"], key="inv")
    run = st.button("🔍 Run Three-Way Match", key="run", type="primary")
    st.markdown("---")
    st.caption("Rules: APPROVED only when vendor, PO reference, quantities and prices all agree. Partial deliveries billed correctly are allowed.")

# =====================================================================
# MAIN PAGE
# =====================================================================
st.markdown(H("""
<div class="s360-hero">
  <div class="s360-brand">SETU<span>360</span></div>
  <div class="s360-tag">AI Procurement Reconciliation for Regional Contractors</div>
  <div class="s360-flow"><span class="pill">PURCHASE ORDER</span><span class="arr">➜</span><span class="pill">DELIVERY CHALLAN</span><span class="arr">➜</span><span class="pill">INVOICE</span></div>
</div>"""), unsafe_allow_html=True)

if run:
    if mode == DEMO_MODE:
        st.session_state["docs"] = copy.deepcopy(SCENARIOS[scenario])
        st.session_state["title"] = scenario
    elif not (po_file and dc_file and inv_file):
        st.error("Please upload all three documents: Purchase Order, Delivery Challan and Invoice.")
    else:
        with st.spinner("Reading documents and extracting fields with AI..."):
            texts = [get_text_from_pdf(f.getvalue()) for f in (po_file, dc_file, inv_file)]
            if all(texts):
                payload = [EXTRACTION_PROMPT, f"--- PURCHASE ORDER TEXT ---\n{texts[0]}",
                           f"--- DELIVERY CHALLAN TEXT ---\n{texts[1]}", f"--- INVOICE TEXT ---\n{texts[2]}"]
                data = call_gemini(payload)
                if data:
                    st.session_state["docs"] = data
                    st.session_state["title"] = "Uploaded documents"
            else:
                st.error("Could not read text from one or more PDFs.")

if "docs" in st.session_state:
    docs = st.session_state["docs"]
    st.markdown(f"**Showing:** {html.escape(st.session_state.get('title', ''))}")
    result = reconcile(docs["po_data"], docs["challan_data"], docs["invoice_data"])
    render_result(result, docs)
else:
    st.markdown("### How Setu360 works")
    c1, c2, c3 = st.columns(3)
    steps = [("1", "Extract", "AI reads the Purchase Order, Delivery Challan and Invoice (even scanned PDFs) and pulls out vendor, PO number, items, quantities and prices."),
             ("2", "Three-way match", "Every item is compared across PO → Challan → Invoice to catch over-delivery, billing for undelivered goods, price changes and vendor mismatches."),
             ("3", "Decide", "Setu360 shows APPROVED or NEEDS REVIEW with the exact discrepancies, the amount at risk and the recommended next step.")]
    for col, (n, t, d) in zip((c1, c2, c3), steps):
        col.markdown(H(f'<div class="how"><div class="num">{n}</div><b>{t}</b><p>{d}</p></div>'), unsafe_allow_html=True)
    st.info("👈 Pick a demo scenario in the sidebar and click **Run Three-Way Match** to see it working.")

st.markdown('<div class="s360-footer">Setu360 · Final-Year Project · Three-way matching powered by Streamlit &amp; Google Gemini</div>', unsafe_allow_html=True)
