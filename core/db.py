"""SQLite schema and queries."""

import sqlite3
from contextlib import contextmanager

from core import config

SCHEMA = """
-- A department + year group of students that shares course notes, e.g. CSE year 3.
CREATE TABLE IF NOT EXISTS cohorts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    department  TEXT NOT NULL COLLATE NOCASE,
    year        TEXT NOT NULL COLLATE NOCASE,
    UNIQUE (department, year)
);

CREATE TABLE IF NOT EXISTS subjects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    cohort_id   INTEGER NOT NULL REFERENCES cohorts(id) ON DELETE CASCADE,
    name        TEXT NOT NULL COLLATE NOCASE,
    UNIQUE (cohort_id, name)
);

-- username is the hall-ticket number for students ("admin" for the admin).
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    full_name     TEXT,
    password_hash TEXT,
    cohort_id     INTEGER REFERENCES cohorts(id) ON DELETE SET NULL
);

-- cohort_id set = course notes shared with that cohort (uploaded by the admin);
-- cohort_id NULL = a student's personal notes.
CREATE TABLE IF NOT EXISTS documents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filename    TEXT NOT NULL,
    subject     TEXT,
    page_count  INTEGER NOT NULL DEFAULT 0,
    uploaded_at TEXT NOT NULL DEFAULT (datetime('now')),
    cohort_id   INTEGER REFERENCES cohorts(id) ON DELETE CASCADE,
    subject_id  INTEGER REFERENCES subjects(id) ON DELETE SET NULL,
    unit        TEXT
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

-- A student's exam timetable; subject is a name, matching their documents' subjects.
CREATE TABLE IF NOT EXISTS exams (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subject     TEXT NOT NULL,
    exam_date   TEXT NOT NULL,
    start_time  TEXT
);
"""

# Columns added after the first release: (table, column, definition). init_db adds any
# that an existing database is missing.
_NEW_COLUMNS = [
    ("users", "full_name", "TEXT"),
    ("users", "password_hash", "TEXT"),
    ("users", "cohort_id", "INTEGER REFERENCES cohorts(id) ON DELETE SET NULL"),
    ("documents", "cohort_id", "INTEGER REFERENCES cohorts(id) ON DELETE CASCADE"),
    ("documents", "subject_id", "INTEGER REFERENCES subjects(id) ON DELETE SET NULL"),
    ("documents", "unit", "TEXT"),
]

# Documents a user can see: their own, plus the course notes shared with their cohort.
# Uses the named parameter :uid.
_VISIBLE = (
    "(d.user_id = :uid OR (d.cohort_id IS NOT NULL"
    " AND d.cohort_id = (SELECT cohort_id FROM users WHERE id = :uid)))"
)


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
        for table, column, definition in _NEW_COLUMNS:
            existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        # Backfill scores for quizzes taken before score tracking existed.
        stale = conn.execute(
            "SELECT DISTINCT q.user_id FROM quiz_attempts q WHERE NOT EXISTS"
            " (SELECT 1 FROM topic_scores s WHERE s.user_id = q.user_id)"
        ).fetchall()
        for row in stale:
            _refresh_topic_scores(conn, row["user_id"])


def get_or_create_user(username: str, db_path=None) -> sqlite3.Row:
    username = username.strip()
    if not username:
        raise ValueError("Username cannot be empty.")
    with connect(db_path) as conn:
        conn.execute("INSERT OR IGNORE INTO users (username) VALUES (?)", (username,))
        return conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()


def find_user(username: str, db_path=None) -> sqlite3.Row | None:
    with connect(db_path) as conn:
        return conn.execute("SELECT * FROM users WHERE username = ?", (username.strip(),)).fetchone()


def get_user(user_id: int, db_path=None) -> sqlite3.Row | None:
    with connect(db_path) as conn:
        return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def set_password_hash(user_id: int, password_hash: str | None, db_path=None) -> None:
    """Store a password hash; None clears it so the student sets a new one at next sign-in."""
    with connect(db_path) as conn:
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))


# --- Cohorts, subjects, class lists ---

def get_or_create_cohort(department: str, year: str, db_path=None) -> int:
    department, year = " ".join(department.split()).upper(), " ".join(str(year).split())
    if not department or not year:
        raise ValueError("Department and year are required.")
    with connect(db_path) as conn:
        conn.execute("INSERT OR IGNORE INTO cohorts (department, year) VALUES (?, ?)", (department, year))
        return conn.execute(
            "SELECT id FROM cohorts WHERE department = ? AND year = ?", (department, year)
        ).fetchone()["id"]


def list_cohorts(db_path=None) -> list[sqlite3.Row]:
    with connect(db_path) as conn:
        return conn.execute(
            "SELECT c.*, (SELECT COUNT(*) FROM users u WHERE u.cohort_id = c.id) AS students"
            " FROM cohorts c ORDER BY c.department, c.year"
        ).fetchall()


def get_cohort(cohort_id: int, db_path=None) -> sqlite3.Row | None:
    with connect(db_path) as conn:
        return conn.execute("SELECT * FROM cohorts WHERE id = ?", (cohort_id,)).fetchone()


def add_subject(cohort_id: int, name: str, db_path=None) -> int:
    name = " ".join(name.split())
    if not name:
        raise ValueError("Subject name is required.")
    with connect(db_path) as conn:
        conn.execute("INSERT OR IGNORE INTO subjects (cohort_id, name) VALUES (?, ?)", (cohort_id, name))
        return conn.execute(
            "SELECT id FROM subjects WHERE cohort_id = ? AND name = ?", (cohort_id, name)
        ).fetchone()["id"]


def list_subjects(cohort_id: int, db_path=None) -> list[sqlite3.Row]:
    with connect(db_path) as conn:
        return conn.execute(
            "SELECT * FROM subjects WHERE cohort_id = ? ORDER BY name", (cohort_id,)
        ).fetchall()


def import_students(rows: list[dict], db_path=None) -> tuple[int, int]:
    """Add or update students from a class list: dicts with hall_ticket, name, department,
    year. Existing students keep their password and history. Returns (added, updated)."""
    added = updated = 0
    for row in rows:
        ticket = str(row["hall_ticket"]).strip().upper()
        if not ticket or ticket.lower() == "admin":
            raise ValueError(f"Invalid hall ticket number: {row['hall_ticket']!r}")
        cohort_id = get_or_create_cohort(row["department"], row["year"], db_path)
        with connect(db_path) as conn:
            exists = conn.execute("SELECT 1 FROM users WHERE username = ?", (ticket,)).fetchone()
            conn.execute(
                "INSERT INTO users (username, full_name, cohort_id) VALUES (?, ?, ?)"
                " ON CONFLICT(username) DO UPDATE SET full_name = excluded.full_name,"
                " cohort_id = excluded.cohort_id",
                (ticket, " ".join(str(row.get("name") or "").split()) or None, cohort_id),
            )
        updated += bool(exists)
        added += not exists
    return added, updated


def list_students(cohort_id: int, db_path=None) -> list[sqlite3.Row]:
    with connect(db_path) as conn:
        return conn.execute(
            "SELECT id, username, full_name, password_hash IS NOT NULL AS has_password"
            " FROM users WHERE cohort_id = ? ORDER BY username", (cohort_id,)
        ).fetchall()


# --- Documents ---

def add_document(
    user_id: int, filename: str, subject: str | None, page_count: int, db_path=None, *,
    cohort_id: int | None = None, subject_id: int | None = None, unit: str | None = None,
) -> int:
    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO documents (user_id, filename, subject, page_count, cohort_id, subject_id, unit)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, filename, subject, page_count, cohort_id, subject_id, unit),
        )
        return cur.lastrowid


_DOCUMENT_COLUMNS = (
    "SELECT d.*, COALESCE(s.name, d.subject) AS subject_name, d.cohort_id IS NOT NULL AS shared"
    " FROM documents d LEFT JOIN subjects s ON s.id = d.subject_id"
)


def list_documents(user_id: int, db_path=None) -> list[sqlite3.Row]:
    """The user's own documents and their cohort's shared course notes, newest first."""
    with connect(db_path) as conn:
        return conn.execute(
            f"{_DOCUMENT_COLUMNS} WHERE {_VISIBLE} ORDER BY d.uploaded_at DESC, d.id DESC",
            {"uid": user_id},
        ).fetchall()


def list_cohort_documents(cohort_id: int, db_path=None) -> list[sqlite3.Row]:
    with connect(db_path) as conn:
        return conn.execute(
            f"{_DOCUMENT_COLUMNS} WHERE d.cohort_id = ? ORDER BY subject_name, d.unit, d.filename",
            (cohort_id,),
        ).fetchall()


def get_document(document_id: int, db_path=None) -> sqlite3.Row | None:
    with connect(db_path) as conn:
        return conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()


def find_document(
    user_id: int, filename: str, db_path=None, *, cohort_id: int | None = None
) -> sqlite3.Row | None:
    """The user's document with this name: personal (cohort_id None) or shared with a cohort."""
    with connect(db_path) as conn:
        return conn.execute(
            "SELECT * FROM documents WHERE user_id = ? AND filename = ? AND cohort_id IS ?",
            (user_id, filename, cohort_id),
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
    """Topics of the documents the user can see (their own and their cohort's)."""
    sql = (
        "SELECT t.* FROM topics t LEFT JOIN documents d ON d.id = t.document_id"
        f" WHERE (t.user_id = :uid OR {_VISIBLE})"
    )
    with connect(db_path) as conn:
        if document_id is None:
            return conn.execute(sql + " ORDER BY t.document_id, t.id", {"uid": user_id}).fetchall()
        return conn.execute(
            sql + " AND t.document_id = :doc ORDER BY t.id", {"uid": user_id, "doc": document_id}
        ).fetchall()


# --- Quizzes ---

def save_quiz_attempt(
    user_id: int, score: int, total: int, answers: list[tuple], db_path=None
) -> int:
    """Save an attempt and its answers in one transaction.
    answers: (topic_id, question, chosen, correct, is_correct) per question."""
    with connect(db_path) as conn:
        attempt_id = conn.execute(
            "INSERT INTO quiz_attempts (user_id, score, total) VALUES (?, ?, ?)",
            (user_id, score, total),
        ).lastrowid
        conn.executemany(
            "INSERT INTO quiz_answers (attempt_id, topic_id, question, chosen, correct, is_correct)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [(attempt_id, t, q, ch, co, int(ok)) for t, q, ch, co, ok in answers],
        )
        _refresh_topic_scores(conn, user_id)
        return attempt_id


def list_quiz_attempts(user_id: int, db_path=None) -> list[sqlite3.Row]:
    with connect(db_path) as conn:
        return conn.execute(
            "SELECT * FROM quiz_attempts WHERE user_id = ? ORDER BY created_at DESC, id DESC",
            (user_id,),
        ).fetchall()


def list_quiz_answers(attempt_id: int, db_path=None) -> list[sqlite3.Row]:
    with connect(db_path) as conn:
        return conn.execute(
            "SELECT a.*, t.name AS topic FROM quiz_answers a"
            " LEFT JOIN topics t ON t.id = a.topic_id WHERE a.attempt_id = ? ORDER BY a.id",
            (attempt_id,),
        ).fetchall()


# --- Topic scores ---

# A topic's accuracy is over this many most recent answers, so improvement shows.
RECENT_ANSWERS = 10

_REFRESH_SCORES = """
INSERT INTO topic_scores (user_id, topic_id, attempts, correct, accuracy, last_seen)
SELECT q.user_id, a.topic_id, COUNT(*), SUM(a.is_correct),
       (SELECT AVG(r.is_correct) FROM (
            SELECT a2.is_correct FROM quiz_answers a2
            JOIN quiz_attempts q2 ON q2.id = a2.attempt_id
            WHERE a2.topic_id = a.topic_id AND q2.user_id = q.user_id
            ORDER BY a2.id DESC LIMIT {recent}) r),
       MAX(q.created_at)
FROM quiz_answers a JOIN quiz_attempts q ON q.id = a.attempt_id
WHERE q.user_id = ? AND a.topic_id IS NOT NULL
GROUP BY a.topic_id
""".format(recent=RECENT_ANSWERS)


def _refresh_topic_scores(conn: sqlite3.Connection, user_id: int) -> None:
    """Rebuild a user's topic_scores from their saved answers."""
    conn.execute("DELETE FROM topic_scores WHERE user_id = ?", (user_id,))
    conn.execute(_REFRESH_SCORES, (user_id,))


def topic_scores(user_id: int, db_path=None) -> list[sqlite3.Row]:
    """Every topic the user can see, with its document, subject and the user's own score
    (NULLs if never tested)."""
    with connect(db_path) as conn:
        return conn.execute(
            "SELECT t.id, t.name, t.document_id, d.filename, d.unit,"
            "       COALESCE(sj.name, d.subject) AS subject,"
            "       s.attempts, s.correct, s.accuracy, s.last_seen"
            " FROM topics t"
            " LEFT JOIN documents d ON d.id = t.document_id"
            " LEFT JOIN subjects sj ON sj.id = d.subject_id"
            " LEFT JOIN topic_scores s ON s.topic_id = t.id AND s.user_id = :uid"
            f" WHERE (t.user_id = :uid OR {_VISIBLE}) ORDER BY t.document_id, t.id",
            {"uid": user_id},
        ).fetchall()


def update_document(
    document_id: int, subject: str | None, page_count: int, db_path=None, *,
    subject_id: int | None = None, unit: str | None = None,
) -> None:
    """Refresh a re-uploaded document in place, keeping its id (and so its topics and
    their quiz history)."""
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE documents SET subject = COALESCE(?, subject), page_count = ?,"
            " subject_id = COALESCE(?, subject_id), unit = COALESCE(?, unit),"
            " uploaded_at = datetime('now') WHERE id = ?",
            (subject, page_count, subject_id, unit, document_id),
        )


# --- Study plans ---

def save_study_plan(
    user_id: int, exam_date: str, hours_per_day: float, plan_json: str, db_path=None
) -> int:
    with connect(db_path) as conn:
        return conn.execute(
            "INSERT INTO study_plans (user_id, exam_date, hours_per_day, plan_json)"
            " VALUES (?, ?, ?, ?)",
            (user_id, exam_date, hours_per_day, plan_json),
        ).lastrowid


def latest_study_plan(user_id: int, db_path=None) -> sqlite3.Row | None:
    with connect(db_path) as conn:
        return conn.execute(
            "SELECT * FROM study_plans WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,)
        ).fetchone()


def update_study_plan(plan_id: int, plan_json: str, db_path=None) -> None:
    with connect(db_path) as conn:
        conn.execute("UPDATE study_plans SET plan_json = ? WHERE id = ?", (plan_json, plan_id))


# --- Exam timetable ---

def set_exams(user_id: int, exams: list[tuple[str, str, str | None]], db_path=None) -> None:
    """Replace the user's timetable with (subject, ISO date, start time or None) rows."""
    with connect(db_path) as conn:
        conn.execute("DELETE FROM exams WHERE user_id = ?", (user_id,))
        conn.executemany(
            "INSERT INTO exams (user_id, subject, exam_date, start_time) VALUES (?, ?, ?, ?)",
            [(user_id, subject, day, time) for subject, day, time in exams],
        )


def list_exams(user_id: int, db_path=None) -> list[sqlite3.Row]:
    with connect(db_path) as conn:
        return conn.execute(
            "SELECT * FROM exams WHERE user_id = ? ORDER BY exam_date, start_time", (user_id,)
        ).fetchall()
