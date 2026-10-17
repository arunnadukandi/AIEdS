"""
Shared visual polish layer for AIEdS — warm "organic naval" direction.

Every page keeps its own background image / hero markup / page-specific
classes exactly as before. This module injects ONE additional stylesheet,
after each page's own <style> block, that:
  - fixes low-contrast form fields (near-opaque surfaces instead of
    translucent ones that let bright backgrounds bleed through)
  - gives the whole app a warm, natural finish: soft rounded panels,
    gentle gold glows, a muted sage-green secondary accent, no hard edges
    or neon — legible above all else
  - modernises tabs, buttons, alerts, expanders, checkboxes, file
    uploaders, dataframes and scrollbars
  - resizes tab pills, tiny inline labels, and common banner/header
    patterns to a more contemporary, legible scale

Because this stylesheet is injected after each page's own CSS, its
`!important` rules win the cascade for anything it touches, while classes
unique to a page (e.g. `.eval-box`, `.assign-card`, `.queue-stat`) are left
untouched structurally — only recolored/resized by the rules below.

Button/tab colors here are chosen for guaranteed contrast against their
own explicit background — never relying on a gradient or blend effect a
button might not actually have (Streamlit only applies `kind="primary"`
styling when a button is created with `type="primary"`; plain `st.button()`
calls are `kind="secondary"` and must look good on their own).

Tab selectors intentionally target both the legacy BaseWeb attributes
(`[data-baseweb="tab"]`) and the current React-Aria markup
(`[role="tab"]`, `[data-testid="stTab"]`) since Streamlit has swapped the
underlying tab implementation across versions.
"""

import streamlit as st

_POLISH_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@400;600;700;900&family=Rajdhani:wght@400;500;600;700&family=Cormorant+Garamond:ital,wght@0,300;0,400;0,600;1,300;1,400&display=swap');

:root{
    --ink:#f5efe0;
    --muted:#b3a583;
    --gold:#c9a45c;
    --gold-bright:#f0d9a0;
    --gold-dim:rgba(201,164,92,0.38);
    --sage:#8fbf9f;
    --sage-dim:rgba(143,191,159,0.35);
    --surface:rgba(8,14,10,0.92);
    --surface-soft:rgba(8,14,10,0.72);
    --surface-hover:rgba(8,14,10,0.97);
    --success:#7fd99a;
    --success-bg:rgba(14,38,24,0.94);
    --danger:#e77a7a;
    --danger-bg:rgba(40,16,16,0.94);
    --warning:#e0b855;
    --warning-bg:rgba(40,30,10,0.94);
}

/* ── Form fields: near-opaque, warm gold focus glow ── */
.stTextArea textarea,
.stTextInput input,
.stNumberInput input,
[data-baseweb="select"] > div,
[data-baseweb="input"] > div {
    background:var(--surface) !important;
    border:1px solid var(--gold-dim) !important;
    border-radius:10px !important;
    color:var(--ink) !important;
    font-family:'Rajdhani',sans-serif !important;
    font-size:14.5px !important;
    box-shadow:inset 0 1px 3px rgba(0,0,0,0.35) !important;
    transition:border-color .18s ease, box-shadow .18s ease !important;
}
.stTextArea textarea::placeholder,
.stTextInput input::placeholder { color:rgba(245,239,224,0.42) !important; }
.stTextArea textarea:focus,
.stTextInput input:focus,
.stNumberInput input:focus {
    background:var(--surface-hover) !important;
    border-color:var(--gold) !important;
    box-shadow:0 0 0 3px rgba(201,164,92,0.18) !important;
    outline:none !important;
}
[data-baseweb="select"] span, [data-baseweb="select"] input { color:var(--ink) !important; }

/* Dropdown popover list */
[data-baseweb="popover"] [data-baseweb="menu"],
[data-baseweb="select"] [data-baseweb="menu"] {
    background:rgba(8,14,10,0.98) !important;
    border:1px solid var(--gold-dim) !important;
    border-radius:12px !important;
    box-shadow:0 12px 40px rgba(0,0,0,0.55) !important;
}
[data-baseweb="menu"] li, [data-baseweb="menu"] li span,
[data-baseweb="select"] [role="option"], [data-baseweb="select"] [role="option"] span {
    color:var(--ink) !important;
    font-family:'Rajdhani',sans-serif !important;
}
[data-baseweb="menu"] li:hover,
[data-baseweb="menu"] [aria-selected="true"],
[data-baseweb="select"] [role="option"]:hover,
[data-baseweb="select"] [role="option"][aria-selected="true"] {
    background:rgba(201,164,92,0.20) !important;
    color:var(--gold-bright) !important;
}

/* Field labels */
.stTextArea label, .stTextInput label, .stNumberInput label,
.stSelectbox label, .stMultiSelect label, .stDateInput label, .stFileUploader label {
    color:var(--gold) !important;
    font-family:'Rajdhani',sans-serif !important;
    font-size:11px !important;
    letter-spacing:0.14em !important;
    text-transform:uppercase !important;
    font-weight:700 !important;
}

/* ── Tabs: soft rounded pill, warm gold active state ── */
.stTabs [data-baseweb="tab-list"], .stTabs [role="tablist"] {
    background:rgba(8,14,10,0.55) !important;
    border:1px solid rgba(201,164,92,0.20) !important;
    border-radius:999px !important;
    padding:5px !important;
    gap:4px !important;
    justify-content:center !important;
    margin-bottom:20px !important;
}
.stTabs [data-baseweb="tab"], .stTabs [role="tab"], .stTabs [data-testid="stTab"] {
    background:transparent !important;
    color:var(--muted) !important;
    font-family:'Rajdhani',sans-serif !important;
    font-size:13px !important;
    font-weight:600 !important;
    letter-spacing:0.08em !important;
    padding:10px 22px !important;
    border-radius:999px !important;
    border-bottom:none !important;
    transition:all .2s ease !important;
}
.stTabs [data-baseweb="tab"]:hover, .stTabs [role="tab"]:hover { color:var(--gold-bright) !important; }
.stTabs [aria-selected="true"] {
    background:linear-gradient(135deg,#b8923e 0%,#e8c87a 55%,#c9a45c 100%) !important;
    color:#241a08 !important;
    font-weight:700 !important;
    box-shadow:0 4px 16px rgba(201,164,92,0.32) !important;
}
.stTabs [data-baseweb="tab-highlight"] { display:none !important; }
.stTabs [data-baseweb="tab-panel"], .stTabs [role="tabpanel"] { padding-top:6px !important; }

/* ── Buttons: soft rounded, explicit high-contrast colors for every kind
   Streamlit actually produces (no assumptions about which "kind" a given
   st.button() call resolves to) ── */
.stButton>button, .stFormSubmitButton>button, .stDownloadButton>button {
    border-radius:10px !important;
    font-family:'Rajdhani',sans-serif !important;
    font-size:13px !important;
    font-weight:700 !important;
    letter-spacing:0.06em !important;
    transition:all .2s ease !important;
}
.stButton>button[kind="primary"], .stFormSubmitButton>button {
    background:linear-gradient(135deg,#b8923e 0%,#e8c87a 55%,#c9a45c 100%) !important;
    color:#241a08 !important;
    border:none !important;
    box-shadow:0 4px 16px rgba(201,164,92,0.28) !important;
}
.stButton>button[kind="primary"]:hover, .stFormSubmitButton>button:hover {
    box-shadow:0 8px 26px rgba(201,164,92,0.42) !important;
    transform:translateY(-1px) !important;
}
.stButton>button[kind="secondary"] {
    background:rgba(201,164,92,0.16) !important;
    color:var(--gold-bright) !important;
    border:1px solid var(--gold-dim) !important;
}
.stButton>button[kind="secondary"]:hover {
    background:rgba(201,164,92,0.26) !important;
    border-color:var(--gold) !important;
}
.stDownloadButton>button {
    background:rgba(143,191,159,0.16) !important;
    color:#c9f0d6 !important;
    border:1px solid var(--sage-dim) !important;
}
.stDownloadButton>button:hover { background:rgba(143,191,159,0.28) !important; }

/* ── Checkboxes / radio ── */
[data-testid="stCheckbox"] label p, [data-testid="stRadio"] label p {
    color:var(--ink) !important;
    font-family:'Rajdhani',sans-serif !important;
    font-size:13.5px !important;
}
[data-testid="stCheckbox"] input[type="checkbox"] { accent-color:var(--gold) !important; }
div[role="radiogroup"] input[type="radio"] { accent-color:var(--gold) !important; }

/* ── File uploader ── */
[data-testid="stFileUploaderDropzone"] {
    background:var(--surface-soft) !important;
    border:1.5px dashed var(--gold-dim) !important;
    border-radius:12px !important;
}
[data-testid="stFileUploaderDropzone"]:hover { border-color:var(--gold) !important; }
[data-testid="stFileUploaderDropzone"] small, [data-testid="stFileUploaderDropzone"] span {
    color:var(--muted) !important;
}

/* ── Expanders ── */
[data-testid="stExpander"] {
    background:var(--surface-soft) !important;
    border:1px solid var(--gold-dim) !important;
    border-radius:12px !important;
    overflow:hidden !important;
}
[data-testid="stExpander"] summary {
    font-family:'Rajdhani',sans-serif !important;
    color:var(--ink) !important;
    font-weight:600 !important;
}
[data-testid="stExpander"] summary:hover { color:var(--gold-bright) !important; }

/* ── Alerts ── */
div[data-testid="stAlert"] { border-radius:10px !important; }
div[data-testid="stAlert"] p, div[data-testid="stAlert"] span { font-family:'Rajdhani',sans-serif !important; font-size:14px !important; }
div[data-testid="stAlert"][kind="error"] { background:var(--danger-bg) !important; border:1px solid rgba(231,122,122,0.5) !important; border-left:3px solid var(--danger) !important; }
div[data-testid="stAlert"][kind="error"] p { color:#ffbdbd !important; }
div[data-testid="stAlert"][kind="success"] { background:var(--success-bg) !important; border:1px solid rgba(127,217,154,0.5) !important; border-left:3px solid var(--success) !important; }
div[data-testid="stAlert"][kind="success"] p { color:#b8f0c8 !important; }
div[data-testid="stAlert"][kind="warning"] { background:var(--warning-bg) !important; border:1px solid rgba(224,184,85,0.5) !important; border-left:3px solid var(--warning) !important; }
div[data-testid="stAlert"][kind="warning"] p { color:#f5da9e !important; }
div[data-testid="stAlert"][kind="info"] { background:rgba(10,24,20,0.94) !important; border:1px solid var(--sage-dim) !important; border-left:3px solid var(--sage) !important; }
div[data-testid="stAlert"][kind="info"] p { color:#c9f0d6 !important; }

/* ── Dataframes / metrics ── */
[data-testid="stDataFrame"] { border-radius:10px !important; overflow:hidden !important; border:1px solid var(--gold-dim) !important; }
[data-testid="stMetricValue"] { color:var(--gold-bright) !important; font-family:'Cinzel',serif !important; }
[data-testid="stMetricLabel"] { color:var(--muted) !important; font-family:'Rajdhani',sans-serif !important; letter-spacing:0.08em !important; text-transform:uppercase !important; }

/* ── Scrollbar ── */
::-webkit-scrollbar { width:6px; height:6px; }
::-webkit-scrollbar-track { background:transparent; }
::-webkit-scrollbar-thumb { background:rgba(201,164,92,0.40); border-radius:4px; }
::-webkit-scrollbar-thumb:hover { background:rgba(201,164,92,0.65); }

/* ── Progress / spinner ── */
.stProgress > div > div { background:linear-gradient(90deg,#b8923e,#e8c87a) !important; }

/* ── Generic banner/header sizing sanity — keeps headings from ballooning ── */
.page-header h1, .page-header h2 { font-size:clamp(17px,2vw,24px) !important; }

/* ── Readability floor: several pages use 8-9px inline "eyebrow" labels that
   read as decorative but are actually load-bearing (subject/term/status tags,
   field captions). Bump anything that tiny up to a legible minimum, wherever
   it's declared — inline style attributes included. ── */
p[style*="font-size:8px"], p[style*="font-size: 8px"],
div[style*="font-size:8px"], div[style*="font-size: 8px"],
span[style*="font-size:8px"], span[style*="font-size: 8px"],
td[style*="font-size:8px"], td[style*="font-size: 8px"] { font-size:11px !important; }
p[style*="font-size:9px"], p[style*="font-size: 9px"],
div[style*="font-size:9px"], div[style*="font-size: 9px"],
span[style*="font-size:9px"], span[style*="font-size: 9px"],
td[style*="font-size:9px"], td[style*="font-size: 9px"] { font-size:11px !important; }
p[style*="font-size:10px"], p[style*="font-size: 10px"],
div[style*="font-size:10px"], div[style*="font-size: 10px"],
span[style*="font-size:10px"], span[style*="font-size: 10px"] { font-size:11.5px !important; }
</style>
"""


def inject_theme_polish():
    """Call once near the top of a page, after its own CSS block."""
    st.markdown(_POLISH_CSS, unsafe_allow_html=True)
