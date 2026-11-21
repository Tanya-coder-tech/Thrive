"""Explainable receipt matching within a single group."""

from dataclasses import dataclass
from difflib import SequenceMatcher
import json
import re
from unicodedata import normalize


NUMBER_FIELDS = ("ReceiptNumber", "ReceiptId", "BillNumber", "InvoiceNumber", "CheckNumber")
NUMBER_TEXT = re.compile(
    r"\b(?:receipt|bill|invoice)[ \t]*(?:(?:no\b\.?|number\b)[ \t]*[:#-]?[ \t]*|#[ \t]*)"
    r"([A-Z0-9][A-Z0-9/-]{0,39})\b",
    re.IGNORECASE,
)
BARE_NUMBER = re.compile(r"\b(?:receipt|bill|invoice)[ \t]+(\d{2,12})[ \t]*$", re.IGNORECASE | re.MULTILINE)


def compact(value):
    return "".join(char for char in normalize("NFKD", value.casefold()) if char.isalnum())


def receipt_number(result):
    analysis = result.get("analyzeResult", result)
    documents = analysis.get("documents", [])
    fields = documents[0].get("fields", {}) if len(documents) == 1 else {}
    values = []
    for key in NUMBER_FIELDS:
        field = fields.get(key) or {}
        confidence = field.get("confidence")
        if confidence is None or confidence >= 0.7:
            values.extend(field.get(name) for name in ("valueString", "content", "valueInteger", "valueNumber"))
    content = analysis.get("content") or ""
    values.extend(NUMBER_TEXT.findall(content))
    values.extend(BARE_NUMBER.findall(content))
    for value in values:
        if value is None:
            continue
        value = str(value).strip()
        labeled = NUMBER_TEXT.search(value) or BARE_NUMBER.search(value)
        if labeled:
            value = labeled[1]
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 /-]{0,39}", value) and any(char.isdigit() for char in value):
            return value
    return ""


@dataclass(frozen=True)
class Signature:
    merchant: str
    purchase_date: str
    total_paise: int | None
    number: str
    items: tuple

    @classmethod
    def from_extraction(cls, extraction):
        draft = extraction.get("source_draft") or {}
        return cls(
            draft.get("merchant") or "",
            draft.get("purchase_date") or "",
            draft.get("total_paise"),
            receipt_number(extraction.get("raw") or {}),
            tuple((item["description"], item.get("amount_paise"))
                  for item in draft.get("items", []) if compact(item.get("description") or "")),
        )

    def as_dict(self):
        return dict(merchant=self.merchant, purchase_date=self.purchase_date, total_paise=self.total_paise,
                    receipt_number=self.number, items=[label for label, _ in self.items])


def text_matches(first, second):
    if not first or not second:
        return False
    return first == second or (min(len(first), len(second)) >= 8
                               and SequenceMatcher(None, first, second).ratio() >= 0.88)


def shared_items(first, second):
    left = [(compact(name), amount) for name, amount in first]
    remaining = [(compact(name), amount) for name, amount in second]
    count = 0
    for name, amount in left:
        candidates = [
            index for index, (other_name, other_amount) in enumerate(remaining)
            if (amount is None or other_amount is None or amount == other_amount) and text_matches(name, other_name)
        ]
        if candidates:
            best = next((index for index in candidates if name == remaining[index][0]), candidates[0])
            remaining.pop(best)
            count += 1
    return count


def match_evidence(first, second):
    """Return review cues only when enough fields corroborate a match."""
    if (not first.purchase_date or first.purchase_date != second.purchase_date
            or not first.total_paise or first.total_paise != second.total_paise
            or not text_matches(compact(first.merchant), compact(second.merchant))):
        return []

    first_number, second_number = compact(first.number), compact(second.number)
    both_numbered = bool(first_number and second_number)
    if both_numbered and first_number != second_number:
        return []

    overlap = shared_items(first.items, second.items)
    if not both_numbered and (overlap < 2 or overlap * 5 < max(len(first.items), len(second.items)) * 3):
        return []

    evidence = ["Merchant names agree" if compact(first.merchant) == compact(second.merchant)
                else "Merchant names are similar", "Same purchase date", "Same receipt total"]
    if both_numbered:
        evidence.append("Matching receipt number")
    if overlap:
        evidence.append(f"{overlap} matching item {'name' if overlap == 1 else 'names'}")
    if not both_numbered:
        evidence.append("Receipt number missing from at least one scan")
    return evidence


def receipt_matches(conn, receipt, signature, candidate_id=None):
    receipt_id = receipt["id"]
    candidates = conn.execute(
        """SELECT r.id, r.filename, r.mime_type, r.file_hash, r.extraction_json,
                  e.id AS expense_id, e.current_revision_id, d.decision, d.reviewed_at, u.name AS reviewer_name
           FROM receipts r JOIN expenses e ON e.receipt_id = r.id
           LEFT JOIN receipt_duplicate_reviews d ON d.receipt_id = min(r.id, ?) AND d.candidate_id = max(r.id, ?)
           LEFT JOIN users u ON u.id = d.reviewed_by
           WHERE r.group_id = ? AND r.id <> ? AND (? IS NULL OR r.id = ?)
             AND (r.file_hash = ? OR d.decision IS NOT NULL OR
                  (r.scan_status = 'ready' AND json_extract(r.extraction_json, '$.source_draft.purchase_date') = ?
                   AND json_extract(r.extraction_json, '$.source_draft.total_paise') = ?))
           ORDER BY r.id DESC""",
        (receipt_id, receipt_id, receipt["group_id"], receipt_id, candidate_id, candidate_id,
         receipt["file_hash"], signature.purchase_date, signature.total_paise),
    )
    matches = []
    for candidate in candidates:
        exact = receipt["file_hash"] == candidate["file_hash"]
        other = Signature.from_extraction(json.loads(candidate["extraction_json"] or "{}"))
        pair = (signature, other) if receipt_id < candidate["id"] else (other, signature)
        evidence = ["Identical file contents"] if exact else match_evidence(*pair)
        if evidence or candidate["decision"]:
            matches.append(dict(
                id=candidate["id"], filename=candidate["filename"], mime_type=candidate["mime_type"],
                expense_id=candidate["expense_id"], posted=candidate["current_revision_id"] is not None,
                kind="exact" if exact else "likely", reasons=evidence, source=other.as_dict(),
                decision=candidate["decision"], reviewed_at=candidate["reviewed_at"], reviewer_name=candidate["reviewer_name"],
            ))
    return sorted(matches, key=lambda match: (match["decision"] is not None, match["kind"] != "exact"))


def confirmed_posted_duplicate(conn, receipt_id):
    """Find a posted counterpart through same-group, human-confirmed matches."""
    return conn.execute(
        """WITH RECURSIVE related(id, group_id) AS (
               SELECT id, group_id FROM receipts WHERE id = ?
               UNION
               SELECT neighbor.id, neighbor.group_id FROM related
               JOIN receipt_duplicate_reviews match ON related.id IN (match.receipt_id, match.candidate_id)
               JOIN receipts neighbor ON neighbor.id = CASE WHEN match.receipt_id = related.id
                   THEN match.candidate_id ELSE match.receipt_id END AND neighbor.group_id = related.group_id
               WHERE match.decision = 'duplicate'
           )
           SELECT e.id FROM related JOIN expenses e ON e.receipt_id = related.id
           WHERE related.id <> ? AND e.current_revision_id IS NOT NULL ORDER BY e.id LIMIT 1""",
        (receipt_id, receipt_id),
    ).fetchone()
