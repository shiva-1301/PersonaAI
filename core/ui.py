"""Streamlit helpers shared by all pages."""

import streamlit as st

from core import db, llm


def require_login() -> int:
    """Stop the page unless a user is signed in; return their user id."""
    db.init_db()
    if "user_id" not in st.session_state:
        st.warning("Please sign in first: open **app** at the top of the sidebar.")
        st.stop()
    sidebar()
    return st.session_state.user_id


def sidebar() -> None:
    with st.sidebar:
        st.write(f"Signed in as **{st.session_state.username}**")
        st.caption(f"Model: {llm.active_model()}")
        if st.button("Log out"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
