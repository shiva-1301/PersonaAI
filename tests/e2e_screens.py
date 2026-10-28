"""End-to-end screen test: drives the real app in headless Chromium and saves screenshots.

Not part of `pytest` (it needs a running app, real AI calls and a few minutes).

    set PERSONAAI_DATA_DIR=<empty folder>
    streamlit run app.py --server.port 8502 --server.headless true
    python tests/e2e_screens.py http://localhost:8502 <notes_unit3.pdf> <notes_unit4.pdf> <notes_subject2> [out_dir]

Run this script with the same PERSONAAI_DATA_DIR so it can check the app's database.
Covers: admin (sign in, class list, sign-up codes, subjects, notes per unit), a student
(first sign-in with code, shared + private notes, Q&A, quiz by unit, two-exam study plan),
and cohort isolation. Passwords and codes are never printed.
"""

import csv
import io
import re
import secrets
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config, db, planner, vectorstore  # noqa: E402

BASE, UNIT3, UNIT4, SUBJECT2 = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])
OUT = Path(sys.argv[5] if len(sys.argv) > 5 else "test_screenshots")
OUT.mkdir(parents=True, exist_ok=True)
SLOW = 240_000  # ms: uploads and quizzes call the AI and load the search models
CLASS_LIST = (
    "hall_ticket,name,department,year\n"
    "22B81A0501,Ananya Rao,CSE,3\n"
    "22B81A0502,Rahul Varma,CSE,3\n"
    "22B81A0401,Sneha Reddy,ECE,3\n"
)
STUDENT_PASSWORD = secrets.token_urlsafe(10)
started = time.time()
shot_no = 0
results: list[tuple[str, bool, str]] = []


def log(msg: str) -> None:
    print(f"[{time.time() - started:6.1f}s] {msg}", flush=True)


def shot(page: Page, name: str) -> None:
    global shot_no
    shot_no += 1
    page.wait_for_timeout(600)
    page.screenshot(path=str(OUT / f"{shot_no:02d}_{name}.png"), full_page=True)
    log(f"screenshot {shot_no:02d}_{name}")


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    log(("PASS " if ok else "FAIL ") + name + (f" ({detail})" if detail else ""))


def no_exception(page: Page, where: str) -> None:
    errors = page.locator('[data-testid="stException"]')
    check(f"no app error on {where}", errors.count() == 0,
          errors.first.inner_text()[:300] if errors.count() else "")


def settle(page: Page) -> None:
    """Wait for Streamlit to finish the current rerun."""
    page.wait_for_timeout(400)
    expect(page.locator('[data-testid="stStatusWidget"]')).to_have_count(0, timeout=SLOW)


def choose(page: Page, scope: str, label: str, option: str) -> None:
    """Pick an option in a selectbox or multiselect (inside the container `scope`).
    Typing filters the list and opens it even if the click landed during a rerun."""
    settle(page)
    for attempt in range(3):
        box = page.locator(scope).get_by_label(label).first
        box.click()
        page.keyboard.type(option[:20])
        try:
            page.get_by_role("option", name=option, exact=True).click(timeout=8000)
            break
        except Exception:
            page.keyboard.press("Escape")
            if attempt == 2:
                raise
    settle(page)


def attach(page: Page, scope: str, path: Path) -> None:
    """Choose a file in an uploader and wait until it has reached the server."""
    page.locator(f"{scope} input[type=file]").set_input_files(str(path))
    # Long names are shortened in the uploader ("BIG_DAT...IT-III.pdf"), so wait for the
    # uploaded file's size label ("310.0KB") instead.
    size = re.compile(r"^\d+(\.\d+)?\s?(B|KB|MB)$")
    expect(page.locator(scope).get_by_text(size).first).to_be_visible(timeout=60_000)
    page.wait_for_timeout(1000)


def sign_in(page: Page, ticket: str, password: str) -> None:
    page.goto(BASE)
    page.get_by_label("Hall ticket number").fill(ticket)
    page.locator("input[aria-label=\"Password\"]").fill(password)
    page.get_by_role("button", name="Sign in").click()
    settle(page)


def sign_out(page: Page) -> None:
    page.get_by_role("button", name="Log out").click()
    expect(page.get_by_label("Hall ticket number")).to_be_visible(timeout=30_000)


def first_sign_in(page: Page, ticket: str, code: str) -> None:
    sign_in(page, ticket, "")
    expect(page.get_by_text("First sign-in for").first).to_be_visible(timeout=30_000)
    page.get_by_label("Sign-up code").fill(code)
    page.get_by_role("textbox", name="Email", exact=True).fill(f"{ticket.lower()}@example.com")  # reserved domain: no real inbox
    page.locator("input[aria-label=\"New password\"]").fill(STUDENT_PASSWORD)
    page.get_by_label("Confirm password").fill(STUDENT_PASSWORD)
    page.get_by_role("button", name="Set password and continue").click()
    settle(page)


def download_codes(page: Page) -> dict[str, str]:
    """Create sign-up codes for the selected cohort and read them from the CSV download."""
    page.get_by_role("button", name="Create sign-up codes for students without a password").click()
    settle(page)
    with page.expect_download() as info:
        page.get_by_role("button", name="Download codes (CSV)").click()
    rows = csv.DictReader(io.StringIO(Path(info.value.path()).read_text(encoding="utf-8")))
    return {r["Hall ticket"]: r["Sign-up code"] for r in rows}


def nav(page: Page, title: str) -> None:
    page.get_by_role("link", name=title).click()
    settle(page)


def run(page: Page) -> None:
    # ---------------- Admin
    page.goto(BASE)
    expect(page.get_by_label("Hall ticket number")).to_be_visible(timeout=60_000)
    shot(page, "login")
    sign_in(page, "admin", config.ADMIN_PASSWORD)
    expect(page.get_by_text("Import a class list").first).to_be_visible(timeout=30_000)
    check("admin signs in and sees only the Admin page",
          page.get_by_role("link", name="Admin").count() == 1 and page.get_by_role("link", name="Quiz").count() == 0)
    shot(page, "admin_start")

    csv_path = OUT / "class_list.csv"
    csv_path.write_text(CLASS_LIST, encoding="utf-8")
    page.locator(".st-key-card_class_list input[type=file]").set_input_files(str(csv_path))
    expect(page.get_by_text("3 students in this file.").first).to_be_visible(timeout=30_000)
    shot(page, "admin_class_list_preview")
    page.get_by_role("button", name="Import 3 students").click()
    settle(page)
    expect(page.get_by_text("Imported: 3 new, 0 updated.").first).to_be_visible(timeout=30_000)
    check("class list imported into 2 cohorts", len(db.list_cohorts()) == 2)
    no_exception(page, "admin import")

    codes = download_codes(page)  # CSE · Year 3 is selected first
    check("sign-up codes issued for both CSE students", sorted(codes) == ["22B81A0501", "22B81A0502"])
    shot(page, "admin_signup_codes")
    page.get_by_role("button", name="I've handed them out").click()
    settle(page)
    choose(page, ".st-key-card_students", "Cohort", "ECE · Year 3")
    codes.update(download_codes(page))
    page.get_by_role("button", name="I've handed them out").click()
    settle(page)

    page.get_by_role("tab", name="Course notes").click()
    settle(page)
    for subject in ("Big Data", "Cyber Security"):
        page.get_by_label("New subject").fill(subject)
        page.get_by_role("button", name="Add subject").click()
        settle(page)
    cse = db.get_or_create_cohort("CSE", "3")
    check("two subjects added", [s["name"] for s in db.list_subjects(cse)] == ["Big Data", "Cyber Security"])

    for subject, unit, path in (("Big Data", "Unit 3", UNIT3), ("Big Data", "Unit 4", UNIT4),
                                ("Cyber Security", "Unit 3", SUBJECT2)):
        scope = ".st-key-card_share_notes"
        choose(page, scope, "Subject", subject)
        choose(page, scope, "Unit", unit)
        attach(page, scope, path)
        page.get_by_role("button", name="Share with cohort").click()
        # The result names this file, so an earlier upload's message can't satisfy the wait.
        expect(page.locator(scope).get_by_text(f"{path.name}:").first).to_be_visible(timeout=SLOW)
        settle(page)
        log(f"shared {path.name} as {subject} / {unit}")
    shared = db.list_cohort_documents(cse)
    check("3 documents shared with CSE · Year 3, each with topics",
          len(shared) == 3 and all(db.list_topics(db.find_user("admin")["id"], d["id"]) for d in shared),
          ", ".join(f"{d['subject_name']}/{d['unit']}" for d in shared))
    no_exception(page, "admin course notes")
    shot(page, "admin_course_notes")
    sign_out(page)

    # ---------------- Student (CSE)
    first_sign_in(page, "22B81A0401", "WRONG-CODE")
    check("wrong sign-up code is refused", page.get_by_text("isn't right").count() == 1)
    shot(page, "student_wrong_code")
    page.get_by_role("button", name="Use a different hall ticket number").click()
    settle(page)

    first_sign_in(page, "22B81A0501", codes["22B81A0501"])
    expect(page.get_by_text("Welcome back, Ananya").first).to_be_visible(timeout=60_000)
    check("student first sign-in with code and new password", True)
    shot(page, "student_home")

    nav(page, "Notes Q&A")
    expect(page.get_by_text("Course notes (3)")).to_be_visible(timeout=SLOW)
    private = OUT / "my_flume_notes.txt"
    private.write_text(
        "My revision notes on Apache Flume.\n\nA Flume agent has three parts: a source, a channel and a "
        "sink. A memory channel is fast but loses events if the agent crashes; a file channel is "
        "slower but durable. Interceptors can modify or drop events before they reach the channel.",
        encoding="utf-8")
    choose(page, ".st-key-card_upload", "Subject", "Big Data")
    attach(page, ".st-key-card_upload", private)
    page.get_by_role("button", name="Process files").click()
    expect(page.get_by_text("My notes (1)")).to_be_visible(timeout=SLOW)
    check("shared and private notes listed together", page.get_by_text("Course notes (3)").count() == 1)
    page.get_by_placeholder("Ask a question about your notes").fill("What is fan-out in Flume?")
    page.keyboard.press("Enter")
    expect(page.get_by_text("Show source excerpts").first).to_be_visible(timeout=SLOW)
    no_exception(page, "Notes Q&A")
    shot(page, "student_notes_and_answer")

    nav(page, "Quiz")
    choose(page, ".st-key-card_setup", "Subject", "Big Data")
    units = ["Unit 3 · " + UNIT3.name, "Unit 4 · " + UNIT4.name]
    page.locator(".st-key-card_setup").get_by_label("Units / documents").first.click()
    for unit in units:  # the list stays open while picking several
        page.get_by_role("option", name=unit, exact=True).click()
        page.wait_for_timeout(500)
    page.keyboard.press("Escape")
    settle(page)
    picked = page.locator(".st-key-card_setup").get_by_text(re.compile(r"^Unit [34] · "))
    check("both units selected in the quiz picker", picked.count() == 2, f"{picked.count()} chips")
    shot(page, "student_quiz_setup")
    t0 = time.time()
    page.get_by_role("button", name="Generate quiz").click()
    expect(page.get_by_text("Question 1 of 10").first).to_be_visible(timeout=SLOW)
    check("10-question quiz from 2 units generated", True, f"{time.time() - t0:.1f}s in the browser")
    shot(page, "student_quiz_question")
    for i in range(10):
        # Wait for each step to show on screen: clicking during a rerun can land on the old question.
        expect(page.get_by_text(f"Question {i + 1} of 10", exact=True)).to_be_visible(timeout=30_000)
        answered = page.get_by_text(f"{i + 1} of 10 answered", exact=True)
        for _ in range(4):  # a click that lands while the question is being replaced is lost
            page.wait_for_timeout(700)
            page.locator('.st-key-question [data-testid="stRadioOption"]').first.click()
            try:
                expect(answered).to_be_visible(timeout=8000)
                break
            except AssertionError:
                pass
        expect(answered).to_be_visible(timeout=1000)
        if i < 9:
            page.get_by_role("button", name="Next").click()
    page.get_by_role("button", name="Submit answers").click()
    expect(page.get_by_text("Review", exact=True).first).to_be_visible(timeout=60_000)
    no_exception(page, "Quiz")
    shot(page, "student_quiz_results")
    student = db.find_user("22B81A0501")["id"]
    attempts = db.list_quiz_attempts(student)
    check("quiz attempt saved", len(attempts) == 1 and attempts[0]["total"] == 10)

    nav(page, "Study Plan")
    page.get_by_role("button", name="Create plan").click()  # default timetable: one row per subject
    expect(page.get_by_text("Day by day").first).to_be_visible(timeout=60_000)
    no_exception(page, "Study Plan")
    shot(page, "student_study_plan")
    _, plan = planner.latest(student)
    exams = {e["subject"]: date.fromisoformat(e["date"]) for e in plan.exams}
    check("plan has two exams", sorted(exams) == ["Big Data", "Cyber Security"], str(exams))
    by_day = {d.date: d for d in plan.days}
    both_early = sum(1 for d in plan.days[:5] if {t.subject for t in d.tasks if t.kind != "exam"} >= set(exams))
    check("early days split between both subjects", both_early >= 3, f"{both_early} of the first 5 days")
    for subject, day in exams.items():
        before = by_day[(day - timedelta(days=1)).isoformat()]
        check(f"day before the {subject} exam is its revision day",
              before.tasks and all(t.kind == "revision" and t.subject == subject for t in before.tasks))
        after = [d.date for d in plan.days if d.date > day.isoformat() and any(t.subject == subject for t in d.tasks)]
        check(f"nothing for {subject} after its exam", not after, ", ".join(after))
    sign_out(page)

    # ---------------- Isolation: a student from another cohort
    first_sign_in(page, "22B81A0401", codes["22B81A0401"])
    expect(page.get_by_text("Welcome back, Sneha").first).to_be_visible(timeout=60_000)
    nav(page, "Notes Q&A")
    expect(page.get_by_text("Course notes (0)")).to_be_visible(timeout=SLOW)
    check("other cohort sees no course notes and none of Ananya's private notes",
          page.get_by_text(UNIT3.name).count() == 0 and page.get_by_text(private.name).count() == 0)
    ece = db.find_user("22B81A0401")["id"]
    check("other cohort's search finds nothing", vectorstore.search(ece, "fan out in flume") == [])
    shot(page, "other_cohort_notes")
    nav(page, "Quiz")
    check("other cohort cannot make a quiz", page.get_by_text("Upload your notes on the Notes Q&A page first").count() == 1)
    shot(page, "other_cohort_quiz")
    sign_out(page)

    # ---------------- Lockout
    for _ in range(5):
        sign_in(page, "22B81A0501", "wrong-password")
    sign_in(page, "22B81A0501", STUDENT_PASSWORD)
    check("5 wrong passwords lock the account, even for the right one",
          page.get_by_text("Too many failed attempts").count() == 1)
    shot(page, "lockout")


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1400, "height": 1000}, accept_downloads=True)
    try:
        run(page)
    except Exception as exc:
        check("screen test ran to the end", False, f"{type(exc).__name__}: {str(exc)[:400]}")
        shot(page, "failure")
    finally:
        browser.close()

failed = [r for r in results if not r[1]]
print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
for name, _, detail in failed:
    print(f"  FAIL {name}: {detail}")
sys.exit(1 if failed else 0)
