"""Upload documents + ask questions about them."""

from html import escape

import streamlit as st

from core import db, ingest, llm, memory, rag
from core.documents import SUPPORTED_TYPES, DocumentError
from ui.shell import load_models, require_login
from ui.styles import badge, callout, card, html, icon, page_header, section

user_id = require_login()

page_header("Notes Q&A", "Answers come only from your uploaded notes, with the file and page they came from.")

st.session_state.setdefault("qa_history", [])
load_models()

documents = db.list_documents(user_id)


# ---------------------------------------------------------------- helpers

def process_uploads(files, subject: str, subject_id: int | None = None) -> list[tuple[str, str]]:
    """Ingest each file; return (level, message) pairs to show after the page reloads."""
    messages = []
    progress = st.progress(0.0)
    for i, file in enumerate(files):
        progress.progress(i / len(files), text=f"Processing {file.name} (extract, embed, find topics)...")
        try:
            result = ingest.ingest(user_id, file.name, file.getvalue(), subject or None, subject_id=subject_id)
        except DocumentError as exc:
            messages.append(("error", str(exc)))
            continue
        except Exception as exc:
            messages.append(("error", f"{file.name}: processing failed ({exc})"))
            continue
        pages = f"{result.pages} pages" if result.pages else "text"
        messages.append(
            ("success", f"{file.name}: {pages}, {result.chunks} chunks, {len(result.topics)} topics"
                        + (f", {result.image_pages_read} image pages read" if result.image_pages_read else ""))
        )
        if result.warning:
            messages.append(("warning", f"{file.name}: {result.warning}"))
    progress.empty()
    return messages


def show_weak_topic(topic: dict | None) -> None:
    if topic:
        callout(
            f"This is about {topic['name']}, one of your weak topics ({topic['accuracy']:.0%} in "
            "recent quizzes). An adaptive quiz on the Quiz page will focus on it.",
            tone="warning", icon="bookmark", bold="Weak topic.",
        )


def show_answer(answer: rag.Answer) -> None:
    if not answer.found:
        callout(answer.text, tone="gray", icon="search")
        if answer.model:
            html(badge(f"Checked by {answer.model}", "gray"))
        return
    st.markdown(answer.text)
    badges = "".join(badge(f"S{s.number} · {s.label}", "blue", "file") for s in answer.sources)
    if answer.model:
        badges += badge(answer.model, "gray", "cpu")
    if badges:
        html(f'<div style="margin-top:.2rem">{badges}</div>')
    if answer.sources:
        with st.expander("Show source excerpts"):
            for s in answer.sources:
                st.markdown(f"**S{s.number} · {s.label}**")
                st.caption(s.excerpt)


def suggested_topics(n: int) -> list[str]:
    """First topics of each document in turn, so suggestions span all the notes."""
    per_doc = [[t["name"] for t in db.list_topics(user_id, d["id"])] for d in documents]
    picks = [names[i] for i in range(max(map(len, per_doc), default=0)) for names in per_doc if i < len(names)]
    return picks[:n]


def ask(question: str, scope: list[int]) -> None:
    """Answer one question inside the current chat container and add it to the history."""
    with st.chat_message("user", avatar=":material/person:"):
        st.markdown(question)
    with st.chat_message("assistant", avatar=":material/school:"):
        with st.spinner("Searching your notes..."):
            try:
                answer = rag.answer(user_id, question, document_ids=scope or None)
            except llm.LLMError:
                st.error(
                    "The AI service isn't responding right now (Gemini may be busy and "
                    "Ollama isn't reachable). Please try again in a minute."
                )
                return
        show_answer(answer)
        weak = memory.related_weak_topic(user_id, question) if answer.found else None
        weak_topic = {"name": weak.name, "accuracy": weak.accuracy} if weak else None
        show_weak_topic(weak_topic)
    st.session_state.qa_history.append(
        {"question": question, "answer": answer, "weak_topic": weak_topic}
    )


# ---------------------------------------------------------------- layout

chat_col, docs_col = st.columns([1.7, 1], gap="large")

# ---- Right: upload + document list ----
with docs_col:
    cohort_id = st.session_state.get("cohort_id")
    cohort_subjects = {s["id"]: s["name"] for s in db.list_subjects(cohort_id)} if cohort_id else {}
    shared_docs = [d for d in documents if d["shared"]]
    my_docs = [d for d in documents if not d["shared"]]

    def doc_line(doc, topics) -> None:
        meta = " · ".join(
            x for x in (f"{doc['page_count']} pages" if doc["page_count"] else "", f"{len(topics)} topics") if x
        )
        badges = (badge(doc["subject_name"], "violet") if doc["subject_name"] else "") + (
            badge(doc["unit"], "blue") if doc["unit"] else "")
        html(
            f'<div class="pa-doc"><div class="pa-doc-icon">{icon("file", 18)}</div><div style="min-width:0">'
            f'<div class="pa-doc-name" title="{escape(doc["filename"])}">{escape(doc["filename"])}</div>'
            f'<div class="pa-doc-meta">{meta}</div>{badges}</div></div>'
        )

    if cohort_id:
        with card("course_docs"):
            section(f"Course notes ({len(shared_docs)})", "Shared by your department. Always up to date.")
            if not shared_docs:
                html('<div class="pa-empty">Your department hasn\'t shared notes yet. '
                     "You can add your own below.</div>")
            for doc in shared_docs:
                doc_line(doc, db.list_topics(user_id, doc["id"]))

    with card("upload"):
        section("Add your own notes", "Private to you. PDF, Word, PowerPoint or TXT. Re-uploading a file with the "
                "same name updates it.")
        with st.form("upload", clear_on_submit=True, border=False):
            files = st.file_uploader(
                "Upload course material",
                type=list(SUPPORTED_TYPES),
                accept_multiple_files=True,
                label_visibility="collapsed",
            )
            if cohort_subjects:
                subject_id = st.selectbox("Subject", [None, *cohort_subjects],
                                          format_func=lambda s: "No subject" if s is None else cohort_subjects[s])
                subject = cohort_subjects.get(subject_id, "")
            else:
                subject_id = None
                subject = st.text_input("Subject (optional)", placeholder="e.g. Big Data")
            submitted = st.form_submit_button(
                "Process files", type="primary", icon=":material/upload:", use_container_width=True
            )
        if submitted:
            if not files:
                st.error("Choose at least one file first.")
            else:
                st.session_state.upload_messages = process_uploads(files, subject, subject_id)
                st.rerun()
        for level, message in st.session_state.pop("upload_messages", []):
            getattr(st, level)(message)

    with card("docs"):
        section(f"My notes ({len(my_docs)})")
        if not my_docs:
            html('<div class="pa-empty">No notes of your own yet. Upload them above.</div>')
        for doc in my_docs:
            topics = db.list_topics(user_id, doc["id"])
            doc_line(doc, topics)
            with st.expander("Edit topics", icon=":material/edit:"):
                edited = st.text_area(
                    "Topics (one per line, edit if any are wrong)",
                    "\n".join(t["name"] for t in topics),
                    height=200,
                    key=f"topics_{doc['id']}",
                )
                col1, col2 = st.columns(2)
                if col1.button("Save topics", key=f"save_{doc['id']}", use_container_width=True):
                    db.set_topics(user_id, doc["id"], edited.splitlines())
                    st.toast("Topics saved.")
                    st.rerun()
                with col2.popover("Delete", icon=":material/delete:", use_container_width=True):
                    st.caption(f"Delete **{doc['filename']}** and its topics? Quiz history for "
                               "those topics will lose its link.")
                    if st.button("Yes, delete", key=f"del_{doc['id']}", type="primary"):
                        ingest.remove(user_id, doc["id"])
                        st.toast(f"Deleted {doc['filename']}.")
                        st.rerun()

# ---- Left: chat ----
with chat_col:
    with card("chat"):
        section("Ask your notes")
        if not documents:
            callout("Upload your notes on the right first, then ask questions here.", "blue", "arrow")
        else:
            names = {d["id"]: d["filename"] for d in documents}
            scope = st.multiselect(
                "Search in", options=list(names), format_func=names.get, placeholder="All documents",
            )
            history = st.container(height=480, border=False)
            question = st.chat_input("Ask a question about your notes")

            with history:
                if not st.session_state.qa_history and not question:
                    html('<div class="pa-empty" style="margin-top:1rem">Try one of these, or type '
                         "your own question below.</div>")
                    suggestion = st.pills(
                        "Suggestions", [f"Explain {n}" for n in suggested_topics(4)],
                        label_visibility="collapsed", key="qa_suggestion",
                    )
                    if suggestion:
                        question = suggestion
                for turn in st.session_state.qa_history:
                    with st.chat_message("user", avatar=":material/person:"):
                        st.markdown(turn["question"])
                    with st.chat_message("assistant", avatar=":material/school:"):
                        show_answer(turn["answer"])
                        show_weak_topic(turn.get("weak_topic"))
                if question:
                    ask(question, scope)

            if st.session_state.qa_history and st.button("Clear chat", icon=":material/delete_sweep:"):
                st.session_state.qa_history = []
                st.session_state.pop("qa_suggestion", None)
                st.rerun()
