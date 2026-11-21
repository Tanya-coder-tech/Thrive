from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from random import Random
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest
from urllib.parse import parse_qs, urlsplit

from PIL import Image

from app import create_app
from demo import sample_receipt
from receipt_extraction import process_next
from reconciliation import blank_draft, equal_split, normalize, parse_paise, proportional_split, preview


class BrowserSession:
    def __init__(self, app):
        self.client = app.test_client()
        self.csrf = self.client.get("/api/session").json["csrf"]

    def call(self, method, path, payload=None, **kwargs):
        response = self.client.open(path, method=method, json=payload,
                                    headers={"X-CSRF-Token": self.csrf}, **kwargs)
        if response.is_json and "csrf" in response.json:
            self.csrf = response.json["csrf"]
        return response

    def use_demo(self, person):
        return self.call("POST", "/api/demo/session", {"person": person}).json["user"]["id"]

    def get(self, path):
        return self.call("GET", path)

    def post(self, path, payload=None, **kwargs):
        return self.call("POST", path, payload, **kwargs)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        instance = Path(__file__).resolve().parents[1] / "instance"
        instance.mkdir(exist_ok=True)
        self.directory = TemporaryDirectory(dir=instance)
        self.addCleanup(self.directory.cleanup)
        self.app = create_app({"DEMO": True, "TESTING": True, "DATA_DIR": Path(self.directory.name),
                               "AZURE_ENDPOINT": "", "AZURE_KEY": ""})
        self.aman = BrowserSession(self.app)
        self.simran = BrowserSession(self.app)
        self.karan = BrowserSession(self.app)
        self.aman_id = self.aman.use_demo("aman")
        self.simran_id = self.simran.use_demo("simran")
        self.karan_id = self.karan.use_demo("karan")
        self.group = self.aman.post("/api/groups", {"name": "Acceptance trip"}).json["id"]
        self.group_url = f"/api/groups/{self.group}"
        self.invite(self.simran)
        self.invite(self.karan)

    def invite(self, member):
        link = self.aman.post(self.group_url + "/invites", {}).json["path"]
        token = parse_qs(urlsplit(link).query)["invite"][0]
        first = member.post("/api/invites/accept", {"token": token})
        self.assertEqual(first.json["id"], self.group)
        self.assertEqual(member.post("/api/invites/accept", {"token": token}).json["id"], self.group)
        return token

    def work(self):
        with self.app.app_context():
            self.assertTrue(process_next())

    def upload(self, filename, original):
        response = self.aman.post(self.group_url + "/receipts",
                                  data={"receipt": (BytesIO(original), filename)})
        self.assertEqual(response.status_code, 202, response.get_data(as_text=True))
        return response.json

    def ledger(self):
        response = self.aman.get(self.group_url + "/balances").json
        balances = {row["id"]: row["net_paise"] for row in response["balances"]}
        self.assertEqual(sum(balances.values()), 0)
        return balances, response["settlements"]

    @staticmethod
    def version(draft):
        return {"revision_id": draft["id"], "edit_version": draft["edit_version"]}

    def load_draft(self, path):
        return self.aman.get(path).json["revisions"][0]

    def save(self, path, draft, member=None):
        return (member or self.aman).call("PATCH", path + "/draft", dict(self.version(draft), draft=draft))

    def duplicate_request(self, user, path, payload):
        start = Barrier(2)

        def repeat(_):
            session = BrowserSession(self.app)
            session.use_demo(user)
            start.wait(timeout=5)
            return session.post(path, payload).status_code

        with ThreadPoolExecutor(max_workers=2) as workers:
            return list(workers.map(repeat, range(2)))

    def test_dinner_from_upload_through_corrected_ledger(self):
        uploaded = self.upload("bill.png", sample_receipt())
        expense = f"/api/expenses/{uploaded['expense_id']}"
        receipt = f"/api/receipts/{uploaded['id']}"
        self.assertEqual(self.aman.get(receipt).json["scan_status"], "queued")
        original = self.aman.get(receipt + "/file")
        self.addCleanup(original.close)
        self.assertEqual(original.data, sample_receipt())
        self.work()
        self.assertEqual(self.simran.get(receipt).json["scan_status"], "ready")
        draft = self.load_draft(expense)
        self.assertEqual([item["amount_paise"] for item in draft["items"]], [40000, 25000, 15000])
        for item, owners in zip(draft["items"], ([self.aman_id, self.simran_id], [self.karan_id],
                                                   [self.aman_id, self.simran_id, self.karan_id])):
            item["member_ids"] = owners
        draft["adjustments"] = []
        result = self.aman.post(expense + "/preview", dict(self.version(draft), draft=draft)).json
        self.assertEqual(result["difference_paise"], 4000)
        draft["edit_version"] = self.save(expense, draft).json["edit_version"]
        blocked = self.aman.post(expense + "/post", self.version(draft))
        self.assertEqual(blocked.status_code, 422)
        self.assertEqual(blocked.json["preview"]["difference_paise"], 4000)
        draft["adjustments"] = [{"kind": "tax", "amount_paise": 4000, "included": False}]
        result = self.aman.post(expense + "/preview", dict(self.version(draft), draft=draft)).json
        expected = dict(zip(map(str, (self.aman_id, self.simran_id, self.karan_id)), (26250, 26250, 31500)))
        self.assertEqual(result["shares"], expected)
        self.assertFalse(result["issues"])
        saved = self.save(expense, draft)
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(self.save(expense, draft, self.simran).status_code, 409)
        self.assertEqual(self.simran.post(expense + "/post", self.version(draft)).status_code, 409)
        draft["edit_version"] = saved.json["edit_version"]
        self.assertEqual(self.duplicate_request("aman", expense + "/post", self.version(draft)), [200, 200])
        self.assertEqual(self.ledger()[0], {self.aman_id: 57750, self.simran_id: -26250, self.karan_id: -31500})
        self.assertEqual(self.aman.get(expense).json["revisions"][0]["shares"], expected)

        claim = {"sender_id": self.simran_id, "recipient_id": self.aman_id, "amount_paise": 26250,
                 "request_key": "simran-demo-transfer"}
        self.assertEqual(self.aman.post(self.group_url + "/settlements", claim).status_code, 403)
        payment = self.simran.post(self.group_url + "/settlements", claim).json
        self.assertEqual(self.simran.post(self.group_url + "/settlements", claim).json["id"], payment["id"])
        confirmation = f"/api/settlements/{payment['id']}/confirm"
        self.assertEqual(self.karan.post(confirmation, {}).status_code, 403)
        self.assertEqual(self.ledger()[0][self.simran_id], -26250)
        self.assertEqual(self.duplicate_request("aman", confirmation, {}), [200, 200])
        self.assertEqual(self.ledger()[0], {self.aman_id: 31500, self.simran_id: 0, self.karan_id: -31500})

        posted = self.aman.get(expense).json["revisions"][0]
        question = self.karan.post(expense + "/disputes", {"revision_id": posted["id"],
                                   "item_id": posted["items"][2]["id"], "reason": "I didn’t share the drinks."})
        self.assertEqual(question.status_code, 201)
        self.assertEqual(self.karan.post(expense + "/corrections", {}).status_code, 201)
        proposed = self.load_draft(expense)
        proposed["items"][2]["member_ids"] = [self.aman_id, self.simran_id]
        proposed["edit_version"] = self.save(expense, proposed, self.karan).json["edit_version"]
        self.assertEqual(self.karan.post(expense + "/post", self.version(proposed)).status_code, 403)
        self.assertEqual(self.aman.post(expense + "/post", self.version(proposed)).status_code, 200)
        history = self.aman.get(expense).json["revisions"]
        self.assertEqual([row["version"] for row in history], [2, 1])
        self.assertEqual(history[1]["shares"], expected)
        self.assertEqual(history[0]["posted_by"], self.aman_id)
        balances, payments = self.ledger()
        self.assertEqual(balances, {self.aman_id: 28875, self.simran_id: -2625, self.karan_id: -26250})
        self.assertEqual([(row["id"], row["status"]) for row in payments], [(payment["id"], "confirmed")])
        resolution = f"/api/disputes/{question.json['id']}/resolve"
        self.assertEqual(self.karan.post(resolution, {"resolution": "Updated"}).status_code, 403)
        self.assertEqual(self.aman.post(resolution, {"resolution": "Updated"}).status_code, 200)
        audit = self.aman.get(self.group_url).json["activity"]
        self.assertEqual(sum(event["action"] == "payment_confirmed" for event in audit), 1)
        self.assertEqual(sum(event["action"] == "expense_posted" for event in audit), 1)

    def test_file_permissions_duplicate_checks_retries_and_manual_entry(self):
        stranger = BrowserSession(self.app)
        stranger.post("/api/auth/register", {"name": "Unaffiliated Student", "email": "student@example.test",
                                             "password": "long-enough-password"})
        self.assertEqual(stranger.get(self.group_url).status_code, 404)
        uploaded = self.upload("bill.png", sample_receipt())
        duplicate = self.upload("copy.png", sample_receipt())
        receipt = f"/api/receipts/{uploaded['id']}"
        self.assertEqual(stranger.get(receipt).status_code, 404)
        self.assertEqual(stranger.get(receipt + "/file").status_code, 404)
        self.assertEqual(stranger.get(f"/api/expenses/{uploaded['expense_id']}").status_code, 404)
        self.assertEqual(self.aman.get(f"/api/receipts/{duplicate['id']}").json["duplicate_of"], uploaded["id"])
        response = self.aman.post(self.group_url + "/receipts",
                                  data={"receipt": (BytesIO(b"<html>invalid</html>"), "bill.png")})
        self.assertEqual(response.status_code, 400)
        jpeg = BytesIO()
        Image.new("RGB", (16, 16)).save(jpeg, "JPEG")
        file = self.upload("photo.jpg", jpeg.getvalue())
        pdf_buffer = BytesIO()
        Image.new("RGB", (250, 300), "white").save(pdf_buffer, "PDF")
        pdf_file = self.upload("bill.pdf", pdf_buffer.getvalue())
        pdf_path = f"/api/receipts/{pdf_file['id']}"
        pdf_response = self.aman.get(pdf_path + "/file")
        self.addCleanup(pdf_response.close)
        self.assertEqual(pdf_response.mimetype, "application/pdf")
        self.assertEqual(pdf_response.data, pdf_buffer.getvalue())
        meta = self.aman.get(pdf_path).json
        self.assertEqual(meta["page_count"], 1)
        self.assertEqual(stranger.get(meta["pdf_preview_url"]).status_code, 404)
        image_response = self.aman.get(meta["pdf_preview_url"])
        self.addCleanup(image_response.close)
        self.assertEqual(image_response.mimetype, "image/png")
        self.assertTrue(image_response.data.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(self.aman.get(pdf_path + "/pdf-preview/2").status_code, 404)
        for _ in range(4):
            self.work()
        failed = f"/api/receipts/{file['id']}"
        self.assertEqual(self.aman.get(failed).json["scan_status"], "failed")
        self.assertEqual(self.aman.post(failed + "/retry", {}).status_code, 202)
        self.work()
        self.assertEqual(self.aman.get(failed).json["scan_status"], "failed")
        expense = f"/api/expenses/{file['expense_id']}"
        draft = dict(self.load_draft(expense), merchant="Manual café", purchase_date="2026-11-20", total_paise=10000)
        draft["edit_version"] = self.save(expense, draft).json["edit_version"]
        self.assertEqual(self.aman.post(expense + "/post", self.version(draft)).status_code, 200)
        self.assertEqual(self.ledger()[0], {self.aman_id: 6666, self.simran_id: -3333, self.karan_id: -3333})

    def test_worker_leaves_saved_manual_edits_in_place(self):
        uploaded = self.upload("bill.png", sample_receipt())
        expense = f"/api/expenses/{uploaded['expense_id']}"
        draft = dict(self.load_draft(expense), merchant="Verified by reviewer")
        self.assertEqual(self.save(expense, draft).status_code, 200)
        self.work()
        record = self.aman.get(expense).json
        self.assertEqual(record["revisions"][0]["merchant"], "Verified by reviewer")
        self.assertEqual(record["receipt"]["extracted"]["merchant"], "The Campus Kitchen")

    def test_only_organizers_can_assign_a_role_and_last_organizer_is_retained(self):
        member = self.group_url + f"/members/{self.simran_id}"
        owner = self.group_url + f"/members/{self.aman_id}"
        self.assertEqual(self.simran.call("PATCH", member, {"role": "organizer"}).status_code, 403)
        self.assertEqual(self.aman.call("PATCH", owner, {"role": "member"}).status_code, 409)
        self.assertEqual(self.aman.call("PATCH", member, {"role": "organizer"}).status_code, 200)
        self.assertEqual(self.aman.call("PATCH", owner, {"role": "member"}).status_code, 200)
        self.assertEqual(self.simran.get(self.group_url).json["group"]["role"], "organizer")


class AccountingTests(unittest.TestCase):
    def test_rounding_and_randomized_shares(self):
        self.assertEqual(equal_split(10000, [3, 1, 2]), {1: 3334, 2: 3333, 3: 3333})
        self.assertEqual(parse_paise("INR 1,23,456.50"), 12345650)
        rng = Random(840)
        for _ in range(400):
            members = list(range(1, rng.randint(2, 14)))
            weights = {member: rng.randint(1, 100000) for member in members}
            amount = rng.randint(-sum(weights), 500000)
            shares, rounded = proportional_split(amount, weights)
            self.assertEqual(sum(shares.values()), amount)
            self.assertEqual(len(rounded), len(set(rounded)))
            for member, share in shares.items():
                self.assertLess(abs(share * sum(weights.values()) - amount * weights[member]),
                                sum(weights.values()))
            total = sum(weights.values()) + amount
            if total > 0:
                draft = dict(blank_draft(1), merchant="Randomized bill", purchase_date="2026-11-20",
                             mode="items", total_paise=total, subtotal_paise=sum(weights.values()),
                             items=[dict(description="Line", amount_paise=weight, member_ids=[member])
                                    for member, weight in weights.items()],
                             adjustments=[dict(kind="discount" if amount < 0 else "tax",
                                               amount_paise=amount, included=False)])
                result = preview(normalize(draft), set(members))
                self.assertFalse(result["issues"], result)
                self.assertEqual(sum(result["shares"].values()), total)

    def test_tax_included_and_ocr_misread(self):
        draft = dict(blank_draft(1), merchant="Café", purchase_date="2026-11-20", total_paise=18000,
                     subtotal_paise=17000, mode="items",
                     items=[dict(description="Sandwiches", amount_paise=18000, member_ids=[1, 2])],
                     adjustments=[dict(kind="tax", amount_paise=1000, included=True)])
        checked = preview(normalize(draft), {1, 2})
        self.assertFalse(checked["issues"])
        self.assertEqual(checked["shares"], {1: 9000, 2: 9000})
        draft["items"][0]["amount_paise"] = 13000
        checked = preview(normalize(draft), {1, 2})
        self.assertEqual(checked["difference_paise"], 5000)
        self.assertTrue(checked["issues"])


if __name__ == "__main__":
    unittest.main()
