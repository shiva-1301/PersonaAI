"""PersonaAI: Streamlit entry point (login + navigation)."""

import streamlit as st

from core import config, db, llm

st.set_page_config(page_title="PersonaAI", page_icon="🎓", layout="wide")
db.init_db()


def login_form() -> None:
    st.title("🎓 PersonaAI")
    st.caption("An adaptive AI study assistant that learns what you don't know yet.")
    with st.form("login"):
        username = st.text_input("Username", max_chars=40, placeholder="e.g. vivek")
        submitted = st.form_submit_button("Continue", type="primary")
    if submitted:
        if not username.strip():
            st.error("Please enter a username.")
            return
        user = db.get_or_create_user(username)
        st.session_state.user_id = user["id"]
        st.session_state.username = user["username"]
        st.rerun()


def sidebar() -> None:
    with st.sidebar:
        st.write(f"Signed in as **{st.session_state.username}**")
        st.caption(f"Model: {llm.active_model()}")
        if st.button("Log out"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()


def home() -> None:
    st.title(f"Welcome, {st.session_state.username} 👋")
    st.write(
        "Upload your course material, ask questions about it, take quizzes, "
        "and get a study plan that focuses on your weak topics."
    )

    st.subheader("LLM connection test")
    provider = st.radio(
        "Provider",
        ["gemini", "ollama"],
        index=0 if config.LLM_PROVIDER == "gemini" else 1,
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


if "user_id" not in st.session_state:
    login_form()
else:
    sidebar()
    home()
