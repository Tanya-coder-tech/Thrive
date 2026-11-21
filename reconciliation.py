"""Receipt validation and deterministic allocation in integer paise."""

from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re


MAX_PAISE = 100_000_000_000
PAYMENT_METHODS = ("", "cash", "upi", "bank", "card", "other")


def parse_paise(value):
    if value is None:
        return None
    clean = re.sub(r"(?i)INR|Rs\.?|₹|[,\s]", "", str(value)).replace("−", "-")
    try:
        amount = Decimal(clean)
        if not amount.is_finite() or abs(amount) > MAX_PAISE / 100:
            return None
        return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return None


def blank_draft(payer_id):
    return dict(merchant="", purchase_date="", payer_id=payer_id, total_paise=None,
                subtotal_paise=None, mode="equal", member_ids=[], items=[], adjustments=[],
                contributions=[dict(member_id=payer_id, amount_paise=None, method="")])


def normalize(data, *, fallback_payer_id=None):
    """Validate the shape of a partial draft, leaving accounting checks to preview."""
    if not isinstance(data, dict):
        raise ValueError("Provide the receipt fields as an object.")

    def label(value, limit):
        if not isinstance(value, str) or len(value) > limit:
            raise ValueError(f"Text must be at most {limit} characters.")
        return value.strip()

    def number(value, signed=False, optional=False):
        if optional and value is None:
            return None
        if type(value) is not int or not (-MAX_PAISE if signed else 0) <= value <= MAX_PAISE:
            raise ValueError("Enter valid amounts in integer paise.")
        return value

    def member(value):
        if type(value) is not int or value < 1 or value > 2**53 - 1:
            raise ValueError("Select a valid group member.")
        return value

    def rows(values, limit):
        if not isinstance(values, list) or len(values) > limit:
            raise ValueError(f"Provide a list of up to {limit} entries.")
        return values

    def members(values):
        return sorted({member(value) for value in rows(values, 100)})

    contributions = None
    if "contributions" in data:
        contributions = []
        for payment in rows(data["contributions"], 50):
            if not isinstance(payment, dict) or "member_id" not in payment:
                raise ValueError("Choose a group member or the trip fund for each contribution.")
            payer = payment["member_id"]
            if payer is not None:
                payer = member(payer)
            method = payment.get("method", "")
            if method not in PAYMENT_METHODS or (payer is None and method):
                raise ValueError("Choose a valid payment method for each personal contribution.")
            contributions.append(dict(member_id=payer, amount_paise=number(payment.get("amount_paise"), optional=True),
                                      method=method))
        # Keep an owner on legacy revision records, including bills paid entirely from the fund.
        payer_id = next((payment["member_id"] for payment in contributions if payment["member_id"] is not None),
                        fallback_payer_id or data.get("payer_id"))
    else:
        payer_id = data.get("payer_id", fallback_payer_id)
    draft = blank_draft(member(payer_id))
    if contributions is not None:
        draft["contributions"] = contributions
    draft["merchant"] = label(data.get("merchant", ""), 160)
    draft["purchase_date"] = label(data.get("purchase_date", ""), 10)
    if draft["purchase_date"]:
        try:
            if date.fromisoformat(draft["purchase_date"]).isoformat() != draft["purchase_date"]:
                raise ValueError
        except ValueError:
            raise ValueError("Enter a valid purchase date.") from None
    draft["total_paise"] = number(data.get("total_paise"), optional=True)
    draft["subtotal_paise"] = number(data.get("subtotal_paise"), optional=True)
    if data.get("mode") not in ("equal", "items"):
        raise ValueError("Choose equal split or item-wise split.")
    draft["mode"] = data["mode"]
    draft["member_ids"] = members(data.get("member_ids", []))

    for item in rows(data.get("items", []), 150):
        if not isinstance(item, dict):
            raise ValueError("Provide a description, amount, and participants for each item.")
        draft["items"].append(dict(description=label(item.get("description", ""), 180),
                                   amount_paise=number(item.get("amount_paise"), optional=True),
                                   member_ids=members(item.get("member_ids", []))))

    for adjustment in rows(data.get("adjustments", []), 30):
        if not isinstance(adjustment, dict):
            raise ValueError("Provide a type and amount for each adjustment.")
        kind = adjustment.get("kind")
        if kind not in ("tax", "discount", "rounding", "other"):
            raise ValueError("Choose a valid adjustment type.")
        amount = number(adjustment.get("amount_paise"), signed=True, optional=True)
        if amount is not None:
            if kind == "discount" and amount > 0:
                raise ValueError("Enter a discount as a negative amount.")
            if kind == "tax" and amount < 0:
                raise ValueError("Enter tax as a positive amount.")
        included = adjustment.get("included", False)
        if type(included) is not bool:
            raise ValueError("Choose whether the adjustment is already included.")
        draft["adjustments"].append(dict(kind=kind, amount_paise=amount, included=included))
    return draft


def equal_split(amount, member_ids):
    member_ids = sorted(member_ids)
    base, remainder = divmod(amount, len(member_ids))
    return {member: base + (index < remainder) for index, member in enumerate(member_ids)}


def proportional_split(amount, weights):
    total = sum(weights.values())
    parts = {member: divmod(abs(amount) * weight, total) for member, weight in weights.items()}
    leftover = abs(amount) - sum(base for base, _ in parts.values())
    ranked = sorted(parts, key=lambda member: (-parts[member][1], member))
    rounding_order = ranked[:leftover]
    extras = set(rounding_order)
    sign = -1 if amount < 0 else 1
    return {member: sign * (base + (member in extras)) for member, (base, _) in parts.items()}, rounding_order


def preview(draft, active_members):
    issues = []

    def issue(field, message):
        issues.append(dict(field=field, message=message))

    if not draft["merchant"]:
        issue("merchant", "Enter the merchant name.")
    if not draft["purchase_date"]:
        issue("purchase_date", "Enter the purchase date.")
    total = draft["total_paise"]
    if total is None or total <= 0:
        issue("total_paise", "Enter a receipt total greater than zero.")

    contributions = draft.get("contributions", [dict(member_id=draft["payer_id"], amount_paise=None, method="")])
    if not contributions:
        issue("contributions", "Add at least one payer or the trip fund.")
    contribution_total = 0
    fund_amount = 0
    fund_rows = 0
    resolved = []
    for index, contribution in enumerate(contributions):
        path = f"contributions.{index}"
        payer = contribution["member_id"]
        amount = contribution["amount_paise"]
        if amount is None and len(contributions) == 1:
            amount = total
        if amount is None or amount <= 0:
            issue(f"{path}.amount_paise", "Enter a positive contribution.")
        else:
            contribution_total += amount
        if payer is None:
            fund_rows += 1
            fund_amount += amount or 0
            if fund_rows > 1:
                issue(f"{path}.member_id", "Use one contribution row for the trip fund.")
        elif payer not in active_members:
            issue(f"{path}.member_id", "Choose a payer who is an active group member.")
        resolved.append(dict(contribution, amount_paise=amount))
    funding_difference = None if total is None else total - contribution_total
    if funding_difference:
        issue("contributions", "Payer contributions must add up to the receipt total.")

    items = draft["items"]
    item_split = draft["mode"] == "items"
    if item_split and not items:
        issue("items", "Add receipt items or choose a whole-bill split.")
    subtotal = 0
    item_shares = {}
    item_rounding = []
    for index, item in enumerate(items):
        amount = item["amount_paise"]
        if not item["description"]:
            issue(f"items.{index}.description", "Enter an item description.")
        if amount is None:
            issue(f"items.{index}.amount_paise", "Enter the printed line amount.")
        else:
            subtotal += amount
        if item_split:
            people = item["member_ids"]
            if not people or not set(people) <= active_members:
                issue(f"items.{index}.member_ids", "Assign this item to at least one group member.")
            elif amount is not None:
                parts = equal_split(amount, people)
                extra = [member for member, share in parts.items() if share > amount // len(people)]
                if extra:
                    item_rounding.append(dict(item_index=index, member_ids=extra))
                for member, share in parts.items():
                    item_shares[member] = item_shares.get(member, 0) + share

    adjustment_total = 0
    for index, adjustment in enumerate(draft["adjustments"]):
        if adjustment["amount_paise"] is None:
            issue(f"adjustments.{index}.amount_paise", "Enter the printed adjustment amount.")
        elif not adjustment["included"]:
            adjustment_total += adjustment["amount_paise"]

    printed_subtotal = draft["subtotal_paise"]
    included_total = sum(adjustment["amount_paise"] or 0 for adjustment in draft["adjustments"]
                         if adjustment["included"])
    if items and printed_subtotal is not None and subtotal not in (printed_subtotal, printed_subtotal + included_total):
        issue("subtotal_paise", "The line amounts do not add up to the printed subtotal.")
    reconstructed = subtotal if items else printed_subtotal
    if reconstructed is not None:
        reconstructed += adjustment_total
    elif adjustment_total:
        issue("subtotal_paise", "Enter a printed subtotal to reconcile adjustments without line items.")
    else:
        reconstructed = total
    difference = None if total is None or reconstructed is None else total - reconstructed
    if difference:
        issue("adjustments", "The line amounts and counted adjustments must match the receipt total.")

    adjustment_shares = {}
    adjustment_rounding = []
    if item_split:
        shares = item_shares.copy()
        if adjustment_total:
            if not sum(item_shares.values()):
                issue("adjustments", "Choose a whole-bill split or correct the item amounts before allocating adjustments.")
            else:
                adjustment_shares, adjustment_rounding = proportional_split(adjustment_total, item_shares)
                shares = {member: value + adjustment_shares[member] for member, value in shares.items()}
    else:
        people = draft["member_ids"]
        if not people or not set(people) <= active_members:
            issue("member_ids", "Select at least one group member to split the bill.")
            shares = {}
        else:
            shares = equal_split(total, people) if total is not None else {}
    if any(share < 0 for share in shares.values()):
        issue("adjustments", "Adjustments cannot make a member’s share negative.")
    if total is not None and sum(shares.values()) != total and not any(
        entry["field"].startswith(("items", "adjustments", "member_ids")) for entry in issues
    ):
        issue("shares", "The assigned shares do not match the receipt total.")
    return dict(issues=issues, subtotal_paise=subtotal, adjustment_paise=adjustment_total,
                reconstructed_paise=reconstructed, difference_paise=difference, shares=shares,
                contributions=resolved, contribution_total_paise=contribution_total,
                contribution_difference_paise=funding_difference, fund_amount_paise=fund_amount,
                item_subtotals=item_shares, adjustment_shares=adjustment_shares,
                item_rounding=item_rounding, adjustment_rounding=adjustment_rounding,
                rounding_recipients=([member for member, share in shares.items()
                                      if share > total // len(shares)]
                                     if not item_split and shares else []))
