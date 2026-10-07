"""Weak-topic dashboard."""

import pandas as pd
import streamlit as st

from core import charts, db, memory
from core.ui import require_login

st.set_page_config(page_title="Progress · PersonaAI", page_icon="📈", layout="wide")
user_id = require_login()

st.title("📈 Progress")
st.caption(
    f"Accuracy per topic over your last {db.RECENT_ANSWERS} answers on it. "
    f"Weak: under {memory.WEAK_BELOW:.0%}; strong: {memory.STRONG_FROM:.0%} or more "
    f"(after at least {memory.MIN_ANSWERS} answers)."
)

attempts = db.list_quiz_attempts(user_id)
stats = memory.topic_stats(user_id)

if not attempts:
    st.info("No quizzes yet. Take a few on the **Quiz** page and your progress will show here.")
    st.stop()

tested = [s for s in stats if s.answers]
weak = sorted((s for s in tested if s.status == "weak"), key=lambda s: s.accuracy)
strong = sorted((s for s in tested if s.status == "strong"), key=lambda s: -s.accuracy)
answered = sum(a["total"] for a in attempts)
correct = sum(a["score"] for a in attempts)

# --- Headline numbers ---
c1, c2, c3, c4 = st.columns(4)
c1.metric("Quizzes taken", len(attempts))
c2.metric("Overall accuracy", f"{correct / answered:.0%}" if answered else "–", help=f"{correct} of {answered} answers")
c3.metric("Weak topics", len(weak))
c4.metric("Topics tested", f"{len(tested)} / {len(stats)}")

# --- Weak / strong lists ---
left, right = st.columns(2)
with left:
    st.subheader("🔴 Weak topics")
    if weak:
        for s in weak:
            st.markdown(f"- **{s.name}** — {s.accuracy:.0%} ({s.correct}/{s.answers} all-time)")
        st.caption("Adaptive quizzes on the **Quiz** page focus on these.")
    else:
        st.caption(
            f"None yet. A topic is judged after {memory.MIN_ANSWERS} answers; "
            "keep taking quizzes."
        )
with right:
    st.subheader("🟢 Strong topics")
    if strong:
        for s in strong:
            st.markdown(f"- **{s.name}** — {s.accuracy:.0%} ({s.correct}/{s.answers} all-time)")
    else:
        st.caption("None yet.")

# --- Topic accuracy chart ---
st.subheader("Accuracy by topic")
topic_df = pd.DataFrame(
    {
        "Topic": s.name,
        "Accuracy": s.accuracy,
        "Answers": s.answers,
        "Status": s.label,
        "Document": s.filename or "",
    }
    for s in tested
)

st.altair_chart(charts.topic_accuracy(topic_df), use_container_width=True)

# --- Quiz history ---
st.subheader("Quiz scores over time")
history = pd.DataFrame(
    {
        "Quiz": i + 1,
        "Score": a["score"] / a["total"] if a["total"] else 0,
        "Result": f"{a['score']} / {a['total']}",
        "Taken": a["created_at"],
    }
    for i, a in enumerate(reversed(attempts))
)
if len(history) < 2:
    st.caption("Take another quiz to see a trend. So far: " + history["Result"].iloc[0])
else:
    st.altair_chart(charts.score_history(history), use_container_width=True)

# --- Table view (every topic, including untested) ---
with st.expander("All topics (table)"):
    table = pd.DataFrame(
        {
            "Topic": s.name,
            "Document": s.filename or "",
            "Status": s.label,
            "Recent accuracy": f"{s.accuracy:.0%}" if s.accuracy is not None else "–",
            "Answers": s.answers,
            "Correct": s.correct,
            "Last tested": s.last_seen or "–",
        }
        for s in stats
    )
    st.dataframe(table, hide_index=True, use_container_width=True)
