from argparse import ArgumentParser
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from hmac import compare_digest
from io import BytesIO
import json
import os
from pathlib import Path
import re
import secrets
from threading import Event

from flask import Flask, current_app, g, jsonify, redirect, render_template, request, send_file, session, url_for
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from database import close_db, db, initialize, transaction
from demo import installed_sample, seed
from demo_receipts import backfill_demo_identifier, demo_variants
from duplicate_receipts import Signature, confirmed_posted_duplicate, receipt_matches
from fund import FundError, begin_refunds, fund_state, record_fund_entry, validate_funding
from ledger import active_ids, audit, create_revision, group_ledger, members, post_revision, revision, write_draft
from receipt_extraction import PdfiumError, pdf_page_count, render_pdf_page, run_worker, start_worker, validate_file
from reconciliation import MAX_PAISE, blank_draft, normalize, preview


class APIError(Exception):
    def __init__(self, message, status=400, **details):
        self.message = message
        self.status = status
        self.details = details


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise APIError("Send a JSON object.")
    return data


def clean(data, key, limit, required=True):
    value = data.get(key, "")
    if not isinstance(value, str) or len(value.strip()) > limit or (required and not value.strip()):
        raise APIError(f"Enter a valid {key.replace('_', ' ')}.")
    return value.strip()


def person_id(data, key):
    value = data.get(key)
    if type(value) is not int or not 1 <= value <= 2**53 - 1:
        raise APIError(f"Select a valid {key.removesuffix('_id')}.")
    return value


def actor():
    if g.user is None:
        raise APIError("Sign in to continue.", 401)
    return g.user["id"]


def membership(conn, group_id, organizer=False):
    user_id = actor()
    if not 1 <= group_id <= 2**53 - 1:
        raise APIError("Group or record not found.", 404)
    group = conn.execute(
        """SELECT g.*, m.role FROM groups g JOIN group_members m ON m.group_id = g.id
           WHERE g.id = ? AND m.user_id = ? AND m.inactive_at IS NULL""", (group_id, user_id),
    ).fetchone()
    if group is None:
        raise APIError("Group or record not found.", 404)
    if organizer and group["role"] != "organizer":
        raise APIError("A group organizer must approve this action.", 403)
    return group


def record(conn, table, key):
    actor()
    if not 1 <= key <= 2**53 - 1:
        raise APIError("Group or record not found.", 404)
    row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (key,)).fetchone()
    if row is None:
        raise APIError("Group or record not found.", 404)
    membership(conn, row["group_id"])
    return row


def email_address(data, required=True):
    value = clean(data, "email", 254, required).casefold()
    if value and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        raise APIError("Enter a valid email address.")
    return value


def user_data(row):
    return {key: row[key] for key in ("id", "name", "email")} if row else None


def sign_in(user_id):
    session.clear()
    session["user_id"] = user_id
    session["csrf"] = secrets.token_urlsafe(24)
    return dict(user=user_data(db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()),
                csrf=session["csrf"])


@contextmanager
def read_snapshot():
    conn = db()
    conn.execute("BEGIN")
    try:
        yield conn
    finally:
        conn.rollback()


def draft_row(conn, expense_id):
    return conn.execute("SELECT * FROM expense_revisions WHERE expense_id = ? AND status = 'draft'",
                        (expense_id,)).fetchone()


def expected_draft(conn, expense_id, data):
    row = draft_row(conn, expense_id)
    if row is None or type(data.get("revision_id")) is not int or data["revision_id"] != row["id"] or not same_edit(row, data):
        raise APIError("This draft changed. Reload it to see the latest version.", 409)
    return row


def same_edit(row, data):
    return type(data.get("edit_version")) is int and row["edit_version"] == data["edit_version"]


def validate_draft_members(conn, group_id, draft):
    selected = {entry["member_id"] for entry in draft["contributions"] if entry["member_id"] is not None}
    selected.update(draft["member_ids"])
    for item in draft["items"]:
        selected.update(item["member_ids"])
    if not selected <= active_ids(conn, group_id):
        raise APIError("Select only active members of this group.")


def expense_summary(conn, group_id):
    expenses = {row["id"]: dict(row, contributions=[]) for row in conn.execute(
        """SELECT e.id, e.receipt_id, e.created_at, e.current_revision_id, r.merchant, r.purchase_date,
           r.payer_id, r.total_paise, r.mode, d.id AS draft_id, d.merchant AS draft_merchant,
           d.purchase_date AS draft_purchase_date, d.total_paise AS draft_total_paise, re.scan_status,
           (SELECT COUNT(*) FROM disputes q WHERE q.expense_id = e.id AND q.status = 'open') AS dispute_count
           FROM expenses e LEFT JOIN expense_revisions r ON e.current_revision_id = r.id
           LEFT JOIN expense_revisions d ON e.id = d.expense_id AND d.status = 'draft'
           LEFT JOIN receipts re ON e.receipt_id = re.id
           WHERE e.group_id = ? ORDER BY e.id DESC""", (group_id,)
    )}
    for row in conn.execute(
        """SELECT e.id AS expense_id, c.member_id, c.amount_paise, c.method FROM expenses e
           JOIN expense_contributions c ON c.revision_id = e.current_revision_id
           WHERE e.group_id = ? ORDER BY c.position""", (group_id,),
    ):
        payment = dict(row)
        expenses[payment.pop("expense_id")]["contributions"].append(payment)
    return list(expenses.values())


def receipt_data(conn, row, expense_id):
    extraction = json.loads(row["extraction_json"]) if row["extraction_json"] else {}
    signature = Signature.from_extraction(extraction)
    matches = receipt_matches(conn, row, signature)
    for match in matches:
        match["preview_url"] = url_for("receipt_file", receipt_id=match["id"])
        match["pdf_preview_url"] = (url_for("receipt_pdf_preview", receipt_id=match["id"], page_number=1)
                                    if match["mime_type"] == "application/pdf" else None)
    page_count = row["pdf_pages"]
    pdf_preview_url = None
    if row["mime_type"] == "application/pdf":
        if page_count is None:
            try:
                page_count = pdf_page_count(current_app.config["RECEIPT_DIR"] / row["file_key"])
            except (OSError, PdfiumError):
                page_count = 0
        if page_count:
            pdf_preview_url = url_for("receipt_pdf_preview", receipt_id=row["id"], page_number=1)
    return dict(id=row["id"], expense_id=expense_id, filename=row["filename"], mime_type=row["mime_type"],
                scan_status=row["scan_status"], scan_error=row["scan_error"], duplicate_of=row["duplicate_of"],
                created_at=row["created_at"], preview_url=url_for("receipt_file", receipt_id=row["id"]),
                page_count=page_count, pdf_preview_url=pdf_preview_url,
                extracted=extraction.get("source_draft"), uncertainty=extraction.get("uncertainty", []),
                comparison=signature.as_dict(), duplicate_matches=matches)


def create_app(overrides=None):
    app = Flask(__name__)
    demo_mode = os.getenv("THRIVE_DEMO") == "1"
    app.config.from_mapping(
        DEMO=demo_mode, DATA_DIR=Path(app.instance_path) / ("demo" if demo_mode else "workspace"),
        AZURE_ENDPOINT=os.getenv("DOCUMENTINTELLIGENCE_ENDPOINT", ""),
        AZURE_KEY=os.getenv("DOCUMENTINTELLIGENCE_API_KEY", ""),
        MAX_CONTENT_LENGTH=10 * 1024 * 1024 + 65536, MAX_RECEIPT_BYTES=10 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("THRIVE_HTTPS") == "1",
        SECRET_KEY=os.getenv("THRIVE_SECRET_KEY"),
    )
    app.config.update(overrides or {})
    data_dir = Path(app.config["DATA_DIR"])
    data_dir.mkdir(parents=True, exist_ok=True)
    app.config.setdefault("DATABASE", data_dir / "thrive.sqlite3")
    app.config.setdefault("RECEIPT_DIR", data_dir / "receipts")
    app.config["RECEIPT_DIR"] = Path(app.config["RECEIPT_DIR"])
    app.config["RECEIPT_DIR"].mkdir(exist_ok=True)
    app.teardown_appcontext(close_db)
    with app.app_context():
        initialize()
        with transaction() as conn:
            if not app.secret_key:
                conn.execute("INSERT OR IGNORE INTO app_settings VALUES ('session_key', ?)", (secrets.token_hex(32),))
                app.secret_key = conn.execute("SELECT value FROM app_settings WHERE name = 'session_key'").fetchone()["value"]
            if app.config["DEMO"]:
                seed(conn, app.config["RECEIPT_DIR"])
                backfill_demo_identifier(conn)
    register_routes(app)
    return app


def register_routes(app):
    @app.before_request
    def load_user():
        if request.endpoint == "static":
            return
        user_id = session.get("user_id")
        g.user = db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone() if user_id else None
        if request.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
            token = request.headers.get("X-CSRF-Token", "")
            expected = session.get("csrf")
            if not expected or not compare_digest(token.encode(), expected.encode()):
                raise APIError("Your session changed. Reload this page and try again.", 403)

    @app.after_request
    def headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Content-Security-Policy",
                                    "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                                    "object-src 'none'; frame-ancestors 'self'; base-uri 'none'; form-action 'self'")
        if request.endpoint != "static":
            response.headers["Cache-Control"] = "private, no-store"
        return response

    @app.errorhandler(APIError)
    def api_error(error):
        return jsonify(error=error.message, **error.details), error.status

    @app.errorhandler(ValueError)
    def invalid(error):
        return jsonify(error=str(error)), 400

    @app.errorhandler(FundError)
    def invalid_fund(error):
        return jsonify(error=str(error)), error.status

    @app.errorhandler(HTTPException)
    def http_error(error):
        message = "The receipt exceeds the 10 MB upload limit." if error.code == 413 else error.description
        return jsonify(error=message), error.code

    @app.get("/")
    def demo_opening():
        if app.config["DEMO"] and "invite" not in request.args:
            return redirect(url_for("static", filename="jaipur/index.html"))
        return index()

    @app.get("/workspace")
    def index():
        return render_template("index.html")

    @app.get("/api/session")
    def get_session():
        if app.config["DEMO"] and not g.user and not session.get("signed_out") and not request.args.get("invite"):
            demo_user = db().execute("SELECT id FROM users WHERE email = 'aman@thrive.demo'").fetchone()
            return jsonify(**sign_in(demo_user["id"]), demo=True)
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(24)
        return jsonify(user=user_data(g.user), csrf=session["csrf"], demo=app.config["DEMO"])

    @app.post("/api/auth/register")
    def register():
        data = body()
        name = clean(data, "name", 90)
        email = email_address(data)
        password = data.get("password")
        if not isinstance(password, str) or not 8 <= len(password) <= 256:
            raise APIError("Use a password with 8 to 256 characters.")
        password_hash = generate_password_hash(password)
        with transaction() as conn:
            if conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
                raise APIError("An account already uses this email.", 409)
            user_id = conn.execute("INSERT INTO users(name, email, password_hash) VALUES (?, ?, ?)",
                                   (name, email, password_hash)).lastrowid
        return jsonify(sign_in(user_id)), 201

    @app.post("/api/auth/login")
    def login():
        data = body()
        email = email_address(data)
        password = data.get("password")
        row = db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if not row or not isinstance(password, str) or len(password) > 256 or not check_password_hash(row["password_hash"], password):
            raise APIError("The email or password is incorrect.", 401)
        return jsonify(sign_in(row["id"]))

    @app.post("/api/auth/logout")
    def logout():
        session.clear()
        session["signed_out"] = True
        session["csrf"] = secrets.token_urlsafe(24)
        return jsonify(user=None, csrf=session["csrf"])

    @app.post("/api/demo/session")
    def demo_session():
        if not app.config["DEMO"]:
            raise APIError("Demo accounts are unavailable.", 404)
        person = clean(body(), "person", 10)
        if person not in ("aman", "simran", "karan", "nisha"):
            raise APIError("Choose a demo member.")
        row = db().execute("SELECT id FROM users WHERE email = ?", (person + "@thrive.demo",)).fetchone()
        if row is None:
            raise APIError("Demo member unavailable.", 404)
        return jsonify(sign_in(row["id"]))

    @app.get("/api/demo/receipt")
    def demo_receipt():
        if not app.config["DEMO"]:
            raise APIError("Demo receipt unavailable.", 404)
        actor()
        original = installed_sample(app.config["RECEIPT_DIR"])
        variant = request.args.get("sample")
        if variant:
            sample = demo_variants(original).get(variant)
            if sample is None:
                raise APIError("Demo receipt unavailable.", 404)
            return send_file(BytesIO(sample), mimetype="image/png", as_attachment=True, download_name=f"{variant}.png")
        return send_file(BytesIO(original), mimetype="image/png", as_attachment=True, download_name="campus-kitchen.png")

    @app.get("/api/groups")
    def list_groups():
        groups = db().execute(
            """SELECT g.*, m.role FROM groups g JOIN group_members m ON m.group_id = g.id
               WHERE m.user_id = ? AND m.inactive_at IS NULL ORDER BY g.id""", (actor(),),
        )
        return jsonify(groups=[dict(group) for group in groups])

    @app.post("/api/groups")
    def create_group():
        data = body()
        name = clean(data, "name", 110)
        description = clean(data, "description", 200, False)
        user_id = actor()
        with transaction() as conn:
            group_id = conn.execute("INSERT INTO groups(name, description) VALUES (?, ?)", (name, description)).lastrowid
            conn.execute("INSERT INTO group_members(group_id, user_id, role) VALUES (?, ?, 'organizer')",
                         (group_id, user_id))
            audit(conn, group_id, user_id, "group_created", name)
        return jsonify(id=group_id), 201

    @app.get("/api/groups/<int:group_id>")
    def get_group(group_id):
        with read_snapshot() as conn:
            group = membership(conn, group_id)
            events = conn.execute(
                """SELECT a.*, u.name AS actor_name FROM audit_events a JOIN users u ON a.actor_id = u.id
                   WHERE a.group_id = ? ORDER BY a.id DESC LIMIT 100""", (group_id,),
            )
            return jsonify(group=dict(group), members=members(conn, group_id), expenses=expense_summary(conn, group_id),
                           ledger=group_ledger(conn, group_id), activity=[dict(event) for event in events])

    @app.get("/api/groups/<int:group_id>/fund")
    def get_fund(group_id):
        with read_snapshot() as conn:
            membership(conn, group_id)
            return jsonify(fund_state(conn, group_id))

    @app.post("/api/groups/<int:group_id>/fund/entries")
    def add_fund_entry(group_id):
        data = body()
        with transaction() as conn:
            membership(conn, group_id, organizer=True)
            entry = record_fund_entry(conn, group_id, actor(), data.get("kind"), data.get("member_id"),
                                      data.get("amount_paise"), data.get("request_key"))
        return jsonify(entry), 201

    @app.post("/api/groups/<int:group_id>/fund/begin-refunds")
    def close_fund(group_id):
        with transaction() as conn:
            membership(conn, group_id, organizer=True)
            return jsonify(begin_refunds(conn, group_id))

    @app.post("/api/groups/<int:group_id>/invites")
    def create_invite(group_id):
        email = email_address(body(), False)
        token = secrets.token_urlsafe(30)
        expires = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        with transaction() as conn:
            membership(conn, group_id, organizer=True)
            conn.execute(
                "INSERT INTO invites(group_id, token_hash, email, expires_at, created_by) VALUES (?, ?, ?, ?, ?)",
                (group_id, sha256(token.encode()).hexdigest(), email or None, expires, actor()),
            )
            audit(conn, group_id, actor(), "invite_created", email or "Shareable invitation")
        return jsonify(path=url_for("index", invite=token), expires_at=expires), 201

    @app.patch("/api/groups/<int:group_id>/members/<int:user_id>")
    def update_role(group_id, user_id):
        role = clean(body(), "role", 10)
        if role not in ("organizer", "member"):
            raise APIError("Choose an organizer or member role.")
        with transaction() as conn:
            membership(conn, group_id, organizer=True)
            person = next((person for person in members(conn, group_id)
                           if person["id"] == user_id and not person["inactive_at"]), None)
            if person is None:
                raise APIError("Group member not found.", 404)
            if person["role"] != role:
                if role == "member" and not conn.execute(
                    """SELECT 1 FROM group_members WHERE group_id = ? AND user_id <> ?
                       AND inactive_at IS NULL AND role = 'organizer'""", (group_id, user_id),
                ).fetchone():
                    raise APIError("Assign another organizer before changing this role.", 409)
                conn.execute("UPDATE group_members SET role = ? WHERE group_id = ? AND user_id = ?",
                             (role, group_id, user_id))
                audit(conn, group_id, actor(), "member_role_changed", f"{person['name']} · {role}")
        return jsonify(id=user_id, role=role)

    @app.post("/api/invites/accept")
    def accept_invite():
        user_id = actor()
        token = clean(body(), "token", 80)
        with transaction() as conn:
            invite = conn.execute("SELECT * FROM invites WHERE token_hash = ?", (sha256(token.encode()).hexdigest(),)).fetchone()
            if invite and invite["accepted_by"] == user_id:
                membership(conn, invite["group_id"])
                return jsonify(id=invite["group_id"])
            if (not invite or invite["accepted_by"] or
                    datetime.fromisoformat(invite["expires_at"]) <= datetime.now(timezone.utc)):
                raise APIError("This invitation has expired or already been used.", 404)
            if invite["email"] and invite["email"] != g.user["email"]:
                raise APIError("Sign in with the email address on this invitation.", 403)
            conn.execute(
                """INSERT INTO group_members(group_id, user_id, role) VALUES (?, ?, 'member')
                   ON CONFLICT(group_id, user_id) DO UPDATE SET inactive_at = NULL""", (invite["group_id"], user_id),
            )
            conn.execute("UPDATE invites SET accepted_by = ? WHERE id = ?", (user_id, invite["id"]))
            audit(conn, invite["group_id"], user_id, "member_joined", g.user["name"])
        return jsonify(id=invite["group_id"])

    @app.post("/api/groups/<int:group_id>/expenses")
    def manual_expense(group_id):
        with transaction() as conn:
            membership(conn, group_id)
            expense_id = conn.execute("INSERT INTO expenses(group_id, created_by) VALUES (?, ?)",
                                      (group_id, actor())).lastrowid
            draft = blank_draft(actor())
            draft["member_ids"] = sorted(active_ids(conn, group_id))
            create_revision(conn, expense_id, 1, actor(), draft)
            audit(conn, group_id, actor(), "draft_created", "Manual expense", expense_id)
        return jsonify(id=expense_id), 201

    @app.post("/api/groups/<int:group_id>/receipts")
    def upload_receipt(group_id):
        membership(db(), group_id)
        upload = request.files.get("receipt")
        if not upload or not upload.filename:
            raise APIError("Choose a receipt to upload.")
        safe_name = secure_filename(upload.filename)
        name = Path(safe_name)
        filename = name.stem[:200] + name.suffix
        if not filename:
            raise APIError("Choose a receipt with a valid filename.")
        content = upload.stream.read(app.config["MAX_RECEIPT_BYTES"] + 1)
        if len(content) > app.config["MAX_RECEIPT_BYTES"]:
            raise APIError("The receipt exceeds the 10 MB upload limit.", 413)
        mime, pdf_pages = validate_file(filename, content)
        file_hash = sha256(content).hexdigest()
        file_key = secrets.token_hex(24) + Path(filename).suffix.lower()
        original = app.config["RECEIPT_DIR"] / file_key
        try:
            with transaction() as conn:
                membership(conn, group_id)
                duplicate = conn.execute(
                    "SELECT id FROM receipts WHERE group_id = ? AND file_hash = ? ORDER BY id LIMIT 1",
                    (group_id, file_hash),
                ).fetchone()
                original.write_bytes(content)
                receipt_id = conn.execute(
                    """INSERT INTO receipts(group_id, uploader_id, file_key, filename, mime_type,
                       file_hash, pdf_pages, scan_status, duplicate_of) VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?)""",
                    (group_id, actor(), file_key, filename, mime, file_hash, pdf_pages, duplicate["id"] if duplicate else None),
                ).lastrowid
                expense_id = conn.execute("INSERT INTO expenses(group_id, receipt_id, created_by) VALUES (?, ?, ?)",
                                          (group_id, receipt_id, actor())).lastrowid
                draft = blank_draft(actor())
                draft["member_ids"] = sorted(active_ids(conn, group_id))
                create_revision(conn, expense_id, 1, actor(), draft)
                audit(conn, group_id, actor(), "receipt_uploaded", filename, expense_id)
        except BaseException:
            original.unlink(missing_ok=True)
            raise
        return jsonify(id=receipt_id, expense_id=expense_id, scan_status="queued"), 202

    @app.get("/api/receipts/<int:receipt_id>")
    def get_receipt(receipt_id):
        with read_snapshot() as conn:
            row = record(conn, "receipts", receipt_id)
            expense = conn.execute("SELECT id FROM expenses WHERE receipt_id = ?", (receipt_id,)).fetchone()
            return jsonify(receipt_data(conn, row, expense["id"]))

    @app.patch("/api/receipts/<int:receipt_id>/matches/<int:candidate_id>")
    def review_receipt_match(receipt_id, candidate_id):
        decision = body().get("decision")
        if decision not in ("duplicate", "different"):
            raise APIError("Choose duplicate or separate purchase.")
        with transaction() as conn:
            row = record(conn, "receipts", receipt_id)
            if not 1 <= candidate_id <= 2**53 - 1:
                raise APIError("Receipt match not found.", 404)
            signature = Signature.from_extraction(json.loads(row["extraction_json"] or "{}"))
            matches = receipt_matches(conn, row, signature, candidate_id)
            if not matches:
                raise APIError("Receipt match not found.", 404)
            expense_id = conn.execute("SELECT id FROM expenses WHERE receipt_id = ?", (receipt_id,)).fetchone()["id"]
            first, second = sorted((receipt_id, candidate_id))
            result = conn.execute(
                """INSERT INTO receipt_duplicate_reviews(receipt_id, candidate_id, decision, reviewed_by)
                   VALUES (?, ?, ?, ?) ON CONFLICT (receipt_id, candidate_id) DO UPDATE SET
                   decision = excluded.decision, reviewed_by = excluded.reviewed_by, reviewed_at = CURRENT_TIMESTAMP
                   WHERE receipt_duplicate_reviews.decision <> excluded.decision""",
                (first, second, decision, actor()),
            )
            if result.rowcount:
                label = "Marked duplicate" if decision == "duplicate" else "Marked separate purchase"
                audit(conn, row["group_id"], actor(), "receipt_match_reviewed",
                      f"{label} · {row['filename']} and {matches[0]['filename']}", expense_id)
            return jsonify(receipt_data(conn, row, expense_id))

    @app.get("/api/receipts/<int:receipt_id>/file")
    def receipt_file(receipt_id):
        row = record(db(), "receipts", receipt_id)
        path = app.config["RECEIPT_DIR"] / row["file_key"]
        if not path.is_file():
            raise APIError("The original receipt could not be found.", 404)
        response = send_file(path, mimetype=row["mime_type"], download_name=row["filename"],
                             as_attachment=request.args.get("download") == "1", conditional=False)
        response.headers["Content-Security-Policy"] = "sandbox; default-src 'none'; frame-ancestors 'self'"
        return response

    @app.get("/api/receipts/<int:receipt_id>/pdf-preview/<int:page_number>")
    def receipt_pdf_preview(receipt_id, page_number):
        row = record(db(), "receipts", receipt_id)
        if row["mime_type"] != "application/pdf" or not 1 <= page_number <= 25:
            raise APIError("Receipt page not found.", 404)
        path = app.config["RECEIPT_DIR"] / row["file_key"]
        try:
            page = render_pdf_page(path, page_number)
        except (FileNotFoundError, IndexError):
            raise APIError("Receipt page not found.", 404) from None
        except (PdfiumError, ValueError):
            raise APIError("The PDF page cannot be previewed.", 422) from None
        return send_file(page, mimetype="image/png", conditional=False)

    @app.post("/api/receipts/<int:receipt_id>/retry")
    def retry_receipt(receipt_id):
        with transaction() as conn:
            row = record(conn, "receipts", receipt_id)
            if row["scan_status"] in ("queued", "processing"):
                return jsonify(scan_status=row["scan_status"]), 202
            if row["scan_status"] != "failed":
                raise APIError("Only failed scans can be retried.", 409)
            first = conn.execute(
                """SELECT r.edit_version FROM expenses e JOIN expense_revisions r ON e.id = r.expense_id
                   WHERE e.receipt_id = ? AND r.version = 1 AND r.status = 'draft'""", (receipt_id,),
            ).fetchone()
            # A retry never replaces a draft a reviewer has already edited.
            version = 1 if first and first["edit_version"] == 1 else 0
            conn.execute(
                """UPDATE receipts SET scan_status = 'queued', scan_error = NULL, attempts = 0,
                   next_attempt_at = 0, draft_version_at_queue = ? WHERE id = ?""", (version, receipt_id),
            )
        return jsonify(scan_status="queued"), 202

    @app.get("/api/expenses/<int:expense_id>")
    def get_expense(expense_id):
        with read_snapshot() as conn:
            expense = record(conn, "expenses", expense_id)
            versions = [revision(conn, row) for row in conn.execute(
                """SELECT r.*, u.name AS posted_by_name FROM expense_revisions r
                   LEFT JOIN users u ON r.posted_by = u.id WHERE r.expense_id = ? ORDER BY r.version DESC""",
                (expense_id,),
            )]
            receipt = None
            if expense["receipt_id"]:
                receipt = receipt_data(
                    conn, conn.execute("SELECT * FROM receipts WHERE id = ?", (expense["receipt_id"],)).fetchone(), expense_id,
                )
            disputes = [dict(row) for row in conn.execute(
                """SELECT d.*, u.name AS actor_name, a.name AS resolver_name, i.description AS item_description
                   FROM disputes d JOIN users u ON u.id = d.actor_id LEFT JOIN users a ON a.id = d.resolved_by
                   LEFT JOIN expense_items i ON i.id = d.item_id WHERE d.expense_id = ? ORDER BY d.id DESC""",
                (expense_id,),
            )]
            return jsonify(expense=dict(expense), revisions=versions, receipt=receipt, disputes=disputes)

    @app.patch("/api/expenses/<int:expense_id>/draft")
    def save_draft(expense_id):
        data = body()
        with transaction() as conn:
            expense = record(conn, "expenses", expense_id)
            row = expected_draft(conn, expense_id, data)
            draft = normalize(data.get("draft"), fallback_payer_id=row["payer_id"])
            validate_draft_members(conn, expense["group_id"], draft)
            write_draft(conn, row["id"], draft)
            audit(conn, expense["group_id"], actor(), "draft_updated", draft["merchant"] or "Receipt draft",
                  expense_id, row["id"])
        return jsonify(edit_version=row["edit_version"] + 1)

    @app.post("/api/expenses/<int:expense_id>/preview")
    def preview_expense(expense_id):
        data = body()
        with read_snapshot() as conn:
            expense = record(conn, "expenses", expense_id)
            row = expected_draft(conn, expense_id, data)
            draft = normalize(data["draft"], fallback_payer_id=row["payer_id"]) if "draft" in data else revision(conn, row)
            result = preview(draft, active_ids(conn, expense["group_id"]))
            if not result["issues"]:
                try:
                    validate_funding(conn, expense["group_id"], expense["current_revision_id"],
                                     result["shares"], result["fund_amount_paise"])
                except FundError as error:
                    result["issues"].append(dict(field="contributions", message=str(error)))
            return jsonify(result)

    @app.post("/api/expenses/<int:expense_id>/post")
    def post_expense(expense_id):
        data = body()
        revision_id = person_id(data, "revision_id")
        with transaction() as conn:
            expense = record(conn, "expenses", expense_id)
            row = conn.execute("SELECT * FROM expense_revisions WHERE id = ? AND expense_id = ?",
                               (revision_id, expense_id)).fetchone()
            if row is None or not same_edit(row, data):
                raise APIError("This draft changed. Reload it to see the latest version.", 409)
            if row["status"] == "posted":
                return jsonify(id=expense_id, revision_id=revision_id, status="posted")
            if expense["current_revision_id"]:
                membership(conn, expense["group_id"], organizer=True)
            elif expense["receipt_id"]:
                match = confirmed_posted_duplicate(conn, expense["receipt_id"])
                if match:
                    raise APIError("This receipt was confirmed as a duplicate of a posted expense.", 409,
                                   related_expense_id=match["id"])
            result = preview(revision(conn, row), active_ids(conn, expense["group_id"]))
            if result["issues"]:
                raise APIError("Resolve the review issues before posting.", 422, preview=result)
            if result["fund_amount_paise"] and not expense["current_revision_id"]:
                membership(conn, expense["group_id"], organizer=True)
            validate_funding(conn, expense["group_id"], expense["current_revision_id"],
                             result["shares"], result["fund_amount_paise"])
            post_revision(conn, expense, row, result["shares"], actor())
        return jsonify(id=expense_id, revision_id=revision_id, status="posted")

    @app.post("/api/expenses/<int:expense_id>/corrections")
    def create_correction(expense_id):
        with transaction() as conn:
            expense = record(conn, "expenses", expense_id)
            if not expense["current_revision_id"]:
                raise APIError("Post the first revision before proposing a correction.", 409)
            draft = draft_row(conn, expense_id)
            if draft:
                return jsonify(revision_id=draft["id"])
            active = conn.execute("SELECT * FROM expense_revisions WHERE id = ?", (expense["current_revision_id"],)).fetchone()
            revision_id = create_revision(conn, expense_id, active["version"] + 1, actor(), revision(conn, active))
            audit(conn, expense["group_id"], actor(), "correction_proposed", active["merchant"], expense_id, revision_id)
        return jsonify(revision_id=revision_id), 201

    @app.get("/api/groups/<int:group_id>/balances")
    def balances(group_id):
        with read_snapshot() as conn:
            membership(conn, group_id)
            return jsonify(group_ledger(conn, group_id))

    @app.post("/api/groups/<int:group_id>/settlements")
    def record_settlement(group_id):
        data = body()
        sender = person_id(data, "sender_id")
        recipient = person_id(data, "recipient_id")
        amount = data.get("amount_paise")
        key = clean(data, "request_key", 100, False) or None
        if type(amount) is not int or not 1 <= amount <= MAX_PAISE or sender == recipient:
            raise APIError("Choose a different recipient and enter a positive amount.")
        if sender != actor():
            raise APIError("Only the sender can record this payment.", 403)
        with transaction() as conn:
            membership(conn, group_id)
            if not {sender, recipient} <= active_ids(conn, group_id):
                raise APIError("Select an active group member as the recipient.")
            existing = conn.execute(
                "SELECT * FROM settlements WHERE group_id = ? AND sender_id = ? AND request_key = ?",
                (group_id, sender, key),
            ).fetchone() if key else None
            if existing:
                if existing["recipient_id"] != recipient or existing["amount_paise"] != amount:
                    raise APIError("This payment request was already used with different details.", 409)
                return jsonify(id=existing["id"], status=existing["status"])
            payment_id = conn.execute(
                """INSERT INTO settlements(group_id, sender_id, recipient_id, amount_paise, status, request_key)
                   VALUES (?, ?, ?, ?, 'pending', ?)""", (group_id, sender, recipient, amount, key),
            ).lastrowid
            audit(conn, group_id, sender, "payment_recorded", f"Payment #{payment_id}")
        return jsonify(id=payment_id, status="pending"), 201

    @app.post("/api/settlements/<int:payment_id>/confirm")
    def confirm_settlement(payment_id):
        with transaction() as conn:
            payment = record(conn, "settlements", payment_id)
            if payment["recipient_id"] != actor():
                raise APIError("Only the recipient can confirm this payment.", 403)
            if payment["status"] == "pending":
                conn.execute("UPDATE settlements SET status = 'confirmed', confirmed_at = CURRENT_TIMESTAMP WHERE id = ?",
                             (payment_id,))
                audit(conn, payment["group_id"], actor(), "payment_confirmed", f"Payment #{payment_id}")
        return jsonify(id=payment_id, status="confirmed")

    @app.post("/api/expenses/<int:expense_id>/disputes")
    def open_dispute(expense_id):
        data = body()
        reason = clean(data, "reason", 1000)
        revision_id = person_id(data, "revision_id")
        item_id = person_id(data, "item_id") if data.get("item_id") is not None else None
        with transaction() as conn:
            expense = record(conn, "expenses", expense_id)
            if not conn.execute("SELECT 1 FROM expense_revisions WHERE id = ? AND expense_id = ? AND status = 'posted'",
                                (revision_id, expense_id)).fetchone():
                raise APIError("Choose a posted version to question.", 404)
            if item_id is not None and not conn.execute("SELECT 1 FROM expense_items WHERE id = ? AND revision_id = ?",
                                                        (item_id, revision_id)).fetchone():
                raise APIError("Choose an item from this revision.", 404)
            dispute_id = conn.execute(
                "INSERT INTO disputes(expense_id, revision_id, item_id, actor_id, reason) VALUES (?, ?, ?, ?, ?)",
                (expense_id, revision_id, item_id, actor(), reason),
            ).lastrowid
            audit(conn, expense["group_id"], actor(), "dispute_opened", reason, expense_id, revision_id)
        return jsonify(id=dispute_id), 201

    @app.post("/api/disputes/<int:dispute_id>/resolve")
    def resolve_dispute(dispute_id):
        resolution = clean(body(), "resolution", 1000)
        with transaction() as conn:
            actor()
            row = conn.execute("SELECT * FROM disputes WHERE id = ?", (dispute_id,)).fetchone()
            if row is None:
                raise APIError("Group or record not found.", 404)
            expense = record(conn, "expenses", row["expense_id"])
            membership(conn, expense["group_id"], organizer=True)
            if row["status"] == "open":
                conn.execute(
                    """UPDATE disputes SET status = 'resolved', resolution = ?, resolved_by = ?,
                       resolved_at = CURRENT_TIMESTAMP WHERE id = ?""", (resolution, actor(), dispute_id),
                )
                audit(conn, expense["group_id"], actor(), "dispute_resolved", resolution,
                      expense["id"], row["revision_id"])
        return jsonify(id=dispute_id, status="resolved")

    @app.cli.command("worker")
    def worker_command():
        """Run the durable receipt queue."""
        run_worker(current_app._get_current_object())


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--demo", action="store_true", help="Use fictional accounts in a separate local database")
    parser.add_argument("--port", type=int, default=5050)
    arguments = parser.parse_args()
    if arguments.demo:
        os.environ["THRIVE_DEMO"] = "1"
    application = create_app()
    stop = Event()
    start_worker(application, stop)
    try:
        application.run(host="127.0.0.1", port=arguments.port)
    finally:
        stop.set()
