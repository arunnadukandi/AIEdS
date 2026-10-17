import streamlit as st
import streamlit.components.v1 as components
import sqlite3, base64, os, sys
from datetime import datetime

st.set_page_config(page_title="AIEdS - Cadet Chat", layout="wide",
                   initial_sidebar_state="collapsed")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
from theme import inject_theme_polish
DB_PATH  = os.path.join(BASE_DIR, "sahayak.db")
CHAT_DB  = os.path.join(BASE_DIR, "chat_sessions.db")

# ── Auth guard ────────────────────────────────────────────────────────────────
if "role" not in st.session_state or st.session_state.role != "student":
    st.error("Unauthorized. Please login."); st.stop()

my_username  = st.session_state.get("username", "unknown")
my_fullname  = st.session_state.get("full_name", my_username)
for pfx in ["CDT ", "Cdt ", "cdt "]:
    if my_fullname.startswith(pfx):
        my_fullname = my_fullname[len(pfx):]
        break

# ── Background ────────────────────────────────────────────────────────────────
def b64img(path):
    if path and os.path.exists(path):
        with open(path, "rb") as f: return base64.b64encode(f.read()).decode()
    return ""

bg_b64 = b64img(os.path.join(BASE_DIR, "chat_background.jpeg"))
bg_css = f'url("data:image/jpeg;base64,{bg_b64}") center/cover no-repeat fixed' if bg_b64 else "none"

# ── Chat DB (temporary — messages auto-expire) ────────────────────────────────
def init_chat_db():
    conn = sqlite3.connect(CHAT_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS messages (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        sender      TEXT NOT NULL,
        sender_name TEXT NOT NULL,
        receiver    TEXT NOT NULL,
        message     TEXT NOT NULL,
        sent_at     TEXT NOT NULL
    )""")
    # Delete messages older than 24 hours on every load
    conn.execute("""DELETE FROM messages
        WHERE sent_at < datetime('now', '-24 hours')""")
    conn.commit(); conn.close()

def get_all_cadets():
    """Get all cadets from sahayak.db except self."""
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT username, full_name FROM users WHERE username != ? AND role='student' ORDER BY full_name",
            (my_username,)
        ).fetchall()
        conn.close()
        return rows
    except Exception:
        return []

def get_messages(other_username):
    """Get conversation between me and another cadet."""
    conn = sqlite3.connect(CHAT_DB)
    rows = conn.execute("""
        SELECT sender, sender_name, message, sent_at FROM messages
        WHERE (sender=? AND receiver=?) OR (sender=? AND receiver=?)
        ORDER BY sent_at ASC
    """, (my_username, other_username, other_username, my_username)).fetchall()
    conn.close()
    return rows

def send_message(receiver, message):
    conn = sqlite3.connect(CHAT_DB)
    conn.execute("""INSERT INTO messages (sender, sender_name, receiver, message, sent_at)
        VALUES (?,?,?,?,?)""",
        (my_username, my_fullname, receiver,
         message.strip(), datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit(); conn.close()

def get_unread_count(other_username):
    """Count messages from other cadet not yet seen."""
    conn = sqlite3.connect(CHAT_DB)
    last_seen = st.session_state.get(f"last_seen_{other_username}", "2000-01-01 00:00:00")
    count = conn.execute("""
        SELECT COUNT(*) FROM messages
        WHERE sender=? AND receiver=? AND sent_at > ?
    """, (other_username, my_username, last_seen)).fetchone()[0]
    conn.close()
    return count

init_chat_db()

# ── CSS ────────────────────────────────────────────────────────────────────────
st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@400;600;700&family=Rajdhani:wght@400;500;600&display=swap');

[data-testid="stSidebar"],[data-testid="collapsedControl"],
#MainMenu,footer,header,[data-testid="stToolbar"] {{ display:none !important; }}
*,*::before,*::after {{ margin:0;padding:0;box-sizing:border-box; }}

.stApp {{
    background:linear-gradient(rgba(3,13,28,0.82),rgba(3,13,28,0.82)), {bg_css};
    min-height:100vh;
}}
.block-container {{ padding:20px 30px !important; max-width:100% !important; }}

/* ── Page header ── */
.chat-header {{
    text-align:center; padding:8px 0 20px 0;
    border-bottom:1px solid rgba(201,164,92,0.2);
    margin-bottom:20px;
}}
.chat-header h2 {{
    font-family:'Cinzel',serif; font-size:clamp(16px,2vw,24px); font-weight:700;
    background:linear-gradient(180deg,#ffffff 0%,#f5d98a 40%,#c9a45c 100%);
    -webkit-background-clip:text; -webkit-text-fill-color:transparent;
    letter-spacing:0.15em; text-transform:uppercase;
}}
.chat-header p {{
    font-family:'Rajdhani',sans-serif; font-size:13px;
    color:rgba(255,245,220,0.60); letter-spacing:0.06em; margin-top:4px;
}}

/* ── Cadet list ── */
.cadet-card {{
    background:rgba(1,5,14,0.85);
    border:1px solid rgba(201,164,92,0.25);
    border-left:3px solid rgba(201,164,92,0.60);
    border-radius:4px; padding:12px 16px; margin-bottom:8px;
    cursor:pointer; transition:all 0.2s;
    display:flex; align-items:center; justify-content:space-between;
}}
.cadet-card:hover {{ border-color:rgba(201,164,92,0.8); background:rgba(20,40,80,0.6); }}
.cadet-card.active {{
    border-left-color:#f5d98a;
    background:rgba(30,60,100,0.5);
}}
.cadet-name {{
    font-family:'Cinzel',serif; font-size:12px; font-weight:700;
    color:#e8c87a; letter-spacing:0.10em; text-transform:uppercase;
}}
.cadet-id {{
    font-family:'Rajdhani',sans-serif; font-size:11px;
    color:rgba(201,164,92,0.50); margin-top:2px;
}}
.unread-badge {{
    background:#e8a020; color:#000; border-radius:50%;
    width:20px; height:20px; display:flex; align-items:center;
    justify-content:center; font-size:10px; font-weight:700;
    font-family:'Rajdhani',sans-serif;
}}

/* ── Chat window ── */
.chat-window {{
    background:rgba(1,5,14,0.90);
    border:1px solid rgba(201,164,92,0.25);
    border-radius:6px; padding:16px;
    height:480px; overflow-y:auto;
    display:flex; flex-direction:column; gap:10px;
}}
.chat-window-header {{
    font-family:'Cinzel',serif; font-size:13px; font-weight:700;
    color:#e8c87a; letter-spacing:0.12em; text-transform:uppercase;
    padding-bottom:12px; border-bottom:1px solid rgba(201,164,92,0.15);
    margin-bottom:4px;
}}

/* ── Message bubbles ── */
.msg-row {{ display:flex; margin-bottom:6px; }}
.msg-row.mine {{ justify-content:flex-end; }}
.msg-row.theirs {{ justify-content:flex-start; }}

.bubble {{
    max-width:72%; padding:10px 14px; border-radius:12px;
    font-family:'Rajdhani',sans-serif; font-size:14px; line-height:1.5;
}}
.bubble.mine {{
    background:linear-gradient(135deg,#1a4a8a,#0d2d5c);
    border:1px solid rgba(79,163,227,0.4);
    color:#e0f0ff; border-bottom-right-radius:3px;
}}
.bubble.theirs {{
    background:rgba(40,30,10,0.9);
    border:1px solid rgba(201,164,92,0.30);
    color:#f0e8d0; border-bottom-left-radius:3px;
}}
.bubble-sender {{
    font-family:'Cinzel',serif; font-size:9px;
    color:rgba(201,164,92,0.70); letter-spacing:0.12em;
    text-transform:uppercase; margin-bottom:4px;
}}
.bubble-time {{
    font-size:10px; color:rgba(200,200,200,0.35);
    margin-top:4px; text-align:right;
}}

/* ── Empty state ── */
.no-chat {{
    display:flex; flex-direction:column; align-items:center;
    justify-content:center; height:100%;
    color:rgba(201,164,92,0.35);
    font-family:'Cinzel',serif; font-size:12px;
    letter-spacing:0.12em; text-transform:uppercase;
}}

/* ── Back button ── */
[data-testid="stButton"] > button[kind="secondary"] {{
    background:rgba(2,8,20,0.45) !important;
    border:1px solid rgba(201,164,92,0.32) !important;
    border-radius:3px !important; height:28px !important;
    padding:0 18px !important; font-family:'Cinzel',serif !important;
    font-size:9px !important; letter-spacing:0.16em !important;
    color:rgba(245,233,200,0.80) !important;
    text-transform:uppercase !important; white-space:nowrap !important;
}}

/* ── Send button ── */
[data-testid="stButton"] > button[kind="primary"] {{
    background:linear-gradient(135deg,#1a4a8a,#0d2d5c) !important;
    border:1px solid rgba(79,163,227,0.5) !important;
    border-radius:4px !important; height:42px !important;
    font-family:'Cinzel',serif !important; font-size:10px !important;
    letter-spacing:0.12em !important; color:#e0f0ff !important;
    text-transform:uppercase !important;
}}

/* ── Text input (message + search) ── */
.stTextInput input {{
    background:rgba(1,5,14,0.85) !important;
    border:1px solid rgba(201,164,92,0.30) !important;
    border-radius:4px !important; color:#f0e8d0 !important;
    font-family:'Rajdhani',sans-serif !important; font-size:14px !important;
    height:38px !important;
}}
.stTextInput input:focus {{
    border-color:rgba(201,164,92,0.70) !important;
    box-shadow:0 0 8px rgba(201,164,92,0.15) !important;
}}
.stTextInput input::placeholder {{
    color:rgba(201,164,92,0.35) !important;
    font-size:12px !important;
}}
</style>

<div class="chat-header">
    <h2>⚓ Cadet Comms</h2>
    <p>Secure one-to-one messaging · Session only · No logs retained</p>
</div>
""", unsafe_allow_html=True)

inject_theme_polish()

# ── Back button ───────────────────────────────────────────────────────────────
col_back, _ = st.columns([2, 8])
with col_back:
    if st.button("DASHBOARD", key="back_btn"):
        st.switch_page("pages/student.py")

st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

# ── Layout: cadet list | chat window ─────────────────────────────────────────
cadets = get_all_cadets()

if not cadets:
    st.markdown("""
    <div style='text-align:center;padding:60px;
        font-family:Cinzel,serif;font-size:13px;
        color:rgba(201,164,92,0.40);letter-spacing:0.12em;'>
        NO OTHER CADETS FOUND IN THE SYSTEM
    </div>""", unsafe_allow_html=True)
    st.stop()

list_col, chat_col = st.columns([1, 2], gap="large")

# ── Cadet list ────────────────────────────────────────────────────────────────
with list_col:
    st.markdown("""
    <p style='font-family:Cinzel,serif;font-size:10px;letter-spacing:0.18em;
       color:rgba(201,164,92,0.55);text-transform:uppercase;margin-bottom:6px;'>
       Select Cadet</p>
    """, unsafe_allow_html=True)

    # ── Search box ───────────────────────────────────────────────────────────
    search_query = st.text_input(
        "Search",
        placeholder="🔍  Search cadet name or ID...",
        key="cadet_search",
        label_visibility="collapsed"
    )

    selected = st.session_state.get("chat_with", None)

    # Filter cadets based on search
    filtered_cadets = []
    for uname, fname in cadets:
        display = fname or uname
        for pfx in ["CDT ", "Cdt ", "cdt "]:
            if display.startswith(pfx):
                display = display[len(pfx):]
                break
        if search_query.strip() == "" or            search_query.strip().lower() in display.lower() or            search_query.strip().lower() in uname.lower():
            filtered_cadets.append((uname, fname, display))

    if not filtered_cadets:
        st.markdown("""
        <p style='font-family:Rajdhani,sans-serif;font-size:12px;
           color:rgba(201,164,92,0.40);text-align:center;padding:20px 0;
           letter-spacing:0.08em;'>NO CADETS FOUND</p>
        """, unsafe_allow_html=True)

    for uname, fname, display in filtered_cadets:
        unread = get_unread_count(uname)
        active_cls = "active" if selected == uname else ""
        badge_html = f"<div class='unread-badge'>{unread}</div>" if unread > 0 else ""

        st.markdown(f"""
        <div class='cadet-card {active_cls}'>
            <div>
                <div class='cadet-name'>{display}</div>
                <div class='cadet-id'>{uname}</div>
            </div>
            {badge_html}
        </div>
        """, unsafe_allow_html=True)

        if st.button(f"Open chat", key=f"sel_{uname}", use_container_width=True):
            st.session_state.chat_with = uname
            st.session_state[f"last_seen_{uname}"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            st.rerun()

# ── Chat window ───────────────────────────────────────────────────────────────
with chat_col:
    if not selected:
        components.html("""
        <style>
        .chat-window {
            background:rgba(1,5,14,0.90);
            border:1px solid rgba(201,164,92,0.25);
            border-radius:6px; padding:16px;
            height:420px; display:flex;
            align-items:center; justify-content:center;
        }
        .no-chat {
            display:flex; flex-direction:column; align-items:center;
            color:rgba(201,164,92,0.35);
            font-family:Cinzel,serif; font-size:12px;
            letter-spacing:0.12em; text-transform:uppercase;
        }
        </style>
        <div class="chat-window">
            <div class="no-chat">
                <div style="font-size:32px;margin-bottom:12px;">⚓</div>
                <div>SELECT A CADET TO BEGIN</div>
            </div>
        </div>
        """, height=460, scrolling=False)
    else:
        # Mark all messages as read as soon as chat window opens
        st.session_state[f"last_seen_{selected}"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Get selected cadet name
        other_name = next((f for u, f in cadets if u == selected), selected)
        for pfx in ["CDT ", "Cdt ", "cdt "]:
            if other_name.startswith(pfx):
                other_name = other_name[len(pfx):]
                break

        messages = get_messages(selected)

        # Build message HTML
        msg_html = ""
        for sender, sender_name, message, sent_at in messages:
            is_mine = sender == my_username
            side    = "mine" if is_mine else "theirs"
            name    = "You" if is_mine else other_name
            time_str = sent_at[11:16]  # HH:MM

            msg_html += f"""
            <div class='msg-row {side}'>
                <div class='bubble {side}'>
                    <div class='bubble-sender'>{name}</div>
                    {message}
                    <div class='bubble-time'>{time_str}</div>
                </div>
            </div>"""

        if not msg_html:
            msg_html = "<div class='no-chat'><div>NO MESSAGES YET — SAY HELLO!</div></div>"

        chat_html = f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@600&family=Rajdhani:wght@500&display=swap');
        * {{ box-sizing:border-box; margin:0; padding:0; }}
        body {{ background:transparent; }}
        .chat-win-header {{
            font-family:'Cinzel',serif; font-size:13px; font-weight:700;
            color:#e8c87a; letter-spacing:0.12em; text-transform:uppercase;
            padding-bottom:10px; border-bottom:1px solid rgba(201,164,92,0.15);
            margin-bottom:10px;
        }}
        .chat-window {{
            background:rgba(1,5,14,0.90);
            border:1px solid rgba(201,164,92,0.25);
            border-radius:6px; padding:16px;
            height:420px; overflow-y:auto;
            display:flex; flex-direction:column; gap:8px;
        }}
        .msg-row {{ display:flex; margin-bottom:4px; }}
        .msg-row.mine {{ justify-content:flex-end; }}
        .msg-row.theirs {{ justify-content:flex-start; }}
        .bubble {{
            max-width:72%; padding:10px 14px; border-radius:12px;
            font-family:'Rajdhani',sans-serif; font-size:14px; line-height:1.5;
        }}
        .bubble.mine {{
            background:linear-gradient(135deg,#1a4a8a,#0d2d5c);
            border:1px solid rgba(79,163,227,0.4);
            color:#e0f0ff; border-bottom-right-radius:3px;
        }}
        .bubble.theirs {{
            background:rgba(40,30,10,0.9);
            border:1px solid rgba(201,164,92,0.30);
            color:#f0e8d0; border-bottom-left-radius:3px;
        }}
        .bubble-sender {{
            font-family:'Cinzel',serif; font-size:9px;
            color:rgba(201,164,92,0.70); letter-spacing:0.12em;
            text-transform:uppercase; margin-bottom:4px;
        }}
        .bubble-time {{
            font-size:10px; color:rgba(200,200,200,0.35);
            margin-top:4px; text-align:right;
        }}
        .no-chat {{
            display:flex; flex-direction:column; align-items:center;
            justify-content:center; height:100%;
            color:rgba(201,164,92,0.35);
            font-family:'Cinzel',serif; font-size:12px;
            letter-spacing:0.12em; text-transform:uppercase;
        }}
        </style>
        <div class="chat-win-header">💬 &nbsp;{other_name}</div>
        <div class="chat-window" id="chat-box">
            {msg_html}
        </div>
        <script>
            var el = document.getElementById('chat-box');
            if(el) el.scrollTop = el.scrollHeight;
        </script>
        """
        components.html(chat_html, height=500, scrolling=False)

        # ── Message input ─────────────────────────────────────────────────────
        st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

        # Use a counter as key suffix — incrementing forces a brand-new empty widget
        if "input_counter" not in st.session_state:
            st.session_state["input_counter"] = 0

        inp_col, btn_col = st.columns([5, 1])
        with inp_col:
            msg_input = st.text_input(
                "Message",
                placeholder=f"Message {other_name}... (Enter to send)",
                key=f"msg_input_{st.session_state['input_counter']}",
                label_visibility="collapsed"
            )
        with btn_col:
            send_btn = st.button("SEND ➤", key="send_btn", type="primary",
                                 use_container_width=True)

        if send_btn and msg_input.strip():
            send_message(selected, msg_input.strip())
            st.session_state[f"last_seen_{selected}"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            st.session_state["input_counter"] += 1
            st.rerun()

        # ── Auto-refresh every 5 seconds ──────────────────────────────────────
        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
        refresh_col, _ = st.columns([1, 3])
        with refresh_col:
            if st.button("🔄  Refresh", key="refresh_btn", use_container_width=True):
                st.session_state[f"last_seen_{selected}"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                st.rerun()
        st.caption("Messages auto-clear after 24 hours · No permanent logs")
