"""PersonaAI: Streamlit entry point. Shows the sign-in card, then routes between pages.

Run with:  streamlit run app.py
"""

import streamlit as st

from core import db
from ui import shell
from ui.styles import html, inject_css

st.set_page_config(page_title="PersonaAI", page_icon="🎓", layout="wide")
db.init_db()
inject_css()  # every page renders inside this run, so this styles all of them


def login_page() -> None:
    """Centred sign-in card. No sidebar: nothing is rendered into it before login."""
    _, middle, _ = st.columns([1, 1.2, 1])
    with middle:
        html('<div style="height:7vh"></div>')
        with st.container(key="login_card"):
            html('<div class="pa-login-logo"><div class="pa-logo-mark">🎓</div></div>'
                 '<div class="pa-login-title">PersonaAI</div>'
                 "<div class=\"pa-login-tag\">The study assistant that learns what you don't know yet.</div>")
            with st.form("login", border=False):
                username = st.text_input("Username", max_chars=40, placeholder="e.g. vivek")
                submitted = st.form_submit_button("Continue", type="primary", use_container_width=True)
            if submitted:
                if not username.strip():
                    st.error("Please enter a username.")
                    return
                user = db.get_or_create_user(username)
                st.session_state.user_id = user["id"]
                st.session_state.username = user["username"]
                st.rerun()
            st.caption("New here? Any username creates your own private study space.")


if "user_id" not in st.session_state:
    page = st.navigation([st.Page(login_page, title="Sign in", icon="🎓")], position="hidden")
else:
    app_pages = shell.pages()
    page = st.navigation(app_pages, position="hidden")
    shell.sidebar(app_pages, page)
page.run()
