import uuid
from typing import Optional, Dict, Any
from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime

from app.core.config import settings

class KnowledgeBaseBase(BaseModel):
    name: str
    description: Optional[str] = None
    # Defaults to the configured model rather than a literal, so overriding
    # EMBEDDING_MODEL does not leave new knowledge bases recording a stale name.
    embedding_model: Optional[str] = Field(default_factory=lambda: settings.EMBEDDING_MODEL)

class KnowledgeBaseCreate(KnowledgeBaseBase):
    pass

class KnowledgeBaseResponse(KnowledgeBaseBase):
    id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class KnowledgeBaseStats(BaseModel):
    total_documents: int
    total_chunks: int
    embedding_model: str
    vector_count: int
    last_indexed_date: Optional[datetime] = None

class DocumentResponse(BaseModel):
    id: uuid.UUID
    kb_id: uuid.UUID
    filename: str
    file_type: str
    file_size: int
    status: str
    meta_info: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentChunkResponse(BaseModel):
    id: uuid.UUID
    doc_id: uuid.UUID
    content: str
    page_number: Optional[int] = None
    chunk_index: Optional[int] = None
    qdrant_point_id: Optional[str] = None
    section: Optional[str] = None
    kind: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
