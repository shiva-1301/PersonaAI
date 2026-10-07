"""Real embeddings + ChromaDB in a temp dir; the LLM is stubbed."""

import pytest

from core import config, db, ingest, llm, rag, vectorstore

NOTES = (
    "Apache Hive is a data warehouse framework built on Hadoop. It uses HiveQL.\n\n"
    "Managed tables are owned by Hive: dropping one deletes its data. "
    "External tables only store metadata; dropping one keeps the data in HDFS."
)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "CHROMA_DIR", tmp_path / "chroma")
    monkeypatch.setattr(config, "UPLOADS_DIR", tmp_path / "uploads")
    db.init_db()
    return db.get_or_create_user("tester")["id"]


def fake_llm(monkeypatch, reply):
    monkeypatch.setattr(llm, "generate", lambda *a, **k: reply)
    monkeypatch.setattr(llm, "generate_with_model", lambda *a, **k: (reply, "fake / model"))


def test_ingest_search_answer_and_remove(env, monkeypatch):
    fake_llm(monkeypatch, '{"topics": ["Hive basics", "Managed vs external tables"]}')
    result = ingest.ingest(env, "hive.txt", NOTES.encode())
    assert result.chunks == 1 and result.warning is None
    assert [t["name"] for t in db.list_topics(env)] == ["Hive basics", "Managed vs external tables"]

    hits = rag.retrieve(env, "what happens when you drop an external table?")
    assert hits and hits[0].filename == "hive.txt" and hits[0].score >= rag.MIN_SCORE

    fake_llm(monkeypatch, "Dropping an external table keeps the data [S1].")
    answer = rag.answer(env, "what happens when you drop an external table?")
    assert answer.found and answer.sources[0].filename == "hive.txt"
    assert answer.model == "fake / model"

    ingest.remove(env, result.document_id)
    assert db.list_documents(env) == []
    assert vectorstore.search(env, "hive") == []


def test_unrelated_question_skips_llm(env, monkeypatch):
    fake_llm(monkeypatch, '{"topics": ["Hive"]}')
    ingest.ingest(env, "hive.txt", NOTES.encode())

    def boom(*a, **k):
        raise AssertionError("LLM should not be called")

    monkeypatch.setattr(llm, "generate", boom)
    monkeypatch.setattr(llm, "generate_with_model", boom)
    assert not rag.answer(env, "How do I bake a chocolate cake?").found


def test_reupload_replaces_and_users_are_isolated(env, monkeypatch):
    fake_llm(monkeypatch, '{"topics": ["Hive"]}')
    ingest.ingest(env, "hive.txt", NOTES.encode())
    ingest.ingest(env, "hive.txt", NOTES.encode())
    assert len(db.list_documents(env)) == 1
    assert len(vectorstore.search(env, "hive tables", k=10)) == 1

    other = db.get_or_create_user("someone-else")["id"]
    assert vectorstore.search(other, "hive tables") == []


def test_topic_failure_does_not_fail_upload(env, monkeypatch):
    def down(*a, **k):
        raise llm.LLMError("offline")

    monkeypatch.setattr(llm, "generate", down)
    result = ingest.ingest(env, "hive.txt", NOTES.encode())
    assert result.warning and result.topics == []
    assert len(db.list_documents(env)) == 1
