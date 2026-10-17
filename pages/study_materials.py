import streamlit as st
import sqlite3, os, base64, sys

st.set_page_config(page_title="IEAS - Study Materials", layout="wide",
                   initial_sidebar_state="collapsed")

BASE_DIR          = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USER_PROFILES_DIR = os.path.join(BASE_DIR, "user_profiles")
sys.path.insert(0, BASE_DIR)
from subject_catalog import get_ready_subjects, _nk, find_term_pdfs, pdf_matches_subject
from theme import inject_theme_polish

if "role" not in st.session_state or st.session_state.role != "student":
    st.error("Unauthorized. Please login."); st.stop()

def b64img(path):
    if path and os.path.exists(path):
        with open(path, "rb") as f: return base64.b64encode(f.read()).decode()
    return ""

bg_b64 = b64img(os.path.join(BASE_DIR, "mainpage.jpeg"))
bg_css = f'url("data:image/jpeg;base64,{bg_b64}") center/cover no-repeat fixed' if bg_b64 else "none"

cadet_name = st.session_state.get("full_name", st.session_state.get("username", "Cadet"))
for pfx in ["CDT ", "Cdt ", "cdt "]:
    if cadet_name.startswith(pfx): cadet_name = cadet_name[len(pfx):]; break

selected_term    = st.session_state.get("selected_term", "Term_1")
selected_subject = st.session_state.get("selected_subject", "")

# ── CSS ────────────────────────────────────────────────────────────────────────
st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@400;600;700;900&family=Cormorant+Garamond:ital,wght@0,300;0,400;0,600;1,300;1,400&display=swap');

[data-testid="stSidebar"],[data-testid="collapsedControl"],
#MainMenu,footer,header,[data-testid="stToolbar"] {{ display:none !important; }}
*,*::before,*::after {{ margin:0;padding:0;box-sizing:border-box; }}
:root {{ --navy:#030d1c;--gold:#c9a45c;--goldl:#e8c87a; }}

.stApp {{
    background:linear-gradient(rgba(3,13,28,0.48),rgba(3,13,28,0.48)), {bg_css};
    min-height:100vh;
}}
.block-container {{
    padding:24px 36px 30px 36px !important;
    max-width:100% !important;
}}

/* ── Page header ── */
.page-header {{ text-align:center; padding:10px 0 24px 0; }}
.page-header .rule {{
    width:180px; height:1px; margin:0 auto 14px auto;
    background:linear-gradient(90deg,transparent,rgba(201,164,92,0.55),transparent);
}}
.page-header h2 {{
    font-family:'Cinzel',serif; font-size:clamp(18px,2.2vw,28px); font-weight:700;
    background:linear-gradient(180deg,#ffffff 0%,#f5d98a 40%,#c9a45c 100%);
    -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-clip:text;
    letter-spacing:0.18em; margin-bottom:8px; text-transform:uppercase;
}}
.page-header p {{
    font-family:'Cormorant Garamond',serif; font-style:italic;
    font-size:clamp(13px,1.2vw,16px); color:rgba(255,245,220,0.70);
    letter-spacing:0.08em;
}}
.page-header .rule-bottom {{
    width:180px; height:1px; margin:14px auto 0 auto;
    background:linear-gradient(90deg,transparent,rgba(201,164,92,0.55),transparent);
}}

/* ── Back button ── */
[data-testid="stButton"] > button[kind="secondary"] {{
    background:rgba(2,8,20,0.45) !important;
    border:1px solid rgba(201,164,92,0.32) !important;
    border-radius:3px !important; height:28px !important;
    padding:0 18px !important; font-family:'Cinzel',serif !important;
    font-size:9px !important; letter-spacing:0.16em !important;
    color:rgba(245,233,200,0.80) !important; box-shadow:none !important;
    text-transform:uppercase !important; white-space:nowrap !important;
}}

/* ── Manual selector ── */
[data-testid="stSelectbox"] label {{
    font-family:'Cinzel',serif !important; font-size:10px !important;
    letter-spacing:0.18em !important; color:#ffffff !important;
    text-transform:uppercase !important;
    opacity:1 !important; visibility:visible !important;
}}
[data-baseweb="select"] > div {{
    background:rgba(2,8,20,0.55) !important;
    border:1px solid rgba(201,164,92,0.35) !important;
    border-radius:6px !important; color:white !important;
    font-family:'Cinzel',serif !important; font-size:12px !important;
}}

/* ── PDF embed container ── */
.pdf-wrap {{
    background:rgba(1,5,14,0.85);
    border:1px solid rgba(201,164,92,0.28);
    border-left:3px solid rgba(201,164,92,0.70);
    border-radius:4px; padding:4px;
    margin-top:16px;
}}

/* ── No manual notice ── */
.no-manual {{
    text-align:center; padding:60px 20px;
    font-family:'Cinzel',serif; font-size:11px; letter-spacing:0.18em;
    color:rgba(255,245,220,0.40); text-transform:uppercase;
    border:1px solid rgba(201,164,92,0.12); border-radius:4px;
    margin-top:16px;
}}

/* ── Download button ── */
[data-testid="stDownloadButton"] > button {{
    background:linear-gradient(135deg,#6b4700,#b87800) !important;
    border:1px solid rgba(201,164,92,0.40) !important;
    border-radius:3px !important;
    font-family:'Cinzel',serif !important; font-size:9px !important;
    letter-spacing:0.18em !important; color:rgba(255,245,220,0.95) !important;
    padding:0 26px !important; height:32px !important;
    box-shadow:none !important; text-transform:uppercase !important;
}}

::-webkit-scrollbar {{ width:4px; }}
::-webkit-scrollbar-thumb {{ background:rgba(201,164,92,0.40); border-radius:2px; }}
</style>

<div class="page-header">
    <div class="rule"></div>
    <h2>Study Materials</h2>
    <p>Cadet {cadet_name.title()} &nbsp;&mdash;&nbsp; {selected_term}</p>
    <div class="rule-bottom"></div>
</div>
""", unsafe_allow_html=True)

inject_theme_polish()

# ── Back button ────────────────────────────────────────────────────────────────
col_back, _ = st.columns([2, 8])
with col_back:
    if st.button("DASHBOARD", key="back_btn"):
        st.switch_page("pages/student.py")

st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

# ── Discover available manuals for this term ───────────────────────────────────
# Raw textbook PDFs live in two separate trees on disk — see
# subject_catalog.find_term_pdfs() for why both must be searched.
pdf_entries = []   # list of (display_name, fname, full_path)
for fname, full in find_term_pdfs(BASE_DIR, selected_term):
    display = os.path.splitext(fname.replace("_", " ").replace("-", " "))[0].title()
    pdf_entries.append((display, fname, full))

# ── Filter to manuals whose subject has BOTH an indexed textbook AND question-
# bank coverage for this term (subject_catalog.get_ready_subjects) — keeps
# Study Materials consistent with what the Adaptive Quiz can actually serve.
_ready_subjects = get_ready_subjects(BASE_DIR, selected_term)

def _pdf_is_ready(fname: str) -> bool:
    for subj, manuals in _ready_subjects.items():
        manual_stems_norm = {_nk(stem) for _, stem in manuals}
        if pdf_matches_subject(fname, subj, manual_stems_norm):
            return True
    return False

pdf_entries = [e for e in pdf_entries if _pdf_is_ready(e[1])]

# ── Card list ─────────────────────────────────────────────────────────────────
if pdf_entries:
    # Sort: subject-matched manual floats to top
    if selected_subject:
        pdf_entries.sort(
            key=lambda x: 0 if selected_subject.lower() in x[1].lower() else 1
        )

    st.markdown(f"""
    <div style='font-family:Cinzel,serif;font-size:9px;letter-spacing:0.18em;
         color:rgba(201,164,92,0.55);text-transform:uppercase;margin-bottom:14px;'>
         {len(pdf_entries)} Manual{"s" if len(pdf_entries)>1 else ""} Available &mdash; {selected_term}
    </div>
    """, unsafe_allow_html=True)

    for display, fname, full_path in pdf_entries:
        sz     = os.path.getsize(full_path)
        sz_str = f"{sz/1024:.0f} KB" if sz < 1024*1024 else f"{sz/1024/1024:.1f} MB"
        is_match     = bool(selected_subject and selected_subject.lower() in fname.lower())
        border_color = "rgba(201,164,92,0.70)" if is_match else "rgba(201,164,92,0.22)"
        badge = ("<span style='font-family:Cinzel,serif;font-size:8px;letter-spacing:0.12em;"
                 "color:#e8c87a;background:rgba(201,164,92,0.15);border:1px solid rgba(201,164,92,0.40);"
                 "border-radius:3px;padding:2px 8px;margin-left:10px;'>YOUR SUBJECT</span>"
                 if is_match else "")

        st.markdown(f"""
        <div style='background:rgba(1,5,14,0.75);border:1px solid {border_color};
             border-left:3px solid {border_color};border-radius:6px;
             padding:16px 20px;margin-bottom:6px;'>
            <div style='font-family:Cinzel,serif;font-size:13px;font-weight:700;
                 color:#e8c87a;letter-spacing:0.06em;margin-bottom:3px;'>
                 &nbsp;{display}{badge}
            </div>
            <div style='font-family:Cormorant Garamond,serif;font-size:12px;
                 color:rgba(255,245,220,0.45);letter-spacing:0.04em;'>
                 {fname} &nbsp;&middot;&nbsp; {sz_str}
            </div>
        </div>
        """, unsafe_allow_html=True)

        # Reading + (for Open) base64-encoding every listed PDF on every
        # rerun — regardless of whether the student ever clicks it — is what
        # made this page slow with multiple/large books: a term with a few
        # 30-40MB PDFs meant tens of MB read from disk and re-encoded on
        # every single render. Both actions are now deferred until the
        # student actually asks for that specific file.
        prep_key = f"prep_{fname}"
        if not st.session_state.get(prep_key):
            if st.button("📂  Load Download / Open Options", key=f"load_{fname}", use_container_width=True):
                st.session_state[prep_key] = True
                st.rerun()
        else:
            col_dl, col_open, col_gap = st.columns([1, 1, 4])

            with col_dl:
                with open(full_path, "rb") as fh:
                    st.download_button(
                        label="⬇  Download",
                        data=fh.read(),
                        file_name=fname,
                        mime="application/pdf",
                        key=f"dl_{fname}",
                        use_container_width=True
                    )

            with col_open:
                # Inline base64 preview is only offered under a size cap —
                # even lazily, browsers struggle to render a data: URI built
                # from a 30-40MB file. Download always works regardless of size.
                OPEN_PREVIEW_CAP_BYTES = 20 * 1024 * 1024
                if sz <= OPEN_PREVIEW_CAP_BYTES:
                    open_key = f"open_{fname}"
                    if not st.session_state.get(open_key):
                        if st.button("↑  Open", key=f"openbtn_{fname}", use_container_width=True):
                            st.session_state[open_key] = True
                            st.rerun()
                    else:
                        with open(full_path, "rb") as fh:
                            pdf_b64 = base64.b64encode(fh.read()).decode("utf-8")
                        st.markdown(
                            f'<div style="width:100%;">'
                            f'<a href="data:application/pdf;base64,{pdf_b64}" target="_blank"'
                            f'style="display:flex;align-items:center;justify-content:center;'
                            f'width:100%;height:32px;'
                            f'background:linear-gradient(135deg,#6b4700,#b87800);'
                            f'border:1px solid rgba(201,164,92,0.40);'
                            f'border-radius:3px;'
                            f'font-family:Cinzel,serif;font-size:15px;'
                            f'letter-spacing:0.18em;color:rgba(255,245,220,0.95);'
                            f'text-decoration:none;text-transform:uppercase;box-sizing:border-box;">'
                            f'&#8593;&nbsp;&nbsp;Open</a>'
                            f'</div>',
                            unsafe_allow_html=True
                        )
                else:
                    st.markdown(
                        "<div style='font-size:11px;color:rgba(255,245,220,0.55);"
                        "padding-top:8px;'>Too large to preview — use Download</div>",
                        unsafe_allow_html=True
                    )

        st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

else:
    st.markdown("""
    <div class='no-manual'>
        No PDF manuals found for this term.<br>
        <span style='font-size:0.85em;opacity:0.6;letter-spacing:0.08em;'>
            Ask your instructor to upload materials for this term.
        </span>
    </div>
    """, unsafe_allow_html=True)
