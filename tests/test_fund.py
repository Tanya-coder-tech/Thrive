from pathlib import Path
import sqlite3
import unittest

from fund import FundError, begin_refunds, fund_allocation, fund_state, record_fund_entry, validate_funding
from ledger import group_ledger


class FundTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        project = Path(__file__).resolve().parents[1]
        for source in ("schema.sql", "migrations/003_expense_funding.sql"):
            self.conn.executescript((project / source).read_text(encoding="utf-8"))
        self.conn.execute("INSERT INTO groups (id, name) VALUES (1, 'Jaipur visit')")
        for member_id, name in enumerate(("Aman", "Simran", "Karan", "Nisha"), 1):
            self.conn.execute("INSERT INTO users VALUES (?, ?, ?, '')", (member_id, name, f"{name}@example.test"))
            self.conn.execute("INSERT INTO group_members (group_id, user_id, role) VALUES (1, ?, ?)",
                              (member_id, "organizer" if member_id == 1 else "member"))

    def post(self, name, shares, contributions):
        fund_amount = sum(amount for member_id, amount in contributions if member_id is None)
        validate_funding(self.conn, 1, None, shares, fund_amount)
        expense_id = self.conn.execute("INSERT INTO expenses (group_id, created_by) VALUES (1, 1)").lastrowid
        revision_id = self.conn.execute(
            """INSERT INTO expense_revisions (expense_id, version, payer_id, merchant, purchase_date, total_paise,
                                               mode, status, created_by, posted_by, posted_at)
               VALUES (?, 1, 1, ?, '2026-11-20', ?, 'equal', 'posted', 1, 1, CURRENT_TIMESTAMP)""",
            (expense_id, name, sum(shares.values())),
        ).lastrowid
        self.conn.executemany(
            """INSERT INTO expense_contributions (revision_id, position, member_id, amount_paise, method)
               VALUES (?, ?, ?, ?, ?)""",
            [(revision_id, position, member_id, amount, "")
             for position, (member_id, amount) in enumerate(contributions)],
        )
        self.conn.executemany("INSERT INTO expense_shares VALUES (?, ?, ?)",
                              [(revision_id, member_id, share) for member_id, share in shares.items()])
        self.conn.execute("UPDATE expenses SET current_revision_id = ? WHERE id = ?", (revision_id, expense_id))
        return revision_id

    def entry(self, kind, member_id, amount, key):
        return record_fund_entry(self.conn, 1, 1, kind, member_id, amount, key)

    def test_jaipur_transport_and_personal_dinner_keep_funds_separate(self):
        for member_id in range(1, 5):
            self.entry("deposit", member_id, 100_000, f"advance-{member_id}")
        self.post("Jaipur transport", {1: 80_000, 2: 80_000, 3: 80_000, 4: 80_000}, [(None, 320_000)])
        self.post("Dinner", {1: 26_250, 2: 26_250, 3: 31_500}, [(1, 50_000), (2, 34_000)])

        fund = fund_state(self.conn, 1)
        self.assertEqual(
            (fund["status"], fund["available_paise"], fund["deposits_paise"], fund["spent_paise"]),
            ("open", 80_000, 400_000, 320_000),
        )
        self.assertEqual([member["actual_share_paise"] for member in fund["positions"]],
                         [106_250, 106_250, 111_500, 80_000])
        self.assertEqual([member["fund_share_paise"] for member in fund["positions"]], [80_000] * 4)
        self.assertEqual([member["refund_due_paise"] for member in fund["positions"]], [20_000] * 4)
        personal = group_ledger(self.conn, 1)["balances"]
        self.assertEqual([member["personal_paid_paise"] for member in personal], [50_000, 34_000, 0, 0])
        self.assertEqual([member["net_paise"] for member in personal], [23_750, 7_750, -31_500, 0])
        self.assertEqual([entry["description"] for entry in fund["activity"] if entry["kind"] == "expense"],
                         ["Jaipur transport"])
        with self.assertRaisesRegex(FundError, "exceeds the available trip fund"):
            validate_funding(self.conn, 1, None, {1: 80_001}, 80_001)
        with self.assertRaisesRegex(FundError, "Begin refunds"):
            self.entry("refund", 1, 20_000, "refund-1")

        self.assertEqual(begin_refunds(self.conn, 1)["status"], "refunding")
        with self.assertRaisesRegex(FundError, "exceeds the member"):
            self.entry("refund", 1, 20_001, "over-refund")
        with self.assertRaisesRegex(FundError, "finished collecting"):
            self.entry("deposit", 1, 1, "late-advance")
        for member_id in range(1, 5):
            self.entry("refund", member_id, 20_000, f"refund-{member_id}")
        repeated = self.entry("refund", 4, 20_000, "refund-4")
        self.assertEqual(repeated["member_id"], 4)
        with self.assertRaisesRegex(FundError, "different fund payment"):
            self.entry("refund", 4, 19_999, "refund-4")
        closed = begin_refunds(self.conn, 1)
        self.assertEqual((closed["status"], closed["available_paise"], closed["refunds_paise"]), ("closed", 0, 80_000))
        self.assertEqual([member["net_paise"] for member in closed["positions"]], [0] * 4)
        self.assertEqual(group_ledger(self.conn, 1)["balances"], personal)
        self.assertIsNotNone(closed["closed_at"])

    def test_top_up_needed_before_refunding(self):
        self.entry("deposit", 1, 100_000, "first-advance")
        self.post("Tour tickets", {2: 30_000}, [(None, 30_000)])

        current = fund_state(self.conn, 1)
        self.assertEqual(current["available_paise"], 70_000)
        self.assertEqual(current["positions"][1]["owed_paise"], 30_000)
        with self.assertRaisesRegex(FundError, "outstanding top-ups"):
            begin_refunds(self.conn, 1)
        self.entry("deposit", 2, 30_000, "top-up")
        refunding = begin_refunds(self.conn, 1)
        self.assertEqual(refunding["available_paise"], 100_000)
        self.assertEqual([position["refund_due_paise"] for position in refunding["positions"]], [100_000, 0, 0, 0])

    def test_fund_portion_rounding_and_revision_freeze(self):
        shares = {3: 100, 1: 100, 2: 100, 4: 0}
        self.assertEqual(fund_allocation(shares, 101), {1: 34, 2: 34, 3: 33})
        for member_id in range(1, 4):
            self.entry("deposit", member_id, 100, f"small-advance-{member_id}")
        original = self.post("Shared cab", shares, [(1, 199), (None, 101)])
        validate_funding(self.conn, 1, original, {1: 300}, 300)
        with self.assertRaisesRegex(FundError, "exceeds the available trip fund"):
            validate_funding(self.conn, 1, original, {1: 301}, 301)
        begin_refunds(self.conn, 1)
        validate_funding(self.conn, 1, original, {1: 200, 2: 200, 3: 200}, 101)
        with self.assertRaisesRegex(FundError, "locked"):
            validate_funding(self.conn, 1, original, {1: 300}, 101)
        with self.assertRaisesRegex(FundError, "locked"):
            validate_funding(self.conn, 1, original, shares, 0)

    def test_zero_cash_closes_without_refunds(self):
        self.entry("deposit", 1, 200, "exact-advance")
        self.post("Parking", {1: 200}, [(None, 200)])
        self.assertEqual(begin_refunds(self.conn, 1)["status"], "closed")
