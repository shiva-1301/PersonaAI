"""A study plan as an .ics calendar file (Google Calendar, Outlook, Apple Calendar).

Each study day becomes one event ending at 22:00 listing that day's tasks, with a reminder
30 minutes before; each exam becomes an event at its start time, with reminders the
day before and an hour before. Times are "floating" (the phone's own time zone).
"""

from datetime import date, datetime, timedelta, timezone

from core.planner import Plan

STUDY_END = "22:00"  # study days have no set time; a block ending in the evening suits most
EARLIEST_START = "08:00"
EXAM_START = "10:00"  # for exams entered without a time
EXAM_HOURS = 3


def _escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n"))


def _fold(line: str) -> list[str]:
    """Lines longer than 75 characters continue on the next line after a space (RFC 5545)."""
    parts = [line[:75]]
    line = line[75:]
    while line:
        parts.append(" " + line[:74])
        line = line[74:]
    return parts


def _stamp(day: date, hhmm: str) -> datetime:
    hours, minutes = (int(x) for x in hhmm.split(":")[:2])
    return datetime(day.year, day.month, day.day, hours, minutes)


def _time_of(text: str | None, default: str) -> str:
    try:
        hours, minutes = (int(x) for x in (text or "").strip().split(":")[:2])
        return f"{hours:02d}:{minutes:02d}" if 0 <= hours < 24 and 0 <= minutes < 60 else default
    except ValueError:
        return default


def _event(uid: str, start: datetime, end: datetime, title: str, details: str, alarms: list[str]) -> list[str]:
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}@personaai",
        f"DTSTAMP:{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}",
        f"DTSTART:{start:%Y%m%dT%H%M%S}",
        f"DTEND:{end:%Y%m%dT%H%M%S}",
        f"SUMMARY:{_escape(title)}",
        f"DESCRIPTION:{_escape(details)}",
    ]
    for trigger in alarms:
        lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_escape(title)}",
                  f"TRIGGER:{trigger}", "END:VALARM"]
    return lines + ["END:VEVENT"]


def plan_to_ics(plan: Plan) -> str:
    times = {e["subject"]: e.get("time") for e in plan.exams or []}
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//PersonaAI//Study plan//EN",
             "CALSCALE:GREGORIAN", "X-WR-CALNAME:PersonaAI study plan"]
    for day in plan.days:
        on = date.fromisoformat(day.date)
        for task in (t for t in day.tasks if t.kind == "exam"):
            start = _stamp(on, _time_of(times.get(task.subject), EXAM_START))
            lines += _event(f"{day.date}-exam-{task.subject}", start, start + timedelta(hours=EXAM_HOURS),
                            task.title, "Good luck!", ["-P1D", "-PT1H"])
        study = [t for t in day.tasks if t.kind != "exam"]
        if study:
            hours = sum(t.hours for t in study)
            start = max(_stamp(on, STUDY_END) - timedelta(hours=hours), _stamp(on, EARLIEST_START))
            details = "\n".join(f"- {t.subject + ' · ' if t.subject else ''}{t.title} ({t.hours:g} h)"
                                for t in study)
            lines += _event(f"{day.date}-study", start, start + timedelta(hours=hours),
                            f"Study plan: {hours:g} h", details, ["-PT30M"])
    lines.append("END:VCALENDAR")
    return "\r\n".join(part for line in lines for part in _fold(line)) + "\r\n"
