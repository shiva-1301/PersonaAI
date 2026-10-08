"""Shared look & feel: one CSS block plus small HTML helpers for the pieces Streamlit
doesn't have natively (hero banner, stat tiles, badges, chips, callouts).

Every page calls inject_css() once. Selectors target data-testid attributes and the
`st-key-<key>` classes Streamlit adds to keyed containers, not generated class names.
Anything user-provided (file names, topic names) goes through _esc() before it is put
into HTML.
"""

from dataclasses import dataclass
from html import escape as _esc

import streamlit as st

# Colours shared with .streamlit/config.toml and core/charts.py. The accent hues are the
# dataviz reference palette's first categorical slots, validated for colour-blind safety.
PALETTE = {
    "bg": "#F5F7FB",
    "card": "#FFFFFF",
    "border": "#E6EAF2",
    "text": "#1B2559",
    "muted": "#6B7A99",
    "primary": "#2A78D6",
    "primary_dark": "#1C5CAB",
    "aqua": "#1BAF7A",
    "orange": "#EB6834",
    "violet": "#4A3AA7",
    "yellow": "#EDA100",
    "good": "#0CA30C",
    "warning": "#FAB219",
    "critical": "#D03B3B",
}

# tone -> (text/icon colour, soft background)
TONES = {
    "blue": ("#1C5CAB", "#E8F1FC"),
    "aqua": ("#0E7A54", "#E4F7EF"),
    "orange": ("#B4461C", "#FDEEE7"),
    "violet": ("#4A3AA7", "#EEECFA"),
    "yellow": ("#8A5D00", "#FDF4DC"),
    "good": ("#0A7A0A", "#E6F6E6"),
    "warning": ("#8A5D00", "#FEF5E1"),
    "critical": ("#B02E2E", "#FCEAEA"),
    "gray": ("#52607A", "#EEF1F6"),
}

_CSS = f"""
<style>
/* ---- Chrome: hide toolbar/deploy/footer, keep the sidebar toggle usable on mobile ---- */
[data-testid="stToolbar"], [data-testid="stDecoration"], footer {{ display: none !important; }}
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stMainBlockContainer"] {{ padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1240px; }}

/* ---- Typography ---- */
h1, h2, h3, h4 {{ color: {PALETTE["text"]}; letter-spacing: -0.01em; }}
.pa-muted {{ color: {PALETTE["muted"]}; }}

/* ---- Cards: containers made with card() (key "card_...") become white rounded cards ---- */
[class*="st-key-card_"] {{
    background: {PALETTE["card"]};
    border: 1px solid {PALETTE["border"]} !important;
    border-radius: 16px;
    box-shadow: 0 1px 2px rgba(27, 37, 89, .04), 0 4px 16px rgba(27, 37, 89, .05);
}}
[data-testid="stExpander"] details {{ background: {PALETTE["card"]}; border-radius: 12px; }}

/* ---- Page header ---- */
.pa-header {{ margin: 0 0 1.25rem 0; }}
.pa-title {{ font-family: Poppins, sans-serif; font-weight: 700; font-size: 1.75rem !important;
    color: {PALETTE["text"]}; line-height: 1.25 !important; }}
.pa-header-sub {{ color: {PALETTE["muted"]}; margin: .25rem 0 0 0; font-size: .95rem !important; }}
.pa-section {{ font-family: Poppins, sans-serif; font-weight: 600; font-size: 1.05rem !important;
    color: {PALETTE["text"]}; margin: 0 0 .15rem 0; }}
.pa-section-sub {{ color: {PALETTE["muted"]}; font-size: .85rem !important; margin: 0 0 .6rem 0; }}

/* ---- Hero banner (a keyed container, so its button stays a real Streamlit button) ---- */
.st-key-hero {{
    background: linear-gradient(120deg, {PALETTE["primary"]} 0%, #3B8FE8 45%, {PALETTE["aqua"]} 100%);
    border-radius: 20px; padding: 2rem 2.2rem 1.6rem 2.2rem; color: #fff;
    box-shadow: 0 10px 30px rgba(42, 120, 214, .25); position: relative; overflow: hidden;
}}
.st-key-hero::after {{
    content: ""; position: absolute; right: -60px; top: -60px; width: 260px; height: 260px;
    border-radius: 50%; background: rgba(255, 255, 255, .10); pointer-events: none;
}}
.pa-hero-kicker {{ text-transform: uppercase; letter-spacing: .08em; font-size: .75rem !important;
    font-weight: 600; opacity: .85; margin: 0; }}
.pa-hero-title {{ font-family: Poppins, sans-serif; font-size: 2rem !important; font-weight: 700;
    line-height: 1.2 !important; margin: .3rem 0 .4rem 0; color: #fff; }}
.pa-hero-text {{ font-size: 1rem !important; opacity: .92; max-width: 640px; margin: 0 0 1rem 0; }}
.st-key-hero [data-testid="stButton"] button,
.st-key-hero [data-testid="stPageLink"] a {{
    background: #fff; color: {PALETTE["primary_dark"]}; border: none; font-weight: 600;
    box-shadow: 0 4px 12px rgba(0, 0, 0, .12);
}}
.st-key-hero [data-testid="stButton"] button:hover {{ background: #F1F6FD; color: {PALETTE["primary_dark"]}; }}

/* ---- Stat tiles ---- */
.pa-stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
    gap: 1rem; margin: .25rem 0 1.25rem 0; }}
.pa-stat {{ background: {PALETTE["card"]}; border: 1px solid {PALETTE["border"]}; border-radius: 16px;
    padding: 1rem 1.1rem; display: flex; gap: .9rem; align-items: center;
    box-shadow: 0 1px 2px rgba(27, 37, 89, .04), 0 4px 16px rgba(27, 37, 89, .05); }}
.pa-stat-icon {{ width: 46px; height: 46px; border-radius: 12px; flex: 0 0 46px; display: flex;
    align-items: center; justify-content: center; font-size: 1.35rem !important; }}
.pa-stat-label {{ color: {PALETTE["muted"]}; font-size: .8rem !important; font-weight: 500; margin: 0; }}
.pa-stat-value {{ font-family: Poppins, sans-serif; font-size: 1.5rem !important; font-weight: 700;
    color: {PALETTE["text"]}; line-height: 1.2 !important; margin: 0; }}
.pa-stat-caption {{ color: {PALETTE["muted"]}; font-size: .75rem !important; margin: 0; }}

/* ---- Badges & chips ---- */
.pa-badge {{ display: inline-flex; align-items: center; gap: .3rem; padding: .15rem .55rem;
    border-radius: 999px; font-size: .75rem !important; font-weight: 600; white-space: nowrap;
    margin: 0 .3rem .3rem 0; }}
.pa-chips {{ display: flex; flex-wrap: wrap; gap: .4rem; margin: .2rem 0 .4rem 0; }}
.pa-chip {{ display: inline-flex; align-items: center; gap: .35rem; padding: .3rem .7rem;
    border-radius: 999px; font-size: .82rem !important; font-weight: 500; }}
.pa-chip b {{ font-weight: 700; }}

.pa-empty {{ color: {PALETTE["muted"]}; font-size: .88rem !important; margin: .1rem 0 .5rem 0; }}
.pa-row {{ display: flex; justify-content: space-between; align-items: center; gap: .8rem;
    padding: .5rem 0; border-bottom: 1px solid #EEF1F6; font-size: .92rem !important; }}
.pa-row:last-child {{ border-bottom: none; }}

/* ---- Document list (Notes Q&A) ---- */
.pa-doc {{ display: flex; gap: .75rem; align-items: flex-start; padding-top: .35rem; }}
.pa-doc-icon {{ width: 38px; height: 38px; flex: 0 0 38px; border-radius: 10px; display: flex;
    align-items: center; justify-content: center; background: {TONES["blue"][1]}; font-size: 1.1rem !important; }}
.pa-doc-name {{ font-weight: 600; color: {PALETTE["text"]}; font-size: .92rem !important;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.pa-doc-meta {{ color: {PALETTE["muted"]}; font-size: .78rem !important; margin-bottom: .25rem; }}
[data-testid="stChatMessage"] {{ background: transparent; padding: .6rem .2rem; }}

/* ---- Study plan timeline ---- */
.pa-date {{ border-radius: 12px; text-align: center; padding: .35rem .2rem; line-height: 1.1 !important; }}
.pa-date-dow {{ font-size: .68rem !important; text-transform: uppercase; letter-spacing: .06em; font-weight: 600; }}
.pa-date-num {{ font-family: Poppins, sans-serif; font-size: 1.35rem !important; font-weight: 700; }}
.pa-date-mon {{ font-size: .72rem !important; }}
[class*="st-key-card_day_"][class*="_today"] {{ border: 1.5px solid {PALETTE["primary"]} !important;
    box-shadow: 0 6px 20px rgba(42, 120, 214, .15); }}

/* ---- Callouts ---- */
.pa-callout {{ display: flex; gap: .7rem; align-items: flex-start; padding: .75rem .9rem;
    border-radius: 12px; font-size: .9rem !important; margin: .3rem 0 .6rem 0; }}

/* ---- Sidebar ---- */
[data-testid="stSidebar"] {{ box-shadow: 1px 0 0 {PALETTE["border"]}; }}
[data-testid="stSidebarHeader"] {{ padding-bottom: 0; height: 2.2rem; }}
.pa-logo {{ display: flex; align-items: center; gap: .65rem; padding: 0 .25rem 1rem .25rem; }}
.pa-logo-mark {{ width: 40px; height: 40px; border-radius: 12px; display: flex; align-items: center;
    justify-content: center; font-size: 1.3rem !important; color: #fff;
    background: linear-gradient(135deg, {PALETTE["primary"]}, {PALETTE["aqua"]}); }}
.pa-logo-name {{ font-family: Poppins, sans-serif; font-weight: 700; font-size: 1.15rem !important;
    color: {PALETTE["text"]}; margin: 0; line-height: 1.1 !important; }}
.pa-logo-tag {{ font-size: .72rem !important; color: {PALETTE["muted"]}; margin: 0; }}
.pa-nav-label {{ text-transform: uppercase; letter-spacing: .08em; font-size: .68rem !important;
    color: {PALETTE["muted"]}; font-weight: 600; margin: .4rem .5rem .3rem .5rem; }}
[data-testid="stSidebar"] [data-testid="stPageLink"] a {{ border-radius: 10px; padding: .45rem .7rem; }}
[data-testid="stSidebar"] [data-testid="stPageLink"] a:hover {{ background: {TONES["blue"][1]}; }}
[data-testid="stSidebar"] [class*="st-key-nav_"] {{ gap: 0; }}
.st-key-profile {{ background: {PALETTE["bg"]}; border: 1px solid {PALETTE["border"]};
    border-radius: 14px; padding: .8rem; margin-top: 1.5rem; }}
.pa-profile {{ display: flex; gap: .7rem; align-items: center; }}
.pa-avatar {{ width: 40px; height: 40px; border-radius: 50%; flex: 0 0 40px; display: flex;
    align-items: center; justify-content: center; color: #fff; font-weight: 700;
    font-family: Poppins, sans-serif; background: linear-gradient(135deg, {PALETTE["violet"]}, {PALETTE["primary"]}); }}
.pa-profile-small {{ font-size: .72rem !important; color: {PALETTE["muted"]}; margin: 0; }}
.pa-profile-name {{ font-weight: 600; color: {PALETTE["text"]}; margin: 0; font-size: .95rem !important;
    overflow: hidden; text-overflow: ellipsis; }}

/* ---- Login ---- */
.st-key-login_card {{ background: {PALETTE["card"]}; border: 1px solid {PALETTE["border"]};
    border-radius: 20px; padding: 2.2rem 2rem 1.6rem 2rem;
    box-shadow: 0 10px 40px rgba(27, 37, 89, .08); }}
.pa-login-logo {{ display: flex; justify-content: center; margin-bottom: .6rem; }}
.pa-login-logo .pa-logo-mark {{ width: 56px; height: 56px; font-size: 1.8rem !important; border-radius: 16px; }}
.pa-login-title {{ text-align: center; font-family: Poppins, sans-serif; font-weight: 700;
    font-size: 1.6rem !important; color: {PALETTE["text"]}; margin: 0; }}
.pa-login-tag {{ text-align: center; color: {PALETTE["muted"]}; font-size: .92rem !important; margin: .3rem 0 1.2rem 0; }}

/* ---- Quiz options look like answer buttons (stRadioGroup > div > label[stRadioOption]) ---- */
.st-key-question [data-testid="stElementContainer"]:has([data-testid="stRadio"]),
.st-key-question [data-testid="stRadio"] {{ width: 100% !important; max-width: 100% !important; }}
.st-key-question [data-testid="stRadioGroup"] {{ display: flex; flex-direction: column; gap: .55rem; width: 100%; }}
.st-key-question [data-testid="stRadioGroup"] > div {{ width: 100%; }}
.st-key-question [data-testid="stRadioOption"] {{
    width: 100%; margin: 0; padding: .75rem 1rem; border: 1.5px solid {PALETTE["border"]};
    border-radius: 12px; background: {PALETTE["card"]}; cursor: pointer;
    transition: border-color .15s, background .15s;
}}
.st-key-question [data-testid="stRadioOption"]:hover {{ border-color: {PALETTE["primary"]}; }}
.st-key-question [data-testid="stRadioOption"][data-selected="true"] {{
    border-color: {PALETTE["primary"]}; background: {TONES["blue"][1]};
}}
.st-key-question [data-testid="stRadioOption"] p {{ font-size: .95rem !important; }}

/* ---- Quiz text ---- */
.pa-question {{ font-family: Poppins, sans-serif; font-weight: 600; font-size: 1.15rem !important;
    color: {PALETTE["text"]}; line-height: 1.45 !important; margin: .5rem 0 .8rem 0; }}
.pa-answer {{ border-radius: 10px; padding: .5rem .75rem; margin: .3rem 0; font-size: .9rem !important; }}
.pa-answer-good {{ background: {TONES["good"][1]}; color: {TONES["good"][0]}; }}
.pa-answer-bad {{ background: {TONES["critical"][1]}; color: {TONES["critical"][0]}; }}
.pa-answer-bad s {{ text-decoration-thickness: 1px; }}

/* ---- Narrow screens ---- */
@media (max-width: 640px) {{
    [data-testid="stMainBlockContainer"] {{ padding-left: 1rem; padding-right: 1rem; }}
    .st-key-hero {{ padding: 1.4rem 1.2rem 1.2rem 1.2rem; }}
    .pa-hero-title {{ font-size: 1.5rem !important; }}
    .pa-stats {{ grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .6rem; }}
    .pa-stat {{ padding: .75rem; gap: .6rem; }}
    .pa-stat-icon {{ width: 36px; height: 36px; flex-basis: 36px; font-size: 1.1rem !important; }}
    .pa-stat-value {{ font-size: 1.2rem !important; }}
}}
</style>
"""


def card(name: str):
    """A white rounded card: `with card("plan"): ...`. The key gives it a stable CSS class."""
    return st.container(border=True, key=f"card_{name}")


def active_nav_css(url_path: str) -> None:
    """Highlight the current page's sidebar link (its container is keyed nav_<url_path>)."""
    html(
        f"<style>.st-key-nav_{url_path} a {{ background: {TONES['blue'][1]} !important;"
        f" box-shadow: inset 3px 0 0 {PALETTE['primary']}; }}"
        f".st-key-nav_{url_path} a span, .st-key-nav_{url_path} a p"
        f" {{ color: {PALETTE['primary_dark']} !important; font-weight: 600 !important; }}</style>"
    )


def inject_css() -> None:
    """Add the shared stylesheet to the current page (call once per run)."""
    st.markdown(_CSS, unsafe_allow_html=True)


def html(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def page_header(title: str, subtitle: str = "") -> None:
    sub = f'<div class="pa-header-sub">{_esc(subtitle)}</div>' if subtitle else ""
    html(f'<div class="pa-header"><div class="pa-title">{_esc(title)}</div>{sub}</div>')


def section(title: str, subtitle: str = "") -> None:
    """A card's title line."""
    html(f'<div class="pa-section">{_esc(title)}</div>'
         + (f'<div class="pa-section-sub">{_esc(subtitle)}</div>' if subtitle else ""))


def hero_text(kicker: str, title: str, text: str) -> None:
    """Text for the hero banner; render it inside `st.container(key="hero")`."""
    html(
        f'<div class="pa-hero-kicker">{_esc(kicker)}</div>'
        f'<div class="pa-hero-title">{_esc(title)}</div>'
        f'<div class="pa-hero-text">{_esc(text)}</div>'
    )


@dataclass
class Stat:
    label: str
    value: str
    icon: str
    tone: str = "blue"
    caption: str = ""


def stat_row(stats: list[Stat]) -> None:
    """A responsive row of stat tiles (wraps to 2 per row on phones)."""
    tiles = []
    for s in stats:
        fg, bg = TONES[s.tone]
        caption = f'<div class="pa-stat-caption">{_esc(s.caption)}</div>' if s.caption else ""
        tiles.append(
            f'<div class="pa-stat"><div class="pa-stat-icon" style="background:{bg};color:{fg}">{s.icon}</div>'
            f'<div><div class="pa-stat-label">{_esc(s.label)}</div><div class="pa-stat-value">{_esc(s.value)}</div>'
            f"{caption}</div></div>"
        )
    html(f'<div class="pa-stats">{"".join(tiles)}</div>')


def badge(text: str, tone: str = "gray", icon: str = "") -> str:
    """Small pill, returned as HTML so several can share one line."""
    fg, bg = TONES[tone]
    return f'<span class="pa-badge" style="background:{bg};color:{fg}">{icon}{_esc(text)}</span>'


def chips(items: list[tuple[str, str]], empty: str = "") -> None:
    """A wrapping row of (text, tone) chips."""
    if not items:
        if empty:
            html(f'<div class="pa-empty">{_esc(empty)}</div>')
        return
    html('<div class="pa-chips">' + "".join(chip(t, tone) for t, tone in items) + "</div>")


def row(left_html: str, right_html: str) -> str:
    """One line of a list inside a card: content on the left, badges on the right."""
    return f'<div class="pa-row"><span>{left_html}</span><span>{right_html}</span></div>'


def chip(text: str, tone: str = "gray") -> str:
    fg, bg = TONES[tone]
    return f'<span class="pa-chip" style="background:{bg};color:{fg}">{_esc(text)}</span>'


def callout(text: str, tone: str = "blue", icon: str = "💡", bold: str = "") -> None:
    """A tinted note. `bold` is an optional emphasised lead-in."""
    fg, bg = TONES[tone]
    lead = f"<b>{_esc(bold)}</b> " if bold else ""
    html(f'<div class="pa-callout" style="background:{bg};color:{fg}"><span>{icon}</span>'
         f"<span>{lead}{_esc(text)}</span></div>")


def logo(tagline: str = "Study assistant") -> str:
    return (
        '<div class="pa-logo"><div class="pa-logo-mark">🎓</div><div>'
        f'<div class="pa-logo-name">PersonaAI</div><div class="pa-logo-tag">{_esc(tagline)}</div></div></div>'
    )
