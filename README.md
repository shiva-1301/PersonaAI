# PersonaAI

**An adaptive AI study assistant that learns what you don't know yet.**

PersonaAI lets a student upload their course material, ask questions about it, take auto-generated quizzes, and get a study plan for their exam. Unlike a general chatbot, it remembers which topics each student struggles with and adapts its quizzes and study plan to target those weak areas.

Aligned with **SDG 4 – Quality Education**.

---

## Problem

Students revise from scattered notes and PDFs, and general AI chatbots:
- answer from general knowledge, not from *their* syllabus and notes,
- don't remember what a student got wrong last time,
- give the same generic study advice to everyone.

## Solution

A web app that grounds every answer in the student's own material (Retrieval-Augmented Generation) and keeps a long-term memory of each student's weak topics.

---

## Features

### 1. Notes Q&A with citations
- Upload course material (PDF, DOCX, TXT).
- Ask questions in plain language.
- Answers are generated **only from the uploaded material** and cite the source document and page.
- If the answer isn't in the material, the assistant says so instead of guessing.

### 2. Quiz generation
- Generate multiple-choice quizzes from any uploaded document or topic.
- Instant grading with explanations for each answer.
- Every answer is recorded per topic.

### 3. Weak-topic memory
- Tracks the student's accuracy on each topic across all quizzes.
- Flags weak topics (low accuracy) and strong topics.
- Later quizzes focus more on weak topics.
- Dashboard shows topic-wise progress over time.

### 4. Personalized study plan
- Student enters the exam date and available hours per day.
- Generates a day-by-day revision plan covering the syllabus, with extra time on weak topics.
- Plan updates as quiz performance changes.

---

## Tech Stack

| Component | Choice |
|---|---|
| Language | Python 3.12 |
| Web UI | Streamlit (custom theme in `.streamlit/config.toml`, shared styles in `ui/`) |
| Charts | Plotly |
| LLM | Google Gemini API (online) / Ollama (offline fallback) |
| Embeddings | sentence-transformers `all-MiniLM-L6-v2` (runs locally) |
| Reranking | cross-encoder `ms-marco-MiniLM-L-6-v2` (runs locally) |
| Vector database | ChromaDB |
| App database | SQLite (users, quiz results, topic scores, plans) |
| Document parsing | pypdf, python-docx |
| Deployment | Streamlit Community Cloud |
| Version control | Git & GitHub |

## System Architecture

```
Upload PDF/DOCX/TXT
        │
        ▼
 Text extraction → Chunking → Embeddings → ChromaDB
                                              │
 Student question ──► Retrieve 20 chunks ◄────┘
                            │
                            ▼
                   Rerank (cross-encoder) → top 5
                            │
                            ▼
                   LLM (Gemini / Ollama) ──► Answer + citations
                            │
 Quiz answers ──► SQLite (topic scores) ──► Weak-topic memory
                                                  │
                                                  ▼
                                   Quiz targeting + Study plan
```

---

## Deliverables

1. **Working web application**: all four features, deployed online with a public link.
2. **Source code repository** on GitHub with a clear structure and setup instructions.
3. **Evaluation report** covering:
   - answer accuracy with RAG vs. without RAG, on a set of real exam questions;
   - quiz improvement when quizzes target weak topics vs. random topics.
4. **Technical documentation**: architecture, database schema, and module descriptions.
5. **User guide** with screenshots.
6. **Demo video** (3–5 minutes).

---

## Scope

**In scope:** single-subject or multi-subject study material, per-user memory, the four features above, and an offline mode via Ollama.

**Out of scope:** lecture recording and transcription, calendar and email integration, mobile app, payment, and multi-institution deployment.

---

## Hardware & Software Requirements

| | Minimum |
|---|---|
| Processor | Intel i5 or equivalent |
| RAM | 8 GB (16 GB for offline mode) |
| Software | Python 3.12+, Git, a modern browser |
| Internet | Needed for Gemini API and deployment; not needed in offline mode |

---

## Run Locally

```bash
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
# put your settings in .env (see below)
streamlit run app.py
```

`.env` settings:

| Setting | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Claude, the main AI model |
| `ANTHROPIC_MODEL` | Claude model (default `claude-sonnet-5-5`) |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | First fallback |
| `OLLAMA_MODEL`, `OLLAMA_HOST` | Offline fallback (local Ollama) |
| `LLM_PROVIDER` | Which provider to try first: `claude` (default), `gemini` or `ollama` |
| `ADMIN_PASSWORD` | Password of the `admin` account; leave empty to turn admin sign-in off |
| `OCR_ENABLED` | Read pages that are only images (scanned PDFs, picture slides) with Claude on upload (default `true`) |
| `SMTP_USER`, `SMTP_PASSWORD` | Email updates: the Gmail address to send from and its [app password](https://myaccount.google.com/apppasswords) (needs 2-Step Verification). Leave empty to turn email off |
| `SMTP_HOST`, `SMTP_PORT`, `APP_URL` | Optional: another mail server (default `smtp.gmail.com`, 465) and the app link used in emails |

**Email updates:** students give their email when they first sign in (results and morning reminders
are then on); they can change it or turn either off under *Email updates* on the Home page, choosing
quiz results and/or a morning study-plan email. Morning emails are sent by
`python scripts/send_reminders.py`; schedule it daily (the command for Windows Task Scheduler
is in the script). The Study Plan page also has **Add to calendar** (an .ics file).

Notes can be PDF, Word (.docx), PowerPoint (.pptx; old .ppt needs LibreOffice) or text.
Slides are cited as "file.pptx, slide N".

If a model fails, the next is tried: Claude → Gemini → lighter Gemini → Ollama. Each gets a
short timeout and at most one retry, and every failure is logged with its status code in
`data/personaai.log`.

### Accounts

1. Sign in as `admin` with `ADMIN_PASSWORD`.
2. **Students & cohorts:** import a class list CSV (`hall_ticket, name, department, year`; a sample
   is downloadable on the page). Each department + year becomes a cohort.
3. **Course notes:** add the cohort's subjects, then upload notes per subject and unit. Every
   student in the cohort sees them.
4. Under **Students**, create sign-up codes and hand them out (they are shown once). A student
   signs in with their hall ticket number and, the first time, their code plus a new password.
   **Reset password** issues a new code. Five failed sign-ins lock the account for 5 minutes.
   Students can also upload private notes of their own.
5. On **Study Plan**, a student enters their exam timetable; the plan splits each day between
   subjects by weakness and how close each exam is.

### Demo cohort

`python scripts/setup_demo_ai_cohort.py` (with the app stopped) copies `notes/` into
`notes_organized/` with clean "Subject - Unit N" names, backs up the database, creates the
**AI · Year 3** cohort with 5 demo students, and uploads every file as shared course notes.
The students' one-time sign-up codes are written to `demo_accounts/` (not in git).

Run the tests with `pytest`. The screen tests (`tests/e2e_screens.py`, `tests/e2e_demo_ai.py`,
need `playwright`) drive a running app in headless Chromium; see their docstrings.

---

## Project Status

🚧 In development.

| Milestone | Status |
|---|---|
| Project setup | ✅ |
| Feature 1: Notes Q&A | ✅ (awaiting your test) |
| Feature 2: Quiz generation | ✅ (awaiting your test) |
| Feature 3: Weak-topic memory | ✅ (awaiting your test) |
| Feature 4: Study plan | ✅ (awaiting your test) |
| Evaluation | ✅ ([report](evaluation/REPORT.md)) |
| Deployment | ⬜ |
| Documentation & demo | ⬜ |
