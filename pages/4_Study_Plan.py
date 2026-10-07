"""Exam study plan."""

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from core import db, memory, planner
from core.ui import require_login

st.set_page_config(page_title="Study Plan · PersonaAI", page_icon="🗓️", layout="wide")
user_id = require_login()

st.title("🗓️ Study Plan")
st.caption(
    "A day-by-day revision plan for your exam. Weak topics get 3× the time of strong ones, "
    "untested topics 2×; every topic is studied and then reviewed with a short quiz a couple of "
    "days later, and the last days are a mock exam and a final revision."
)

KIND_ICONS = {"study": "📖", "review": "🔁", "mock": "📝", "revision": "🎯"}
today = date.today()


def new_plan_form(existing: planner.Plan | None) -> None:
    documents = db.list_documents(user_id)
    if not documents:
        st.info("Upload your notes on the **Notes Q&A** page first.")
        return
    names = {d["id"]: d["filename"] for d in documents}
    with st.form("new_plan"):
        exam = st.date_input(
            "Exam date",
            value=date.fromisoformat(existing.exam_date) if existing else today + timedelta(days=14),
            min_value=today + timedelta(days=1),
        )
        hours = st.number_input(
            "Study hours per day", min_value=0.5, max_value=12.0, step=0.5,
            value=float(existing.hours_per_day) if existing else 3.0,
        )
        doc_ids = st.multiselect(
            "Documents to cover", list(names), format_func=names.get, placeholder="All documents"
        )
        submitted = st.form_submit_button("Create plan", type="primary")
    if submitted:
        try:
            planner.create(user_id, exam, hours, doc_ids or None)
        except planner.PlanError as exc:
            st.error(str(exc))
            return
        st.session_state.pop("plan_form", None)
        st.rerun()
    if existing and st.button("Cancel"):
        st.session_state.pop("plan_form", None)
        st.rerun()


def show_plan(plan_id: int, plan: planner.Plan) -> None:
    exam = date.fromisoformat(plan.exam_date)
    days_left = (exam - today).days
    if days_left < 1:
        st.info(f"Your exam on {exam:%a %d %b} has passed. Create a plan for your next one.")
        new_plan_form(None)
        return

    done = sum(d.done for d in plan.days)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Exam", f"{exam:%d %b}", f"{days_left} days left", delta_color="off")
    c2.metric("Hours per day", f"{plan.hours_per_day:g}")
    c3.metric("Days done", f"{done} / {len(plan.days)}")
    c4.metric("Topics covered", len(plan.topic_hours))

    col1, col2, _ = st.columns([1.4, 1, 3])
    if col1.button("🔄 Regenerate with latest scores", type="primary"):
        new = planner.regenerate(user_id, plan, today)
        names = {s.topic_id: s.name for s in memory.topic_stats(user_id)}
        st.session_state.plan_changes = planner.changes(plan, new, names)
        st.rerun()
    if col2.button("New plan"):
        st.session_state.plan_form = True
        st.rerun()

    changes = st.session_state.pop("plan_changes", None)
    if changes is not None:
        if changes:
            st.success("Plan updated from your latest quiz scores:\n\n" + "\n".join(f"- {c}" for c in changes))
        else:
            st.success("Plan regenerated; time per topic is unchanged.")

    if plan.generated_on < today.isoformat():
        st.caption(
            f"This plan was made on {date.fromisoformat(plan.generated_on):%d %b}. "
            "Regenerate it after a few quizzes so it reflects your latest weak topics."
        )

    # Today's tasks in full.
    todays = plan.day(today)
    if todays:
        st.subheader("Today")
        for t in todays.tasks:
            st.markdown(f"{KIND_ICONS[t.kind]} {t.title} — **{t.hours:g} h**")

    # Day-by-day table with a "Done" checkbox per day.
    st.subheader("Day by day")
    table = pd.DataFrame(
        {
            "Done": d.done,
            "Date": ("📍 " if d.date == today.isoformat() else "")
            + f"{date.fromisoformat(d.date):%a %d %b}",
            "Plan": "  ·  ".join(f"{KIND_ICONS[t.kind]} {t.title} ({t.hours:g}h)" for t in d.tasks),
            "Hours": d.hours,
        }
        for d in plan.days
    )
    edited = st.data_editor(
        table,
        key=f"plan_{plan_id}",
        hide_index=True,
        use_container_width=True,
        disabled=["Date", "Plan", "Hours"],
        column_config={
            "Done": st.column_config.CheckboxColumn(width="small"),
            "Date": st.column_config.TextColumn(width="small"),
            "Plan": st.column_config.TextColumn(width="large"),
            "Hours": st.column_config.NumberColumn(format="%.1f h", width="small"),
        },
    )
    marks = [bool(x) for x in edited["Done"]]
    if marks != [d.done for d in plan.days]:
        for d, mark in zip(plan.days, marks):
            d.done = mark
        planner.save(plan_id, plan)
        st.rerun()

    # Where the time goes.
    with st.expander("Time per topic"):
        stats = {s.topic_id: s for s in memory.topic_stats(user_id)}
        rows = [
            {
                "Topic": stats[tid].name if tid in stats else "(deleted topic)",
                "Status": stats[tid].label if tid in stats else "",
                "Planned hours": hours,
            }
            for tid, hours in sorted(plan.topic_hours.items(), key=lambda kv: -kv[1])
        ]
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        st.caption(
            "Weights: " + ", ".join(f"{memory.STATUS_LABELS[k]} {w}×" for k, w in planner.WEIGHTS.items())
        )


current = planner.latest(user_id)
if current is None or st.session_state.get("plan_form"):
    new_plan_form(current[1] if current else None)
else:
    show_plan(*current)
