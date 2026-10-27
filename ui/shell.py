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
ADMIN_PAGES = [
    ("views/admin.py", "Admin", ":material/admin_panel_settings:", "admin"),
]


def pages(role: str = "student") -> list:
    registry = ADMIN_PAGES if role == "admin" else PAGES
    return [
        st.Page(path, title=title, icon=icon, url_path=url, default=(i == 0))
        for i, (path, title, icon, url) in enumerate(registry)
    ]


def cohort_label(cohort_id: int | None) -> str:
    cohort = db.get_cohort(cohort_id) if cohort_id else None
    return f"{cohort['department']} · Year {cohort['year']}" if cohort else ""


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
            name = st.session_state.get("full_name") or st.session_state.username
            if st.session_state.get("role") == "admin":
                detail = "Administrator"
            else:
                detail = " · ".join(x for x in (st.session_state.username if name != st.session_state.username
                                                else "", cohort_label(st.session_state.get("cohort_id"))) if x)
            html(
                '<div class="pa-profile">'
                f'<div class="pa-avatar">{escape(name[:1].upper())}</div><div style="min-width:0">'
                f'<div class="pa-profile-small">Signed in as</div><div class="pa-profile-name">{escape(name)}</div>'
                + (f'<div class="pa-profile-small">{escape(detail)}</div>' if detail else "")
                + "</div></div>"
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


def require_admin() -> int:
    """Like require_login(), but only for the admin account."""
    user_id = require_login()
    if st.session_state.get("role") != "admin":
        st.warning("This page is for the admin only.")
        st.stop()
    return user_id


@st.cache_resource(show_spinner="Loading the search models (first time only, ~30s)...")
def _load_models() -> bool:
    rag.warm_up()
    return True


def load_models() -> None:
    """Load the embedding + reranking models once per server process."""
    _load_models()
