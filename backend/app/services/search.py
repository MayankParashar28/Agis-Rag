import uuid
import time
import math
from typing import List, Dict, Any, Tuple, Optional
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from sentence_transformers import SentenceTransformer, CrossEncoder
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.core.logging import logger
from app.models.knowledge import DocumentChunk, Document

class BM25OkapiLocal:
    """
    A lightweight local implementation of BM25Okapi for sparse text search.
    """
    def __init__(self, corpus: List[Dict[str, Any]], k1: float = 1.5, b: float = 0.75):
        self.corpus = corpus
        self.k1 = k1
        self.b = b
        self.doc_len = []
        self.avg_doc_len = 0.0
        self.doc_count = len(corpus)
        self.doc_freqs = []
        self.idf = {}
        self.words_map = {}
        
        self._initialize()

    def _tokenize(self, text: str) -> List[str]:
        return text.lower().split()

    def _initialize(self):
        total_len = 0
        df = {}
        
        for idx, doc in enumerate(self.corpus):
            tokens = self._tokenize(doc["content"])
            self.doc_len.append(len(tokens))
            total_len += len(tokens)
            
            frequencies = {}
            for token in tokens:
                frequencies[token] = frequencies.get(token, 0) + 1
            self.doc_freqs.append(frequencies)
            
            for token in frequencies.keys():
                df[token] = df.get(token, 0) + 1
                
        self.avg_doc_len = total_len / self.doc_count if self.doc_count > 0 else 0.0
        
        for word, freq in df.items():
            # Standard BM25 IDF
            self.idf[word] = math.log(1.0 + (self.doc_count - freq + 0.5) / (freq + 0.5))

    def get_scores(self, query: str) -> List[float]:
        query_tokens = self._tokenize(query)
        scores = [0.0] * self.doc_count
        
        for token in query_tokens:
            if token not in self.idf:
                continue
            
            idf_val = self.idf[token]
            for doc_idx in range(self.doc_count):
                tf = self.doc_freqs[doc_idx].get(token, 0)
                d_len = self.doc_len[doc_idx]
                
                # BM25 formulation
                num = tf * (self.k1 + 1.0)
                denom = tf + self.k1 * (1.0 - self.b + self.b * (d_len / self.avg_doc_len))
                scores[doc_idx] += idf_val * (num / denom)
                
        return scores

    def search(self, query: str, top_n: int = 50) -> List[Tuple[Dict[str, Any], float]]:
        if self.doc_count == 0:
            return []
        scores = self.get_scores(query)
        scored_docs = [(self.corpus[i], scores[i]) for i in range(self.doc_count) if scores[i] > 0.0]
        scored_docs.sort(key=lambda x: x[1], reverse=True)
        return scored_docs[:top_n]


class RetrievalPipeline:
    def __init__(self):
        # Qdrant client
        self.qclient = QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY)
        
        # Dense Embedding Model
        logger.info("RetrievalPipeline: Loading SentenceTransformer BAAI/bge-large-en-v1.5...")
        self.embed_model = SentenceTransformer("BAAI/bge-large-en-v1.5", device="cpu")
        
        # CrossEncoder Reranker
        logger.info("RetrievalPipeline: Loading CrossEncoder BAAI/bge-reranker-large...")
        self.reranker = CrossEncoder("BAAI/bge-reranker-large", device="cpu")
        logger.info("RetrievalPipeline: Models loaded successfully.")

    def _get_collection_name(self, kb_id: uuid.UUID) -> str:
        return f"kb_{str(kb_id).replace('-', '_')}"

    async def _fetch_all_kb_chunks(
        self, 
        db: AsyncSession, 
        kb_id: uuid.UUID, 
        document_ids: Optional[List[uuid.UUID]] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetches all chunks for a KB from PostgreSQL to run local BM25.
        """
        query = (
            select(DocumentChunk.content, DocumentChunk.page_number, DocumentChunk.chunk_index, Document.filename, DocumentChunk.id)
            .join(Document, Document.id == DocumentChunk.doc_id)
            .where(Document.kb_id == kb_id)
        )
        if document_ids:
            query = query.where(DocumentChunk.doc_id.in_(document_ids))
            
        result = await db.execute(query)
        chunks = []
        for row in result.all():
            chunks.append({
                "content": row[0],
                "page_number": row[1],
                "chunk_index": row[2],
                "filename": row[3],
                "source": row[3],
                "chunk_id": str(row[4])
            })
        return chunks

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
            # We can uniquely identify chunks by chunk_id
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
            # Find matching doc in payload or reuse
            rrf_scores[key] = rrf_scores.get(key, 0.0) + (1.0 / (k + rank + 1))
            
        # Re-assemble the combined corpus
        # Create map of keys to document details
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
            # Attach RRF score as similarity metric
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
        top_k: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Performs Hybrid Search (BM25 + Vector Search) and merges results.
        """
        # 1. Vector Search
        collection_name = self._get_collection_name(kb_id)
        
        # Verify collection exists
        collections = self.qclient.get_collections().collections
        if not any(c.name == collection_name for c in collections):
            return []

        # Generate query embedding
        query_vector = self.embed_model.encode(query, normalize_embeddings=True).tolist()
        
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

        # 2. Sparse BM25 Search
        kb_chunks = await self._fetch_all_kb_chunks(db, kb_id, document_ids)
        bm25_results = []
        if kb_chunks:
            bm25_model = BM25OkapiLocal(kb_chunks)
            bm25_hits = bm25_model.search(query, top_n=top_k)
            for chunk, score in bm25_hits:
                chunk_copy = chunk.copy()
                chunk_copy["score"] = score
                bm25_results.append(chunk_copy)

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
        Retrieves top 50 hybrid matches and reranks them to top 5 using BGE Reranker.
        """
        start_time = time.time()
        
        # Step 1: Hybrid Search (BM25 + Vector)
        hybrid_start = time.time()
        candidates = await self.search_hybrid(db, kb_id, query, document_ids, top_k=50)
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
        
        # BGE Reranker CrossEncoder outputs scores (can be sigmoid/logits)
        rerank_scores = self.reranker.predict(pairs).tolist()
        rerank_latency = time.time() - rerank_start
        
        # Attach rerank score and sort
        scored_candidates = []
        for idx, candidate in enumerate(candidates):
            c_copy = candidate.copy()
            c_copy["original_score"] = c_copy.get("score", c_copy.get("rrf_score", 0.0))
            c_copy["rerank_score"] = rerank_scores[idx]
            scored_candidates.append(c_copy)
            
        # Sort by rerank score descending
        scored_candidates.sort(key=lambda x: x["rerank_score"], reverse=True)
        top_5 = scored_candidates[:5]
        
        # Scale scores to similarity range [0, 1] for citations display
        # BGE reranker logits are usually unbounded. We can apply sigmoid to normalize.
        for c in top_5:
            # Sigmoid normalization
            c["similarity_score"] = round(1 / (1 + math.exp(-c["rerank_score"])), 4)

        return {
            "chunks": top_5,
            "candidates_pre_rerank": candidates[:10], # Return top 10 for retrieval visualization comparison
            "retrieval_latency": retrieval_latency,
            "rerank_latency": rerank_latency,
            "total_latency": time.time() - start_time
        }

retrieval_pipeline = RetrievalPipeline()
