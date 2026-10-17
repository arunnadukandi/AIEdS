import streamlit as st
import json
import re
import random
import os
import base64
import time
import sqlite3
import sys

# ── Configuration ────────────────────────────
BASE_DIR       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUIZ_BANK_PATH = os.path.join(BASE_DIR, "quiz_bank.json")
BG_IMAGE_PATH  = os.path.join(BASE_DIR, "mainpage.jpeg")
DB_PATH        = os.path.join(BASE_DIR, "sahayak.db")
sys.path.insert(0, BASE_DIR)
from theme import inject_theme_polish


# ── Mastery persistence helpers ───────────────
def load_mastery(user_id, term, subject):
    """Load persisted DI and mastery score for this user+term+subject.
    Returns (current_di, mastery_score). Defaults: (0.1, 0.0) if no record."""
    try:
        con = sqlite3.connect(DB_PATH, timeout=5)
        row = con.execute(
            "SELECT current_di, last_score FROM mastery "
            "WHERE user_id=? AND term=? AND subject=?",
            (user_id, term, subject)
        ).fetchone()
        con.close()
        if row:
            return float(row[0]), float(row[1]) if row[1] is not None else 0.0
    except Exception:
        pass
    return 0.1, 0.0


def save_mastery(user_id, term, subject, current_di, questions_delta, new_mastery_score):
    """UPSERT mastery row. Increments questions_done and sessions_done by session totals."""
    try:
        con = sqlite3.connect(DB_PATH, timeout=5)
        con.execute("""
            INSERT INTO mastery
                (user_id, term, subject, current_di, questions_done, sessions_done, last_score)
            VALUES (?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT(user_id, term, subject) DO UPDATE SET
                current_di     = excluded.current_di,
                questions_done = mastery.questions_done + excluded.questions_done,
                sessions_done  = mastery.sessions_done + 1,
                last_score     = excluded.last_score,
                last_updated   = datetime('now')
        """, (user_id, term, subject, current_di, questions_delta, new_mastery_score))
        con.commit()
        con.close()
    except Exception:
        pass  # Shadow copy is read-only; silently skips on dev machine


def _nk(s):
    """Normalise a name for matching: any run of non-alphanumeric characters
    (dots, hyphens, whitespace, underscores, ...) → a single underscore,
    lowercase. Collapsing underscores too matters: a FAISS stem with an
    underscore sitting right next to a hyphen would otherwise leave a stray
    double underscore that breaks matching against the same name normalised
    elsewhere."""
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def _matching_subject_keys(bank, match_norm):
    """Every distinct subject_key in `bank` (already term-scoped) that belongs
    to the subject named by match_norm (a value already run through _nk()).

    Three strategies, because quiz_bank.json is inconsistent about how
    subject_key relates to the subject name:
      1. subject_key normalises to exactly match_norm.
      2. subject_key starts with match_norm (e.g. "embedded_systems_lyla_das"
         starts with "embedded_systems").
      3. The curated "subject" field matches instead — some entries' subject_key
         is just a book-title stem unrelated to the subject name at all (e.g.
         subject "Electromagnetic Waves" / subject_key
         "elements-of-electromagnetics-sadiku"), so subject_key alone can never
         match those; compare match_norm against the normalised subject field
         too (either direction, since "subject" is usually clean but
         occasionally more specific than the cadet-facing display name).
    """
    matched = set()
    for q in bank:
        subj = q.get("subject", "")
        subj_key = q.get("subject_key", "")
        if not subj or not subj_key:
            continue
        sk_norm = _nk(subj_key)
        subj_norm = _nk(subj)
        if sk_norm == match_norm or (sk_norm and sk_norm.startswith(match_norm)):
            matched.add(subj_key)
        elif subj_norm and (subj_norm == match_norm
                             or subj_norm.startswith(match_norm)
                             or match_norm.startswith(subj_norm)):
            matched.add(subj_key)
    return matched


def _base_chapter(raw: str) -> str:
    """Collapse a raw quiz_bank.json "chapter" tag down to its chapter title,
    stripping the page/section reference and any finer subsection so cadets
    pick one entry per real textbook chapter instead of one per page.

    quiz_bank.json's "chapter" field isn't consistently formatted across
    books' generation scripts, so this has to handle a few shapes:
      - "Built-in Exceptions (p. 162)"                         -> "Built-in Exceptions"
      - "Statements and Syntax – The def Statement (p. 82)"    -> "Statements and Syntax"
      - "Ch 1 - Introduction to Embedded Systems (p.1, Sec 1.2)" -> "Ch 1 - Introduction to Embedded Systems"
      - "Chapter 10"                                            -> "Chapter 10" (no page ref to strip)

    The trailing "(...)" page/section reference is always stripped. A further
    " – subsection" or " - subsection" split is applied only when the string
    does NOT start with "Ch <N>" — that dash is structural there (separating
    the chapter number from its title), not a subsection separator, so
    splitting on it would wrongly truncate "Ch 1 - Introduction to Embedded
    Systems" down to just "Ch 1".
    """
    s = re.sub(r"\s*\([^)]*\d[^)]*\)\s*$", "", raw).strip()
    if not re.match(r"^ch\.?\s*\d+\b", s, re.IGNORECASE):
        s = re.split(r"\s[–—�]\s|\s-\s", s, maxsplit=1)[0].strip()
    return s or raw.strip()


def _page_ref(raw_chapter: str) -> str:
    """Extract just the page/section reference from a raw quiz_bank.json
    "chapter" tag, e.g. "Built-in Exceptions (p. 162)" -> "p. 162", or
    "Ch 1 - Introduction to Embedded Systems (p.1, Sec 1.2)" -> "p.1, Sec 1.2".
    Shown next to each question (not in the chapter picker) so a cadet can
    look up exactly where in the textbook to study further."""
    m = re.search(r"\(([^)]*\d[^)]*)\)\s*$", raw_chapter or "")
    return m.group(1).strip() if m else ""


def _chapter_sort_key(chapter: str):
    """Sort chapters in reading order (Ch 1, Ch 2, ... Ch 10) instead of
    plain alphabetical (which would put "Ch 10" before "Ch 2")."""
    m = re.match(r"^ch(?:apter)?\.?\s*(\d+)", chapter, re.IGNORECASE)
    return (0, int(m.group(1)), chapter) if m else (1, 0, chapter)


def get_dynamic_chapters(selected_subject):
    """
    Return the distinct textbook chapter tags (quiz_bank.json's "chapter"
    field) available for the cadet's selected subject, so cadets pick an
    actual chapter rather than just a book. See _matching_subject_keys() for
    how subject_key/subject matching works.

    FAISS gate: only subjects whose book is indexed (a *.faiss.index file exists
    for this subject in the term's user_profiles folder) are returned, so the
    quiz chapter list only appears once the instructor has indexed the book.
    """
    if not os.path.exists(QUIZ_BANK_PATH):
        return []
    if not selected_subject or selected_subject == "—":
        return []

    selected_term = st.session_state.get("selected_term", "").strip()  # e.g. "Term_3"

    # Derive the match key from the human-readable display name stored by student.py.
    # Fall back to selected_subject (FAISS stem) if display name not yet in session.
    display_name = st.session_state.get("selected_subject_display", "") or selected_subject
    match_norm   = _nk(display_name)   # e.g. "embedded_systems"

    # ── FAISS gate: only proceed if a FAISS index exists for this subject ──────
    user_profiles_dir = os.path.join(BASE_DIR, "user_profiles")
    term_dir = os.path.join(user_profiles_dir, selected_term) if selected_term else None
    if term_dir and os.path.isdir(term_dir):
        # Accept a FAISS file if the subject match_norm is a leading prefix of
        # the normalised filename (handles "{subject}_{pdfname}_faiss.index").
        faiss_match = any(
            _nk(f).startswith(match_norm)
            for f in os.listdir(term_dir) if f.endswith("_faiss.index")
        )
        if not faiss_match:
            return []   # Book not indexed yet → no quiz available
    else:
        # user_profiles dir or term dir missing → no books indexed at all
        return []

    try:
        with open(QUIZ_BANK_PATH, "r", encoding="utf-8") as f:
            bank = json.load(f)

        # Scope to the cadet's current term
        if selected_term:
            bank = [q for q in bank
                    if q.get("term", "").strip() == selected_term]

        matched_keys = _matching_subject_keys(bank, match_norm)
        if not matched_keys:
            return []

        # Dedupe down to one entry per real textbook chapter (_base_chapter
        # strips the page/section reference and any page-level subsection),
        # sorted in reading order rather than alphabetically.
        chapters = sorted(
            {_base_chapter(q.get("chapter", "").strip())
             for q in bank
             if q.get("subject_key", "") in matched_keys and q.get("chapter", "").strip()},
            key=_chapter_sort_key
        )
        return chapters
    except Exception as e:
        st.error(f"Error reading quiz bank: {e}")
        return []


def clean_display_name(name: str) -> str:
    """
    Cleans a chapter/subject name for display.
    - Replaces underscores with spaces, title-cases
    - Removes consecutive duplicate words
      e.g. "Computer Programming Programming In Python" -> "Computer Programming In Python"
    """
    name = name.replace("_", " ").strip().title()
    words = name.split()
    deduped = [words[0]] if words else []
    for w in words[1:]:
        if w.lower() != deduped[-1].lower():
            deduped.append(w)
    return " ".join(deduped)


# ── Page config ───────────────────────────────
st.set_page_config(page_title="IEAS - Adaptive Quiz", layout="centered")

# ── Styles ────────────────────────────────────
def apply_styles(image_path):
    bg_css = ""
    if os.path.exists(image_path):
        with open(image_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode()
        ext  = image_path.rsplit(".", 1)[-1].lower()
        mime = "image/jpeg" if ext in ("jpg","jpeg") else f"image/{ext}"
        bg_css = f'.stApp {{ background-image: url("data:{mime};base64,{encoded}"); background-size: cover; background-position: center; background-attachment: fixed; }}'

    st.markdown(f"""<style>
    {bg_css}
    [data-testid="stSidebar"], [data-testid="collapsedControl"] {{ display: none !important; }}
    .stApp::before {{ content:""; position:fixed; inset:0; background:rgba(0,0,0,0.58); z-index:0; }}
    section[data-testid="stMain"] > div {{ position:relative; z-index:1; }}

    .page-header {{
        background: rgba(10,30,60,0.90); border-radius:12px;
        padding:18px 28px; margin-bottom:20px;
    }}
    .page-header h1 {{ color:#ffffff !important; margin:0; font-size:1.55rem; }}
    .page-header .meta {{ color:#b8d4ff !important; font-size:0.82rem; margin-top:5px; }}

    /* Chatbot-mode banner */
    .chatbot-mode-banner {{
        background:linear-gradient(135deg,rgba(20,50,100,0.92),rgba(10,30,60,0.95));
        border:1px solid rgba(201,164,92,0.50);
        border-radius:12px; padding:14px 20px; margin-bottom:16px;
        display:flex; align-items:center; gap:12px;
    }}
    .chatbot-mode-banner .cmb-icon {{ font-size:26px; }}
    .chatbot-mode-banner .cmb-text h4 {{
        margin:0 0 3px 0; color:#e8c87a !important;
        font-size:0.95rem; font-weight:700; letter-spacing:0.05em;
    }}
    .chatbot-mode-banner .cmb-text p {{
        margin:0; color:rgba(240,228,200,0.70) !important; font-size:0.82rem;
    }}

    .card {{
        background:#ffffff; border-radius:12px;
        padding:24px 28px; margin-bottom:14px;
        box-shadow:0 4px 20px rgba(0,0,0,0.22);
    }}
    .card h2, .card h3, .card p {{ color:#111111 !important; }}

    .chapter-row {{
        background:#f5f7fb; border-radius:10px; padding:14px 18px;
        margin-bottom:4px; border-left:4px solid #1a56db;
    }}
    .chapter-row h4 {{ margin:0 0 3px 0; color:#1a1a2e !important; font-size:1rem; }}
    .chapter-row p  {{ margin:0; color:#555 !important; font-size:0.87rem; }}

    .q-text {{
        background:#eef2ff; border-left:5px solid #1a56db; border-radius:8px;
        padding:14px 18px; margin-bottom:16px;
        color:#111 !important; font-size:1.05rem; font-weight:500;
    }}
    .q-ref {{
        color:#4b5563 !important; font-size:0.8rem; font-style:italic;
        margin:-10px 0 16px 4px;
    }}

    .badge-correct {{ background:#dcfce7; border-left:5px solid #16a34a; border-radius:8px; padding:12px 18px; color:#14532d !important; font-weight:600; margin-bottom:10px; }}
    .badge-wrong   {{ background:#fee2e2; border-left:5px solid #dc2626; border-radius:8px; padding:12px 18px; color:#7f1d1d !important; font-weight:600; margin-bottom:10px; }}
    .badge-answer  {{ background:#fef9c3; border-left:5px solid #ca8a04; border-radius:8px; padding:12px 18px; color:#713f12 !important; margin-bottom:10px; }}
    .badge-explain {{ background:#f0f9ff; border-left:5px solid #0284c7; border-radius:8px; padding:12px 18px; color:#0c4a6e !important; margin-bottom:10px; }}

    /* Generating spinner */
    .gen-spinner {{
        background:#ffffff; border-radius:12px;
        padding:22px 26px; margin-bottom:14px;
        box-shadow:0 4px 20px rgba(0,0,0,0.18);
        text-align:center;
    }}
    .gen-spinner p {{ color:#333 !important; font-size:0.95rem; }}

    div[data-testid="stForm"] {{
        background:#ffffff !important; border-radius:12px;
        padding:20px 24px !important; box-shadow:0 4px 20px rgba(0,0,0,0.22);
    }}

    /* ── Button visibility fix ── */
    .stButton > button, .stFormSubmitButton > button {{
        background: linear-gradient(135deg, #1a3a6e 0%, #1a56db 100%) !important;
        color: #ffffff !important;
        border: 1px solid rgba(79,130,220,0.6) !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
        font-size: 0.95rem !important;
        padding: 10px 18px !important;
        width: 100% !important;
        transition: all 0.2s ease !important;
        box-shadow: 0 4px 14px rgba(26,86,219,0.35) !important;
    }}
    .stButton > button:hover, .stFormSubmitButton > button:hover {{
        background: linear-gradient(135deg, #1e4a8a 0%, #2563eb 100%) !important;
        box-shadow: 0 6px 20px rgba(26,86,219,0.50) !important;
        transform: translateY(-1px) !important;
    }}
    div[data-testid="stRadio"] > label,
    div[data-testid="stRadio"] span,
    div[data-testid="stRadio"] p,
    div[data-testid="stForm"] div[data-testid="stMarkdownContainer"] p,
    .stRadio label {{ color:#111111 !important; }}
    /* ── Widgets that sit directly on the dark page background (outside the
       white .card/.stForm) need light text — otherwise Streamlit's default
       dark label color disappears against the dark overlay. The chapter
       picker selectbox is the only one on this page, so this can be scoped
       broadly without affecting the (correctly dark-on-white) form/radio text
       above, which is deliberately scoped to div[data-testid="stForm"] only. ── */
    div[data-testid="stSelectbox"] label,
    div[data-testid="stSelectbox"] label p {{ color:#f5f5f5 !important; }}
    div[data-testid="stRadio"] div[data-testid="stVerticalBlock"] > div {{
        background:#f5f7fb; border-radius:8px; padding:6px 10px; margin-bottom:6px;
    }}
    div[data-testid="stRadio"] > div > label > div > p {{ color:#111 !important; font-weight:600; font-size:0.95rem; }}

    .score-box {{
        background:#ffffff; border-radius:12px; padding:28px;
        text-align:center; box-shadow:0 4px 20px rgba(0,0,0,0.22); margin-bottom:14px;
    }}
    .score-box h2      {{ color:#1a1a2e !important; margin-bottom:6px; }}
    .score-box .s-num  {{ font-size:3rem; font-weight:800; color:#1a56db !important; line-height:1.1; }}
    .score-box .s-msg  {{ color:#333 !important; font-size:1.05rem; margin-top:10px; }}
    .score-box .s-sub  {{ color:#555 !important; font-size:0.9rem; margin-top:4px; }}

    .review-header {{
        background:rgba(10,30,60,0.88); border-radius:10px;
        padding:14px 20px; margin:20px 0 12px 0;
    }}
    .review-header h3 {{ color:#ffffff !important; margin:0; font-size:1.1rem; }}

    .review-item {{
        background:#ffffff; border-radius:10px; padding:16px 20px;
        margin-bottom:10px; box-shadow:0 2px 10px rgba(0,0,0,0.15);
        border-left:5px solid #ccc;
    }}
    .review-item.correct {{ border-left-color:#16a34a; }}
    .review-item.wrong   {{ border-left-color:#dc2626; }}

    .review-item .ri-num   {{ font-size:0.78rem; font-weight:700; color:#888 !important; text-transform:uppercase; margin-bottom:4px; }}
    .review-item .ri-q     {{ font-size:0.97rem; font-weight:600; color:#1a1a2e !important; margin-bottom:8px; }}
    .review-item .ri-your  {{ font-size:0.88rem; padding:5px 10px; border-radius:5px; display:inline-block; margin-bottom:5px; }}
    .review-item .your-ok  {{ background:#dcfce7; color:#14532d !important; font-weight:600; }}
    .review-item .your-bad {{ background:#fee2e2; color:#7f1d1d !important; font-weight:600; }}
    .review-item .ri-ans   {{ font-size:0.88rem; padding:5px 10px; border-radius:5px; display:inline-block; background:#fef9c3; color:#713f12 !important; }}
    </style>""", unsafe_allow_html=True)


apply_styles(BG_IMAGE_PATH)
inject_theme_polish()

# ── Guard ─────────────────────────────────────
if "selected_subject" not in st.session_state:
    st.markdown('<div class="card"><h3>No subject selected.</h3></div>', unsafe_allow_html=True)
    if st.button("Go to Dashboard"):
        st.switch_page("pages/student.py")
    st.stop()

# ── Detect mode ───────────────────────────────
CHATBOT_MODE = st.session_state.get("chatbot_quiz_mode", False)

# ── Session init ──────────────────────────────
if "quiz_step"              not in st.session_state: st.session_state.quiz_step              = 0
if "quiz_chapter"           not in st.session_state: st.session_state.quiz_chapter           = None
if "current_di"             not in st.session_state: st.session_state.current_di             = 0.1
if "mastery_score_at_start" not in st.session_state: st.session_state.mastery_score_at_start = 0.0
if "score"                  not in st.session_state: st.session_state.score                  = 0
if "history"          not in st.session_state: st.session_state.history          = []
if "show_explanation" not in st.session_state: st.session_state.show_explanation = False
if "current_question" not in st.session_state: st.session_state.current_question = None
if "quiz_log"         not in st.session_state: st.session_state.quiz_log         = []

# Chatbot-mode specific
if "cb_generated_qs"  not in st.session_state: st.session_state.cb_generated_qs  = []  # list of generated MCQ dicts
if "cb_q_index"       not in st.session_state: st.session_state.cb_q_index       = 0   # current question pointer

if st.session_state.quiz_chapter is None and st.session_state.quiz_step > 0 and not CHATBOT_MODE:
    st.session_state.quiz_step = 0

# ── Helpers ───────────────────────────────────
def get_adaptive_question(chapter_value, current_di):
    """chapter_value is either "ALL" (every question across the cadet's
    matched subject, for this term) or one exact quiz_bank.json "chapter" tag
    (as returned by get_dynamic_chapters), picked by the cadet at step 0."""
    if not os.path.exists(QUIZ_BANK_PATH):
        st.error(f"Quiz bank not found: {QUIZ_BANK_PATH}")
        return None
    try:
        with open(QUIZ_BANK_PATH, "r", encoding="utf-8") as f:
            bank = json.load(f)
    except Exception as e:
        st.error(f"Error loading quiz bank: {e}")
        return None

    selected_term = st.session_state.get("selected_term", "").strip()
    if selected_term:
        bank = [q for q in bank if q.get("term", "").strip() == selected_term]

    if chapter_value == "ALL":
        display_name = (st.session_state.get("selected_subject_display", "")
                         or st.session_state.get("selected_subject", ""))
        matched_keys = _matching_subject_keys(bank, _nk(display_name))
        eligible = [q for q in bank
                    if q.get("subject_key", "") in matched_keys
                    and q["id"] not in st.session_state.history]
    else:
        eligible = [q for q in bank
                    if _base_chapter(q.get("chapter", "").strip()) == chapter_value.strip()
                    and q["id"] not in st.session_state.history]
    if not eligible:
        return None
    random.shuffle(eligible)
    eligible.sort(key=lambda x: abs(x.get("di", x.get("difficulty", 0.5)) - current_di))
    return eligible[0]


def reset_to_chapter_select():
    for k in ["quiz_step","current_di","mastery_score_at_start","score","history","quiz_log",
              "show_explanation","current_question","user_ans","is_correct","quiz_chapter",
              "cb_generated_qs","cb_q_index"]:
        st.session_state.pop(k, None)


def render_header(meta=""):
    meta_html = f'<div class="meta">{meta}</div>' if meta else ""
    st.markdown(f'<div class="page-header"><h1>IMPROVE YOUR KNOWLEDGE</h1>{meta_html}</div>',
                unsafe_allow_html=True)


# ── LLM question generator for chatbot mode ───
def _generate_one_question(client, ctx: str, subject: str, q_index: int, di: float, already_asked=None) -> dict | None:
    """Generate a single MCQ. Called by the streaming generator."""
    asked_str = ""
    if already_asked:
        asked_str = "Do NOT repeat these:\n" + "\n".join(f"- {t}" for t in already_asked[-4:]) + "\n\n"
    prompt = (
        f"Text: {ctx}\n\n"
        f"{asked_str}"
        f"Write ONE unique MCQ (question number {q_index+1}) about \"{subject}\". "
        f"Reply with JSON only:\n"
        '{' + f'"text":"?","options":["A) a","B) b","C) c","D) d"],'
        '"answer":"A) a","explanation":"reason"' + '}'
    )
    try:
        resp = client.chat(
            model="llama3.2:3b-instruct-q4_K_M",
            messages=[{"role": "user", "content": prompt}],
            stream=False,
            keep_alive=-1,
            options={"num_gpu": 50, "temperature": 0.7, "num_ctx": 1024}
        )
        raw = resp["message"]["content"].strip()
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$",        "", raw).strip()
        s = raw.find("{");  e = raw.rfind("}") + 1
        if s == -1 or e == 0:
            return None
        q = json.loads(raw[s:e])
        if not all(k in q for k in ("text", "options", "answer")):
            return None
        if len(q.get("options", [])) != 4:
            return None
        q["id"]          = f"cq_{q_index+1}"
        q["di"]          = di
        q["explanation"] = q.get("explanation", "")
        return q
    except Exception:
        return None


def _start_background_generation(ctx: str, subject: str, total: int = 5):
    """
    Launch a background thread that generates questions one-by-one
    and appends them to st.session_state.cb_generated_qs as they finish.
    Uses a thread-safe list to avoid Streamlit session state race conditions.
    """
    import threading
    from ollama import Client
    from httpx import Timeout

    difficulties = [0.2, 0.4, 0.5, 0.7, 0.9]
    start_index  = len(st.session_state.cb_generated_qs)

    if start_index >= total:
        return  # already have all questions

    # Snapshot existing questions into a plain list (thread-safe, no session state access)
    existing_snapshot = list(st.session_state.cb_generated_qs)
    # Use a shared list that both thread and main thread can access safely
    shared_q_list = st.session_state.cb_generated_qs

    def _worker():
        try:
            client = Client(host="http://127.0.0.1:11434", timeout=Timeout(45.0))
        except Exception:
            return
        used_texts = {q["text"].strip() for q in existing_snapshot}
        # Use more context for better quality questions (up to 1200 chars)
        ctx_for_bg = ctx[:1200].strip()
        for i in range(start_index, total):
            di = difficulties[i % len(difficulties)]
            q  = _generate_one_question(client, ctx_for_bg, subject, i, di)
            if q and q["text"].strip() not in used_texts:
                used_texts.add(q["text"].strip())
                try:
                    shared_q_list.append(q)
                except Exception:
                    pass  # session expired, silently stop

    t = threading.Thread(target=_worker, daemon=True)
    t.start()


def _get_cb_question(current_di: float) -> dict | None:
    """Pick the next unused question from the pre-ranked pool.

    The pool (cb_generated_qs) is already sorted by semantic similarity
    to the cadet's session topics by _launch_chatbot_quiz() in chatbot.py.
    Here we simply respect that order and additionally prefer the question
    whose difficulty index is closest to the cadet's current performance.
    """
    used_ids = set(st.session_state.history)
    pool = [q for q in st.session_state.cb_generated_qs if q["id"] not in used_ids]
    if not pool:
        return None
    # Sort by difficulty proximity only — semantic ordering was already done upstream
    pool.sort(key=lambda x: abs(x["di"] - current_di))
    return pool[0]


# ══════════════════════════════════════════════
#  CHATBOT QUIZ MODE  (entered from chatbot.py)
# ══════════════════════════════════════════════
if CHATBOT_MODE:
    cb_subject = st.session_state.get("chatbot_quiz_subject", st.session_state.get("selected_subject", ""))
    cb_context = st.session_state.get("chatbot_quiz_context", "")
    cb_topics  = st.session_state.get("chatbot_quiz_topics",  [])
    need_ai    = st.session_state.get("chatbot_quiz_need_ai", 5)
    CB_TOTAL   = 5

    # ── Banner ────────────────────────────────────────────────────────────────
    # Extract the key noun/concept from each topic (skip common question words)
    _stop_words = {
        "what","is","are","a","an","the","of","to","in","for","and","or","it",
        "on","by","be","was","can","with","that","this","which","how","does","do",
        "give","line","answer","explain","define","describe","tell","me","us","about",
        "brief","short","long","detail","detailed","simple","example","5","3","2","1",
        "write","list","state","why","when","where","who","difference","between","vs",
    }
    def _extract_topic_keyword(topic_str: str) -> str:
        words = re.findall(r"[a-zA-Z]+", topic_str.lower())
        keywords = [w for w in words if len(w) > 3 and w not in _stop_words]
        if keywords:
            return " ".join(w.title() for w in keywords[:2])
        return topic_str.strip().title()[:30]

    key_topics = list(dict.fromkeys(_extract_topic_keyword(t) for t in cb_topics))
    topics_preview = ", ".join(key_topics[:4])
    if len(key_topics) > 4:
        topics_preview += f" +{len(key_topics)-4} more"

    st.markdown(f"""
        <div class="chatbot-mode-banner">
            <div class="cmb-icon">💬→🎯</div>
            <div class="cmb-text">
                <h4>Chatbot Session Quiz — {cb_subject}</h4>
                <p>Topics: {topics_preview or "your recent session"}</p>
            </div>
        </div>
    """, unsafe_allow_html=True)

    # ── Guard: no bank questions loaded ──────────────────────────────────────
    if not st.session_state.cb_generated_qs:
        st.warning(
            f"No questions found in the question bank for **{cb_subject}**. "
            "Ask your instructor to upload questions for this subject."
        )
        if st.button("Return to Chatbot", key="cb_no_qs"):
            st.session_state.chatbot_quiz_mode = False
            st.switch_page("pages/chatbot.py")
        st.stop()

    # ── All questions already loaded from bank — ensure quiz state is ready ───
    if st.session_state.quiz_step == 0:
        _uid  = st.session_state.get("user_id")
        _term = st.session_state.get("selected_term", "Term_1")
        _di, _ms = load_mastery(_uid, _term, cb_subject) if _uid else (0.1, 0.0)
        st.session_state.quiz_step              = 1
        st.session_state.current_di             = _di
        st.session_state.mastery_score_at_start = _ms
        st.session_state.score                  = 0
        st.session_state.history          = []
        st.session_state.quiz_log         = []
        st.session_state.show_explanation = False
        st.session_state.current_question = None
        st.rerun()

    # ── Quiz running ──────────────────────────────────────────────────────────
    total_q = len(st.session_state.cb_generated_qs)

    if st.session_state.quiz_step <= total_q:
        render_header(
            f"Subject: <b>{cb_subject}</b> &nbsp;|&nbsp; "
            f"Mode: <b>Chatbot Session Quiz</b> &nbsp;|&nbsp; "
            f"Difficulty: <b>{st.session_state.current_di:.2f}</b>")

        answered = st.session_state.quiz_step - 1
        st.progress(answered / total_q)

        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("Back to Chatbot", key="cb_back_chat", use_container_width=True):
                st.session_state.chatbot_quiz_mode = False
                reset_to_chapter_select()
                st.switch_page("pages/chatbot.py")
        with col_b:
            if st.button("Return to Dashboard", key="cb_back_dash", use_container_width=True):
                st.session_state.chatbot_quiz_mode = False
                reset_to_chapter_select()
                st.switch_page("pages/student.py")

        # Pick current question
        if st.session_state.current_question is None:
            st.session_state.current_question = _get_cb_question(st.session_state.current_di)

        q = st.session_state.current_question

        if q:
            if not st.session_state.show_explanation:
                st.markdown(f"""
                    <div class="card">
                        <h3 style="margin:0 0 6px 0;color:#1a1a2e!important">
                            Question {st.session_state.quiz_step} of {total_q}
                        </h3>
                        <div class="q-text">{q["text"]}</div>
                    </div>""", unsafe_allow_html=True)
                with st.form(key=f"cb_quiz_form_{q['id']}"):
                    ans    = st.radio("Select the correct answer:", q["options"])
                    submit = st.form_submit_button("Submit Answer", use_container_width=True)
                    if submit:
                        correct = ans == q["answer"]
                        st.session_state.user_ans         = ans
                        st.session_state.show_explanation = True
                        st.session_state.history.append(q["id"])
                        st.session_state.is_correct       = correct
                        st.session_state.quiz_log.append({
                            "num":         st.session_state.quiz_step,
                            "text":        q["text"],
                            "options":     q["options"],
                            "answer":      q["answer"],
                            "user":        ans,
                            "correct":     correct,
                            "explanation": q.get("explanation", ""),
                        })
                        if correct:
                            st.session_state.score     += 1
                            st.session_state.current_di = min(1.0, st.session_state.current_di + 0.15)
                        else:
                            st.session_state.current_di = max(0.1, st.session_state.current_di - 0.1)
                        st.rerun()
            else:
                correct_icon = "✅" if st.session_state.is_correct else "❌"
                result_color = "#14532d" if st.session_state.is_correct else "#7f1d1d"
                result_bg    = "#dcfce7" if st.session_state.is_correct else "#fee2e2"
                result_label = "Correct!" if st.session_state.is_correct else "Incorrect."
                answer_row   = "" if st.session_state.is_correct else f"""
                    <div style="background:#fef9c3;border-left:5px solid #ca8a04;border-radius:8px;
                                padding:12px 18px;margin-top:10px;color:#713f12;font-weight:600;">
                        Correct Answer: {q['answer']}
                    </div>"""
                explain_row = ""
                if q.get("explanation"):
                    explain_row = f"""
                    <div style="background:#f0f9ff;border-left:5px solid #0284c7;border-radius:8px;
                                padding:12px 18px;margin-top:10px;color:#0c4a6e;">
                        💡 {q['explanation']}
                    </div>"""
                st.markdown(f"""
                    <div class="card">
                        <h3 style="margin:0 0 6px 0;color:#1a1a2e!important">
                            Result — Question {st.session_state.quiz_step} {correct_icon}
                        </h3>
                        <div class="q-text">{q["text"]}</div>
                        <div style="background:{result_bg};border-left:5px solid {'#16a34a' if st.session_state.is_correct else '#dc2626'};
                                    border-radius:8px;padding:12px 18px;margin-top:10px;
                                    color:{result_color};font-weight:600;">
                            {result_label} &nbsp; Your answer: {st.session_state.user_ans}
                        </div>
                        {answer_row}
                        {explain_row}
                    </div>""", unsafe_allow_html=True)
                is_last = (st.session_state.quiz_step >= total_q)
                next_label = "Submit Quiz ➤" if is_last else "Next Question ➤"
                if st.button(next_label, key=f"cb_next_{q['id']}", use_container_width=True):
                    st.session_state.quiz_step       += 1
                    st.session_state.show_explanation = False
                    st.session_state.current_question = None
                    st.rerun()
        else:
            st.session_state.quiz_step = total_q + 1
            st.rerun()

        st.stop()  # ← prevents normal quiz code from running in chatbot mode

    # ── Chatbot quiz RESULTS (all questions answered) ─────────────────────────
    else:
        render_header(f"Subject: <b>{cb_subject}</b> &nbsp;|&nbsp; Mode: <b>Chatbot Session Quiz</b>")

        total_attempted = len(st.session_state.quiz_log)
        if total_attempted > 0:
            pct         = (st.session_state.score / total_attempted) * 100
            wrong_count = total_attempted - st.session_state.score
            msg = ("Excellent performance!" if pct >= 80
                   else ("Good job! Keep practicing." if pct >= 50
                         else "Keep studying, you will get there!"))
            # ── Persist mastery ──────────────────────────────────────────────
            _uid = st.session_state.get("user_id")
            _term = st.session_state.get("selected_term", "Term_1")
            if _uid and cb_subject:
                _new_ms = (0.6 * (st.session_state.score / total_attempted)
                           + 0.4 * st.session_state.get("mastery_score_at_start", 0.0))
                save_mastery(_uid, _term, cb_subject,
                             st.session_state.current_di, total_attempted, _new_ms)
            # ────────────────────────────────────────────────────────────────
            st.markdown(f"""
                <div class="score-box">
                    <h2>Quiz Completed</h2>
                    <p class="s-sub">Subject: <b>{cb_subject}</b></p>
                    <div class="s-num">{st.session_state.score} / {total_attempted}</div>
                    <div style="display:flex;justify-content:center;gap:30px;margin-top:12px">
                        <span style="color:#16a34a!important;font-weight:700;font-size:1rem">Correct: {st.session_state.score}</span>
                        <span style="color:#dc2626!important;font-weight:700;font-size:1rem">Wrong: {wrong_count}</span>
                    </div>
                    <div class="s-msg">{msg}</div>
                </div>""", unsafe_allow_html=True)
        else:
            st.markdown('<div class="score-box"><h2>Quiz Ended Early</h2>'
                        '<p class="s-msg">No questions were answered.</p></div>',
                        unsafe_allow_html=True)

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Back to Chatbot", use_container_width=True, key="cb_res_chat"):
                st.session_state.chatbot_quiz_mode = False
                reset_to_chapter_select()
                st.switch_page("pages/chatbot.py")
        with col2:
            if st.button("Return to Dashboard", use_container_width=True, key="cb_res_dash"):
                st.session_state.chatbot_quiz_mode = False
                reset_to_chapter_select()
                st.switch_page("pages/student.py")

        # Full question-by-question review
        st.markdown('<div class="review-header"><h3>📋 Question Review</h3></div>',
                    unsafe_allow_html=True)
        for entry in st.session_state.quiz_log:
            status_class = "correct" if entry["correct"] else "wrong"
            status_label = "✅ Correct" if entry["correct"] else "❌ Wrong"
            your_class   = "your-ok"  if entry["correct"] else "your-bad"
            correct_row  = (f'<div style="margin-top:6px">'
                            f'<span class="ri-ans">Correct Answer: {entry["answer"]}</span></div>'
                            if not entry["correct"] else "")
            explain_row  = (f'<div style="margin-top:8px;font-size:0.85rem;color:#0c4a6e!important;'
                            f'background:#f0f9ff;padding:8px 12px;border-radius:6px">'
                            f'💡 {entry["explanation"]}</div>'
                            if entry.get("explanation") else "")
            st.markdown(f"""
                <div class="review-item {status_class}">
                    <div class="ri-num">Q{entry['num']} &mdash; {status_label}</div>
                    <div class="ri-q">{entry['text']}</div>
                    <div><span class="ri-your {your_class}">Your answer: {entry['user']}</span></div>
                    {correct_row}{explain_row}
                </div>""", unsafe_allow_html=True)

        st.stop()  # ← never fall through to normal quiz mode

# ══════════════════════════════════════════════
#  NORMAL QUIZ MODE  (entered from student.py)
# ══════════════════════════════════════════════

# 1. Calculate pool size for exhaustive mode BEFORE the logic starts
if st.session_state.quiz_chapter:
    if not os.path.exists(QUIZ_BANK_PATH):
        st.error("Quiz bank not found.")
        st.stop()
    with open(QUIZ_BANK_PATH, "r", encoding="utf-8") as f:
        bank = json.load(f)
    _term = st.session_state.get("selected_term", "").strip()
    if _term:
        bank = [q for q in bank if q.get("term", "").strip() == _term]
    if st.session_state.quiz_chapter == "ALL":
        _display_name = (st.session_state.get("selected_subject_display", "")
                          or st.session_state.get("selected_subject", ""))
        _matched_keys = _matching_subject_keys(bank, _nk(_display_name))
        total_available = len([q for q in bank if q.get("subject_key", "") in _matched_keys])
    else:
        _ch = st.session_state.quiz_chapter
        total_available = len([q for q in bank if _base_chapter(q.get("chapter", "").strip()) == _ch.strip()])
else:
    total_available = 0

# ── STEP 0 — CHAPTER SELECTION ────────────────
if st.session_state.quiz_step == 0:
    render_header()
    
    # Get the parent subject selected from the dashboard
    # (e.g., "Introduction to Radar" or "Mathematics")
    current_sub = st.session_state.get("selected_subject", "")
    # Use the human-readable display name stored by student.py; fall back to
    # cleaning the FAISS stem only if the display name was not set.
    display_sub = st.session_state.get("selected_subject_display", "") or clean_display_name(current_sub)

    # get_dynamic_chapters returns the distinct quiz_bank.json "chapter" tags
    # available for this subject (see its docstring for the matching rules).
    available_chapters = get_dynamic_chapters(current_sub)

    _count_line = (f"<p style='margin:6px 0 0 0;color:#374151'>"
                   f"{len(available_chapters)} chapter{'s' if len(available_chapters) != 1 else ''} available.</p>"
                   if available_chapters else "")
    st.markdown(f"""
        <div class="card">
            <h2 style="margin:0 0 6px 0">Select a Chapter</h2>
            <p style="margin:0">Available units for: <b>{display_sub}</b></p>
            {_count_line}
        </div>""", unsafe_allow_html=True)

    if not available_chapters:
        # Distinguish between "book not indexed" and "QB not found"
        selected_term = st.session_state.get("selected_term", "")
        user_profiles_dir = os.path.join(BASE_DIR, "user_profiles")
        term_dir = os.path.join(user_profiles_dir, selected_term)
        # Use the subject display name prefix to check subject-specific indexing.
        _sub_display = st.session_state.get("selected_subject_display", "") or display_sub
        _sub_norm    = re.sub(r"[^a-z0-9]+", "_", _sub_display.lower()).strip("_")
        book_indexed = (
            os.path.isdir(term_dir) and
            any(
                f.endswith("_faiss.index") and re.sub(r"[^a-z0-9]+", "_", f.lower()).strip("_").startswith(_sub_norm)
                for f in os.listdir(term_dir)
            )
        )
        if not book_indexed:
            st.warning(f"📚 No textbook has been indexed for **{display_sub}** yet.")
            st.info("An instructor needs to upload the PDF for this subject via the **Instructor panel → Upload PDFs** before the quiz becomes available.")
        else:
            st.warning(f"No quiz questions found for **{display_sub}** in Term {selected_term}.")
            st.info("The textbook is indexed (chatbot is available), but no question bank has been loaded for this subject yet.")
    else:
        ALL_LABEL = "All Chapters (mixed)"
        chapter_choice = st.selectbox(
            "Choose a chapter",
            [ALL_LABEL] + available_chapters,
            key="chapter_picker"
        )

        if st.button("Start Quiz", use_container_width=True):
            chapter_value = "ALL" if chapter_choice == ALL_LABEL else chapter_choice
            _uid  = st.session_state.get("user_id")
            _term = st.session_state.get("selected_term", "Term_1")
            _di, _ms = load_mastery(_uid, _term, chapter_value) if _uid else (0.1, 0.0)
            st.session_state.quiz_chapter           = chapter_value
            st.session_state.quiz_step              = 1
            st.session_state.current_di             = _di
            st.session_state.mastery_score_at_start = _ms
            st.session_state.score                  = 0
            st.session_state.history                = []
            st.session_state.quiz_log               = []
            st.session_state.show_explanation       = False
            st.session_state.current_question       = None
            st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("Return to Dashboard", key="rtd_1", use_container_width=True):
        st.switch_page("pages/student.py")


# ── STEPS 1 to N — ACTIVE QUIZ ────────────────
elif 1 <= st.session_state.quiz_step <= total_available:
    chapter_label = ("All Chapters" if st.session_state.quiz_chapter == "ALL"
                      else st.session_state.quiz_chapter)
    
    render_header(
        f"Subject: <b>{st.session_state.selected_subject}</b> &nbsp;|&nbsp; "
        f"Chapter: <b>{chapter_label}</b> &nbsp;|&nbsp; "
        f"Difficulty: <b>{st.session_state.current_di:.2f}</b>")

    st.progress(min(st.session_state.quiz_step / total_available, 1.0))
    
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("Change Chapter", use_container_width=True):
            reset_to_chapter_select()
            st.rerun()
    with col_b:
        if st.button("Return to Dashboard", key="rtd_2", use_container_width=True):
            reset_to_chapter_select()
            st.switch_page("pages/student.py")

    if st.session_state.current_question is None:
        st.session_state.current_question = get_adaptive_question(
            st.session_state.quiz_chapter, st.session_state.current_di)

    q = st.session_state.current_question

    if q:
        _ref = _page_ref(q.get("chapter", ""))
        if not st.session_state.show_explanation:
            st.markdown(f"""
                <div class="card">
                    <h3 style="margin:0 0 12px 0;color:#1a1a2e!important">Question {st.session_state.quiz_step} of {total_available}</h3>
                    <div class="q-text">{q['text']}</div>
                </div>""", unsafe_allow_html=True)
            if _ref:
                st.markdown(f'<div class="q-ref">📖 Refer: {_ref}</div>', unsafe_allow_html=True)

            with st.form(key=f"quiz_form_{q['id']}"):
                ans = st.radio("Select the correct answer:", q["options"])
                submit = st.form_submit_button("Submit Answer", use_container_width=True)
                if submit:
                    correct = (ans == q["answer"])
                    st.session_state.user_ans         = ans
                    st.session_state.show_explanation = True
                    st.session_state.history.append(q["id"])
                    st.session_state.is_correct       = correct
                    st.session_state.quiz_log.append({
                        "num":     st.session_state.quiz_step,
                        "text":    q["text"],
                        "options": q["options"],
                        "answer":  q["answer"],
                        "user":    ans,
                        "correct": correct,
                        "explanation": q.get("explanation", ""),
                        "chapter": q.get("chapter", ""),
                    })
                    if correct:
                        st.session_state.score     += 1
                        st.session_state.current_di = min(1.0, st.session_state.current_di + 0.15)
                    else:
                        st.session_state.current_di = max(0.1, st.session_state.current_di - 0.1)
                    st.rerun()
            
            if st.button("🏁 End Quiz & View Results", use_container_width=True):
                st.session_state.quiz_step = total_available + 1
                st.rerun()
        else:
            st.markdown(f"""
                <div class="card">
                    <h3 style="margin:0 0 12px 0;color:#1a1a2e!important">Result — Question {st.session_state.quiz_step}</h3>
                    <div class="q-text">{q['text']}</div>
                </div>""", unsafe_allow_html=True)
            if _ref:
                st.markdown(f'<div class="q-ref">📖 Refer: {_ref}</div>', unsafe_allow_html=True)

            if st.session_state.is_correct:
                st.markdown(f'<div class="badge-correct">Correct! Your answer: {st.session_state.user_ans}</div>', unsafe_allow_html=True)
            else:
                st.markdown(
                    f'<div class="badge-wrong">Incorrect. Your answer: {st.session_state.user_ans}</div>'
                    f'<div class="badge-answer">Correct Answer: {q["answer"]}</div>',
                    unsafe_allow_html=True)
            
            if q.get("explanation"):
                st.markdown(f'<div class="badge-explain">Explanation: {q["explanation"]}</div>', unsafe_allow_html=True)

            col_next, col_stop = st.columns(2)
            with col_next:
                if st.button("Next Question", use_container_width=True):
                    st.session_state.quiz_step       += 1
                    st.session_state.show_explanation = False
                    st.session_state.current_question = None
                    st.rerun()
            with col_stop:
                if st.button("Stop & View Results", use_container_width=True):
                    st.session_state.quiz_step = total_available + 1
                    st.rerun()
    else:
        # Fallback if no questions are available
        st.session_state.quiz_step = total_available + 1
        st.rerun()


# ── STEP FINAL — RESULTS ────────────────────────
else:
    chapter_label = ("All Chapters" if st.session_state.quiz_chapter == "ALL"
                      else st.session_state.quiz_chapter)
    render_header()

    total_attempted = len(st.session_state.quiz_log)

    if total_attempted > 0:
        pct = (st.session_state.score / total_attempted) * 100
        msg = ("Excellent performance!" if pct >= 80
               else ("Good job! Keep practicing." if pct >= 50
                     else "Keep studying, you will get there!"))
        wrong_count = total_attempted - st.session_state.score
        # ── Persist mastery ──────────────────────────────────────────────────
        _uid     = st.session_state.get("user_id")
        _term    = st.session_state.get("selected_term", "Term_1")
        _subject = st.session_state.get("quiz_chapter", "")
        if _uid and _subject:
            _new_ms = (0.6 * (st.session_state.score / total_attempted)
                       + 0.4 * st.session_state.get("mastery_score_at_start", 0.0))
            save_mastery(_uid, _term, _subject,
                         st.session_state.current_di, total_attempted, _new_ms)
        # ────────────────────────────────────────────────────────────────────
        st.markdown(f"""
            <div class="score-box">
                <h2>Quiz Completed</h2>
                <p class="s-sub">Chapter: <b>{chapter_label}</b></p>
                <div class="s-num">{st.session_state.score} / {total_attempted}</div>
                <div style="display:flex;justify-content:center;gap:30px;margin-top:12px">
                    <span style="color:#16a34a!important;font-weight:700;font-size:1rem">Correct: {st.session_state.score}</span>
                    <span style="color:#dc2626!important;font-weight:700;font-size:1rem">Wrong: {wrong_count}</span>
                </div>
                <div class="s-msg">{msg}</div>
            </div>""", unsafe_allow_html=True)
    else:
        st.markdown('<div class="score-box"><h2>Quiz Ended Early</h2><p class="s-msg">No questions were answered.</p></div>', unsafe_allow_html=True)

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Retry Same Chapter", use_container_width=True):
            saved = st.session_state.quiz_chapter
            _uid  = st.session_state.get("user_id")
            _term = st.session_state.get("selected_term", "Term_1")
            _di, _ms = load_mastery(_uid, _term, saved) if _uid else (0.1, 0.0)
            reset_to_chapter_select()
            st.session_state.quiz_step              = 1
            st.session_state.quiz_chapter           = saved
            st.session_state.current_di             = _di
            st.session_state.mastery_score_at_start = _ms
            st.session_state.score                  = 0
            st.session_state.history                = []
            st.session_state.quiz_log               = []
            st.rerun()
    with col2:
        if st.button("Change Chapter", use_container_width=True):
            reset_to_chapter_select()
            st.rerun()

    st.markdown('<div class="review-header"><h3>Question Review</h3></div>', unsafe_allow_html=True)

    for entry in st.session_state.quiz_log:
        status_class = "correct" if entry["correct"] else "wrong"
        status_label = "Correct" if entry["correct"] else "Wrong"
        your_class   = "your-ok" if entry["correct"] else "your-bad"
        correct_row  = ""
        if not entry["correct"]:
            correct_row = f'<div style="margin-top:6px"><span class="ri-ans">Correct Answer: {entry["answer"]}</span></div>'
        explain_row = ""
        if entry.get("explanation"):
            explain_row = f'<div style="margin-top:8px;font-size:0.85rem;color:#0c4a6e!important;background:#f0f9ff;padding:8px 12px;border-radius:6px">Explanation: {entry["explanation"]}</div>'
        ref_row = ""
        _ref = _page_ref(entry.get("chapter", ""))
        if _ref:
            ref_row = f'<div class="q-ref" style="margin:4px 0 0 0">📖 Refer: {_ref}</div>'

        st.markdown(f"""
            <div class="review-item {status_class}">
                <div class="ri-num">Q{entry['num']} &mdash; {status_label}</div>
                <div class="ri-q">{entry['text']}</div>
                {ref_row}
                <div><span class="ri-your {your_class}">Your answer: {entry['user']}</span></div>
                {correct_row}
                {explain_row}
            </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("Return to Dashboard", key="rtd_3", use_container_width=True):
        reset_to_chapter_select()
        st.switch_page("pages/student.py")
