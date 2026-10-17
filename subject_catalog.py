"""
subject_catalog.py — single source of truth for "is this subject ready to show
a cadet?" A subject is ready only when BOTH:
  1. A textbook is indexed for it (a *_faiss.index file exists under
     user_profiles/<Term>/), and
  2. The question bank (quiz_bank.json) has at least one question tagged to
     that subject for that same term.

Every student-facing page that lists or selects a subject (student.py's
Subject/Subject Manual dropdowns, and by extension _quiz.py, chatbot.py and
study_materials.py which all consume the subject chosen there) should filter
through get_ready_subjects() so a subject only ever appears once both the
book and its QB are actually usable.

Usage (from pages/*.py):
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from subject_catalog import get_ready_subjects
"""
import os
import re
import json


def _nk(s: str) -> str:
    """Normalise a name for matching: any run of non-alphanumeric characters
    (dots, hyphens, whitespace, underscores, parens, ...) -> a single
    underscore, lowercase. Collapsing underscores too (not just dots/hyphens/
    whitespace) matters: a FAISS stem like "..._-sadiku_matthew" has an
    underscore sitting right next to a hyphen, and normalising only the
    hyphen leaves a stray double underscore that breaks substring matching
    against the same name normalised elsewhere (e.g. from a PDF filename)."""
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")


def _clean_subject(name: str) -> str:
    """Strip trailing author/publisher info from a subject display name and
    normalise separators (mirrors pages/student.py's _clean_subject)."""
    name = name.replace("_", " ")
    name = re.sub(r"\s+[Bb]y\s+.*$", "", name).strip()
    name = re.sub(r"\s+[A-Z][a-z]?\.[A-Za-z\-]+$", "", name).strip()
    return name


def _singular(s: str) -> str:
    """Strip one trailing 's' — tolerates plural/singular drift between a
    curated subject name ("Embedded Systems") and a raw filename that used
    the singular ("embedded-system-...pdf"), or between word forms like
    "electromagnetics" vs "electromagnetic"."""
    return s[:-1] if s.endswith("s") else s


_MATCH_STOPWORDS = {"and", "of", "the", "a", "an", "for", "to", "in", "on", "by", "with"}


def _content_tokens(nk_string: str) -> set:
    """Break an already-_nk()-normalised string into significant tokens for
    fuzzy subject matching: drops connector words and very short fragments,
    and singularises each token so 'electromagnetics' lines up with
    'electromagnetic', 'systems' with 'system', etc."""
    toks = set()
    for t in nk_string.split("_"):
        if not t or t in _MATCH_STOPWORDS or len(t) <= 2:
            continue
        toks.add(_singular(t))
    return toks


def load_quiz_bank(base_dir: str) -> list:
    path = os.path.join(base_dir, "quiz_bank.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return json.load(f)
    except Exception:
        return []


def build_subject_manuals(base_dir: str, term: str) -> dict:
    """{subject_display: [(manual_display, stem), ...]} from indexed FAISS books
    for this term, regardless of QB coverage (i.e. "book available" only)."""
    folder = os.path.join(base_dir, "user_profiles", term)
    subject_manuals: dict = {}
    if not os.path.isdir(folder):
        return subject_manuals
    for f in sorted(os.listdir(folder)):
        if not f.endswith("_faiss.index"):
            continue
        stem = f.replace("_faiss.index", "")
        meta_path = os.path.join(folder, f"{stem}_meta.json")
        if os.path.exists(meta_path):
            try:
                with open(meta_path, encoding="utf-8", errors="replace") as mf:
                    meta = json.load(mf)
            except Exception:
                meta = {}
            subj = _clean_subject(str(meta.get("subject", stem)).strip().title())
            manual = str(meta.get("manual", stem)).strip().replace("_", " ").title()
        else:
            # No _meta.json for this book — best-effort subject/manual split
            # from the filename stem alone. Previously this used only the
            # text before the FIRST underscore as the subject (e.g. just
            # "Elements" from "elements_of_electromagnetics_sadiku"), which
            # is a near-meaningless subject name on its own AND gave
            # has_qb_coverage() only one weak word to match against — a
            # major reason correctly-uploaded books were silently hidden
            # from students. Using the FULL stem keeps every word from the
            # title available, giving the significant-word-overlap fallback
            # in has_qb_coverage() a real chance to link this book to its
            # actual question-bank subject even without a curated
            # _meta.json. (For a clean short display name instead, add a
            # proper _meta.json with a "subject" field for this book.)
            subj = _clean_subject(stem.replace("_", " ").title())
            manual = subj
        subject_manuals.setdefault(subj, []).append((manual, stem))
    return subject_manuals


def qb_subject_keys(base_dir: str, term: str) -> set:
    """Normalised subject_key/subject strings that have >=1 QB question for this term.

    Both fields are indexed because quiz_bank.json is inconsistent: some entries'
    subject_key is prefixed with the subject name (e.g. "embedded-systems-lyla-das"
    for subject "Embedded Systems"), while others use a bare book-title stem
    unrelated to the subject name (e.g. "python-pocket-reference-mark-lutz" for
    subject "Computer Programming"). The curated "subject" field is reliably the
    clean display name, so it is included as a match key too.
    """
    bank = load_quiz_bank(base_dir)
    keys = set()
    for q in bank:
        if q.get("term", "").strip() != term:
            continue
        for field in ("subject", "subject_key"):
            v = q.get(field, "")
            if v:
                keys.add(_nk(v))
    return keys


def has_qb_coverage(qb_keys_norm: set, subject_display: str) -> bool:
    """True if this subject (as derived from the book side) has at least one
    matching entry among the normalised QB subject/subject_key strings.

    Two strategies, because relying on only the first silently hid most
    correctly-uploaded subjects in practice:
      1. Whole-string prefix match (strongest signal) — exact or near-exact
         subject naming between the book side and quiz_bank.json, e.g. a
         curated "subject" field that matches word-for-word, or a
         subject_key/FAISS stem that literally starts with the subject name.
      2. Significant-word overlap, singular-normalised (fallback) — catches
         real-world cases where the two sides describe the same subject with
         different phrasing or word order, e.g. a book indexed as "Antenna
         Theory" against a question bank tagged "Antenna Propagation", or an
         instructor-typed subject that doesn't literally prefix-match
         quiz_bank.json's curated subject string. Requires at least one
         shared *significant* word (connector words and short fragments are
         excluded), so two subjects must genuinely share topical vocabulary,
         not just incidental structure.
    """
    match_norm = _nk(subject_display)
    if not match_norm:
        return False

    if any(k.startswith(match_norm) or match_norm.startswith(k)
           for k in qb_keys_norm if k):
        return True

    subj_tokens = _content_tokens(match_norm)
    if not subj_tokens:
        return False
    for k in qb_keys_norm:
        if k and subj_tokens & _content_tokens(k):
            return True
    return False


def get_ready_subjects(base_dir: str, term: str) -> dict:
    """Subjects with BOTH an indexed textbook AND question-bank coverage for
    this term. Returns {subject_display: [(manual_display, stem), ...]} —
    only subjects that pass both checks are included (all of that subject's
    indexed manuals are kept once the subject itself qualifies)."""
    subject_manuals = build_subject_manuals(base_dir, term)
    qb_keys = qb_subject_keys(base_dir, term)
    return {subj: manuals for subj, manuals in subject_manuals.items()
            if has_qb_coverage(qb_keys, subj)}


def find_term_pdfs(base_dir: str, term: str) -> list:
    """Every PDF file that could plausibly be a study material for this term.

    Two source trees exist on disk and neither alone is complete:
      - login/user_profiles/<Term>/ (+ its study_materials/ subfolder) — where
        an instructor's upload sometimes lands the raw PDF alongside its FAISS
        index, but often does not (only the processed index/doc/meta/cache
        files remain, no raw PDF).
      - <project_root>/data/term_N/**/ — the actual textbook PDF repository
        (books according to syllabus / books not according to syllabus /
        reference material / ...); subfolder names vary in spelling and
        capitalisation across terms, so this is walked recursively.
    Returns a list of (filename, full_path) tuples, deduplicated by filename.
    """
    seen_names = set()
    results = []

    folder = os.path.join(base_dir, "user_profiles", term)
    mat_path = os.path.join(folder, "study_materials")
    for d in (mat_path, folder):
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if f.lower().endswith(".pdf") and f not in seen_names:
                seen_names.add(f)
                results.append((f, os.path.join(d, f)))

    project_root = os.path.dirname(base_dir)
    term_num = re.sub(r"[^0-9]", "", term)
    data_term_dir = os.path.join(project_root, "data", f"term_{term_num}") if term_num else None
    if data_term_dir and os.path.isdir(data_term_dir):
        for root, _dirs, files in os.walk(data_term_dir):
            for f in sorted(files):
                if f.lower().endswith(".pdf") and f not in seen_names:
                    seen_names.add(f)
                    results.append((f, os.path.join(root, f)))

    return results


def pdf_matches_subject(fname: str, subject_display: str, manual_stems_norm: set) -> bool:
    """True if a PDF filename plausibly belongs to a ready subject.

    Two independent strategies, because neither alone covers the real data:
      1. Manual-stem containment: the FAISS stem (subject + instructor-typed
         manual label) appears in the filename or vice versa. Works when the
         instructor's "manual" label roughly matches the real filename.
      2. Subject-name prefix, tolerant of a trailing plural 's': works when
         the manual label is a generic word (e.g. "control systems") that has
         no relation to the real filename, but the filename still leads with
         the subject name (e.g. "automatic-control-systems ...kuo.pdf").
    """
    fn_norm = _nk(os.path.splitext(fname)[0])
    if not fn_norm:
        return False
    if any(fn_norm in s or s in fn_norm for s in manual_stems_norm):
        return True
    subj_norm = _nk(subject_display)
    if not subj_norm:
        return False
    a, b = _singular(subj_norm), _singular(fn_norm)
    return fn_norm.startswith(subj_norm) or a.startswith(b) or b.startswith(a)
