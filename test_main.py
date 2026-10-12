import unittest

import main


class InvoiceTests(unittest.TestCase):
    def test_extracts_fields(self):
        text = ("Supplier: Eko Power Solutions\nInvoice No: X-1\nDate: 2026-01-01\n"
                "- Item 2 x 1,000 = 2,000\nSubtotal: 2,000\nVAT 7.5%: 150\nTotal: 2,150")
        inv = main.extract_regex(text)
        self.assertEqual(inv["supplier"], "Eko Power Solutions")
        self.assertEqual(inv["total"], 2150)
        self.assertEqual(len(inv["line_items"]), 1)

    def test_demo_routes_correctly(self):
        import json
        invoices = json.load(open("sample_invoices.json"))
        known = set(json.load(open("known_suppliers.json")))
        result = main.process(invoices, known)
        self.assertEqual(len(result["posted"]), 3)
        reasons = " ".join(r for i in result["review"] for r in i["reasons"])
        self.assertIn("duplicate", reasons)
        self.assertIn("unknown supplier", reasons)
        self.assertIn("total says", reasons)


if __name__ == "__main__":
    unittest.main()
