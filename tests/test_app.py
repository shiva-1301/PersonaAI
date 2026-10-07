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
