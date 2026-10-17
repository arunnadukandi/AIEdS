import streamlit as st
import os, json, faiss, sqlite3, time, base64, re, io, sys
import numpy as np
from sentence_transformers import SentenceTransformer
from ollama import Client
from httpx import Timeout

st.set_page_config(page_title="AIEdS - AI Chatbot", layout="wide",
                   initial_sidebar_state="collapsed")

os.environ['NO_PROXY']               = 'localhost,127.0.0.1'
os.environ['OLLAMA_FLASH_ATTENTION'] = '1'
os.environ['OLLAMA_KV_CACHE_TYPE']   = 'q8_0'

BASE_DIR          = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USER_PROFILES_DIR = os.path.join(BASE_DIR, "user_profiles")
sys.path.insert(0, BASE_DIR)
from theme import inject_theme_polish

# 1. Fetch values from session state so the variables are defined
selected_subject = st.session_state.get("selected_subject", "—")
selected_term    = st.session_state.get("selected_term", "Term_1")

if "last_subject" not in st.session_state:
    st.session_state.last_subject = selected_subject

if st.session_state.last_subject != selected_subject:
    # WIPE CHAT: Clear history for the new subject
    st.session_state.messages = []
    st.session_state.chatbot_topics_asked = []
    st.session_state.chatbot_context_store = {}
    st.session_state.current_cache_id = None
    
    # Update tracker
    st.session_state.last_subject = selected_subject
    st.rerun() # Refresh to show empty chat for the new subject
# ──────────────────────────────────────────────────────────────────────────


# 2. Define the folder path based on the selected term
folder = os.path.join(USER_PROFILES_DIR, selected_term)

# 3. Create the subject-specific filename slug
s_name = selected_subject.replace(" ", "_").lower()

# 4. Define your dynamic cache paths
CACHE_DB_PATH    = os.path.join(folder, f"{s_name}_cache.db")
CACHE_INDEX_PATH = os.path.join(folder, f"{s_name}_qcache.index")  # answer cache ONLY — never the book index

# ── Auth guard ────────────────────────────────────────────────────────────────
if "role" not in st.session_state or st.session_state.role != "student":
    st.switch_page("login.py")
    st.stop()


# ── Early session state inits (must be before sidebar renders) ────────────────
if "chatbot_mode" not in st.session_state:
    st.session_state.chatbot_mode = "standard"  # standard | oral | nautical

# ── Hide default Streamlit sidebar nav IMMEDIATELY — before anything renders ──
st.markdown("""
<style>
[data-testid="stSidebarNav"],
[data-testid="stSidebarNavItems"],
[data-testid="stSidebarNavSeparator"],
section[data-testid="stSidebar"] > div:first-child > div:first-child ul,
#MainMenu, footer, header, [data-testid="stToolbar"],
[data-testid="stStatusWidget"], div[class*="StatusWidget"],
.stSpinner, div:has(>.stSpinner) { display: none !important; }
</style>
""", unsafe_allow_html=True)

# ── ORIGINAL proven cache_resource — exactly as the fast version ──────────────
@st.cache_resource(show_spinner=False)
def get_ollama_client():
    return Client(host='http://127.0.0.1:11434', timeout=Timeout(120.0))

@st.cache_resource(show_spinner=False)
def load_emb_model():
    # Prefer the bundled local model (same pattern as pages/instructor.py) so
    # this works offline / without a trusted path to huggingface.co — only
    # fall back to fetching by name from the Hub if it isn't present.
    model_path = os.path.join(BASE_DIR, "Python-3.12.9", "embedding_model")
    target = model_path if os.path.exists(model_path) else 'all-MiniLM-L6-v2'
    return SentenceTransformer(target, device='cpu')

ollama_client = get_ollama_client()

# ── Text model (one place to change it) ───────────────────────────────────────
CHAT_MODEL = "deepseek-r1:14b"
VISION_MODEL = "qwen3-vl:8b"   # reads images & handwriting
CHAT_THINK = False   # False = answer starts immediately; True = model reasons first (slower)

def _llm_chat(**kw):
    """ollama chat call with think on/off; falls back if the ollama package is too old."""
    try:
        return ollama_client.chat(think=CHAT_THINK, **kw)
    except TypeError:
        return ollama_client.chat(**kw)

# ── Handwriting reading (vision model) ────────────────────────────────────────
HANDWRITING_MODELS = [VISION_MODEL, "gemma3:12b"]   # tried in this order
HW_AUTO_PROMPT = ("📝 Read my handwritten note. If it contains questions, answer each one "
                  "step by step; otherwise explain the note clearly and point out any mistakes.")
HANDWRITING_PROMPT = (
    "This image is a photo or scan of handwritten notes or a handwritten question paper. "
    "Transcribe ALL the handwritten text exactly as written, line by line, top to bottom. "
    "Write equations in LaTeX ($...$). Keep question numbers. "
    "If a diagram is drawn, describe it in one line inside [brackets]. "
    "If a word is unreadable write [?]. Output ONLY the transcription, no comments."
)

def _prep_image(img_bytes, max_side=1600):
    """Shrink big phone photos and convert to JPEG so the vision model is fast."""
    try:
        from PIL import Image, ImageOps
        im = ImageOps.exif_transpose(Image.open(io.BytesIO(img_bytes))).convert("RGB")
        im.thumbnail((max_side, max_side))
        buf = io.BytesIO(); im.save(buf, format="JPEG", quality=90)
        return buf.getvalue()
    except Exception:
        return img_bytes

def transcribe_handwriting(img_bytes):
    """Returns (text, model_used). Tries qwen3-vl first, then gemma3:12b."""
    b64 = base64.b64encode(_prep_image(img_bytes)).decode()
    for m in HANDWRITING_MODELS:
        try:
            r = _llm_chat(model=m, stream=False, keep_alive=-1,
                          messages=[{"role": "user", "content": HANDWRITING_PROMPT, "images": [b64]}],
                          options={"num_gpu": 64, "temperature": 0.0, "num_ctx": 8192})
            text = (r["message"]["content"] if isinstance(r, dict) else r.message.content).strip()
            text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
            if text:
                return text, m
        except Exception:
            continue
    return "", None

def transcribe_pdf_pages(pdf_bytes, max_pages=6):
    """Scanned / handwritten PDF: render each page and read it with the vision model."""
    import fitz
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    out = []
    for i, page in enumerate(doc):
        if i >= max_pages:
            out.append(f"[Only the first {max_pages} pages were read]")
            break
        png = page.get_pixmap(dpi=150).tobytes("png")
        text, _ = transcribe_handwriting(png)
        out.append(f"Page {i+1}:\n{text or '[could not read this page]'}")
    doc.close()
    return "\n\n".join(out)

def _reading_box(sub):
    return f"""
        <div class="thinking-box">
            <div class="thinking-icon">✍️</div>
            <div class="thinking-text">
                <div class="thinking-label">Reading handwriting
                    <span class="thinking-dots"><span></span><span></span><span></span></span>
                </div>
                <div class="thinking-sub">{sub}</div>
            </div>
        </div>"""
emb_model     = load_emb_model()

# ── DB: auto-create cache table if missing ────────────────────────────────────
# ── Helper Functions using Global Subject-Specific Paths ─────────────────────

def _ensure_cache_db():
    """Uses global CACHE_DB_PATH to ensure the correct subject DB exists."""
    with sqlite3.connect(CACHE_DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                query    TEXT NOT NULL,
                answer   TEXT NOT NULL,
                feedback INTEGER DEFAULT NULL,
                comment  TEXT DEFAULT NULL
            )
        """)
        conn.commit()

def save_to_cache(query, answer):
    """Store a question/answer pair. The vector goes into {subject}_qcache.index,
    tagged with the database row id, so the book index is never touched."""
    _ensure_cache_db()
    vec = emb_model.encode([query]).astype('float32')
    faiss.normalize_L2(vec)

    with sqlite3.connect(CACHE_DB_PATH) as conn:
        row_id = conn.execute(
            "INSERT INTO cache (query,answer) VALUES (?,?)", (query, answer)
        ).lastrowid

    index = None
    if os.path.exists(CACHE_INDEX_PATH):
        try:
            index = faiss.read_index(CACHE_INDEX_PATH)
        except Exception:
            index = None
    if index is None:
        index = faiss.IndexIDMap(faiss.IndexFlatIP(vec.shape[1]))

    index.add_with_ids(vec, np.array([row_id], dtype='int64'))
    faiss.write_index(index, CACHE_INDEX_PATH)
    return row_id

def get_semantic_cache(query, threshold=0.8):
    """Return (answer, row_id) for a near-identical past question, else (None, None)."""
    if not os.path.exists(CACHE_INDEX_PATH) or not os.path.exists(CACHE_DB_PATH):
        return None, None
    try:
        idx = faiss.read_index(CACHE_INDEX_PATH)
        vec = emb_model.encode([query]).astype('float32')
        faiss.normalize_L2(vec)
        D, I = idx.search(vec, 1)
        if I[0][0] != -1 and D[0][0] > threshold:
            row_id = int(I[0][0])
            with sqlite3.connect(CACHE_DB_PATH) as conn:
                res = conn.execute(
                    "SELECT answer FROM cache WHERE id = ?", (row_id,)
                ).fetchone()
            if res:
                return res[0], row_id
    except Exception:
        pass
    return None, None

def update_feedback(cache_id, score):
    """Updates feedback in the global CACHE_DB_PATH."""
    if os.path.exists(CACHE_DB_PATH):
        with sqlite3.connect(CACHE_DB_PATH) as conn:
            conn.execute("UPDATE cache SET feedback = ? WHERE id = ?", (score, cache_id))
            conn.commit()

# ── System prompt — instructs model to use LaTeX ──────────────────────────────
def get_oral_board_prompt():
    return (
        "You are a strict Oral Board / Viva answer generator for Indian Naval Academy cadets.\n"
        "A CONTEXT block extracted from the cadet's subject manual will be provided.\n\n"
        "ABSOLUTE RULES:\n"
        "- Use ONLY the information inside the CONTEXT block below. Nothing else.\n"
        "- If the CONTEXT does not contain the answer, respond exactly: 'This topic is not found in the selected manual section. Please refer to the full manual.'\n"
        "- Do NOT use your training knowledge. Do NOT add outside information.\n"
        "- Keep the answer to 100-120 words. Clear, simple, naval tone.\n"
        "- No filler phrases like 'Great question'. Go straight to the answer.\n"
        "- If a formula exists in the CONTEXT, include it in one line.\n"
        "- If steps exist in the CONTEXT, list max 4 bullet points.\n"
    )



# ── DeepSeek-R1 question-type router ─────────────────────────────────────────
import re as _re

def detect_question_type(query: str) -> str:
    """Return 'numerical' for calculation/derivation queries, else 'theoretical'."""
    patterns = [
        r"\b(calculat|comput|find|solv|determin|evaluat|deriv|show that|prov)\w*\b",
        r"\d+\s*(hz|mhz|ghz|khz|db|v|a|w|f|h|ohm|rad|°|deg|km|ms|us|ns)\b",
        r"\b(formula|expression|equation|value of|magnitude|phase|gain|bandwidth|snr|ber|"
        r"bit rate|sampling|fourier|laplace|z-transform|convolution|impulse|step|ramp)\b",
    ]
    q = query.lower()
    for pat in patterns:
        if _re.search(pat, q):
            return "numerical"
    return "theoretical"

def get_adaptive_prompt():
    pref = st.session_state.get('user_difficulty_preference', 'standard')
    if pref == 'not_clear':
        style = (
            "TEACHING STYLE: Extreme Simplicity. The student is completely lost. "
            "Use a real-world everyday analogy to explain the concept. Avoid all technical jargon. "
            "Use very short sentences and numbered bullet points only. Do not use complex math."
        )
    elif pref == 'need_clarity':
        style = (
            "TEACHING STYLE: Moderate Clarity. The student needs a simpler explanation. "
            "Restate the concept in plain language, provide one relatable example, "
            "and explain every variable/symbol in any equation used."
        )
    else:
        style = "TEACHING STYLE: Standard technical depth suitable for a Naval Academy Cadet."

    mode = detect_question_type(
        st.session_state.get("chatbot_last_query", "")
    )
    num_instruction = (
        "RULE 0: NUMERICAL PROBLEMS\n"
        "   - Show every step. State the formula, substitute values, simplify.\n"
        "   - Always include units at every step.\n"
        "   - Box the final answer using: **Answer: <value> <unit>**\n"
        "   - If the context lacks data for the calculation, say so explicitly.\n\n"
    ) if mode == "numerical" else ""

    return (
        f"You are the AIEdS Instructor. {style}\n\n"
        f"{num_instruction}"
        "RULE 1: MATHEMATICS (LaTeX Formatting)\n"
        "   - Use LaTeX for ALL math. Use $...$ for inline and $$...$$ for block equations.\n"
        "   - NEVER use plain text fractions like 'a/b'. Always use \\frac{{}}{{}}.\n"
        "   - FORMAT EXAMPLE: $$[Result] = \\frac{{[Variable_A] \\cdot [Variable_B]}}{{[Variable_C]^2}}$$\n"
        "   - NOTE: The example above is for FORMATTING ONLY. Use formulas appropriate to the current subject.\n"
        "   - CRITICAL: Every LaTeX environment must be closed (e.g., \\begin{{cases}}...\\end{{cases}}).\n\n"
        
        "RULE 2: PROGRAMMING (Code Blocks)\n"
        "   - Use standard Markdown code blocks (e.g., ```python) for logic.\n"
        "   - NEVER put programming code inside LaTeX dollar signs ($).\n\n"
        
        "RULE 3: BLOCK DIAGRAMS (ASCII Art)\n"
        "   - When a block diagram helps explain a system, generate it using ASCII art inside a code block.\n"
        "   - Use +-------+ for boxes, | text | for content, and arrows (↓ or →) for connections.\n"
        "   - Always centre-align the diagram and use a plain '''text''' code block.\n"
        "   - Example:\n"
        "     ```text\n"
        "     +-------------------+\n"
        "     |    AC Input       |\n"
        "     +-------------------+\n"
        "               ↓\n"
        "     +-------------------+\n"
        "     |   Transformer     |\n"
        "     +-------------------+\n"
        "               ↓\n"
        "     +-------------------+\n"
        "     |    AC Output      |\n"
        "     +-------------------+\n"
        "     ```\n\n"
        
        "RULE 4: SOURCE & TONE\n"
        "   - Strictly use the provided 'Context' manual to answer.\n"
        "   - Professional, authoritative, and encouraging Naval persona."
    )
    
# ── Message renderer ─────────────────────────────────────────────────────────
def render_message(content):
    """Renders assistant messages using st.markdown."""
    st.markdown(content)

# ── Background image ──────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def _bg_b64():
    for name in ["chatbot_background.jpeg", "chatbot_background.png", "chatbot_background.jpg", "mainpage.jpeg"]:
        p = os.path.join(BASE_DIR, name)
        if os.path.exists(p):
            with open(p, "rb") as f:
                data = f.read()
            ext = "png" if data[:8] == b'\x89PNG\r\n\x1a\n' else "jpeg"
            return base64.b64encode(data).decode(), ext
    return "", "jpeg"

_bg_data, _bg_ext = _bg_b64()
_bg_url = f"data:image/{_bg_ext};base64,{_bg_data}" if _bg_data else ""

# ── Sidebar logo ──────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def _logo_b64():
    for name in ["aieds_logo.png", "logo.png", "brain_logo.png"]:
        p = os.path.join(BASE_DIR, name)
        if os.path.exists(p):
            with open(p, "rb") as f:
                return base64.b64encode(f.read()).decode()
    return ""

_logo    = _logo_b64()
_logo_src = f"data:image/png;base64,{_logo}" if _logo else ""

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@400;600;700;900&display=swap');

*,*::before,*::after{{margin:0;padding:0;box-sizing:border-box}}
:root{{--gold:#c9a45c;--goldl:#e8c87a;--border:rgba(201,164,92,0.28)}}

.stApp{{
    background:linear-gradient(rgba(2,8,22,0.68),rgba(2,8,22,0.68)),
               url("{_bg_url}") center/cover no-repeat fixed;
    min-height:100vh;
}}

[data-testid="collapsedControl"],
[data-testid="stSidebarCollapsedControl"] {{
    display:flex !important;
    visibility:visible !important;
    opacity:1 !important;
    position:fixed !important;
    top:50% !important;
    left:0px !important;
    transform:translateY(-50%) !important;
    z-index:99999 !important;
    width:28px !important;
    height:64px !important;
    background:linear-gradient(135deg,rgba(201,164,92,0.25),rgba(201,164,92,0.10)) !important;
    border:1px solid rgba(201,164,92,0.60) !important;
    border-left:none !important;
    border-radius:0 10px 10px 0 !important;
    backdrop-filter:blur(8px) !important;
    align-items:center !important;
    justify-content:center !important;
    cursor:pointer !important;
    box-shadow:3px 0 16px rgba(201,164,92,0.25) !important;
    animation:sidebarPulse 2.5s ease-in-out infinite !important;
}}
[data-testid="collapsedControl"] svg,
[data-testid="stSidebarCollapsedControl"] svg {{
    color:#e8c87a !important;
    fill:#e8c87a !important;
    width:16px !important;
    height:16px !important;
}}
[data-testid="collapsedControl"]:hover,
[data-testid="stSidebarCollapsedControl"]:hover {{
    background:linear-gradient(135deg,rgba(201,164,92,0.45),rgba(201,164,92,0.25)) !important;
    border-color:rgba(201,164,92,0.95) !important;
    box-shadow:4px 0 24px rgba(201,164,92,0.50) !important;
    width:34px !important;
    animation:none !important;
}}
@keyframes sidebarPulse {{
    0%,100% {{ box-shadow:3px 0 16px rgba(201,164,92,0.25); border-color:rgba(201,164,92,0.60); }}
    50%      {{ box-shadow:4px 0 28px rgba(201,164,92,0.55); border-color:rgba(201,164,92,0.95); }}
}}

.stApp::before{{
    content:'';position:fixed;inset:0;z-index:0;pointer-events:none;
    background:
        radial-gradient(ellipse 80% 40% at 20% 80%,rgba(201,164,92,.07) 0%,transparent 60%),
        radial-gradient(ellipse 60% 30% at 80% 20%,rgba(12,40,90,.18) 0%,transparent 55%);
    animation:auroraDrift 20s ease-in-out infinite alternate;
}}
@keyframes auroraDrift{{
    0%  {{transform:scale(1)    translateY(0);  opacity:.7}}
    50% {{transform:scale(1.05) translateY(-10px);opacity:1}}
    100%{{transform:scale(1)    translateY(5px);opacity:.8}}
}}

.stApp::after{{
    content:'';position:fixed;inset:0;z-index:0;pointer-events:none;
    background-image:
        radial-gradient(circle 1.5px at 15% 25%,rgba(201,164,92,.40) 100%,transparent),
        radial-gradient(circle 1px  at 75% 15%,rgba(201,164,92,.28) 100%,transparent),
        radial-gradient(circle 2px  at 55% 70%,rgba(201,164,92,.22) 100%,transparent),
        radial-gradient(circle 1px  at 35% 55%,rgba(201,164,92,.32) 100%,transparent),
        radial-gradient(circle 1.5px at 90% 60%,rgba(201,164,92,.22) 100%,transparent),
        radial-gradient(circle 1px  at 10% 80%,rgba(201,164,92,.28) 100%,transparent);
    animation:particleDrift 28s linear infinite;
}}
@keyframes particleDrift{{
    0%  {{transform:translateY(0)    translateX(0)}}
    33% {{transform:translateY(-14px) translateX(7px)}}
    66% {{transform:translateY(7px)  translateX(-9px)}}
    100%{{transform:translateY(0)    translateX(0)}}
}}

@keyframes thinkPulse {{
    0%,100% {{ opacity:0.4; transform:scale(1); }}
    50%      {{ opacity:1.0; transform:scale(1.15); }}
}}
@keyframes thinkSlide {{
    0%   {{ opacity:0; transform:translateX(-8px); }}
    100% {{ opacity:1; transform:translateX(0); }}
}}
@keyframes dotBounce {{
    0%,80%,100% {{ transform:translateY(0); }}
    40%         {{ transform:translateY(-6px); }}
}}
.thinking-box {{
    display:flex; align-items:flex-start; gap:12px;
    background:rgba(3,13,28,0.60);
    border:1px solid rgba(201,164,92,0.22);
    border-radius:12px; padding:14px 18px;
    margin:4px 0 8px 0;
    animation:thinkSlide 0.3s ease forwards;
}}
.thinking-icon {{
    font-size:22px; line-height:1;
    animation:thinkPulse 1.8s ease-in-out infinite;
    flex-shrink:0; margin-top:2px;
}}
.thinking-text {{
    display:flex; flex-direction:column; gap:5px;
}}
.thinking-label {{
    font-family:'Cinzel',serif; font-size:11px;
    letter-spacing:0.18em; color:#e8c87a;
    text-transform:uppercase;
}}
.thinking-sub {{
    font-family:'Cormorant Garamond',serif; font-style:italic;
    font-size:13px; color:rgba(245,233,200,0.60); line-height:1.4;
}}
.thinking-dots {{ display:inline-flex; gap:4px; margin-left:4px; }}
.thinking-dots span {{
    width:5px; height:5px; border-radius:50%;
    background:#c9a45c; display:inline-block;
    animation:dotBounce 1.2s ease-in-out infinite;
}}
.thinking-dots span:nth-child(2) {{ animation-delay:0.2s; }}
.thinking-dots span:nth-child(3) {{ animation-delay:0.4s; }}

/* ── Quiz CTA banner ── */
.quiz-cta {{
    background:linear-gradient(135deg,rgba(20,50,100,0.85),rgba(10,30,60,0.90));
    border:1px solid rgba(201,164,92,0.45);
    border-radius:14px;
    padding:16px 22px;
    margin:12px 0 4px 0;
    display:flex;
    align-items:center;
    gap:14px;
    animation:thinkSlide 0.4s ease forwards;
}}
.quiz-cta-icon {{ font-size:28px; flex-shrink:0; }}
.quiz-cta-text {{ flex:1; }}
.quiz-cta-text .quiz-cta-title {{
    font-family:'Cinzel',serif;
    font-size:13px; letter-spacing:0.12em;
    color:#e8c87a; font-weight:700;
    margin-bottom:3px;
}}
.quiz-cta-text .quiz-cta-sub {{
    font-size:12px; color:rgba(240,228,200,0.65);
    font-family:Arial,sans-serif; line-height:1.4;
}}

[data-testid="stSidebar"] [data-testid="stSidebarNav"],
#MainMenu,footer,header,[data-testid="stToolbar"],
[data-testid="stStatusWidget"],div[class*="StatusWidget"],
.stSpinner,div:has(>.stSpinner){{display:none!important}}

.block-container{{
    padding:12px 28px 20px 28px!important;
    max-width:100%!important;position:relative;z-index:1;
}}

[data-testid="stSidebar"]{{
    background:linear-gradient(180deg,rgba(3,10,24,.97) 0%,rgba(5,16,38,.95) 100%)!important;
    border-right:1px solid var(--border)!important;
    backdrop-filter:blur(18px)!important;
}}
[data-testid="stSidebar"] *{{color:rgba(240,228,200,.88)!important}}
[data-testid="stSidebar"] .stButton>button{{
    background:rgba(201,164,92,.10)!important;
    border:1px solid var(--border)!important;
    border-radius:10px!important;color:var(--goldl)!important;
    font-family:'Cinzel',serif!important;font-size:10px!important;
    letter-spacing:.12em!important;width:100%!important;
    height:auto!important;min-height:36px!important;
    padding:8px 10px!important;line-height:1.35!important;
    white-space:normal!important;transition:all .2s!important;
}}
[data-testid="stSidebar"] .stButton>button:hover{{
    background:rgba(201,164,92,.22)!important;
    border-color:rgba(201,164,92,.65)!important;
}}

.stApp h1{{
    font-family:'Cinzel',serif!important;
    font-size:clamp(18px,2.2vw,26px)!important;font-weight:700!important;
    background:linear-gradient(180deg,#ffffff 0%,#f5d98a 40%,#c9a45c 100%);
    -webkit-background-clip:text;-webkit-text-fill-color:transparent;
    background-clip:text;letter-spacing:.08em!important;
    filter:drop-shadow(0 0 14px rgba(201,164,92,.3));
    margin-bottom:10px!important;
}}

[data-testid="stChatMessage"]{{
    background:rgba(3,13,28,.72)!important;
    border:1px solid var(--border)!important;
    border-radius:16px!important;backdrop-filter:blur(12px)!important;
    margin-bottom:18px!important;padding:22px 26px!important;
    animation:msgFadeIn .3s ease-out;
}}
@keyframes msgFadeIn{{
    from{{opacity:0;transform:translateY(6px)}}
    to{{opacity:1;transform:translateY(0)}}
}}
[data-testid="stChatMessage"] p{{
    color:rgba(240,228,200,.95)!important;
    font-family:Arial,Helvetica,sans-serif!important;
    font-size:16px!important;line-height:1.85!important;
    margin-bottom:10px!important;
}}
[data-testid="stChatMessage"] li{{
    color:rgba(240,228,200,.95)!important;
    font-family:Arial,Helvetica,sans-serif!important;
    font-size:16px!important;line-height:1.85!important;
    margin-bottom:6px!important;
}}
[data-testid="stChatMessage"] h1,
[data-testid="stChatMessage"] h2,
[data-testid="stChatMessage"] h3,
[data-testid="stChatMessage"] h4{{
    color:#e8c87a!important;
    -webkit-text-fill-color:#e8c87a!important;
    font-family:'Cinzel',serif!important;
    font-weight:700!important;
    letter-spacing:0.06em!important;
    margin:18px 0 10px 0!important;
    padding-bottom:6px!important;
    border-bottom:1px solid rgba(201,164,92,0.25)!important;
}}
[data-testid="stChatMessage"] h1{{font-size:1.3em!important;}}
[data-testid="stChatMessage"] h2{{font-size:1.15em!important;}}
[data-testid="stChatMessage"] h3{{font-size:1.05em!important;}}
[data-testid="stChatMessage"] strong{{
    color:#f5d98a!important;
    -webkit-text-fill-color:#f5d98a!important;
}}
[data-testid="stChatMessage"] code{{
    background:rgba(201,164,92,0.12)!important;
    color:#f5d98a!important;
    border-radius:4px!important;
    padding:2px 6px!important;
    font-size:0.92em!important;
}}
[data-testid="stChatMessage"] pre{{
    background:rgba(3,13,28,0.85)!important;
    border:1px solid rgba(201,164,92,0.22)!important;
    border-radius:10px!important;
    padding:16px!important;
    overflow-x:auto!important;
    margin:12px 0!important;
}}
[data-testid="stChatMessage"] pre code{{
    background:transparent!important;
    padding:0!important;
    color:rgba(240,228,200,0.92)!important;
}}
[data-testid="stChatMessage"] .katex{{
    color:#f5d98a!important;font-size:1.15em!important;
}}
[data-testid="stChatMessage"] .katex-display{{
    display:block!important;text-align:left!important;
    overflow-x:auto!important;padding:12px 0!important;
    margin:14px 0!important;color:#f5d98a!important;
}}

[data-testid="stChatInput"]{{
    background:#ffffff!important;
    border:1.5px solid rgba(201,164,92,.50)!important;
    border-radius:14px!important;
}}
[data-testid="stChatInput"] textarea,
[data-testid="stChatInput"] div,
[data-testid="stChatInput"] p{{
    color:#0d0d0d!important;
    -webkit-text-fill-color:#0d0d0d!important;
    caret-color:#c9a45c!important;
    font-family:Arial,Helvetica,sans-serif!important;
    font-size:15px!important;background:#ffffff!important;
    opacity:1!important;
}}
[data-testid="stChatInput"] textarea::placeholder{{
    color:rgba(0,0,0,.38)!important;
    -webkit-text-fill-color:rgba(0,0,0,.38)!important;
}}
[data-testid="stChatInput"]:focus-within{{
    border-color:rgba(201,164,92,.80)!important;
    box-shadow:0 0 0 3px rgba(201,164,92,.18)!important;
}}

[data-testid="stCaptionContainer"] p{{
    color:rgba(201,164,92,.65)!important;font-size:11px!important;
    font-family:'Cinzel',serif!important;letter-spacing:.08em!important;
}}

div[data-testid="column"] .stButton>button{{
    background:rgba(201,164,92,.14)!important;
    border:1.5px solid rgba(201,164,92,.65)!important;
    border-radius:10px!important;
    font-size:15px!important;
    font-weight:600!important;
    color:#f0d898!important;transition:all .2s!important;
    padding:6px 12px!important;
}}
div[data-testid="column"] .stButton>button:hover{{
    background:rgba(201,164,92,.35)!important;
    border-color:var(--gold)!important;
    box-shadow:0 0 14px rgba(201,164,92,.5)!important;
    color:#ffffff!important;
}}

.welcome-overlay{{
    position:fixed;
    top:0;left:0;right:0;bottom:0;
    display:flex;
    flex-direction:column;
    align-items:center;
    justify-content:center;
    z-index:999;
    pointer-events:none;
}}
.welcome-box{{
    pointer-events:all;
    width:min(680px,88vw);
    text-align:center;
}}
.welcome-title{{
    font-family:'Cinzel',serif;
    font-size:clamp(20px,2.8vw,32px);
    font-weight:700;
    background:linear-gradient(180deg,#ffffff 0%,#f5d98a 40%,#c9a45c 100%);
    -webkit-background-clip:text;-webkit-text-fill-color:transparent;
    background-clip:text;
    letter-spacing:0.08em;
    filter:drop-shadow(0 0 18px rgba(201,164,92,0.45));
    margin-bottom:18px;
    line-height:1.35;
}}
.welcome-sub{{ display:none; }}
hr{{border-color:var(--border)!important}}
</style>
""", unsafe_allow_html=True)

inject_theme_polish()

# ── SIDEBAR ───────────────────────────────────────────────────────────────────
with st.sidebar:
    display_name = st.session_state.get(
        'full_name', st.session_state.get('username', 'Cadet')).upper()
    st.markdown(f"""
    <div style='padding:16px 4px 14px 4px; text-align:center;'>
        {("<img src='" + _logo_src + "' style='width:72px;height:72px;object-fit:contain;" +
         "margin-bottom:10px;filter:drop-shadow(0 0 12px rgba(201,164,92,0.55));' />") if _logo_src else ""}
        <p style='font-family:Cinzel,serif;font-size:24px;font-weight:900;
           background:linear-gradient(180deg,#fff 0%,#f5d98a 35%,#c9a45c 100%);
           -webkit-background-clip:text;-webkit-text-fill-color:transparent;
           background-clip:text;letter-spacing:0.14em;margin-bottom:12px;
           white-space:nowrap;'>AIEdS CHATBOT</p>
        <p style='font-size:13px;color:rgba(201,164,92,0.85);font-family:Cinzel,serif;
           letter-spacing:0.12em;margin-bottom:6px;font-weight:700;text-align:left;'>
           CADET: <span style='color:#f0d898;font-weight:900;'>{display_name}</span></p>
        <p style='font-size:12px;color:rgba(201,164,92,0.60);font-family:Cinzel,serif;
           letter-spacing:0.11em;font-weight:600;text-align:left;'>
           ID: {st.session_state.get('username','N/A')}</p>
    </div>
    """, unsafe_allow_html=True)
    st.divider()

    selected_term    = st.session_state.get("selected_term", "Term_1")
    selected_subject = st.session_state.get("selected_subject", "—")
    folder           = os.path.join(USER_PROFILES_DIR, selected_term)

    st.markdown(f"""
    <div style='margin:4px 0 14px 0;'>
        <p style='font-family:Cinzel,serif;font-size:9px;letter-spacing:0.18em;
                  color:rgba(201,164,92,0.55);text-transform:uppercase;margin-bottom:4px;'>
                  Academic Term</p>
        <div style='background:rgba(2,8,20,0.55);border:1px solid rgba(201,164,92,0.22);
                    border-radius:8px;padding:8px 12px;'>
            <p style='font-family:Cinzel,serif;font-size:12px;color:#e8c87a;
                      letter-spacing:0.06em;margin:0;'>{selected_term}</p>
        </div>
    </div>
    <div style='margin:0 0 14px 0;'>
        <p style='font-family:Cinzel,serif;font-size:9px;letter-spacing:0.18em;
                  color:rgba(201,164,92,0.55);text-transform:uppercase;margin-bottom:4px;'>
                  Subject Manual</p>
        <div style='background:rgba(2,8,20,0.55);border:1px solid rgba(201,164,92,0.22);
                    border-radius:8px;padding:8px 12px;'>
            <p style='font-family:Cinzel,serif;font-size:11px;color:#e8c87a;
                      letter-spacing:0.04em;margin:0;word-break:break-word;'>
               {selected_subject if selected_subject else "—"}</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.divider()
    if st.button("Home Dashboard", use_container_width=True):
        st.switch_page("pages/student.py")

    st.divider()
    # ── Mode selector ──────────────────────────────────────────────────────────
    st.markdown(
        "<p style='font-family:Cinzel,serif;font-size:9px;letter-spacing:0.18em;"
        "color:rgba(201,164,92,0.55);text-transform:uppercase;margin-bottom:8px;'>"
        "Special Modes</p>",
        unsafe_allow_html=True
    )

    # Oral Board button
    ob_active = st.session_state.chatbot_mode == "oral"
    if st.button(
        "🎖️  Oral Board / Viva" + ("  ✓" if ob_active else ""),
        use_container_width=True,
        key="oral_board_btn"
    ):
        if ob_active:
            st.session_state.chatbot_mode = "standard"
            st.session_state.messages = []
        else:
            st.session_state.chatbot_mode = "oral"
            st.session_state.messages = []
        st.rerun()

    # Nautical Board button
    nb_active = st.session_state.chatbot_mode == "nautical"
    if st.button(
        "⚓  Nautical Board / PPT / PDF" + ("  ✓" if nb_active else ""),
        use_container_width=True,
        key="nautical_board_btn"
    ):
        if nb_active:
            st.session_state.chatbot_mode = "standard"
            st.session_state.messages = []
        else:
            st.session_state.chatbot_mode = "nautical"
            st.session_state.messages = []
        st.rerun()

    # Mode description hints + Return button
    if ob_active:
        st.markdown(
            "<p style='font-family:Cinzel,serif;font-size:9px;letter-spacing:0.10em;"
            "color:rgba(201,164,92,0.50);margin-top:6px;line-height:1.5;'>"
            "⚡ Short answers from your<br>selected subject manual</p>",
            unsafe_allow_html=True
        )
        if st.button("↩  Return to Chatbot", use_container_width=True, key="return_standard_ob"):
            st.session_state.chatbot_mode = "standard"
            st.session_state.messages = []
            st.rerun()
    elif nb_active:
        st.markdown(
            "<p style='font-family:Cinzel,serif;font-size:9px;letter-spacing:0.10em;"
            "color:rgba(201,164,92,0.50);margin-top:6px;line-height:1.5;'>"
            "📎 Summarise docs · Answer question papers<br>· Analyse images with qwen3-vl</p>",
            unsafe_allow_html=True
        )
        if st.button("↩  Return to Chatbot", use_container_width=True, key="return_standard_nb"):
            st.session_state.chatbot_mode = "standard"
            st.session_state.messages = []
            st.rerun()

    st.divider()
    # ── Clear Cache ────────────────────────────────────────────────────────────
    st.markdown(
        "<p style='font-family:Cinzel,serif;font-size:9px;letter-spacing:0.18em;"
        "color:rgba(201,164,92,0.55);text-transform:uppercase;margin-bottom:8px;'>"
        "Cache</p>",
        unsafe_allow_html=True
    )
    if st.button("🗑️  Clear Answer Cache", use_container_width=True, key="clear_cache_btn"):
        cleared = 0
        s_name = st.session_state.get("selected_subject", "").replace(" ", "_").lower()
        term   = st.session_state.get("selected_term", "Term_1")
        folder = os.path.join(USER_PROFILES_DIR, term)
        db_p   = os.path.join(folder, f"{s_name}_cache.db")
        idx_p  = os.path.join(folder, f"{s_name}_qcache.index")   # answer cache only
        try:
            if os.path.exists(db_p):
                import sqlite3 as _sq
                with _sq.connect(db_p) as _conn:
                    _conn.execute("DELETE FROM cache")
                    _conn.commit()
                cleared += 1
            if os.path.exists(idx_p):
                os.remove(idx_p)
                cleared += 1
        except Exception as _e:
            st.error(f"Cache clear failed: {_e}")
        if cleared:
            st.session_state.current_cache_id = None
            st.toast("✅ Cache cleared for this subject!", icon="🗑️")
        else:
            st.toast("No cache found for this subject.", icon="ℹ️")

    # ── Handwritten note upload (standard chatbot only) ───────────────────────
    if st.session_state.get("chatbot_mode", "standard") == "standard":
        st.divider()
        st.markdown(
            "<p style='font-family:Cinzel,serif;font-size:9px;letter-spacing:0.18em;"
            "color:rgba(201,164,92,0.55);text-transform:uppercase;margin-bottom:8px;'>"
            "Handwritten Note</p>", unsafe_allow_html=True)
        _note = st.file_uploader("Photo of handwritten note", type=["png", "jpg", "jpeg"],
                                 key="hw_note_upload", label_visibility="collapsed")
        if _note is not None:
            _nid = f"{_note.name}-{_note.size}"
            if st.session_state.get("hw_note_id") != _nid:
                _slot = st.empty()
                _slot.markdown(_reading_box("Converting your note to text…"), unsafe_allow_html=True)
                _txt, _m = transcribe_handwriting(_note.getvalue())
                _slot.empty()
                st.session_state["hw_note_id"]   = _nid
                st.session_state["hw_note_text"] = _txt
                if _txt:
                    # Answer straight away — no need to type anything
                    st.session_state.setdefault("messages", []).append(
                        {"role": "user", "content": HW_AUTO_PROMPT})
            if st.session_state.get("hw_note_text"):
                st.caption("✅ Note read — answer shown in the chat. Ask follow-up questions below.")
                with st.expander("What I read"):
                    st.markdown(st.session_state["hw_note_text"])
                if st.button("🔄  Explain this note again", use_container_width=True, key="hw_reask"):
                    st.session_state.setdefault("messages", []).append(
                        {"role": "user", "content": HW_AUTO_PROMPT})
            else:
                st.caption("⚠️ Couldn't read this photo. Try a clearer, well-lit, straight photo.")
        else:
            st.session_state.pop("hw_note_id", None)
            st.session_state.pop("hw_note_text", None)

    st.divider()
    if st.button("Logout", use_container_width=True):
        st.session_state.clear(); st.switch_page("login.py")

# ── MAIN CHAT ─────────────────────────────────────────────────────────────────
if "messages"              not in st.session_state: st.session_state.messages              = []
if "current_cache_id"      not in st.session_state: st.session_state.current_cache_id      = None
if "trigger_reask"         not in st.session_state: st.session_state.trigger_reask         = False
if "show_quiz_cta"         not in st.session_state: st.session_state.show_quiz_cta         = False
if "chatbot_topics_asked"  not in st.session_state: st.session_state.chatbot_topics_asked  = []  # questions asked this session
if "chatbot_context_store" not in st.session_state: st.session_state.chatbot_context_store = {}  # topic -> context snippets
if "chatbot_mode"          not in st.session_state: st.session_state.chatbot_mode          = "standard"  # standard | oral | nautical

is_empty = len(st.session_state.messages) == 0


# ── Helpers ───────────────────────────────────────────────────────────────────
def _get_faiss_context(prompt):
    """Return (context_text, page, subject, manual, stem) for the currently selected subject."""
    s_name = selected_subject.replace(" ", "_").lower()
    idx_p  = os.path.join(folder, f"{s_name}_faiss.index")
    doc_p  = os.path.join(folder, f"{s_name}_doc.json")
    if not os.path.exists(idx_p):
        return None, None, None, None, s_name
    idx = faiss.read_index(idx_p)
    q_v = emb_model.encode([prompt]).astype('float32')
    faiss.normalize_L2(q_v)
    _, I = idx.search(q_v, 5)
    with open(doc_p) as f:
        doc_map = json.load(f)
    entry = doc_map.get(str(I[0][0]), "")
    # New format: dict with text/page/subject/manual
    # Old format: plain string (backward compat)
    if isinstance(entry, dict):
        context = entry.get("text", "")
        page    = entry.get("page", None)
        subject = entry.get("subject", selected_subject)
        manual  = entry.get("manual", "")
    else:
        context = entry
        page    = None
        subject = selected_subject
        manual  = ""
    return context, page, subject, manual, s_name


def _get_faiss_context_multi(prompt, top_k=3):
    """Return concatenated top-k chunks for oral board (more context = less hallucination)."""
    s_name = selected_subject.replace(" ", "_").lower()
    idx_p  = os.path.join(folder, f"{s_name}_faiss.index")
    doc_p  = os.path.join(folder, f"{s_name}_doc.json")
    if not os.path.exists(idx_p):
        return None, None, None, None, s_name
    idx = faiss.read_index(idx_p)
    q_v = emb_model.encode([prompt]).astype('float32')
    faiss.normalize_L2(q_v)
    _, I = idx.search(q_v, top_k)
    with open(doc_p) as f:
        doc_map = json.load(f)
    chunks, page, subject, manual = [], None, selected_subject, ""
    for idx_id in I[0]:
        if idx_id == -1:
            continue
        entry = doc_map.get(str(idx_id), "")
        if isinstance(entry, dict):
            chunks.append(entry.get("text", ""))
            if page is None:
                page    = entry.get("page", None)
                subject = entry.get("subject", selected_subject)
                manual  = entry.get("manual", "")
        else:
            if entry:
                chunks.append(entry)
    combined = "\n\n---\n\n".join(chunks)
    return combined, page, subject, manual, s_name


def run_query(prompt):

    s_name = selected_subject.replace(" ", "_").lower()
    db_p = os.path.join(folder, f"{s_name}_cache.db")
    idx_p = os.path.join(folder, f"{s_name}_faiss.index")

    note_text = st.session_state.get("hw_note_text", "") or ""
    search_q  = f"{prompt}\n{note_text[:1500]}" if note_text else prompt
    note_part = (f"\n\nCadet's handwritten note (transcribed):\n{note_text}" if note_text else "")

    with st.chat_message("assistant"):
        start_time = time.time()
        # A question about an uploaded note is never answered from cache
        cached_ans, c_id = (None, None) if note_text else get_semantic_cache(prompt)
        if cached_ans:
            full_resp = cached_ans
            render_message(full_resp)
            st.caption("⚡ Instant Cached Response")
            st.session_state.current_cache_id = c_id
            # Store topic even on cache hit
            ctx, page, subject, manual, stem = _get_faiss_context(prompt)
            if ctx:
                st.session_state.chatbot_context_store.setdefault(stem, [])
                if ctx not in st.session_state.chatbot_context_store[stem]:
                    st.session_state.chatbot_context_store[stem].append(ctx)
                st.session_state["chatbot_last_ctx"] = ctx
        else:
            ctx, page, subject, manual, stem = _get_faiss_context(search_q)
            if ctx is not None:
                # Accumulate context for quiz generation
                st.session_state.chatbot_context_store.setdefault(stem, [])
                if ctx not in st.session_state.chatbot_context_store[stem]:
                    st.session_state.chatbot_context_store[stem].append(ctx)
                # Always keep latest context as direct fallback
                st.session_state["chatbot_last_ctx"] = ctx

                # ── Book reference citation ───────────────────────────────────
                if page:
                    ref_parts = [subject]
                    if manual and manual.lower() != subject.lower():
                        ref_parts.append(manual)
                    ref_label = "  ›  ".join(ref_parts)
                    st.markdown(
                        f"<p style='font-family:Cinzel,serif;font-size:10px;"
                        f"letter-spacing:0.16em;color:rgba(201,164,92,0.65);"
                        f"margin:0 0 10px 0;'>📖 {ref_label}  —  Page {page}</p>",
                        unsafe_allow_html=True
                    )

                thinking_steps = [
                    ("🧠", "Analysing your question", "Understanding the context and intent"),
                    ("📖", "Reading your manual",     "Searching relevant sections"),
                    ("⚙️",  "Processing knowledge",   "Connecting concepts from the material"),
                    ("✍️",  "Composing answer",        "Formulating a precise response"),
                ]
                thinking_slot = st.empty()

                def show_thinking(step):
                    icon, label, sub = thinking_steps[step % len(thinking_steps)]
                    thinking_slot.markdown(f"""
                        <div class="thinking-box">
                            <div class="thinking-icon">{icon}</div>
                            <div class="thinking-text">
                                <div class="thinking-label">{label}
                                    <span class="thinking-dots">
                                        <span></span><span></span><span></span>
                                    </span>
                                </div>
                                <div class="thinking-sub">{sub}</div>
                            </div>
                        </div>
                    """, unsafe_allow_html=True)

                show_thinking(0)

                st.session_state["chatbot_last_query"] = prompt
                def stream_gen():
                    first_chunk = True
                    in_think = False
                    stream = _llm_chat(
                        model=CHAT_MODEL,
                        messages=[
                            {"role": "system", "content": get_adaptive_prompt()},
                            {"role": "user",   "content": f"Context: {ctx}{note_part}\n\nQuestion: {prompt}"}
                        ],
                        stream=True, keep_alive=-1,
                        options={"num_gpu": 64, "temperature": 0.0, "num_ctx": 4096}
                    )
                    for chunk in stream:
                        token = chunk['message']['content']
                        if '<think>' in token:
                            in_think = True
                            continue
                        if '</think>' in token:
                            in_think = False
                            continue
                        if in_think:
                            continue
                        if first_chunk:
                            thinking_slot.empty()
                            first_chunk = False
                        yield token

                stream_slot = st.empty()
                try:
                    with stream_slot:
                        full_resp = st.write_stream(stream_gen())
                    stream_slot.empty()
                    render_message(full_resp)
                    st.session_state.current_cache_id = (
                        None if note_text else save_to_cache(prompt, full_resp))
                except Exception:
                    thinking_slot.empty()
                    stream_slot.empty()
                    full_resp = ("The AI assistant is temporarily unavailable — the local model "
                                 "server isn't responding. Please try again in a moment, or let "
                                 "your instructor know if this keeps happening.")
                    st.error(full_resp)
            else:
                _looked = os.path.join(folder, f"{selected_subject.replace(' ', '_').lower()}_faiss.index")
                full_resp = ("The textbook index for this subject is missing on the server. "
                             "Please ask your instructor to re-index it.\n\n"
                             f"`Looked for: {_looked}`  \n"
                             f"`Term = {selected_term!r}   Subject = {selected_subject!r}`")
                st.warning(full_resp)
                st.session_state.messages.append({"role": "assistant", "content": full_resp})
                return
        st.caption(f"⏱️ Response Time: {time.time()-start_time:.2f}s")
        st.session_state.messages.append({"role": "assistant", "content": full_resp})

    # ── Track question asked ──────────────────────────────────────────────────
    if prompt not in st.session_state.chatbot_topics_asked:
        st.session_state.chatbot_topics_asked.append(prompt)

    # ── Show quiz CTA after every answer ─────────────────────────────────────
    st.session_state.show_quiz_cta = True


# ── ORAL BOARD / VIVA: RAG-based but short answers (num_ctx=1024) ─────────────
def run_oral_query(prompt):
    """Oral board mode — short answers pulled from the selected subject manual."""
    with st.chat_message("assistant"):
        start_time = time.time()

        # Check semantic cache first
        cached_ans, c_id = get_semantic_cache(prompt)
        if cached_ans:
            render_message(cached_ans)
            st.caption(f"⚡ Cached  |  🎖️ Oral Board / Viva Mode")
            st.session_state.current_cache_id = c_id
            st.session_state.messages.append({"role": "assistant", "content": cached_ans})
            return

        # Get top-3 chunks from the selected subject FAISS index
        ctx, page, subject, manual, stem = _get_faiss_context_multi(prompt, top_k=3)

        if ctx is None:
            st.warning("Subject manual not found. Please select a subject from the dashboard first.")
            return

        # Accumulate context (for quiz)
        st.session_state.chatbot_context_store.setdefault(stem, [])
        if ctx not in st.session_state.chatbot_context_store[stem]:
            st.session_state.chatbot_context_store[stem].append(ctx)
        st.session_state["chatbot_last_ctx"] = ctx

        # Citation line
        if page:
            ref_parts = [subject]
            if manual and manual.lower() != subject.lower():
                ref_parts.append(manual)
            ref_label = "  ›  ".join(ref_parts)
            st.markdown(
                f"<p style='font-family:Cinzel,serif;font-size:10px;"
                f"letter-spacing:0.16em;color:rgba(201,164,92,0.65);"
                f"margin:0 0 10px 0;'>📖 {ref_label}  —  Page {page}</p>",
                unsafe_allow_html=True
            )

        thinking_slot = st.empty()
        thinking_slot.markdown("""
            <div class="thinking-box">
                <div class="thinking-icon">🎖️</div>
                <div class="thinking-text">
                    <div class="thinking-label">Oral Board / Viva
                        <span class="thinking-dots"><span></span><span></span><span></span></span>
                    </div>
                    <div class="thinking-sub">Reading your manual for a precise answer</div>
                </div>
            </div>
        """, unsafe_allow_html=True)

        # Context embedded directly in system prompt — prevents hallucination
        system_with_ctx = (
            "You are an Oral Board / Viva examiner for Indian Naval Academy cadets.\n\n"
            "=== MANUAL EXTRACT (answer using ONLY this) ===\n"
            f"{ctx}\n"
            "=== END OF MANUAL EXTRACT ===\n\n"
            "RULES:\n"
            "1. Use ONLY the MANUAL EXTRACT above. No outside knowledge whatsoever.\n"
            "2. If the topic is not in the extract, respond: "
            "'This topic is not found in the retrieved section. Try rephrasing or check full manual.'\n"
            "3. Answer in 100-120 words. Simple, clear, naval tone.\n"
            "4. No filler words. Go straight to the answer.\n"
            "5. Include formula if present in extract. Max 4 bullet points if steps exist.\n"
        )

        def oral_stream():
            first = True
            in_think = False
            stream = _llm_chat(
                model=CHAT_MODEL,
                messages=[
                    {"role": "system", "content": system_with_ctx},
                    {"role": "user",   "content": prompt}
                ],
                stream=True, keep_alive=-1,
                options={"num_gpu": 64, "temperature": 0.0, "num_ctx": 4096}
            )
            for chunk in stream:
                token = chunk['message']['content']
                if '<think>' in token:
                    in_think = True
                    continue
                if '</think>' in token:
                    in_think = False
                    continue
                if in_think:
                    continue
                if first:
                    thinking_slot.empty()
                    first = False
                yield token

        stream_slot = st.empty()
        try:
            with stream_slot:
                full_resp = st.write_stream(oral_stream())
            stream_slot.empty()
            render_message(full_resp)
            st.caption(f"⏱️ {time.time()-start_time:.2f}s  |  🎖️ Oral Board / Viva Mode")
            st.session_state.current_cache_id = save_to_cache(prompt, full_resp)
            st.session_state.messages.append({"role": "assistant", "content": full_resp})
        except Exception:
            thinking_slot.empty()
            stream_slot.empty()
            full_resp = ("The AI assistant is temporarily unavailable — the local model "
                         "server isn't responding. Please try again in a moment.")
            st.error(full_resp)

    if prompt not in st.session_state.chatbot_topics_asked:
        st.session_state.chatbot_topics_asked.append(prompt)


# ── NAUTICAL BOARD: PPT/PDF summary ───────────────────────────────────────────
def _extract_pptx_text(file_bytes):
    """Extract slide text from an uploaded PPTX file."""
    try:
        from pptx import Presentation
        prs = Presentation(io.BytesIO(file_bytes))
        slides_text = []
        for i, slide in enumerate(prs.slides, 1):
            texts = []
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text.strip():
                    texts.append(shape.text.strip())
            if texts:
                slides_text.append(f"Slide {i}: " + " | ".join(texts))
        return "\n".join(slides_text)
    except Exception as e:
        return f"[Error reading PPTX: {e}]"


def _extract_pdf_text(file_bytes):
    """Extract text from an uploaded PDF file."""
    try:
        import fitz
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        pages = []
        for i, page in enumerate(doc, 1):
            t = page.get_text().strip()
            if t:
                pages.append(f"Page {i}: {t[:800]}")
        doc.close()
        return "\n".join(pages)
    except Exception as e:
        return f"[Error reading PDF: {e}]"


def run_nautical_summary(raw_text, filename, instruction="Provide a brief structured summary."):
    """Send extracted doc text to LLM following the cadet's instruction."""
    # Lock show_quiz_cta off — nautical is summary-only, never quiz
    st.session_state.show_quiz_cta = False

    truncated = raw_text[:4500] if len(raw_text) > 4500 else raw_text

    system_prompt = (
        "You are the AIEdS Nautical Board Assistant for Indian Naval Academy.\n"
        "You receive text extracted from a document uploaded by a cadet.\n\n"
        "Follow the cadet's instruction EXACTLY:\n"
        "- 'Summarise briefly' → brief structured summary\n"
        "- 'Answer all questions' → treat as question paper, answer each question\n"
        "- 'Key points' → bullet-point the most important facts\n"
        "- 'Simple explanation' → plain easy language\n\n"
        "Naval-professional tone. Do NOT add content not in the document.\n"
    )
    user_msg = f"Instruction: {instruction}\n\n=== DOCUMENT ===\n{truncated}\n=== END ==="

    with st.chat_message("assistant"):
        st.markdown(
            f"<p style='font-family:Cinzel,serif;font-size:10px;letter-spacing:0.16em;"
            f"color:rgba(201,164,92,0.70);margin:0 0 8px 0;'>⚓ Processing: {filename}</p>",
            unsafe_allow_html=True
        )
        slot = st.empty()
        slot.markdown("""
            <div class="thinking-box">
                <div class="thinking-icon">⚓</div>
                <div class="thinking-text">
                    <div class="thinking-label">Nautical Board
                        <span class="thinking-dots"><span></span><span></span><span></span></span>
                    </div>
                    <div class="thinking-sub">Reading document and following your instruction…</div>
                </div>
            </div>
        """, unsafe_allow_html=True)

        def naut_stream():
            first = True
            in_think = False
            stream = _llm_chat(
                model=CHAT_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_msg}
                ],
                stream=True, keep_alive=-1,
                options={"num_gpu": 64, "temperature": 0.0, "num_ctx": 4096}
            )
            for chunk in stream:
                token = chunk['message']['content']
                if '<think>' in token:
                    in_think = True
                    continue
                if '</think>' in token:
                    in_think = False
                    continue
                if in_think:
                    continue
                if first:
                    slot.empty()
                    first = False
                yield token

        sslot = st.empty()
        try:
            with sslot:
                result = st.write_stream(naut_stream())
            sslot.empty()
            st.markdown(result)
            st.caption(f"⚓ Nautical Board — {filename}")
        except Exception:
            slot.empty()
            sslot.empty()
            st.error("The AI assistant is temporarily unavailable — the local model "
                     "server isn't responding. Please try again in a moment.")
        # Ensure quiz CTA stays off after stream finishes
        st.session_state.show_quiz_cta = False


def run_nautical_image(img_bytes, filename, instruction="Describe this image in detail."):
    """Analyse an uploaded image using qwen3-vl via Ollama."""
    import base64 as _b64
    st.session_state.show_quiz_cta = False
    img_b64 = _b64.b64encode(img_bytes).decode()

    slot = st.empty()
    slot.markdown("""
        <div class="thinking-box">
            <div class="thinking-icon">🖼️</div>
            <div class="thinking-text">
                <div class="thinking-label">Image Analysis
                    <span class="thinking-dots"><span></span><span></span><span></span></span>
                </div>
                <div class="thinking-sub">Reading image with qwen3-vl vision model…</div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    try:
        response = _llm_chat(
            model=VISION_MODEL,
            messages=[{"role": "user", "content": instruction, "images": [img_b64]}],
            keep_alive=-1,
            options={"num_gpu": 64, "temperature": 0.0}
        )
        slot.empty()
        result = response['message']['content']
        # Store result in session state so it survives rerun
        st.session_state["naut_img_result"] = result
        st.session_state["naut_img_filename"] = filename
    except Exception as e:
        slot.empty()
        st.session_state["naut_img_result"] = None
        st.error(f"Image analysis failed: {e}\n\nPull the model first: `ollama pull qwen3-vl:8b`")

    st.session_state.show_quiz_cta = False


def run_nautical_qp_answers(qp_text, manual_context, subject_stem, filename):
    """Generate detailed answers for a question paper using the selected subject manual."""
    st.session_state.show_quiz_cta = False

    subject_display = subject_stem.replace("_", " ").title()
    truncated_qp  = qp_text[:3000]       if len(qp_text)       > 3000 else qp_text
    truncated_ctx = manual_context[:2000] if len(manual_context) > 2000 else manual_context

    system_prompt = (
        f"You are the AIEdS Question Paper Answer Generator for Indian Naval Academy.\n"
        f"Subject: {subject_display}\n\n"
        f"You will receive QUESTIONS from a question paper and MANUAL CONTEXT from the textbook.\n\n"
        f"YOUR TASK:\n"
        f"- Answer EVERY question found in the QUESTIONS section\n"
        f"- Use the MANUAL CONTEXT as your primary source\n"
        f"- If a question is not in the context, use your knowledge of {subject_display}\n"
        f"- Format each answer as: **Q<n>.** <question text>\n**Ans:** <answer>\n"
        f"- Each answer: 3-6 sentences. Clear, accurate, naval tone.\n"
        f"- Include formulas where relevant. Number all answers.\n"
    )
    user_msg = (
        f"=== QUESTIONS ===\n{truncated_qp}\n=== END QUESTIONS ===\n\n"
        f"=== MANUAL CONTEXT ({subject_display}) ===\n{truncated_ctx}\n=== END CONTEXT ===\n\n"
        f"Now answer all the questions above."
    )

    with st.chat_message("assistant"):
        st.markdown(
            f"<p style='font-family:Cinzel,serif;font-size:10px;letter-spacing:0.16em;"
            f"color:rgba(201,164,92,0.70);margin:0 0 8px 0;'>"
            f"📝 Answers for: {filename}  |  Subject: {subject_display}</p>",
            unsafe_allow_html=True
        )
        slot = st.empty()
        slot.markdown("""
            <div class="thinking-box">
                <div class="thinking-icon">📝</div>
                <div class="thinking-text">
                    <div class="thinking-label">Question Paper Answers
                        <span class="thinking-dots"><span></span><span></span><span></span></span>
                    </div>
                    <div class="thinking-sub">Reading questions and generating answers from manual…</div>
                </div>
            </div>
        """, unsafe_allow_html=True)

        def qp_stream():
            first = True
            in_think = False
            stream = _llm_chat(
                model=CHAT_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_msg}
                ],
                stream=True, keep_alive=-1,
                options={"num_gpu": 64, "temperature": 0.0, "num_ctx": 4096}
            )
            for chunk in stream:
                token = chunk['message']['content']
                if '<think>' in token:
                    in_think = True
                    continue
                if '</think>' in token:
                    in_think = False
                    continue
                if in_think:
                    continue
                if first:
                    slot.empty()
                    first = False
                yield token

        sslot = st.empty()
        try:
            with sslot:
                answers = st.write_stream(qp_stream())
            sslot.empty()
            st.markdown(answers)
            st.caption(f"📚 Answers from: {subject_display} manual")
            st.session_state["naut_qp_result"]   = answers
            st.session_state["naut_qp_filename"] = filename
        except Exception:
            slot.empty()
            sslot.empty()
            st.error("The AI assistant is temporarily unavailable — the local model "
                     "server isn't responding. Please try again in a moment.")
        st.session_state.show_quiz_cta = False


def _launch_chatbot_quiz():
    """Launch chatbot quiz.

    Selling-point behaviour: every question served is semantically relevant
    to what the cadet actually studied in this chat session.

    Algorithm (no keyword hacks — pure embedding cosine similarity):
    ─────────────────────────────────────────────────────────────────
    1. Load quiz_bank.json and hard-filter by subject name match.
    2. Build a single MEAN session embedding from all FAISS context
       chunks retrieved during the conversation (chatbot_context_store).
       This represents "what the cadet has been learning about".
    3. Encode every quiz bank question with the same SentenceTransformer
       model (all-MiniLM-L6-v2) that is already loaded in memory.
    4. Compute cosine similarity between each question vector and the
       mean session embedding.  Sort descending.
    5. Apply a hard relevance cutoff (SIM_THRESHOLD = 0.25).
       Questions below the threshold are dropped unless we have fewer
       than CB_TOTAL matched questions, in which case we fill with the
       next-closest ones to always give a full quiz.
    6. Pick the top CB_TOTAL, assign ascending difficulty, hand off to
       _quiz.py via session state.
    """
    import json    as _json
    import random  as _random
    import numpy   as _np

    QUIZ_BANK_PATH = os.path.join(BASE_DIR, "quiz_bank.json")
    CB_TOTAL       = 5
    SIM_THRESHOLD  = 0.25          # minimum cosine similarity to be considered relevant

    topics = st.session_state.get("chatbot_topics_asked", [])

    # ── Step 1: Load bank and hard-filter by subject ──────────────────────────
    all_subject_qs = []
    if os.path.exists(QUIZ_BANK_PATH):
        try:
            with open(QUIZ_BANK_PATH, "r", encoding="utf-8") as f:
                bank = _json.load(f)
            subj_lower = selected_subject.strip().lower().replace("_", " ")
            for q in bank:
                q_subj = q.get("subject", "").strip().lower().replace("_", " ")
                if subj_lower in q_subj or q_subj in subj_lower:
                    all_subject_qs.append(q)
        except Exception:
            all_subject_qs = []

    if not all_subject_qs:
        # Nothing in the bank for this subject — abort gracefully
        st.warning("No questions found in the question bank for this subject. "
                   "Ask your instructor to upload a question bank first.")
        return

    # ── Step 2: Build mean session embedding from retrieved FAISS contexts ────
    #
    # chatbot_context_store = { subject_slug: [chunk1, chunk2, ...] }
    # These chunks are the actual manual text the model used to answer
    # the cadet's questions — the ground truth of what was studied.
    #
    context_chunks = []
    for chunks in st.session_state.get("chatbot_context_store", {}).values():
        context_chunks.extend(chunks)

    # Fallback: if context store empty, use raw question strings
    if not context_chunks:
        context_chunks = topics if topics else ["general subject revision"]

    # Encode all context chunks, then mean-pool → single session vector
    # emb_model is already loaded as a @st.cache_resource — no reload cost
    ctx_vecs = emb_model.encode(context_chunks, convert_to_numpy=True, show_progress_bar=False)
    session_vec = ctx_vecs.mean(axis=0)                        # shape (384,)
    session_vec = session_vec / (_np.linalg.norm(session_vec) + 1e-9)   # L2 normalise

    # ── Step 3: Encode every subject-filtered quiz question ───────────────────
    q_texts = [q.get("question", q.get("text", "")) for q in all_subject_qs]
    q_vecs  = emb_model.encode(q_texts, convert_to_numpy=True, show_progress_bar=False)
    # L2 normalise each row so dot-product == cosine similarity
    norms   = _np.linalg.norm(q_vecs, axis=1, keepdims=True) + 1e-9
    q_vecs  = q_vecs / norms

    # ── Step 4: Cosine similarity of each question vs session embedding ───────
    sims = q_vecs @ session_vec                                # shape (N,)

    # Attach similarity score to each question dict (temporary field)
    for i, q in enumerate(all_subject_qs):
        q["_sim"] = float(sims[i])

    # ── Step 5: Sort by similarity descending, apply threshold ───────────────
    all_subject_qs.sort(key=lambda q: q["_sim"], reverse=True)

    above_threshold = [q for q in all_subject_qs if q["_sim"] >= SIM_THRESHOLD]
    below_threshold = [q for q in all_subject_qs if q["_sim"] <  SIM_THRESHOLD]

    # Prefer above-threshold; fill with below only if needed to reach CB_TOTAL
    ordered_qs = above_threshold + below_threshold

    # ── Step 6: Deduplicate by text and take top CB_TOTAL ────────────────────
    difficulties     = [0.2, 0.4, 0.5, 0.7, 0.9]
    selected_bank_qs = []
    seen_texts       = set()
    for bq in ordered_qs:
        if len(selected_bank_qs) >= CB_TOTAL:
            break
        q_text = bq.get("question", bq.get("text", "")).strip().lower()
        if q_text in seen_texts:
            continue
        seen_texts.add(q_text)
        i = len(selected_bank_qs)
        selected_bank_qs.append({
            "id":          f"bq_{i+1}",
            "text":        bq.get("question", bq.get("text", "")),
            "options":     bq.get("options", []),
            "answer":      bq.get("answer", ""),
            "explanation": bq.get("explanation", ""),
            "di":          difficulties[i % len(difficulties)],
            "source":      "bank",
        })

    # ── Step 7: Reset quiz state cleanly ─────────────────────────────────────
    for k in ["quiz_step", "current_di", "score", "history", "quiz_log",
              "show_explanation", "current_question", "user_ans", "is_correct",
              "quiz_chapter", "cb_generated_qs", "cb_q_index", "chatbot_quiz_mode",
              "cb_wait_count"]:
        st.session_state.pop(k, None)

    # ── Step 8: Hand off to _quiz.py ─────────────────────────────────────────
    st.session_state["selected_subject"]      = selected_subject
    st.session_state["chatbot_quiz_mode"]     = True
    st.session_state["chatbot_quiz_subject"]  = selected_subject
    st.session_state["chatbot_quiz_topics"]   = topics
    st.session_state["chatbot_quiz_bank_qs"]  = selected_bank_qs
    st.session_state["chatbot_quiz_need_ai"]  = 0
    st.session_state["cb_generated_qs"]       = selected_bank_qs
    st.session_state["quiz_step"]             = 1
    st.session_state["current_di"]            = 0.1
    st.session_state["score"]                 = 0
    st.session_state["history"]               = []
    st.session_state["quiz_log"]              = []
    st.session_state["show_explanation"]      = False
    st.session_state["current_question"]      = None

    st.switch_page("pages/_quiz.py")


# ──────────────────────────────────────────────────────────────────────────────
# ── NAUTICAL BOARD MODE ───────────────────────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────────────
if st.session_state.chatbot_mode == "nautical":
    # Lock quiz CTA off immediately — nautical is summary-only
    st.session_state.show_quiz_cta = False

    st.markdown(
        "<h1 style='font-family:Cinzel,serif;font-size:clamp(18px,2.2vw,26px);"
        "font-weight:700;background:linear-gradient(180deg,#ffffff 0%,#f5d98a 40%,#c9a45c 100%);"
        "-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;"
        "letter-spacing:0.08em;filter:drop-shadow(0 0 14px rgba(201,164,92,0.3));"
        "margin-bottom:4px;'>⚓ Nautical Board / PPT / PDF / Image</h1>",
        unsafe_allow_html=True
    )
    st.markdown(
        "<p style='font-family:Cinzel,serif;font-size:11px;letter-spacing:0.14em;"
        "color:rgba(201,164,92,0.60);margin-bottom:16px;'>"
        "Summarise slides · Answer question papers · Analyse images with qwen3-vl vision.</p>",
        unsafe_allow_html=True
    )

    uploaded_doc = st.file_uploader(
        "Upload PPT, PDF or a photo of handwritten pages",
        type=["pptx", "pdf", "png", "jpg", "jpeg"],
        key="nautical_upload_doc",
        label_visibility="collapsed"
    )
    if uploaded_doc is not None:
        doc_bytes = uploaded_doc.read()
        doc_fname = uploaded_doc.name
        st.markdown(
            "<p style='font-family:Cinzel,serif;font-size:10px;letter-spacing:0.14em;"
            "color:rgba(201,164,92,0.70);margin:12px 0 4px 0;'>📝 WHAT DO YOU NEED FROM THIS DOCUMENT?</p>",
            unsafe_allow_html=True
        )
        naut_instruction = st.text_area(
            "Instruction",
            placeholder=(
                "Examples:\n"
                "• Summarise this PPT briefly\n"
                "• This is a question paper — answer all questions\n"
                "• List the key points from each slide\n"
                "• Explain the topic in simple language"
            ),
            height=110,
            key="naut_instruction_doc",
            label_visibility="collapsed"
        )
        if st.button("📋  Process Document", use_container_width=False, key="naut_process_doc"):
            st.session_state.show_quiz_cta = False
            _ext = doc_fname.lower().rsplit(".", 1)[-1]
            _slot = st.empty()
            if _ext == "pptx":
                raw_text = _extract_pptx_text(doc_bytes)
            elif _ext in ("png", "jpg", "jpeg"):
                _slot.markdown(_reading_box("Reading your handwritten page…"), unsafe_allow_html=True)
                raw_text, _ = transcribe_handwriting(doc_bytes)
            else:
                raw_text = _extract_pdf_text(doc_bytes)
                # Scanned or handwritten PDF has (almost) no text layer -> read pages as images
                if not raw_text.startswith("[Error") and len(raw_text.strip()) < 100:
                    _slot.markdown(_reading_box("Scanned/handwritten PDF — reading each page…"),
                                   unsafe_allow_html=True)
                    raw_text = transcribe_pdf_pages(doc_bytes)
            _slot.empty()
            if not raw_text.strip():
                raw_text = "[Error: no readable text found — try a clearer photo or scan]"
            elif _ext in ("png", "jpg", "jpeg", "pdf"):
                with st.expander("📝 Text read from your file"):
                    st.markdown(raw_text)
            if raw_text.startswith("[Error"):
                st.error(raw_text)
            else:
                instr = naut_instruction.strip() if naut_instruction.strip() else "Provide a brief structured summary."
                run_nautical_summary(raw_text, doc_fname, instr)

    st.stop()   # Never fall through to standard chat or quiz CTA

# ──────────────────────────────────────────────────────────────────────────────
# ── ORAL BOARD MODE ───────────────────────────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────────────
elif st.session_state.chatbot_mode == "oral":
    is_empty = len(st.session_state.messages) == 0

    if is_empty:
        st.markdown("""
        <style>
        [data-testid="stBottom"] {
            position:fixed !important;
            top:50% !important;
            left:50% !important;
            transform:translate(-50%, 20px) !important;
            width:min(680px,88vw) !important;
            bottom:unset !important;
            background:transparent !important;
            padding:0 !important;
        }
        [data-testid="stBottom"] > div {
            background:transparent !important;
            padding:0 !important;
        }
        </style>
        <div class="welcome-overlay">
            <div class="welcome-box">
                <div class="welcome-title">🎖️ Oral Board / Viva<br><span style="font-size:0.55em;letter-spacing:0.10em;color:rgba(245,233,200,0.65);">Short answers from your selected subject manual</span></div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        if oral_prompt := st.chat_input("Ask any naval/technical question…"):
            st.session_state.messages.append({"role": "user", "content": oral_prompt})
            st.rerun()
    else:
        st.markdown(
            "<h1 style='font-family:Cinzel,serif;font-size:clamp(18px,2.2vw,26px);"
            "font-weight:700;background:linear-gradient(180deg,#ffffff 0%,#f5d98a 40%,#c9a45c 100%);"
            "-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;"
            "letter-spacing:0.08em;filter:drop-shadow(0 0 14px rgba(201,164,92,0.3));"
            "margin-bottom:10px;'>🎖️ Oral Board / Viva</h1>",
            unsafe_allow_html=True
        )

        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                if msg["role"] == "assistant":
                    render_message(msg["content"])
                else:
                    st.write(msg["content"])

        if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
            last_user = st.session_state.messages[-1]["content"]
            if not any(m["role"] == "assistant" for m in st.session_state.messages[-1:]):
                run_oral_query(last_user)

        if oral_prompt := st.chat_input("Ask any naval/technical question…"):
            st.session_state.messages.append({"role": "user", "content": oral_prompt})
            with st.chat_message("user"):
                st.write(oral_prompt)
            run_oral_query(oral_prompt)

    st.stop()   # Don't render standard chat below

# ──────────────────────────────────────────────────────────────────────────────
# ── STANDARD MODE ─────────────────────────────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────────────
# ── When no messages yet: show centred welcome + input ────────────────────────
if is_empty:
    st.markdown("""
    <style>
    [data-testid="stBottom"] {
        position:fixed !important;
        top:50% !important;
        left:50% !important;
        transform:translate(-50%, 20px) !important;
        width:min(680px,88vw) !important;
        bottom:unset !important;
        background:transparent !important;
        padding:0 !important;
    }
    [data-testid="stBottom"] > div {
        background:transparent !important;
        padding:0 !important;
    }
    </style>
    <div class="welcome-overlay">
        <div class="welcome-box">
            <div class="welcome-title">Welcome Buddy!<br>How can I help you today?</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    if welcome_prompt := st.chat_input("Ask a technical question from your manual..."):
        st.session_state.user_difficulty_preference = 'standard'
        st.session_state.messages.append({"role": "user", "content": welcome_prompt})
        st.rerun()

# ── After first message: normal chat mode ─────────────────────────────────────
else:
    st.markdown(
        "<h1 style='font-family:Cinzel,serif;font-size:clamp(18px,2.2vw,26px);"
        "font-weight:700;background:linear-gradient(180deg,#ffffff 0%,#f5d98a 40%,#c9a45c 100%);"
        "-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;"
        "letter-spacing:0.08em;filter:drop-shadow(0 0 14px rgba(201,164,92,0.3));"
        "margin-bottom:10px;'>AI Learning Assistant</h1>",
        unsafe_allow_html=True
    )

    # Render existing messages
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            if msg["role"] == "user" and msg.get("reask_label"):
                st.caption(f"🔄 *Re-asking with {msg['reask_label']} — adjusting for your rating*")
            if msg["role"] == "assistant":
                render_message(msg["content"])
            else:
                st.write(msg["content"])

    # If last message is from user and no assistant reply yet, run query
    if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
        last_user = st.session_state.messages[-1]["content"]
        if not any(m["role"] == "assistant" for m in st.session_state.messages[-1:]):
            run_query(last_user)

# ── Auto re-ask on low rating ─────────────────────────────────────────────────
if not is_empty:
    if st.session_state.trigger_reask:
        st.session_state.trigger_reask = False
        st.rerun()

    elif prompt := st.chat_input("Ask a technical question from your manual..."):
        # Reset difficulty to standard for every new question
        st.session_state.user_difficulty_preference = 'standard'
        st.session_state.show_quiz_cta = False  # hide old CTA while answering
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.write(prompt)
        run_query(prompt)

# ── FEEDBACK ──────────────────────────────────────────────────────────────────
if st.session_state.current_cache_id:
    st.divider()
    st.markdown(
        "<p style='font-family:Cinzel,serif;font-size:15px;font-weight:700;"
        "letter-spacing:0.20em;color:#e8c87a;margin-bottom:10px;'>"
        "📊 &nbsp;HOW WAS THE EXPLANATION?</p>",
        unsafe_allow_html=True)

    btn_col1, btn_col2, btn_col3, _ = st.columns([0.22, 0.22, 0.22, 0.34])

    if btn_col1.button("❌ Not clear at all", key="rate_not_clear", use_container_width=True):
        st.session_state.user_difficulty_preference = 'not_clear'
        update_feedback(st.session_state.current_cache_id, 1)
        st.session_state.current_cache_id = None
        last_user_msg = next(
            (m["content"] for m in reversed(st.session_state.messages)
             if m["role"] == "user"), None)
        if last_user_msg:
            st.toast("Generating the simplest explanation...", icon="🔄")
            st.session_state.messages.append({
                "role": "user",
                "content": last_user_msg,
                "reask_label": "Simplest explanation"
            })
            st.session_state.trigger_reask = True
        st.rerun()

    if btn_col2.button("🔶 Need a bit clarity", key="rate_need_clarity", use_container_width=True):
        st.session_state.user_difficulty_preference = 'need_clarity'
        update_feedback(st.session_state.current_cache_id, 2)
        st.session_state.current_cache_id = None
        last_user_msg = next(
            (m["content"] for m in reversed(st.session_state.messages)
             if m["role"] == "user"), None)
        if last_user_msg:
            st.toast("Generating a clearer explanation...", icon="🔄")
            st.session_state.messages.append({
                "role": "user",
                "content": last_user_msg,
                "reask_label": "Clearer explanation with some math"
            })
            st.session_state.trigger_reask = True
        st.rerun()

    if btn_col3.button("✅ Understood clearly", key="rate_understood", use_container_width=True):
        st.session_state.user_difficulty_preference = 'standard'
        update_feedback(st.session_state.current_cache_id, 3)
        st.session_state.current_cache_id = None
        st.toast("Great! Ask your next question.", icon="✅")
        st.rerun()

# ── QUIZ CTA — standard mode only, never in nautical or oral board ────────────
if (not is_empty
        and st.session_state.get("show_quiz_cta", False)
        and st.session_state.get("chatbot_mode", "standard") == "standard"):
    n_topics = len(st.session_state.chatbot_topics_asked)
    topic_word = "topic" if n_topics == 1 else "topics"
    st.markdown(f"""
        <div class="quiz-cta">
            <div class="quiz-cta-icon">🎯</div>
            <div class="quiz-cta-text">
                <div class="quiz-cta-title">Test Your Understanding</div>
                <div class="quiz-cta-sub">
                    You've explored {n_topics} {topic_word} this session.
                    Questions drawn from the <b>{selected_subject}</b> question bank, matched to topics you explored.
                </div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    quiz_col, _ = st.columns([0.38, 0.62])
    with quiz_col:
        if st.button("🎯  Take Quiz on This Topic", use_container_width=True, key="quiz_cta_btn"):
            _launch_chatbot_quiz()

    st.markdown("<div style='margin-bottom:6px'></div>", unsafe_allow_html=True)
