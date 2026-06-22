import uuid
import time
import math
from typing import List, Dict, Any, Tuple, Optional
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, func

from app.core.config import settings
from app.core.logging import logger
from app.models.knowledge import DocumentChunk, Document
from app.services.models import get_embedding_model, get_reranker


class RetrievalPipeline:
    def __init__(self):
        # Qdrant client
        self.qclient = QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY)
        
        # Dense Embedding Model and CrossEncoder Reranker from shared registry
        self.embed_model = get_embedding_model()
        self.reranker = get_reranker()
        logger.info("RetrievalPipeline: Shared models loaded successfully.")

    def _get_collection_name(self, kb_id: uuid.UUID) -> str:
        return f"kb_{str(kb_id).replace('-', '_')}"

    def reciprocal_rank_fusion(
        self, 
        vector_results: List[Dict[str, Any]], 
        bm25_results: List[Dict[str, Any]], 
        k: int = 60
    ) -> List[Dict[str, Any]]:
        """
        Combines search lists using Reciprocal Rank Fusion (RRF).
        """
        rrf_scores = {}
        
        # Helper to compute key
        def get_key(doc: Dict[str, Any]) -> str:
            if "chunk_id" in doc:
                return str(doc["chunk_id"])
            return f"{doc['filename']}_{doc['page_number']}_{doc.get('chunk_index', 0)}"

        # Score vector results
        for rank, doc in enumerate(vector_results):
            key = get_key(doc)
            rrf_scores[key] = rrf_scores.get(key, 0.0) + (1.0 / (k + rank + 1))

        # Score BM25 results
        for rank, doc in enumerate(bm25_results):
            key = get_key(doc)
            rrf_scores[key] = rrf_scores.get(key, 0.0) + (1.0 / (k + rank + 1))
            
        # Re-assemble the combined corpus
        doc_map = {}
        for doc in vector_results:
            doc_map[get_key(doc)] = doc
        for doc in bm25_results:
            doc_map[get_key(doc)] = doc

        # Sort by RRF score
        sorted_keys = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)
        
        fused_results = []
        for key in sorted_keys:
            doc = doc_map[key]
            doc_copy = doc.copy()
            doc_copy["rrf_score"] = rrf_scores[key]
            fused_results.append(doc_copy)
            
        return fused_results

    async def search_hybrid(
        self, 
        db: AsyncSession, 
        kb_id: uuid.UUID, 
        query: str, 
        document_ids: Optional[List[uuid.UUID]] = None,
        top_k: int = 15
    ) -> List[Dict[str, Any]]:
        """
        Performs Hybrid Search (PostgreSQL FTS + Vector Search) and merges results.
        """
        # 1. Vector Search
        collection_name = self._get_collection_name(kb_id)
        
        # Verify collection exists
        collections = self.qclient.get_collections().collections
        if not any(c.name == collection_name for c in collections):
            return []

        # Generate query embedding asynchronously in threadpool to prevent blocking the event loop
        import asyncio
        query_vector = await asyncio.to_thread(
            self.embed_model.encode, query, normalize_embeddings=True
        )
        query_vector = query_vector.tolist()
        
        qfilter = None
        if document_ids:
            qfilter = qmodels.Filter(
                should=[
                    qmodels.FieldCondition(
                        key="doc_id",
                        match=qmodels.MatchValue(value=str(doc_id))
                    )
                    for doc_id in document_ids
                ]
            )
            
        query_res = self.qclient.query_points(
            collection_name=collection_name,
            query=query_vector,
            query_filter=qfilter,
            limit=top_k
        )
        vector_hits = query_res.points
        
        vector_results = []
        for hit in vector_hits:
            doc_info = hit.payload.copy()
            doc_info["score"] = hit.score
            vector_results.append(doc_info)

        # 2. Sparse Search using PostgreSQL Full-Text Search (PG FTS)
        bm25_results = []
        try:
            fts_query = (
                select(
                    DocumentChunk.content,
                    DocumentChunk.page_number,
                    DocumentChunk.chunk_index,
                    Document.filename,
                    DocumentChunk.id,
                    func.ts_rank_cd(
                        func.to_tsvector('english', DocumentChunk.content),
                        func.plainto_tsquery('english', query)
                    ).label("rank")
                )
                .join(Document, Document.id == DocumentChunk.doc_id)
                .where(
                    Document.kb_id == kb_id,
                    func.to_tsvector('english', DocumentChunk.content).op("@@")(
                        func.plainto_tsquery('english', query)
                    )
                )
            )
            if document_ids:
                fts_query = fts_query.where(DocumentChunk.doc_id.in_(document_ids))
                
            fts_query = fts_query.order_by(text("rank DESC")).limit(top_k)
            
            result = await db.execute(fts_query)
            for row in result.all():
                bm25_results.append({
                    "content": row[0],
                    "page_number": row[1],
                    "chunk_index": row[2],
                    "filename": row[3],
                    "source": row[3],
                    "chunk_id": str(row[4]),
                    "score": float(row[5])
                })
        except Exception as e:
            logger.error(f"PostgreSQL FTS failed: {str(e)}")
            bm25_results = []

        # 3. Fuse rankings
        fused = self.reciprocal_rank_fusion(vector_results, bm25_results)
        return fused[:top_k]

    async def retrieve_and_rerank(
        self, 
        db: AsyncSession, 
        kb_id: uuid.UUID, 
        query: str,
        document_ids: Optional[List[uuid.UUID]] = None
    ) -> Dict[str, Any]:
        """
        Retrieves top 15 hybrid matches and reranks them to top 5 using BGE Reranker.
        """
        start_time = time.time()
        
        # Step 1: Hybrid Search (PG FTS + Vector)
        hybrid_start = time.time()
        candidates = await self.search_hybrid(db, kb_id, query, document_ids, top_k=15)
        retrieval_latency = time.time() - hybrid_start
        
        if not candidates:
            return {
                "chunks": [],
                "retrieval_latency": retrieval_latency,
                "rerank_latency": 0.0,
                "total_latency": time.time() - start_time
            }

        # Step 2: BGE Reranking
        rerank_start = time.time()
        passages = [c["content"] for c in candidates]
        pairs = [[query, p] for p in passages]
        
        import asyncio
        rerank_scores = await asyncio.to_thread(self.reranker.predict, pairs)
        rerank_scores = rerank_scores.tolist()
        rerank_latency = time.time() - rerank_start
        
        # Attach rerank score and sort
        scored_candidates = []
        for idx, candidate in enumerate(candidates):
            c_copy = candidate.copy()
            c_copy["original_score"] = c_copy.get("score", c_copy.get("rrf_score", 0.0))
            c_copy["rerank_score"] = rerank_scores[idx]
            scored_candidates.append(c_copy)
            
        scored_candidates.sort(key=lambda x: x["rerank_score"], reverse=True)
        top_5 = scored_candidates[:5]
        
        for c in top_5:
            # Sigmoid normalization
            c["similarity_score"] = round(1 / (1 + math.exp(-c["rerank_score"])), 4)

        return {
            "chunks": top_5,
            "candidates_pre_rerank": candidates[:10],
            "retrieval_latency": retrieval_latency,
            "rerank_latency": rerank_latency,
            "total_latency": time.time() - start_time
        }

retrieval_pipeline = RetrievalPipeline()
