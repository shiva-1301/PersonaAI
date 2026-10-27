"""Set up the demo "AI" cohort: organised course notes, 5 students with sign-up codes.

    python scripts/setup_demo_ai_cohort.py

1. Copies every file in notes/ to notes_organized/ under a clean "Subject - Unit N" name
   (the originals are left untouched). Subjects and units below were decided from each
   file's content, not only its name.
2. Backs up the database, then creates the cohort AI / year 3, its subjects, and the demo
   students, and issues each a one-time sign-up code (written once to
   demo_accounts/ai_cohort_signup_codes.csv, which git ignores).
3. Uploads every organised file as shared course notes for the cohort (OCR included), and
   writes demo_accounts/ingest_report.json.

Safe to re-run: files are re-uploaded in place, students are updated, and codes are only
issued to students who have neither a password nor a code. Other accounts are not touched.
Stop the running app first: the search index shouldn't be written by two processes at once.
"""

import csv
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core import auth, config, db, ingest  # noqa: E402

NOTES, ORGANIZED, ACCOUNTS = ROOT / "notes", ROOT / "notes_organized", ROOT / "demo_accounts"
DEPARTMENT, YEAR = "AI", "3"

# original file -> (subject, unit, clean name, what the content shows)
FILES = {
    "UNIT-1 NLP (1).pdf": ("NLP", "Unit 1", "NLP - Unit 1.pdf", "Unit-1: regular expressions and N-grams"),
    "NLP-UNIT 2.pdf": ("NLP", "Unit 2", "NLP - Unit 2.pdf", "UNIT-2: lexical semantics"),
    "NLP-Unit-3 (1).pdf": ("NLP", "Unit 3", "NLP - Unit 3.pdf", "UNIT-3: constituency grammar and parsing"),
    "NLP-Unit-4 (1).pdf": ("NLP", "Unit 4", "NLP - Unit 4.pdf", "UNIT-4: word senses, WordNet"),
    "NLP-Unit-5 (1).pdf": ("NLP", "Unit 5", "NLP - Unit 5.pdf", "Unit-5: coreference and discourse coherence"),
    "N Grams programs (1).docx": ("NLP", "Lab programs", "NLP - Lab Programs - N-grams.docx",
                                  "NLTK n-gram probability programs (Unit 1 topic)"),
    "Regular Expressions programs (1).docx": ("NLP", "Lab programs", "NLP - Lab Programs - Regular Expressions.docx",
                                              "Python regex programs (Unit 1 topic)"),
    "NLP_Viva_Questions.pdf": ("NLP", "Viva questions", "NLP - Viva Questions (Units 1-5).pdf",
                               "100 Q&A, 20 per unit, Units 1-5"),
    "DeepLearning_Unit-I.pptx": ("Deep Learning", "Unit 1", "Deep Learning - Unit 1.pptx",
                                 "Unit-I: deep learning fundamentals"),
    "DeepLearning_Unit-II.pptx": ("Deep Learning", "Unit 2", "Deep Learning - Unit 2.pptx",
                                  "Unit-II: convolutional neural networks"),
    "DeepLearning_Unit-III (2).pptx": ("Deep Learning", "Unit 3", "Deep Learning - Unit 3.pptx",
                                       "Unit-III: recurrent neural networks"),
    "Deep_Learning_Packages_Basics_TensorFlow_Keras_PyTorch.pptx": (
        "Deep Learning", "Lab programs", "Deep Learning - Lab - TensorFlow, Keras and PyTorch Basics.pptx",
        "lab experiment on DL frameworks"),
    "BD- Unit - II.pptx": ("Big Data", "Unit 2", "Big Data - Unit 2.pptx", "YARN, MapReduce job run, scheduling"),
    "BDAH - Unit - III (1).pptx": ("Big Data", "Unit 3", "Big Data - Unit 3.pptx", "UNIT-III: Apache Pig"),
    "UNIT 3_Notes -Cybersecurity_Complete_Notes_Buffer_Overflow_SQL_Injection_Malicious_PDF (1).docx": (
        "Cyber Security", "Unit 3", "Cyber Security - Unit 3 (Notes).docx",
        "Unit 3 notes: buffer overflow, SQL injection, malicious PDF"),
    "UNIT III (1).pptx": ("Cyber Security", "Unit 3", "Cyber Security - Unit 3 (Slides).pptx",
                          "Exploitation: buffer overflow, SQL injection, malicious PDF"),
    "UNIT IV (1).pptx": ("Cyber Security", "Unit 4", "Cyber Security - Unit 4.pptx", "web exploit tools"),
    "Unit 1 Final Notes (1).docx": ("Negotiation Skills", "Unit 1", "Negotiation Skills - Unit 1.docx",
                                    "UNIT-I: negotiation"),
    "Unit 2 Final Notes (1).docx": ("Negotiation Skills", "Unit 2", "Negotiation Skills - Unit 2.docx",
                                    "UNIT-II: types and practice of negotiation"),
}
# Demo students (format of a JNTUH-style hall ticket: year, college, course, branch 66 = AI&ML, roll).
STUDENTS = [
    ("24B81A6601", "Aarav Sharma"), ("24B81A6602", "Diya Reddy"), ("24B81A6603", "Karthik Rao"),
    ("24B81A6604", "Meghana Varma"), ("24B81A6605", "Rohan Naidu"),
]


def organise() -> None:
    missing = [name for name in FILES if not (NOTES / name).exists()]
    extra = [p.name for p in NOTES.iterdir() if p.is_file() and p.name not in FILES]
    if missing or extra:
        sys.exit(f"notes/ doesn't match the plan. Missing: {missing}. Not planned: {extra}.")
    ORGANIZED.mkdir(exist_ok=True)
    for original, (_, _, clean, _) in FILES.items():
        shutil.copy2(NOTES / original, ORGANIZED / clean)
    print(f"Copied {len(FILES)} files to {ORGANIZED.name}/")


def backup_database() -> None:
    if config.DB_PATH.exists():
        target = config.DATA_DIR / "backups" / f"personaai_{datetime.now():%Y%m%d_%H%M%S}.db"
        target.parent.mkdir(exist_ok=True)
        shutil.copy2(config.DB_PATH, target)
        print(f"Database backed up to {target.relative_to(ROOT)}")


def enrol() -> int:
    db.init_db()
    cohort = db.get_or_create_cohort(DEPARTMENT, YEAR)
    db.import_students([{"hall_ticket": t, "name": n, "department": DEPARTMENT, "year": YEAR} for t, n in STUDENTS])
    ACCOUNTS.mkdir(exist_ok=True)
    issued = []
    for ticket, name in STUDENTS:
        user = db.find_user(ticket)
        if not user["password_hash"] and not user["setup_code_hash"]:
            issued.append((ticket, name, auth.issue_setup_code(user["id"])))
    if issued:
        path = ACCOUNTS / "ai_cohort_signup_codes.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["hall_ticket", "name", "signup_code"])
            writer.writerows(issued)
        print(f"Sign-up codes written to {path.relative_to(ROOT)} (shown once here):")
        for row in issued:
            print("  " + "  ".join(row))
    else:
        print("All demo students already have a code or a password; no new codes issued.")
    return cohort


def upload(cohort: int) -> None:
    admin = db.get_or_create_user(auth.ADMIN_USERNAME)["id"]
    subjects = {s: db.add_subject(cohort, s) for s in dict.fromkeys(v[0] for v in FILES.values())}
    report = []
    for original, (subject, unit, clean, _) in FILES.items():
        started = time.time()
        try:
            result = ingest.ingest(admin, clean, (ORGANIZED / clean).read_bytes(),
                                   cohort_id=cohort, subject_id=subjects[subject], unit=unit)
            row = {"file": clean, "subject": subject, "unit": unit, "pages": result.pages,
                   "chunks": result.chunks, "image_pages_read": result.image_pages_read,
                   "topics": result.topics, "warning": result.warning}
        except Exception as exc:
            row = {"file": clean, "subject": subject, "unit": unit, "error": f"{type(exc).__name__}: {exc}"}
        row["seconds"] = round(time.time() - started, 1)
        report.append(row)
        print(f"  {clean:60} {row.get('chunks', '-'):>4} chunks {row.get('image_pages_read', 0):>3} OCR "
              f"{len(row.get('topics', [])):>2} topics {row['seconds']:>6}s {row.get('warning') or row.get('error') or ''}")
    (ACCOUNTS / "ingest_report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    organise()
    backup_database()
    cohort = enrol()
    print("Uploading course notes...")
    upload(cohort)
