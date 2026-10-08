"""Exam study plan: a day-by-day timeline with topic priority chips."""

from datetime import date, timedelta
from html import escape

import pandas as pd
import streamlit as st

from core import db, memory, planner
from ui.shell import require_login
from ui.styles import Stat, TONES, callout, card, chip, chips, html, page_header, section, stat_row

user_id = require_login()

page_header(
    "Study Plan",
    "A day-by-day revision plan for your exam that gives your weak topics extra time.",
)

today = date.today()
# kind -> (icon, label, tone)
KINDS = {
    "study": ("📖", "Study", "blue"),
    "review": ("🔁", "Review + 5-question quiz", "aqua"),
    "mock": ("📝", "Mock exam", "violet"),
    "revision": ("🎯", "Final revision", "orange"),
}


# ---------------------------------------------------------------- create

def new_plan_form(existing: planner.Plan | None) -> None:
    documents = db.list_documents(user_id)
    if not documents:
        callout("Upload your notes on the Notes Q&A page first.", "blue", "👉")
        return
    names = {d["id"]: d["filename"] for d in documents}
    left, right = st.columns([1.5, 1], gap="large")
    with left, card("plan_form"):
        section("Plan your revision", "Tell PersonaAI when the exam is and how much time you have.")
        with st.form("new_plan", border=False):
            c1, c2 = st.columns(2)
            exam = c1.date_input(
                "Exam date",
                value=date.fromisoformat(existing.exam_date) if existing else today + timedelta(days=14),
                min_value=today + timedelta(days=1),
            )
            hours = c2.number_input(
                "Study hours per day", min_value=0.5, max_value=12.0, step=0.5,
                value=float(existing.hours_per_day) if existing else 3.0,
            )
            doc_ids = st.multiselect(
                "Documents to cover", list(names), format_func=names.get, placeholder="All documents"
            )
            submitted = st.form_submit_button(
                "Create plan", type="primary", icon=":material/event_available:", use_container_width=True
            )
        if submitted:
            try:
                planner.create(user_id, exam, hours, doc_ids or None)
            except planner.PlanError as exc:
                st.error(str(exc))
                return
            st.session_state.pop("plan_form", None)
            st.rerun()
        if existing and st.button("Cancel", type="tertiary"):
            st.session_state.pop("plan_form", None)
            st.rerun()

    with right, card("how"):
        section("How your plan is built")
        html('<div class="pa-section-sub">Time per topic is split by how well you know it:</div>')
        tones = {"weak": "critical", "new": "gray", "learning": "warning", "strong": "good"}
        chips([(f"{memory.STATUS_LABELS[k]} · {w}×", tones[k]) for k, w in planner.WEIGHTS.items()])
        st.markdown(
            "- Every topic gets at least 30 minutes.\n"
            "- Each topic is studied, then reviewed with a short quiz about 2 days later.\n"
            "- The last two days are a mock exam and a weak-topic revision.\n"
            "- **Regenerate** after a few quizzes: improved topics get less time."
        )


# ---------------------------------------------------------------- view

def _toggle_done(plan_id: int, plan: planner.Plan, index: int, key: str) -> None:
    plan.days[index].done = bool(st.session_state[key])
    planner.save(plan_id, plan)


def _task_chip(task: planner.Task, weak_ids: set[int]) -> str:
    icon, _, tone = KINDS[task.kind]
    # Display-only shortening: the icon + legend already say it's a review with a quiz.
    title = task.title.replace("Review + 5-question quiz:", "Review:")
    if task.topic_id in weak_ids:
        return chip(f"⚑ {icon} {title} · {task.hours:g} h", "critical")
    return chip(f"{icon} {title} · {task.hours:g} h", tone)


def _day_card(plan_id: int, plan: planner.Plan, index: int, weak_ids: set[int]) -> None:
    day = plan.days[index]
    d = date.fromisoformat(day.date)
    is_today = d == today
    with card(f"day_{index}{'_today' if is_today else ''}"):
        date_col, tasks_col, done_col = st.columns([0.9, 6, 1.1], vertical_alignment="center")
        bg, fg = (TONES["blue"][1], TONES["blue"][0]) if is_today else ("#F5F7FB", "#52607A")
        date_col.markdown(
            f'<div class="pa-date" style="background:{bg};color:{fg}">'
            f'<div class="pa-date-dow">{"Today" if is_today else f"{d:%a}"}</div>'
            f'<div class="pa-date-num">{d.day}</div><div class="pa-date-mon">{d:%b}</div></div>',
            unsafe_allow_html=True,
        )
        with tasks_col:
            html(f'<div class="pa-chips" style="opacity:{0.55 if day.done else 1}">'
                 + "".join(_task_chip(t, weak_ids) for t in day.tasks) + "</div>"
                 + f'<div class="pa-empty" style="margin:0">{day.hours:g} h planned</div>')
        key = f"done_{plan_id}_{index}"
        done_col.checkbox("Done", value=day.done, key=key, on_change=_toggle_done,
                          args=(plan_id, plan, index, key))


def show_plan(plan_id: int, plan: planner.Plan) -> None:
    exam = date.fromisoformat(plan.exam_date)
    days_left = (exam - today).days
    if days_left < 1:
        callout(f"Your exam on {exam:%a %d %b} has passed. Create a plan for your next one.", "blue", "🎓")
        new_plan_form(None)
        return

    stats = {s.topic_id: s for s in memory.topic_stats(user_id)}
    weak_ids = {tid for tid, s in stats.items() if s.status == "weak"}
    done = sum(d.done for d in plan.days)
    stat_row([
        Stat("Exam", f"{exam:%d %b}", "🎓", "violet", f"{days_left} day{'s' if days_left != 1 else ''} left"),
        Stat("Hours per day", f"{plan.hours_per_day:g} h", "⏱️", "blue", f"{sum(plan.topic_hours.values()):g} h of topic study"),
        Stat("Days done", f"{done} / {len(plan.days)}", "✅", "aqua"),
        Stat("Topics covered", str(len(plan.topic_hours)), "📚", "orange",
             f"{len([t for t in plan.topic_hours if t in weak_ids])} weak, extra time"),
    ])

    c1, c2, _ = st.columns([1.5, 1, 2.5])
    if c1.button("Regenerate with latest scores", type="primary", icon=":material/refresh:",
                 use_container_width=True):
        new = planner.regenerate(user_id, plan, today)
        names = {s.topic_id: s.name for s in stats.values()}
        st.session_state.plan_changes = planner.changes(plan, new, names)
        st.rerun()
    if c2.button("New plan", icon=":material/add:", use_container_width=True):
        st.session_state.plan_form = True
        st.rerun()

    changes = st.session_state.pop("plan_changes", None)
    if changes is not None:
        if changes:
            st.success("Plan updated from your latest quiz scores:\n\n" + "\n".join(f"- {c}" for c in changes))
        else:
            st.success("Plan regenerated; time per topic is unchanged.")
    elif plan.generated_on < today.isoformat():
        callout(f"This plan was made on {date.fromisoformat(plan.generated_on):%d %b}. Regenerate it "
                "after a few quizzes so it reflects your latest weak topics.", "gray", "🕑")

    # Legend for the chips below (colour is never the only cue: every chip has an icon + label).
    chips([(f"{icon} {label}", tone) for icon, label, tone in KINDS.values()] + [("⚑ Weak topic: priority", "critical")])

    indices = range(len(plan.days))
    earlier = [i for i in indices if plan.days[i].date < today.isoformat()]
    upcoming = [i for i in indices if plan.days[i].date >= today.isoformat()]
    html('<div class="pa-section" style="margin:.6rem 0 .4rem 0">Day by day</div>')
    for i in upcoming:
        _day_card(plan_id, plan, i, weak_ids)
    if earlier:
        with st.expander(f"Earlier days ({len(earlier)})", icon=":material/history:"):
            for i in earlier:
                _day_card(plan_id, plan, i, weak_ids)

    with st.expander("Time per topic", icon=":material/pie_chart:"):
        rows = [
            {
                "Topic": stats[tid].name if tid in stats else "(deleted topic)",
                "Status": stats[tid].label if tid in stats else "",
                "Planned hours": hours,
            }
            for tid, hours in sorted(plan.topic_hours.items(), key=lambda kv: -kv[1])
        ]
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


current = planner.latest(user_id)
if current is None or st.session_state.get("plan_form"):
    new_plan_form(current[1] if current else None)
else:
    show_plan(*current)
