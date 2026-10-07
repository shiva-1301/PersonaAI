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
