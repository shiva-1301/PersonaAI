# PersonaAI Evaluation Report

Two questions from the project brief:

1. **Does answering from the student's notes (RAG) beat a plain LLM on real exam questions?**
2. **Do quizzes that target weak topics beat randomly spread quizzes?**

All numbers below come from files in `evaluation/results/`; each can be regenerated with the commands at the end.

---

## 1. Answer accuracy: with notes (RAG) vs without notes

### Method

| | |
|---|---|
| **Questions** | 60 short exam questions with model answers, from *BD MID 2 SHORTS.pdf* (30 for Unit III, 30 for Unit IV), split into a **development set** (odd-numbered, 30) and a **held-out set** (even-numbered, 30). |
| **Notes used by RAG** | *BIG_DATA_UNIT-III.pdf* and *BIG_DATA_UNIT-4.pdf* only. The Q&A PDF the questions came from is **not** indexed, so RAG can't copy the reference answers. |
| **With notes (RAG)** | PersonaAI's real Q&A pipeline: embedding search (top 20) → cross-encoder rerank → top 5 excerpts → the LLM answers only from them, or says "not found". |
| **Without notes** | The same LLM answers from general knowledge, with the same exam-style instructions. |
| **Model** | `gemini-3.5-flash-lite` for every answer, fixed for the whole run (no fallback to other models). |
| **Grading** | An LLM judge (same model, temperature 0) grades each answer against the reference: *correct* / *partial* / *wrong*. Both answers are shown as "Answer 1 / Answer 2" in random order, so the judge can't tell which is RAG. A "not found" answer counts as wrong. |
| **Manual check** | `results.csv` has `manual_rag` / `manual_no_rag` columns; any verdict typed there overrides the judge (`--report` rebuilds the summary). No overrides have been applied yet. |

The development set was used to look for problems and try fixes; the held-out set was run once, on the final pipeline, so its score is not inflated by tuning.

### Results

| Set | Condition | Correct | Partial | Wrong | Accuracy |
|---|---|---|---|---|---|
| Development (30) | **With notes (RAG)** | 26 | 1 | 3 | **87%** |
| | Without notes | 29 | 1 | 0 | **97%** |
| Held-out (30) | **With notes (RAG)** | 25 | 5 | 0 | **83%** |
| | Without notes | 30 | 0 | 0 | **100%** |
| **All 60** | **With notes (RAG)** | 51 | 6 | 3 | **85%** |
| | Without notes | 59 | 1 | 0 | **98%** |

![Held-out results](results/holdout/chart.png)

**On these questions, the plain LLM was more accurate than RAG.** This is the opposite of the expected result, and the reasons matter more than the headline:

- **RAG was almost never factually wrong.** Across 60 questions it gave 0 wrong answers; all 3 "wrong" verdicts are cases where it said *"not found in your notes"*. When it did answer, 96% (development) and 83% (held-out) of answers were fully correct, and the rest were partial.
- **The questions are general knowledge for the model.** "What is Apache Hive?" or "What is bucketing?" are covered extensively in the model's training data, so the no-notes answers are complete. RAG can only say what the retrieved excerpts say.
- **RAG's misses are retrieval misses**, not answer-writing mistakes (failure analysis below).
- **Where notes add something specific, RAG wins**: e.g. *"What are the benefits of using schemas?"* — RAG gave the course's exact points (fields referenced by name); the plain LLM gave generic database benefits and was graded partial.

What this evaluation does **not** measure: whether answers match *how the course teaches a topic* (terminology, examples, the lecturer's emphasis), and citations. RAG answers carry a file and page for every claim; plain answers can't be checked against the notes. A question set built from material that is *not* general knowledge (lecturer-specific examples, definitions that differ from the textbook) would be a fairer test of that value.

### Failure analysis

| Question | Verdict | Cause |
|---|---|---|
| What is a Map in Pig? | not found | The defining line ("Map: collection of key-value pairs…") sits in a bullet list that never says "Pig"; embedding search ranks it 16th because "Map" pulls in *MapReduce* chunks. |
| What are conditional functions in Hive? | not found | The IF/CASE text is in one chunk that embedding search didn't return at all (keyword search found it 2nd in the experiment below, but the reranker then ranked it 12th). |
| What is a Subquery in Hive? | not found | The notes define it in a summary table ("nested queries in WHERE, FROM, SELECT"); a chunk that only *mentions* subqueries ranked above it. |
| How can data be imported into Hive? | partial | "Import" retrieved the *Sqoop import* pages instead of Hive's `LOAD DATA` section. |
| What is Bucketing in Hive? | partial | The chunk boundary cut the `CREATE TABLE … CLUSTERED BY` example in half. |
| What are UDFs / relational operators in Hive? | partial | The retrieved excerpts list fewer items (no UDAF/UDTF; no LIKE/RLIKE/IN) than the reference answer. |

The common cause is **chunks that lose their context**: a chunk is ~180 words cut from the middle of a section, so it doesn't contain the section heading ("Pig Latin – Data Types", "Hive – Importing Data") that would connect it to the question.

### Experiment: adding keyword (BM25) search — not adopted

Because exact terms like *Map* were being confused with *MapReduce*, keyword search was added alongside embedding search (`dev_v2`). It did put the missing chunks into the candidate list, but the cross-encoder still ranked them low, so the same 3 questions failed:

| Development set | RAG correct | No-RAG correct |
|---|---|---|
| Embedding → rerank (final) | 26 | 29 |
| Embedding + BM25 → rerank | 25 | 27 |

A retrieval-only check (does a chunk covering ≥ 50% of the reference answer reach the LLM?) gave 27/30 for both, and 28/30 with a larger reranker (`ms-marco-MiniLM-L-12-v2`) — a one-question difference. With no measurable gain, the change was reverted to keep the pipeline simple.

### How reliable are these numbers?

- **Judge noise is about ±2 questions.** In `dev_v2` the *unchanged* no-notes answers were re-judged and scored 27 correct instead of 29. Differences of 1–2 questions (≈ 3–7 points) between runs are not meaningful.
- **The RAG vs no-RAG gap is larger than that** (51 vs 59 correct over 60), so the direction of the result is reliable for this question set.
- The judge is the same model that wrote the answers. Grading is against a written reference answer and blind to which answer is which, which limits self-preference, but a manual check of the verdicts (columns provided) would strengthen the report.

### Recommended improvements (future work)

1. **Section headings in chunks** — prefix each chunk with the heading it belongs to, so "Map: key-value pairs" is stored as "Pig Latin Data Types › Map: …". Directly targets the main failure cause.
2. **Chunk on section boundaries** instead of fixed word windows, so examples aren't cut in half.
3. **A stronger reranker**, if deployment memory allows.
4. **Optional "notes first, then general knowledge" answers**, clearly labelled, for questions the notes don't fully cover. (This would relax the current rule that answers come only from the notes, so it is a product decision.)

---

## 2. Adaptive vs evenly spread quizzes (simulation)

**This is a simulation, not a study with real students** — a real comparison would need many students over weeks. It runs PersonaAI's real quiz-allocation and weak-topic scoring code for simulated students. Full details: [results/adaptive_simulation.md](results/adaptive_simulation.md).

**Setup:** 200 simulated students per mode; 20 topics, 5 of them genuinely weak (hidden chance of a correct answer 25–45%; others 70–95%); 10 quizzes of 10 questions. Assumption: answering a question on a topic (and reading its explanation) closes 8% of the gap to full mastery of that topic.

| Measure | Adaptive | Even mix |
|---|---|---|
| Questions on the truly weak topics (quizzes 4–10) | **55%** | 25% |
| Weak topics flagged as weak at least once | 73% | 70% |
| Mean mastery of weak topics after 10 quizzes (start ≈ 35%) | **68%** | 55% |

![Simulated mastery of weak topics](results/adaptive_simulation.png)

- **Adaptive mode spends more than twice as much practice on the weak topics** once they have been identified, and under the learning assumption this lifts weak-topic mastery by about 13 points more than an even mix after 10 quizzes.
- **It does not find weak topics faster.** Both modes flag about 70% of truly weak topics within 10 quizzes. Detection is noisy because a topic is judged after only 3 answers: a weak topic still scores 2/3 by chance about a third of the time.
- The size of the mastery gain depends on the assumed learning rate; the *share of questions on weak topics* does not.

---

## Reproducing

```bash
pip install -r requirements-dev.txt
python -m evaluation.build_questions                     # questions.csv + questions_holdout.csv
python -m evaluation.run_eval --out evaluation/results/dev_v1
python -m evaluation.run_eval --questions evaluation/questions_holdout.csv --out evaluation/results/holdout
python -m evaluation.run_eval --report --out evaluation/results/holdout   # after manual overrides
python -m evaluation.simulate_adaptive --students 200
```

A run stopped by the API rate limit resumes where it left off when the same command is run again. Free-tier note: `gemini-3.5-flash-lite` allows 15 requests/minute; the runner waits these out automatically.
