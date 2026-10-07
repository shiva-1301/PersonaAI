"""RAG vs no-RAG evaluation.

For every question in evaluation/questions.csv:
  * "With notes" (RAG): PersonaAI's real Q&A pipeline over an index of ONLY the course
    notes (by default the Unit III and Unit IV PDFs, never the Q&A PDF the questions
    came from).
  * "Without notes": the same model answers from its general knowledge.
  * An LLM judge compares each answer with the reference answer: correct / partial /
    wrong. The two answers are shown to the judge as "Answer 1/2" in random order, so
    it can't tell which is which.

One model is pinned for the whole run (no fallback), and each finished question is
saved immediately, so a run stopped by a quota limit resumes where it left off.
You can override any verdict by filling the manual_rag / manual_no_rag columns in
results.csv, then re-run with --report to rebuild the summary.

Usage:
    python -m evaluation.run_eval                      # run (or resume) + report
    python -m evaluation.run_eval --limit 5            # first 5 questions only
    python -m evaluation.run_eval --report             # rebuild report from results.csv
    python -m evaluation.run_eval --model gemini-3.8-flash --out evaluation/results-38
"""

import argparse
import csv
import json
import random
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from core import config

HERE = Path(__file__).parent
DEFAULT_DOCS = [Path("data/uploads/BIG_DATA_UNIT-III.pdf"), Path("data/uploads/BIG_DATA_UNIT-4.pdf")]
VERDICTS = ("correct", "partial", "wrong")
FIELDS = [
    "id", "unit", "question", "reference_answer",
    "rag_answer", "rag_sources", "rag_verdict", "rag_reason",
    "no_rag_answer", "no_rag_verdict", "no_rag_reason",
    "model", "judge_model", "retrieval", "answered_at", "manual_rag", "manual_no_rag",
]

NO_RAG_SYSTEM = """You are a study assistant for a university Big Data course.
Answer the exam question from your own knowledge. Write the way a good exam answer reads:
a one-line definition or direct answer first, then key points as bullets, and a short
example if useful. Keep it concise."""

JUDGE_PROMPT = """You are grading answers to a university exam question against the
reference answer from the course material.

Question: {question}

Reference answer: {reference}

Answer 1:
{answer1}

Answer 2:
{answer2}

Grade each answer on its own:
- "correct": covers the main points of the reference answer and states nothing that
  contradicts it. Extra correct detail is fine.
- "partial": gets some main points, or is mostly right with a notable error or omission.
- "wrong": misses the main points, contradicts the reference, or doesn't answer.

Return JSON: {{"answer1": {{"verdict": "...", "reason": "one sentence"}},
"answer2": {{"verdict": "...", "reason": "one sentence"}}}}"""


class QuotaStop(Exception):
    """The pinned model stopped answering (quota, outage); results so far are saved."""


def setup(model: str, cache: Path) -> None:
    """Isolated storage + one pinned model for the whole run."""
    cache.mkdir(parents=True, exist_ok=True)
    config.DB_PATH = cache / "eval.db"
    config.CHROMA_DIR = cache / "chroma"
    config.UPLOADS_DIR = cache / "uploads"
    config.LLM_FALLBACK = False
    if model.startswith("gemini"):
        config.LLM_PROVIDER, config.GEMINI_MODEL = "gemini", model
    else:
        config.LLM_PROVIDER, config.OLLAMA_MODEL = "ollama", model


def build_index(docs: list[Path]) -> int:
    """Index the notes for a dedicated eval user (no topic extraction: no LLM calls)."""
    from core import db, vectorstore
    from core.documents import chunk_pages, extract_pages

    db.init_db()
    user_id = db.get_or_create_user("evaluation")["id"]
    have = {d["filename"] for d in db.list_documents(user_id)}
    for path in docs:
        if path.name in have:
            continue
        pages = extract_pages(path.name, path.read_bytes())
        doc_id = db.add_document(user_id, path.name, "evaluation", len(pages))
        vectorstore.add_chunks(user_id, doc_id, path.name, chunk_pages(pages))
        print(f"Indexed {path.name}: {len(pages)} pages")
    return user_id


def load_rows(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as f:
        return {row["id"]: row for row in csv.DictReader(f)}


def write_rows(path: Path, rows: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for row in sorted(rows.values(), key=lambda r: int(r["id"])):
            writer.writerow({k: row.get(k, "") for k in FIELDS})
    tmp.replace(path)


def evaluate_one(user_id: int, q: dict, previous: dict | None = None) -> dict:
    """Answer with and without notes, then judge. With `previous` (--rerun-rag), the
    saved no-notes answer is reused and only the notes side is re-answered."""
    from core import llm, rag

    try:
        with_notes = rag.answer(user_id, q["question"])
        if previous:
            no_rag_text, model = previous["no_rag_answer"], previous["model"]
        else:
            no_rag_text, model = llm.generate_with_model(q["question"], system=NO_RAG_SYSTEM)
    except llm.LLMError as exc:
        raise QuotaStop(str(exc)[:300]) from exc

    row = {
        **{k: q[k] for k in ("id", "unit", "question")},
        "reference_answer": q["reference_answer"],
        "rag_answer": with_notes.text,
        "rag_sources": "; ".join(s.label for s in with_notes.sources),
        "no_rag_answer": no_rag_text,
        "model": model,
        "retrieval": rag.RETRIEVAL,
        "answered_at": datetime.now().isoformat(timespec="seconds"),
    }
    verdicts = judge(q, with_notes.text if with_notes.found else None, no_rag_text)
    row.update(verdicts)
    return row


def judge(q: dict, rag_text: str | None, no_rag_text: str) -> dict:
    """Blind, order-randomised grading of both answers in one call. A RAG answer of
    "not found" is graded wrong without asking the judge."""
    from core import llm

    rag_shown = rag_text if rag_text is not None else "I couldn't find this in the notes."
    pair = [("rag", rag_shown), ("no_rag", no_rag_text)]
    random.shuffle(pair)
    prompt = JUDGE_PROMPT.format(
        question=q["question"], reference=q["reference_answer"],
        answer1=pair[0][1], answer2=pair[1][1],
    )
    try:
        reply, judge_model = llm.generate_with_model(prompt, json_mode=True, temperature=0)
    except llm.LLMError as exc:
        raise QuotaStop(str(exc)[:300]) from exc
    data = json.loads(re.sub(r"^```(?:json)?|```$", "", reply.strip(), flags=re.M).strip())

    out = {"judge_model": judge_model}
    for slot, (name, _) in zip(("answer1", "answer2"), pair):
        item = data.get(slot) or {}
        verdict = str(item.get("verdict", "")).lower().strip()
        out[f"{name}_verdict"] = verdict if verdict in VERDICTS else "wrong"
        out[f"{name}_reason"] = str(item.get("reason", "")).strip()
    if rag_text is None:
        out["rag_verdict"], out["rag_reason"] = "wrong", "Abstained: answer not found in the notes."
    return out


# --- Report ---

def final_verdicts(row: dict, condition: str) -> str:
    manual = row.get(f"manual_{condition}", "").strip().lower()
    return manual if manual in VERDICTS else row[f"{condition}_verdict"]


def summarize(rows: list[dict]) -> dict:
    summary = {}
    for condition in ("rag", "no_rag"):
        counts = Counter(final_verdicts(r, condition) for r in rows)
        n = len(rows)
        summary[condition] = {
            **{v: counts.get(v, 0) for v in VERDICTS},
            "n": n,
            "accuracy": counts.get("correct", 0) / n if n else 0,
            # partial answers count half
            "score": (counts.get("correct", 0) + 0.5 * counts.get("partial", 0)) / n if n else 0,
        }
    summary["abstained"] = sum(r["rag_reason"].startswith("Abstained") for r in rows)
    answered = [r for r in rows if not r["rag_reason"].startswith("Abstained")]
    summary["rag_answered_accuracy"] = (
        sum(final_verdicts(r, "rag") == "correct" for r in answered) / len(answered) if answered else 0
    )
    summary["manual_overrides"] = sum(
        bool(r.get("manual_rag", "").strip()) + bool(r.get("manual_no_rag", "").strip()) for r in rows
    )
    return summary


def write_report(out: Path, rows: list[dict], docs: list[Path]) -> None:
    s = summarize(rows)
    models = sorted({r["model"] for r in rows})
    judges = sorted({r["judge_model"] for r in rows})
    label = {"rag": "With notes (RAG)", "no_rag": "Without notes"}
    lines = [
        "# Evaluation: answer accuracy with vs without the student's notes",
        "",
        f"- Questions: {len(rows)} (from `evaluation/questions.csv`)",
        f"- Notes indexed for RAG: {', '.join(p.name for p in docs)}",
        f"- Answer model: {', '.join(models)}; judge: {', '.join(judges)} (blind, order randomised)",
        f"- Retrieval: {', '.join(sorted({r.get('retrieval') or 'embedding -> cross-encoder' for r in rows}))}",
        f"- Manual overrides applied: {s['manual_overrides']}",
        "",
        "| Condition | Correct | Partial | Wrong | Accuracy | Score (partial = ½) |",
        "|---|---|---|---|---|---|",
    ]
    for c in ("rag", "no_rag"):
        x = s[c]
        lines.append(
            f"| {label[c]} | {x['correct']} | {x['partial']} | {x['wrong']} "
            f"| {x['accuracy']:.0%} | {x['score']:.0%} |"
        )
    lines += [
        "",
        f"RAG abstained (\"not found in your notes\") on {s['abstained']} question(s); "
        "these count as wrong. When it did answer, "
        f"{s['rag_answered_accuracy']:.0%} of its answers were correct.",
        "",
        "![Results](chart.png)",
        "",
        "## Per unit",
        "",
        "| Unit | Questions | RAG accuracy | No-RAG accuracy |",
        "|---|---|---|---|",
    ]
    for unit in sorted({r["unit"] for r in rows}):
        sub = summarize([r for r in rows if r["unit"] == unit])
        lines.append(
            f"| {unit} | {sub['rag']['n']} | {sub['rag']['accuracy']:.0%} | {sub['no_rag']['accuracy']:.0%} |"
        )
    lines += ["", "## Questions where the two conditions disagree", ""]
    for r in rows:
        a, b = final_verdicts(r, "rag"), final_verdicts(r, "no_rag")
        if a != b:
            lines.append(f"- Q{r['id']} *{r['question']}* — RAG: **{a}**, no-RAG: **{b}**. {r['no_rag_reason'] if a == 'correct' else r['rag_reason']}")
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    chart_note = write_chart(out, s)
    table_start = next(i for i, line in enumerate(lines) if line.startswith("| Condition"))
    print("\n".join(lines[table_start : table_start + 4]))
    print(f"\nReport: {out / 'summary.md'}" + (f"\n{chart_note}" if chart_note else ""))


def write_chart(out: Path, s: dict) -> str | None:
    """100%-stacked bars, one per condition, in the status colours (each segment also
    carries a text label, so colour is never the only cue)."""
    try:
        import altair as alt
        import pandas as pd
        import vl_convert as vlc
    except ImportError:
        return "Chart skipped: install dev requirements (pip install -r requirements-dev.txt)."
    colors = {"correct": "#0ca30c", "partial": "#fab219", "wrong": "#d03b3b"}
    label = {"rag": "With notes (RAG)", "no_rag": "Without notes"}
    df = pd.DataFrame(
        [
            {"Condition": label[c], "Verdict": v.capitalize(), "Count": s[c][v],
             "Order": i, "Share": s[c][v] / s[c]["n"] if s[c]["n"] else 0}
            for c in ("rag", "no_rag") for i, v in enumerate(VERDICTS)
        ]
    )
    base = alt.Chart(df).encode(
        y=alt.Y("Condition:N", title=None, sort=[label["rag"], label["no_rag"]]),
        x=alt.X("Share:Q", stack="normalize", axis=alt.Axis(format="%", title=None)),
        order=alt.Order("Order:Q"),
    )
    bars = base.mark_bar(stroke="#fcfcfb", strokeWidth=2, size=34).encode(
        color=alt.Color(
            "Verdict:N",
            scale=alt.Scale(domain=["Correct", "Partial", "Wrong"], range=list(colors.values())),
            legend=alt.Legend(orient="top", title=None),
        )
    )
    text = base.transform_filter("datum.Count > 0").mark_text(
        align="right", dx=-6, color="#0b0b0b", fontSize=12
    ).encode(
        x=alt.X("Share:Q", stack="normalize"),
        text=alt.Text("label:N"),
    ).transform_calculate(label="datum.Verdict + ' ' + datum.Count")
    chart = (bars + text).properties(
        width=560, height=120, title="Answer accuracy on 30 exam questions"
    ).configure(background="#fcfcfb").configure_view(stroke=None)
    (out / "chart.png").write_bytes(vlc.vegalite_to_png(chart.to_json(), scale=2))
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--questions", type=Path, default=HERE / "questions.csv")
    parser.add_argument("--docs", type=Path, nargs="+", default=DEFAULT_DOCS)
    parser.add_argument("--model", default="gemini-3.5-flash-lite")
    parser.add_argument("--out", type=Path, default=HERE / "results")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--report", action="store_true", help="only rebuild the report")
    parser.add_argument(
        "--rerun-rag", action="store_true",
        help="re-answer the with-notes side for rows made by an older retrieval, reusing "
        "their saved without-notes answers",
    )
    args = parser.parse_args()

    results_path = args.out / "results.csv"
    rows = load_rows(results_path)
    with args.questions.open(encoding="utf-8", newline="") as f:
        questions = list(csv.DictReader(f))[: args.limit]

    stopped = None
    if not args.report:
        setup(args.model, HERE / ".cache")
        user_id = build_index(args.docs)
        from core import rag
        rag.warm_up()

        def pending(q):
            row = rows.get(q["id"], {})
            if not row.get("no_rag_verdict"):
                return True
            return args.rerun_rag and row.get("retrieval") != rag.RETRIEVAL

        todo = [q for q in questions if pending(q)]
        print(f"{len(questions) - len(todo)} done, {len(todo)} to go (model: {args.model})")
        for i, q in enumerate(todo, 1):
            try:
                previous = rows.get(q["id"]) if args.rerun_rag and rows.get(q["id"], {}).get("no_rag_answer") else None
                rows[q["id"]] = {**rows.get(q["id"], {}), **evaluate_one(user_id, q, previous)}
            except QuotaStop as exc:
                stopped = exc
                break
            write_rows(results_path, rows)
            r = rows[q["id"]]
            print(f"[{i}/{len(todo)}] Q{q['id']}: RAG {r['rag_verdict']}, no-RAG {r['no_rag_verdict']}")

    done = [rows[q["id"]] for q in questions if rows.get(q["id"], {}).get("no_rag_verdict")]
    if done:
        write_report(args.out, done, args.docs)
    if stopped:
        print(f"\nStopped early ({stopped}).\nResults so far are saved; run the same command again later to resume.")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
