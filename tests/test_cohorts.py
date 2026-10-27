import sqlite3

import pytest

from core import auth, config, db, memory


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "app.db")
    db.init_db()


def _class(cse3=("22B81A0501", "22B81A0502"), ece3=("22B81A0401",)):
    rows = [{"hall_ticket": t, "name": f"Student {t[-2:]}", "department": "cse", "year": "3"} for t in cse3]
    rows += [{"hall_ticket": t, "name": "ECE student", "department": "ECE", "year": "3"} for t in ece3]
    return db.import_students(rows)


def test_class_list_creates_cohorts_and_is_idempotent(env):
    assert _class() == (3, 0)
    assert _class() == (0, 3)  # re-import updates, never duplicates
    cohorts = {(c["department"], c["year"]): c["students"] for c in db.list_cohorts()}
    assert cohorts == {("CSE", "3"): 2, ("ECE", "3"): 1}
    with pytest.raises(ValueError):
        db.import_students([{"hall_ticket": "admin", "name": "x", "department": "CSE", "year": "3"}])


def test_shared_notes_are_visible_only_to_their_cohort(env):
    _class()
    admin = db.get_or_create_user("admin")["id"]
    cse = db.get_or_create_cohort("CSE", "3")
    dbms = db.add_subject(cse, "DBMS")
    shared = db.add_document(admin, "dbms_unit1.pdf", None, 10, cohort_id=cse, subject_id=dbms, unit="Unit 1")
    db.set_topics(admin, shared, ["Normalization", "ER model"])

    a, b = db.find_user("22b81a0501")["id"], db.find_user("22B81A0502")["id"]
    ece = db.find_user("22B81A0401")["id"]
    personal = db.add_document(a, "my_notes.pdf", "DBMS", 2)
    db.set_topics(a, personal, ["Joins"])

    docs_a = {d["filename"]: (d["shared"], d["subject_name"]) for d in db.list_documents(a)}
    assert docs_a == {"dbms_unit1.pdf": (1, "DBMS"), "my_notes.pdf": (0, "DBMS")}
    assert [d["filename"] for d in db.list_documents(b)] == ["dbms_unit1.pdf"]  # not A's personal notes
    assert db.list_documents(ece) == []  # other cohort sees nothing
    assert {t["name"] for t in db.list_topics(b)} == {"Normalization", "ER model"}
    assert {s.subject for s in memory.topic_stats(a)} == {"DBMS"}


def test_scores_on_shared_topics_are_per_student(env):
    _class()
    admin = db.get_or_create_user("admin")["id"]
    cse = db.get_or_create_cohort("CSE", "3")
    doc = db.add_document(admin, "u1.pdf", None, 1, cohort_id=cse)
    db.set_topics(admin, doc, ["Hashing"])
    tid = db.list_topics(admin)[0]["id"]
    a, b = db.find_user("22B81A0501")["id"], db.find_user("22B81A0502")["id"]
    db.save_quiz_attempt(a, 0, 3, [(tid, f"q{i}", "x", "y", False) for i in range(3)])

    [stat_a] = memory.topic_stats(a)
    [stat_b] = memory.topic_stats(b)
    assert stat_a.status == "weak" and stat_b.status == "new"


def test_student_cannot_delete_shared_notes(env, monkeypatch):
    from core import ingest, vectorstore
    monkeypatch.setattr(vectorstore, "delete_document", lambda doc_id: None)
    _class()
    admin = db.get_or_create_user("admin")["id"]
    cse = db.get_or_create_cohort("CSE", "3")
    doc = db.add_document(admin, "u1.pdf", None, 1, cohort_id=cse)
    ingest.remove(db.find_user("22B81A0501")["id"], doc)
    assert db.get_document(doc) is not None
    ingest.remove(admin, doc)
    assert db.get_document(doc) is None


def test_old_database_gets_new_columns(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE"
        " COLLATE NOCASE, created_at TEXT NOT NULL DEFAULT (datetime('now')));"
        "CREATE TABLE documents (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,"
        " filename TEXT NOT NULL, subject TEXT, page_count INTEGER NOT NULL DEFAULT 0,"
        " uploaded_at TEXT NOT NULL DEFAULT (datetime('now')));"
        "INSERT INTO users (username) VALUES ('vivek');"
        "INSERT INTO documents (user_id, filename) VALUES (1, 'old.pdf');"
    )
    conn.commit()
    conn.close()
    db.init_db(path)
    db.init_db(path)  # running twice is harmless
    [doc] = db.list_documents(1, path)
    assert doc["filename"] == "old.pdf" and doc["shared"] == 0
    assert db.find_user("vivek", path)["password_hash"] is None


def test_password_hashing():
    stored = auth.hash_password("secret123")
    assert "secret123" not in stored
    assert auth.verify_password("secret123", stored)
    assert not auth.verify_password("secret124", stored)
    assert not auth.verify_password("x", "garbage")


def _code_for(ticket):
    return auth.issue_setup_code(db.find_user(ticket)["id"])


def test_first_sign_in_sets_password_then_requires_it(env):
    _class()
    with pytest.raises(auth.PasswordNotSet):
        auth.sign_in("22b81a0501", "")
    code = _code_for("22B81A0501")
    assert len(code) == 9 and code[4] == "-"
    with pytest.raises(auth.AuthError, match="don't match"):
        auth.set_first_password("22B81A0501", code, "secret123", "secret12")
    with pytest.raises(auth.AuthError, match="at least"):
        auth.set_first_password("22B81A0501", code, "abc", "abc")
    # Codes are forgiving about case, spaces and the dash.
    account = auth.set_first_password("22B81A0501", f" {code.lower().replace('-', ' ')} ", "secret123", "secret123")
    assert account.role == "student" and account.cohort_id == db.get_or_create_cohort("CSE", "3")
    assert db.find_user("22B81A0501")["setup_code_hash"] is None  # the code is used up

    assert auth.sign_in("22b81a0501", "secret123").username == "22B81A0501"
    with pytest.raises(auth.AuthError, match="Wrong"):
        auth.sign_in("22B81A0501", "wrong-password")
    with pytest.raises(auth.AuthError, match="already has a password"):
        auth.set_first_password("22B81A0501", code, "another1", "another1")
    with pytest.raises(auth.AuthError, match="isn't registered"):
        auth.sign_in("99X99", "secret123")


def test_password_cannot_be_set_without_the_admins_code(env):
    _class()
    with pytest.raises(auth.AuthError, match="don't have a sign-up code"):
        auth.set_first_password("22B81A0501", "", "secret123", "secret123")
    _code_for("22B81A0501")
    with pytest.raises(auth.AuthError, match="sign-up code isn't right"):
        auth.set_first_password("22B81A0501", "AAAA-BBBB", "secret123", "secret123")
    assert db.find_user("22B81A0501")["password_hash"] is None
    # A new code replaces the old one; another student's code doesn't work.
    old = _code_for("22B81A0501")
    new = _code_for("22B81A0501")
    other = _code_for("22B81A0502")
    for wrong in (old, other):
        if wrong != new:
            with pytest.raises(auth.AuthError, match="isn't right"):
                auth.set_first_password("22B81A0501", wrong, "secret123", "secret123")
    assert auth.set_first_password("22B81A0501", new, "secret123", "secret123").username == "22B81A0501"


def test_admin_codes_for_cohort_and_password_reset(env):
    _class()
    cse = db.get_or_create_cohort("CSE", "3")
    codes = auth.issue_codes_for_cohort(cse)
    assert [(t, n) for t, n, _ in codes] == [("22B81A0501", "Student 01"), ("22B81A0502", "Student 02")]
    auth.set_first_password("22B81A0501", codes[0][2], "secret123", "secret123")
    assert [t for t, _, _ in auth.issue_codes_for_cohort(cse)] == ["22B81A0502"]  # signed-up students skipped

    uid = db.find_user("22B81A0501")["id"]
    code = auth.reset_password(uid)
    with pytest.raises(auth.PasswordNotSet):
        auth.sign_in("22B81A0501", "secret123")
    auth.set_first_password("22B81A0501", code, "newpass1", "newpass1")
    assert auth.sign_in("22B81A0501", "newpass1").user_id == uid


@pytest.fixture
def clock(monkeypatch):
    now = [1_000_000.0]
    monkeypatch.setattr(auth, "_now", lambda: now[0])
    return now


def test_five_failed_logins_lock_the_account_for_five_minutes(env, clock):
    _class()
    auth.set_first_password("22B81A0501", _code_for("22B81A0501"), "secret123", "secret123")
    for _ in range(auth.MAX_FAILED_LOGINS):
        with pytest.raises(auth.AuthError, match="Wrong"):
            auth.sign_in("22B81A0501", "guess")
    # Locked: even the right password is refused, with the time left.
    with pytest.raises(auth.LockedOut, match="Try again in 5 minutes"):
        auth.sign_in("22b81a0501", "secret123")
    clock[0] += auth.LOCKOUT_SECONDS - 61
    with pytest.raises(auth.LockedOut, match="Try again in 2 minutes"):
        auth.sign_in("22B81A0501", "secret123")
    clock[0] += 62
    assert auth.sign_in("22B81A0501", "secret123").username == "22B81A0501"
    assert db.login_failures("22B81A0501") is None  # success clears the count


def test_failures_must_be_in_a_row_and_other_accounts_are_unaffected(env, clock):
    _class()
    for ticket in ("22B81A0501", "22B81A0502"):
        auth.set_first_password(ticket, _code_for(ticket), "secret123", "secret123")
    for _ in range(auth.MAX_FAILED_LOGINS - 1):
        with pytest.raises(auth.AuthError):
            auth.sign_in("22B81A0501", "guess")
    auth.sign_in("22B81A0501", "secret123")  # resets the count
    for _ in range(auth.MAX_FAILED_LOGINS - 1):
        with pytest.raises(auth.AuthError):
            auth.sign_in("22B81A0501", "guess")
    assert auth.sign_in("22B81A0501", "secret123")  # still not locked
    for _ in range(auth.MAX_FAILED_LOGINS):
        with pytest.raises(auth.AuthError):
            auth.sign_in("22B81A0501", "guess")
    assert auth.sign_in("22B81A0502", "secret123")  # a classmate can still sign in


def test_wrong_sign_up_codes_and_unknown_names_count_towards_lockout(env, clock, monkeypatch):
    _class()
    _code_for("22B81A0501")
    for _ in range(auth.MAX_FAILED_LOGINS):
        with pytest.raises(auth.AuthError, match="isn't right"):
            auth.set_first_password("22B81A0501", "AAAA-AAAA", "secret123", "secret123")
    with pytest.raises(auth.LockedOut):
        auth.set_first_password("22B81A0501", "AAAA-AAAA", "secret123", "secret123")
    for _ in range(auth.MAX_FAILED_LOGINS):
        with pytest.raises(auth.AuthError, match="isn't registered"):
            auth.sign_in("NOBODY", "x")
    with pytest.raises(auth.LockedOut):
        auth.sign_in("nobody", "x")
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "admin-pass")
    for _ in range(auth.MAX_FAILED_LOGINS):
        with pytest.raises(auth.AuthError, match="Wrong"):
            auth.sign_in("admin", "guess")
    with pytest.raises(auth.LockedOut):
        auth.sign_in("admin", "admin-pass")


def test_admin_reset_also_clears_a_lockout(env, clock):
    _class()
    auth.set_first_password("22B81A0501", _code_for("22B81A0501"), "secret123", "secret123")
    for _ in range(auth.MAX_FAILED_LOGINS):
        with pytest.raises(auth.AuthError):
            auth.sign_in("22B81A0501", "guess")
    code = auth.reset_password(db.find_user("22B81A0501")["id"])
    assert auth.set_first_password("22B81A0501", code, "newpass1", "newpass1")


def test_admin_sign_in(env, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "")
    with pytest.raises(auth.AuthError, match="ADMIN_PASSWORD"):
        auth.sign_in("admin", "anything")
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "admin-pass")
    with pytest.raises(auth.AuthError, match="Wrong"):
        auth.sign_in("Admin", "nope")
    assert auth.sign_in("Admin", "admin-pass").role == "admin"
