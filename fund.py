"""Advance collections, fund-funded shares, and trip refunds in integer paise."""

from collections import defaultdict

from reconciliation import MAX_PAISE, proportional_split


class FundError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def fund_allocation(shares, amount_paise):
    """The part of each posted share covered by the trip fund."""
    if not amount_paise:
        return {}
    if amount_paise < 0 or amount_paise > sum(shares.values()):
        raise ValueError("Fund payments must be within the assigned expense total.")
    allocation, _ = proportional_split(amount_paise, shares)
    return {member_id: amount for member_id, amount in allocation.items() if amount}


def _fund_status(conn, group_id):
    row = conn.execute(
        "SELECT status, refunding_at, closed_at FROM trip_funds WHERE group_id = ?",
        (group_id,),
    ).fetchone()
    return dict(row) if row else dict(status="open", refunding_at=None, closed_at=None)


def _posted_expenses(conn, group_id):
    return conn.execute(
        """SELECT e.id AS expense_id, r.id AS revision_id, r.merchant AS description,
                  r.posted_by AS actor_id, r.posted_at AS created_at,
                  COALESCE((SELECT SUM(c.amount_paise) FROM expense_contributions c
                            WHERE c.revision_id = r.id AND c.member_id IS NULL), 0) AS amount_paise
           FROM expenses e JOIN expense_revisions r ON r.id = e.current_revision_id
           WHERE e.group_id = ?""",
        (group_id,),
    )


def fund_state(conn, group_id):
    positions = {
        row["id"]: dict(member_id=row["id"], name=row["name"], advance_paise=0,
                        actual_share_paise=0, fund_share_paise=0, refunds_paise=0)
        for row in conn.execute(
            """SELECT u.id, u.name FROM users u JOIN group_members m ON m.user_id = u.id
               WHERE m.group_id = ? ORDER BY u.id""",
            (group_id,),
        )
    }
    deposits = refunds = spent = 0
    activity = []
    for row in conn.execute(
        """SELECT f.id, f.kind, f.member_id, u.name AS member_name, f.actor_id, f.amount_paise, f.created_at
           FROM fund_entries f JOIN users u ON u.id = f.member_id WHERE f.group_id = ?""",
        (group_id,),
    ):
        entry = dict(row)
        activity.append(entry)
        position = positions[entry["member_id"]]
        if entry["kind"] == "deposit":
            position["advance_paise"] += entry["amount_paise"]
            deposits += entry["amount_paise"]
        else:
            position["refunds_paise"] += entry["amount_paise"]
            refunds += entry["amount_paise"]

    shares_by_revision = defaultdict(dict)
    for row in conn.execute(
        """SELECT s.revision_id, s.member_id, s.share_paise FROM expenses e JOIN expense_shares s
           ON s.revision_id = e.current_revision_id WHERE e.group_id = ?""",
        (group_id,),
    ):
        shares_by_revision[row["revision_id"]][row["member_id"]] = row["share_paise"]
        positions[row["member_id"]]["actual_share_paise"] += row["share_paise"]

    for row in _posted_expenses(conn, group_id):
        amount = row["amount_paise"]
        if amount:
            for member_id, share in fund_allocation(shares_by_revision[row["revision_id"]], amount).items():
                positions[member_id]["fund_share_paise"] += share
            spent += amount
            activity.append(dict(row, id=row["expense_id"], kind="expense", member_id=None, member_name=None))

    for position in positions.values():
        net = position["advance_paise"] - position["fund_share_paise"] - position["refunds_paise"]
        position.update(net_paise=net, refund_due_paise=max(net, 0), owed_paise=max(-net, 0))
    activity.sort(key=lambda item: (item["created_at"] or "", item["kind"] == "refund",
                                    item["kind"] == "expense", item["id"]), reverse=True)
    return dict(
        _fund_status(conn, group_id),
        available_paise=deposits - spent - refunds,
        deposits_paise=deposits,
        spent_paise=spent,
        refunds_paise=refunds,
        positions=list(positions.values()),
        activity=activity,
    )


def validate_funding(conn, group_id, old_revision_id, shares, amount_paise):
    """Enforce funding limits within the transaction that posts a revision."""
    old_amount = 0
    if old_revision_id:
        old_amount = conn.execute(
            """SELECT COALESCE(SUM(c.amount_paise), 0) FROM expense_contributions c
               JOIN expenses e ON e.current_revision_id = c.revision_id
               WHERE c.revision_id = ? AND e.group_id = ? AND c.member_id IS NULL""",
            (old_revision_id, group_id),
        ).fetchone()[0]
    if not old_amount and not amount_paise:
        return

    fund = fund_state(conn, group_id)
    if fund["status"] == "open":
        if amount_paise - old_amount > fund["available_paise"]:
            raise FundError("This payment exceeds the available trip fund. Collect a top-up or reduce the fund contribution.")
        return

    old_shares = {
        row["member_id"]: row["share_paise"]
        for row in conn.execute(
            "SELECT member_id, share_paise FROM expense_shares WHERE revision_id = ?",
            (old_revision_id,),
        )
    } if old_amount else {}
    if fund_allocation(old_shares, old_amount) != fund_allocation(shares, amount_paise):
        raise FundError("Fund spending and member charges are locked once refunds begin.")


def _existing_entry(conn, group_id, request_key):
    row = conn.execute(
        """SELECT f.id, f.kind, f.member_id, u.name AS member_name, f.actor_id, f.amount_paise, f.created_at
           FROM fund_entries f JOIN users u ON u.id = f.member_id
           WHERE f.group_id = ? AND f.request_key = ?""",
        (group_id, request_key),
    ).fetchone()
    return dict(row) if row else None


def record_fund_entry(conn, group_id, actor_id, kind, member_id, amount_paise, request_key):
    if kind not in ("deposit", "refund"):
        raise FundError("Choose an advance deposit or refund.", 422)
    if type(member_id) is not int:
        raise FundError("Select a group member.", 422)
    if type(amount_paise) is not int or not 0 < amount_paise <= MAX_PAISE:
        raise FundError("Enter a positive amount within the allowed range.", 422)
    if not isinstance(request_key, str) or not 1 <= len(request_key.strip()) <= 100:
        raise FundError("A request key is required to record a fund payment.", 422)
    request_key = request_key.strip()
    existing = _existing_entry(conn, group_id, request_key)
    if existing:
        if (existing["actor_id"], existing["kind"], existing["member_id"], existing["amount_paise"]) != (
            actor_id, kind, member_id, amount_paise
        ):
            raise FundError("This request key is already attached to a different fund payment.")
        return existing

    fund = fund_state(conn, group_id)
    position = next((position for position in fund["positions"] if position["member_id"] == member_id), None)
    if position is None:
        raise FundError("Select a member of this group.", 422)
    if kind == "deposit" and fund["status"] != "open":
        raise FundError("The trip fund has finished collecting advances.")
    if kind == "refund":
        if fund["status"] != "refunding":
            raise FundError("Begin refunds before recording a return from the trip fund.")
        if amount_paise > min(position["refund_due_paise"], fund["available_paise"]):
            raise FundError("This refund exceeds the member’s refundable balance or the available trip fund.")

    conn.execute(
        """INSERT INTO fund_entries (group_id, member_id, actor_id, kind, amount_paise, request_key)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (group_id, member_id, actor_id, kind, amount_paise, request_key),
    )
    if kind == "refund" and amount_paise == fund["available_paise"]:
        conn.execute(
            "UPDATE trip_funds SET status = 'closed', closed_at = CURRENT_TIMESTAMP WHERE group_id = ?",
            (group_id,),
        )
    return _existing_entry(conn, group_id, request_key)


def begin_refunds(conn, group_id):
    """Freeze member fund charges and start returning the remaining cash."""
    fund = fund_state(conn, group_id)
    if fund["status"] != "open":
        return fund
    if any(position["owed_paise"] for position in fund["positions"]):
        raise FundError("Collect outstanding top-ups from members before beginning refunds.")
    status = "refunding" if fund["available_paise"] else "closed"
    conn.execute(
        """INSERT INTO trip_funds (group_id, status, refunding_at, closed_at)
           VALUES (?, ?, CURRENT_TIMESTAMP, CASE WHEN ? = 'closed' THEN CURRENT_TIMESTAMP END)
           ON CONFLICT(group_id) DO UPDATE SET status = excluded.status,
               refunding_at = excluded.refunding_at, closed_at = excluded.closed_at""",
        (group_id, status, status),
    )
    return dict(fund, **_fund_status(conn, group_id))
