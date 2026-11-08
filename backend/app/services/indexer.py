import re
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

QDRANT_BATCH = 64   # vectors per upsert request
DB_BATCH = 200      # chunk rows per flush

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_text(text: str) -> str:
    """Drop NUL and other control characters. PDF text extraction often emits
    them, and Postgres refuses to store NUL in a text column."""
    return _CONTROL_CHARS.sub("", text)


class DocumentIndexer:
    def __init__(self):
        # Initialize Qdrant Client
        self.qclient = QdrantClient(
            url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY, timeout=30
        )
        logger.info(f"Connected to Qdrant vector database at {settings.QDRANT_URL}.")
        
        # Load local BGE Embedding model from shared registry
        self.embed_model = get_embedding_model()
        self.vector_dim = settings.EMBEDDING_DIM
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

    async def rebuild_collection_from_db(self, db, kb_id: uuid.UUID) -> int:
        """Re-create a KB's vector collection from the chunks held in Postgres.

        Postgres is the source of truth: it stores every chunk's content, page
        and point id, so the only thing missing from a lost collection is the
        vectors - and those are recomputable from the same text with the same
        model. The rebuild is faithful rather than approximate: identical point
        ids and payloads, so citations and filters keep working.

        This exists because a Qdrant Cloud free cluster is suspended after a
        week of inactivity and deleted after four. Rather than depend on a
        keepalive ping never being missed, treat the vector store as a derived
        index that can be rebuilt on demand.

        Returns the number of points written.
        """
        from sqlalchemy import select
        from app.models.knowledge import Document, DocumentChunk

        rows = (await db.execute(
            select(DocumentChunk, Document)
            .join(Document, Document.id == DocumentChunk.doc_id)
            .where(Document.kb_id == kb_id)
            .order_by(DocumentChunk.chunk_index)
        )).all()

        if not rows:
            logger.info(f"Nothing to rebuild for KB {kb_id}: no chunks in Postgres.")
            return 0

        collection_name = self.ensure_collection(kb_id)
        logger.info(f"Rebuilding {collection_name} from {len(rows)} Postgres chunks...")

        texts = [chunk.content for chunk, _ in rows]
        vectors = await asyncio.to_thread(
            self.embed_model.encode, texts, normalize_embeddings=True
        )

        points = []
        for (chunk, doc), vector in zip(rows, vectors):
            # Older chunks may predate qdrant_point_id; fall back to the row id
            # and persist it so later rebuilds stay stable.
            point_id = chunk.qdrant_point_id or str(chunk.id)
            if not chunk.qdrant_point_id:
                chunk.qdrant_point_id = point_id
            points.append(qmodels.PointStruct(
                id=point_id,
                vector=vector.tolist(),
                payload={
                    "chunk_id": point_id,
                    "doc_id": str(chunk.doc_id),
                    "kb_id": str(kb_id),
                    "content": chunk.content,
                    "page_number": chunk.page_number,
                    "filename": doc.filename,
                    "source": doc.filename,
                },
            ))

        # Batched: one upsert of a whole corpus can exceed the request limit.
        BATCH = 128
        for i in range(0, len(points), BATCH):
            self.qclient.upsert(collection_name=collection_name, points=points[i:i + BATCH])

        await db.commit()
        logger.info(f"Rebuilt {collection_name} with {len(points)} points.")
        return len(points)

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
            
            for j, part in enumerate(splits):
                # Put the separator back between parts only - appending it to
                # the last part added text that was never in the document.
                is_last = j == len(splits) - 1
                part_str = part + (separator if separator and not is_last else "")
                
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
            # chunk_overlap 0 must mean no overlap: prev[-0:] is the WHOLE
            # previous chunk, which used to double every chunk.
            if i == 0 or chunk_overlap <= 0:
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
        chunk_overlap: int = 200,
        report_progress: bool = True,
    ) -> Dict[str, Any]:
        """
        Processes parsed pages, chunks them, generates embeddings, and indexes in Qdrant & PostgreSQL.

        Reports live progress (chunking -> embedding batch by batch -> saving)
        to Redis so the UI can show a progress bar while this runs.
        """
        from app.services import progress
        def _report(stage, pct=None, msg=None):
            if report_progress:
                progress.report(str(doc_id), stage, pct, msg)
        # Fetch Document record
        result = await db.execute(select(Document).where(Document.id == doc_id))
        doc = result.scalar_one_or_none()
        if not doc:
            raise ValueError(f"Document with ID {doc_id} not found.")

        kb_id, filename = doc.kb_id, doc.filename
        # End the read transaction now. Embedding a large document takes
        # minutes on CPU, and hosted Postgres (Neon, poolers) closes
        # connections that sit idle inside a transaction - the final save then
        # failed with "connection is closed" for anything but small files.
        await db.commit()

        collection_name = self.ensure_collection(kb_id)
        
        # We will hold all PostgreSQL DocumentChunk objects and Qdrant points
        db_chunks = []
        qdrant_points = []
        
        total_chunks = 0
        embedding_latencies = []
        
        # Collect all chunk texts across all pages to batch embed them
        _report("chunking", msg=f"{len(parsed_pages)} page(s) read")
        all_chunks_info = []
        for page in parsed_pages:
            content = clean_text(page.get("content") or "")
            page_num = page["page_number"]
            if not content.strip():
                continue  # image-only / blank page
            chunks_text = self.split_text_recursive(content, chunk_size, chunk_overlap)
            for idx, text in enumerate(chunks_text):
                if not text.strip():
                    continue
                all_chunks_info.append({
                    "text": text,
                    "page_number": page_num
                })
                
        # Batch embed all chunks
        all_texts = [c["text"] for c in all_chunks_info]
        if not all_texts:
            raise ValueError(
                "No readable text was found in this document. If it is a scanned PDF, "
                "set LLAMAPARSE_API_KEY so it can be OCR'd, or upload a text-based version."
            )
        if all_texts:
            logger.info(f"DocumentIndexer: Batch embedding {len(all_texts)} chunks...")
            start_embed = time.time()
            # Encode in groups of batches so progress can be reported between
            # them. Each group is still vectorized internally (batch_size=32).
            _report("embedding", msg=f"0/{len(all_texts)} chunks embedded")
            group = 128
            encoded_batches = []
            for g in range(0, len(all_texts), group):
                part = await asyncio.to_thread(
                    self.embed_model.encode,
                    all_texts[g:g + group],
                    batch_size=32,
                    show_progress_bar=False,
                    normalize_embeddings=True
                )
                encoded_batches.extend(part)
                if report_progress:
                    progress.embedding_progress(str(doc_id), min(g + group, len(all_texts)), len(all_texts))
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
                            "kb_id": str(kb_id),
                            "content": chunk_info["text"],
                            "page_number": chunk_info["page_number"],
                            "filename": filename,
                            "source": filename
                        }
                    )
                )
                total_chunks += 1

        # Transaction block to ensure consistency between Qdrant and PostgreSQL
        _report("saving", msg=f"Saving {total_chunks} chunks")
        try:
            # Upsert vectors in batches: one request carrying every vector of a
            # large document is megabytes of JSON and can hit the client
            # timeout or the server's request-size limit.
            if qdrant_points:
                logger.info(f"Upserting {len(qdrant_points)} vectors to Qdrant collection {collection_name}...")
                for i in range(0, len(qdrant_points), QDRANT_BATCH):
                    batch = qdrant_points[i:i + QDRANT_BATCH]
                    await asyncio.to_thread(self.qclient.upsert, collection_name=collection_name, points=batch)

            # Fresh transaction for the write (the read one was closed above).
            result = await db.execute(select(Document).where(Document.id == doc_id))
            doc = result.scalar_one_or_none()
            if not doc:
                raise ValueError("The document was deleted while it was being indexed.")
            for i in range(0, len(db_chunks), DB_BATCH):
                db.add_all(db_chunks[i:i + DB_BATCH])
                await db.flush()

            doc.status = "indexed"
            doc.meta_info = {
                **(doc.meta_info or {}),
                "total_chunks": total_chunks,
                "embedding_model": settings.EMBEDDING_MODEL,
                "last_indexed_at": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            doc.meta_info.pop("error_msg", None)
            await db.commit()

        except Exception as e:
            logger.error(f"Failed to commit indexed document {filename}: {str(e)}")
            try:
                await db.rollback()
            except Exception:
                pass
            # Remove every vector this run wrote, whichever batch failed.
            try:
                self.qclient.delete(
                    collection_name=collection_name,
                    points_selector=qmodels.FilterSelector(filter=qmodels.Filter(must=[
                        qmodels.FieldCondition(key="doc_id", match=qmodels.MatchValue(value=str(doc_id)))
                    ]))
                )
                logger.info(f"Rolled back vectors of {doc_id} from Qdrant after the failure.")
            except Exception as rollback_err:
                logger.critical(f"Failed to rollback Qdrant vectors after DB failure: {str(rollback_err)}")
            raise e
        
        _report("done", msg=f"{total_chunks} chunks indexed")
        # New content: cached answers for this KB are no longer trustworthy.
        from app.services.answer_cache import bump_kb_version_sync
        bump_kb_version_sync(kb_id)
        avg_embed_latency = sum(embedding_latencies) / len(embedding_latencies) if embedding_latencies else 0.0
        logger.info(f"Indexed document {filename}. Total chunks: {total_chunks}. Avg embed latency: {avg_embed_latency:.4f}s")
        
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
        from app.services.answer_cache import bump_kb_version_sync
        await asyncio.to_thread(bump_kb_version_sync, doc.kb_id)
        logger.info(f"Deleted document {doc.filename} ({doc_id}) from database.")

document_indexer = DocumentIndexer()
