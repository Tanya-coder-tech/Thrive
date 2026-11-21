CREATE TABLE expense_contributions (
    revision_id INTEGER NOT NULL REFERENCES expense_revisions(id),
    position INTEGER NOT NULL,
    member_id INTEGER REFERENCES users(id),
    amount_paise INTEGER CHECK (amount_paise >= 0 OR amount_paise IS NULL),
    method TEXT NOT NULL DEFAULT '' CHECK (method IN ('', 'cash', 'upi', 'bank', 'card', 'other')),
    PRIMARY KEY (revision_id, position),
    CHECK (member_id IS NOT NULL OR method = '')
);

INSERT INTO expense_contributions (revision_id, position, member_id, amount_paise)
SELECT id, 0, payer_id, CASE WHEN status = 'posted' THEN total_paise ELSE NULL END
FROM expense_revisions;

CREATE TABLE trip_funds (
    group_id INTEGER PRIMARY KEY REFERENCES groups(id),
    status TEXT NOT NULL CHECK (status IN ('open', 'refunding', 'closed')),
    refunding_at TEXT,
    closed_at TEXT
);

CREATE TABLE fund_entries (
    id INTEGER PRIMARY KEY,
    group_id INTEGER NOT NULL REFERENCES groups(id),
    member_id INTEGER NOT NULL REFERENCES users(id),
    actor_id INTEGER NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL CHECK (kind IN ('deposit', 'refund')),
    amount_paise INTEGER NOT NULL CHECK (amount_paise > 0),
    request_key TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (group_id, request_key)
);

CREATE TABLE receipt_duplicate_reviews (
    receipt_id INTEGER NOT NULL REFERENCES receipts(id),
    candidate_id INTEGER NOT NULL REFERENCES receipts(id),
    decision TEXT NOT NULL CHECK (decision IN ('duplicate', 'different')),
    reviewed_by INTEGER NOT NULL REFERENCES users(id),
    reviewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (receipt_id, candidate_id),
    CHECK (receipt_id < candidate_id)
);
