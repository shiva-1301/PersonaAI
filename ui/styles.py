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
    border-radius: 2px;
    box-shadow: 0 1px 2px rgba(27, 37, 89, .05);
}}
[data-testid="stExpander"] details {{ background: {PALETTE["card"]}; border-radius: 2px; }}

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
    background: {PALETTE["text"]}; border-left: 4px solid {PALETTE["primary"]};
    border-radius: 2px; padding: 1.8rem 2.2rem 1.5rem 2.2rem; color: #fff;
}}
.pa-hero-kicker {{ text-transform: uppercase; letter-spacing: .08em; font-size: .75rem !important;
    font-weight: 600; opacity: .85; margin: 0; }}
.pa-hero-title {{ font-family: Poppins, sans-serif; font-size: 2rem !important; font-weight: 700;
    line-height: 1.2 !important; margin: .3rem 0 .4rem 0; color: #fff; }}
.pa-hero-text {{ font-size: 1rem !important; opacity: .92; max-width: 640px; margin: 0 0 1rem 0; }}
.st-key-hero [data-testid="stButton"] button,
.st-key-hero [data-testid="stPageLink"] a {{
    background: #fff; color: {PALETTE["text"]}; border: 1px solid #fff; font-weight: 600;
}}
.st-key-hero [data-testid="stButton"] button:hover {{ background: #E8EDF5; color: {PALETTE["text"]}; }}

/* ---- Stat tiles ---- */
.pa-stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
    gap: 1rem; margin: .25rem 0 1.25rem 0; }}
.pa-stat {{ background: {PALETTE["card"]}; border: 1px solid {PALETTE["border"]}; border-radius: 2px;
    padding: 1rem 1.1rem; display: flex; gap: .9rem; align-items: center;
    box-shadow: 0 1px 2px rgba(27, 37, 89, .05); }}
.pa-stat-icon {{ width: 42px; height: 42px; border-radius: 2px; flex: 0 0 42px; display: flex;
    align-items: center; justify-content: center; background: {PALETTE["bg"]};
    border: 1px solid {PALETTE["border"]}; color: {PALETTE["muted"]}; }}
.pa-stat-label {{ color: {PALETTE["muted"]}; font-size: .8rem !important; font-weight: 500; margin: 0; }}
.pa-stat-value {{ font-family: Poppins, sans-serif; font-size: 1.5rem !important; font-weight: 700;
    color: {PALETTE["text"]}; line-height: 1.2 !important; margin: 0; }}
.pa-stat-caption {{ color: {PALETTE["muted"]}; font-size: .75rem !important; margin: 0; }}

/* Pills (suggested questions) keep their own round shape unless told otherwise. */
[data-testid^="stBaseButton-pills"] {{ border-radius: 2px !important; }}

/* ---- Line icons (icon()): take the surrounding text colour ---- */
.pa-icon {{ display: inline-block; vertical-align: -0.18em; flex: 0 0 auto; }}

/* ---- Badges & chips ---- */
.pa-badge {{ display: inline-flex; align-items: center; gap: .3rem; padding: .15rem .55rem;
    border-radius: 2px; font-size: .75rem !important; font-weight: 600; white-space: nowrap;
    margin: 0 .3rem .3rem 0; }}
.pa-chips {{ display: flex; flex-wrap: wrap; gap: .4rem; margin: .2rem 0 .4rem 0; }}
.pa-chip {{ display: inline-flex; align-items: center; gap: .35rem; padding: .3rem .7rem;
    border-radius: 2px; font-size: .82rem !important; font-weight: 500; }}
.pa-chip b {{ font-weight: 700; }}

.pa-empty {{ color: {PALETTE["muted"]}; font-size: .88rem !important; margin: .1rem 0 .5rem 0; }}
.pa-row {{ display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center;
    gap: .3rem .8rem; padding: .5rem 0; border-bottom: 1px solid #EEF1F6; font-size: .92rem !important; }}
.pa-row > span:first-child {{ min-width: 0; overflow-wrap: anywhere; }}
.pa-row:last-child {{ border-bottom: none; }}

/* ---- Document list (Notes Q&A) ---- */
.pa-doc {{ display: flex; gap: .75rem; align-items: flex-start; padding-top: .35rem; }}
.pa-doc-icon {{ width: 38px; height: 38px; flex: 0 0 38px; border-radius: 2px; display: flex;
    align-items: center; justify-content: center; background: {PALETTE["bg"]};
    border: 1px solid {PALETTE["border"]}; color: {PALETTE["muted"]}; }}
.pa-doc-name {{ font-weight: 600; color: {PALETTE["text"]}; font-size: .92rem !important;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.pa-doc-meta {{ color: {PALETTE["muted"]}; font-size: .78rem !important; margin-bottom: .25rem; }}
[data-testid="stChatMessage"] {{ background: transparent; padding: .6rem .2rem; }}

/* ---- Study plan timeline ---- */
.pa-date {{ border-radius: 2px; text-align: center; padding: .35rem .2rem; line-height: 1.1 !important; }}
.pa-date-dow {{ font-size: .68rem !important; text-transform: uppercase; letter-spacing: .06em; font-weight: 600; }}
.pa-date-num {{ font-family: Poppins, sans-serif; font-size: 1.35rem !important; font-weight: 700; }}
.pa-date-mon {{ font-size: .72rem !important; }}
[class*="st-key-card_day_"][class*="_today"] {{ border: 1.5px solid {PALETTE["primary"]} !important;
    box-shadow: none; }}

/* ---- Callouts ---- */
.pa-callout {{ display: flex; gap: .7rem; align-items: flex-start; padding: .75rem .9rem;
    border-radius: 2px; font-size: .9rem !important; margin: .3rem 0 .6rem 0; }}

/* ---- Sidebar ---- */
[data-testid="stSidebar"] {{ box-shadow: 1px 0 0 {PALETTE["border"]}; }}
[data-testid="stSidebarHeader"] {{ padding-bottom: 0; height: 2.2rem; }}
.pa-logo {{ display: flex; align-items: center; gap: .65rem; padding: 0 .25rem 1rem .25rem; }}
.pa-logo-mark {{ width: 40px; height: 40px; border-radius: 2px; display: flex; align-items: center;
    justify-content: center; color: #fff;
    background: {PALETTE["primary"]}; }}
.pa-logo-name {{ font-family: Poppins, sans-serif; font-weight: 700; font-size: 1.15rem !important;
    color: {PALETTE["text"]}; margin: 0; line-height: 1.1 !important; }}
.pa-logo-tag {{ font-size: .72rem !important; color: {PALETTE["muted"]}; margin: 0; }}
.pa-nav-label {{ text-transform: uppercase; letter-spacing: .08em; font-size: .68rem !important;
    color: {PALETTE["muted"]}; font-weight: 600; margin: .4rem .5rem .3rem .5rem; }}
[data-testid="stSidebar"] [data-testid="stPageLink"] a {{ border-radius: 2px; padding: .45rem .7rem; }}
[data-testid="stSidebar"] [data-testid="stPageLink"] a:hover {{ background: {TONES["blue"][1]}; }}
[data-testid="stSidebar"] [class*="st-key-nav_"] {{ gap: 0; }}
.st-key-profile {{ background: {PALETTE["bg"]}; border: 1px solid {PALETTE["border"]};
    border-radius: 2px; padding: .8rem; margin-top: 1.5rem; }}
.pa-profile {{ display: flex; gap: .7rem; align-items: center; }}
.pa-avatar {{ width: 40px; height: 40px; border-radius: 2px; flex: 0 0 40px; display: flex;
    align-items: center; justify-content: center; color: #fff; font-weight: 700;
    font-family: Poppins, sans-serif; background: {PALETTE["text"]}; }}
.pa-profile-small {{ font-size: .72rem !important; color: {PALETTE["muted"]}; margin: 0; }}
.pa-profile-name {{ font-weight: 600; color: {PALETTE["text"]}; margin: 0; font-size: .95rem !important;
    overflow: hidden; text-overflow: ellipsis; }}

/* ---- Login ---- */
.st-key-login_card {{ background: {PALETTE["card"]}; border: 1px solid {PALETTE["border"]};
    border-radius: 2px; padding: 2.2rem 2rem 1.6rem 2rem;
    box-shadow: 0 1px 3px rgba(27, 37, 89, .08); }}
.pa-login-logo {{ display: flex; justify-content: center; margin-bottom: .6rem; }}
.pa-login-logo .pa-logo-mark {{ width: 52px; height: 52px; border-radius: 2px; }}
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
    border-radius: 2px; background: {PALETTE["card"]}; cursor: pointer;
    transition: border-color .15s, background .15s;
}}
.st-key-question [data-testid="stRadioOption"]:hover {{ border-color: {PALETTE["primary"]}; }}
.st-key-question [data-testid="stRadioOption"][data-selected="true"] {{
    border-color: {PALETTE["primary"]}; background: {TONES["blue"][1]};
}}
.st-key-question [data-testid="stRadioOption"] p {{ font-size: .95rem !important; }}
/* Keyboard users need to see which option / link has focus */
.st-key-question [data-testid="stRadioOption"]:has(input:focus-visible),
[data-testid="stSidebar"] [data-testid="stPageLink"] a:focus-visible {{
    outline: 2px solid {PALETTE["primary"]}; outline-offset: 2px;
}}
@media (prefers-reduced-motion: reduce) {{
    .st-key-question [data-testid="stRadioOption"] {{ transition: none; }}
}}

/* ---- Quiz text ---- */
.pa-question {{ font-family: Poppins, sans-serif; font-weight: 600; font-size: 1.15rem !important;
    color: {PALETTE["text"]}; line-height: 1.45 !important; margin: .5rem 0 .8rem 0; }}
.pa-answer {{ border-radius: 2px; padding: .5rem .75rem; margin: .3rem 0; font-size: .9rem !important; }}
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
    .pa-stat-icon {{ width: 34px; height: 34px; flex-basis: 34px; }}
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


# Line icons (24x24 grid, drawn with the current text colour), in the style of the Lucide set.
ICONS = {
    "file": '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z"/><path d="M14 2v5h6"/>'
            '<path d="M16 13H8M16 17H8M10 9H8"/>',
    "quiz": '<rect width="8" height="4" x="8" y="2" rx="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6'
            'a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><path d="m9 14 2 2 4-4"/>',
    "target": '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
    "alert": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/>'
             '<path d="M12 9v4M12 17h.01"/>',
    "book": '<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2zM22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>',
    "repeat": '<path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/>',
    "cap": '<path d="M22 10 12 5 2 10l10 5 10-5z"/><path d="M6 12v5c3 3 9 3 12 0v-5M22 10v6"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    "check-circle": '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
    "layers": '<path d="m12 2 10 5-10 5L2 7z"/><path d="m2 17 10 5 10-5M2 12l10 5 10-5"/>',
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
             '<path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
    "key": '<circle cx="7.5" cy="15.5" r="5.5"/><path d="m21 2-9.6 9.6M15.5 7.5l3 3L22 7l-3-3"/>',
    "info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
    "arrow": '<path d="M5 12h14M12 5l7 7-7 7"/>',
    "bookmark": '<path d="m19 21-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>',
    "search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    "cpu": '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/>'
           '<path d="M15 2v2M15 20v2M2 15h2M2 9h2M20 15h2M20 9h2M9 2v2M9 20v2"/>',
    "trend": '<path d="m22 7-8.5 8.5-5-5L2 17"/><path d="M16 7h6v6"/>',
    "award": '<circle cx="12" cy="8" r="6"/><path d="M15.48 12.89 17 22l-5-3-5 3 1.52-9.11"/>',
    "flag": '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1zM4 22v-7"/>',
    "calendar": '<rect width="18" height="18" x="3" y="4" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "x": '<path d="M18 6 6 18M6 6l12 12"/>',
}


def icon(name: str, size: int = 16) -> str:
    """An inline line icon from ICONS, as HTML."""
    return (f'<svg class="pa-icon" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
            f'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" '
            f'aria-hidden="true">{ICONS[name]}</svg>')


def _lead(name: str, size: int = 14) -> str:
    """Icon before a label: an ICONS name, or literal text (e.g. a check mark)."""
    if not name:
        return ""
    return icon(name, size) if name in ICONS else _esc(name)


@dataclass
class Stat:
    label: str
    value: str
    icon: str  # an ICONS name
    tone: str = "blue"
    caption: str = ""


def stat_row(stats: list[Stat]) -> None:
    """A responsive row of stat tiles (wraps to 2 per row on phones)."""
    tiles = []
    for s in stats:
        caption = f'<div class="pa-stat-caption">{_esc(s.caption)}</div>' if s.caption else ""
        tiles.append(
            f'<div class="pa-stat"><div class="pa-stat-icon">{icon(s.icon, 20)}</div>'
            f'<div><div class="pa-stat-label">{_esc(s.label)}</div><div class="pa-stat-value">{_esc(s.value)}</div>'
            f"{caption}</div></div>"
        )
    html(f'<div class="pa-stats">{"".join(tiles)}</div>')


def badge(text: str, tone: str = "gray", icon: str = "") -> str:
    """Small tag, returned as HTML so several can share one line. `icon`: an ICONS name."""
    fg, bg = TONES[tone]
    return f'<span class="pa-badge" style="background:{bg};color:{fg}">{_lead(icon, 12)}{_esc(text)}</span>'


def chips(items: list[tuple], empty: str = "") -> None:
    """A wrapping row of (text, tone) or (text, tone, icon) chips."""
    if not items:
        if empty:
            html(f'<div class="pa-empty">{_esc(empty)}</div>')
        return
    html('<div class="pa-chips">' + "".join(chip(*item) for item in items) + "</div>")


def row(left_html: str, right_html: str) -> str:
    """One line of a list inside a card: content on the left, badges on the right."""
    return f'<div class="pa-row"><span>{left_html}</span><span>{right_html}</span></div>'


def chip(text: str, tone: str = "gray", icon: str = "") -> str:
    fg, bg = TONES[tone]
    return f'<span class="pa-chip" style="background:{bg};color:{fg}">{_lead(icon)}{_esc(text)}</span>'


def callout(text: str, tone: str = "blue", icon: str = "info", bold: str = "") -> None:
    """A tinted note with a coloured left rule. `bold` is an optional emphasised lead-in."""
    fg, bg = TONES[tone]
    lead = f"<b>{_esc(bold)}</b> " if bold else ""
    html(f'<div class="pa-callout" style="background:{bg};color:{fg};border-left:3px solid {fg}">'
         f"<span>{_lead(icon, 17)}</span><span>{lead}{_esc(text)}</span></div>")


def logo(tagline: str = "Study assistant") -> str:
    return (
        f'<div class="pa-logo"><div class="pa-logo-mark">{icon("cap", 22)}</div><div>'
        f'<div class="pa-logo-name">PersonaAI</div><div class="pa-logo-tag">{_esc(tagline)}</div></div></div>'
    )
