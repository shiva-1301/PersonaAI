"""Email each student who asked for it their study plan for today.

    python scripts/send_reminders.py

Run it once each morning, e.g. with Windows Task Scheduler:
    schtasks /Create /SC DAILY /ST 07:00 /TN "PersonaAI reminders" ^
      /TR "C:\\Projects\\PersonaAI\\.venv\\Scripts\\python.exe C:\\Projects\\PersonaAI\\scripts\\send_reminders.py"
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import db, notify, planner  # noqa: E402


def main(today: date | None = None) -> tuple[int, int]:
    """Send today's reminders; returns (sent, failed)."""
    today = today or date.today()
    if not notify.enabled():
        print("Email is not set up (SMTP_USER / SMTP_PASSWORD in .env).")
        return 0, 0
    db.init_db()
    sent = failed = 0
    for user in db.users_wanting_reminders():
        latest = planner.latest(user["id"])
        email = latest and notify.reminder_email((user["full_name"] or user["username"]).split()[0],
                                                 latest[1], today)
        if not email:
            continue
        try:
            notify.send(user["email"], *email)
            sent += 1
        except notify.EmailError as exc:
            print(f"{user['username']}: {exc}")
            failed += 1
    print(f"{sent} reminder(s) sent, {failed} failed.")
    return sent, failed


if __name__ == "__main__":
    sys.exit(1 if main()[1] else 0)
