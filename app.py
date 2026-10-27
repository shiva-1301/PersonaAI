"""PersonaAI: Streamlit entry point. Shows the sign-in card, then routes between pages.

Run with:  streamlit run app.py
"""

from html import escape

import streamlit as st

from core import auth, db
from ui import shell
from ui.styles import html, inject_css

st.set_page_config(page_title="PersonaAI", page_icon="🎓", layout="wide")
db.init_db()
inject_css()  # every page renders inside this run, so this styles all of them


def _start_session(account: auth.Account) -> None:
    st.session_state.pop("first_login", None)
    st.session_state.user_id = account.user_id
    st.session_state.username = account.username
    st.session_state.full_name = account.full_name
    st.session_state.role = account.role
    st.session_state.cohort_id = account.cohort_id
    st.rerun()


def _first_password_form(ticket: str) -> None:
    """A registered student's first sign-in: they choose their password."""
    html(f'<div class="pa-login-tag">First sign-in for <b>{escape(ticket)}</b>. '
         "Choose a password you'll use from now on.</div>")
    with st.form("set_password", border=False):
        password = st.text_input("New password", type="password",
                                 help=f"At least {auth.MIN_PASSWORD_LENGTH} characters.")
        confirm = st.text_input("Confirm password", type="password")
        submitted = st.form_submit_button("Set password and continue", type="primary",
                                          use_container_width=True)
    if submitted:
        try:
            account = auth.set_first_password(ticket, password, confirm)
        except auth.AuthError as exc:
            st.error(str(exc))
            return
        _start_session(account)
    if st.button("Use a different hall ticket number", type="tertiary", use_container_width=True):
        st.session_state.pop("first_login", None)
        st.rerun()


def login_page() -> None:
    """Centred sign-in card. No sidebar: nothing is rendered into it before login."""
    _, middle, _ = st.columns([1, 1.2, 1])
    with middle:
        html('<div style="height:7vh"></div>')
        with st.container(key="login_card"):
            html('<div class="pa-login-logo"><div class="pa-logo-mark">🎓</div></div>'
                 '<div class="pa-login-title">PersonaAI</div>'
                 "<div class=\"pa-login-tag\">The study assistant that learns what you don't know yet.</div>")
            if "first_login" in st.session_state:
                _first_password_form(st.session_state.first_login)
                return
            with st.form("login", border=False):
                username = st.text_input("Hall ticket number", max_chars=40)
                password = st.text_input("Password", type="password",
                                         help="Signing in for the first time? Leave it empty.")
                submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)
            if submitted:
                if not username.strip():
                    st.error("Please enter your hall ticket number.")
                    return
                try:
                    account = auth.sign_in(username, password)
                except auth.PasswordNotSet:
                    st.session_state.first_login = db.find_user(username)["username"]
                    st.rerun()
                except auth.AuthError as exc:
                    st.error(str(exc))
                    return
                _start_session(account)
            st.caption("Your department registers your hall ticket number. "
                       "On your first sign-in you choose a password.")


if "user_id" not in st.session_state:
    page = st.navigation([st.Page(login_page, title="Sign in", icon="🎓")], position="hidden")
else:
    app_pages = shell.pages(st.session_state.get("role", "student"))
    page = st.navigation(app_pages, position="hidden")
    shell.sidebar(app_pages, page)
page.run()
