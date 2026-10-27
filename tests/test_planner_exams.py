"""Exam-timetable plans: several subjects, each with its own exam date."""

from datetime import date, timedelta

import pytest

from core import config, db, planner
from core.memory import TopicStat
from core.planner import Exam, PlanError, build_exam_plan

TODAY = date(2026, 11, 2)


def stat(tid, subject, acc=None, answers=5):
    return TopicStat(tid, f"{subject} topic {tid}", tid, "f.pdf",
                     answers if acc is not None else 0, 0, acc, None, subject)


DBMS = [stat(1, "DBMS", 0.2), stat(2, "DBMS", 0.3), stat(3, "DBMS", 0.4)]  # weak
OS = [stat(4, "OS", 0.9), stat(5, "OS", 0.95), stat(6, "OS", 0.9)]  # strong
EXAMS = [Exam("OS", TODAY + timedelta(days=10), "14:00"), Exam("DBMS", TODAY + timedelta(days=6), "10:00")]


def plan(stats=DBMS + OS, exams=EXAMS, hours=4):
    return build_exam_plan(stats, exams, hours, today=TODAY)


def tasks_of(p, subject):
    return [(d.date, t) for d in p.days for t in d.tasks if t.subject == subject]


def test_exam_days_are_marked_and_plan_ends_on_the_last_exam():
    p = plan()
    assert p.days[0].date == TODAY.isoformat() and p.exam_date == p.days[-1].date
    exams = {d.date: t.title for d in p.days for t in d.tasks if t.kind == "exam"}
    assert exams == {(TODAY + timedelta(days=6)).isoformat(): "Exam: DBMS at 10:00",
                     (TODAY + timedelta(days=10)).isoformat(): "Exam: OS at 14:00"}
    assert [e["subject"] for e in p.exams] == ["DBMS", "OS"]  # sorted by date


def test_nothing_of_a_subject_after_its_exam_and_revision_the_day_before():
    p = plan()
    dbms_exam = (TODAY + timedelta(days=6)).isoformat()
    assert all(day <= dbms_exam for day, _ in tasks_of(p, "DBMS"))
    before = {d.date: d for d in p.days}[(TODAY + timedelta(days=5)).isoformat()]
    assert {t.subject for t in before.tasks} == {"DBMS"} and before.tasks[0].kind == "revision"


def test_every_topic_is_studied_before_its_exam():
    p = plan()
    for subject, stats, exam in (("DBMS", DBMS, EXAMS[1]), ("OS", OS, EXAMS[0])):
        studied = {t.topic_id for day, t in tasks_of(p, subject) if t.kind == "study"}
        assert studied == {s.topic_id for s in stats}
        assert all(day < exam.date.isoformat() for day, t in tasks_of(p, subject) if t.kind == "study")


def test_nearer_weaker_subject_gets_more_time_and_days_stay_within_hours():
    p = plan()
    hours = {s: sum(t.hours for _, t in tasks_of(p, s) if t.kind in ("study", "review")) for s in ("DBMS", "OS")}
    assert hours["DBMS"] > hours["OS"]
    assert all(d.hours <= 4 for d in p.days)


def test_timetable_errors():
    with pytest.raises(PlanError, match="at least one exam"):
        plan(exams=[])
    with pytest.raises(PlanError, match="after today"):
        plan(exams=[Exam("DBMS", TODAY)])
    with pytest.raises(PlanError, match="No topics for Maths"):
        plan(exams=[Exam("Maths", TODAY + timedelta(days=5))])
    with pytest.raises(PlanError, match="only once"):
        plan(exams=[Exam("DBMS", TODAY + timedelta(days=5)), Exam("dbms", TODAY + timedelta(days=7))])
    with pytest.raises(PlanError, match="Not enough time before the DBMS exam"):
        plan(exams=[Exam("DBMS", TODAY + timedelta(days=1))], hours=0.5)


def test_notes_without_a_subject_are_planned_as_general():
    stats = [stat(1, None), stat(2, None)]
    p = plan(stats, [Exam(planner.GENERAL_SUBJECT, TODAY + timedelta(days=4))])
    assert {t.topic_id for _, t in tasks_of(p, "General") if t.kind == "study"} == {1, 2}


def test_round_trip_keeps_timetable():
    p = plan()
    again = planner.Plan.from_dict(p.to_dict())
    assert again.exams == p.exams and again.days[0].tasks[0].subject == p.days[0].tasks[0].subject


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    db.init_db()
    uid = db.get_or_create_user("u")["id"]
    for name, subject in (("dbms.pdf", "DBMS"), ("os.pdf", "OS")):
        doc = db.add_document(uid, name, subject, 5)
        db.set_topics(uid, doc, [f"{subject} one", f"{subject} two"])
    return uid


def test_create_saves_timetable_and_regenerate_drops_past_exams(env):
    exams = [Exam("DBMS", TODAY + timedelta(days=3), "10:00"), Exam("OS", TODAY + timedelta(days=8))]
    assert planner.subject_names(env) == ["DBMS", "OS"]
    planner.create_for_exams(env, exams, 3, today=TODAY)
    assert [(e["subject"], e["start_time"]) for e in db.list_exams(env)] == [("DBMS", "10:00"), ("OS", None)]

    _, saved = planner.latest(env)
    later = planner.regenerate(env, saved, today=TODAY + timedelta(days=4))  # DBMS exam is over
    assert [e["subject"] for e in later.exams] == ["OS"]
    with pytest.raises(PlanError, match="passed"):
        planner.regenerate(env, later, today=TODAY + timedelta(days=9))
