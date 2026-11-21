from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from app import create_app
from database import db
from test_thrive import BrowserSession


PROJECT = Path(__file__).resolve().parents[1]


class TripExtensionTests(unittest.TestCase):
    def setUp(self):
        instance = PROJECT / "instance"
        instance.mkdir(exist_ok=True)
        directory = TemporaryDirectory(dir=instance)
        self.addCleanup(directory.cleanup)
        self.app = create_app({"DEMO": True, "TESTING": True, "DATA_DIR": Path(directory.name),
                               "AZURE_ENDPOINT": "", "AZURE_KEY": ""})
        self.aman = BrowserSession(self.app)
        self.simran = BrowserSession(self.app)
        self.aman_id = self.aman.use_demo("aman")
        self.simran_id = self.simran.use_demo("simran")
        group = next(group for group in self.aman.get("/api/groups").json["groups"] if group["name"] == "Jaipur Trip")
        self.group_path = f"/api/groups/{group['id']}"

    @staticmethod
    def version(draft):
        return dict(revision_id=draft["id"], edit_version=draft["edit_version"])

    def save(self, path, draft):
        saved = self.aman.call("PATCH", path + "/draft", dict(self.version(draft), draft=draft))
        self.assertEqual(saved.status_code, 200, saved.json)
        draft["edit_version"] = saved.json["edit_version"]

    def test_two_payers_validate_independently_of_member_shares(self):
        dinner = next(row for row in self.aman.get(self.group_path).json["expenses"]
                      if row["merchant"] == "The Campus Kitchen")
        path = f"/api/expenses/{dinner['id']}"
        posted = self.aman.get(path).json["revisions"][0]
        self.assertEqual(posted["contributions"], [
            dict(member_id=self.aman_id, amount_paise=50000, method="cash"),
            dict(member_id=self.simran_id, amount_paise=34000, method="upi"),
        ])
        self.aman.post(path + "/corrections", {})
        draft = self.aman.get(path).json["revisions"][0]
        draft["contributions"][0]["amount_paise"] = 49000
        self.save(path, draft)
        estimate = self.aman.post(path + "/preview", self.version(draft)).json
        self.assertEqual(sum(estimate["shares"].values()), 84000)
        self.assertEqual(estimate["contribution_difference_paise"], 1000)
        self.assertEqual(self.aman.post(path + "/post", self.version(draft)).status_code, 422)
        draft["contributions"][1]["amount_paise"] = 35000
        self.save(path, draft)
        self.assertEqual(self.aman.post(path + "/post", self.version(draft)).status_code, 200)
        latest, earlier = self.aman.get(path).json["revisions"]
        self.assertEqual(latest["shares"], earlier["shares"])
        self.assertEqual(earlier["contributions"], posted["contributions"])
        ledger = {r["id"]: r["net_paise"] for r in self.aman.get(self.group_path + "/balances").json["balances"]}
        self.assertEqual(ledger[self.aman_id], 22750)
        self.assertEqual(ledger[self.simran_id], 8750)
        self.assertEqual(sum(ledger.values()), 0)
        self.assertEqual(self.aman.get(self.group_path + "/fund").json["available_paise"], 80000)

    def test_fund_posting_permissions_overdraft_and_refund_retries(self):
        fund_path = self.group_path + "/fund"
        self.assertEqual(self.simran.get(fund_path).json["available_paise"], 80000)
        payment = dict(kind="deposit", member_id=self.simran_id, amount_paise=20000, request_key="test-top-up")
        self.assertEqual(self.simran.post(fund_path + "/entries", payment).status_code, 403)
        self.assertEqual(self.simran.post(fund_path + "/begin-refunds", {}).status_code, 403)

        expense = self.aman.post(self.group_path + "/expenses", {}).json
        path = f"/api/expenses/{expense['id']}"
        draft = self.aman.get(path).json["revisions"][0]
        draft.update(merchant="Trip supplies", purchase_date="2026-11-20", total_paise=80001,
                     contributions=[dict(member_id=None, amount_paise=None, method="")])
        self.save(path, draft)
        estimate = self.aman.post(path + "/preview", self.version(draft)).json
        self.assertEqual(estimate["fund_amount_paise"], 80001)
        self.assertTrue(any("available trip fund" in issue["message"] for issue in estimate["issues"]))
        self.assertEqual(self.simran.post(path + "/post", self.version(draft)).status_code, 403)
        self.assertEqual(self.aman.post(path + "/post", self.version(draft)).status_code, 409)
        self.assertEqual(self.aman.get(fund_path).json["available_paise"], 80000)

        refund = dict(kind="refund", member_id=self.aman_id, amount_paise=20000, request_key="test-refund")
        self.assertEqual(self.aman.post(fund_path + "/entries", refund).status_code, 409)
        self.assertEqual(self.aman.post(fund_path + "/begin-refunds", {}).json["status"], "refunding")
        first = self.aman.post(fund_path + "/entries", refund)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(self.aman.post(fund_path + "/entries", refund).json["id"], first.json["id"])
        self.assertEqual(self.aman.get(fund_path).json["available_paise"], 60000)


class ContributionMigrationTests(unittest.TestCase):
    def test_legacy_payer_becomes_a_contribution(self):
        instance = PROJECT / "instance"
        instance.mkdir(exist_ok=True)
        with TemporaryDirectory(dir=instance) as directory:
            data_dir = Path(directory)
            conn = sqlite3.connect(data_dir / "thrive.sqlite3")
            try:
                conn.executescript((PROJECT / "schema.sql").read_text(encoding="utf-8"))
                conn.executescript("""
                    INSERT INTO users VALUES (1, 'Legacy member', 'legacy@test.example', 'hash');
                    INSERT INTO groups(id, name) VALUES (1, 'Legacy group');
                    INSERT INTO group_members(group_id, user_id, role) VALUES (1, 1, 'organizer');
                    INSERT INTO expenses(id, group_id, created_by) VALUES (1, 1, 1), (2, 1, 1);
                    INSERT INTO expense_revisions
                        (id, expense_id, version, merchant, purchase_date, payer_id, total_paise, mode, status, created_by)
                    VALUES (1, 1, 1, 'Posted bill', '2026-11-20', 1, 84000, 'equal', 'posted', 1),
                           (2, 2, 1, 'Open draft', '2026-11-20', 1, 10000, 'equal', 'draft', 1);
                    INSERT INTO expense_shares VALUES (1, 1, 84000);
                    UPDATE expenses SET current_revision_id=1 WHERE id=1;
                    PRAGMA user_version=2;
                """)
            finally:
                conn.close()
            app = create_app({"DEMO": False, "TESTING": True, "DATA_DIR": data_dir})
            with app.app_context():
                rows = db().execute(
                    "SELECT revision_id, member_id, amount_paise FROM expense_contributions ORDER BY revision_id"
                ).fetchall()
                self.assertEqual([tuple(row) for row in rows], [(1, 1, 84000), (2, 1, None)])
