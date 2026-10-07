"""Simulation: adaptive quizzes vs evenly spread ("random") quizzes.

A simulated student has a hidden mastery (probability of answering correctly) for each
topic; some topics are genuinely weak. Each session they take a 10-question quiz whose
questions are allocated by PersonaAI's real code (memory.adaptive_allocation or
quiz.even_allocation), and their answers are saved and scored through the real database
(so weak-topic detection is the app's own). No LLM is involved.

Assumption (stated in the report): answering a question on a topic and reading the
explanation raises mastery of that topic by LEARNING_RATE of the remaining gap.

Measured per mode, averaged over many simulated students:
  * share of quiz questions that land on the truly weak topics,
  * sessions until the app has flagged every truly weak topic as weak at least once,
  * mean mastery of the truly weak topics after each session.

Usage:  python -m evaluation.simulate_adaptive [--students 200] [--sessions 10]
"""

import argparse
import random
import tempfile
from pathlib import Path

from core import config

HERE = Path(__file__).parent
N_TOPICS = 20
N_WEAK = 5
QUIZ_SIZE = 10
WEAK_MASTERY = (0.25, 0.45)
OTHER_MASTERY = (0.70, 0.95)
LEARNING_RATE = 0.08


def simulate_student(mode: str, sessions: int, seed: int, workdir: Path) -> dict:
    from core import db, memory, quiz

    rng = random.Random(seed)
    config.DB_PATH = workdir / f"{mode}-{seed}.db"
    db.init_db()
    uid = db.get_or_create_user("sim")["id"]
    doc = db.add_document(uid, "notes.pdf", None, 10)
    db.set_topics(uid, doc, [f"Topic {i}" for i in range(N_TOPICS)])
    tids = [t["id"] for t in db.list_topics(uid)]
    weak = set(rng.sample(tids, N_WEAK))
    mastery = {t: rng.uniform(*(WEAK_MASTERY if t in weak else OTHER_MASTERY)) for t in tids}

    on_weak, weak_mastery, detected_at = [], [], None
    ever_flagged: set[int] = set()
    random.seed(seed)  # quiz.even_allocation shuffles with the global RNG
    for s in range(1, sessions + 1):
        if mode == "adaptive":
            allocation = memory.adaptive_allocation(memory.topic_stats(uid), QUIZ_SIZE)
        else:
            allocation = quiz.even_allocation(tids, QUIZ_SIZE)
        answers = []
        for tid, n in allocation.items():
            for _ in range(n):
                ok = rng.random() < mastery[tid]
                answers.append((tid, "q", "a", "b", ok))
                mastery[tid] += LEARNING_RATE * (1 - mastery[tid])
        db.save_quiz_attempt(uid, sum(a[4] for a in answers), len(answers), answers)

        on_weak.append(sum(n for t, n in allocation.items() if t in weak) / QUIZ_SIZE)
        weak_mastery.append(sum(mastery[t] for t in weak) / len(weak))
        # A weak topic counts as detected once flagged; it may later leave the weak list
        # because the student improved on it, which is the point.
        ever_flagged |= {s.topic_id for s in memory.weak_topics(uid)}
        if detected_at is None and weak <= ever_flagged:
            detected_at = s
    return {
        "on_weak": on_weak,
        "weak_mastery": weak_mastery,
        "detected_at": detected_at,
        "flagged_share": len(weak & ever_flagged) / len(weak),
    }


def run(students: int, sessions: int) -> dict:
    results = {}
    with tempfile.TemporaryDirectory() as tmp:
        for mode in ("adaptive", "even"):
            runs = [simulate_student(mode, sessions, seed, Path(tmp)) for seed in range(students)]
            detected = [r["detected_at"] for r in runs if r["detected_at"] is not None]
            results[mode] = {
                "on_weak": [sum(r["on_weak"][s] for r in runs) / students for s in range(sessions)],
                "weak_mastery": [sum(r["weak_mastery"][s] for r in runs) / students for s in range(sessions)],
                "detected_share": len(detected) / students,
                "flagged_share": sum(r["flagged_share"] for r in runs) / students,
                "detected_mean": sum(detected) / len(detected) if detected else None,
            }
    return results


def write_report(results: dict, students: int, sessions: int, out: Path) -> None:
    a, e = results["adaptive"], results["even"]
    expected_even = N_WEAK / N_TOPICS
    start = sum(WEAK_MASTERY) / 2
    lines = [
        "# Simulation: adaptive vs evenly spread quizzes",
        "",
        "**This is a simulation, not a study with real students.** It shows how PersonaAI's "
        "real allocation and scoring code behaves for a simulated student.",
        "",
        f"- {students} simulated students × {sessions} quizzes of {QUIZ_SIZE} questions, per mode",
        f"- {N_TOPICS} topics, {N_WEAK} genuinely weak (hidden mastery {WEAK_MASTERY[0]:.0%}–"
        f"{WEAK_MASTERY[1]:.0%}; others {OTHER_MASTERY[0]:.0%}–{OTHER_MASTERY[1]:.0%})",
        f"- Assumption: each question answered on a topic (with its explanation) closes "
        f"{LEARNING_RATE:.0%} of the gap to full mastery of that topic",
        "",
        "| Measure | Adaptive | Even mix |",
        "|---|---|---|",
        f"| Questions on truly weak topics (sessions 4–{sessions}) | "
        f"{sum(a['on_weak'][3:]) / len(a['on_weak'][3:]):.0%} | {sum(e['on_weak'][3:]) / len(e['on_weak'][3:]):.0%} |",
        f"| Truly weak topics flagged as weak at least once within {sessions} quizzes | "
        f"{a['flagged_share']:.0%} | {e['flagged_share']:.0%} |",
        f"| Students whose weak topics were all flagged within {sessions} quizzes | "
        f"{a['detected_share']:.0%} | {e['detected_share']:.0%} |",
        f"| Quizzes needed to flag all weak topics (mean, when flagged) | "
        f"{a['detected_mean']:.1f} | {e['detected_mean']:.1f} |" if a["detected_mean"] and e["detected_mean"]
        else f"| Quizzes needed to detect all weak topics | {a['detected_mean']} | {e['detected_mean']} |",
        f"| Mean mastery of weak topics after {sessions} quizzes (started ~{start:.0%}) | "
        f"{a['weak_mastery'][-1]:.0%} | {e['weak_mastery'][-1]:.0%} |",
        "",
        f"With an even mix, about {expected_even:.0%} of questions hit the weak topics by chance "
        f"({N_WEAK} of {N_TOPICS} topics). In the first quizzes adaptive mode has no weak topics "
        "to target yet and favours untested topics; once topics have 3+ answers it shifts ~60% "
        "of each quiz onto the ones it has flagged.",
        "",
        "Detection is noisy by design: a topic is judged after only 3 answers, so a weak topic "
        "(~40% per question) still scores 2/3 about a third of the time and is not flagged then; "
        "and as the student improves on a topic it can leave the weak range before it is flagged. "
        "Raising the minimum answers would make flags more reliable but slower.",
        "",
        "![Weak-topic mastery per quiz](adaptive_simulation.png)",
    ]
    (out / "adaptive_simulation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    note = write_chart(results, out)
    print("\n".join(lines[8:16]))
    print(f"\nReport: {out / 'adaptive_simulation.md'}" + (f"\n{note}" if note else ""))


def write_chart(results: dict, out: Path) -> str | None:
    try:
        import altair as alt
        import pandas as pd
        import vl_convert as vlc
    except ImportError:
        return "Chart skipped: install dev requirements (pip install -r requirements-dev.txt)."
    label = {"adaptive": "Adaptive", "even": "Even mix"}
    colors = ["#2a78d6", "#eb6834"]  # categorical slots 1-2 (dataviz reference palette)
    df = pd.DataFrame(
        {"Quiz": s + 1, "Mode": label[m], "Mastery": v}
        for m in ("adaptive", "even") for s, v in enumerate(results[m]["weak_mastery"])
    )
    scale = alt.Scale(domain=list(label.values()), range=colors)
    lines = alt.Chart(df).mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=64, filled=True)).encode(
        x=alt.X("Quiz:O", axis=alt.Axis(labelAngle=0, title="Quiz number")),
        y=alt.Y("Mastery:Q", scale=alt.Scale(domain=[0, 1]), axis=alt.Axis(format="%", title=None)),
        color=alt.Color("Mode:N", scale=scale, legend=alt.Legend(orient="top", title=None)),
    )
    last = df[df["Quiz"] == df["Quiz"].max()]
    labels = alt.Chart(last).mark_text(align="left", dx=8, fontSize=12, color="#0b0b0b").encode(
        x="Quiz:O", y="Mastery:Q", text=alt.Text("label:N"),
    ).transform_calculate(label="datum.Mode + ' ' + format(datum.Mastery, '.0%')")
    chart = (lines + labels).properties(
        width=520, height=260, title="Mean mastery of the truly weak topics (simulated)"
    ).configure(background="#fcfcfb").configure_view(stroke=None)
    (out / "adaptive_simulation.png").write_bytes(vlc.vegalite_to_png(chart.to_json(), scale=2))
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--students", type=int, default=200)
    parser.add_argument("--sessions", type=int, default=10)
    parser.add_argument("--out", type=Path, default=HERE / "results")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    results = run(args.students, args.sessions)
    write_report(results, args.students, args.sessions, args.out)


if __name__ == "__main__":
    main()
