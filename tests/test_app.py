from streamlit.testing.v1 import AppTest

from core import config


def test_login_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "app.db")
    at = AppTest.from_file("../app.py").run()
    assert not at.exception
    assert at.title[0].value == "🎓 PersonaAI"

    at.text_input[0].input("Vivek")
    at.button[0].click().run()
    assert not at.exception
    assert at.session_state.username == "Vivek"
    assert "Welcome, Vivek" in at.title[0].value


def test_empty_username_shows_error(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "app.db")
    at = AppTest.from_file("../app.py").run()
    at.button[0].click().run()
    assert at.error[0].value == "Please enter a username."
    assert "user_id" not in at.session_state


def test_notes_page_requires_login(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "app.db")
    at = AppTest.from_file("../pages/1_Notes_QA.py").run()
    assert not at.exception
    assert "sign in" in at.warning[0].value


def test_notes_page_empty_state(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "app.db")
    from core import rag
    monkeypatch.setattr(rag, "warm_up", lambda: None)  # skip loading ML models
    from core import db
    db.init_db()
    user = db.get_or_create_user("Vivek")
    at = AppTest.from_file("../pages/1_Notes_QA.py")
    at.session_state.user_id = user["id"]
    at.session_state.username = "Vivek"
    at.run()
    assert not at.exception
    assert at.title[0].value == "📚 Notes Q&A"
    assert any("Upload your notes" in i.value for i in at.info)


def test_quiz_page_full_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "app.db")
    from core import db, quiz, rag
    monkeypatch.setattr(rag, "warm_up", lambda: None)
    db.init_db()
    user = db.get_or_create_user("Vivek")
    doc = db.add_document(user["id"], "unit4.pdf", None, 20)
    db.set_topics(user["id"], doc, ["Hive tables"])
    tid = db.list_topics(user["id"])[0]["id"]
    fake = [quiz.Question(tid, "Hive tables", f"Question {i}?", ["a", "b", "c", "d"], 1, "because", "unit4.pdf, p. 3")
            for i in range(5)]
    monkeypatch.setattr(quiz, "generate", lambda uid, alloc: fake)

    at = AppTest.from_file("../pages/2_Quiz.py")
    at.session_state.user_id = user["id"]
    at.session_state.username = "Vivek"
    at.run()
    assert not at.exception
    at.radio[0].set_value(5)
    next(b for b in at.button if b.label == "Generate quiz").click().run()
    assert not at.exception
    assert at.subheader[0].value == "5 questions"

    # Submitting with blanks is refused
    at.button[0].click().run()
    assert "Answer every question first" in at.warning[0].value

    for i in range(5):
        at.radio(key=f"q_{i}").set_value(1 if i < 4 else 2)
    at.button[0].click().run()
    assert not at.exception
    assert at.metric[0].value == "4 / 5"
    [attempt] = db.list_quiz_attempts(user["id"])
    assert (attempt["score"], attempt["total"]) == (4, 5)


def _user_with_history(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "app.db")
    from core import db, rag
    monkeypatch.setattr(rag, "warm_up", lambda: None)
    db.init_db()
    uid = db.get_or_create_user("Vivek")["id"]
    doc = db.add_document(uid, "unit4.pdf", None, 20)
    db.set_topics(uid, doc, ["Hive tables", "Sqoop export", "Pig macros"])
    ids = {t["name"]: t["id"] for t in db.list_topics(uid)}
    db.save_quiz_attempt(uid, 1, 4, [(ids["Hive tables"], f"q{i}", "x", "y", i == 0) for i in range(4)])
    db.save_quiz_attempt(uid, 3, 3, [(ids["Sqoop export"], f"s{i}", "y", "y", True) for i in range(3)])
    return uid, ids


def test_progress_page_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "app.db")
    from core import db
    db.init_db()
    at = AppTest.from_file("../pages/3_Progress.py")
    at.session_state.user_id = db.get_or_create_user("Vivek")["id"]
    at.session_state.username = "Vivek"
    at.run()
    assert not at.exception
    assert "No quizzes yet" in at.info[0].value


def test_progress_page_with_history(tmp_path, monkeypatch):
    uid, _ = _user_with_history(tmp_path, monkeypatch)
    at = AppTest.from_file("../pages/3_Progress.py")
    at.session_state.user_id = uid
    at.session_state.username = "Vivek"
    at.run()
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics == {"Quizzes taken": "2", "Overall accuracy": "57%",
                       "Weak topics": "1", "Topics tested": "2 / 3"}
    text = " ".join(m.value for m in at.markdown)
    assert "**Hive tables** — 25%" in text and "**Sqoop export** — 100%" in text


def test_quiz_page_adaptive_targets_weak_topics(tmp_path, monkeypatch):
    uid, ids = _user_with_history(tmp_path, monkeypatch)
    from core import quiz
    seen = {}

    def fake_generate(user_id, allocation):
        seen.update(allocation)
        return [quiz.Question(ids["Hive tables"], "Hive tables", "Q?", ["a", "b", "c", "d"], 0, "", None)]

    monkeypatch.setattr(quiz, "generate", fake_generate)
    at = AppTest.from_file("../pages/2_Quiz.py")
    at.session_state.user_id = uid
    at.session_state.username = "Vivek"
    at.run()
    assert "**Hive tables** (25%)" in at.info[0].value
    next(b for b in at.button if b.label == "Generate quiz").click().run()
    assert not at.exception
    # 10 questions: 6 on the weak topic, the rest untested first
    assert seen[ids["Hive tables"]] == 6 and seen[ids["Pig macros"]] >= 2


def test_study_plan_page_create_and_regenerate(tmp_path, monkeypatch):
    uid, ids = _user_with_history(tmp_path, monkeypatch)
    from core import planner
    at = AppTest.from_file("../pages/4_Study_Plan.py")
    at.session_state.user_id = uid
    at.session_state.username = "Vivek"
    at.run()
    assert not at.exception
    at.number_input[0].set_value(2.0)
    at.button[0].click().run()  # "Create plan" (form submit)
    assert not at.exception
    plan_id, plan = planner.latest(uid)
    assert len(plan.days) == 14 and set(plan.topic_hours) == set(ids.values())
    # Weak "Hive tables" (25%) gets the most time
    assert max(plan.topic_hours, key=plan.topic_hours.get) == ids["Hive tables"]
    assert [h.value for h in at.subheader] == ["Today", "Day by day"]
    # (The "Done" checkboxes live in st.data_editor, which AppTest can't drive;
    # saving them is covered by test_planner.test_marking_days_done_is_saved.)

    next(b for b in at.button if b.label.startswith("🔄 Regenerate")).click().run()
    assert not at.exception
    assert "Plan regenerated" in at.success[0].value  # no new quizzes -> unchanged
