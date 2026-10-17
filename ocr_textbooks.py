#!/usr/bin/env python3
"""
ocr_textbooks.py — Batch-OCR scanned textbook PDFs for AIEdS.

Uses ONLY tools already present on ece-lab (no pip, no sudo, no NumPy):
    pdfinfo / pdftoppm / pdfunite / pdftotext  (poppler-utils 22.02)
    tesseract 4.1.1 with 'eng'

For every PDF in SRC_DIR it renders each page to an image, OCRs it with
Tesseract into a searchable single-page PDF (image + invisible text layer),
and merges the pages into DST_DIR/<same name>.pdf. Originals are never touched.
PDFs that already have a text layer are copied as-is.

Usage:
    python3 ocr_textbooks.py <src_dir> <dst_dir> [--jobs 48] [--dpi 300] [--force]
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REQUIRED_TOOLS = ("tesseract", "pdftoppm", "pdfunite", "pdfinfo", "pdftotext")


def has_text_layer(pdf: Path, min_chars: int = 200) -> bool:
    """True if the first few pages already contain extractable text."""
    try:
        out = subprocess.run(
            ["pdftotext", "-l", "5", str(pdf), "-"],
            capture_output=True, text=True, timeout=120,
        ).stdout
        return len(out.strip()) >= min_chars
    except Exception:
        return False


def page_count(pdf: Path) -> int:
    out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if line.startswith("Pages:"):
            return int(line.split()[1])
    return 0


def ocr_page(src: Path, n: int, tmp: Path, dpi: int, env: dict) -> Path:
    """Render page n and OCR it into tmp/p_NNNNN.pdf. Returns that path."""
    stem = tmp / ("p_%05d" % n)
    subprocess.run(
        ["pdftoppm", "-f", str(n), "-l", str(n), "-r", str(dpi), "-gray",
         "-png", "-singlefile", str(src), str(stem)],
        check=True, capture_output=True,
    )
    png = stem.with_suffix(".png")
    subprocess.run(
        ["tesseract", str(png), str(stem), "-l", "eng", "--psm", "1", "pdf"],
        check=True, capture_output=True, env=env,
    )
    png.unlink(missing_ok=True)
    return stem.with_suffix(".pdf")


MERGE_CHUNK = 200  # pdfunite opens every input at once; stay well under ulimit -n (1024)


def merge_pages(files: list, out: Path, tmp: Path) -> None:
    """Merge single-page PDFs in order, in chunks, so huge books don't hit the open-file limit."""
    if len(files) <= MERGE_CHUNK:
        subprocess.run(["pdfunite", *files, str(out)], check=True, capture_output=True)
        return
    chunks = []
    for k in range(0, len(files), MERGE_CHUNK):
        c = tmp / ("chunk_%04d.pdf" % (k // MERGE_CHUNK))
        subprocess.run(["pdfunite", *files[k:k + MERGE_CHUNK], str(c)],
                       check=True, capture_output=True)
        chunks.append(str(c))
    merge_pages(chunks, out, tmp)


def ocr_pdf(src: Path, dst: Path, jobs: int, dpi: int) -> str:
    n_pages = page_count(src)
    if n_pages == 0:
        return "FAILED: could not read page count"

    env = dict(os.environ, OMP_THREAD_LIMIT="1")  # one core per tesseract
    with tempfile.TemporaryDirectory(prefix="aieds_ocr_") as td:
        tmp = Path(td)
        pages = {}
        errors = 0
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            futs = {pool.submit(ocr_page, src, i, tmp, dpi, env): i
                    for i in range(1, n_pages + 1)}
            for f in as_completed(futs):
                try:
                    pages[futs[f]] = f.result()
                except Exception:
                    errors += 1
        if errors:
            return "FAILED: %d of %d pages did not OCR" % (errors, n_pages)

        ordered = [str(pages[i]) for i in range(1, n_pages + 1)]
        part = dst.with_suffix(".partial.pdf")
        merge_pages(ordered, part, tmp)
        part.rename(dst)
    return "ok (%d pages)" % n_pages


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src_dir")
    ap.add_argument("dst_dir")
    ap.add_argument("--jobs", type=int, default=48)
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    missing = [t for t in REQUIRED_TOOLS if shutil.which(t) is None]
    if missing:
        print("ERROR: missing tools:", ", ".join(missing))
        return 1

    src_dir, dst_dir = Path(a.src_dir).resolve(), Path(a.dst_dir).resolve()
    if src_dir == dst_dir:
        print("ERROR: dst_dir must differ from src_dir")
        return 1
    dst_dir.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(p for p in src_dir.rglob("*")
                  if p.suffix.lower() == ".pdf" and dst_dir not in p.parents)
    if not pdfs:
        print("No PDFs found in", src_dir)
        return 1

    print("Found %d PDFs  (jobs=%d, dpi=%d)\n" % (len(pdfs), a.jobs, a.dpi))
    failed = 0
    for i, src in enumerate(pdfs, 1):
        dst = dst_dir / src.relative_to(src_dir)
        dst.parent.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        if dst.exists() and not a.force:
            status = "skip (already done)"
        elif has_text_layer(src) and not a.force:
            shutil.copy2(src, dst)
            status = "copied (already has text)"
        else:
            try:
                status = ocr_pdf(src, dst, a.jobs, a.dpi)
            except subprocess.CalledProcessError as e:
                err = (e.stderr or b"").decode(errors="replace").strip().splitlines()
                status = "FAILED: %s exit %s: %s" % (e.cmd[0], e.returncode, err[-1] if err else "")
            except Exception as e:
                status = "FAILED: %s" % e
        failed += status.startswith("FAILED")
        print("[%d/%d] %-60s %s (%.0fs)" % (i, len(pdfs), src.name[:60], status, time.time() - t0))
        sys.stdout.flush()

    print("\nDone. %d failed." % failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
