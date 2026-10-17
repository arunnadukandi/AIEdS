"""
pdf_ingest.py — shared PDF -> FAISS indexing for AIEdS (text PDFs AND scanned PDFs).

Used by:
  * pages/instructor.py  (one upload at a time, from the Knowledge Upload tab)
  * reindex_books.py     (batch rebuild of every book already on the server)

Place this file in the AIEdS root folder (same folder as quiz_bank.json / sahayak.db).

Why this exists
---------------
The old indexer called page.get_text() only. Scanned books have no text layer, so
every chunk was just "--- SOURCE ... PAGE n ---" plus an image link. All chunks
looked identical to the embedder, so retrieval returned random pages. This module
runs OCR (Tesseract) on any page without real text.

Server requirements (one time):
    sudo apt install -y tesseract-ocr
    <python that runs streamlit> -m pip install pytesseract pillow

Output files are the SAME format the chatbot already reads:
    {stem}_faiss.index   IndexFlatIP over L2-normalised embeddings
    {stem}_doc.json      {"0": {"text", "page", "subject", "manual", "ocr"}, ...}
    {stem}_meta.json     {"subject", "manual", "stem", + indexing stats}
"""

import io
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

import faiss
import fitz  # PyMuPDF
import numpy as np

INGEST_VERSION = "pdf_ingest-v1"

OCR_DPI        = 300    # 300 dpi is the sweet spot for printed textbooks
OCR_LANG       = "eng"
MIN_TEXT_CHARS = 60     # a page with fewer real characters than this gets OCR
CHUNK_CHARS    = 900    # ~200-230 tokens: fits all-MiniLM-L6-v2's 256-token window
CHUNK_OVERLAP  = 150
MIN_CHUNK_CHARS = 40

# Tesseract is itself multi-threaded; we parallelise across pages instead.
os.environ.setdefault("OMP_THREAD_LIMIT", "1")


# ── Helpers ───────────────────────────────────────────────────────────────────
def tesseract_available():
    """True if pytesseract is installed and the tesseract binary runs."""
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def default_workers():
    return max(1, min(32, (os.cpu_count() or 2) - 2))


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


def clean_text(text):
    """Normalise extracted/OCR text: join hyphenated breaks, unwrap lines, trim noise."""
    if not text:
        return ""
    text = text.replace("\r", "").replace("\x0c", "")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)          # hyphen-\nated -> hyphenated
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)            # unwrap single line breaks
    text = re.sub(r" {2,}", " ", text)
    return universal_cleaner(text.strip())


def _ocr_png(png_bytes):
    """OCR one rendered page. Runs in a worker thread (tesseract is a subprocess)."""
    import pytesseract
    from PIL import Image
    img = Image.open(io.BytesIO(png_bytes))
    return pytesseract.image_to_string(img, lang=OCR_LANG, config="--oem 1 --psm 3")


# ── Step 1: page text (native or OCR) ─────────────────────────────────────────
def extract_pages(pdf_path, workers=None, progress_cb=None, use_ocr=None):
    """Return (pages, stats). pages = [(page_no_1_based, text, ocr_used), ...].

    Rendering happens in the calling thread (PyMuPDF is not thread-safe);
    OCR runs in a thread pool because each call is a separate tesseract process.
    """
    if use_ocr is None:
        use_ocr = tesseract_available()
    workers = workers or default_workers()

    doc = fitz.open(pdf_path)
    n = len(doc)
    results = {}
    pending = {}
    max_in_flight = workers * 2

    def _collect(block=False):
        done = [p for p, f in pending.items() if block or f.done()]
        for p in done:
            fut = pending.pop(p)
            try:
                results[p] = (fut.result(), True)
            except Exception:
                results[p] = ("", True)
            if progress_cb:
                progress_cb(len(results) / max(n, 1))

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for pno in range(n):
                page = doc[pno]
                native = page.get_text("text") or ""
                if len(native.strip()) >= MIN_TEXT_CHARS or not use_ocr:
                    results[pno] = (native, False)
                    if progress_cb:
                        progress_cb(len(results) / max(n, 1))
                    continue
                pix = page.get_pixmap(dpi=OCR_DPI, colorspace=fitz.csGRAY)
                pending[pno] = pool.submit(_ocr_png, pix.tobytes("png"))
                while len(pending) >= max_in_flight:
                    time.sleep(0.05)
                    _collect()
            while pending:
                time.sleep(0.05)
                _collect()
    finally:
        doc.close()

    pages = []
    for pno in range(n):
        raw, ocr = results.get(pno, ("", False))
        pages.append((pno + 1, clean_text(raw), ocr))

    stats = {
        "pages":         n,
        "ocr_pages":     sum(1 for _, _, o in pages if o),
        "empty_pages":   sum(1 for _, t, _ in pages if len(t) < MIN_CHUNK_CHARS),
        "ocr_available": bool(use_ocr),
    }
    return pages, stats


# ── Step 2: chunking ──────────────────────────────────────────────────────────
def split_text(text, size=CHUNK_CHARS, overlap=CHUNK_OVERLAP):
    """Split on sentence/word boundaries into ~size-char chunks with overlap."""
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    chunks, start, L = [], 0, len(text)
    while start < L:
        end = min(start + size, L)
        if end < L:
            cut = text.rfind(". ", start + size // 2, end)
            if cut == -1:
                cut = text.rfind(" ", start + size // 2, end)
            if cut != -1:
                end = cut + 1
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= L:
            break
        nxt = max(end - overlap, start + 1)
        sp = text.find(" ", nxt, end)
        start = sp + 1 if sp != -1 else nxt
    return chunks


def chunk_pages(pages, subject_name, manual_name):
    chunks = []
    for page_no, text, ocr in pages:
        for piece in split_text(text):
            if len(piece) < MIN_CHUNK_CHARS:
                continue
            chunks.append({
                "text":    piece,
                "page":    page_no,
                "subject": subject_name.strip(),
                "manual":  manual_name.strip(),
                "ocr":     bool(ocr),
            })
    return chunks


# ── Step 3: embed + write index (atomic) ──────────────────────────────────────
def _atomic_write_bytes_index(index, path):
    tmp = path + ".tmp"
    faiss.write_index(index, tmp)
    os.replace(tmp, path)


def _atomic_write_json(obj, path):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


def build_index(pdf_path, subject_name, manual_name, term_dir, file_stem, embedder,
                workers=None, progress_cb=None, use_ocr=None):
    """Extract (with OCR), chunk, embed and write {stem}_faiss.index/_doc.json/_meta.json.

    progress_cb(fraction, message) is optional (Streamlit progress bar or CLI printer).
    Returns (n_chunks, stats). Raises ValueError if no usable text was found.
    """
    t0 = time.time()

    def _p(frac, msg):
        if progress_cb:
            progress_cb(min(max(frac, 0.0), 1.0), msg)

    _p(0.0, "Reading pages")
    pages, stats = extract_pages(
        pdf_path, workers=workers, use_ocr=use_ocr,
        progress_cb=lambda f: _p(0.85 * f, "Reading pages (OCR for scanned pages)"))

    chunks = chunk_pages(pages, subject_name, manual_name)
    if not chunks:
        hint = ("" if stats["ocr_available"] else
                " Tesseract OCR is not installed — run: sudo apt install -y tesseract-ocr "
                "and pip install pytesseract pillow.")
        raise ValueError(f"No readable text found in '{os.path.basename(pdf_path)}'.{hint}")

    _p(0.88, f"Embedding {len(chunks)} chunks")
    emb = embedder.encode([c["text"] for c in chunks], batch_size=64,
                          show_progress_bar=False, convert_to_numpy=True).astype("float32")
    faiss.normalize_L2(emb)
    index = faiss.IndexFlatIP(emb.shape[1])
    index.add(emb)

    os.makedirs(term_dir, exist_ok=True)
    _atomic_write_bytes_index(index, os.path.join(term_dir, f"{file_stem}_faiss.index"))
    _atomic_write_json({str(i): c for i, c in enumerate(chunks)},
                       os.path.join(term_dir, f"{file_stem}_doc.json"))
    stats.update({"chunks": len(chunks), "seconds": round(time.time() - t0, 1)})
    _atomic_write_json({
        "subject":       subject_name.strip(),
        "manual":        manual_name.strip(),
        "stem":          file_stem,
        "indexed_with":  INGEST_VERSION,
        "indexed_at":    time.strftime("%Y-%m-%d %H:%M:%S"),
        **stats,
    }, os.path.join(term_dir, f"{file_stem}_meta.json"))

    # Old semantic-cache answers for this book were built on bad text — drop them.
    for suffix in ("_cache.db", "_qcache.index"):
        p = os.path.join(term_dir, f"{file_stem}{suffix}")
        if os.path.exists(p):
            os.remove(p)

    _p(1.0, "Done")
    return len(chunks), stats
