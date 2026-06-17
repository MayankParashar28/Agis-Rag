import uuid
import time
import json
import asyncio
from datetime import datetime
from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException, status, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db, SessionLocal
from app.api.v1.auth import get_current_active_user
from app.models.auth import User
from app.models.metrics import Conversation, Message, QueryLog
from app.models.knowledge import KnowledgeBase
from app.schemas.chat import (
    ConversationCreate,
    ConversationResponse,
    ConversationUpdate,
    MessageResponse,
    ChatQuery
)
from app.services.agent import (
    classify_query_node,
    retrieve_context_node,
    rerank_context_node,
    self_evaluate_node,
    synthesize_context_fallback
)
from app.services.memory import chat_memory
from app.core.config import settings
from app.core.logging import logger

router = APIRouter()

@router.get("/conversations", response_model=List[ConversationResponse])
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == current_user.id)
        .order_by(Conversation.updated_at.desc())
    )
    return result.scalars().all()


@router.post("/conversations", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    conv_in: ConversationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    # Verify KB ownership if set
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == conv_in.kb_id,
            KnowledgeBase.user_id == current_user.id
        )
    )
    kb = result.scalar_one_or_none()
    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge base not found or access denied."
        )

    db_obj = Conversation(
        user_id=current_user.id,
        kb_id=conv_in.kb_id,
        title=conv_in.title or "New Chat"
    )
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj


@router.get("/conversations/{conv_id}/messages", response_model=List[MessageResponse])
async def list_messages(
    conv_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    # Verify conversation ownership
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_id,
            Conversation.user_id == current_user.id
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found or access denied."
        )

    msg_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at.asc())
    )
    return msg_result.scalars().all()


# --- SSE Streaming Response Generator ---
async def stream_agentic_rag(
    query_in: ChatQuery, 
    user_id: uuid.UUID,
    kb_id: uuid.UUID
):
    total_start = time.time()
    
    # We open our own DB session for the duration of the stream
    async with SessionLocal() as db:
        # Step 1: Query Analysis & Classification
        yield f"data: {json.dumps({'event': 'status', 'message': 'Classifying query and planning retrieval...'})}\n\n"
        await asyncio.sleep(0.1) # small pause for visual flow
        
        state = {
            "query": query_in.query,
            "kb_id": kb_id,
            "db_session": db,
            "web_search_enabled": query_in.web_search_enabled,
            "needs_web_search": False,
            "retrieved_chunks": [],
            "reranked_chunks": [],
            "response": "",
            "citations": [],
            "confidence_score": 0.0,
            "retry_count": 0,
            "revised_query": query_in.query,
            "latency_breakdown": {},
            "document_ids": query_in.document_ids
        }
        
        # Run classification
        class_res = await classify_query_node(state)
        state.update(class_res)
        
        # Step 2: Context Retrieval
        search_source = "Knowledge Base + Web Search" if state["needs_web_search"] else "Knowledge Base"
        yield f"data: {json.dumps({'event': 'status', 'message': f'Searching {search_source}...'})}\n\n"
        
        ret_res = await retrieve_context_node(state)
        state.update(ret_res)
        
        # Step 3: Reranking
        retrieved_count = len(state["retrieved_chunks"])
        yield f"data: {json.dumps({'event': 'status', 'message': f'Found {retrieved_count} candidate chunks. Reranking with BGE Reranker...'})}\n\n"
        await asyncio.sleep(0.1)
        
        rerank_res = await rerank_context_node(state)
        state.update(rerank_res)
        
        # Yield retrieval metrics for visualizer before LLM generation
        yield f"data: {json.dumps({'event': 'retrieval_debug', 'candidates_pre_rerank': state['retrieved_chunks'][:10], 'reranked_chunks': state['reranked_chunks']})}\n\n"
        
        # Step 4: Stream Response Generation
        yield f"data: {json.dumps({'event': 'status', 'message': 'Generating response...'})}\n\n"
        
        # Prepare context and prompt
        context_str = ""
        citations = []
        for idx, chunk in enumerate(state["reranked_chunks"]):
            context_str += f"[Source {idx+1}] File: {chunk['filename']}, Page: {chunk.get('page_number', 'N/A')}\nContent: {chunk['content']}\n\n"
            citations.append({
                "source_doc": chunk["filename"],
                "page": chunk.get("page_number", 1),
                "score": chunk.get("similarity_score", 0.0)
            })
            
        system_prompt = (
            "You are an expert Enterprise AI assistant. Answer the query using ONLY the provided sources. "
            "Cite your sources exactly when presenting facts. If the sources do not contain the answer, "
            "state that you cannot find the answer in the provided documents.\n\n"
            f"Sources:\n{context_str}"
        )
        
        full_response_text = ""
        gen_start = time.time()
        
        if settings.GEMINI_API_KEY:
            try:
                import openai
                client = openai.AsyncOpenAI(
                    api_key=settings.GEMINI_API_KEY,
                    base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
                )
                stream = await client.chat.completions.create(
                    model=settings.GEMINI_MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": query_in.query}
                    ],
                    temperature=0.2,
                    stream=True
                )
                
                # Stream tokens
                async for chunk in stream:
                    token = chunk.choices[0].delta.content or ""
                    if token:
                        full_response_text += token
                        yield f"data: {json.dumps({'event': 'token', 'text': token})}\n\n"
                        
            except Exception as e:
                logger.error(f"Gemini Stream Generation API error: {str(e)}")
                full_response_text = f"Error generating answer via Gemini. Falling back to local synthesis.\n\nContext:\n{context_str[:500]}..."
                yield f"data: {json.dumps({'event': 'token', 'text': full_response_text})}\n\n"
        elif settings.OPENAI_API_KEY:
            try:
                import openai
                client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
                stream = await client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": query_in.query}
                    ],
                    temperature=0.2,
                    stream=True
                )
                
                # Stream tokens
                async for chunk in stream:
                    token = chunk.choices[0].delta.content or ""
                    if token:
                        full_response_text += token
                        yield f"data: {json.dumps({'event': 'token', 'text': token})}\n\n"
                        
            except Exception as e:
                logger.error(f"OpenAI Stream Generation API error: {str(e)}")
                full_response_text = f"Error generating answer via OpenAI. Falling back to local synthesis.\n\nContext:\n{context_str[:500]}..."
                yield f"data: {json.dumps({'event': 'token', 'text': full_response_text})}\n\n"
        else:
            # Local/offline fallback streaming simulation
            fallback_text = synthesize_context_fallback(query_in.query, state["reranked_chunks"])
            # Stream fallback text character by character or word by word to simulate streaming
            words = fallback_text.split(" ")
            for w in words:
                token = w + " "
                full_response_text += token
                yield f"data: {json.dumps({'event': 'token', 'text': token})}\n\n"
                await asyncio.sleep(0.02)
                
        gen_latency = time.time() - gen_start
        state["response"] = full_response_text
        state["citations"] = citations
        state["latency_breakdown"]["generation"] = gen_latency
        
        # Step 5: Self Evaluation
        yield f"data: {json.dumps({'event': 'status', 'message': 'Evaluating faithfulness and accuracy...'})}\n\n"
        await asyncio.sleep(0.1)
        
        eval_res = await self_evaluate_node(state)
        state.update(eval_res)
        
        total_latency = time.time() - total_start
        avg_retrieval_score = sum(c.get("similarity_score", 0.0) for c in state["reranked_chunks"]) / len(state["reranked_chunks"]) if state["reranked_chunks"] else 0.0
        
        # Step 6: Log Metrics & Store in PG + Redis
        # Insert User Message
        user_msg = Message(
            conversation_id=query_in.conversation_id,
            sender="user",
            content=query_in.query
        )
        # Insert Assistant Message
        assistant_msg = Message(
            conversation_id=query_in.conversation_id,
            sender="assistant",
            content=full_response_text,
            citations=citations,
            latency=total_latency,
            retrieval_score=avg_retrieval_score
        )
        
        # Save Log details to PostgreSQL `query_logs` for dashboards
        query_log = QueryLog(
            user_id=user_id,
            query=query_in.query,
            latency=total_latency,
            embedding_latency=state["latency_breakdown"].get("retrieval", 0.1) * 0.3, # approximate embedding part
            retrieval_latency=state["latency_breakdown"].get("retrieval", 0.1) * 0.7,
            hallucination_rate=round(100.0 - state["confidence_score"], 2),
            retrieval_score=avg_retrieval_score
        )
        
        db.add(user_msg)
        db.add(assistant_msg)
        db.add(query_log)
        
        # Update conversation updated_at
        conv_res = await db.execute(select(Conversation).where(Conversation.id == query_in.conversation_id))
        conv = conv_res.scalar_one_or_none()
        if conv:
            conv.updated_at = func.now() if 'func' in globals() else datetime.now()
            
        await db.commit()
        
        # Save to Redis memory for session continuity
        await chat_memory.add_message(str(query_in.conversation_id), {"sender": "user", "content": query_in.query})
        await chat_memory.add_message(str(query_in.conversation_id), {"sender": "assistant", "content": full_response_text, "citations": citations})
        
        # Yield final metadata packet
        yield f"data: {json.dumps({'event': 'metadata', 'query_log_id': str(query_log.id), 'citations': citations, 'confidence_score': state['confidence_score'], 'latency': total_latency, 'latency_breakdown': state['latency_breakdown']})}\n\n"
        yield "data: [DONE]\n\n"


@router.post("/message")
async def send_message(
    query_in: ChatQuery,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    # 1. Verify user owns the conversation and get its kb_id
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == query_in.conversation_id,
            Conversation.user_id == current_user.id
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found or access denied."
        )

    # Stream the agentic RAG response
    return StreamingResponse(
        stream_agentic_rag(query_in, current_user.id, conv.kb_id),
        media_type="text/event-stream"
    )


@router.put("/conversations/{conv_id}", response_model=ConversationResponse)
async def update_conversation(
    conv_id: uuid.UUID,
    conv_in: ConversationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_id,
            Conversation.user_id == current_user.id
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found or access denied."
        )
    
    conv.title = conv_in.title
    conv.updated_at = func.now()
    await db.commit()
    await db.refresh(conv)
    return conv


@router.delete("/conversations/{conv_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conv_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_id,
            Conversation.user_id == current_user.id
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found or access denied."
        )
        
    await db.delete(conv)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
