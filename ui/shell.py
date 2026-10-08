"""App shell: page registry, custom sidebar, login guard, model warm-up."""

import streamlit as st

from core import db, llm, rag
from ui.styles import active_nav_css, html, logo
from html import escape

# (file, title, Material icon, URL path). Order = sidebar order.
PAGES = [
    ("views/home.py", "Home", ":material/space_dashboard:", "home"),
    ("views/notes_qa.py", "Notes Q&A", ":material/forum:", "notes"),
    ("views/quiz.py", "Quiz", ":material/quiz:", "quiz"),
    ("views/progress.py", "Progress", ":material/monitoring:", "progress"),
    ("views/study_plan.py", "Study Plan", ":material/event_note:", "plan"),
]


def pages() -> list:
    return [
        st.Page(path, title=title, icon=icon, url_path=url, default=(i == 0))
        for i, (path, title, icon, url) in enumerate(PAGES)
    ]


def sidebar(nav_pages: list, current) -> None:
    """Logo, icon navigation (current page highlighted), and the signed-in user's card."""
    with st.sidebar:
        html(logo())
        html('<div class="pa-nav-label">Menu</div>')
        for page in nav_pages:
            with st.container(key=f"nav_{page.url_path or 'home'}"):
                st.page_link(page)
        active_nav_css(current.url_path or "home")
        with st.container(key="profile"):
            name = st.session_state.username
            html(
                '<div class="pa-profile">'
                f'<div class="pa-avatar">{escape(name[:1].upper())}</div><div style="min-width:0">'
                f'<div class="pa-profile-small">Signed in as</div><div class="pa-profile-name">{escape(name)}</div>'
                "</div></div>"
            )
            st.caption(f"AI model: {llm.active_model().split(' / ')[-1]}")
            if st.button("Log out", icon=":material/logout:", use_container_width=True):
                for key in list(st.session_state.keys()):
                    del st.session_state[key]
                st.rerun()


def require_login() -> int:
    """Stop the page unless a user is signed in; return their user id.
    (The router in app.py only offers pages after login; this guards direct runs.)"""
    db.init_db()
    if "user_id" not in st.session_state:
        st.warning("Please sign in first.")
        st.stop()
    return st.session_state.user_id


@st.cache_resource(show_spinner="Loading the search models (first time only, ~30s)...")
def _load_models() -> bool:
    rag.warm_up()
    return True


def load_models() -> None:
    """Load the embedding + reranking models once per server process."""
    _load_models()
