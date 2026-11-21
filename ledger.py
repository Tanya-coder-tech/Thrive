"""Revision persistence and the balance projection from the active ledger."""

from collections import defaultdict

from fund import fund_allocation


def audit(conn, group_id, actor_id, action, detail, expense_id=None, revision_id=None):
    conn.execute(
        """INSERT INTO audit_events(group_id, actor_id, action, detail, expense_id, revision_id)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (group_id, actor_id, action, detail, expense_id, revision_id),
    )


def revision(conn, row):
    result = dict(row)
    revision_id = row["id"]
    result["contributions"] = [dict(payment) for payment in conn.execute(
        """SELECT member_id, amount_paise, method FROM expense_contributions WHERE revision_id = ?
           ORDER BY position""", (revision_id,))]
    result["member_ids"] = [person["member_id"] for person in conn.execute(
        "SELECT member_id FROM revision_members WHERE revision_id = ? ORDER BY member_id", (revision_id,))]
    result["items"] = [dict(item) for item in conn.execute(
        "SELECT id, description, amount_paise FROM expense_items WHERE revision_id = ? ORDER BY position",
        (revision_id,))]
    assignments = {}
    for person in conn.execute(
        """SELECT a.item_id, a.member_id FROM item_assignments a JOIN expense_items i ON i.id = a.item_id
           WHERE i.revision_id = ? ORDER BY a.member_id""", (revision_id,)
    ):
        assignments.setdefault(person["item_id"], []).append(person["member_id"])
    for item in result["items"]:
        item["member_ids"] = assignments.get(item["id"], [])
    result["adjustments"] = [
        dict(kind=adjustment["kind"], amount_paise=adjustment["amount_paise"], included=bool(adjustment["included"]))
        for adjustment in conn.execute("SELECT * FROM adjustments WHERE revision_id = ? ORDER BY id", (revision_id,))
    ]
    result["shares"] = {share["member_id"]: share["share_paise"] for share in conn.execute(
        "SELECT member_id, share_paise FROM expense_shares WHERE revision_id = ? ORDER BY member_id", (revision_id,))}
    return result


def write_draft(conn, revision_id, draft, *, bump=True):
    conn.execute(
        """UPDATE expense_revisions SET merchant = ?, purchase_date = ?, payer_id = ?, total_paise = ?,
           subtotal_paise = ?, mode = ?, edit_version = edit_version + ? WHERE id = ? AND status = 'draft'""",
        (draft["merchant"], draft["purchase_date"], draft["payer_id"], draft["total_paise"],
         draft["subtotal_paise"], draft["mode"], int(bump), revision_id),
    )
    for table in ("expense_contributions", "revision_members", "expense_items", "adjustments"):
        conn.execute(f"DELETE FROM {table} WHERE revision_id = ?", (revision_id,))
    conn.executemany(
        """INSERT INTO expense_contributions(revision_id, position, member_id, amount_paise, method)
           VALUES (?, ?, ?, ?, ?)""",
        [(revision_id, position, payment["member_id"], payment["amount_paise"], payment["method"])
         for position, payment in enumerate(draft["contributions"])],
    )
    conn.executemany("INSERT INTO revision_members VALUES (?, ?)",
                     [(revision_id, member) for member in draft["member_ids"]])
    for position, item in enumerate(draft["items"]):
        item_id = conn.execute(
            "INSERT INTO expense_items(revision_id, position, description, amount_paise) VALUES (?, ?, ?, ?)",
            (revision_id, position, item["description"], item["amount_paise"]),
        ).lastrowid
        conn.executemany("INSERT INTO item_assignments VALUES (?, ?)",
                         [(item_id, member) for member in item["member_ids"]])
    conn.executemany(
        "INSERT INTO adjustments(revision_id, kind, amount_paise, included) VALUES (?, ?, ?, ?)",
        [(revision_id, adj["kind"], adj["amount_paise"], adj["included"]) for adj in draft["adjustments"]],
    )


def create_revision(conn, expense_id, version, actor, draft):
    revision_id = conn.execute(
        """INSERT INTO expense_revisions(expense_id, version, payer_id, merchant, purchase_date, mode, status, created_by)
           VALUES (?, ?, ?, '', '', 'equal', 'draft', ?)""", (expense_id, version, draft["payer_id"], actor),
    ).lastrowid
    write_draft(conn, revision_id, draft, bump=False)
    return revision_id


def post_revision(conn, expense, row, shares, actor):
    conn.execute(
        """UPDATE expense_contributions SET amount_paise = ? WHERE revision_id = ? AND amount_paise IS NULL""",
        (row["total_paise"], row["id"]),
    )
    conn.execute(
        """UPDATE expense_revisions SET status = 'posted', posted_by = ?, posted_at = CURRENT_TIMESTAMP
           WHERE id = ?""", (actor, row["id"]))
    conn.executemany("INSERT INTO expense_shares VALUES (?, ?, ?)",
                     [(row["id"], member, amount) for member, amount in shares.items()])
    conn.execute("UPDATE expenses SET current_revision_id = ? WHERE id = ?", (row["id"], expense["id"]))
    action = "correction_approved" if expense["current_revision_id"] else "expense_posted"
    audit(conn, expense["group_id"], actor, action, row["merchant"], expense["id"], row["id"])


def active_ids(conn, group_id):
    return {row["user_id"] for row in conn.execute(
        "SELECT user_id FROM group_members WHERE group_id = ? AND inactive_at IS NULL", (group_id,))}


def members(conn, group_id):
    return [dict(row) for row in conn.execute(
        """SELECT u.id, u.name, m.role, m.inactive_at FROM group_members m JOIN users u ON u.id = m.user_id
           WHERE m.group_id = ? ORDER BY u.id""", (group_id,))]


def group_ledger(conn, group_id):
    balances = {person["id"]: dict(person, net_paise=0, personal_paid_paise=0,
                                  actual_share_paise=0, fund_share_paise=0)
                for person in members(conn, group_id)}
    active_expenses = list(conn.execute(
        """SELECT r.id, r.total_paise FROM expenses e
           JOIN expense_revisions r ON r.id = e.current_revision_id WHERE e.group_id = ?""", (group_id,)))
    funded_amounts = defaultdict(int)
    for row in conn.execute(
        """SELECT c.revision_id, c.member_id, c.amount_paise FROM expenses e JOIN expense_contributions c
           ON c.revision_id = e.current_revision_id WHERE e.group_id = ?""", (group_id,)
    ):
        if row["member_id"] is None:
            funded_amounts[row["revision_id"]] += row["amount_paise"]
        else:
            balances[row["member_id"]]["personal_paid_paise"] += row["amount_paise"]
    shares_by_revision = defaultdict(dict)
    for row in conn.execute(
        """SELECT s.revision_id, s.member_id, s.share_paise FROM expenses e JOIN expense_shares s
           ON s.revision_id = e.current_revision_id WHERE e.group_id = ?""", (group_id,)
    ):
        shares_by_revision[row["revision_id"]][row["member_id"]] = row["share_paise"]
        balances[row["member_id"]]["actual_share_paise"] += row["share_paise"]
    for revision_id, amount in funded_amounts.items():
        for member_id, share in fund_allocation(shares_by_revision[revision_id], amount).items():
            balances[member_id]["fund_share_paise"] += share
    for person in balances.values():
        person["net_paise"] = person["personal_paid_paise"] - person["actual_share_paise"] + person["fund_share_paise"]
    settlements = [dict(row) for row in conn.execute(
        "SELECT * FROM settlements WHERE group_id = ? ORDER BY id DESC", (group_id,))]
    for row in settlements:
        if row["status"] == "confirmed":
            balances[row["sender_id"]]["net_paise"] += row["amount_paise"]
            balances[row["recipient_id"]]["net_paise"] -= row["amount_paise"]
    if sum(person["net_paise"] for person in balances.values()) != 0:
        raise RuntimeError("An unbalanced ledger was detected")
    return dict(
        balances=list(balances.values()), settlements=settlements,
        transfers=suggest_transfers(balances.values()),
        total_paise=sum(row["total_paise"] for row in active_expenses),
        posted_count=len(active_expenses),
    )


def suggest_transfers(people):
    debtors = [[p["id"], -p["net_paise"]] for p in people if p["net_paise"] < 0]
    creditors = [[p["id"], p["net_paise"]] for p in people if p["net_paise"] > 0]
    transfers = []
    debtor = creditor = 0
    while debtor < len(debtors) and creditor < len(creditors):
        sender, debt = debtors[debtor]
        recipient, credit = creditors[creditor]
        amount = min(debt, credit)
        transfers.append(dict(sender_id=sender, recipient_id=recipient, amount_paise=amount))
        debtors[debtor][1] -= amount
        creditors[creditor][1] -= amount
        debtor += debt == amount
        creditor += credit == amount
    return transfers
