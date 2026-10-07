# PersonaAI: Implementation Plan

Build plan for PersonaAI. See [README.md](README.md) for features and deliverables.

**How we work:** one phase at a time. Each phase ends with a working app you can test. We only move on when that phase's "Done when" checks pass.

---

## Project Structure

```
PersonaAI/
├── app.py                  # Streamlit entry point (login + navigation)
├── pages/
│   ├── 1_Notes_QA.py       # Upload documents + ask questions
│   ├── 2_Quiz.py           # Generate and take quizzes
│   ├── 3_Progress.py       # Weak-topic dashboard
│   └── 4_Study_Plan.py     # Exam study plan
├── core/
│   ├── config.py           # Loads settings from .env
│   ├── llm.py              # One interface for Gemini / Ollama
│   ├── documents.py        # PDF/DOCX/TXT extraction + chunking
│   ├── vectorstore.py      # ChromaDB: embed, store, retrieve
│   ├── rag.py              # Question → retrieve → answer with citations
│   ├── quiz.py             # Quiz generation + grading
│   ├── memory.py           # Topic scores, weak-topic detection
│   ├── planner.py          # Study plan generation
│   └── db.py               # SQLite schema + queries
├── evaluation/
│   ├── questions.csv       # Your exam questions + correct answers
│   └── run_eval.py         # RAG vs no-RAG accuracy test
├── data/                   # Uploaded files, ChromaDB, SQLite (git-ignored)
├── tests/                  # Unit tests for core modules
├── .env                    # Your API keys (git-ignored, never committed)
├── requirements.txt
├── README.md
└── IMPLEMENTATION.md
```

---

## Database Schema (SQLite)

| Table | Columns |
|---|---|
| `users` | id, username, created_at |
| `documents` | id, user_id, filename, subject, page_count, uploaded_at |
| `topics` | id, user_id, document_id, name |
| `quiz_attempts` | id, user_id, created_at, score, total |
| `quiz_answers` | id, attempt_id, topic_id, question, chosen, correct, is_correct |
| `topic_scores` | user_id, topic_id, attempts, correct, accuracy, last_seen |
| `study_plans` | id, user_id, exam_date, hours_per_day, plan_json, created_at |

---

## Phase 0: Setup (Day 1)

- [x] Create Python virtual environment (`.venv`)
- [x] `requirements.txt`: streamlit, chromadb, sentence-transformers, pypdf, python-docx, google-genai, ollama, python-dotenv, pandas
- [x] `.gitignore` (`.env`, `.venv`, `data/`)
- [x] `core/config.py` loads `.env`
- [x] `core/llm.py` with a test call to Gemini (and Ollama fallback)
- [x] Git init + first commit
- [x] Basic `app.py` with username login

**Done when:** `streamlit run app.py` opens in the browser, you can enter a username, and a test LLM call returns a reply.

---

## Phase 1: Notes Q&A with Citations (Days 2–3)

- [x] Upload PDF/DOCX/TXT (multiple files)
- [x] Extract text page by page; chunk into ~180-word pieces with 40-word overlap *(changed from ~500 tokens: all-MiniLM-L6-v2 only reads 256 tokens, so longer chunks were silently truncated)*
- [x] Strip repeated page headers/footers; re-extract "one word per line" PDFs in layout mode
- [x] Embed chunks locally (sentence-transformers `all-MiniLM-L6-v2`) and store them in ChromaDB, tagged with user, file, and page
- [x] Extract a topic list from each document (LLM) and save it to `topics`; user can edit it
- [x] Chat interface: retrieve 20 candidates, rerank with a cross-encoder (`ms-marco-MiniLM-L-6-v2`), the LLM answers **only from the top 5** *(reranker added: without it, "What is Apache Pig?" ranked the defining chunk 8th and got "not found")*
- [x] Show citations (file name + page) under each answer
- [x] Reply "not found in your notes" when retrieval finds nothing relevant (reranker score cutoff + LLM `NOT_FOUND`)

**Done when:** you upload your notes, ask 5 questions, and get correct answers with correct page citations, and an off-syllabus question gets "not found".

---

## Phase 2: Quiz Generation (Days 4–5)

- [ ] Choose a document/topic and number of questions (5/10/15)
- [ ] LLM generates MCQs as structured JSON (question, 4 options, answer, explanation, topic)
- [ ] Validate the JSON; regenerate if it's malformed
- [ ] Quiz UI: answer all questions, then submit
- [ ] Show score, correct answers, and explanations
- [ ] Save every answer to `quiz_answers` with its topic

**Done when:** you generate a 10-question quiz from your notes, the questions match the material, and your results are saved.

---

## Phase 3: Weak-Topic Memory + Dashboard (Days 6–7)

- [ ] Update `topic_scores` after every quiz
- [ ] Weak topic = accuracy < 60% with at least 3 attempts; strong = ≥ 80%
- [ ] "Adaptive quiz" mode: ~60% of questions come from weak topics
- [ ] Progress page: per-topic accuracy bar chart, weak/strong lists, quiz history over time
- [ ] Q&A assistant mentions related weak topics when relevant

**Done when:** after 3–4 quizzes, the dashboard shows your weak topics correctly and an adaptive quiz focuses on them.

---

## Phase 4: Study Plan (Day 8)

- [ ] Inputs: exam date, hours per day, documents/subjects to cover
- [ ] Plan generator: covers all topics, gives weak topics extra time, and schedules revision + mock-quiz days before the exam
- [ ] Display as a day-by-day table; mark days complete
- [ ] "Regenerate" updates the plan using the latest topic scores

**Done when:** a plan for an exam 14 days away covers every topic, weights weak ones, and changes after you improve on a topic.

---

## Phase 5: Evaluation (Days 9–10)

- [ ] You provide `evaluation/questions.csv`: 15–30 questions with correct answers from your syllabus
- [ ] `run_eval.py` answers each question **with RAG** and **without RAG** (plain LLM)
- [ ] An LLM judge plus your manual check scores each answer as correct / partially correct / wrong
- [ ] Output: accuracy table + chart for the report
- [ ] Optional: adaptive vs random quiz comparison over several sessions

**Done when:** you have a results table showing RAG vs no-RAG accuracy on your own questions.

---

## Phase 6: Polish + Deployment (Days 11–12)

- [ ] Error handling: bad files, empty uploads, API failures, rate limits
- [ ] Offline mode: switch to Ollama with one setting
- [ ] UI cleanup: consistent layout, loading spinners, helpful empty states
- [ ] Unit tests for chunking, retrieval, quiz validation, score updates
- [ ] Push to GitHub
- [ ] Deploy on Streamlit Community Cloud (API key added as a secret there, not in code)

**Done when:** the public link works on a fresh browser and on your phone.

---

## Phase 7: Documentation + Demo (Days 13–15)

- [ ] Technical documentation: architecture, schema, module descriptions
- [ ] User guide with screenshots
- [ ] Final README update with setup steps + live link
- [ ] Demo video script (3–5 min); you record it
- [ ] Viva prep notes: how RAG, embeddings, chunking, and weak-topic scoring work

---

## Risks

| Risk | Mitigation |
|---|---|
| Gemini free-tier rate limits | Cache answers; retry with backoff; Ollama fallback |
| Scanned/messy PDFs | Use text-based PDFs; OCR only if needed later |
| LLM returns invalid quiz JSON | Structured output + validation + auto-retry |
| Wrong topic extraction | Let user edit the topic list after upload |
| Streamlit Cloud resets local data | Acceptable for demo; note it as a limitation (or move to a hosted DB if required) |
| Internet down on demo day | Run locally with Ollama |

---

## What I Need From You

| When | What |
|---|---|
| Before Phase 0 | Gemini API key in `.env` |
| Before Phase 1 | 2–3 text-based PDFs from one subject |
| After each phase | 15 min of testing + feedback |
| Before Phase 5 | 15–30 exam questions with correct answers |
| Phase 6 | GitHub + Streamlit Cloud login |
| Phase 7 | Record the demo video |
