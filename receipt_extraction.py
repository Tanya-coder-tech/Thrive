"""Validate originals, normalize the receipt model, and process durable scan jobs."""

from datetime import date
from decimal import Decimal
from io import BytesIO
import json
from math import isfinite
from pathlib import Path
import secrets
from threading import Lock, Thread
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import warnings

from flask import current_app
from PIL import Image
from pypdfium2 import PdfDocument, PdfiumError

from database import transaction
from ledger import audit, members, write_draft
from reconciliation import blank_draft, normalize, parse_paise


TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".pdf": "application/pdf"}
CONFIDENCE_THRESHOLD = 0.8
PDF_LOCK = Lock()


class ScanError(Exception):
    def __init__(self, message, retryable=False):
        super().__init__(message)
        self.retryable = retryable


def pdf_page_count(source):
    with PDF_LOCK, PdfDocument(source) as document:
        return len(document)


def render_pdf_page(path, number):
    with PDF_LOCK, PdfDocument(path) as document:
        if not 1 <= number <= len(document):
            raise IndexError("Receipt page not found")
        page = document[number - 1]
        try:
            width, height = page.get_size()
            if not all(isfinite(side) and side > 0 for side in (width, height)):
                raise ValueError("Receipt page size is invalid")
            bitmap = page.render(scale=min(3, 1500 / max(width, height)))
            try:
                output = BytesIO()
                bitmap.to_pil().save(output, format="PNG")
            finally:
                bitmap.close()
        finally:
            page.close()
    output.seek(0)
    return output


def validate_file(filename, content):
    mime = TYPES.get(Path(filename).suffix.lower())
    if not mime:
        raise ValueError("Choose a JPG, PNG, or PDF receipt.")
    pdf_pages = None
    try:
        if mime == "application/pdf":
            if not content.startswith(b"%PDF-"):
                raise ValueError
            pdf_pages = pdf_page_count(content)
            if not 1 <= pdf_pages <= 25:
                raise ValueError
        else:
            expected = "JPEG" if mime == "image/jpeg" else "PNG"
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(content)) as image:
                    if image.format != expected or image.width * image.height > 25_000_000:
                        raise ValueError
                    image.verify()
                with Image.open(BytesIO(content)) as image:
                    image.load()
    except (OSError, ValueError, SyntaxError, PdfiumError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError("The receipt file is damaged, unsupported, or too large to read.") from None
    return mime, pdf_pages


def field_amount(field, currency_code="INR"):
    currency = field.get("valueCurrency")
    if isinstance(currency, dict):
        code = currency.get("currencyCode")
        if code and code != currency_code:
            return None
        return parse_paise(currency.get("amount"))
    for key in ("valueNumber", "valueInteger", "valueString", "content"):
        if field.get(key) is not None:
            return parse_paise(field[key])
    return None


def normalize_extraction(result, payer_id, member_ids, *, currency_code="INR"):
    documents = result.get("analyzeResult", result).get("documents", [])
    if len(documents) > 1:
        raise ScanError("Several receipts were detected. Upload one receipt or enter the details manually.")
    if not documents:
        raise ScanError("No receipt fields were recognized. Try another image or enter the details manually.")
    fields = documents[0].get("fields", {})
    draft = blank_draft(payer_id)
    uncertainty = []

    def amount_of(field):
        return field_amount(field, currency_code)

    def track(path, field, value):
        if value is None or value == "" or (field.get("confidence") or 0) < CONFIDENCE_THRESHOLD:
            uncertainty.append(dict(field=path, source=field.get("content"),
                                    confidence=field.get("confidence"),
                                    original=value))
        return value

    merchant = fields.get("MerchantName") or {}
    draft["merchant"] = track("merchant", merchant, (merchant.get("valueString") or merchant.get("content") or "")[:160])
    purchased = fields.get("TransactionDate") or {}
    raw_date = purchased.get("valueDate") or ""
    try:
        raw_date = date.fromisoformat(raw_date).isoformat()
    except (TypeError, ValueError):
        raw_date = ""
    draft["purchase_date"] = track("purchase_date", purchased, raw_date)
    for name, path in (("Total", "total_paise"), ("Subtotal", "subtotal_paise")):
        field = fields.get(name) or {}
        if field or name == "Total":
            amount = amount_of(field)
            draft[path] = track(path, field, amount if amount is not None and amount >= 0 else None)
    for index, row in enumerate((fields.get("Items") or {}).get("valueArray", [])[:150]):
        item = row.get("valueObject") or {}
        desc = item.get("Description") or item.get("Name") or {}
        printed = item.get("TotalPrice") or {}
        amount = amount_of(printed)
        unit_price = item.get("Price") or item.get("UnitPrice") or {}
        quantity = item.get("Quantity") or {}
        price = amount_of(unit_price)
        count = quantity.get("valueNumber", quantity.get("valueInteger"))
        if amount is None and price is not None and isinstance(count, (int, float, Decimal)) and count > 0:
            amount = parse_paise(Decimal(price) * Decimal(str(count)) / 100)
            printed = dict(content=f"{quantity.get('content', count)} × {unit_price.get('content', price / 100)}",
                           confidence=0)
        draft["items"].append(dict(
            description=track(f"items.{index}.description", desc, (desc.get("valueString") or desc.get("content") or "")[:180]),
            amount_paise=track(f"items.{index}.amount_paise", printed, amount if amount is not None and amount >= 0 else None),
            member_ids=[],
        ))
    for names, kind in ((("TotalTax", "Tax"), "tax"), (("TotalDiscount", "Discount"), "discount"),
                        (("Tip",), "other")):
        field = next((fields[name] for name in names if fields.get(name)), None)
        if field:
            amount = amount_of(field)
            if kind == "discount" and amount is not None:
                amount = -abs(amount)
            if kind == "tax" and amount is not None and amount < 0:
                amount = None
            draft["adjustments"].append(dict(kind=kind, amount_paise=track(
                f"adjustments.{len(draft['adjustments'])}.amount_paise", field, amount), included=False))
    if draft["items"]:
        draft["mode"] = "items"
        line_total = sum(item["amount_paise"] or 0 for item in draft["items"])
        for adjustment in draft["adjustments"]:
            if adjustment["kind"] == "tax" and line_total == draft["total_paise"] and all(
                item["amount_paise"] is not None for item in draft["items"]
            ) and sum(adj["amount_paise"] or 0 for adj in draft["adjustments"] if adj["kind"] != "tax") == 0:
                adjustment["included"] = True
    else:
        draft["member_ids"] = member_ids
    return normalize(draft), uncertainty


def scan_with_azure(content, mime, endpoint, key):
    if not (endpoint and key):
        raise ScanError("Receipt scanning is unavailable. Enter the details manually or configure Azure and retry.")
    url = endpoint.rstrip("/") + "/documentintelligence/documentModels/prebuilt-receipt:analyze?api-version=2024-11-30"
    endpoint_parts = urlsplit(endpoint)

    def request(address, body=None):
        headers = {"Ocp-Apim-Subscription-Key": key, "Content-Type": mime}
        try:
            return urlopen(Request(address, data=body, headers=headers), timeout=20)
        except HTTPError as error:
            raise ScanError("Azure could not scan this receipt.", error.code in (408, 429, 500, 502, 503, 504)) from None
        except (URLError, TimeoutError):
            raise ScanError("The receipt scanner could not be reached.", True) from None

    if endpoint_parts.scheme != "https" or not endpoint_parts.hostname:
        raise ScanError("The receipt scanner needs a valid HTTPS endpoint.")
    with request(url, content) as response:
        operation = response.headers.get("Operation-Location", "")
    operation_parts = urlsplit(operation)
    if operation_parts.scheme != "https" or operation_parts.netloc != endpoint_parts.netloc:
        raise ScanError("The receipt scanner returned an invalid operation URL.")
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        time.sleep(1.5)
        with request(operation) as response:
            result = json.load(response, parse_float=Decimal)
        status = result.get("status")
        if status == "succeeded":
            return result
        if status in ("failed", "canceled"):
            raise ScanError("Azure could not read this receipt. Try another image or enter it manually.")
    raise ScanError("Receipt scanning timed out. Try again or enter the details manually.", True)


def process_next():
    """Claim one committed receipt job. A lease allows another worker to recover interruptions."""
    now = time.time()
    lease = secrets.token_hex(16)
    with transaction() as conn:
        row = conn.execute(
            """SELECT * FROM receipts WHERE (scan_status = 'queued' AND next_attempt_at <= ?)
               OR (scan_status = 'processing' AND lease_until <= ?) ORDER BY id LIMIT 1""", (now, now),
        ).fetchone()
        if not row:
            return False
        conn.execute(
            """UPDATE receipts SET scan_status = 'processing', attempts = attempts + 1, lease_until = ?,
               lease_token = ? WHERE id = ?""", (now + 180, lease, row["id"]),
        )
        group_members = [person["id"] for person in members(conn, row["group_id"]) if not person["inactive_at"]]

    try:
        content = (current_app.config["RECEIPT_DIR"] / row["file_key"]).read_bytes()
        result = None
        if current_app.config["DEMO"]:
            from demo import installed_sample
            from demo_receipts import demo_extraction
            result = demo_extraction(installed_sample(current_app.config["RECEIPT_DIR"]), row["file_hash"])
        if result is None:
            result = scan_with_azure(content, row["mime_type"], current_app.config["AZURE_ENDPOINT"],
                                     current_app.config["AZURE_KEY"])
        draft, uncertainty = normalize_extraction(result, row["uploader_id"], group_members)
        payload = json.dumps(dict(raw=result, source_draft=draft, uncertainty=uncertainty),
                             ensure_ascii=False, default=lambda value: float(value))
        status, error, next_attempt = "ready", None, 0
    except ScanError as exc:
        retry = exc.retryable and row["attempts"] < 2
        status, error = ("queued" if retry else "failed"), str(exc)
        next_attempt = time.time() + 5 * 2 ** row["attempts"] if retry else 0
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        current_app.logger.exception("Could not process receipt %s", row["id"])
        status, error, next_attempt = "failed", "The scan could not be read. Retry or enter the receipt manually.", 0

    with transaction() as conn:
        update = conn.execute(
            """UPDATE receipts SET scan_status = ?, scan_error = ?, next_attempt_at = ?, extraction_json = ?,
               lease_until = NULL, lease_token = NULL WHERE id = ? AND lease_token = ?""",
            (status, error, next_attempt, payload if status == "ready" else None, row["id"], lease),
        )
        if update.rowcount and status == "ready":
            expense = conn.execute(
                """SELECT e.id AS expense_id, r.id FROM expenses e JOIN expense_revisions r ON r.expense_id = e.id
                   WHERE e.receipt_id = ? AND r.version = 1 AND r.status = 'draft' AND r.edit_version = ?""",
                (row["id"], row["draft_version_at_queue"]),
            ).fetchone()
            if expense:
                write_draft(conn, expense["id"], draft)
            audit(conn, row["group_id"], row["uploader_id"], "receipt_scanned", row["filename"],
                  expense["expense_id"] if expense else None)
    return True


def run_worker(app, stop=None):
    while stop is None or not stop.is_set():
        try:
            with app.app_context():
                if process_next():
                    continue
        except Exception:
            app.logger.exception("Receipt worker failed to claim or finish a job")
        if stop is None:
            time.sleep(1)
        else:
            stop.wait(1)


def start_worker(app, stop):
    worker = Thread(target=run_worker, args=(app, stop), daemon=True, name="receipt-worker")
    worker.start()
    return worker
