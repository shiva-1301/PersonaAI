import pytest

from core import db


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    db.init_db(path)
    return path


def test_init_creates_all_tables(db_path):
    with db.connect(db_path) as conn:
        names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "users", "documents", "topics", "quiz_attempts",
        "quiz_answers", "topic_scores", "study_plans",
    } <= names


def test_get_or_create_user_is_idempotent_and_case_insensitive(db_path):
    first = db.get_or_create_user("Vivek", db_path)
    again = db.get_or_create_user("  vivek ", db_path)
    assert first["id"] == again["id"]
    assert first["username"] == "Vivek"


def test_empty_username_rejected(db_path):
    with pytest.raises(ValueError):
        db.get_or_create_user("   ", db_path)


def test_set_topics_keeps_ids_of_unchanged_topics(db_path):
    uid = db.get_or_create_user("u", db_path)["id"]
    doc = db.add_document(uid, "a.pdf", None, 3, db_path)
    db.set_topics(uid, doc, ["Hive", "Pig", "pig", ""], db_path)
    before = {t["name"]: t["id"] for t in db.list_topics(uid, doc, db_path)}
    assert set(before) == {"Hive", "Pig"}

    db.set_topics(uid, doc, ["Pig", "Sqoop"], db_path)
    after = {t["name"]: t["id"] for t in db.list_topics(uid, doc, db_path)}
    assert set(after) == {"Pig", "Sqoop"}
    assert after["Pig"] == before["Pig"]


def test_deleting_document_deletes_its_topics(db_path):
    uid = db.get_or_create_user("u", db_path)["id"]
    doc = db.add_document(uid, "a.pdf", None, 3, db_path)
    db.set_topics(uid, doc, ["Hive"], db_path)
    db.delete_document(doc, db_path)
    assert db.list_topics(uid, db_path=db_path) == []
