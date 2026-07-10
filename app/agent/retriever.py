"""
Retriever: query-time component used by the agent.

Two collections:
  - schema_docs : top-k tables relevant to the user's question
  - few_shots   : top-k example NL→SQL pairs

Both use cosine similarity over OpenAI embeddings.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import chromadb
from chromadb.config import Settings as ChromaSettings
from openai import OpenAI

from app.config import settings


@dataclass
class SchemaHit:
    table: str
    doc: str
    score: float


@dataclass
class FewShotHit:
    question: str
    sql: str
    category: str
    score: float


class Retriever:
    """Singleton-ish; instantiate once per process."""

    def __init__(self) -> None:
        self._oai = OpenAI(api_key=settings.openai_api_key)
        self._client = chromadb.PersistentClient(
            path=settings.chroma_dir,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._schema = self._client.get_collection("schema_docs")
        self._fs = self._client.get_collection("few_shots")

    # ---------------------------------------------------------
    def _embed(self, text: str) -> list[float]:
        resp = self._oai.embeddings.create(
            model=settings.openai_embedding_model,
            input=[text],
        )
        return resp.data[0].embedding

    # ---------------------------------------------------------
    def retrieve_schema(self, query: str, k: Optional[int] = None) -> list[SchemaHit]:
        k = k or settings.top_k_schema
        emb = self._embed(query)
        res = self._schema.query(query_embeddings=[emb], n_results=k)
        hits: list[SchemaHit] = []
        for table_meta, doc, dist in zip(res["metadatas"][0], res["documents"][0], res["distances"][0]):
            hits.append(SchemaHit(table=table_meta["table"], doc=doc, score=1 - dist))
        return hits

    def retrieve_few_shots(self, query: str, k: Optional[int] = None) -> list[FewShotHit]:
        k = k or settings.top_k_fewshots
        emb = self._embed(query)
        res = self._fs.query(query_embeddings=[emb], n_results=k)
        hits: list[FewShotHit] = []
        for q, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
            hits.append(FewShotHit(
                question=q, sql=meta["sql"], category=meta["category"], score=1 - dist,
            ))
        return hits


# -------------------------------------------------------------
_retriever: Optional[Retriever] = None


def get_retriever() -> Retriever:
    global _retriever
    if _retriever is None:
        _retriever = Retriever()
    return _retriever
