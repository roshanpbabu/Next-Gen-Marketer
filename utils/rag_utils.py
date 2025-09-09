from typing import List, Dict, Any, Optional
from pathlib import Path
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
import pandas as pd
import hashlib

PERSIST_DIR = str(Path(".chroma").absolute())
_EMBEDDER = None

# ---------------- Embeddings ---------------- #
def get_embedder(model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
    """Lazy-load the SentenceTransformer embedder on first use."""
    global _EMBEDDER
    if _EMBEDDER is None:
        _EMBEDDER = SentenceTransformer(model_name)
    return _EMBEDDER

def _embed(texts: List[str], model_name: Optional[str] = None) -> List[List[float]]:
    """Encode texts into vectors. SentenceTransformer handles internal batching."""
    embedder = get_embedder(model_name or "sentence-transformers/all-MiniLM-L6-v2")
    return embedder.encode(texts, normalize_embeddings=True).tolist()

# ---------------- Chroma Client ---------------- #
def get_client():
    return chromadb.PersistentClient(path=PERSIST_DIR, settings=Settings(allow_reset=False))

def get_collection(namespace: str):
    client = get_client()
    return client.get_or_create_collection(name=namespace, metadata={"hnsw:space": "cosine"})

# ---------------- Helpers ---------------- #
def _row_to_key(row: pd.Series, id_cols: Optional[List[str]] = None, chunk_index: Optional[int] = None) -> str:
    """Create a canonical string for a row to be hashed into an ID."""
    if id_cols:
        parts = [str(row.get(c, "")) for c in id_cols]
    else:
        parts = [str(v) for v in row.values]
    if chunk_index is not None:
        parts.append(str(chunk_index))
    return "|".join(parts)

def stable_id_from_row(row: pd.Series, id_cols: Optional[List[str]] = None, id_prefix: str = "") -> str:
    """Return a deterministic id for a row (md5 of chosen key)."""
    key = _row_to_key(row, id_cols=id_cols, chunk_index=None)
    return id_prefix + hashlib.md5(key.encode("utf-8")).hexdigest()

def chunk_text(text: str, max_chars: int = 1500) -> List[str]:
    """Split a long string into character chunks (simple but effective)."""
    if not text:
        return []
    text = text.strip()
    if len(text) <= max_chars:
        return [text]
    return [text[i:i+max_chars] for i in range(0, len(text), max_chars)]

# ---------------- Upsert ---------------- #
def upsert_dataframe_as_docs(
    df: pd.DataFrame,
    namespace: str,
    text_cols: Optional[List[str]] = None,
    meta_cols: Optional[List[str]] = None,
    id_cols: Optional[List[str]] = None,
    id_prefix: str = "",
    batch_size: int = 64,
    max_chars_per_doc: int = 1500,
    auto_text_only: bool = False
):
    """
    Upsert dataframe rows into a Chroma collection in batches.
    - If text_cols is None, use all cols (or only string cols if auto_text_only=True).
    - If meta_cols is None, use all cols.
    - If id_cols is None, row hash is used for stable ID.
    """
    if df is None or df.shape[0] == 0:
        return

    all_cols = list(df.columns)
    if text_cols is None:
        if auto_text_only:
            text_cols = [c for c in all_cols if df[c].dtype == "object"]
            if not text_cols:  # fallback
                text_cols = all_cols.copy()
        else:
            text_cols = all_cols.copy()

    if meta_cols is None:
        meta_cols = all_cols.copy()

    coll = get_collection(namespace)

    docs_batch, ids_batch, metas_batch = [], [], []
    for _, row in df.iterrows():
        # Document text
        parts = [str(row[c]) for c in text_cols if pd.notna(row.get(c, None))]
        text = " | ".join(parts)

        # Chunk if long
        chunks = chunk_text(text, max_chars_per_doc) or [""]

        for i, chunk in enumerate(chunks):
            if id_cols:
                key = _row_to_key(row, id_cols=id_cols, chunk_index=(i if len(chunks) > 1 else None))
                doc_id = id_prefix + hashlib.md5(key.encode("utf-8")).hexdigest()
            else:
                fallback_key = "|".join([str(v) for v in row.values]) + f"|chunk:{i}"
                doc_id = id_prefix + hashlib.md5(fallback_key.encode("utf-8")).hexdigest()

            meta = {k: (None if pd.isna(row.get(k, None)) else row.get(k, None)) for k in meta_cols}
            if len(chunks) > 1:
                meta["_chunk"] = i
                meta["_chunk_count"] = len(chunks)

            ids_batch.append(doc_id)
            docs_batch.append(chunk)
            metas_batch.append(meta)

        if len(docs_batch) >= batch_size:
            embeddings = _embed(docs_batch)
            coll.upsert(documents=docs_batch, metadatas=metas_batch, ids=ids_batch, embeddings=embeddings)
            docs_batch, ids_batch, metas_batch = [], [], []

    if docs_batch:
        embeddings = _embed(docs_batch)
        coll.upsert(documents=docs_batch, metadatas=metas_batch, ids=ids_batch, embeddings=embeddings)

# ---------------- Query helper ---------------- #
def query_namespace(
    namespace: str,
    query_text: str,
    k: int = 5,
    where: Optional[Dict[str, Any]] = None,
    include: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """
    Query a Chroma collection and return list of hits:
    [{ "id": str, "text": str, "metadata": dict, "distance": float|None }]
    """
    try:
        coll = get_collection(namespace)
    except Exception:
        return []

    include = include or ["documents", "metadatas", "distances"]
    results = coll.query(query_texts=[query_text], n_results=k, where=where)

    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    ids = results.get("ids", [[]])[0] if "ids" in results else [None] * len(docs)
    dists = results.get("distances", [[]])[0] if "distances" in results else [None] * len(docs)

    hits = []
    for i, doc in enumerate(docs):
        hits.append({
            "id": ids[i] if i < len(ids) else None,
            "text": doc,
            "metadata": metas[i] if i < len(metas) else {},
            "distance": dists[i] if i < len(dists) else None
        })
    return hits

# ---------------- Explicit exports ---------------- #
__all__ = [
    "get_embedder",
    "get_client",
    "get_collection",
    "stable_id_from_row",
    "chunk_text",
    "upsert_dataframe_as_docs",
    "query_namespace"
]
