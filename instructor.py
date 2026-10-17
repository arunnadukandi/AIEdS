import streamlit as st
import os
import json
import faiss
import numpy as np
import fitz  # PyMuPDF
import re
import base64
from sentence_transformers import SentenceTransformer

# ── 1. CONFIGURATION ──────────────────────────────────────────────────────────
BASE_DIR = "/home/ece/IEAS/login"

@st.cache_resource
def load_embedder_model():
    model_path = os.path.join(BASE_DIR, "Python-3.12.9", "embedding_model")
    target = model_path if os.path.exists(model_path) else 'all-MiniLM-L6-v2'
    return SentenceTransformer(target)

def universal_cleaner(text):
    """Converts common technical symbols to LaTeX for better LLM rendering."""
    greek = {
        "λ": "\\lambda", "σ": "\\sigma", "θ": "\\theta", "Δ": "\\Delta",
        "ω": "\\omega", "μ": "\\mu", "π": "\\pi", "α": "\\alpha", "β": "\\beta"
    }
    for char, latex in greek.items():
        text = text.replace(char, latex)
    text = re.sub(r'10\s*\^?\s*([-+]?\d+)', r'10^{\1}', text)
    return text

# ── 2. AUTH CHECK ─────────────────────────────────────────────────────────────
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from session_guard import require_role, logout
require_role("instructor")

st.set_page_config(page_title="AIEdS - Instructor Panel", layout="wide",
                   initial_sidebar_state="collapsed")

# ── 3. BACKGROUND ─────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def _bg_b64():
    for name in ["instructor_background.jpeg", "instructor_background.png",
                 "instructor_background.jpg", "mainpage.jpeg"]:
        p = os.path.join(BASE_DIR, name)
        if os.path.exists(p):
            with open(p, "rb") as f:
                data = f.read()
            ext = "png" if data[:8] == b'\x89PNG\r\n\x1a\n' else "jpeg"
            return base64.b64encode(data).decode(), ext
    return "", "jpeg"

_bg_data, _bg_ext = _bg_b64()
_bg_url = f"data:image/{_bg_ext};base64,{_bg_data}" if _bg_data else ""

# ── 4. COMPLETE VIBRANT CSS ────────────────────────────────────────────────────
st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@400;600;700;900&family=Rajdhani:wght@400;500;600;700&family=Orbitron:wght@400;700&display=swap');

*,*::before,*::after{{margin:0;padding:0;box-sizing:border-box}}
:root{{
    --gold: #c9a45c;
    --gold-bright: #f5d98a;
    --border-gold: rgba(201, 164, 92, 0.5);
    --glass-card-bg: rgba(3, 13, 28, 0.92);
}}

.stApp {{
    background: linear-gradient(rgba(2,8,20,0.85),rgba(2,8,20,0.85)), url('{_bg_url}') center/cover no-repeat fixed !important;
    min-height: 100vh;
}}

/* ── AURORA DRIFT ANIMATION ── */
.stApp::before{{
    content:''; position:fixed; inset:0; z-index:-1; pointer-events:none;
    background: radial-gradient(ellipse 80% 40% at 20% 80%, rgba(201,164,92,.12) 0%, transparent 60%),
                radial-gradient(ellipse 60% 30% at 80% 20%, rgba(12,40,90,.22) 0%, transparent 55%);
    animation: auroraDrift 22s ease-in-out infinite alternate;
}}
@keyframes auroraDrift {{
    0%   {{ transform: scale(1) translateY(0); opacity: 0.6; }}
    50%  {{ transform: scale(1.05) translateY(-10px); opacity: 1; }}
    100% {{ transform: scale(1) translateY(5px); opacity: 0.8; }}
}}

/* ── FLOATING TOGGLE (Pill-style navigation) ── */
[data-testid="collapsedControl"], [data-testid="stSidebarCollapsedControl"] {{
    display:flex !important; visibility:visible !important; position:fixed !important;
    top:50% !important; left:0px !important; transform:translateY(-50%) !important;
    background: linear-gradient(135deg, rgba(201,164,92,0.4), rgba(201,164,92,0.15)) !important;
    border: 1px solid var(--gold) !important; border-left: none !important;
    border-radius: 0 12px 12px 0 !important; width: 32px !important; height: 64px !important;
    z-index: 99999 !important; cursor: pointer !important; backdrop-filter: blur(10px);
    animation: sidebarPulse 2.5s ease-in-out infinite !important;
}}
[data-testid="collapsedControl"] svg {{ fill: var(--gold-bright) !important; width: 22px; height: 22px; }}
@keyframes sidebarPulse {{
    0%,100% {{ box-shadow: 0 0 10px rgba(201,164,92,0.2); border-color: rgba(201,164,92,0.6); }}
    50%      {{ box-shadow: 0 0 25px rgba(201,164,92,0.5); border-color: white; }}
}}

/* ── SIDEBAR CLEANUP ── */
[data-testid="stSidebarNav"], [data-testid="stSidebarNavItems"],
section[data-testid="stSidebar"] > div:first-child > div:first-child ul {{ display: none !important; }}

[data-testid="stSidebar"]{{
    background: linear-gradient(180deg, #020814 0%, #051026 100%) !important;
    border-right: 2px solid var(--gold) !important;
}}
[data-testid="stSidebar"] * {{ color: #ffffff !important; font-family: 'Rajdhani', sans-serif !important; font-size: 15px !important; }}

/* ── PAGE HEADERS & SUBTITLES ── */
.stApp h1 {{
    font-family: 'Cinzel', serif !important;
    background: linear-gradient(180deg, #ffffff 0%, #f5d98a 40%, #c9a45c 100%);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    filter: drop-shadow(0 0 12px rgba(201,164,92,0.4));
    font-weight: 900 !important; font-size: 36px !important; margin-bottom: 5px !important;
}}

.header-subtitle {{
    font-family: 'Rajdhani', sans-serif !important;
    font-size: 20px !important; font-weight: 700 !important;
    color: #ffffff !important; text-transform: uppercase;
    text-shadow: 2px 2px 8px rgba(0,0,0,1); letter-spacing: 0.1em;
}}

/* ── GLASS CARDS ── */
.glass-card {{
    background: var(--glass-card-bg) !important;
    border: 1px solid var(--border-gold);
    border-top: 1px solid rgba(255, 255, 255, 0.25);
    border-radius: 18px; padding: 35px; margin-bottom: 25px;
    backdrop-filter: blur(15px); box-shadow: 0 15px 40px rgba(0,0,0,0.6);
}}

/* ── VIBRANT PROCESS BUTTON (Total Visibility) ── */
div[data-testid="stFormSubmitButton"] > button, .stButton > button {{
    background: linear-gradient(90deg, #c9a45c 0%, #f5d98a 50%, #c9a45c 100%) !important;
    color: #000000 !important; -webkit-text-fill-color: #000000 !important;
    font-family: 'Cinzel', serif !important; font-weight: 900 !important;
    font-size: 17px !important; letter-spacing: 0.12em !important;
    border: none !important; border-radius: 10px !important; height: 54px !important;
    box-shadow: 0 5px 15px rgba(0,0,0,0.5) !important; text-transform: uppercase !important;
}}

/* ── FORM LABELS ── */
.stApp label p {{
    color: var(--gold-bright) !important; font-family: 'Cinzel', serif !important;
    font-size: 14px !important; font-weight: 800 !important;
    text-transform: uppercase !important; text-shadow: 1px 1px 2px black;
}}

/* ── ALERTS (Success/Error Glow) ── */
div[data-testid="stAlert"] {{
    background: rgba(0, 0, 0, 0.85) !important;
    border-radius: 12px !important; border: 1px solid var(--border-gold) !important;
}}
div[data-testid="stAlert"][kind="success"] {{ border-left: 6px solid #00ff88 !important; }}
div[data-testid="stAlert"][kind="success"] p {{ color: #00ff88 !important; font-weight: 700 !important; }}

/* ── EVALUATION BOX ── */
.eval-box{{ background: rgba(4, 15, 32, 0.95); border: 2px solid var(--gold); border-radius: 14px; padding: 25px; margin-top: 16px; }}
.eval-score{{ font-family: 'Orbitron', sans-serif; font-size: 2.8rem; font-weight: 700; color: var(--gold-bright) !important; line-height: 1.1; }}
.eval-text{{ color: #ffffff !important; font-size: 16px; line-height: 1.7; font-family: 'Rajdhani', sans-serif !important; font-weight: 500; }}

/* ── PROGRESS BAR ── */
.stProgress>div>div>div{{ background: var(--gold-bright) !important; height: 10px !important; border-radius: 10px !important; }}

/* ── SCROLLBAR ── */
::-webkit-scrollbar {{ width: 8px; }}
::-webkit-scrollbar-thumb {{ background: var(--gold); border-radius: 10px; }}

/* ── TAB HEADERS: BOLD, LARGE & CLEAR ── */

/* 1. The container for the tabs */
.stTabs [data-baseweb="tab-list"] {{
    gap: 30px !important;
    background: rgba(0, 0, 0, 0.5) !important; /* Darker background for contrast */
    padding: 12px 20px !important;
    border-radius: 15px !important;
    border-bottom: 2px solid rgba(201, 164, 92, 0.3) !important;
}}

/* 2. Styling for all Tabs (Unselected) */
.stTabs [data-baseweb="tab"] {{
    height: 50px !important;
}}

.stTabs [data-baseweb="tab"] p {{
    font-size: 20px !important;         /* Much larger font */
    font-weight: 800 !important;         /* Extra Bold */
    font-family: 'Rajdhani', sans-serif !important;
    color: rgba(255, 255, 255, 0.5) !important; /* Faded white when not selected */
    letter-spacing: 0.05em !important;
    transition: all 0.3s ease !important;
}}

/* 3. Styling for the Selected Tab */
.stTabs [aria-selected="true"] p {{
    color: #f5d98a !important;          /* Bright Vibrant Gold */
    font-weight: 900 !important;         /* Max Boldness */
    text-shadow: 0 0 15px rgba(245, 217, 138, 0.6) !important; /* Glow effect */
}}

/* 4. The moving indicator line under the tab */
[data-baseweb="tab-highlight-point"] {{
    background-color: #f5d98a !important; /* Gold line instead of red */
    height: 4px !important;
}}
</style>
""", unsafe_allow_html=True)

# ── 5. SIDEBAR (collapsed by default, toggle via button) ──────────────────────
instructor_name = st.session_state.get("full_name",
                  st.session_state.get("username", "Instructor")).upper()

with st.sidebar:
    st.markdown(f"""
    <div style='padding:16px 4px 14px 4px;'>
        <p style='font-family:Cinzel,serif;font-size:20px;font-weight:900;
           background:linear-gradient(180deg,#fff 0%,#f5d98a 35%,#c9a45c 100%);
           -webkit-background-clip:text;-webkit-text-fill-color:transparent;
           background-clip:text;letter-spacing:0.12em;margin-bottom:12px;'>
           INSTRUCTOR PANEL</p>
        <p style='font-size:12px;color:rgba(201,164,92,0.85);font-family:Cinzel,serif;
           letter-spacing:0.12em;margin-bottom:4px;font-weight:700;'>
           INSTRUCTOR</p>
        <p style='font-size:13px;color:#f0d898;font-family:Cinzel,serif;
           letter-spacing:0.10em;font-weight:900;margin-bottom:4px;'>
           {instructor_name}</p>
        <p style='font-size:11px;color:rgba(201,164,92,0.55);font-family:Cinzel,serif;
           letter-spacing:0.10em;'>
           ID: {st.session_state.get('username','N/A')}</p>
    </div>
    """, unsafe_allow_html=True)
    st.divider()

    st.markdown('<p class="sec-label">Navigation</p>', unsafe_allow_html=True)
    if st.button("🏠  Home / Dashboard", use_container_width=True):
        st.switch_page("login.py")
    if st.button("🚪  Logout", use_container_width=True):
        logout("login.py")
        st.switch_page("login.py")

    st.divider()
    st.markdown("""
    <div style='padding:6px 0;'>
        <p style='font-family:Cinzel,serif;font-size:9px;letter-spacing:.18em;
                  color:rgba(201,164,92,.55);text-transform:uppercase;margin-bottom:10px;'>
                  Quick Guide</p>
        <div style='display:flex;flex-direction:column;gap:8px;'>
            <div style='display:flex;align-items:flex-start;gap:8px;'>
                <span style='color:#e8c87a;font-size:14px;'>📚</span>
                <span style='font-family:Rajdhani,sans-serif;font-size:12px;
                      color:rgba(240,220,180,.70);'>Upload PDFs to index for RAG chatbot</span>
            </div>
            <div style='display:flex;align-items:flex-start;gap:8px;'>
                <span style='color:#e8c87a;font-size:14px;'>📝</span>
                <span style='font-family:Rajdhani,sans-serif;font-size:12px;
                      color:rgba(240,220,180,.70);'>Upload assignment sheets + answer keys</span>
            </div>
            <div style='display:flex;align-items:flex-start;gap:8px;'>
                <span style='color:#e8c87a;font-size:14px;'>🤖</span>
                <span style='font-family:Rajdhani,sans-serif;font-size:12px;
                      color:rgba(240,220,180,.70);'>AI evaluates cadet answer images automatically</span>
            </div>
            <div style='display:flex;align-items:flex-start;gap:8px;'>
                <span style='color:#e8c87a;font-size:14px;'>🗂️</span>
                <span style='font-family:Rajdhani,sans-serif;font-size:12px;
                      color:rgba(240,220,180,.70);'>Manage & delete indexed materials by term</span>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

# ── 6. PAGE HEADER ────────────────────────────────────────────────────────────
st.markdown("""
<div style='padding:18px 0 6px 0;'>
    <h1 style='font-family:Cinzel,serif;font-size:clamp(18px,2.2vw,28px);font-weight:900;
       background:linear-gradient(180deg,#ffffff 0%,#f5d98a 40%,#c9a45c 100%);
       -webkit-background-clip:text;-webkit-text-fill-color:transparent;
       background-clip:text;letter-spacing:0.10em;margin-bottom:4px;'>
       AIEdS — INSTRUCTOR PANEL</h1>
    <p style='font-family:Rajdhani,sans-serif;font-size:14px;
       color:rgba(201,164,92,0.60);letter-spacing:0.08em;'>
       Knowledge Management · Assignment Evaluation · Materials Manager</p>
</div>
""", unsafe_allow_html=True)

# ── 7. TABS ───────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📚  Knowledge Upload",
    "📝  Assignment Evaluation",
    "🗂️  Materials Manager",
    "📋  Post Assignment",
    "📊  Submissions",
])

# ════════════════════════════════════════════════════════════════════════════════
#  TAB 1 — KNOWLEDGE UPLOAD
# ════════════════════════════════════════════════════════════════════════════════
with tab1:
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.markdown("""
    <p style='font-family:Cinzel,serif;font-size:15px;font-weight:700;
       color:#e8c87a;letter-spacing:.08em;margin-bottom:4px;'>
       Add New Academic Material</p>
    <p style='font-family:Rajdhani,sans-serif;font-size:13px;
       color:rgba(201,164,92,.55);margin-bottom:16px;'>
       Upload a PDF manaul for the Cadet access.</p>
    """, unsafe_allow_html=True)

    with st.form("upload_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            sub_name = st.text_input("Subject Name", placeholder="e.g., Marine Engineering")
        with col2:
            term_selection = st.selectbox("Assign to Term", [f"Term_{i}" for i in range(1, 9)])
        up_file  = st.file_uploader("Upload Manual (PDF)", type="pdf")
        submitted = st.form_submit_button("⚡  Process and Index Material", use_container_width=True)

    st.markdown('</div>', unsafe_allow_html=True)

    if submitted:
        if sub_name and up_file:
            def process_pdf_advanced(pdf_file, subject_name, term_folder_name, model):
                safe_subject = subject_name.strip().replace(" ", "_").lower()
                manual_name  = os.path.splitext(pdf_file.name)[0]
                safe_manual  = manual_name.strip().replace(" ", "_").lower()
                file_stem    = f"{safe_subject}_{safe_manual}" if safe_manual != safe_subject else safe_subject
                term_dir     = os.path.join(BASE_DIR, "user_profiles", term_folder_name)
                IMAGE_DIR    = os.path.join(BASE_DIR, "static", "images", file_stem)
                os.makedirs(term_dir, exist_ok=True)
                os.makedirs(IMAGE_DIR, exist_ok=True)
                temp_path = f"temp_{pdf_file.name}"
                with open(temp_path, "wb") as f:
                    f.write(pdf_file.getbuffer())
                doc = fitz.open(temp_path)
                chunks = []
                chunk_size, overlap = 600, 100
                progress_bar = st.progress(0)
                for page_num in range(len(doc)):
                    page      = doc[page_num]
                    page_text = universal_cleaner(page.get_text("text"))
                    page_header = f"--- SOURCE: {subject_name} | PAGE: {page_num + 1} ---\n\n"
                    if page.get_drawings() or page.get_images():
                        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                        img_filename  = f"pg{page_num}_visual.png"
                        img_save_path = os.path.join(IMAGE_DIR, img_filename)
                        pix.save(img_save_path)
                        img_web_path  = f"/app/static/images/{file_stem}/{img_filename}"
                        page_text     = f"\n\n![Technical Illustration]({img_web_path})\n\n" + page_text
                    for i in range(0, len(page_text), chunk_size - overlap):
                        chunks.append({
                            "text":    page_header + page_text[i : i + chunk_size],
                            "page":    page_num + 1,
                            "subject": subject_name.strip(),
                            "manual":  manual_name.strip(),
                        })
                    progress_bar.progress((page_num + 1) / len(doc))
                with st.spinner("Generating embeddings..."):
                    embeddings = model.encode([c["text"] for c in chunks]).astype('float32')
                    faiss.normalize_L2(embeddings)
                    index = faiss.IndexFlatIP(embeddings.shape[1])
                    index.add(embeddings)
                    faiss.write_index(index, os.path.join(term_dir, f"{file_stem}_faiss.index"))
                    with open(os.path.join(term_dir, f"{file_stem}_doc.json"), 'w') as f:
                        json.dump({str(i): chunks[i] for i in range(len(chunks))}, f)
                    with open(os.path.join(term_dir, f"{file_stem}_meta.json"), 'w') as f:
                        json.dump({"subject": subject_name.strip(),
                                   "manual":  manual_name.strip(),
                                   "stem":    file_stem}, f)
                doc.close()
                # Save original PDF to term folder so study_material.py can list it
                pdf_dest = os.path.join(term_dir, pdf_file.name)
                with open(pdf_dest, "wb") as f:
                    f.write(pdf_file.getbuffer())
                os.remove(temp_path)
                return len(chunks), file_stem

            embedder = load_embedder_model()
            count, stem = process_pdf_advanced(up_file, sub_name, term_selection, embedder)
            st.success(f"✅  Successfully indexed **{count}** context chunks for **'{sub_name}'** → Term {term_selection}.")
        else:
            st.error("Please provide both a Subject Name and a PDF file.")


# ════════════════════════════════════════════════════════════════════════════════
#  TAB 2 — ASSIGNMENT EVALUATION
# ════════════════════════════════════════════════════════════════════════════════
with tab2:
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.markdown("""
    <p style='font-family:Cinzel,serif;font-size:15px;font-weight:700;
       color:#e8c87a;letter-spacing:.08em;margin-bottom:4px;'>
       AI-Powered Assignment Evaluation</p>
    <p style='font-family:Rajdhani,sans-serif;font-size:13px;
       color:rgba(201,164,92,.55);margin-bottom:16px;'>
       Upload the assignment sheet, answer key (optional), and the cadet's answer image.
       The AI will evaluate the response and provide a score with detailed feedback.</p>
    """, unsafe_allow_html=True)

    col_l, col_r = st.columns(2, gap="large")

    with col_l:
        st.markdown('<p class="sec-label">Assignment Sheet (PDF or Image)</p>', unsafe_allow_html=True)
        assignment_file = st.file_uploader(
            "Upload Assignment Sheet", type=["pdf", "png", "jpg", "jpeg"],
            key="asgn_sheet", label_visibility="collapsed")

        st.markdown('<p class="sec-label" style="margin-top:14px;">Answer Key (PDF or Image — Optional)</p>',
                    unsafe_allow_html=True)
        answer_key_file = st.file_uploader(
            "Upload Answer Key", type=["pdf", "png", "jpg", "jpeg"],
            key="asgn_key", label_visibility="collapsed")

    with col_r:
        st.markdown('<p class="sec-label">Cadet\'s Answer (Image)</p>', unsafe_allow_html=True)
        cadet_answer_file = st.file_uploader(
            "Upload Cadet Answer Image", type=["png", "jpg", "jpeg"],
            key="cadet_ans", label_visibility="collapsed")

        st.markdown('<p class="sec-label" style="margin-top:14px;">Subject / Context (Optional)</p>',
                    unsafe_allow_html=True)
        eval_subject = st.text_input("Subject context", placeholder="e.g., Radar Systems — Chapter 2",
                                     key="eval_subj", label_visibility="collapsed")
        total_marks  = st.number_input("Total Marks for this Assignment", min_value=1,
                                       max_value=200, value=20, step=1)

    st.markdown('</div>', unsafe_allow_html=True)

    # ── Vision model detection ───────────────────────────────────────────────
    VISION_MODELS = ["llama3.2-vision", "llava", "moondream", "bakllava",
                     "llava-llama3", "minicpm-v", "gemma3"]

    def _detect_vision_model():
        """Returns the first available vision-capable model name, or None."""
        try:
            from ollama import Client
            from httpx import Timeout
            client = Client(host="http://127.0.0.1:11434", timeout=Timeout(10.0))
            models = client.list()
            names  = [m["name"] for m in models.get("models", [])]
            for name in names:
                for vm in VISION_MODELS:
                    if vm in name.lower():
                        return name
        except Exception:
            pass
        return None

    detected_vision = _detect_vision_model()

    if not detected_vision:
        st.markdown("""
        <div style='background:rgba(180,120,0,0.12);border:1px solid rgba(201,164,92,0.40);
             border-radius:12px;padding:16px 20px;margin-bottom:16px;'>
            <p style='font-family:Cinzel,serif;font-size:12px;color:#e8c87a;
               letter-spacing:.08em;margin-bottom:6px;font-weight:700;'>
               ⚠️ NO VISION MODEL DETECTED</p>
            <p style='font-family:Rajdhani,sans-serif;font-size:13px;
               color:rgba(240,220,180,.75);margin-bottom:8px;'>
               Image-based evaluation requires a vision-capable model.
               The evaluation code is ready — it will activate automatically
               the moment you pull a vision model.</p>
            <p style='font-family:Rajdhani,sans-serif;font-size:13px;
               color:rgba(201,164,92,.80);'>
               Recommended models to pull when network is available:<br>
               &nbsp;&nbsp;• <code>ollama pull moondream</code> &nbsp;(1.8 GB — smallest)<br>
               &nbsp;&nbsp;• <code>ollama pull llava:7b</code> &nbsp;(4.1 GB)<br>
               &nbsp;&nbsp;• <code>ollama pull llama3.2-vision</code> &nbsp;(7.9 GB — best quality)
            </p>
        </div>
        """, unsafe_allow_html=True)

    # ── Evaluate button ──────────────────────────────────────────────────────
    eval_clicked = st.button(
        "🤖  Evaluate with AI",
        use_container_width=True,
        key="eval_btn",
        disabled=(not detected_vision)
    )

    if eval_clicked and detected_vision:
        if not cadet_answer_file:
            st.error("Please upload the cadet's answer image to evaluate.")
        else:
            # ── Build content blocks for llama3.2-vision ──────────────────────
            import base64 as _b64

            def _to_b64(uploaded_file):
                return _b64.b64encode(uploaded_file.read()).decode("utf-8")

            def _extract_pdf_text(uploaded_file):
                """Extract text from PDF using PyMuPDF."""
                data = uploaded_file.read()
                doc  = fitz.open(stream=data, filetype="pdf")
                text = "\n\n".join(page.get_text("text") for page in doc)
                doc.close()
                return text.strip()

            def _is_pdf(f):
                return f.name.lower().endswith(".pdf")

            # Cadet answer — always image
            cadet_b64  = _to_b64(cadet_answer_file)
            cadet_mime = "image/jpeg" if cadet_answer_file.name.lower().endswith((".jpg",".jpeg")) else "image/png"

            # Assignment sheet text / image
            asgn_text = ""
            asgn_image_block = None
            if assignment_file:
                if _is_pdf(assignment_file):
                    asgn_text = _extract_pdf_text(assignment_file)
                else:
                    ab64 = _to_b64(assignment_file)
                    mime = "image/jpeg" if assignment_file.name.lower().endswith((".jpg",".jpeg")) else "image/png"
                    asgn_image_block = {"type": "image_url",
                                        "image_url": {"url": f"data:{mime};base64,{ab64}"}}

            # Answer key text
            key_text = ""
            if answer_key_file:
                if _is_pdf(answer_key_file):
                    key_text = _extract_pdf_text(answer_key_file)
                else:
                    kb64 = _to_b64(answer_key_file)
                    key_text = f"[Answer key provided as image — use it as reference for marking]"

            # ── Build prompt ──────────────────────────────────────────────────
            subject_ctx = f"Subject/Chapter: {eval_subject}.\n" if eval_subject else ""
            asgn_ctx    = f"\n\nASSIGNMENT SHEET:\n{asgn_text}" if asgn_text else (
                          "\n\nASSIGNMENT SHEET: [See uploaded image]" if asgn_image_block else "")
            key_ctx     = f"\n\nANSWER KEY:\n{key_text}" if key_text else ""

            prompt_text = (
                f"You are an experienced naval academy instructor evaluating a cadet's written assignment.\n"
                f"{subject_ctx}"
                f"Total marks available: {total_marks}.\n"
                f"{asgn_ctx}{key_ctx}\n\n"
                f"CADET'S ANSWER: [See the image provided]\n\n"
                f"Instructions:\n"
                f"1. Read the cadet's handwritten/typed answer from the image carefully.\n"
                f"2. Compare it against the assignment questions and answer key (if provided).\n"
                f"3. Provide:\n"
                f"   - SCORE: X / {total_marks}\n"
                f"   - STRENGTHS: What the cadet answered correctly\n"
                f"   - WEAKNESSES: What was missing, incorrect, or incomplete\n"
                f"   - SUGGESTIONS: Specific advice for improvement\n"
                f"   - OVERALL REMARKS: 2-3 sentence summary\n"
                f"Be fair, specific, and constructive. Use the format above clearly."
            )

            # ── Call llama3.2-vision via ollama ───────────────────────────────
            with st.spinner(f"🤖 Evaluating with `{detected_vision}` — this may take 20-40 seconds..."):
                try:
                    from ollama import Client
                    from httpx import Timeout

                    client = Client(host="http://127.0.0.1:11434", timeout=Timeout(120.0))

                    # Build message content list
                    content = [{"type": "text", "text": prompt_text}]
                    # Add cadet answer image
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{cadet_mime};base64,{cadet_b64}"}
                    })
                    # If assignment sheet was an image, add it too
                    if asgn_image_block:
                        content.append(asgn_image_block)

                    resp = client.chat(
                        model=detected_vision,
                        messages=[{"role": "user", "content": content}],
                        stream=False,
                        keep_alive=-1,
                        options={"num_gpu": 50, "temperature": 0.1, "num_ctx": 4096}
                    )
                    eval_result = resp["message"]["content"].strip()
                    st.session_state["last_eval_result"] = eval_result
                    st.session_state["last_eval_marks"]  = total_marks

                except Exception as e:
                    st.error(f"⚠️ Evaluation failed: {e}")
                    eval_result = None

    # ── Show result ───────────────────────────────────────────────────────────
    if st.session_state.get("last_eval_result"):
        result_text  = st.session_state["last_eval_result"]
        total_m      = st.session_state.get("last_eval_marks", 20)

        # Try to extract score from result
        score_match  = re.search(r'SCORE[:\s]+(\d+(?:\.\d+)?)\s*/\s*(\d+)', result_text, re.IGNORECASE)
        score_display = score_match.group(0) if score_match else "See below"

        st.markdown(f"""
        <div class="eval-box">
            <div style='display:flex;align-items:center;gap:20px;margin-bottom:16px;flex-wrap:wrap;'>
                <div>
                    <div class="eval-label">AI Evaluation Score</div>
                    <div class="eval-score">{score_display}</div>
                </div>
                <div style='flex:1;min-width:200px;'>
                    <div class="eval-label">Subject</div>
                    <div style='font-family:Cinzel,serif;font-size:13px;color:#e8c87a;'>
                        {eval_subject or "—"}</div>
                    <div class="eval-label" style="margin-top:8px;">Total Marks</div>
                    <div style='font-family:Orbitron,sans-serif;font-size:15px;color:#e8c87a;'>{total_m}</div>
                </div>
            </div>
            <hr style='border-color:rgba(201,164,92,.22);margin:12px 0;'/>
            <div class="eval-text">{result_text.replace(chr(10), '<br>')}</div>
        </div>
        """, unsafe_allow_html=True)

        # Download button for report
        report_txt = (
            f"AIEdS Assignment Evaluation Report\n"
            f"{'='*50}\n"
            f"Subject: {eval_subject or 'N/A'}\n"
            f"Total Marks: {total_m}\n"
            f"{'='*50}\n\n"
            f"{result_text}"
        )
        st.download_button(
            label="📥  Download Evaluation Report",
            data=report_txt,
            file_name="evaluation_report.txt",
            mime="text/plain",
            use_container_width=True
        )

        if st.button("🗑️  Clear Result", use_container_width=True, key="clear_eval"):
            st.session_state.pop("last_eval_result", None)
            st.session_state.pop("last_eval_marks", None)
            st.rerun()


# ════════════════════════════════════════════════════════════════════════════════
#  TAB 3 — MATERIALS MANAGER
# ════════════════════════════════════════════════════════════════════════════════
with tab3:
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.markdown("""
    <p style='font-family:Cinzel,serif;font-size:15px;font-weight:700;
       color:#e8c87a;letter-spacing:.08em;margin-bottom:4px;'>
       Manage Indexed Materials</p>
    <p style='font-family:Rajdhani,sans-serif;font-size:13px;
       color:rgba(201,164,92,.55);margin-bottom:16px;'>
       View and delete indexed manuals by term.</p>
    """, unsafe_allow_html=True)

    view_term = st.selectbox("Filter by Term:", [f"Term_{i}" for i in range(1, 9)], key="mgr_term")
    st.markdown('</div>', unsafe_allow_html=True)

    term_path = os.path.join(BASE_DIR, "user_profiles", view_term)

    if os.path.exists(term_path):
        meta_files = [f for f in os.listdir(term_path) if f.endswith("_meta.json")]
        if not meta_files:
            st.markdown("""
            <div class="glass-card">
                <p style='font-family:Rajdhani,sans-serif;font-size:14px;
                   color:rgba(201,164,92,.50);text-align:center;padding:10px 0;'>
                   No indexed materials found for this term.</p>
            </div>""", unsafe_allow_html=True)
        else:
            for meta_f in meta_files:
                with open(os.path.join(term_path, meta_f)) as j:
                    data = json.load(j)
                subj = data.get("subject", "Unknown")
                man  = data.get("manual",  "Unknown")
                stem = data.get("stem",    meta_f.replace("_meta.json", ""))

                # Check file sizes
                idx_size = ""
                idx_path = os.path.join(term_path, f"{stem}_faiss.index")
                if os.path.exists(idx_path):
                    sz = os.path.getsize(idx_path)
                    idx_size = f"{sz/1024:.0f} KB" if sz < 1024*1024 else f"{sz/1024/1024:.1f} MB"

                st.markdown(f"""
                <div class="glass-card" style="padding:16px 20px;margin-bottom:10px;">
                    <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;">
                        <div>
                            <p style="font-family:Cinzel,serif;font-size:13px;color:#e8c87a;
                               font-weight:700;margin-bottom:2px;">📖 {subj}</p>
                            <p style="font-family:Rajdhani,sans-serif;font-size:12px;
                               color:rgba(201,164,92,.55);margin:0;">Manual: {man}
                               {"&nbsp;&nbsp;·&nbsp;&nbsp;Index: " + idx_size if idx_size else ""}</p>
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                col_info, col_del = st.columns([0.85, 0.15])
                with col_del:
                    if st.button("🗑️ Delete", key=f"del_{stem}", use_container_width=True):
                        for ext in ["_faiss.index", "_doc.json", "_meta.json"]:
                            p = os.path.join(term_path, stem + ext)
                            if os.path.exists(p):
                                os.remove(p)
                        # Also remove the original PDF from the term folder
                        for f in os.listdir(term_path):
                            if f.lower().endswith(".pdf") and (
                                man.lower() in f.lower() or stem.lower() in f.lower()):
                                pdf_p = os.path.join(term_path, f)
                                if os.path.exists(pdf_p):
                                    os.remove(pdf_p)
                                break
                        st.toast(f"Deleted: {subj}")
                        st.rerun()
    else:
        st.markdown("""
        <div class="glass-card">
            <p style='font-family:Rajdhani,sans-serif;font-size:14px;
               color:rgba(201,164,92,.50);text-align:center;padding:10px 0;'>
               Term directory has not been created yet.
            </p></div>""", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════════════════
#  TAB 4 — POST ASSIGNMENT
# ════════════════════════════════════════════════════════════════════════════════
with tab4:
    import sqlite3 as _sq
    from datetime import datetime as _dt

    DB_PATH_INS = os.path.join(BASE_DIR, "sahayak.db")

    def _init_assignment_cols():
        """Ensure all required columns exist in assignments and submissions."""
        con = _sq.connect(DB_PATH_INS)
        c = con.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            term TEXT, subject TEXT, title TEXT, description TEXT,
            due_date TEXT, marks INTEGER DEFAULT 0,
            posted_by TEXT, created_at TEXT,
            sheet_data BLOB, sheet_name TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER, student_id TEXT,
            file_name TEXT, file_data BLOB, remarks TEXT,
            submitted_at TEXT,
            ai_score REAL, ai_feedback TEXT,
            manual_score REAL, status TEXT DEFAULT 'submitted',
            flagged INTEGER DEFAULT 0,
            FOREIGN KEY(assignment_id) REFERENCES assignments(id)
        )""")
        for col, defn in [
            ("sheet_data", "BLOB"), ("sheet_name", "TEXT"),
            ("ai_score", "REAL"), ("ai_feedback", "TEXT"),
            ("manual_score", "REAL"), ("status", "TEXT DEFAULT 'submitted'"),
            ("flagged", "INTEGER DEFAULT 0"),
        ]:
            try:
                c.execute(f"ALTER TABLE submissions ADD COLUMN {col} {defn}")
            except Exception:
                pass
            try:
                c.execute(f"ALTER TABLE assignments ADD COLUMN {col} {defn}")
            except Exception:
                pass
        con.commit(); con.close()

    _init_assignment_cols()

    posted_by_name = st.session_state.get("full_name",
                     st.session_state.get("username", "Instructor"))

    st.markdown("""
    <p style='font-family:Cinzel,serif;font-size:15px;font-weight:700;
       color:#e8c87a;letter-spacing:.08em;margin-bottom:4px;'>
       Post a New Assignment</p>
    <p style='font-family:Rajdhani,sans-serif;font-size:13px;
       color:rgba(201,164,92,.55);margin-bottom:20px;'>
       Fill in the details below. Cadets will see this in their Assignment Portal.</p>
    """, unsafe_allow_html=True)

    with st.form("post_assignment_form", clear_on_submit=True):
        col_a, col_b = st.columns(2, gap="large")
        with col_a:
            pa_term    = st.selectbox("Term", [f"Term_{i}" for i in range(1, 9)], key="pa_term")
            pa_subject = st.text_input("Subject", placeholder="e.g., Radar Systems", key="pa_subj")
            pa_title   = st.text_input("Assignment Title", placeholder="e.g., Chapter 3 — Propagation Loss", key="pa_title")
            pa_marks   = st.number_input("Maximum Marks", min_value=1, max_value=200, value=20, step=1, key="pa_marks")
        with col_b:
            pa_due     = st.date_input("Due Date", key="pa_due")
            pa_desc    = st.text_area("Description / Instructions", height=120,
                                      placeholder="Describe the assignment, what cadets must submit, evaluation criteria…",
                                      key="pa_desc")
            pa_sheet   = st.file_uploader("Assignment Sheet (PDF or Image, optional)",
                                          type=["pdf","png","jpg","jpeg"], key="pa_sheet")

        post_btn = st.form_submit_button("📋  Post Assignment", use_container_width=True)

    if post_btn:
        if not pa_subject.strip() or not pa_title.strip():
            st.error("Subject and Title are required.")
        else:
            sheet_data = pa_sheet.read() if pa_sheet else None
            sheet_name = pa_sheet.name  if pa_sheet else None
            con = _sq.connect(DB_PATH_INS)
            con.execute("""INSERT INTO assignments
                (term, subject, title, description, due_date, marks,
                 posted_by, created_at, sheet_data, sheet_name)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (pa_term, pa_subject.strip(), pa_title.strip(),
                 pa_desc.strip(), str(pa_due), int(pa_marks),
                 posted_by_name, _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
                 sheet_data, sheet_name))
            con.commit(); con.close()
            st.success(f"Assignment '{pa_title}' posted for {pa_term}.")

    # ── List existing assignments ──────────────────────────────────────────────
    st.markdown("<hr style='border-color:rgba(201,164,92,0.18);margin:20px 0;'>", unsafe_allow_html=True)
    st.markdown("""
    <p style='font-family:Cinzel,serif;font-size:13px;font-weight:700;
       color:#e8c87a;letter-spacing:.08em;margin-bottom:10px;'>
       Posted Assignments</p>
    """, unsafe_allow_html=True)

    flt_col, _ = st.columns([2, 4])
    with flt_col:
        pa_flt = st.selectbox("Filter", ["All Terms"] + [f"Term_{i}" for i in range(1, 9)],
                              key="pa_flt")

    con = _sq.connect(DB_PATH_INS)
    if pa_flt == "All Terms":
        rows = con.execute(
            "SELECT id,term,subject,title,due_date,marks,posted_by FROM assignments ORDER BY created_at DESC"
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT id,term,subject,title,due_date,marks,posted_by FROM assignments WHERE term=? ORDER BY created_at DESC",
            (pa_flt,)
        ).fetchall()
    con.close()

    if not rows:
        st.info("No assignments posted yet.")
    else:
        for asn_id, term, subj, title, due, marks, by in rows:
            col_info, col_del = st.columns([0.88, 0.12])
            with col_info:
                st.markdown(f"""
                <div style='background:rgba(1,5,14,0.82);border:1px solid rgba(201,164,92,0.28);
                     border-left:3px solid rgba(201,164,92,0.70);border-radius:4px;
                     padding:12px 18px;margin-bottom:4px;'>
                    <span style='font-family:Cinzel,serif;font-size:12px;font-weight:700;
                          color:#e8c87a;letter-spacing:.1em;text-transform:uppercase;'>
                        {title}</span>
                    <span style='font-family:Rajdhani,sans-serif;font-size:12px;
                          color:rgba(201,164,92,.55);margin-left:14px;'>
                        {term} &nbsp;·&nbsp; {subj} &nbsp;·&nbsp; Due: {due} &nbsp;·&nbsp; {marks} marks &nbsp;·&nbsp; By: {by}
                    </span>
                </div>
                """, unsafe_allow_html=True)
            with col_del:
                if st.button("Delete", key=f"del_asn_{asn_id}", use_container_width=True):
                    con = _sq.connect(DB_PATH_INS)
                    con.execute("DELETE FROM assignments WHERE id=?", (asn_id,))
                    con.execute("DELETE FROM submissions WHERE assignment_id=?", (asn_id,))
                    con.commit(); con.close()
                    st.rerun()


# ════════════════════════════════════════════════════════════════════════════════
#  TAB 5 — SUBMISSIONS QUEUE
# ════════════════════════════════════════════════════════════════════════════════
with tab5:
    import sqlite3 as _sq2
    import re as _re

    DB_PATH_SUB = os.path.join(BASE_DIR, "sahayak.db")

    st.markdown("""
    <p style='font-family:Cinzel,serif;font-size:15px;font-weight:700;
       color:#e8c87a;letter-spacing:.08em;margin-bottom:4px;'>
       Submission Queue</p>
    <p style='font-family:Rajdhani,sans-serif;font-size:13px;
       color:rgba(201,164,92,.55);margin-bottom:16px;'>
       Select an assignment to view submissions, run AI grading, adjust scores, and release results.</p>
    """, unsafe_allow_html=True)

    # ── Assignment selector ───────────────────────────────────────────────────
    con2 = _sq2.connect(DB_PATH_SUB)
    asn_list = con2.execute(
        "SELECT id, term, subject, title FROM assignments ORDER BY created_at DESC"
    ).fetchall()
    con2.close()

    if not asn_list:
        st.info("No assignments posted yet. Use the Post Assignment tab first.")
        st.stop()

    asn_options = {f"[{a[1]}] {a[3]} — {a[2]}": a[0] for a in asn_list}
    sel_asn_label = st.selectbox("Select Assignment", list(asn_options.keys()), key="sq_asn")
    sel_asn_id    = asn_options[sel_asn_label]

    # ── Load submissions for selected assignment ───────────────────────────────
    con2 = _sq2.connect(DB_PATH_SUB)
    subs = con2.execute("""
        SELECT id, student_id, file_name, file_data, remarks,
               submitted_at, ai_score, ai_feedback, manual_score, status, flagged
        FROM submissions WHERE assignment_id=? ORDER BY submitted_at ASC
    """, (sel_asn_id,)).fetchall()
    total_marks_row = con2.execute(
        "SELECT marks FROM assignments WHERE id=?", (sel_asn_id,)
    ).fetchone()
    con2.close()

    total_marks_sq = total_marks_row[0] if total_marks_row else 20

    # ── Summary row ───────────────────────────────────────────────────────────
    n_total   = len(subs)
    n_graded  = sum(1 for s in subs if s[6] is not None or s[8] is not None)
    n_released = sum(1 for s in subs if s[9] == "released")

    st.markdown(f"""
    <div style='display:flex;gap:14px;margin-bottom:18px;flex-wrap:wrap;'>
        <div style='background:rgba(1,5,14,0.82);border:1px solid rgba(201,164,92,0.28);
             border-radius:4px;padding:10px 20px;text-align:center;'>
            <div style='font-family:Orbitron,sans-serif;font-size:22px;color:#e8c87a;'>{n_total}</div>
            <div style='font-family:Cinzel,serif;font-size:9px;letter-spacing:.12em;
                 color:rgba(201,164,92,.55);text-transform:uppercase;'>Submitted</div>
        </div>
        <div style='background:rgba(1,5,14,0.82);border:1px solid rgba(100,149,237,0.30);
             border-radius:4px;padding:10px 20px;text-align:center;'>
            <div style='font-family:Orbitron,sans-serif;font-size:22px;color:#c2d6ff;'>{n_graded}</div>
            <div style='font-family:Cinzel,serif;font-size:9px;letter-spacing:.12em;
                 color:rgba(100,149,237,.55);text-transform:uppercase;'>Graded</div>
        </div>
        <div style='background:rgba(1,5,14,0.82);border:1px solid rgba(0,196,114,0.30);
             border-radius:4px;padding:10px 20px;text-align:center;'>
            <div style='font-family:Orbitron,sans-serif;font-size:22px;color:#6effc8;'>{n_released}</div>
            <div style='font-family:Cinzel,serif;font-size:9px;letter-spacing:.12em;
                 color:rgba(0,196,114,.55);text-transform:uppercase;'>Released</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Release all graded results ─────────────────────────────────────────────
    if n_graded > 0 and n_graded > n_released:
        if st.button("🟢  Release All Graded Results to Cadets",
                     key="sq_release", use_container_width=True):
            con2 = _sq2.connect(DB_PATH_SUB)
            con2.execute("""
                UPDATE submissions SET status='released'
                WHERE assignment_id=?
                  AND (ai_score IS NOT NULL OR manual_score IS NOT NULL)
            """, (sel_asn_id,))
            con2.commit(); con2.close()
            st.success("Results released. Cadets can now view their grades.")
            st.rerun()

    st.markdown("<hr style='border-color:rgba(201,164,92,0.15);margin:10px 0 18px 0;'>",
                unsafe_allow_html=True)

    if not subs:
        st.info("No submissions yet for this assignment.")
    else:
        for sub in subs:
            (sub_id, student_id, file_name, file_data, remarks,
             submitted_at, ai_score, ai_feedback, manual_score, status, flagged) = sub

            effective_score = manual_score if manual_score is not None else ai_score
            status_color = {
                "released": "#6effc8",
                "graded":   "#c2d6ff",
                "submitted":"#e8c87a",
            }.get(status or "submitted", "#e8c87a")

            flag_icon = " 🚩" if flagged else ""
            score_display = f"{effective_score}/{total_marks_sq}" if effective_score is not None else "—"

            st.markdown(f"""
            <div style='background:rgba(1,5,14,0.88);border:1px solid rgba(201,164,92,0.28);
                 border-left:3px solid {status_color};border-radius:4px;
                 padding:14px 18px 10px 18px;margin-bottom:6px;'>
                <div style='display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;'>
                    <div>
                        <span style='font-family:Cinzel,serif;font-size:12px;font-weight:700;
                              color:#ffffff;letter-spacing:.12em;'>{student_id}{flag_icon}</span>
                        <span style='font-family:Rajdhani,sans-serif;font-size:12px;
                              color:rgba(201,164,92,.55);margin-left:14px;'>
                            Submitted: {submitted_at} &nbsp;·&nbsp; File: {file_name}
                            {(" &nbsp;·&nbsp; Remarks: " + remarks) if remarks else ""}
                        </span>
                    </div>
                    <div style='font-family:Orbitron,sans-serif;font-size:16px;
                         color:{status_color};font-weight:700;'>
                        {score_display}
                        <span style='font-family:Cinzel,serif;font-size:9px;
                              letter-spacing:.1em;color:{status_color};
                              opacity:.7;text-transform:uppercase;margin-left:6px;'>{status or "submitted"}</span>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            exp_key = f"exp_{sub_id}"
            with st.expander(f"Grade submission — {student_id}", expanded=False):

                # ── Download cadet file ────────────────────────────────────────
                if file_data:
                    ext = file_name.split(".")[-1].lower() if file_name else "bin"
                    mime_map = {"pdf":"application/pdf","png":"image/png",
                                "jpg":"image/jpeg","jpeg":"image/jpeg",
                                "docx":"application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                "zip":"application/zip"}
                    dl_mime = mime_map.get(ext, "application/octet-stream")
                    st.download_button(
                        label=f"📥 Download {file_name}",
                        data=bytes(file_data),
                        file_name=file_name,
                        mime=dl_mime,
                        key=f"dl_sub_{sub_id}",
                        use_container_width=True
                    )

                # ── AI grading ─────────────────────────────────────────────────
                VISION_MODELS_SQ = ["llama3.2-vision","llava","moondream",
                                    "bakllava","llava-llama3","minicpm-v","gemma3"]

                def _detect_vm():
                    try:
                        from ollama import Client
                        from httpx import Timeout
                        client = Client(host="http://127.0.0.1:11434", timeout=Timeout(10.0))
                        names = [m["name"] for m in client.list().get("models",[])]
                        for n in names:
                            for vm in VISION_MODELS_SQ:
                                if vm in n.lower(): return n
                    except Exception:
                        pass
                    return None

                vm = _detect_vm()

                ai_col, manual_col = st.columns(2, gap="large")

                with ai_col:
                    st.markdown('<p style="font-family:Cinzel,serif;font-size:10px;'
                                'letter-spacing:.12em;color:rgba(201,164,92,.75);'
                                'text-transform:uppercase;margin-bottom:6px;">AI Grade</p>',
                                unsafe_allow_html=True)

                    ai_ctx = st.text_input(
                        "Answer key / context for AI (optional)",
                        placeholder="Paste expected answer or key points…",
                        key=f"ai_ctx_{sub_id}"
                    )

                    ai_grade_btn = st.button(
                        "🤖 Grade with AI",
                        key=f"ai_grade_{sub_id}",
                        disabled=(not vm or not file_data),
                        use_container_width=True
                    )

                    if ai_grade_btn and vm and file_data:
                        is_image = file_name.lower().endswith((".png",".jpg",".jpeg"))
                        if not is_image:
                            st.warning("AI vision grading requires an image file (PNG/JPG). "
                                       "For PDF submissions, download and evaluate manually.")
                        else:
                            import base64 as _b64sq
                            img_b64  = _b64sq.b64encode(bytes(file_data)).decode()
                            img_mime = "image/jpeg" if file_name.lower().endswith((".jpg",".jpeg")) else "image/png"
                            key_ctx  = f"\n\nAnswer key / context:\n{ai_ctx}" if ai_ctx.strip() else ""
                            prompt   = (
                                f"You are an experienced naval academy instructor.\n"
                                f"Total marks: {total_marks_sq}.{key_ctx}\n\n"
                                f"Evaluate the cadet's handwritten answer from the image.\n"
                                f"Respond with exactly:\n"
                                f"SCORE: X / {total_marks_sq}\n"
                                f"STRENGTHS: ...\n"
                                f"WEAKNESSES: ...\n"
                                f"SUGGESTIONS: ...\n"
                                f"OVERALL REMARKS: ..."
                            )
                            with st.spinner(f"Grading with {vm}…"):
                                try:
                                    from ollama import Client
                                    from httpx import Timeout
                                    client = Client(host="http://127.0.0.1:11434",
                                                    timeout=Timeout(120.0))
                                    resp = client.chat(
                                        model=vm,
                                        messages=[{"role":"user","content":[
                                            {"type":"text","text":prompt},
                                            {"type":"image_url","image_url":
                                             {"url":f"data:{img_mime};base64,{img_b64}"}}
                                        ]}],
                                        stream=False, keep_alive=-1,
                                        options={"temperature":0.1,"num_ctx":4096}
                                    )
                                    ai_text = resp["message"]["content"].strip()
                                    score_m = _re.search(
                                        r'SCORE[:\s]+(\d+(?:\.\d+)?)\s*/\s*\d+',
                                        ai_text, _re.IGNORECASE)
                                    ai_num = float(score_m.group(1)) if score_m else None
                                    low_score = ai_num is not None and ai_num < (total_marks_sq * 0.4)
                                    con2 = _sq2.connect(DB_PATH_SUB)
                                    con2.execute("""
                                        UPDATE submissions
                                        SET ai_score=?, ai_feedback=?, status='graded',
                                            flagged=?
                                        WHERE id=?
                                    """, (ai_num, ai_text, 1 if low_score else 0, sub_id))
                                    con2.commit(); con2.close()
                                    st.success(f"AI grade saved: {ai_num}/{total_marks_sq}")
                                    if low_score:
                                        st.warning("Low score — submission flagged for review.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"AI grading failed: {e}")

                    if ai_feedback:
                        with st.expander("AI Feedback", expanded=False):
                            st.text(ai_feedback)

                # ── Manual score override ──────────────────────────────────────
                with manual_col:
                    st.markdown('<p style="font-family:Cinzel,serif;font-size:10px;'
                                'letter-spacing:.12em;color:rgba(201,164,92,.75);'
                                'text-transform:uppercase;margin-bottom:6px;">'
                                'Manual Score Override</p>',
                                unsafe_allow_html=True)

                    default_manual = float(manual_score) if manual_score is not None else (
                                     float(ai_score)     if ai_score     is not None else 0.0)

                    new_manual = st.number_input(
                        f"Score (max {total_marks_sq})",
                        min_value=0.0, max_value=float(total_marks_sq),
                        value=default_manual, step=0.5,
                        key=f"man_{sub_id}"
                    )

                    flag_val = bool(flagged)
                    new_flag = st.checkbox("Flag for review", value=flag_val, key=f"flg_{sub_id}")

                    if st.button("💾 Save Score", key=f"save_{sub_id}", use_container_width=True):
                        con2 = _sq2.connect(DB_PATH_SUB)
                        con2.execute("""
                            UPDATE submissions
                            SET manual_score=?, status='graded', flagged=?
                            WHERE id=?
                        """, (new_manual, 1 if new_flag else 0, sub_id))
                        con2.commit(); con2.close()
                        st.success("Score saved.")
                        st.rerun()
