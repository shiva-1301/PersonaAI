"""Generate and take quizzes."""

import streamlit as st

from core import db, memory, quiz
from core.ui import load_models, require_login

st.set_page_config(page_title="Quiz · PersonaAI", page_icon="📝", layout="wide")
user_id = require_login()
load_models()

st.title("📝 Quiz")
st.caption("Multiple-choice questions generated from your notes. Every answer is saved per topic.")

# st.session_state.active_quiz: {"questions": [...], "result": Result | None, "chosen": [...]}
state = st.session_state.get("active_quiz")


def setup() -> None:
    documents = db.list_documents(user_id)
    topics = db.list_topics(user_id)
    if not documents:
        st.info("Upload your notes on the **Notes Q&A** page first.")
        return
    if not topics:
        st.info("Your documents have no topics yet. Add them on the **Notes Q&A** page.")
        return

    names = {d["id"]: d["filename"] for d in documents}
    doc_ids = st.multiselect(
        "Documents", list(names), format_func=names.get, placeholder="All documents"
    )
    available = [t for t in topics if not doc_ids or t["document_id"] in doc_ids]
    topic_names = {t["id"]: t["name"] for t in available}
    topic_ids = st.multiselect(
        "Topics",
        list(topic_names),
        format_func=topic_names.get,
        placeholder="All topics in the selected documents",
    )
    n = st.radio("Number of questions", quiz.QUIZ_SIZES, index=1, horizontal=True)
    mode = st.radio(
        "Mode",
        ["Adaptive", "Even mix"],
        horizontal=True,
        captions=[
            f"~{round(memory.ADAPTIVE_WEAK_SHARE * 100)}% of questions on your weak topics",
            "Questions spread evenly over the topics",
        ],
    )

    chosen_topics = topic_ids or list(topic_names)
    stats = memory.topic_stats(user_id, chosen_topics)
    weak = sorted((s for s in stats if s.status == "weak"), key=lambda s: s.accuracy)
    if mode == "Adaptive":
        if weak:
            st.info(
                "Focusing on your weak topics: "
                + ", ".join(f"**{s.name}** ({s.accuracy:.0%})" for s in weak)
            )
        else:
            st.info(
                f"No weak topics yet (a topic needs {memory.MIN_ANSWERS}+ answers to be judged). "
                "This quiz will favour topics you haven't been tested on."
            )

    if st.button("Generate quiz", type="primary"):
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
        st.session_state.active_quiz = {"questions": questions, "result": None, "chosen": []}
        st.rerun()


def take(questions: list[quiz.Question]) -> None:
    st.subheader(f"{len(questions)} questions")
    with st.form("quiz"):
        chosen = []
        for i, q in enumerate(questions):
            st.markdown(f"**{i + 1}. {q.question}**")
            choice = st.radio(
                f"Question {i + 1}",
                range(4),
                format_func=lambda j, q=q: f"{quiz.LETTERS[j]}. {q.options[j]}",
                index=None,
                key=f"q_{i}",
                label_visibility="collapsed",
            )
            chosen.append(choice)
            st.caption(f"Topic: {q.topic}")
            st.divider()
        submitted = st.form_submit_button("Submit answers", type="primary")

    if submitted:
        missing = [str(i + 1) for i, c in enumerate(chosen) if c is None]
        if missing:
            st.warning(f"Answer every question first. Missing: {', '.join(missing)}")
            return
        state["result"] = quiz.submit(user_id, questions, chosen)
        state["chosen"] = chosen
        st.rerun()

    if st.button("Cancel quiz"):
        del st.session_state.active_quiz
        st.rerun()


def results(questions: list[quiz.Question], chosen: list[int], result: quiz.Result) -> None:
    col1, col2 = st.columns([1, 3])
    col1.metric("Score", f"{result.score} / {result.total}", f"{result.percent}%")
    with col2:
        wrong_topics = sorted({q.topic for q, ok in zip(questions, result.correct) if not ok})
        if not wrong_topics:
            st.success("Perfect score! 🎉")
        else:
            st.info("Revise: " + ", ".join(wrong_topics))

    for i, (q, c, ok) in enumerate(zip(questions, chosen, result.correct)):
        icon = "✅" if ok else "❌"
        with st.container(border=True):
            st.markdown(f"{icon} **{i + 1}. {q.question}**")
            if ok:
                st.markdown(f"Your answer: **{q.options[c]}**")
            else:
                st.markdown(f"Your answer: ~~{q.options[c]}~~")
                st.markdown(f"Correct answer: **{q.correct_option}**")
            if q.explanation:
                st.caption(q.explanation)
            st.caption(f"Topic: {q.topic}" + (f" · Source: {q.source}" if q.source else ""))

    if st.button("New quiz", type="primary"):
        del st.session_state.active_quiz
        st.rerun()


if state is None:
    setup()
elif state["result"] is None:
    take(state["questions"])
else:
    results(state["questions"], state["chosen"], state["result"])
