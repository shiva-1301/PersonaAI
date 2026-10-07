"""SQLite schema and queries."""

import sqlite3
from contextlib import contextmanager

from core import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT NOT NULL UNIQUE COLLATE NOCASE,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS documents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filename    TEXT NOT NULL,
    subject     TEXT,
    page_count  INTEGER NOT NULL DEFAULT 0,
    uploaded_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS topics (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    name        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quiz_attempts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    score       INTEGER NOT NULL DEFAULT 0,
    total       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS quiz_answers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id  INTEGER NOT NULL REFERENCES quiz_attempts(id) ON DELETE CASCADE,
    topic_id    INTEGER REFERENCES topics(id) ON DELETE SET NULL,
    question    TEXT NOT NULL,
    chosen      TEXT,
    correct     TEXT NOT NULL,
    is_correct  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS topic_scores (
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    topic_id    INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    attempts    INTEGER NOT NULL DEFAULT 0,
    correct     INTEGER NOT NULL DEFAULT 0,
    accuracy    REAL NOT NULL DEFAULT 0,
    last_seen   TEXT,
    PRIMARY KEY (user_id, topic_id)
);

CREATE TABLE IF NOT EXISTS study_plans (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    exam_date     TEXT NOT NULL,
    hours_per_day REAL NOT NULL,
    plan_json     TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


@contextmanager
def connect(db_path=None):
    """Open a connection with foreign keys on and rows accessible by column name."""
    conn = sqlite3.connect(db_path or config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path=None) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def get_or_create_user(username: str, db_path=None) -> sqlite3.Row:
    username = username.strip()
    if not username:
        raise ValueError("Username cannot be empty.")
    with connect(db_path) as conn:
        conn.execute("INSERT OR IGNORE INTO users (username) VALUES (?)", (username,))
        return conn.execute(
            "SELECT id, username, created_at FROM users WHERE username = ?", (username,)
        ).fetchone()


# --- Documents ---

def add_document(user_id: int, filename: str, subject: str | None, page_count: int, db_path=None) -> int:
    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO documents (user_id, filename, subject, page_count) VALUES (?, ?, ?, ?)",
            (user_id, filename, subject, page_count),
        )
        return cur.lastrowid


def list_documents(user_id: int, db_path=None) -> list[sqlite3.Row]:
    with connect(db_path) as conn:
        return conn.execute(
            "SELECT * FROM documents WHERE user_id = ? ORDER BY uploaded_at DESC, id DESC",
            (user_id,),
        ).fetchall()


def find_document(user_id: int, filename: str, db_path=None) -> sqlite3.Row | None:
    with connect(db_path) as conn:
        return conn.execute(
            "SELECT * FROM documents WHERE user_id = ? AND filename = ?", (user_id, filename)
        ).fetchone()


def delete_document(document_id: int, db_path=None) -> None:
    """Deletes the document and (via ON DELETE CASCADE) its topics."""
    with connect(db_path) as conn:
        conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))


# --- Topics ---

def set_topics(user_id: int, document_id: int, names: list[str], db_path=None) -> None:
    """Replace a document's topic list. Topics whose names are kept keep their ids
    (and so their quiz history); removed ones are deleted."""
    wanted = []
    for name in names:
        name = " ".join(name.split())
        if name and name.lower() not in {w.lower() for w in wanted}:
            wanted.append(name)
    with connect(db_path) as conn:
        existing = {
            r["name"].lower(): r["id"]
            for r in conn.execute("SELECT id, name FROM topics WHERE document_id = ?", (document_id,))
        }
        keep = {n.lower() for n in wanted}
        for lname, topic_id in existing.items():
            if lname not in keep:
                conn.execute("DELETE FROM topics WHERE id = ?", (topic_id,))
        for name in wanted:
            if name.lower() not in existing:
                conn.execute(
                    "INSERT INTO topics (user_id, document_id, name) VALUES (?, ?, ?)",
                    (user_id, document_id, name),
                )


def list_topics(user_id: int, document_id: int | None = None, db_path=None) -> list[sqlite3.Row]:
    with connect(db_path) as conn:
        if document_id is None:
            return conn.execute(
                "SELECT * FROM topics WHERE user_id = ? ORDER BY document_id, id", (user_id,)
            ).fetchall()
        return conn.execute(
            "SELECT * FROM topics WHERE user_id = ? AND document_id = ? ORDER BY id",
            (user_id, document_id),
        ).fetchall()
