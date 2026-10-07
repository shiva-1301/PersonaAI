"""Upload documents + ask questions about them."""

import streamlit as st

from core import db, ingest, llm, rag
from core.documents import SUPPORTED_TYPES, DocumentError
from core.ui import require_login

st.set_page_config(page_title="Notes Q&A · PersonaAI", page_icon="📚", layout="wide")
user_id = require_login()

st.title("📚 Notes Q&A")
st.caption("Answers come only from your uploaded notes, with the file and page they came from.")

st.session_state.setdefault("qa_history", [])


@st.cache_resource(show_spinner="Loading the search models (first time only, ~30s)...")
def _load_models() -> bool:
    rag.warm_up()
    return True


_load_models()

documents = db.list_documents(user_id)
ask_tab, docs_tab = st.tabs(["💬 Ask", f"📄 My documents ({len(documents)})"])


# --- Documents tab ---

def process_uploads(files, subject: str) -> list[tuple[str, str]]:
    """Ingest each file; return (level, message) pairs to show after the page reloads."""
    messages = []
    progress = st.progress(0.0)
    for i, file in enumerate(files):
        progress.progress(i / len(files), text=f"Processing {file.name} (extract, embed, find topics)...")
        try:
            result = ingest.ingest(user_id, file.name, file.getvalue(), subject or None)
        except DocumentError as exc:
            messages.append(("error", str(exc)))
            continue
        except Exception as exc:
            messages.append(("error", f"{file.name}: processing failed ({exc})"))
            continue
        pages = f"{result.pages} pages" if result.pages else "text"
        messages.append(
            ("success", f"{file.name}: {pages}, {result.chunks} chunks, {len(result.topics)} topics")
        )
        if result.warning:
            messages.append(("warning", f"{file.name}: {result.warning}"))
    progress.empty()
    return messages


with docs_tab:
    with st.form("upload", clear_on_submit=True, border=True):
        files = st.file_uploader(
            "Upload course material",
            type=list(SUPPORTED_TYPES),
            accept_multiple_files=True,
            help="Text-based PDF, DOCX or TXT. Re-uploading a file with the same name replaces it.",
        )
        subject = st.text_input("Subject (optional)", placeholder="e.g. Big Data")
        submitted = st.form_submit_button("Process files", type="primary")
    if submitted:
        if not files:
            st.error("Choose at least one file first.")
        else:
            st.session_state.upload_messages = process_uploads(files, subject)
            st.rerun()
    for level, message in st.session_state.pop("upload_messages", []):
        getattr(st, level)(message)

    if not documents:
        st.info("No documents yet. Upload your notes above to get started.")
    for doc in documents:
        topics = db.list_topics(user_id, doc["id"])
        pages = f"{doc['page_count']} pages · " if doc["page_count"] else ""
        subject_tag = f" · {doc['subject']}" if doc["subject"] else ""
        with st.expander(f"**{doc['filename']}** — {pages}{len(topics)} topics{subject_tag}"):
            edited = st.text_area(
                "Topics (one per line, edit if any are wrong)",
                "\n".join(t["name"] for t in topics),
                height=200,
                key=f"topics_{doc['id']}",
            )
            col1, col2, _ = st.columns([1, 1, 3])
            if col1.button("Save topics", key=f"save_{doc['id']}"):
                db.set_topics(user_id, doc["id"], edited.splitlines())
                st.toast("Topics saved.")
                st.rerun()
            if col2.button("Delete document", key=f"del_{doc['id']}", type="secondary"):
                ingest.remove(user_id, doc["id"])
                st.toast(f"Deleted {doc['filename']}.")
                st.rerun()


# --- Ask tab ---

def show_answer(answer: rag.Answer) -> None:
    if not answer.found:
        st.info(answer.text)
        return
    st.markdown(answer.text)
    if answer.sources:
        st.caption("Sources: " + " · ".join(f"[S{s.number}] {s.label}" for s in answer.sources))
        with st.expander("Show source excerpts"):
            for s in answer.sources:
                st.markdown(f"**[S{s.number}] {s.label}**")
                st.caption(s.excerpt)


with ask_tab:
    if not documents:
        st.info("Upload your notes in the **My documents** tab first, then ask questions here.")
    else:
        names = {d["id"]: d["filename"] for d in documents}
        scope = st.multiselect(
            "Search in",
            options=list(names),
            format_func=names.get,
            placeholder="All documents",
        )

        for turn in st.session_state.qa_history:
            with st.chat_message("user"):
                st.markdown(turn["question"])
            with st.chat_message("assistant"):
                show_answer(turn["answer"])

        question = st.chat_input("Ask a question about your notes")
        if question:
            with st.chat_message("user"):
                st.markdown(question)
            with st.chat_message("assistant"):
                with st.spinner("Searching your notes..."):
                    try:
                        answer = rag.answer(user_id, question, document_ids=scope or None)
                    except llm.LLMError:
                        st.error(
                            "The AI service isn't responding right now (Gemini may be busy and "
                            "Ollama isn't reachable). Please try again in a minute."
                        )
                        st.stop()
                show_answer(answer)
            st.session_state.qa_history.append({"question": question, "answer": answer})

        if st.session_state.qa_history and st.button("Clear chat"):
            st.session_state.qa_history = []
            st.rerun()
