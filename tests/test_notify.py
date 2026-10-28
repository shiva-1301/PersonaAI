"""Email updates, with a fake SMTP server (nothing is sent)."""

import importlib.util
import json
import smtplib
from datetime import date, timedelta
from pathlib import Path

import pytest

from core import config, db, notify, planner
from core.memory import TopicStat
from core.planner import Exam, build_exam_plan

TODAY = date(2026, 11, 2)


class FakeSMTP:
    sent: list = []
    fail_login = False

    def __init__(self, host, port, timeout=None, context=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        if self.fail_login:
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


@pytest.fixture
def smtp(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "SMTP_USER", "sender@example.com")
    monkeypatch.setattr(config, "SMTP_PASSWORD", "secret-app-password")
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    FakeSMTP.sent, FakeSMTP.fail_login = [], False
    db.init_db()
    return FakeSMTP


def plan():
    stats = [TopicStat(i, f"Topic {i}", i, "f.pdf", 0, 0, None, None, "DBMS") for i in range(1, 4)]
    return build_exam_plan(stats, [Exam("DBMS", TODAY + timedelta(days=3), "10:00")], 2, today=TODAY)


def test_send_and_quiz_email(smtp):
    notify.send("student@example.com", *notify.quiz_email("Asha", 7, 10, ["Joins", "Indexes"]))
    msg = smtp.sent[0]
    assert msg["To"] == "student@example.com" and msg["Subject"] == "Quiz result: 7/10 (70%)"
    assert "- Joins" in msg.get_content() and "turn them off" in msg.get_content()


def test_login_failure_never_shows_the_password(smtp):
    smtp.fail_login = True
    with pytest.raises(notify.EmailError) as err:
        notify.send("student@example.com", "s", "b")
    assert "secret-app-password" not in str(err.value) and "app password" in str(err.value)


def test_reminder_lists_today_and_next_exam():
    subject, body = notify.reminder_email("Asha", plan(), TODAY)
    assert subject.startswith("Today's study plan:") and "DBMS · Study: Topic 1" in body
    assert "Next exam: DBMS in 3 days." in body
    assert notify.reminder_email("Asha", plan(), TODAY + timedelta(days=30)) is None
    assert notify.reminder_email("Asha", plan(), TODAY + timedelta(days=3))[0] == "Exam today"


def test_address_check():
    assert notify.valid_address("23eg106c21@anurag.edu.in")
    assert not notify.valid_address("not an email") and not notify.valid_address("a@b")


def test_reminder_script_emails_only_students_who_asked(smtp):
    wants = db.get_or_create_user("wants")["id"]
    silent = db.get_or_create_user("silent")["id"]
    db.set_email_settings(wants, "wants@example.com", scores=False, reminders=True)
    db.set_email_settings(silent, "silent@example.com", scores=True, reminders=False)
    for uid in (wants, silent):
        db.save_study_plan(uid, plan().exam_date, 2, json.dumps(plan().to_dict()))
    spec = importlib.util.spec_from_file_location(
        "send_reminders", Path(__file__).resolve().parent.parent / "scripts" / "send_reminders.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    assert script.main(TODAY) == (1, 0)
    assert [m["To"] for m in smtp.sent] == ["wants@example.com"]
