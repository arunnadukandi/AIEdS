import streamlit as st
import streamlit.components.v1 as components
import sqlite3, os, base64, sys
import html as _html
from datetime import datetime, date

st.set_page_config(page_title="IEAS - Assignments", layout="wide",
                   initial_sidebar_state="collapsed")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
from theme import inject_theme_polish
DB_PATH  = os.path.join(BASE_DIR, "sahayak.db")
ASSIGN_DIR = os.path.join(BASE_DIR, "assignments")

if "role" not in st.session_state or st.session_state.role != "student":
    st.error("Unauthorized. Please login."); st.stop()

# ── ensure DB tables exist ─────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # assignments posted by instructors
    c.execute("""CREATE TABLE IF NOT EXISTS assignments (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        term        TEXT,
        subject     TEXT,
        title       TEXT,
        description TEXT,
        due_date    TEXT,
        marks       INTEGER DEFAULT 0,
        posted_by   TEXT,
        created_at  TEXT
    )""")
    # Add marks column if it doesn't exist (for existing DBs)
    try:
        c.execute("ALTER TABLE assignments ADD COLUMN marks INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # submissions by students
    c.execute("""CREATE TABLE IF NOT EXISTS submissions (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        assignment_id INTEGER,
        student_id    TEXT,
        file_name     TEXT,
        file_data     BLOB,
        remarks       TEXT,
        submitted_at  TEXT,
        FOREIGN KEY(assignment_id) REFERENCES assignments(id)
    )""")
    # Add grading columns if they don't exist (for existing DBs)
    for _col, _defn in [
        ("ai_score",     "REAL"),
        ("ai_feedback",  "TEXT"),
        ("manual_score", "REAL"),
        ("status",       "TEXT DEFAULT 'submitted'"),
        ("flagged",      "INTEGER DEFAULT 0"),
        ("sheet_data",   "BLOB"),
        ("sheet_name",   "TEXT"),
    ]:
        try:
            c.execute(f"ALTER TABLE submissions ADD COLUMN {_col} {_defn}")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute(f"ALTER TABLE assignments ADD COLUMN {_col} {_defn}")
        except sqlite3.OperationalError:
            pass
    conn.commit(); conn.close()

init_db()

def b64img(path):
    if path and os.path.exists(path):
        with open(path, "rb") as f: return base64.b64encode(f.read()).decode()
    return ""

bg_b64 = b64img(os.path.join(BASE_DIR, "mainpage.jpeg"))
bg_css = f'url("data:image/jpeg;base64,{bg_b64}") center/cover no-repeat fixed' if bg_b64 else "none"

student_id   = st.session_state.get("username", "unknown")
cadet_name   = st.session_state.get("full_name", student_id)
for pfx in ["CDT ", "Cdt ", "cdt "]:
    if cadet_name.startswith(pfx): cadet_name = cadet_name[len(pfx):]; break

# ── CSS ────────────────────────────────────────────────────────────────────────
st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@400;600;700;900&family=Cormorant+Garamond:ital,wght@0,300;0,400;0,600;1,300;1,400&display=swap');

[data-testid="stSidebar"],[data-testid="collapsedControl"],
#MainMenu,footer,header,[data-testid="stToolbar"] {{ display:none !important; }}
*,*::before,*::after {{ margin:0;padding:0;box-sizing:border-box; }}
:root {{ --navy:#030d1c;--gold:#c9a45c;--goldl:#e8c87a; }}

.stApp {{
    background:linear-gradient(rgba(3,13,28,0.42),rgba(3,13,28,0.42)), {bg_css};
    min-height:100vh;
}}
.block-container {{
    padding:24px 36px 30px 36px !important;
    max-width:100% !important;
}}

/* ── Page header ── */
.page-header {{ text-align:center; padding:10px 0 28px 0; }}
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
    font-size:clamp(13px,1.2vw,16px); color:rgba(255,245,220,0.80);
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

/* ── Assignment cards ── */
.assign-card {{
    background:rgba(1,5,14,0.88);
    border:1px solid rgba(201,164,92,0.35);
    border-left:3px solid rgba(201,164,92,0.80);
    border-radius:4px; padding:24px 28px 20px 28px;
    margin-bottom:12px;
    position:relative; overflow:hidden;
}}
.assign-card::after {{
    content:''; position:absolute; bottom:0; left:0; right:0;
    height:1px;
    background:linear-gradient(90deg,rgba(201,164,92,0.30),transparent);
}}

/* ── Card title row ── */
.card-title-row {{
    display:flex; align-items:flex-start; justify-content:space-between;
    margin-bottom:12px; gap:12px; flex-wrap:wrap;
    padding-bottom:10px;
    border-bottom:1px solid rgba(201,164,92,0.10);
}}
.assign-title {{
    font-family:'Cinzel',serif; font-size:clamp(13px,1.3vw,16px); font-weight:700;
    color:#ffffff; letter-spacing:0.16em; text-transform:uppercase;
}}

/* ── Info pills row ── */
.info-pills {{
    display:flex; flex-wrap:wrap; gap:6px; margin-bottom:14px;
}}
.pill {{
    display:inline-flex; align-items:center; gap:4px;
    padding:5px 14px;
    border-radius:4px; font-family:'Cinzel',serif;
    font-size:11px; letter-spacing:0.12em; font-weight:700;
    text-transform:uppercase;
}}
.pill-subject {{
    background:rgba(100,149,237,0.18); border:1px solid rgba(100,149,237,0.55);
    color:#c2d6ff;
}}
.pill-term {{
    background:rgba(180,100,220,0.18); border:1px solid rgba(180,100,220,0.50);
    color:#e8caff;
}}
.pill-due {{
    background:rgba(232,160,32,0.18); border:1px solid rgba(232,160,32,0.55);
    color:#ffd070;
}}
.pill-marks {{
    background:rgba(0,196,114,0.18); border:1px solid rgba(0,196,114,0.55);
    color:#6effc8;
}}
.pill-submitted {{
    background:rgba(0,196,114,0.20); border:1px solid rgba(0,196,114,0.60);
    color:#6effc8; font-size:11px; letter-spacing:0.12em;
}}

/* ── Description ── */
.assign-desc {{
    font-family:'Cormorant Garamond',serif; font-size:clamp(14px,1.1vw,16px);
    color:rgba(255,245,220,0.92); line-height:1.75; margin-bottom:14px;
    padding-bottom:14px; font-weight:500;
    border-bottom:1px solid rgba(201,164,92,0.15);
}}

/* ── Submission view ── */
.sub-view {{
    background:rgba(0,196,114,0.06);
    border:1px solid rgba(0,196,114,0.25);
    border-left:3px solid rgba(0,196,114,0.60);
    border-radius:3px; padding:14px 18px; margin-top:6px;
    font-family:'Cormorant Garamond',serif;
    font-size:15px; color:rgba(255,245,220,0.92); line-height:2.0; font-weight:500;
}}
.sub-view .sub-heading {{
    font-family:'Cinzel',serif; font-size:11px; letter-spacing:0.16em;
    color:rgba(201,164,92,0.95); text-transform:uppercase; margin-bottom:10px;
}}

/* ── Upload label ── */
.upload-label {{
    font-family:'Cinzel',serif; font-size:11px; letter-spacing:0.16em;
    color:rgba(201,164,92,0.90); margin-top:8px; margin-bottom:4px;
    text-transform:uppercase; font-weight:700;
}}

/* ── Empty layout skeleton card ── */
.empty-card {{
    background:rgba(1,5,14,0.82);
    border:1px solid rgba(201,164,92,0.18);
    border-left:3px solid rgba(201,164,92,0.28);
    border-radius:4px; padding:24px 28px;
    margin-bottom:12px;
}}
.empty-title-bar {{
    height:14px; width:55%; border-radius:2px;
    background:rgba(201,164,92,0.12); margin-bottom:16px;
}}
.empty-pills {{
    display:flex; gap:8px; margin-bottom:18px;
}}
.empty-pill {{
    height:22px; width:120px; border-radius:2px;
    background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.08);
}}
.empty-line {{
    height:10px; border-radius:2px;
    background:rgba(255,255,255,0.05); margin-bottom:10px;
}}
.empty-upload {{
    height:60px; border-radius:3px; margin-top:18px;
    background:rgba(201,164,92,0.04);
    border:1px solid rgba(201,164,92,0.14);
}}
.no-assign-notice {{
    text-align:center; padding:16px 20px 24px 20px;
    font-family:'Cinzel',serif; font-size:11px; letter-spacing:0.18em;
    color:rgba(255,245,220,0.50); text-transform:uppercase;
    border-bottom:1px solid rgba(201,164,92,0.12); margin-bottom:20px;
}}

/* ── Form inputs ── */
.stTextArea textarea, .stTextInput input {{
    background:rgba(2,8,20,0.94) !important;
    border:1px solid rgba(201,164,92,0.40) !important;
    border-radius:6px !important; color:#f9f2df !important;
    font-family:'Cormorant Garamond',serif !important; font-size:15px !important;
    box-shadow:inset 0 1px 4px rgba(0,0,0,0.45) !important;
}}
.stTextArea textarea::placeholder, .stTextInput input::placeholder {{
    color:rgba(245,233,200,0.42) !important;
}}
.stTextArea textarea:focus, .stTextInput input:focus {{
    background:rgba(2,8,20,0.98) !important;
    border-color:rgba(201,164,92,0.75) !important;
}}
.stFileUploader {{
    background:rgba(2,8,20,0.40) !important;
    border:1px solid rgba(201,164,92,0.22) !important;
    border-radius:3px !important;
}}

/* Submit primary button */
[data-testid="stButton"] > button[kind="primary"] {{
    background:linear-gradient(135deg,#6b4700,#b87800) !important;
    border:1px solid rgba(201,164,92,0.40) !important;
    border-radius:3px !important;
    font-family:'Cinzel',serif !important; font-size:9px !important;
    letter-spacing:0.18em !important; color:rgba(255,245,220,0.95) !important;
    padding:0 26px !important; height:32px !important;
    box-shadow:none !important; text-transform:uppercase !important;
}}
[data-testid="stButton"] > button[kind="primary"]:hover {{
    opacity:0.85 !important;
}}

::-webkit-scrollbar {{ width:4px; }}
::-webkit-scrollbar-thumb {{ background:rgba(201,164,92,0.40); border-radius:2px; }}
</style>

<div class="page-header">
    <div class="rule"></div>
    <h2>Assignment Portal</h2>
    <p>Cadet {cadet_name.title()} &nbsp;&mdash;&nbsp; Review directives and submit your work</p>
    <div class="rule-bottom"></div>
</div>
""", unsafe_allow_html=True)

inject_theme_polish()

# ── Back button ────────────────────────────────────────────────────────────────
col_back, _ = st.columns([2, 8])
with col_back:
    if st.button("DASHBOARD", key="back_btn"):
        st.switch_page("pages/student.py")

st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

# ── Term filter ────────────────────────────────────────────────────────────────
filter_col, _, _ = st.columns([2, 2, 2])
with filter_col:
    _term_opts = ["All Terms"] + [f"Term_{i}" for i in range(1, 9)]
    _my_term   = st.session_state.get("selected_term", "All Terms")
    term_filter = st.selectbox(
        "Filter by Term", _term_opts,
        index=_term_opts.index(_my_term) if _my_term in _term_opts else 0,
        key="asn_term"
    )

st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

# ── DB helpers ─────────────────────────────────────────────────────────────────
def get_assignments(term_filter):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Add sheet columns if they don't exist yet
    try: c.execute("ALTER TABLE assignments ADD COLUMN sheet_data BLOB")
    except: pass
    try: c.execute("ALTER TABLE assignments ADD COLUMN sheet_name TEXT")
    except: pass
    conn.commit()
    if term_filter == "All Terms":
        c.execute("SELECT id,term,subject,title,description,due_date,marks,posted_by,created_at,sheet_data,sheet_name FROM assignments ORDER BY due_date ASC")
    else:
        c.execute("SELECT id,term,subject,title,description,due_date,marks,posted_by,created_at,sheet_data,sheet_name FROM assignments WHERE term=? ORDER BY due_date ASC", (term_filter,))
    rows = c.fetchall()
    conn.close()
    return rows  # id,term,subject,title,description,due_date,marks,posted_by,created_at,sheet_data,sheet_name

def already_submitted(assignment_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id FROM submissions WHERE assignment_id=? AND student_id=?",
              (assignment_id, student_id))
    row = c.fetchone()
    conn.close()
    return row is not None

def get_submission(assignment_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""SELECT file_name, remarks, submitted_at,
                        ai_score, manual_score, status, ai_feedback
                 FROM submissions
                 WHERE assignment_id=? AND student_id=?""",
              (assignment_id, student_id))
    sub = c.fetchone()
    conn.close()
    return sub

def submit_assignment(assignment_id, file_name, file_data, remarks):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""INSERT INTO submissions
        (assignment_id, student_id, file_name, file_data, remarks, submitted_at)
        VALUES (?,?,?,?,?,?)""",
        (assignment_id, student_id, file_name, file_data, remarks,
         datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit(); conn.close()

assignments = get_assignments(term_filter)

# ── Render assignments ─────────────────────────────────────────────────────────
if not assignments:
    _term_txt = "any term" if term_filter == "All Terms" else term_filter.replace("_", " ")
    st.markdown(f"""
    <div style='background:rgba(1,5,14,0.82);border:1px solid rgba(201,164,92,0.30);
         border-left:3px solid rgba(201,164,92,0.70);border-radius:4px;
         padding:34px 28px;text-align:center;margin-top:10px;'>
        <div style='font-family:"Cinzel",serif;font-size:clamp(14px,1.4vw,18px);font-weight:700;
             letter-spacing:0.16em;color:#e8c87a;text-transform:uppercase;margin-bottom:10px;'>
            No assignment posted for {_term_txt}</div>
        <div style='font-family:"Cormorant Garamond",serif;font-style:italic;font-size:16px;
             color:rgba(255,245,220,0.75);'>
            Check back later, or choose another term above.</div>
    </div>
    """, unsafe_allow_html=True)
else:
    # ── Assignment selector: one focused assignment at a time, instead of
    # stacking every assignment's card + submission form down the page ──
    assign_labels, assign_map = [], {}
    for asn in assignments:
        _id, _term, _subject, _title, *_ = asn
        badge = "  ✓ Submitted" if already_submitted(_id) else ""
        label = f"[{_subject}] {_title} ({_term}){badge}"
        assign_labels.append(label)
        assign_map[label] = asn

    sel_col, _ = st.columns([2, 2])
    with sel_col:
        sel_label = st.selectbox("Select Assignment", assign_labels, key="asn_select")

    asn = assign_map[sel_label]
    asn_id, term, subject, title, desc, due_date, marks, posted_by, created_at, sheet_data, sheet_name = asn
    submitted = already_submitted(asn_id)

    tab_details, tab_submit = st.tabs(["📋  INSTRUCTIONS", "📤  SUBMIT / STATUS"])

    try:
        overdue = (not submitted) and bool(due_date) and date.fromisoformat(str(due_date)[:10]) < date.today()
    except ValueError:
        overdue = False
    e_title, e_subject = _html.escape(str(title or "")), _html.escape(str(subject or ""))
    e_desc   = _html.escape(str(desc or "")).replace("\n", "<br>")
    e_poster = _html.escape(str(posted_by or ""))

    with tab_details:
        submitted_badge_html = "<span class='pill-submitted'>SUBMITTED</span>" if submitted else ""
        if overdue:
            submitted_badge_html = ("<span class='pill-submitted' style='background:rgba(255,80,80,0.18);"
                                    "border-color:rgba(255,80,80,0.6);color:#ff9a9a;'>OVERDUE</span>")
        card_html = f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@400;600;700&family=Cormorant+Garamond:ital,wght@0,400;0,600;1,400&display=swap');
        * {{ box-sizing:border-box; margin:0; padding:0; }}
        body {{ background:transparent; font-family:'Cormorant Garamond',serif; }}
        .assign-card {{
            background:rgba(1,5,14,0.88);
            border:1px solid rgba(201,164,92,0.35);
            border-left:3px solid rgba(201,164,92,0.80);
            border-radius:4px; padding:20px 24px 16px 24px;
            position:relative; overflow:hidden;
        }}
        .assign-card::after {{
            content:''; position:absolute; bottom:0; left:0; right:0;
            height:1px;
            background:linear-gradient(90deg,rgba(201,164,92,0.30),transparent);
        }}
        .card-title-row {{
            display:flex; align-items:flex-start; justify-content:space-between;
            margin-bottom:10px; gap:12px; flex-wrap:wrap;
            padding-bottom:8px;
            border-bottom:1px solid rgba(201,164,92,0.10);
        }}
        .assign-title {{
            font-family:'Cinzel',serif; font-size:14px; font-weight:700;
            color:#ffffff; letter-spacing:0.16em; text-transform:uppercase;
        }}
        .pill-submitted {{
            background:rgba(0,196,114,0.20); border:1px solid rgba(0,196,114,0.60);
            color:#6effc8; font-size:9px; letter-spacing:0.14em;
            font-family:'Cinzel',serif; font-weight:700; text-transform:uppercase;
            padding:3px 10px; border-radius:2px;
        }}
        .info-pills {{
            display:flex; flex-wrap:wrap; gap:6px; margin-bottom:12px;
        }}
        .pill {{
            display:inline-flex; align-items:center; gap:4px;
            padding:3px 12px; border-radius:2px;
            font-family:'Cinzel',serif; font-size:9px;
            letter-spacing:0.12em; font-weight:700; text-transform:uppercase;
        }}
        .pill-subject {{ background:rgba(100,149,237,0.18); border:1px solid rgba(100,149,237,0.55); color:#c2d6ff; }}
        .pill-term    {{ background:rgba(180,100,220,0.18); border:1px solid rgba(180,100,220,0.50); color:#e8caff; }}
        .pill-due     {{ background:rgba(232,160,32,0.18);  border:1px solid rgba(232,160,32,0.55);  color:#ffd070; }}
        .pill-marks   {{ background:rgba(0,196,114,0.18);   border:1px solid rgba(0,196,114,0.55);   color:#6effc8; }}
        .assign-desc {{
            font-family:'Cormorant Garamond',serif; font-size:15px;
            color:rgba(255,245,220,0.92); line-height:1.75; margin-bottom:12px;
            padding-bottom:12px; font-weight:500;
            border-bottom:1px solid rgba(201,164,92,0.15);
        }}
        .issued-by {{
            font-family:'Cinzel',serif; font-size:9px;
            color:rgba(255,245,220,0.45); letter-spacing:0.12em; text-transform:uppercase;
        }}
        </style>
        <div class="assign-card">
            <div class="card-title-row">
                <div class="assign-title">{e_title}</div>
                {submitted_badge_html}
            </div>
            <div class="info-pills">
                <span class="pill pill-subject">Subject &nbsp;|&nbsp; {e_subject}</span>
                <span class="pill pill-term">{term}</span>
                <span class="pill pill-due">Due &nbsp;|&nbsp; {due_date}</span>
                <span class="pill pill-marks">Max Marks &nbsp;|&nbsp; {marks if marks else "—"}</span>
            </div>
            <div class="assign-desc">{e_desc if e_desc else "&nbsp;"}</div>
            <div class="issued-by">Issued by &nbsp;{e_poster}</div>
        </div>
        """
        _desc_lines = sum(max(1, len(l) // 110 + 1) for l in str(desc or "").splitlines() or [""])
        components.html(card_html, height=min(170 + 27 * _desc_lines, 700), scrolling=True)

        # ── Download Assignment Sheet ─────────────────────────────────────────
        if sheet_data:
            dl_col, _ = st.columns([1, 3])
            with dl_col:
                ext = sheet_name.split(".")[-1].lower() if sheet_name else "pdf"
                mime = "application/pdf" if ext == "pdf" else f"image/{ext}"
                st.download_button(
                    label="📄  Download Assignment Sheet",
                    data=sheet_data,
                    file_name=sheet_name or f"assignment_{asn_id}.pdf",
                    mime=mime,
                    key=f"dl_{asn_id}",
                    use_container_width=True
                )

    # ── Submission area: its own tab, so cadets land straight on it instead
    # of scrolling past the instructions every time ─────────────────────────
    with tab_submit:
        if submitted:
            sub = get_submission(asn_id)
            if sub:
                file_name, remarks, submitted_at = sub[0], sub[1], sub[2]
                ai_score     = sub[3] if len(sub) > 3 else None
                manual_score = sub[4] if len(sub) > 4 else None
                sub_status   = sub[5] if len(sub) > 5 else "submitted"
                ai_feedback  = sub[6] if len(sub) > 6 else None

                effective_score = manual_score if manual_score is not None else ai_score
                grade_released  = sub_status == "released" and effective_score is not None

                grade_block = ""
                if grade_released:
                    pct = round((effective_score / marks) * 100) if marks else 0
                    bar_color = "#6effc8" if pct >= 60 else ("#f5d98a" if pct >= 40 else "#ff6b6b")
                    feedback_html = ""
                    if ai_feedback:
                        feedback_html = f"""
                        <div style='margin-top:10px;padding:8px 12px;
                             background:rgba(255,255,255,0.04);border-radius:3px;
                             font-size:13px;color:rgba(255,245,220,0.75);
                             white-space:pre-wrap;line-height:1.6;'>
                            {_html.escape(ai_feedback)}
                        </div>"""
                    grade_block = f"""
                    <div style='margin-top:10px;padding:12px 16px;
                         background:rgba(110,255,200,0.06);
                         border:1px solid rgba(110,255,200,0.28);
                         border-left:3px solid rgba(110,255,200,0.70);
                         border-radius:3px;'>
                        <div style='font-family:"Cinzel",serif;font-size:9px;
                             letter-spacing:.18em;color:rgba(110,255,200,0.85);
                             text-transform:uppercase;margin-bottom:8px;'>
                            Grade Released</div>
                        <div style='display:flex;align-items:center;gap:18px;flex-wrap:wrap;'>
                            <div style='font-family:"Orbitron",sans-serif;font-size:28px;
                                 color:{bar_color};font-weight:700;'>
                                {effective_score:g}/{marks}</div>
                            <div style='flex:1;min-width:120px;'>
                                <div style='height:6px;background:rgba(255,255,255,0.10);
                                     border-radius:3px;overflow:hidden;'>
                                    <div style='width:{pct}%;height:100%;
                                         background:{bar_color};border-radius:3px;'></div>
                                </div>
                                <div style='font-family:"Rajdhani",sans-serif;font-size:12px;
                                     color:rgba(201,164,92,.60);margin-top:3px;'>
                                    {pct}% &nbsp;&middot;&nbsp; {"Pass" if pct >= 40 else "Below threshold"}</div>
                            </div>
                        </div>
                        {feedback_html}
                    </div>"""

                components.html(f"""
                <style>
                @import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@400;700&family=Cormorant+Garamond:wght@400;600&family=Orbitron:wght@700&display=swap');
                * {{ box-sizing:border-box; margin:0; padding:0; }}
                body {{ background:transparent; }}
                .sub-view {{
                    background:rgba(0,196,114,0.06);
                    border:1px solid rgba(0,196,114,0.25);
                    border-left:3px solid rgba(0,196,114,0.60);
                    border-radius:3px; padding:12px 16px;
                    font-family:'Cormorant Garamond',serif;
                    font-size:15px; color:rgba(255,245,220,0.92);
                    line-height:2.0; font-weight:500;
                }}
                .sub-heading {{
                    font-family:'Cinzel',serif; font-size:9px;
                    letter-spacing:0.18em; color:rgba(201,164,92,0.90);
                    text-transform:uppercase; margin-bottom:8px;
                }}
                b {{ color:#e8c87a; }}
                </style>
                <div class="sub-view">
                    <div class="sub-heading">Submission Record</div>
                    <b>File:</b> &nbsp;{_html.escape(str(file_name))}<br>
                    <b>Remarks:</b> &nbsp;{_html.escape(remarks) if remarks else "&#8212;"}<br>
                    <b>Submitted at:</b> &nbsp;{submitted_at}
                </div>
                {grade_block}
                """, height=(min(260 + 22 * (len(ai_feedback or "") // 90 + (ai_feedback or "").count(chr(10))), 900)
                            if grade_released else 120), scrolling=True)
        else:
            st.markdown("""
            <div class='upload-label'>Submit Your Work</div>
            """, unsafe_allow_html=True)

            up_col, note_col = st.columns([1, 1])

            with up_col:
                up_file = st.file_uploader(
                    "Upload file (PDF, DOCX, ZIP, etc.)",
                    key=f"up_{asn_id}",
                    type=["pdf", "docx", "doc", "zip", "txt", "png", "jpg", "jpeg"]
                )

            with note_col:
                remarks = st.text_area(
                    "Note to Instructor (optional)",
                    key=f"rem_{asn_id}",
                    placeholder="Add any notes, queries, or context for your instructor…",
                    height=100
                )

            btn_col, _ = st.columns([1, 4])
            with btn_col:
                sub_btn = st.button("Submit Assignment", key=f"sub_{asn_id}", type="primary")

            if overdue:
                st.warning(f"This assignment was due on {due_date}. You can still submit, "
                           f"but your instructor will see the submission date.")

            if sub_btn:
                if up_file is None:
                    st.warning("Please upload a file before submitting.")
                else:
                    file_bytes = up_file.read()
                    submit_assignment(asn_id, up_file.name, file_bytes, remarks)
                    st.success(f"Assignment '{title}' submitted successfully.")
                    st.rerun()

        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
