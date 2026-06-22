import uuid
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict
from datetime import datetime

class MessageBase(BaseModel):
    sender: str  # 'user', 'assistant'
    content: str

class MessageCreate(MessageBase):
    pass

class MessageResponse(MessageBase):
    id: uuid.UUID
    conversation_id: uuid.UUID
    citations: Optional[List[Dict[str, Any]]] = None
    latency: Optional[float] = None
    retrieval_score: Optional[float] = None
    query_log_id: Optional[uuid.UUID] = None
    rating: Optional[int] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class ConversationBase(BaseModel):
    title: str

class ConversationCreate(BaseModel):
    kb_id: uuid.UUID
    title: Optional[str] = "New Chat"

class ConversationResponse(ConversationBase):
    id: uuid.UUID
    user_id: uuid.UUID
    kb_id: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class ConversationUpdate(BaseModel):
    title: str

class ChatQuery(BaseModel):
    conversation_id: uuid.UUID
    query: str
    web_search_enabled: Optional[bool] = False
    document_ids: Optional[List[uuid.UUID]] = None
