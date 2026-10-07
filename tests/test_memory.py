import pytest

from core import config, db, ingest, llm, memory
from core.memory import TopicStat, adaptive_allocation, classify


@pytest.mark.parametrize("acc,n,status", [
    (None, 0, "new"), (0.0, 2, "learning"),          # too few answers to judge
    (0.5, 3, "weak"), (0.59, 10, "weak"),
    (0.6, 3, "learning"), (0.79, 5, "learning"),
    (0.8, 3, "strong"), (1.0, 4, "strong"),
])
def test_classify(acc, n, status):
    assert classify(acc, n) == status


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "CHROMA_DIR", tmp_path / "chroma")
    monkeypatch.setattr(config, "UPLOADS_DIR", tmp_path / "uploads")
    db.init_db()
    uid = db.get_or_create_user("u")["id"]
    doc = db.add_document(uid, "unit4.pdf", None, 20)
    db.set_topics(uid, doc, ["Hive tables", "Sqoop export", "Pig macros"])
    return uid, {t["name"]: t["id"] for t in db.list_topics(uid)}


def answer(uid, tid, results):
    """Save one quiz with the given correct/incorrect results, all on one topic."""
    db.save_quiz_attempt(uid, sum(results), len(results),
                         [(tid, f"q{i}", "x", "y", ok) for i, ok in enumerate(results)])


def by_name(uid):
    return {s.name: s for s in memory.topic_stats(uid)}


def test_scores_update_after_each_quiz(env):
    uid, ids = env
    answer(uid, ids["Hive tables"], [True, False, False])
    stats = by_name(uid)
    hive = stats["Hive tables"]
    assert (hive.answers, hive.correct, round(hive.accuracy, 2), hive.status) == (3, 1, 0.33, "weak")
    assert stats["Sqoop export"].status == "new"
    assert [s.name for s in memory.weak_topics(uid)] == ["Hive tables"]


def test_accuracy_uses_recent_answers_so_improvement_counts(env):
    uid, ids = env
    answer(uid, ids["Hive tables"], [False] * 10)
    assert by_name(uid)["Hive tables"].status == "weak"
    answer(uid, ids["Hive tables"], [True] * 9)
    hive = by_name(uid)["Hive tables"]
    # all-time 9/19 = 47% would still be weak; the last 10 answers are 9/10 = 90%
    assert (hive.answers, hive.correct) == (19, 9)
    assert hive.accuracy == pytest.approx(0.9) and hive.status == "strong"


def test_backfill_for_quizzes_saved_before_scores_existed(env):
    uid, ids = env
    answer(uid, ids["Pig macros"], [False, False, False])
    with db.connect() as conn:
        conn.execute("DELETE FROM topic_scores")
    db.init_db()
    assert by_name(uid)["Pig macros"].status == "weak"


def stat(tid, status_acc, answers=5, last_seen=None):
    return TopicStat(tid, f"t{tid}", 1, "f.pdf", answers if status_acc is not None else 0,
                     0, status_acc, last_seen)


def test_adaptive_puts_60_percent_on_weak_topics_weakest_first():
    stats = [stat(1, 0.2), stat(2, 0.5), stat(3, 0.9), stat(4, None), stat(5, 0.7)]
    alloc = adaptive_allocation(stats, 10)
    assert sum(alloc.values()) == 10
    assert alloc[1] + alloc[2] == 6
    assert alloc[1] >= alloc[2]
    # the other 4: untested first, then learning, then strong
    assert alloc[4] >= 1 and alloc[5] >= 1 and alloc[3] >= 1


def test_adaptive_without_weak_topics_prefers_untested():
    stats = [stat(1, 0.9), stat(2, None), stat(3, None), stat(4, 0.7)]
    alloc = adaptive_allocation(stats, 2)
    assert alloc == {2: 1, 3: 1}


def test_adaptive_with_only_weak_topics_uses_them_all():
    alloc = adaptive_allocation([stat(1, 0.1), stat(2, 0.3)], 5)
    assert sum(alloc.values()) == 5 and set(alloc) == {1, 2}


def test_reupload_keeps_topics_and_their_history(env, monkeypatch):
    uid, _ = env
    monkeypatch.setattr(llm, "generate", lambda *a, **k: '{"topics": ["Hive tables", "Hive views"]}')
    first = ingest.ingest(uid, "notes.txt", b"Hive managed tables own their data.")
    tid = db.list_topics(uid, first.document_id)[0]["id"]
    answer(uid, tid, [False, False, False])

    monkeypatch.setattr(llm, "generate", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no re-extract")))
    again = ingest.ingest(uid, "notes.txt", b"Hive managed tables own their data. Updated.")
    assert again.document_id == first.document_id
    assert again.topics == ["Hive tables", "Hive views"]
    assert by_name(uid)["Hive tables"].status == "weak"  # history survived


def test_question_topic_matches_closest_topic(env):
    uid, ids = env
    answer(uid, ids["Sqoop export"], [False, False, False])
    assert memory.question_topic(uid, "How does Sqoop export data to MySQL?").name == "Sqoop export"
    assert memory.related_weak_topic(uid, "How does Sqoop export data to MySQL?").name == "Sqoop export"
    assert memory.related_weak_topic(uid, "What is a Pig macro?") is None  # topic not weak
    assert memory.question_topic(uid, "Who won the 2018 FIFA World Cup?") is None
