"""
src/knowledge/rag/embedder.py
──────────────────────────────
本地多语言 Embedding，支持中英文混合文献。

默认模型: BAAI/bge-m3
  - 支持 100+ 语言，中英文混合效果优秀
  - 大小: ~570 MB（首次运行自动下载）
  - 维度: 1024
  - 运行环境: CPU 即可（速度约 50-200 句/秒）

其他可选模型（在 config.py 或 .env 中设置 EMBEDDING_MODEL）:
  - BAAI/bge-small-zh-v1.5       纯中文轻量版，~95MB，dim=512
  - paraphrase-multilingual-MiniLM-L12-v2  多语言轻量，~118MB，dim=384
  - BAAI/bge-large-zh-v1.5       中文高质量，~1.3GB，dim=1024

注意：bge-m3 不需要 query prefix（与 bge-en 系列不同）。
"""

import logging
from typing import Union

log = logging.getLogger(__name__)

# Models that require the BGE English query prefix
_BGE_EN_PREFIXED = {
    "BAAI/bge-small-en-v1.5",
    "BAAI/bge-base-en-v1.5",
    "BAAI/bge-large-en-v1.5",
}
_BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class LocalEmbedder:
    """
    Wraps sentence-transformers for embedding queries and documents.
    Singleton pattern — model loaded once and reused.
    """

    _instance = None

    def __new__(cls, model_name: str = "BAAI/bge-m3"):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._loaded = False
            cls._instance.model_name = model_name
        return cls._instance

    def _load(self):
        if self._loaded:
            return
        log.info("Loading embedding model '%s' …", self.model_name)
        log.info("（首次运行将自动下载模型，请稍候）")
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(self.model_name)
        self._needs_prefix = self.model_name in _BGE_EN_PREFIXED
        self._loaded = True
        # get_embedding_dimension() is the new name; fall back for older versions
        get_dim = (getattr(self._model, "get_embedding_dimension", None)
                   or getattr(self._model, "get_sentence_embedding_dimension", None))
        dim = get_dim() if get_dim else "?"
        log.info("Embedding model loaded: dim=%s, needs_prefix=%s",
                 dim, self._needs_prefix)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of document chunks (no prefix needed)."""
        self._load()
        vecs = self._model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=len(texts) > 20,
            batch_size=32,
        )
        return vecs.tolist()

    def embed_query(self, query: str) -> list[float]:
        """
        Embed a search query.
        For English BGE models, prepend the retrieval prefix.
        For bge-m3 and Chinese models, use the query as-is.
        """
        self._load()
        text = (_BGE_QUERY_PREFIX + query) if self._needs_prefix else query
        vec = self._model.encode([text], normalize_embeddings=True)[0]
        return vec.tolist()

    @property
    def dim(self) -> int:
        self._load()
        get_dim = (getattr(self._model, "get_embedding_dimension", None)
                   or getattr(self._model, "get_sentence_embedding_dimension", None))
        return get_dim() if get_dim else 1024


# Module-level singleton
_embedder: LocalEmbedder | None = None


def get_embedder(model_name: str | None = None) -> LocalEmbedder:
    global _embedder
    if _embedder is None:
        if model_name is None:
            try:
                from config import EMBEDDING_MODEL
                model_name = EMBEDDING_MODEL
            except ImportError:
                model_name = "BAAI/bge-m3"
        _embedder = LocalEmbedder(model_name)
    return _embedder
