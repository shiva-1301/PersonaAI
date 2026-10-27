"""Generate and take quizzes: setup -> one question at a time -> results."""

from html import escape

import streamlit as st

from core import db, memory, quiz
from ui.shell import load_models, require_login
from ui.styles import Stat, badge, callout, card, chips, html, page_header, row, section, stat_row

user_id = require_login()
load_models()

page_header("Quiz", "Multiple-choice questions written from your notes. Every answer is saved per topic.")

# st.session_state.active_quiz = {
#     "questions": [...], "answers": [index | None per question], "current": int,
#     "result": Result | None, "chosen": [...] (answers at submission)}
state = st.session_state.get("active_quiz")


def start(questions: list[quiz.Question]) -> None:
    st.session_state.active_quiz = {
        "questions": questions, "answers": [None] * len(questions), "current": 0,
        "result": None, "chosen": [],
    }


# ---------------------------------------------------------------- setup

def setup() -> None:
    documents = db.list_documents(user_id)
    topics = db.list_topics(user_id)
    if not documents:
        callout("Upload your notes on the Notes Q&A page first.", "blue", "👉")
        return
    if not topics:
        callout("Your documents have no topics yet. Add them on the Notes Q&A page.", "blue", "👉")
        return

    left, right = st.columns([1.8, 1], gap="large")
    with left, card("setup"):
        section("Create a quiz", "Pick chapters, how many questions, and how to choose them.")
        subjects = sorted({d["subject_name"] for d in documents if d["subject_name"]}, key=str.lower)
        c0, c1 = st.columns([1, 2.2])
        subject = c0.selectbox("Subject", ["All subjects", *subjects]) if subjects else "All subjects"
        in_subject = [d for d in documents if subject == "All subjects" or d["subject_name"] == subject]
        chapters = quiz.chapter_options(in_subject, with_subject=subject == "All subjects")
        picked = c1.multiselect("Chapters", list(chapters), placeholder="All chapters")
        scope = {doc_id for label in (picked or chapters) for doc_id in chapters[label]}
        available = [t for t in topics if t["document_id"] in scope]
        topic_names = {t["id"]: t["name"] for t in available}
        topic_ids = st.multiselect(
            "Topics", list(topic_names), format_func=topic_names.get, placeholder="All topics",
        )
        c1, c2 = st.columns(2)
        n = c1.segmented_control("Number of questions", quiz.QUIZ_SIZES, default=10) or 10
        mode = c2.segmented_control("Mode", ["Adaptive", "Even mix"], default="Adaptive") or "Adaptive"
        st.caption(
            f"**Adaptive:** ~{round(memory.ADAPTIVE_WEAK_SHARE * 100)}% of questions on your weak "
            "topics, the rest on topics you haven't been tested on.  **Even mix:** spread evenly."
        )

        chosen_topics = topic_ids or list(topic_names)
        stats = memory.topic_stats(user_id, chosen_topics)
        if st.button("Generate quiz", type="primary", icon=":material/auto_awesome:", use_container_width=True):
            if mode == "Adaptive":
                allocation = memory.adaptive_allocation(stats, n)
            else:
                allocation = quiz.even_allocation(chosen_topics, n)
            with st.spinner(f"Writing {n} questions from your notes..."):
                try:
                    questions = quiz.generate(user_id, allocation)
                except quiz.QuizError as exc:
                    st.error(str(exc))
                    return
            start(questions)
            st.rerun()

    with right, card("focus"):
        weak = sorted((s for s in stats if s.status == "weak"), key=lambda s: s.accuracy)
        section("Adaptive focus" if mode == "Adaptive" else "Topics in this quiz")
        if mode == "Adaptive":
            if weak:
                html('<div class="pa-section-sub">This quiz will concentrate on:</div>')
                chips([(f"{s.name} · {s.accuracy:.0%}", "critical") for s in weak])
            else:
                html(f'<div class="pa-empty">No weak topics yet: a topic needs {memory.MIN_ANSWERS}+ '
                     "answers to be judged. This quiz will favour topics you haven't been tested on.</div>")
        else:
            chips([(topic_names[t], "blue") for t in chosen_topics[:12]])
            if len(chosen_topics) > 12:
                html(f'<div class="pa-empty">+ {len(chosen_topics) - 12} more</div>')


# ---------------------------------------------------------------- taking the quiz

def _record_answer(state: dict, i: int) -> None:
    """Radio callback: store the answer before the page redraws, so the progress count and
    the navigator's ticks are current (and survive the radio not being shown later)."""
    state["answers"][i] = st.session_state[f"q_{i}"]


def _jump(state: dict, key: str) -> None:
    """Navigator callback: move to the chosen question."""
    if st.session_state.get(key) is not None:
        state["current"] = st.session_state[key]


def take(state: dict) -> None:
    questions, answers = state["questions"], state["answers"]
    i = state["current"]
    q = questions[i]
    answered = sum(a is not None for a in answers)

    with card("progress"):
        html(row(f"<b>Question {i + 1} of {len(questions)}</b>",
                 f'<span class="pa-muted">{answered} of {len(questions)} answered</span>'))
        st.progress((i + 1) / len(questions))
        st.pills(
            "Jump to question", range(len(questions)),
            format_func=lambda j: f"{j + 1}{' ✓' if answers[j] is not None else ''}",
            default=i, label_visibility="collapsed",
            key=f"jump_{i}", on_change=_jump, args=(state, f"jump_{i}"),
        )

    with st.container(key="question"), card("question_body"):
        html(badge(q.topic, "violet", "📘 ") + f'<div class="pa-question">{escape(q.question)}</div>')
        st.radio(
            f"Question {i + 1}",
            range(4),
            format_func=lambda j: f"{quiz.LETTERS[j]}.  {q.options[j]}",
            index=answers[i],
            key=f"q_{i}",
            label_visibility="collapsed",
            on_change=_record_answer, args=(state, i),
        )

    for message in st.session_state.pop("quiz_warning", []):
        st.warning(message)

    prev_col, cancel_col, next_col = st.columns([1, 1, 1])
    if prev_col.button("Previous", icon=":material/arrow_back:", disabled=i == 0, use_container_width=True):
        state["current"] = i - 1
        st.rerun()
    # A popover, so one stray click can't throw away every answer.
    with cancel_col.popover("Cancel quiz", icon=":material/close:", use_container_width=True):
        st.caption(f"Discard this quiz? Your {answered} answer{'s' if answered != 1 else ''} won't be saved.")
        if st.button("Yes, discard", type="primary", key="cancel_quiz"):
            del st.session_state.active_quiz
            st.rerun()
    if i < len(questions) - 1:
        if next_col.button("Next", icon=":material/arrow_forward:", type="primary", use_container_width=True):
            state["current"] = i + 1
            st.rerun()
    elif next_col.button("Submit answers", icon=":material/check:", type="primary", use_container_width=True):
        missing = [j for j, a in enumerate(answers) if a is None]
        if missing:
            # Take the student straight to the first unanswered question.
            st.session_state.quiz_warning = [
                f"Answer every question first. Missing: {', '.join(str(j + 1) for j in missing)}"]
            state["current"] = missing[0]
            st.rerun()
        state["result"] = quiz.submit(user_id, questions, list(answers))
        state["chosen"] = list(answers)
        st.rerun()


# ---------------------------------------------------------------- results

def results(questions: list[quiz.Question], chosen: list[int], result: quiz.Result) -> None:
    wrong_topics = sorted({q.topic for q, ok in zip(questions, result.correct) if not ok})
    tone = "aqua" if result.percent >= 80 else "yellow" if result.percent >= 60 else "orange"
    stat_row([
        Stat("Score", f"{result.score} / {result.total}", "🏆", tone),
        Stat("Accuracy", f"{result.percent}%", "🎯", tone),
        Stat("Correct", str(result.score), "✅", "aqua"),
        Stat("To revise", str(len(wrong_topics)), "📌", "orange", "topics"),
    ])
    if wrong_topics:
        with card("revise"):
            section("Topics to revise", "These answers were saved; your weak-topic tracking is updated.")
            chips([(t, "critical") for t in wrong_topics])
    else:
        callout("Perfect score! Every topic in this quiz was answered correctly.", "good", "🎉")

    b1, b2, _ = st.columns([1, 1, 2])
    if b1.button("New quiz", type="primary", icon=":material/refresh:", use_container_width=True):
        del st.session_state.active_quiz
        st.rerun()
    if b2.button("See progress", icon=":material/monitoring:", use_container_width=True):
        st.switch_page("views/progress.py")

    html('<div class="pa-section" style="margin-top:1rem">Review</div>')
    for i, (q, c, ok) in enumerate(zip(questions, chosen, result.correct)):
        with card(f"review_{i}"):
            verdict = badge("Correct", "good", "✓ ") if ok else badge("Incorrect", "critical", "✗ ")
            if ok:
                answer = f'<div class="pa-answer pa-answer-good">✓ {escape(q.options[c])}</div>'
            else:
                answer = (f'<div class="pa-answer pa-answer-bad">✗ Your answer: <s>{escape(q.options[c])}</s></div>'
                          f'<div class="pa-answer pa-answer-good">✓ Correct: {escape(q.correct_option)}</div>')
            html(verdict + badge(q.topic, "violet", "📘 ")
                 + f'<div class="pa-question" style="font-size:1rem !important">{i + 1}. {escape(q.question)}</div>'
                 + answer)
            if q.explanation:
                st.caption(q.explanation)
            if q.source:
                html(badge(q.source, "blue", "📄 "))


if state is None:
    setup()
elif state["result"] is None:
    take(state)
else:
    results(state["questions"], state["chosen"], state["result"])
