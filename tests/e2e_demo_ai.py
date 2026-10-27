"""End-to-end check of the demo "AI" cohort in headless Chromium, against the running app.

    python tests/e2e_demo_ai.py http://localhost:8501 [out_dir]

Needs the cohort from scripts/setup_demo_ai_cohort.py and its codes CSV. Signs in as two
demo students, asks 2 questions per subject (checking the cited files), one question that
spans two subjects and one the notes don't cover, generates a quiz for one chapter in the
browser, and checks a student of another cohort sees none of the notes. Afterwards the two
students used are reset with fresh sign-up codes, so every code in the CSV still works.
Writes results.json and screenshots to out_dir. Passwords and codes are never printed.
"""

import csv
import json
import re
import secrets
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core import auth, db  # noqa: E402

BASE = sys.argv[1]
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else ROOT / "test_screenshots")
OUT.mkdir(parents=True, exist_ok=True)
CODES_CSV = ROOT / "demo_accounts" / "ai_cohort_signup_codes.csv"
SLOW = 240_000

# (asking student index, subject, question, file the answer must cite)
QUESTIONS = [
    (0, "NLP", "What is a context-free grammar?", "NLP - Unit 3.pdf"),
    (0, "NLP", "What is coreference resolution?", "NLP - Unit 5.pdf"),
    (0, "Deep Learning", "What do striding and padding do in a convolutional neural network?", "Deep Learning - Unit 2.pptx"),
    (0, "Deep Learning", "How is an LSTM different from a vanilla RNN?", "Deep Learning - Unit 3.pptx"),
    (0, "Big Data", "What are the main components of YARN?", "Big Data - Unit 2.pptx"),
    (1, "Big Data", "What is Apache Pig used for?", "Big Data - Unit 3.pptx"),
    (1, "Cyber Security", "How can SQL injection be prevented?", "Cyber Security - Unit 3"),
    (1, "Cyber Security", "What are web exploit tools and how do they hide exploits?", "Cyber Security - Unit 4.pptx"),
    (1, "Negotiation Skills", "What is the difference between distributive and integrative negotiation?",
     "Negotiation Skills - Unit 2.docx"),
    (1, "Negotiation Skills", "Why do people negotiate?", "Negotiation Skills - Unit 1.docx"),
]
CROSS = ("What does the YARN Resource Manager do, and what does a pooling layer do in a CNN?",
         ["Big Data - Unit 2.pptx", "Deep Learning - Unit 2.pptx"])
NOT_COVERED = "How does the Kubernetes scheduler decide which node a pod runs on?"
QUIZ_CHAPTER = "Deep Learning · Unit 2"

results: dict = {"checks": [], "answers": [], "timings": {}}
shot_no = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    results["checks"].append({"check": name, "ok": bool(ok), "detail": detail})
    print(("PASS " if ok else "FAIL ") + name + (f" ({detail})" if detail else ""), flush=True)


def shot(page: Page, name: str) -> None:
    global shot_no
    shot_no += 1
    page.wait_for_timeout(500)
    page.screenshot(path=str(OUT / f"{shot_no:02d}_{name}.png"), full_page=True)


def sign_in_first_time(page: Page, ticket: str, code: str, password: str) -> None:
    page.goto(BASE)
    page.get_by_label("Hall ticket number").fill(ticket)
    page.locator('input[aria-label="Password"]').fill("")
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_text("First sign-in for").first).to_be_visible(timeout=30_000)
    page.get_by_label("Sign-up code").fill(code)
    page.locator('input[aria-label="New password"]').fill(password)
    page.get_by_label("Confirm password").fill(password)
    page.get_by_role("button", name="Set password and continue").click()
    expect(page.get_by_text("Welcome back").first).to_be_visible(timeout=60_000)


def sign_out(page: Page) -> None:
    page.get_by_role("button", name="Log out").click()
    expect(page.get_by_label("Hall ticket number")).to_be_visible(timeout=30_000)


def ask(page: Page, question: str) -> tuple[str, float]:
    """Ask in the chat and return the new answer's text (with its source badges)."""
    messages = page.locator('[data-testid="stChatMessage"]')
    before = messages.count()
    page.get_by_placeholder("Ask a question about your notes").fill(question)
    started = time.time()
    page.keyboard.press("Enter")
    expect(messages).to_have_count(before + 2, timeout=SLOW)
    answer = messages.nth(before + 1)
    # The spinner sits in the answer bubble until the reply is in. Asking again before that
    # would make Streamlit drop the unfinished answer.
    expect(answer).not_to_contain_text("Searching your notes", timeout=SLOW)
    expect(answer).to_contain_text(re.compile(r"claude / |gemini / |ollama / |couldn't find", re.I), timeout=SLOW)
    page.wait_for_timeout(800)
    return answer.inner_text(), time.time() - started


def chapters_offered(page: Page, labels: list[str]) -> list[str]:
    """Which of these chapters the picker offers. The list scrolls (only ~10 rows are in the
    page at once), so each label is typed into the picker's filter and looked for."""
    box = page.locator(".st-key-card_setup").get_by_label("Chapters").first
    found = []
    for label in labels:
        box.click()
        box.fill(label)
        if page.get_by_role("option", name=label, exact=True).count():
            found.append(label)
        box.fill("")
        page.keyboard.press("Escape")
    return found


def run(page: Page, students: list[dict]) -> None:
    passwords = [secrets.token_urlsafe(10) for _ in students]
    for idx in (0, 1):
        student = students[idx]
        sign_in_first_time(page, student["hall_ticket"], student["signup_code"], passwords[idx])
        check(f"{student['hall_ticket']} signs in with their code", True)
        page.get_by_role("link", name="Notes Q&A").click()
        expect(page.get_by_text("Course notes (19)").first).to_be_visible(timeout=SLOW)
        if idx == 0:
            shot(page, "student_course_notes")
        for who, subject, question, expected in QUESTIONS:
            if who != idx:
                continue
            text, seconds = ask(page, question)
            cited = re.findall(r"S\d+ · ([^\n]+?(?:p\. \d+|slide \d+|\.docx|\.pdf|\.pptx))", text)
            ok = any(expected in c for c in cited)
            results["answers"].append({"student": student["hall_ticket"], "subject": subject, "question": question,
                                       "expected_source": expected, "cited": cited, "seconds": round(seconds, 1),
                                       "answer": text})
            check(f"{subject}: '{question}' cites {expected}", ok, f"{seconds:.1f}s; cited {cited}")
        shot(page, f"student{idx + 1}_answers")
        if idx == 1:
            text, seconds = ask(page, CROSS[0])
            cited = re.findall(r"S\d+ · ([^\n]+?(?:p\. \d+|slide \d+|\.docx|\.pdf|\.pptx))", text)
            results["answers"].append({"question": CROSS[0], "cited": cited, "seconds": round(seconds, 1), "answer": text})
            check("cross-subject question cites both subjects' files",
                  all(any(e in c for c in cited) for e in CROSS[1]), f"{seconds:.1f}s; cited {cited}")
            text, seconds = ask(page, NOT_COVERED)
            results["answers"].append({"question": NOT_COVERED, "seconds": round(seconds, 1), "answer": text})
            check("question the notes don't cover is answered honestly",
                  "couldn't find this in your notes" in text.lower() or "not in your notes" in text.lower()
                  or "don't cover" in text.lower() or "do not cover" in text.lower(), f"{seconds:.1f}s")
            shot(page, "cross_and_not_covered")

            page.get_by_role("link", name="Quiz").click()
            expect(page.locator(".st-key-card_setup")).to_be_visible(timeout=60_000)
            expected = ([f"NLP · Unit {i}" for i in range(1, 6)] + ["NLP · Lab programs", "NLP · Viva questions"]
                        + [f"Deep Learning · Unit {i}" for i in range(1, 4)] + ["Deep Learning · Lab programs"]
                        + ["Big Data · Unit 2", "Big Data · Unit 3", "Cyber Security · Unit 3", "Cyber Security · Unit 4",
                           "Negotiation Skills · Unit 1", "Negotiation Skills · Unit 2"])
            chapters = chapters_offered(page, expected)
            results["chapters"] = chapters
            check("quiz picker lists every subject's chapters", chapters == expected,
                  f"{len(chapters)} of {len(expected)}; missing {sorted(set(expected) - set(chapters))}")
            page.locator(".st-key-card_setup").get_by_label("Chapters").first.click()
            page.get_by_role("option", name=QUIZ_CHAPTER, exact=True).click()
            page.keyboard.press("Escape")
            page.wait_for_timeout(800)
            shot(page, "quiz_chapter_picked")
            started = time.time()
            page.get_by_role("button", name="Generate quiz").click()
            expect(page.get_by_text("Question 1 of 10", exact=True)).to_be_visible(timeout=SLOW)
            results["timings"]["browser_quiz_seconds"] = round(time.time() - started, 1)
            check(f"10-question quiz for {QUIZ_CHAPTER} generated in the browser", True,
                  f"{time.time() - started:.1f}s")
            shot(page, "quiz_question")
        sign_out(page)

    # Another cohort's student sees none of the AI notes.
    cohort = db.get_or_create_cohort("CSE", "3")
    db.import_students([{"hall_ticket": "24B81A0599", "name": "Isolation Check", "department": "CSE", "year": "3"}])
    other = db.find_user("24B81A0599")
    try:
        sign_in_first_time(page, "24B81A0599", auth.issue_setup_code(other["id"]), secrets.token_urlsafe(10))
        page.get_by_role("link", name="Notes Q&A").click()
        expect(page.get_by_text("Course notes (0)").first).to_be_visible(timeout=SLOW)
        check("a student of another cohort sees none of the AI cohort's notes",
              page.get_by_text("NLP - Unit").count() == 0)
        shot(page, "other_cohort")
        sign_out(page)
    finally:
        with db.connect() as conn:  # remove the temporary account and its empty cohort
            conn.execute("DELETE FROM login_failures WHERE username = ?", ("24b81a0599",))
            conn.execute("DELETE FROM users WHERE id = ?", (other["id"],))
            conn.execute("DELETE FROM cohorts WHERE id = ? AND NOT EXISTS"
                         " (SELECT 1 FROM users WHERE cohort_id = ?)", (cohort, cohort))


def reset_used_students(students: list[dict]) -> None:
    """Give the students signed in above fresh codes, so the CSV is valid for the demo."""
    for student in students[:2]:
        user = db.find_user(student["hall_ticket"])
        if user["password_hash"]:
            student["signup_code"] = auth.reset_password(user["id"])
    with CODES_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["hall_ticket", "name", "signup_code"])
        writer.writeheader()
        writer.writerows(students)


students = list(csv.DictReader(CODES_CSV.open(encoding="utf-8")))
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1400, "height": 1000})
    try:
        run(page, students)
    except Exception as exc:
        check("demo check ran to the end", False, f"{type(exc).__name__}: {str(exc)[:400]}")
        shot(page, "failure")
    finally:
        browser.close()
        reset_used_students(students)

(OUT / "demo_results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
failed = [c for c in results["checks"] if not c["ok"]]
print(f"\n{len(results['checks']) - len(failed)} passed, {len(failed)} failed")
sys.exit(1 if failed else 0)
