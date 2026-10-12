"""Invoice Processing Automation.

Extract -> validate -> route invoices. Runs offline with regex extraction;
uses an LLM for extraction when ANTHROPIC_API_KEY or OPENAI_API_KEY is set.
"""
import argparse
import csv
import json
import re
from pathlib import Path

import llm

MONEY = r"([0-9][0-9,]*\.?[0-9]*)"


def to_num(s: str) -> float:
    return float(s.replace(",", ""))


def extract_regex(text: str) -> dict:
    def find(pattern):
        m = re.search(pattern, text, re.I | re.M)
        return m.group(1).strip() if m else None

    items = []
    for m in re.finditer(r"^\s*-\s*(.+?)\s+(\d+)\s*x\s*" + MONEY + r"\s*=\s*" + MONEY,
                         text, re.M):
        items.append({"description": m.group(1).strip(), "qty": int(m.group(2)),
                      "unit_price": to_num(m.group(3)), "amount": to_num(m.group(4))})
    sub, vat, tot = find(r"^Subtotal:?\s*" + MONEY), find(r"^VAT.*?:\s*" + MONEY), \
        find(r"^Total:?\s*" + MONEY)
    return {
        "supplier": find(r"^Supplier:?\s*(.+)$"),
        "invoice_number": find(r"^Invoice\s*(?:No|Number|#)\.?:?\s*(\S+)"),
        "invoice_date": find(r"^Date:?\s*(.+)$"),
        "due_date": find(r"^Due:?\s*(.+)$"),
        "line_items": items,
        "subtotal": to_num(sub) if sub else None,
        "vat": to_num(vat) if vat else 0.0,
        "total": to_num(tot) if tot else None,
    }


def extract(text: str) -> dict:
    if llm.available():
        data = llm.complete_json(
            "Extract this invoice into JSON with keys supplier, invoice_number, "
            "invoice_date, due_date, line_items (description, qty, unit_price, "
            "amount), subtotal, vat, total. Numbers as plain numbers.\n\n" + text)
        if isinstance(data, dict) and data.get("total") is not None:
            return data
    return extract_regex(text)


def validate(inv: dict, known_suppliers: set, seen: set) -> list:
    reasons = []
    for field in ("supplier", "invoice_number", "total"):
        if not inv.get(field):
            reasons.append(f"missing {field}")
    items_sum = round(sum(i["amount"] for i in inv.get("line_items", [])), 2)
    for i in inv.get("line_items", []):
        if round(i["qty"] * i["unit_price"], 2) != round(i["amount"], 2):
            reasons.append(f"line '{i['description']}': {i['qty']} x {i['unit_price']:,} "
                           f"!= {i['amount']:,}")
    if inv.get("subtotal") is not None and items_sum != round(inv["subtotal"], 2):
        reasons.append(f"line items add to {items_sum:,.2f} but subtotal says "
                       f"{inv['subtotal']:,.2f}")
    if inv.get("subtotal") is not None and inv.get("total") is not None:
        expected = round(inv["subtotal"] + (inv.get("vat") or 0), 2)
        if expected != round(inv["total"], 2):
            reasons.append(f"subtotal + VAT = {expected:,.2f} but total says "
                           f"{inv['total']:,.2f}")
    if inv.get("supplier") and inv["supplier"] not in known_suppliers:
        reasons.append(f"unknown supplier '{inv['supplier']}'")
    key = (inv.get("supplier"), inv.get("invoice_number"))
    if key in seen:
        reasons.append(f"duplicate of invoice {inv.get('invoice_number')}")
    seen.add(key)
    return reasons


def process(invoices: list, known_suppliers: set) -> dict:
    seen, posted, review = set(), [], []
    for doc in invoices:
        inv = extract(doc["text"])
        inv["source"] = doc["source"]
        reasons = validate(inv, known_suppliers, seen)
        (review if reasons else posted).append({**inv, "reasons": reasons})
    return {"posted": posted, "review": review}


def save(result: dict, out: Path) -> None:
    out.mkdir(exist_ok=True)
    with open(out / "posted.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["supplier", "invoice_number", "invoice_date", "due_date",
                    "subtotal", "vat", "total", "source"])
        for i in result["posted"]:
            w.writerow([i["supplier"], i["invoice_number"], i["invoice_date"],
                        i["due_date"], i["subtotal"], i["vat"], i["total"], i["source"]])
    (out / "review_queue.json").write_text(json.dumps(result["review"], indent=2))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", default="sample_invoices.json")
    ap.add_argument("--suppliers", default="known_suppliers.json")
    ap.add_argument("--demo", action="store_true", help="run on the sample data")
    args = ap.parse_args()
    invoices = json.loads(Path(args.input).read_text(encoding="utf-8"))
    known = set(json.loads(Path(args.suppliers).read_text(encoding="utf-8")))
    result = process(invoices, known)
    save(result, Path("output"))
    print(f"Mode: {'LLM (' + llm.provider() + ')' if llm.available() else 'offline rules'}")
    print(f"Processed {len(invoices)} invoices: {len(result['posted'])} ready to post, "
          f"{len(result['review'])} need review\n")
    for i in result["posted"]:
        print(f"  POST    {i['invoice_number']:<10} {i['supplier']:<26} NGN {i['total']:>12,.2f}")
    for i in result["review"]:
        print(f"  REVIEW  {str(i['invoice_number']):<10} {str(i['supplier']):<26}")
        for r in i["reasons"]:
            print(f"          - {r}")
    print("\nSaved output/posted.csv and output/review_queue.json")


if __name__ == "__main__":
    main()
