import sqlite3
from contextlib import contextmanager
from pathlib import Path

from flask import current_app, g


def db():
    if "db" not in g:
        connection = sqlite3.connect(current_app.config["DATABASE"], timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        g.db = connection
    return g.db


def close_db(_error):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def initialize():
    connection = db()
    connection.execute("PRAGMA journal_mode = WAL")
    with transaction() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            apply_schema(conn, "schema.sql")
        elif version == 1:
            conn.execute("ALTER TABLE receipts ADD COLUMN pdf_pages INTEGER")
        if version < 3:
            apply_schema(conn, "migrations/003_expense_funding.sql")
            conn.execute("PRAGMA user_version = 3")


def apply_schema(conn, filename):
    sql = Path(__file__).parent.joinpath(filename).read_text(encoding="utf-8")
    statement = ""
    for line in sql.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            conn.execute(statement)
            statement = ""
    if statement.strip():
        raise ValueError(f"Incomplete migration statement in {filename}")


@contextmanager
def transaction():
    connection = db()
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
