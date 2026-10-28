"""Email updates: quiz results and the day's study plan, sent from the project's account
(SMTP_USER) to the address a student gives on the Home page."""

import logging
import re
import smtplib
import ssl
import threading
from datetime import date
from email.message import EmailMessage

from core import config
from core.planner import Plan

log = logging.getLogger(__name__)
TIMEOUT_S = 20
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


class EmailError(RuntimeError):
    pass


def enabled() -> bool:
    return bool(config.SMTP_USER and config.SMTP_PASSWORD)


def valid_address(address: str) -> bool:
    return bool(EMAIL_RE.match(address.strip()))


def send(to: str, subject: str, body: str) -> None:
    """Send a plain-text email. Raises EmailError (never containing the password)."""
    if not enabled():
        raise EmailError("Email is not set up (SMTP_USER / SMTP_PASSWORD in .env).")
    msg = EmailMessage()
    msg["From"] = f"PersonaAI <{config.SMTP_USER}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body + f"\n\nOpen PersonaAI: {config.APP_URL}\n"
                    "To stop these emails, turn them off under Email updates on the Home page.")
    try:
        with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=TIMEOUT_S,
                              context=ssl.create_default_context()) as smtp:
            # Google shows app passwords in groups of four; the spaces aren't part of them.
            smtp.login(config.SMTP_USER, config.SMTP_PASSWORD.replace(" ", ""))
            smtp.send_message(msg)
    except smtplib.SMTPAuthenticationError as exc:
        log.warning("Email login failed (%s)", exc.smtp_code)
        raise EmailError("The email account rejected the login. Check SMTP_USER and the app password.") from None
    except (smtplib.SMTPException, OSError) as exc:
        log.warning("Email to a student failed: %s", type(exc).__name__)
        raise EmailError(f"Couldn't send the email ({type(exc).__name__}).") from None


def send_in_background(to: str, subject: str, body: str) -> None:
    """send() without making the student wait; failures are only logged."""
    def run():
        try:
            send(to, subject, body)
        except EmailError:
            pass
    threading.Thread(target=run, daemon=True).start()


def quiz_email(name: str, score: int, total: int, to_revise: list[str]) -> tuple[str, str]:
    percent = round(100 * score / total) if total else 0
    lines = [f"Hi {name},", "", f"You scored {score} / {total} ({percent}%) on your quiz."]
    if to_revise:
        lines += ["", "Topics to revise:"] + [f"- {t}" for t in to_revise]
    else:
        lines += ["", "Every answer was right. Well done!"]
    return f"Quiz result: {score}/{total} ({percent}%)", "\n".join(lines)


def reminder_email(name: str, plan: Plan, on: date) -> tuple[str, str] | None:
    """Today's tasks from the plan, or None if nothing is planned today."""
    day = plan.day(on)
    if not day or not day.tasks:
        return None
    lines = [f"Hi {name},", "", f"Your study plan for {on:%A %d %B}:", ""]
    for t in day.tasks:
        subject = f"{t.subject} · " if t.subject and t.kind != "exam" else ""
        lines.append(f"- {subject}{t.title}" + (f" ({t.hours:g} h)" if t.hours else ""))
    upcoming = [e for e in plan.exams or [] if e["date"] > on.isoformat()]
    if upcoming:
        nxt = upcoming[0]
        days = (date.fromisoformat(nxt["date"]) - on).days
        lines += ["", f"Next exam: {nxt['subject']} in {days} day{'s' if days != 1 else ''}."]
    hours = sum(t.hours for t in day.tasks)
    exam_today = any(t.kind == "exam" for t in day.tasks)
    subject = "Exam today" if exam_today else f"Today's study plan: {hours:g} h"
    return subject, "\n".join(lines)
