from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app import create_app
from database import db
from demo import SAMPLE_KEY
from duplicate_receipts import confirmed_posted_duplicate, receipt_number
from receipt_extraction import process_next
from test_thrive import BrowserSession


class ReceiptMatchingTests(unittest.TestCase):
    def setUp(self):
        instance = Path(__file__).resolve().parents[1] / "instance"
        instance.mkdir(exist_ok=True)
        directory = TemporaryDirectory(dir=instance)
        self.addCleanup(directory.cleanup)
        self.app = create_app({"DEMO": True, "TESTING": True, "DATA_DIR": Path(directory.name),
                               "AZURE_ENDPOINT": "", "AZURE_KEY": ""})
        self.browser = BrowserSession(self.app)
        self.aman = self.browser.use_demo("aman")
        with self.app.app_context():
            self.original = dict(db().execute(
                """SELECT r.id, r.group_id, e.id AS expense_id FROM receipts r
                   JOIN expenses e ON e.receipt_id = r.id WHERE r.file_key = ?""", (SAMPLE_KEY,),
            ).fetchone())
        self.group_url = f"/api/groups/{self.original['group_id']}"

    def upload(self, variant, group_url=None):
        sample = self.browser.get(f"/api/demo/receipt?sample={variant}")
        self.addCleanup(sample.close)
        self.assertEqual(sample.status_code, 200)
        uploaded = self.browser.post((group_url or self.group_url) + "/receipts",
                                     data={"receipt": (BytesIO(sample.data), f"{variant}.png")})
        self.assertEqual(uploaded.status_code, 202, uploaded.get_data(as_text=True))
        with self.app.app_context():
            self.assertTrue(process_next())
        return uploaded.json

    def receipt(self, data):
        return self.browser.get(f"/api/receipts/{data['id']}").json

    def review(self, first, second, decision):
        return self.browser.call("PATCH", f"/api/receipts/{first['id']}/matches/{second['id']}", {"decision": decision})

    def test_different_photo_matches_and_review_is_reversible(self):
        uploaded = self.upload("second-photo")
        receipt = self.receipt(uploaded)
        self.assertIsNone(receipt["duplicate_of"])
        self.assertEqual(receipt["comparison"]["receipt_number"], "026")
        [match] = receipt["duplicate_matches"]
        self.assertEqual(match["id"], self.original["id"])
        self.assertEqual(match["kind"], "likely")
        self.assertTrue(match["posted"])
        self.assertIn("Matching receipt number", match["reasons"])
        self.assertIn("3 matching item names", match["reasons"])

        reviewed = self.review(uploaded, self.original, "duplicate")
        self.assertEqual(reviewed.status_code, 200)
        self.assertEqual(reviewed.json["duplicate_matches"][0]["decision"], "duplicate")
        self.assertEqual(self.receipt(self.original)["duplicate_matches"][0]["decision"], "duplicate")
        with self.app.app_context():
            self.assertEqual(confirmed_posted_duplicate(db(), uploaded["id"])["id"], self.original["expense_id"])
        expense_url = f"/api/expenses/{uploaded['expense_id']}"
        draft = self.browser.get(expense_url).json["revisions"][0]
        draft.update(mode="equal", member_ids=[self.aman])
        version = {"revision_id": draft["id"], "edit_version": draft["edit_version"]}
        saved = self.browser.call("PATCH", expense_url + "/draft", dict(version, draft=draft))
        self.assertEqual(saved.status_code, 200, saved.get_data(as_text=True))
        version["edit_version"] = saved.json["edit_version"]
        self.assertEqual(self.browser.post(expense_url + "/post", version).status_code, 409)

        reviewed = self.review(self.original, uploaded, "different")
        self.assertEqual(reviewed.status_code, 200)
        self.assertEqual(self.receipt(uploaded)["duplicate_matches"][0]["decision"], "different")
        with self.app.app_context():
            self.assertIsNone(confirmed_posted_duplicate(db(), uploaded["id"]))
        self.assertEqual(self.browser.post(expense_url + "/post", version).status_code, 200)

    def test_different_receipt_number_excludes_same_merchant_and_total(self):
        receipt = self.receipt(self.upload("separate-purchase"))
        original = self.receipt(self.original)
        self.assertEqual(receipt["comparison"]["receipt_number"], "041")
        for field in ("merchant", "purchase_date", "total_paise", "items"):
            self.assertEqual(receipt["comparison"][field], original["comparison"][field])
        self.assertEqual(receipt["duplicate_matches"], [])

    def test_cropped_receipt_number_uses_other_evidence(self):
        receipt = self.receipt(self.upload("cropped-number"))
        self.assertEqual(receipt["comparison"]["receipt_number"], "")
        [match] = receipt["duplicate_matches"]
        self.assertEqual(match["id"], self.original["id"])
        self.assertEqual(match["kind"], "likely")
        self.assertIn("Receipt number missing from at least one scan", match["reasons"])
        self.assertIn("3 matching item names", match["reasons"])

    def test_ignores_other_groups_and_uses_receipt_number_tokens(self):
        unrelated = self.browser.post("/api/groups", {"name": "Another trip"}).json["id"]
        uploaded = self.upload("second-photo", f"/api/groups/{unrelated}")
        self.assertEqual(self.receipt(uploaded)["duplicate_matches"], [])
        self.assertEqual(self.review(uploaded, self.original, "duplicate").status_code, 404)
        self.assertEqual(receipt_number({"analyzeResult": {"content": "Invoice No. JA-520 / Ref 250"}}), "JA-520")
        self.assertEqual(receipt_number({"analyzeResult": {"content": "Bill total 840\nPaid by UPI"}}), "")

    def test_confirmed_match_chains_resolve_to_the_posted_expense(self):
        second = self.upload("second-photo")
        crop = self.upload("cropped-number")
        self.assertEqual(self.review(second, self.original, "duplicate").status_code, 200)
        self.assertEqual(self.review(crop, second, "duplicate").status_code, 200)
        with self.app.app_context():
            self.assertEqual(confirmed_posted_duplicate(db(), crop["id"])["id"], self.original["expense_id"])
        self.assertEqual(self.review(crop, self.original, "duplicate").status_code, 200)
        with self.app.app_context():
            self.assertEqual(confirmed_posted_duplicate(db(), crop["id"])["id"], self.original["expense_id"])
        self.assertEqual(self.review(crop, self.original, "different").status_code, 200)
        self.assertEqual(self.review(second, self.original, "different").status_code, 200)
        with self.app.app_context():
            self.assertIsNone(confirmed_posted_duplicate(db(), crop["id"]))
