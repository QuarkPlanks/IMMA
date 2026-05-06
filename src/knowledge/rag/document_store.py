"""
src/knowledge/rag/document_store.py
────────────────────────────────────
ChromaDB vector store management.

Collection: "polymer_knowledge"
Each document record:
  - id:         chunk_id (str)
  - embedding:  384-dim float list
  - document:   chunk text
  - metadata:   {source, doc_type, added_at}
"""

import logging
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

import sys
ROOT_DIR = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

CHROMA_DIR = ROOT_DIR / "data" / "chroma_db"


def _collection_name() -> str:
    """
    Derive ChromaDB collection name from the embedding model.
    Different models have different dimensions — mixing them corrupts the index.
    Examples:
      BAAI/bge-m3              → polymer_knowledge_bge_m3
      BAAI/bge-small-en-v1.5  → polymer_knowledge_bge_small_en
      paraphrase-multilingual-MiniLM-L12-v2 → polymer_knowledge_multilingual
    """
    try:
        from config import EMBEDDING_MODEL
        model = EMBEDDING_MODEL
    except ImportError:
        model = "BAAI/bge-m3"
    # Sanitize to valid collection name
    import re
    suffix = re.sub(r"[^a-zA-Z0-9]", "_", model.split("/")[-1])[:30]
    return f"polymer_knowledge_{suffix}"


def _get_collection():
    """Lazily create/open the ChromaDB collection."""
    import chromadb
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = client.get_or_create_collection(
        name=_collection_name(),
        metadata={"hnsw:space": "cosine"},
    )
    return collection


def add_chunks(chunks: list[dict], doc_type: str = "paper") -> int:
    """
    Add a list of chunk dicts to the vector store.
    Each chunk: {"text": str, "source": str, "chunk_id": str}
    Returns number of new chunks added (skips duplicates).
    """
    if not chunks:
        return 0

    from .embedder import get_embedder
    embedder = get_embedder()
    collection = _get_collection()

    texts      = [c["text"]     for c in chunks]
    ids        = [c["chunk_id"] for c in chunks]
    metadatas  = [
        {
            "source":   c.get("source", "unknown"),
            "doc_type": doc_type,
            "added_at": datetime.now().isoformat(),
        }
        for c in chunks
    ]

    # Check which IDs are already in the store
    existing = set(collection.get(ids=ids)["ids"])
    new_chunks = [(t, i, m) for t, i, m in zip(texts, ids, metadatas) if i not in existing]

    if not new_chunks:
        log.info("All %d chunks already in store, skipping.", len(chunks))
        return 0

    new_texts, new_ids, new_meta = zip(*new_chunks)
    log.info("Embedding %d new chunks …", len(new_texts))
    embeddings = embedder.embed_documents(list(new_texts))

    collection.add(
        ids        = list(new_ids),
        embeddings = embeddings,
        documents  = list(new_texts),
        metadatas  = list(new_meta),
    )
    log.info("Added %d chunks to '%s'.", len(new_texts), _collection_name())
    return len(new_texts)


def query(
    query_text: str,
    n_results: int = 5,
    doc_type_filter: Optional[str] = None,
) -> list[dict]:
    """
    Retrieve top-n relevant chunks for a query.
    Returns list of {text, source, score, doc_type}.
    """
    from .embedder import get_embedder
    embedder = get_embedder()
    collection = _get_collection()

    if collection.count() == 0:
        return []

    q_vec = embedder.embed_query(query_text)
    where = {"doc_type": doc_type_filter} if doc_type_filter else None

    kwargs = dict(
        query_embeddings=[q_vec],
        n_results=min(n_results, collection.count()),
        include=["documents", "metadatas", "distances"],
    )
    if where:
        kwargs["where"] = where

    results = collection.query(**kwargs)

    hits = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        hits.append({
            "text":     doc,
            "source":   meta.get("source", ""),
            "doc_type": meta.get("doc_type", ""),
            "score":    round(1 - dist, 4),   # cosine similarity
        })
    return hits


def stats() -> dict:
    """Return basic stats about the knowledge base."""
    try:
        collection = _get_collection()
        count = collection.count()
        return {"total_chunks": count, "collection": _collection_name(),
                "db_path": str(CHROMA_DIR)}
    except Exception as e:
        return {"error": str(e)}


def delete_by_source(source: str) -> int:
    """Remove all chunks from a given source document."""
    collection = _get_collection()
    results = collection.get(where={"source": source})
    ids = results["ids"]
    if ids:
        collection.delete(ids=ids)
    return len(ids)
