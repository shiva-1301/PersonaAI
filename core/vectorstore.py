"""ChromaDB: embed, store and retrieve chunks.

Embeddings are computed locally with sentence-transformers, so no API calls are made
here. All users share one collection; every query is filtered by user_id.
"""

from dataclasses import dataclass

from core import config
from core.documents import Chunk

EMBED_MODEL = "all-MiniLM-L6-v2"
COLLECTION = "chunks"

_model = None
_client = None
_client_path = None


@dataclass
class Hit:
    text: str
    document_id: int
    filename: str
    page: int | None
    distance: float  # cosine distance: 0 = identical, 1 = unrelated
    score: float | None = None  # reranker relevance (higher = better), set by rag.retrieve


def _embedder():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(EMBED_MODEL)
    return _model


def embed(texts: list[str]) -> list[list[float]]:
    return _embedder().encode(texts, normalize_embeddings=True, show_progress_bar=False).tolist()


def _collection():
    global _client, _client_path
    import chromadb
    from chromadb.config import Settings

    # Re-open if the storage dir changed (tests point config.CHROMA_DIR at a temp dir).
    if _client is None or _client_path != config.CHROMA_DIR:
        _client = chromadb.PersistentClient(
            path=str(config.CHROMA_DIR), settings=Settings(anonymized_telemetry=False)
        )
        _client_path = config.CHROMA_DIR
    return _client.get_or_create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})


def add_chunks(user_id: int, document_id: int, filename: str, chunks: list[Chunk]) -> None:
    if not chunks:
        return
    texts = [c.text for c in chunks]
    _collection().add(
        ids=[f"{document_id}-{c.index}" for c in chunks],
        documents=texts,
        embeddings=embed(texts),
        metadatas=[
            {
                "user_id": user_id,
                "document_id": document_id,
                "filename": filename,
                # Chroma metadata can't hold None; 0 means "no page number".
                "page": c.page or 0,
                "chunk": c.index,
            }
            for c in chunks
        ],
    )


def delete_document(document_id: int) -> None:
    _collection().delete(where={"document_id": document_id})


def search(
    user_id: int, query: str, k: int = 5, document_ids: list[int] | None = None
) -> list[Hit]:
    """Return the k chunks closest to the query by embedding similarity, best first."""
    where: dict = {"user_id": user_id}
    if document_ids:
        where = {"$and": [where, {"document_id": {"$in": list(document_ids)}}]}
    result = _collection().query(
        query_embeddings=embed([query]),
        n_results=k,
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    return [
        Hit(
            text=text,
            document_id=meta["document_id"],
            filename=meta["filename"],
            page=meta["page"] or None,
            distance=dist,
        )
        for text, meta, dist in zip(
            result["documents"][0], result["metadatas"][0], result["distances"][0]
        )
    ]
