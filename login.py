import streamlit as st
import sqlite3
import hashlib
import hmac
import base64
import os
import re
import glob
import uuid
import sys

# --- DATABASE ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
from theme import inject_theme_polish
DB_PATH  = os.path.join(BASE_DIR, "sahayak.db")

# --- STREAM → TERM MAPPING ---
# ACE = Automation & Control Engineering
# ECE = Electronics & Communication Engineering
# NE  = Naval Engineering
ALL_TERMS = [f"Term_{i}" for i in range(1, 9)]
STREAM_TERMS = {
    "ACE": ALL_TERMS,
    "ECE": ALL_TERMS,
    "NE":  ALL_TERMS,
}
SECTIONS = ["Section A", "Section B", "Section C", "Section D"]

def create_tables():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()

        # --- existing users table (unchanged) ---
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT    NOT NULL UNIQUE,
                password_hash TEXT    NOT NULL,
                salt          TEXT    NOT NULL DEFAULT '',
                role          TEXT    NOT NULL,
                full_name     TEXT
            )""")

        # Migration: add columns to existing DBs without breaking them
        existing_cols = [r[1] for r in c.execute("PRAGMA table_info(users)").fetchall()]
        for col, definition in [
            ("salt",     "TEXT NOT NULL DEFAULT ''"),
            ("stream",   "TEXT NOT NULL DEFAULT ''"),   # ACE / ECE / NE
            ("category", "TEXT NOT NULL DEFAULT ''"),   # kept for backward-compat; unused
            ("term",     "TEXT NOT NULL DEFAULT ''"),
            ("section",  "TEXT NOT NULL DEFAULT ''"),
        ]:
            if col not in existing_cols:
                c.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")

        # --- instructor_mappings: one row per term+section an instructor teaches ---
        c.execute("""
            CREATE TABLE IF NOT EXISTS instructor_mappings (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                instructor_id INTEGER NOT NULL,
                term          TEXT    NOT NULL,
                section       TEXT    NOT NULL,
                FOREIGN KEY (instructor_id) REFERENCES users(id)
            )""")

        # --- term_upgrade_requests: cadets request term change, admin approves ---
        c.execute("""
            CREATE TABLE IF NOT EXISTS term_upgrade_requests (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                cadet_id       INTEGER NOT NULL,
                current_term   TEXT    NOT NULL,
                requested_term TEXT    NOT NULL,
                status         TEXT    NOT NULL DEFAULT 'pending',
                created_at     TEXT    NOT NULL DEFAULT (datetime('now')),
                reviewed_at    TEXT,
                FOREIGN KEY (cadet_id) REFERENCES users(id)
            )""")

        # --- session_tokens: one active token per user, invalidated on logout ---
        c.execute("""
            CREATE TABLE IF NOT EXISTS session_tokens (
                user_id    INTEGER PRIMARY KEY,
                token      TEXT    NOT NULL,
                created_at TEXT    NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )""")

        conn.commit()

create_tables()

# --- SESSION TOKEN HELPERS ---
def create_session_token(user_id: int) -> str:
    token = str(uuid.uuid4())
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO session_tokens (user_id, token, created_at) "
            "VALUES (?, ?, datetime('now'))",
            (user_id, token)
        )
        conn.commit()
    return token

def invalidate_session_token(user_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM session_tokens WHERE user_id=?", (user_id,))
        conn.commit()

def validate_session_token(user_id: int, token: str) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT token FROM session_tokens WHERE user_id=?", (user_id,)
        ).fetchone()
    return row is not None and row[0] == token

# --- AUTH HELPERS (unchanged) ---
def _make_salt() -> str:
    return base64.b64encode(os.urandom(16)).decode()

def hash_password(password: str, salt: str = "") -> str:
    return hashlib.sha256((salt + password).encode()).hexdigest()

def authenticate(username: str, password: str, role: str):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.cursor().execute(
            "SELECT id, role, full_name, password_hash, salt, stream, term, section "
            "FROM users WHERE username=?",
            (username,)
        ).fetchone()
    if row is None:
        return None, "no_user"
    uid, db_role, full_name, db_hash, db_salt, stream, term, section = row
    if db_role != role:
        return None, "wrong_role"
    if not hmac.compare_digest(hash_password(password, db_salt), db_hash):
        return None, "wrong_password"
    return (uid, db_role, full_name, stream, term, section), None

def sign_up_cadet(username, password, full_name, stream, term, section):
    if len(password) < 6:
        return False, "Password must be at least 6 characters."
    if not stream or not term or not section:
        return False, "Please select stream, term and section."
    # Academy number format: XXXX-X-XXX  e.g. 4736-C-110
    if not re.match(r"^\d{4}-[A-Za-z]{1}-\d{3}$", username):
        return False, "Invalid format. Use XXXX-X-XXX (e.g. 4736-C-110)."
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        if c.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            return False, "Academy number already registered."
        try:
            salt = _make_salt()
            c.execute(
                "INSERT INTO users (username, password_hash, salt, role, full_name, stream, term, section) "
                "VALUES (?, ?, ?, 'student', ?, ?, ?, ?)",
                (username, hash_password(password, salt), salt, full_name, stream, term, section)
            )
            conn.commit()
            return True, "Account created! Switch to Login."
        except Exception as e:
            return False, str(e)

def sign_up_instructor(username, password, full_name, mappings):
    """
    mappings: list of (term, section) tuples — empty at signup, added from dashboard later
    """
    if len(password) < 6:
        return False, "Password must be at least 6 characters."
    if not full_name.strip():
        return False, "Please enter your full name."
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        if c.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            return False, "Username already exists."
        try:
            salt = _make_salt()
            c.execute(
                "INSERT INTO users (username, password_hash, salt, role, full_name) "
                "VALUES (?, ?, ?, 'instructor', ?)",
                (username, hash_password(password, salt), salt, full_name)
            )
            instructor_id = c.lastrowid
            for term, section in mappings:
                c.execute(
                    "INSERT INTO instructor_mappings (instructor_id, term, section) VALUES (?, ?, ?)",
                    (instructor_id, term, section)
                )
            conn.commit()
            return True, "Instructor account created! Switch to Login."
        except Exception as e:
            return False, str(e)

# --- PAGE CONFIG (unchanged) ---
st.set_page_config(page_title="AIEdS · INA", layout="wide", initial_sidebar_state="collapsed")

# --- ASSET HELPERS (unchanged) ---
def b64(path: str) -> str:
    if path and os.path.exists(path):
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return ""

def find(base: str, *names: str):
    for n in names:
        p = os.path.join(base, n)
        if os.path.exists(p):
            return p
    return None

bg_path  = find(BASE_DIR, "loginbackground.jpeg", "loginbackground.jpg",
                           "background.jpeg",      "background.jpg")
oct_path = find(BASE_DIR, "octaginal-crest.png",  "octagonal-crest.png", "navy-crest.png")
ina_path = find(BASE_DIR, "ChatGPT_Image_Mar_28__2026__11_26_58_AM.png",
                           "ina-crest.png",         "ina_crest.png")
if not ina_path:
    m = glob.glob(os.path.join(BASE_DIR, "ChatGPT*.png")) + \
        glob.glob(os.path.join(BASE_DIR, "INA*.png"))
    ina_path = m[0] if m else None

if bg_path:
    ext    = "jpeg" if bg_path.endswith((".jpg", ".jpeg")) else "png"
    bg_css = f'url("data:image/{ext};base64,{b64(bg_path)}")'
else:
    bg_css = "linear-gradient(135deg,#06101f,#0d2040)"

oct_src = f"data:image/png;base64,{b64(oct_path)}" if oct_path else ""
ina_src = f"data:image/png;base64,{b64(ina_path)}" if ina_path else ""

# --- CSS (completely unchanged from original) ---
st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@400;600;700;900&family=Cormorant+Garamond:ital,wght@0,300;0,400;0,600;1,300;1,400&display=swap');

[data-testid="stSidebar"],[data-testid="collapsedControl"],
#MainMenu,footer,header,[data-testid="stToolbar"]{{
    display:none !important;
}}

*,*::before,*::after{{ margin:0; padding:0; box-sizing:border-box; }}
:root{{ --navy:#06101f; --gold:#c9a45c; --goldl:#e8c87a; --cream:#f5e9c8; }}

/* Change this section */
html {{ 
    overflow-y: auto !important; 
    height: auto !important; 
}}
body {{ 
    overflow-y: auto !important; 
    height: auto !important; 
}}

.stApp {{
    background: {bg_css} center/cover no-repeat fixed;
    height: auto !important; 
    min-height: 100vh !important; 
    overflow-y: auto !important; /* Forces scrollbar to appear if content is long */
}}

.stTextInput, .stSelectbox, .stMultiSelect {{ 
    margin-bottom: 2px !important; 
}}


.stApp::before{{
    content:''; position:fixed; inset:0; z-index:0; pointer-events:none;
    background:linear-gradient(to right,
        rgba(6,16,31,0.05) 0%, rgba(6,16,31,0.05) 35%,
        rgba(6,16,31,0.55) 58%, rgba(6,16,31,0.80) 100%);
}}

.block-container {{
    padding: 2rem 1rem 5rem 1rem !important; /* Added 5rem bottom padding so you can scroll past the bottom box */
    max-width: 100% !important;
    height: auto !important;
    overflow: visible !important; 
    position: relative; 
    z-index: 1;
}}

.crest{{
    position:fixed; top:18px; z-index:9999;
    width:86px; height:86px; object-fit:contain;
    filter:drop-shadow(0 3px 16px rgba(0,0,0,0.9));
    transition:transform .3s;
}}
.crest:hover{{ transform:scale(1.08); }}
.crest.left {{ left:22px; }}
.crest.right{{ right:22px; width:90px; height:90px; }}

    height:calc(100vh - 3rem) !important;
    align-items:center !important;
    gap:0 !important;
}}
div[data-testid="column"]:first-child > div{{
    background:transparent !important;
}}

div[data-testid="column"]:last-child
[data-testid="stVerticalBlockBorderWrapper"]{{
    background:rgba(4,10,22,0.80) !important;
    backdrop-filter:blur(22px) !important;
    -webkit-backdrop-filter:blur(22px) !important;
    border:1px solid rgba(201,164,92,0.32) !important;
    border-radius:18px !important;
    box-shadow:0 16px 64px rgba(0,0,0,0.70),
               inset 0 1px 0 rgba(201,164,92,0.22) !important;
    padding:15px 28px 15px 28px !important;
    max-width:420px !important;
    margin:0 40px 20px auto !important;
}}

.card-eyebrow{{
    margin-top: 50px;
    padding-right: 60px;
    font-family:'Cinzel',serif; font-size:13px;
    letter-spacing:0.18em; color:#e8c87a;
    font-weight:600;
    text-transform:uppercase; text-align:center;
    margin-bottom:10px; line-height:1.6;
    text-shadow:0 0 18px rgba(201,164,92,0.7), 0 2px 8px rgba(0,0,0,1);
}}
.card-heading{{
    font-family:'Cinzel',serif;
    font-size:28px; font-weight:900;
    color:#ffffff; text-align:center;
    letter-spacing:0.12em; line-height:1.18;
    margin-bottom:6px;
    background: linear-gradient(180deg, #ffffff 0%, #e8c87a 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    filter: drop-shadow(0 2px 8px rgba(0,0,0,1)) drop-shadow(0 0 20px rgba(201,164,92,0.4));
}}
.card-sub{{
    font-family:'Cormorant Garamond',serif;
    font-style:italic; font-size:12.5px;
    color:#ffffff; text-align:center;
    text-shadow:0 1px 10px rgba(0,0,0,1), 0 0 8px rgba(0,0,0,1);
    margin-bottom:4px;
}}
.card-divider{{
    width:65px; height:1px; margin:10px auto 14px auto;
    background:linear-gradient(90deg,transparent,var(--gold),transparent);
}}
.card-footer{{
    font-family:'Cinzel',serif; font-size:8px;
    letter-spacing:0.12em; color:rgba(245,233,200,0.26);
    text-align:center; margin-top:8px;
}}

[data-testid="stForm"]{{
    background:transparent !important;
    border:none !important; padding:0 !important;
}}

.stTabs [data-baseweb="tab-highlight"],
.stTabs [data-baseweb="tab-highlight-point"]{{ display:none !important; }}
.stTabs [data-baseweb="tab-list"], .stTabs [role="tablist"]{{
    background:rgba(6,16,31,0.55) !important;
    border:1px solid rgba(201,164,92,0.22) !important;
    border-radius:999px !important;
    padding:4px !important;
    justify-content:center !important; gap:2px !important;
    margin-bottom:16px !important;
}}
.stTabs [data-baseweb="tab"], .stTabs [role="tab"], .stTabs [data-testid="stTab"]{{
    background:transparent !important;
    color:rgba(245,238,220,0.82) !important;
    font-family:'Cinzel',serif !important;
    font-size:12.5px !important; font-weight:600 !important; letter-spacing:0.20em !important;
    padding:9px 20px !important;
    border-radius:999px !important;
    border-bottom:none !important;
    text-shadow:0 1px 8px rgba(0,0,0,1) !important;
    transition:all .2s ease !important;
}}
.stTabs [aria-selected="true"]{{
    background:linear-gradient(135deg,#b8923e 0%,#e8c87a 55%,#c9a45c 100%) !important;
    color:#0a1526 !important;
    font-weight:700 !important;
    text-shadow:none !important;
    box-shadow:0 4px 16px rgba(201,164,92,0.35) !important;
}}
.stTabs [data-baseweb="tab-panel"]{{ padding:0 !important; }}

div[role="radiogroup"] label,
div[role="radiogroup"] label p,
div[role="radiogroup"] label span,
[data-testid="stRadio"] label,
[data-testid="stRadio"] label p,
[data-testid="stRadio"] div[data-testid="stMarkdownContainer"] p {{
    color:#ffffff !important;
    font-size:13px !important;
    font-family:'Cinzel',serif !important;
    font-weight:700 !important;
    letter-spacing:0.14em !important;
    text-transform:uppercase !important;
    text-shadow:0 0 10px rgba(255,255,255,0.2), 0 2px 4px rgba(0,0,0,0.8) !important;
    opacity:1 !important;
}}
div[role="radiogroup"] input[type="radio"] {{
    accent-color:#c9a45c !important;
}}

.stTextInput, .stSelectbox, .stMultiSelect {{
    margin-bottom: 2px !important; 
}}

.stTextInput label, .stSelectbox label, .stMultiSelect label {{
    margin-bottom: 0px !important; /* This pulls the label closer to the input box */
}}
.stTextInput label{{
    color:#e8c87a !important;
    font-size:11px !important; letter-spacing:0.18em !important;
    text-transform:uppercase !important; font-family:'Cinzel',serif !important;
    font-weight:700 !important;
    text-shadow:0 0 10px rgba(0,0,0,1), 0 2px 6px rgba(0,0,0,1) !important;
}}
.stTextInput input{{
    background-color:rgba(6,16,31,0.90) !important;
    border:1px solid rgba(201,164,92,0.38) !important;
    border-radius:8px !important; color:white !important;
    font-size:14px !important; height:42px !important; padding:0 13px !important;
    transition:all .22s ease !important;
}}
.stTextInput input:focus{{
    border-color:var(--gold) !important;
    background-color:rgba(6,16,31,0.96) !important;
    box-shadow:0 0 0 3px rgba(201,164,92,0.13) !important;
}}
.stTextInput input::placeholder{{ color:rgba(245,233,200,0.42) !important; }}

/* Selectbox and multiselect styling to match the card theme */
.stSelectbox label, .stMultiSelect label {{
    color:#e8c87a !important;
    font-size:11px !important; letter-spacing:0.18em !important;
    text-transform:uppercase !important; font-family:'Cinzel',serif !important;
    font-weight:700 !important;
    text-shadow:0 0 10px rgba(0,0,0,1), 0 2px 6px rgba(0,0,0,1) !important;
}}
.stSelectbox [data-baseweb="select"] > div,
.stMultiSelect [data-baseweb="select"] > div {{
    background-color:rgba(6,16,31,0.55) !important;
    border:1px solid rgba(201,164,92,0.38) !important;
    border-radius:8px !important; color:white !important;
}}
.stSelectbox [data-baseweb="select"] span,
.stMultiSelect [data-baseweb="select"] span {{
    color:white !important; font-size:13px !important;
}}
/* Dropdown option list — popover container */
[data-baseweb="popover"] [data-baseweb="menu"],
[data-baseweb="select"] [data-baseweb="menu"] {{
    background-color:rgba(8,20,45,0.97) !important;
    border:1px solid rgba(201,164,92,0.45) !important;
    border-radius:8px !important;
    box-shadow:0 8px 32px rgba(0,0,0,0.80) !important;
}}
/* Dropdown option list text */
[data-baseweb="popover"] li,
[data-baseweb="popover"] li span,
[data-baseweb="menu"] li,
[data-baseweb="menu"] li span,
[data-baseweb="select"] [role="option"],
[data-baseweb="select"] [role="option"] span {{
    color:#f0e6cc !important;
    font-size:13px !important;
    font-family:'Cinzel',serif !important;
    letter-spacing:0.06em !important;
    background-color:transparent !important;
}}
/* Hovered / focused option */
[data-baseweb="menu"] li:hover,
[data-baseweb="menu"] [aria-selected="true"],
[data-baseweb="select"] [role="option"]:hover,
[data-baseweb="select"] [role="option"][aria-selected="true"] {{
    background-color:rgba(201,164,92,0.20) !important;
    color:#e8c87a !important;
}}
/* Selected value and placeholder always white */
[data-baseweb="select"] > div > div,
[data-baseweb="select"] input,
[data-baseweb="select"] [data-testid="stMarkdownContainer"] p {{
    color:white !important;
}}

.stButton>button,.stFormSubmitButton>button{{
    background:linear-gradient(135deg,#b8923e 0%,#e8c87a 52%,#c9a45c 100%) !important;
    color:var(--navy) !important; font-family:'Cinzel',serif !important;
    font-weight:900 !important; font-size:10.5px !important;
    letter-spacing:0.28em !important; text-transform:uppercase !important;
    border:none !important; border-radius:8px !important;
    width:100% !important; height:44px !important; margin-top:6px !important;
    box-shadow:0 4px 22px rgba(201,164,92,0.36) !important;
    transition:all .22s ease !important;
}}
.stButton>button:hover,.stFormSubmitButton>button:hover{{
    background:linear-gradient(135deg,#c9a45c 0%,#f5d98a 52%,#e8c87a 100%) !important;
    box-shadow:0 8px 32px rgba(201,164,92,0.52) !important;
    transform:translateY(-2px) !important;
}}

/* Error alert — bright red, always readable */
div[data-testid="stAlert"][data-baseweb="notification"]{{
    border-radius:8px !important;
    margin-top:6px !important; margin-bottom:4px !important;
    padding:10px 14px !important;
}}
div[data-testid="stAlert"] p,
div[data-testid="stAlert"] span,
div[data-testid="stAlert"] div {{
    font-size:12px !important;
    font-family:'Cinzel',serif !important;
    letter-spacing:0.06em !important;
}}
/* Error — dark navy background, bright red-white text */
div[data-testid="stAlert"][kind="error"],
div[data-baseweb="notification"][kind="error"]{{
    background:rgba(4,8,20,0.96) !important;
    border:1px solid rgba(255,90,90,0.75) !important;
    border-left:3px solid #ff5a5a !important;
}}
div[data-testid="stAlert"][kind="error"] p,
div[data-testid="stAlert"][kind="error"] span,
div[data-testid="stAlert"][kind="error"] div {{
    color:#ff9090 !important;
}}
/* Success — dark navy background, bright green text */
div[data-testid="stAlert"][kind="success"]{{
    background:rgba(4,8,20,0.96) !important;
    border:1px solid rgba(60,220,100,0.75) !important;
    border-left:3px solid #3cdc64 !important;
}}
div[data-testid="stAlert"][kind="success"] p,
div[data-testid="stAlert"][kind="success"] span,
div[data-testid="stAlert"][kind="success"] div {{
    color:#7eeea0 !important;
}}

div[data-testid="stVerticalBlock"]>div{{ gap: 0.1rem !important; }}
/* Hide internal hidden goto-login buttons */
button[kind="secondary"]:has(p:empty),
[data-testid="stButton"]:has(button p:empty) {{ display:none !important; }}
::-webkit-scrollbar{{ display:none; }}

/* Hide browser-native "Press Enter to submit form" tooltip */
input::-webkit-input-placeholder {{ }}
form input {{ -webkit-user-modify: read-write-plaintext-only; }}
[title="Press Enter to submit form"],
[aria-label="Press Enter to submit form"] {{
    display:none !important;
    visibility:hidden !important;
    opacity:0 !important;
}}
/* Streamlit's own enter-to-submit helper text */
div[data-testid="InputInstructions"],
div[data-testid="InputInstructions"] * {{
    display:none !important;
}}
</style>

<script>
document.addEventListener('DOMContentLoaded', function() {{
    document.querySelectorAll('form').forEach(f => f.setAttribute('novalidate', ''));
}});
const _obs = new MutationObserver(() => {{
    document.querySelectorAll('form:not([novalidate])').forEach(f => f.setAttribute('novalidate', ''));
}});
_obs.observe(document.body, {{ childList: true, subtree: true }});
</script>

{"<img class='crest left'  src='" + oct_src + "' alt='Navy Crest'/>" if oct_src else ""}
{"<img class='crest right' src='" + ina_src + "' alt='INA Crest'/>"  if ina_src else ""}
""", unsafe_allow_html=True)

inject_theme_polish()

# --- LAYOUT ---
_, right_col = st.columns([2, 1])

with right_col:
    with st.container(border=True):

        st.markdown("""
            <p class="card-eyebrow">Artificial Intelligence Education System &nbsp;·&nbsp; AIEdS</p>
            <h2 class="card-heading">INDIAN NAVAL ACADEMY</h2>
            <div class="card-divider"></div>
        """, unsafe_allow_html=True)

                # 1. Add the state check here
        if 'active_tab' not in st.session_state:
            st.session_state.active_tab = 0

        # 2. This is the exact line to replace/update
        # --- TAB LOGIC WITH AUTO-RESET ---
        # Get the tab index from URL, default to 0 (Login)
        query_params = st.query_params
        default_tab = int(query_params.get("tab", 0))

        # We use the 'index' parameter to force the tab selection
        tab_login, tab_signup = st.tabs(["  LOGIN  ", "  SIGN UP  "])
        
        # If we just signed up, we want to force the user into the first tab
        if default_tab == 0:
            active_tab = tab_login
        else:
            active_tab = tab_signup


        # ── LOGIN TAB (unchanged logic, enriched session state) ──────────────
        with tab_login:
            l_role = st.radio("Role", ["student", "instructor", "admin"],
                              horizontal=True, key="lr", label_visibility="collapsed")

            l_label       = ("Academy Number" if l_role == "student"
                             else "Admin Username" if l_role == "admin" else "Username")
            l_placeholder = "e.g. 4736-C-110" if l_role == "student" else ""

            with st.form("login_form"):
                l_user = st.text_input(l_label, placeholder=l_placeholder,
                                       key=f"lu_{l_role}")
                l_pass = st.text_input("Password", type="password",
                                       key=f"lp_{l_role}")
                if st.form_submit_button("Login to AIEdS"):
                    l_user = l_user.strip()
                    if not l_user and not l_pass:
                        st.error("Please enter your credentials.")
                    elif not l_user:
                        st.error("Please enter your username.")
                    elif not l_pass:
                        st.error("Please enter your password.")
                    else:
                        user_data, reason = authenticate(l_user, l_pass, l_role)
                        if user_data:
                            uid, role, full_name, stream, term, section = user_data
                            # Generate unique session token for this login
                            token = create_session_token(uid)
                            # Core session
                            st.session_state.user_id       = uid
                            st.session_state.role          = role
                            st.session_state.full_name     = full_name
                            st.session_state.username      = l_user
                            st.session_state.session_token = token
                            # Stream / term / section
                            st.session_state.stream        = stream
                            st.session_state.category      = stream   # backward-compat alias
                            st.session_state.term          = term
                            st.session_state.section       = section
                            # Set selected_term for chatbot/quiz compatibility
                            if term:
                                st.session_state.selected_term = term
                            st.switch_page(f"pages/{role}.py")
                        else:
                            msgs = {
                                "no_user"       : "Invalid username or password.",
                                "wrong_role"    : f"This account is not registered as {l_role}. Select the correct role.",
                                "wrong_password": "Invalid username or password.",
                            }
                            st.error(msgs.get(reason, "Authentication failed. Please try again."))

        # ── SIGN-UP TAB ──────────────────────────────────────────────────────
        with tab_signup:
            s_role = st.radio("Role", ["student", "instructor"],
                              horizontal=True, key="sr", label_visibility="collapsed")

            # --- CADET SIGN-UP ---
            if s_role == "student":
                s_stream = st.selectbox(
                    "Stream",
                    list(STREAM_TERMS.keys()),
                    format_func=lambda x: {"ACE": "ACE — Automation & Control Engineering",
                                           "ECE": "ECE — Electronics & Communication Engineering",
                                           "NE":  "NE  — Naval Engineering"}.get(x, x),
                    key="ss_stream_student"
                )
                s_term = st.selectbox(
                    "Current Term",
                    STREAM_TERMS[st.session_state.get("ss_stream_student", "ACE")],
                    key="st_student"
                )

                with st.form("signup_form_student"):
                    s_name = st.text_input("Full Name", placeholder="e.g. Arjun Kumar", key="sn_student")
                    s_user = st.text_input("Academy Number", placeholder="e.g. 4736-C-110", key="su_student")
                    s_pass = st.text_input("Password", type="password", key="sp_student")
                    s_section = st.selectbox("Section", SECTIONS, key="sse_student")
                    cadet_msg = st.empty()

                    if st.form_submit_button("Create Cadet Account"):
                        s_name, s_user = s_name.strip(), s_user.strip()
                        final_stream = st.session_state.get("ss_stream_student", "ACE")
                        final_term   = st.session_state.get("st_student", "Term_1")

                        if not s_name or not s_user or not s_pass:
                            cadet_msg.error("Please fill in all fields.")
                        else:
                            ok, msg = sign_up_cadet(s_user, s_pass, s_name, final_stream, final_term, s_section)
                            if ok:
                                st.session_state.signup_success = True
                            else:
                                cadet_msg.error(msg)

                # --- CORRECT INDENTATION: Aligned with 'with st.form' ---
                if st.session_state.get("signup_success"):
                    cadet_msg.markdown("""
                        <div style="background:rgba(4,8,20,0.96);
                                    border:1px solid rgba(60,220,100,0.75);
                                    border-left:3px solid #3cdc64;
                                    border-radius:10px; padding:18px;
                                    text-align:center; margin:8px 0;">
                            <div style="font-size:24px; margin-bottom:8px;">✅</div>
                            <div style="font-family:'Cinzel',serif; font-size:11px;
                                        color:#7eeea0; letter-spacing:0.14em; margin-bottom:4px;">
                                ACCOUNT CREATED SUCCESSFULLY
Please login with the credentials just enetered
                            </div>
                        </div>
                    """, unsafe_allow_html=True)
                    
                    
                    
                        




            # ── INSTRUCTOR SIGN-UP ────────────────────────────────────────
            else:
                with st.form("signup_form_instructor"):
                    s_name = st.text_input("Full Name", placeholder="e.g. Cdr. Rajesh Nair",
                                           key="sn_instructor")
                    s_user = st.text_input("Instructor Code", placeholder="e.g. INST-001",
                                           key="su_instructor")
                    s_pass = st.text_input("Password", type="password", key="sp_instructor")
                    submitted_instructor = st.form_submit_button("Create Instructor Account")

                inst_msg = st.empty()

                if submitted_instructor:
                    s_name = s_name.strip()
                    s_user = s_user.strip()

                    if not s_name or not s_user or not s_pass:
                        inst_msg.error("Please fill in all fields.")
                    else:
                        ok, msg = sign_up_instructor(s_user, s_pass, s_name, [])
                        if ok:
                            inst_msg.markdown("""
                                <div style="background:rgba(4,8,20,0.96);
                                            border:1px solid rgba(60,220,100,0.75);
                                            border-left:3px solid #3cdc64;
                                            border-radius:10px; padding:18px;
                                            text-align:center; margin:8px 0;">
                                    <div style="font-size:24px; margin-bottom:8px;">✅</div>
                                    <div style="font-family:'Cinzel',serif; font-size:12px;
                                                color:#7eeea0; letter-spacing:0.18em; margin-bottom:4px; font-weight:700;">
                                        INSTRUCTOR ACCOUNT CREATED
                                    </div>
                                </div>
                            """, unsafe_allow_html=True)
                        else:
                            inst_msg.error(msg)
