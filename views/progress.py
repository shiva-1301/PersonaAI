"""Weak-topic dashboard."""

import pandas as pd
import streamlit as st

from core import charts, db, memory
from ui.shell import require_login
from ui.styles import Stat, callout, card, chips, html, page_header, section, stat_row

user_id = require_login()

page_header(
    "Progress",
    f"Accuracy per topic over your last {db.RECENT_ANSWERS} answers on it. "
    f"Weak: under {memory.WEAK_BELOW:.0%}; strong: {memory.STRONG_FROM:.0%} or more "
    f"(after at least {memory.MIN_ANSWERS} answers).",
)

attempts = db.list_quiz_attempts(user_id)
stats = memory.topic_stats(user_id)

if not attempts:
    callout("No quizzes yet. Take a few on the Quiz page and your progress will show here.", "blue", "📈")
    if st.button("Take a quiz", type="primary", icon=":material/quiz:"):
        st.switch_page("views/quiz.py")
    st.stop()

tested = [s for s in stats if s.answers]
weak = sorted((s for s in tested if s.status == "weak"), key=lambda s: s.accuracy)
strong = sorted((s for s in tested if s.status == "strong"), key=lambda s: -s.accuracy)
answered = sum(a["total"] for a in attempts)
correct = sum(a["score"] for a in attempts)

# ---- Headline numbers ----
stat_row([
    Stat("Quizzes taken", str(len(attempts)), "📝", "violet", f"{answered} questions"),
    Stat("Overall accuracy", f"{correct / answered:.0%}" if answered else "–", "🎯", "aqua",
         f"{correct} of {answered} correct"),
    Stat("Weak topics", str(len(weak)), "⚠️", "orange", f"{len(strong)} strong"),
    Stat("Topics tested", f"{len(tested)} / {len(stats)}", "📚", "blue", "at least one answer"),
])

# ---- Score trend + topic status ----
left, right = st.columns([1.5, 1])
with left, card("history"):
    section("Quiz scores over time")
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
        html(f'<div class="pa-empty">Take another quiz to see a trend. So far: '
             f'{history["Result"].iloc[0]}.</div>')
    else:
        st.plotly_chart(charts.score_history(history), use_container_width=True, config=charts.PLOTLY_CONFIG)

with right, card("status"):
    section("Weak topics", "Adaptive quizzes focus on these")
    chips([(f"{s.name} · {s.accuracy:.0%}", "critical") for s in weak],
          empty=f"None yet. A topic is judged after {memory.MIN_ANSWERS} answers.")
    html('<div class="pa-section-sub" style="margin-top:.6rem"><b>Strong</b></div>')
    chips([(f"{s.name} · {s.accuracy:.0%}", "good") for s in strong], empty="None yet.")
    learning = sorted((s for s in tested if s.status == "learning"), key=lambda s: s.accuracy)
    if learning:
        html('<div class="pa-section-sub" style="margin-top:.6rem"><b>Still learning</b> '
             f"(fewer than {memory.MIN_ANSWERS} answers, or {memory.WEAK_BELOW:.0%}"
             f"–{memory.STRONG_FROM:.0%})</div>")
        more = [(f"+{len(learning) - 6} more in the chart", "gray")] if len(learning) > 6 else []
        chips([(f"{s.name} · {s.accuracy:.0%}", "warning") for s in learning[:6]] + more)

# ---- Accuracy per topic ----
with card("topics"):
    section("Accuracy by topic", "Weakest first. Hover a bar for details.")
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
    st.plotly_chart(charts.topic_accuracy(topic_df), use_container_width=True, config=charts.PLOTLY_CONFIG)

# ---- Table view (every topic, including untested) ----
with st.expander("All topics (table)", icon=":material/table:"):
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
