#!/usr/bin/env python3
"""
reindex_books.py — rebuild every textbook index in user_profiles/ with OCR.

Place in the AIEdS root folder (next to pdf_ingest.py, quiz_bank.json, sahayak.db).
Uses the PDFs the Instructor Panel already saved in user_profiles/Term_N/, so
nothing has to be uploaded again. Streamlit can keep running.

Usage (use the same python that runs streamlit):
    python3 reindex_books.py --dry-run            # list what would be rebuilt
    python3 reindex_books.py                      # rebuild everything not yet on v1
    python3 reindex_books.py --term Term_3        # one term only
    python3 reindex_books.py --only haykin        # stems containing 'haykin'
    python3 reindex_books.py --force              # rebuild even if already done
    python3 reindex_books.py --workers 48         # OCR threads (default: cores-2, max 32)

Safe to re-run: finished books are skipped (resumable), old files are backed up to
user_profiles/_backup_<timestamp>/ first, and new files are written atomically.
A CSV report is written to reindex_report_<timestamp>.csv.
"""

import argparse
import csv
import glob
import json
import os
import shutil
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import pdf_ingest  # noqa: E402

USER_PROFILES_DIR = os.path.join(BASE_DIR, "user_profiles")


def load_embedder():
    from sentence_transformers import SentenceTransformer
    model_path = os.path.join(BASE_DIR, "Python-3.12.9", "embedding_model")
    target = model_path if os.path.exists(model_path) else "all-MiniLM-L6-v2"
    try:
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        device = "cpu"
    print(f"Embedding model: {target}  (device: {device})")
    return SentenceTransformer(target, device=device)


def find_pdf(term_dir, manual, stem):
    exact = os.path.join(term_dir, f"{manual}.pdf")
    if os.path.exists(exact):
        return exact
    pdfs = [p for p in glob.glob(os.path.join(term_dir, "*")) if p.lower().endswith(".pdf")]
    m_low = manual.strip().lower()
    for p in pdfs:
        if os.path.splitext(os.path.basename(p))[0].strip().lower() == m_low:
            return p
    for p in pdfs:
        name = os.path.splitext(os.path.basename(p))[0].strip().replace(" ", "_").lower()
        if name and name in stem:
            return p
    return None


def collect_jobs(term_filter, only):
    jobs = []
    for term_dir in sorted(glob.glob(os.path.join(USER_PROFILES_DIR, "Term_*"))):
        term = os.path.basename(term_dir)
        if term_filter and term != term_filter:
            continue
        for meta_p in sorted(glob.glob(os.path.join(term_dir, "*_meta.json"))):
            try:
                with open(meta_p, encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception as e:
                print(f"  ! unreadable {meta_p}: {e}")
                continue
            stem = meta.get("stem") or os.path.basename(meta_p)[:-len("_meta.json")]
            if only and only.lower() not in stem.lower():
                continue
            jobs.append({
                "term": term, "term_dir": term_dir, "stem": stem,
                "subject": meta.get("subject", stem), "manual": meta.get("manual", stem),
                "done": meta.get("indexed_with") == pdf_ingest.INGEST_VERSION,
                "pdf": find_pdf(term_dir, meta.get("manual", stem), stem),
            })
    return jobs


def backup(job, backup_root):
    dest = os.path.join(backup_root, job["term"])
    os.makedirs(dest, exist_ok=True)
    for suffix in ("_faiss.index", "_doc.json", "_meta.json"):
        src = os.path.join(job["term_dir"], job["stem"] + suffix)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(dest, os.path.basename(src)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--term")
    ap.add_argument("--only")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--no-ocr", action="store_true", help="skip OCR (not recommended for scans)")
    args = ap.parse_args()

    ocr_ok = pdf_ingest.tesseract_available()
    print(f"Tesseract OCR available: {ocr_ok}")
    if not ocr_ok and not args.no_ocr and not args.dry_run:
        print("\nTesseract is required for scanned books. Install it, then re-run:\n"
              "  sudo apt install -y tesseract-ocr\n"
              f"  {sys.executable} -m pip install pytesseract pillow\n")
        sys.exit(1)

    jobs = collect_jobs(args.term, args.only)
    todo = [j for j in jobs if j["pdf"] and (args.force or not j["done"])]
    missing = [j for j in jobs if not j["pdf"]]
    print(f"Books found: {len(jobs)}  |  to rebuild: {len(todo)}  |  "
          f"already done: {sum(1 for j in jobs if j['done'])}  |  PDF missing: {len(missing)}")
    for j in missing:
        print(f"  ! PDF not found for {j['term']}/{j['stem']} (manual '{j['manual']}') — re-upload it")
    if args.dry_run:
        for j in todo:
            print(f"  would rebuild {j['term']}/{j['stem']}  <-  {os.path.basename(j['pdf'])}")
        return

    ts = time.strftime("%Y%m%d_%H%M")
    backup_root = os.path.join(USER_PROFILES_DIR, f"_backup_{ts}")
    report_p = os.path.join(BASE_DIR, f"reindex_report_{ts}.csv")
    embedder = load_embedder() if todo else None
    workers = args.workers or pdf_ingest.default_workers()
    print(f"OCR threads: {workers}\nBackups: {backup_root}\n")

    rows = []
    for k, job in enumerate(todo, 1):
        label = f"[{k}/{len(todo)}] {job['term']}/{job['stem']}"
        last = {"t": 0.0}

        def _progress(frac, msg, _label=label):
            now = time.time()
            if now - last["t"] > 5 or frac >= 1.0:
                last["t"] = now
                print(f"  {_label}: {frac*100:5.1f}%  {msg}", flush=True)

        print(label)
        backup(job, backup_root)
        try:
            n, st = pdf_ingest.build_index(
                job["pdf"], job["subject"], job["manual"], job["term_dir"], job["stem"],
                embedder, workers=workers, progress_cb=_progress,
                use_ocr=not args.no_ocr)
            rows.append([job["term"], job["stem"], st["pages"], st["ocr_pages"],
                         st["empty_pages"], n, st["seconds"], "ok"])
            print(f"  -> {n} chunks | {st['pages']} pages, {st['ocr_pages']} OCR, "
                  f"{st['empty_pages']} empty | {st['seconds']} s\n")
        except Exception as e:
            rows.append([job["term"], job["stem"], "", "", "", 0, "", f"FAILED: {e}"])
            print(f"  -> FAILED: {e}\n")

    with open(report_p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["term", "stem", "pages", "ocr_pages", "empty_pages", "chunks", "seconds", "status"])
        w.writerows(rows)
    ok = sum(1 for r in rows if r[-1] == "ok")
    print(f"Finished: {ok}/{len(rows)} rebuilt. Report: {report_p}")
    if ok:
        print("The chatbot picks up the new indexes automatically (it reloads when files change).")


if __name__ == "__main__":
    main()
