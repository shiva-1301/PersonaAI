"""Study plan -> .ics calendar file."""

from datetime import date, timedelta

from core import ics
from core.memory import TopicStat
from core.planner import Exam, build_exam_plan

TODAY = date(2026, 11, 2)


def plan():
    stats = [TopicStat(i, f"Topic {i}, part {i}", i, "f.pdf", 0, 0, None, None, "DBMS") for i in range(1, 5)]
    return build_exam_plan(stats, [Exam("DBMS", TODAY + timedelta(days=4), "09:30")], 3, today=TODAY)


def unfold(text: str) -> list[str]:
    return text.replace("\r\n ", "").split("\r\n")


def test_study_days_and_exam_become_events_with_reminders():
    text = ics.plan_to_ics(plan())
    lines = unfold(text)
    assert lines[0] == "BEGIN:VCALENDAR" and text.endswith("END:VCALENDAR\r\n")
    assert lines.count("BEGIN:VEVENT") == lines.count("END:VEVENT") == 5  # 4 study/revision days + exam
    exam = lines.index("SUMMARY:Exam: DBMS at 09:30")
    assert lines[exam - 2] == "DTSTART:20261106T093000" and lines[exam - 1] == "DTEND:20261106T123000"
    assert "TRIGGER:-P1D" in lines and "TRIGGER:-PT30M" in lines
    assert "DTSTART:20261102T190000" in lines  # 3 h of study ending at 22:00
    assert any(line.startswith("DESCRIPTION:- DBMS · Study: Topic 1\\, part 1") for line in lines)  # escaped


def test_long_lines_are_folded():
    assert all(len(line) <= 75 for line in ics.plan_to_ics(plan()).split("\r\n"))


def test_exam_without_a_valid_time_starts_at_ten():
    p = plan()
    p.exams[0]["time"] = "soon"
    assert "DTSTART:20261106T100000" in unfold(ics.plan_to_ics(p))
