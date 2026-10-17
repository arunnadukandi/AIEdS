import streamlit as st
import sqlite3, hashlib, base64, os, sys

st.set_page_config(page_title="IEAS - Profile", layout="centered",
                   initial_sidebar_state="collapsed")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
from theme import inject_theme_polish
DB_PATH  = os.path.join(BASE_DIR, "sahayak.db")

if "role" not in st.session_state or st.session_state.role != "student":
    st.switch_page("login.py")
    st.stop()

def hash_password(p, salt=""): return hashlib.sha256((salt + p).encode()).hexdigest()
def make_salt(): return base64.b64encode(os.urandom(16)).decode()

cadet_name = st.session_state.get("full_name", st.session_state.get("username","Cadet"))
cadet_id   = st.session_state.get("username","—")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@400;600;700;900&family=Cormorant+Garamond:ital,wght@0,300;0,400;0,600;1,300;1,400&display=swap');

[data-testid="stSidebar"],[data-testid="collapsedControl"],
#MainMenu,footer,header,[data-testid="stToolbar"] { display:none !important; }
:root { --navy:#030d1c; --gold:#c9a45c; --goldl:#e8c87a; }
html,body { background:#030d1c !important; }
.stApp { background:linear-gradient(135deg,#030d1c 0%,#051630 50%,#030d1c 100%) !important; min-height:100vh; }
.block-container { padding:40px 40px !important; max-width:680px !important; margin:0 auto !important; }

/* Back button */
.stButton>button {
    background:rgba(6,16,40,0.80) !important;
    border:1px solid rgba(201,164,92,0.35) !important;
    border-radius:20px !important; height:34px !important;
    padding:0 18px !important; font-family:'Cinzel',serif !important;
    font-size:10px !important; letter-spacing:0.16em !important;
    color:rgba(245,233,200,0.90) !important; width:auto !important;
    box-shadow:none !important;
}
.stButton>button:hover {
    background:rgba(201,164,92,0.14) !important;
    border-color:rgba(201,164,92,0.60) !important; transform:none !important;
}
.stFormSubmitButton>button {
    background:linear-gradient(135deg,#b8923e,#e8c87a,#c9a45c) !important;
    color:#030d1c !important; font-family:'Cinzel',serif !important;
    font-weight:900 !important; font-size:11px !important;
    letter-spacing:0.26em !important; border:none !important;
    border-radius:8px !important; height:46px !important; width:100% !important;
}
.stTextInput label { color:var(--goldl) !important; font-size:10px !important; letter-spacing:0.20em !important; text-transform:uppercase !important; font-family:'Cinzel',serif !important; font-weight:700 !important; }
.stTextInput input { background-color:rgba(6,16,40,0.80) !important; border:1px solid rgba(201,164,92,0.35) !important; border-radius:8px !important; color:white !important; font-size:15px !important; height:44px !important; }
.stTextInput input:focus { border-color:var(--gold) !important; box-shadow:0 0 0 3px rgba(201,164,92,0.13) !important; }
.stAlert { border-radius:8px !important; background:rgba(3,13,28,0.92) !important; }
</style>
""", unsafe_allow_html=True)

inject_theme_polish()

# Back button
if st.button("← Back to Dashboard"):
    st.switch_page("pages/student.py")

st.markdown(f"""
<div style="text-align:center; padding:30px 0 20px 0;">
    <div style="font-size:72px; margin-bottom:12px;">👤</div>
    <p style="font-family:'Cinzel',serif; font-size:10px; letter-spacing:0.45em;
       color:#c9a45c; text-transform:uppercase; margin-bottom:8px;">Cadet Profile</p>
    <h1 style="font-family:'Cinzel',serif; font-size:36px; font-weight:900;
        background:linear-gradient(180deg,#fff 0%,#e8c87a 55%,#c9a45c 100%);
        -webkit-background-clip:text; -webkit-text-fill-color:transparent;
        background-clip:text; letter-spacing:0.06em; margin-bottom:0;">
        {cadet_name}
    </h1>
</div>

<div style="background:rgba(4,14,34,0.90); border:1px solid rgba(201,164,92,0.25);
     border-radius:16px; padding:28px 32px; margin-bottom:28px; position:relative; overflow:hidden;">
<div style="position:absolute;top:0;left:10%;right:10%;height:1px;
     background:linear-gradient(90deg,transparent,rgba(201,164,92,0.45),transparent);"></div>

<table style="width:100%; border-collapse:collapse;">
    <tr>
        <td style="font-family:'Cinzel',serif; font-size:9px; letter-spacing:0.22em;
                   color:#c9a45c; text-transform:uppercase; padding:12px 0 12px 0;
                   width:38%; border-bottom:1px solid rgba(201,164,92,0.10);">Academy ID</td>
        <td style="font-family:'Cormorant Garamond',serif; font-size:17px;
                   color:white; padding:12px 0; border-bottom:1px solid rgba(201,164,92,0.10);">
                   {cadet_id}</td>
    </tr>
    <tr>
        <td style="font-family:'Cinzel',serif; font-size:9px; letter-spacing:0.22em;
                   color:#c9a45c; text-transform:uppercase; padding:12px 0;
                   border-bottom:1px solid rgba(201,164,92,0.10);">Full Name</td>
        <td style="font-family:'Cormorant Garamond',serif; font-size:17px;
                   color:white; padding:12px 0; border-bottom:1px solid rgba(201,164,92,0.10);">
                   {st.session_state.get("full_name","—")}</td>
    </tr>
    <tr>
        <td style="font-family:'Cinzel',serif; font-size:9px; letter-spacing:0.22em;
                   color:#c9a45c; text-transform:uppercase; padding:12px 0;">Role</td>
        <td style="font-family:'Cormorant Garamond',serif; font-size:17px;
                   color:white; padding:12px 0;">Student</td>
    </tr>
</table>
</div>

<p style="font-family:'Cinzel',serif; font-size:9px; letter-spacing:0.35em;
   color:#c9a45c; text-transform:uppercase; text-align:center; margin-bottom:16px;">
   ✏ &nbsp; Update Details
</p>
""", unsafe_allow_html=True)

with st.form("pf"):
    nn  = st.text_input("Full Name", value=st.session_state.get("full_name",""))
    cp  = st.text_input("Current Password", type="password")
    np_ = st.text_input("New Password (blank = keep current)", type="password")
    if st.form_submit_button("Save Changes", use_container_width=True):
        if cp:
            with sqlite3.connect(DB_PATH) as conn:
                row = conn.execute("SELECT salt, password_hash FROM users WHERE id=?",
                                   (st.session_state.user_id,)).fetchone()
                db_salt, db_hash = row if row else ("", None)
                if db_hash is not None and hash_password(cp, db_salt) == db_hash:
                    if np_:
                        new_salt = make_salt()
                        conn.execute("UPDATE users SET full_name=?, password_hash=?, salt=? WHERE id=?",
                                     (nn, hash_password(np_, new_salt), new_salt, st.session_state.user_id))
                    else:
                        conn.execute("UPDATE users SET full_name=? WHERE id=?",
                                     (nn, st.session_state.user_id))
                    conn.commit()
                    st.success("Profile updated successfully!")
                    st.session_state.full_name = nn
                    st.rerun()
                else:
                    st.error("Current password is incorrect.")
        else:
            st.warning("Please enter your current password.")
