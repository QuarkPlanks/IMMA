"""
src/knowledge/literature/downloader.py
───────────────────────────────────────
Download PDFs and index abstracts into the RAG knowledge base.

Two ingestion paths:
  A. Download full PDF → parse & chunk → embed (best quality)
  B. Abstract-only fallback if PDF unavailable → embed as single chunk
"""

import time
import logging
import hashlib
import re
from pathlib import Path

import requests

log = logging.getLogger(__name__)

import sys
ROOT_DIR = Path(__file__).parent.parent.parent.parent
PDF_DIR = ROOT_DIR / "data" / "literature" / "pdfs"
PDF_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 Chrome/124 Safari/537.36")
}


def _pdf_filename(title: str, year: int) -> str:
    safe = re.sub(r"[^\w\s-]", "", title)[:60].strip().replace(" ", "_")
    return f"{year}_{safe}.pdf"


def download_pdf(url: str, save_path: Path, timeout: int = 30) -> bool:
    """Download a PDF file, return True if successful."""
    if save_path.exists() and save_path.stat().st_size > 5000:
        log.info("  PDF already exists: %s", save_path.name)
        return True
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, stream=True)
        r.raise_for_status()
        content_type = r.headers.get("Content-Type", "")
        if "pdf" not in content_type and "octet" not in content_type:
            # Some URLs redirect to HTML; check first bytes
            first = b""
            for chunk in r.iter_content(1024):
                first = chunk
                break
            if not first.startswith(b"%PDF"):
                log.warning("  Not a PDF: %s", url[:60])
                return False

        with open(save_path, "wb") as f:
            r.raw.seek(0) if hasattr(r.raw, "seek") else None
            f.write(first if "first" in dir() else b"")
            for chunk in r.iter_content(8192):
                f.write(chunk)

        size_kb = save_path.stat().st_size // 1024
        log.info("  Downloaded: %s (%d KB)", save_path.name, size_kb)
        return True
    except Exception as e:
        log.warning("  Download failed (%s): %s", url[:60], e)
        return False


def index_paper(paper: dict, force: bool = False) -> int:
    """
    Download PDF (if available) and add to vector store.
    Returns number of chunks added.
    """
    from src.knowledge.rag.pdf_parser import parse_pdf_to_chunks, parse_text_to_chunks
    from src.knowledge.rag.document_store import add_chunks

    title   = paper.get("title", "Untitled")
    year    = paper.get("year", 0)
    pdf_url = paper.get("pdf_url")
    abstract= paper.get("abstract", "")
    authors = ", ".join(paper.get("authors", []))
    source  = f"{title} ({year}) — {authors}"

    # Generate a stable doc_id
    doc_id = hashlib.md5(title.encode()).hexdigest()[:12]

    # Path A: full PDF
    if pdf_url:
        fname = _pdf_filename(title, year)
        pdf_path = PDF_DIR / fname
        ok = download_pdf(pdf_url, pdf_path)
        if ok:
            chunks = parse_pdf_to_chunks(pdf_path, source_label=source)
            if chunks:
                return add_chunks(chunks, doc_type="paper")

    # Path B: abstract only
    if abstract:
        text = f"Title: {title}\nAuthors: {authors}\nYear: {year}\n\nAbstract:\n{abstract}"
        chunks = parse_text_to_chunks(text, source=source, doc_id=doc_id)
        return add_chunks(chunks, doc_type="abstract")

    return 0


def index_local_pdf(pdf_path: str | Path, doc_type: str = "manual") -> int:
    """
    Index a locally available PDF (e.g. textbook, TDS, internal manual).
    """
    from src.knowledge.rag.pdf_parser import parse_pdf_to_chunks
    from src.knowledge.rag.document_store import add_chunks
    pdf_path = Path(pdf_path)
    chunks = parse_pdf_to_chunks(pdf_path, source_label=pdf_path.name)
    return add_chunks(chunks, doc_type=doc_type)


def index_text_snippet(text: str, source: str, doc_id: str, doc_type: str = "tds") -> int:
    """
    Index a raw text snippet (e.g. scraped TDS content, grade raw_text).
    """
    from src.knowledge.rag.pdf_parser import parse_text_to_chunks
    from src.knowledge.rag.document_store import add_chunks
    chunks = parse_text_to_chunks(text, source=source, doc_id=doc_id)
    return add_chunks(chunks, doc_type=doc_type)
