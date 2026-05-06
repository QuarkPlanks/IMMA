"""
src/knowledge/rag/pdf_parser.py
────────────────────────────────
Extract and chunk text from PDF files for vector indexing.
"""

import re
from pathlib import Path
from typing import Iterator


def extract_text_pymupdf(pdf_path: str | Path) -> str:
    """Extract all text from a PDF using PyMuPDF (fitz)."""
    try:
        import fitz  # pymupdf
        doc = fitz.open(str(pdf_path))
        pages = []
        for page in doc:
            pages.append(page.get_text("text"))
        doc.close()
        return "\n".join(pages)
    except Exception as e:
        return ""


def clean_text(text: str) -> str:
    """Clean extracted PDF text."""
    # Remove excessive whitespace and fix hyphenation
    text = re.sub(r"-\n(\w)", r"\1", text)           # dehyphenate
    text = re.sub(r"\n{3,}", "\n\n", text)            # max 2 consecutive newlines
    text = re.sub(r"[ \t]{2,}", " ", text)            # collapse spaces
    text = re.sub(r"\f", "\n\n", text)                # form feeds → paragraph
    return text.strip()


def chunk_text(
    text: str,
    chunk_size: int = 600,
    overlap: int = 100,
    min_chunk: int = 80,
) -> list[str]:
    """
    Split text into overlapping chunks for embedding.
    Tries to split on paragraph/sentence boundaries.
    """
    # Split into paragraphs first
    paragraphs = re.split(r"\n\n+", text)
    chunks = []
    current = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        if len(current) + len(para) + 2 <= chunk_size:
            current = (current + "\n\n" + para).strip()
        else:
            # Save current chunk
            if len(current) >= min_chunk:
                chunks.append(current)
            # Start new chunk with overlap from end of previous
            overlap_text = current[-overlap:] if len(current) > overlap else current
            current = (overlap_text + "\n\n" + para).strip()

    if len(current) >= min_chunk:
        chunks.append(current)

    return chunks


def parse_pdf_to_chunks(
    pdf_path: str | Path,
    source_label: str = "",
) -> list[dict]:
    """
    Parse a PDF and return a list of chunk dicts ready for ChromaDB ingestion.
    Each chunk: {"text": str, "source": str, "chunk_id": str}
    """
    pdf_path = Path(pdf_path)
    source = source_label or pdf_path.name
    raw = extract_text_pymupdf(pdf_path)
    if not raw:
        return []

    text = clean_text(raw)
    chunks = chunk_text(text)

    return [
        {
            "text":     c,
            "source":   source,
            "chunk_id": f"{pdf_path.stem}_chunk{i:04d}",
        }
        for i, c in enumerate(chunks)
    ]


def parse_text_to_chunks(
    text: str,
    source: str,
    doc_id: str,
    chunk_size: int = 600,
    overlap: int = 100,
) -> list[dict]:
    """Parse plain text (not PDF) into chunks."""
    text = clean_text(text)
    chunks = chunk_text(text, chunk_size, overlap)
    return [
        {
            "text":     c,
            "source":   source,
            "chunk_id": f"{doc_id}_chunk{i:04d}",
        }
        for i, c in enumerate(chunks)
    ]
