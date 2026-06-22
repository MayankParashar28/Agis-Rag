import uuid
import time
from typing import List, Dict, Any
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
import asyncio

from app.core.config import settings
from app.core.logging import logger
from app.models.knowledge import Document, DocumentChunk
from app.services.models import get_embedding_model

class DocumentIndexer:
    def __init__(self):
        # Initialize Qdrant Client
        self.qclient = QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY)
        logger.info(f"Connected to Qdrant vector database at {settings.QDRANT_URL}.")
        
        # Load local BGE Embedding model from shared registry
        self.embed_model = get_embedding_model()
        self.vector_dim = 1024
        logger.info("Embedding model loaded successfully.")

    def _get_collection_name(self, kb_id: uuid.UUID) -> str:
        return f"kb_{str(kb_id).replace('-', '_')}"

    def ensure_collection(self, kb_id: uuid.UUID) -> str:
        collection_name = self._get_collection_name(kb_id)
        # Check if collection exists
        collections = self.qclient.get_collections().collections
        exists = any(c.name == collection_name for c in collections)
        
        if not exists:
            logger.info(f"Creating Qdrant collection {collection_name}...")
            self.qclient.create_collection(
                collection_name=collection_name,
                vectors_config=qmodels.VectorParams(
                    size=self.vector_dim,
                    distance=qmodels.Distance.COSINE
                )
            )
            logger.info(f"Collection {collection_name} created successfully.")
            
        # Ensure the payload index on doc_id exists (required by strict mode)
        try:
            logger.info(f"Ensuring payload index on 'doc_id' for collection {collection_name}...")
            self.qclient.create_payload_index(
                collection_name=collection_name,
                field_name="doc_id",
                field_schema=qmodels.PayloadSchemaType.KEYWORD
            )
            logger.info(f"Payload index on 'doc_id' for {collection_name} ensured.")
        except Exception as e:
            logger.warning(f"Failed to create payload index on 'doc_id': {str(e)}")
            
        return collection_name

    def split_text_recursive(self, text: str, chunk_size: int = 1000, chunk_overlap: int = 200) -> List[str]:
        """
        Splits text recursively using delimiters (paragraphs, sentences, words).
        """
        if len(text) <= chunk_size:
            return [text]

        delimiters = ["\n\n", "\n", ". ", " ", ""]
        chunks = []
        
        # Helper to recursively split text blocks
        def recursive_split(text_block: str, separator_idx: int) -> List[str]:
            if len(text_block) <= chunk_size:
                return [text_block]
            
            if separator_idx >= len(delimiters):
                # Hard cut if we ran out of delimiters
                return [text_block[i:i+chunk_size] for i in range(0, len(text_block), chunk_size)]
            
            separator = delimiters[separator_idx]
            splits = text_block.split(separator) if separator else list(text_block)
            
            result = []
            current_chunk = ""
            
            for part in splits:
                # Add separator back if not empty
                part_str = part + (separator if separator_idx < len(delimiters) - 1 else "")
                
                if len(current_chunk) + len(part_str) <= chunk_size:
                    current_chunk += part_str
                else:
                    if current_chunk:
                        result.append(current_chunk)
                    
                    # If the part itself is bigger than chunk_size, split it with next separator
                    if len(part_str) > chunk_size:
                        sub_splits = recursive_split(part_str, separator_idx + 1)
                        result.extend(sub_splits)
                        current_chunk = ""
                    else:
                        current_chunk = part_str
                        
            if current_chunk:
                result.append(current_chunk)
                
            return result

        raw_chunks = recursive_split(text, 0)
        
        # Apply overlapping
        overlapped_chunks = []
        for i, chunk in enumerate(raw_chunks):
            if i == 0:
                overlapped_chunks.append(chunk)
            else:
                # Add overlap from previous chunk if possible
                prev_chunk = raw_chunks[i-1]
                overlap_text = prev_chunk[-chunk_overlap:] if len(prev_chunk) >= chunk_overlap else prev_chunk
                overlapped_chunks.append(overlap_text + chunk)
                
        return overlapped_chunks

    async def index_document(
        self, 
        db: AsyncSession, 
        doc_id: uuid.UUID, 
        parsed_pages: List[Dict[str, Any]],
        chunk_size: int = 1000,
        chunk_overlap: int = 200
    ) -> Dict[str, Any]:
        """
        Processes parsed pages, chunks them, generates embeddings, and indexes in Qdrant & PostgreSQL.
        """
        # Fetch Document record
        result = await db.execute(select(Document).where(Document.id == doc_id))
        doc = result.scalar_one_or_none()
        if not doc:
            raise ValueError(f"Document with ID {doc_id} not found.")

        collection_name = self.ensure_collection(doc.kb_id)
        
        # We will hold all PostgreSQL DocumentChunk objects and Qdrant points
        db_chunks = []
        qdrant_points = []
        
        total_chunks = 0
        embedding_latencies = []
        
        # Collect all chunk texts across all pages to batch embed them
        all_chunks_info = []
        for page in parsed_pages:
            content = page["content"]
            page_num = page["page_number"]
            chunks_text = self.split_text_recursive(content, chunk_size, chunk_overlap)
            for idx, text in enumerate(chunks_text):
                all_chunks_info.append({
                    "text": text,
                    "page_number": page_num
                })
                
        # Batch embed all chunks
        all_texts = [c["text"] for c in all_chunks_info]
        if all_texts:
            logger.info(f"DocumentIndexer: Batch embedding {len(all_texts)} chunks...")
            start_embed = time.time()
            # Encode in batches to leverage vectorization & PyTorch enhancements
            encoded_batches = await asyncio.to_thread(
                self.embed_model.encode, 
                all_texts, 
                batch_size=32, 
                show_progress_bar=False,
                normalize_embeddings=True
            )
            embed_latency = time.time() - start_embed
            # Calculate average per-chunk latency for tracking
            avg_chunk_latency = embed_latency / len(all_texts)
            embedding_latencies = [avg_chunk_latency] * len(all_texts)
            
            # Reconstruct DB chunks and Qdrant points
            for i, chunk_info in enumerate(all_chunks_info):
                chunk_id = uuid.uuid4()
                qdrant_point_id = str(chunk_id)
                vector = encoded_batches[i].tolist()
                
                # Relational DB DocumentChunk
                db_chunk = DocumentChunk(
                    id=chunk_id,
                    doc_id=doc_id,
                    content=chunk_info["text"],
                    page_number=chunk_info["page_number"],
                    chunk_index=total_chunks,
                    qdrant_point_id=qdrant_point_id
                )
                db_chunks.append(db_chunk)
                
                # Qdrant Point
                qdrant_points.append(
                    qmodels.PointStruct(
                        id=qdrant_point_id,
                        vector=vector,
                        payload={
                            "chunk_id": qdrant_point_id,
                            "doc_id": str(doc_id),
                            "kb_id": str(doc.kb_id),
                            "content": chunk_info["text"],
                            "page_number": chunk_info["page_number"],
                            "filename": doc.filename,
                            "source": doc.filename
                        }
                    )
                )
                total_chunks += 1

        # Transaction block to ensure consistency between Qdrant and PostgreSQL
        try:
            # Upsert vectors to Qdrant
            if qdrant_points:
                logger.info(f"Upserting {len(qdrant_points)} vectors to Qdrant collection {collection_name}...")
                self.qclient.upsert(
                    collection_name=collection_name,
                    points=qdrant_points
                )
                
            # Bulk save DB chunks
            db.add_all(db_chunks)
            
            # Update Document status
            doc.status = "indexed"
            doc.meta_info = {
                **(doc.meta_info or {}),
                "total_chunks": total_chunks,
                "embedding_model": "BAAI/bge-large-en-v1.5",
                "last_indexed_at": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            await db.commit()
            
        except Exception as e:
            logger.error(f"Failed to commit indexed document {doc.filename}: {str(e)}")
            await db.rollback()
            # Rollback Qdrant inserts
            if qdrant_points:
                point_ids = [p.id for p in qdrant_points]
                try:
                    self.qclient.delete(
                        collection_name=collection_name,
                        points_selector=qmodels.PointIdsList(points=point_ids)
                    )
                    logger.info(f"Rolled back {len(point_ids)} vectors from Qdrant due to DB failure.")
                except Exception as rollback_err:
                    logger.critical(f"Failed to rollback Qdrant vectors after DB failure: {str(rollback_err)}")
            raise e
        
        avg_embed_latency = sum(embedding_latencies) / len(embedding_latencies) if embedding_latencies else 0.0
        logger.info(f"Indexed document {doc.filename}. Total chunks: {total_chunks}. Avg embed latency: {avg_embed_latency:.4f}s")
        
        return {
            "total_chunks": total_chunks,
            "average_embedding_latency": avg_embed_latency
        }

    async def delete_document(self, db: AsyncSession, doc_id: uuid.UUID) -> None:
        """
        Deletes document chunks from PostgreSQL and Qdrant vector database.
        """
        # Fetch Document record
        result = await db.execute(select(Document).where(Document.id == doc_id))
        doc = result.scalar_one_or_none()
        if not doc:
            return
            
        collection_name = self._get_collection_name(doc.kb_id)
        
        # Delete vectors from Qdrant
        try:
            logger.info(f"Deleting vectors for document {doc_id} from Qdrant collection {collection_name}...")
            self.qclient.delete(
                collection_name=collection_name,
                points_selector=qmodels.FilterSelector(
                    filter=qmodels.Filter(
                        must=[
                            qmodels.FieldCondition(
                                key="doc_id",
                                match=qmodels.MatchValue(value=str(doc_id))
                            )
                        ]
                    )
                )
            )
        except Exception as e:
            logger.error(f"Error deleting vectors from Qdrant: {str(e)}")
            
        # Delete document chunks from PostgreSQL (cascaded delete handled by ForeignKey relation in DB schema)
        await db.execute(delete(Document).where(Document.id == doc_id))
        await db.commit()
        logger.info(f"Deleted document {doc.filename} ({doc_id}) from database.")

document_indexer = DocumentIndexer()
