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
