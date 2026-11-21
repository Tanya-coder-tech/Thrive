CREATE TABLE IF NOT EXISTS app_settings (
    name TEXT PRIMARY KEY, value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS group_members (
    group_id INTEGER NOT NULL REFERENCES groups(id), user_id INTEGER NOT NULL REFERENCES users(id),
    role TEXT NOT NULL CHECK (role IN ('organizer', 'member')),
    joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, inactive_at TEXT,
    PRIMARY KEY (group_id, user_id)
);
CREATE TABLE IF NOT EXISTS invites (
    id INTEGER PRIMARY KEY, group_id INTEGER NOT NULL REFERENCES groups(id),
    token_hash TEXT NOT NULL UNIQUE, email TEXT, expires_at TEXT NOT NULL,
    created_by INTEGER NOT NULL REFERENCES users(id), accepted_by INTEGER REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS receipts (
    id INTEGER PRIMARY KEY, group_id INTEGER NOT NULL REFERENCES groups(id),
    uploader_id INTEGER NOT NULL REFERENCES users(id), file_key TEXT NOT NULL UNIQUE,
    filename TEXT NOT NULL, mime_type TEXT NOT NULL, file_hash TEXT NOT NULL, pdf_pages INTEGER,
    scan_status TEXT NOT NULL CHECK (scan_status IN ('queued', 'processing', 'ready', 'failed')),
    extraction_json TEXT, scan_error TEXT, duplicate_of INTEGER REFERENCES receipts(id),
    attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at REAL NOT NULL DEFAULT 0,
    lease_until REAL, lease_token TEXT, draft_version_at_queue INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS receipt_jobs ON receipts(scan_status, next_attempt_at);
CREATE INDEX IF NOT EXISTS receipt_hashes ON receipts(group_id, file_hash);
CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY, group_id INTEGER NOT NULL REFERENCES groups(id),
    receipt_id INTEGER UNIQUE REFERENCES receipts(id), created_by INTEGER NOT NULL REFERENCES users(id),
    current_revision_id INTEGER REFERENCES expense_revisions(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS expense_revisions (
    id INTEGER PRIMARY KEY, expense_id INTEGER NOT NULL REFERENCES expenses(id), version INTEGER NOT NULL,
    edit_version INTEGER NOT NULL DEFAULT 1,
    payer_id INTEGER NOT NULL REFERENCES users(id), merchant TEXT NOT NULL,
    purchase_date TEXT NOT NULL, total_paise INTEGER, subtotal_paise INTEGER,
    mode TEXT NOT NULL CHECK (mode IN ('equal', 'items')),
    status TEXT NOT NULL CHECK (status IN ('draft', 'posted')),
    created_by INTEGER NOT NULL REFERENCES users(id), posted_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, posted_at TEXT,
    UNIQUE(expense_id, version)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_open_draft ON expense_revisions(expense_id) WHERE status = 'draft';
CREATE TABLE IF NOT EXISTS revision_members (
    revision_id INTEGER NOT NULL REFERENCES expense_revisions(id),
    member_id INTEGER NOT NULL REFERENCES users(id), PRIMARY KEY(revision_id, member_id)
);
CREATE TABLE IF NOT EXISTS expense_items (
    id INTEGER PRIMARY KEY, revision_id INTEGER NOT NULL REFERENCES expense_revisions(id),
    position INTEGER NOT NULL, description TEXT NOT NULL, amount_paise INTEGER
);
CREATE TABLE IF NOT EXISTS item_assignments (
    item_id INTEGER NOT NULL REFERENCES expense_items(id) ON DELETE CASCADE,
    member_id INTEGER NOT NULL REFERENCES users(id), PRIMARY KEY(item_id, member_id)
);
CREATE TABLE IF NOT EXISTS adjustments (
    id INTEGER PRIMARY KEY, revision_id INTEGER NOT NULL REFERENCES expense_revisions(id),
    kind TEXT NOT NULL, amount_paise INTEGER, included INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS expense_shares (
    revision_id INTEGER NOT NULL REFERENCES expense_revisions(id),
    member_id INTEGER NOT NULL REFERENCES users(id), share_paise INTEGER NOT NULL CHECK (share_paise >= 0),
    PRIMARY KEY(revision_id, member_id)
);
CREATE TABLE IF NOT EXISTS settlements (
    id INTEGER PRIMARY KEY, group_id INTEGER NOT NULL REFERENCES groups(id),
    sender_id INTEGER NOT NULL REFERENCES users(id), recipient_id INTEGER NOT NULL REFERENCES users(id),
    amount_paise INTEGER NOT NULL CHECK (amount_paise > 0), request_key TEXT,
    status TEXT NOT NULL CHECK (status IN ('pending', 'confirmed')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, confirmed_at TEXT,
    CHECK (sender_id <> recipient_id), UNIQUE(group_id, sender_id, request_key)
);
CREATE TABLE IF NOT EXISTS disputes (
    id INTEGER PRIMARY KEY, expense_id INTEGER NOT NULL REFERENCES expenses(id),
    revision_id INTEGER NOT NULL REFERENCES expense_revisions(id),
    item_id INTEGER REFERENCES expense_items(id), actor_id INTEGER NOT NULL REFERENCES users(id),
    reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved')),
    resolution TEXT, resolved_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY, group_id INTEGER NOT NULL REFERENCES groups(id),
    expense_id INTEGER REFERENCES expenses(id), revision_id INTEGER REFERENCES expense_revisions(id),
    actor_id INTEGER NOT NULL REFERENCES users(id), action TEXT NOT NULL, detail TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS expense_group ON expenses(group_id);
CREATE INDEX IF NOT EXISTS activity_group ON audit_events(group_id, id DESC);
