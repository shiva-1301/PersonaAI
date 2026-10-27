"""Home dashboard: welcome banner, headline numbers, today's plan, topics to revise."""

from datetime import date, datetime, timezone
from html import escape

import streamlit as st

from core import config, db, llm, memory, planner
from ui.shell import require_login
from ui.styles import Stat, badge, card, chips, hero_text, html, row, section, stat_row

user_id = require_login()
name = st.session_state.username

documents = db.list_documents(user_id)
attempts = db.list_quiz_attempts(user_id)
stats = memory.topic_stats(user_id)
weak = sorted((s for s in stats if s.status == "weak"), key=lambda s: s.accuracy)
strong = [s for s in stats if s.status == "strong"]
answered = sum(a["total"] for a in attempts)
correct = sum(a["score"] for a in attempts)

# ---- Hero banner ----
if not documents:
    message, cta, target = (
        "Upload your course notes to begin. PersonaAI answers from them, quizzes you, and "
        "keeps track of what you don't know yet.",
        "Start with Notes Q&A", "views/notes_qa.py",
    )
elif weak:
    message, cta, target = (
        f"You have {len(weak)} weak topic{'s' if len(weak) > 1 else ''} to work on. "
        "An adaptive quiz will focus on them.",
        "Take an adaptive quiz", "views/quiz.py",
    )
else:
    message, cta, target = (
        "Your notes are ready. Ask a question or take a quiz; PersonaAI will learn which "
        "topics need more work.",
        "Take a quiz", "views/quiz.py",
    )

with st.container(key="hero"):
    hero_text(f"{date.today():%A, %d %B}", f"Welcome back, {name} 👋", message)
    left, right, _ = st.columns([1.1, 1.1, 2.5])
    if left.button(cta, icon=":material/arrow_forward:", use_container_width=True):
        st.switch_page(target)
    if documents and right.button("Ask your notes", icon=":material/forum:", use_container_width=True):
        st.switch_page("views/notes_qa.py")

html('<div style="height:1.1rem"></div>')

# ---- Headline numbers ----
stat_row([
    Stat("Documents uploaded", str(len(documents)), "📄", "blue",
         f"{len(stats)} topics" if stats else "No topics yet"),
    Stat("Quizzes taken", str(len(attempts)), "📝", "violet",
         f"{answered} questions answered" if answered else "None yet"),
    Stat("Average score", f"{correct / answered:.0%}" if answered else "–", "🎯", "aqua",
         "across all quizzes"),
    Stat("Weak topics", str(len(weak)), "⚠️", "orange",
         f"{len(strong)} strong" if strong else f"need {memory.MIN_ANSWERS}+ answers each"),
])

left, right = st.columns([1.35, 1])

# ---- Today's plan ----
with left:
    with card("today"):
        section("Today's study plan")
        current = planner.latest(user_id)
        today = current[1].day(date.today()) if current else None
        if today and today.tasks:
            icons = {"study": "📖", "review": "🔁", "mock": "📝", "revision": "🎯"}
            html("".join(row(f"{icons[t.kind]} {escape(t.title)}", badge(f"{t.hours:g} h", "blue"))
                         for t in today.tasks))
            if today.done:
                html(badge("Done for today", "good", "✓ "))
        elif current:
            st.caption("Nothing planned for today.")
        else:
            st.caption("No study plan yet. Tell PersonaAI your exam date and it builds a "
                       "day-by-day plan that gives weak topics extra time.")
        if st.button("Open study plan" if current else "Create a study plan",
                     icon=":material/event_note:", key="open_plan"):
            st.switch_page("views/study_plan.py")

# ---- Topics to revise ----
with right:
    with card("revise"):
        section("Topics to revise", "From your recent quiz answers")
        chips([(f"{s.name} · {s.accuracy:.0%}", "critical") for s in weak[:8]],
              empty=f"No weak topics yet. A topic is judged after {memory.MIN_ANSWERS} answers.")
        if strong:
            html('<div class="pa-section-sub" style="margin-top:.6rem">Strong</div>')
            chips([(s.name, "good") for s in strong[:6]])

# ---- Recent quizzes ----
if attempts:
    with card("recent"):
        section("Recent quizzes")
        rows = []
        for a in attempts[:5]:
            pct = a["score"] / a["total"] if a["total"] else 0
            tone = "good" if pct >= 0.8 else "warning" if pct >= 0.6 else "critical"
            # SQLite stores UTC; show the student's local time.
            when = (datetime.fromisoformat(a["created_at"]).replace(tzinfo=timezone.utc)
                    .astimezone().strftime("%d %b, %H:%M"))
            rows.append(row(f"📝 Quiz · {when}",
                            badge(f"{a['score']}/{a['total']}", "gray") + badge(f"{pct:.0%}", tone)))
        html("".join(rows))

# ---- System check (the original LLM connection test) ----
with st.expander("System check: AI connection", icon=":material/settings:"):
    providers = ["claude", "gemini", "ollama"]
    provider = st.radio(
        "Provider", providers,
        index=providers.index(config.LLM_PROVIDER) if config.LLM_PROVIDER in providers else 0,
        horizontal=True,
    )
    if st.button("Send test message"):
        with st.spinner(f"Asking {llm.active_model(provider)}..."):
            try:
                reply = llm.generate(
                    "In one short sentence, say hello to a student starting to revise for exams.",
                    provider=provider,
                    fallback=False,
                )
                st.success(reply)
            except llm.LLMError as exc:
                st.error(f"LLM call failed: {exc}")
