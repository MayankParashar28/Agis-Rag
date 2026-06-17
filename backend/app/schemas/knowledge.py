import uuid
from typing import Optional, Dict, Any
from pydantic import BaseModel, ConfigDict
from datetime import datetime

class KnowledgeBaseBase(BaseModel):
    name: str
    description: Optional[str] = None
    embedding_model: Optional[str] = "BAAI/bge-large-en-v1.5"

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

    model_config = ConfigDict(from_attributes=True)
