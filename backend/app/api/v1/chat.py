import uuid
import time
import json
import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException, status, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case

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
from app.services.llm_providers import provider_chain, mark_exhausted
from app.services.agent import (
    classify_query_node,
    retrieve_context_node,
    rerank_context_node,
    self_evaluate_node,
    synthesize_context_fallback
)
from app.services.memory import chat_memory
from app.services import answer_cache
from app.services.guard import build_context, SOURCE_RULES
from app.services import llm as llm_helper
from app.services import audit
from app.services.followups import suggest_follow_ups
from app.services.export import conversation_to_markdown
from app.core.config import settings
import re

from app.core.logging import logger
from app.services.llm_errors import describe_llm_failure

router = APIRouter()
from app.services.timestamps import turn_stamps as _stamps  # noqa: E402


def _chronological():
    # Older rows share a timestamp per turn; break the tie question-first.
    return (Message.created_at.asc(), case((Message.sender == "user", 0), else_=1))


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


@router.get("/conversations", response_model=List[ConversationResponse])
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """The caller's conversations, most recently active first.

    The client has always called this; the route did not exist, so every
    request returned 405 and the sidebar rendered empty. Conversations were
    being created and persisted correctly - they were simply unlistable, which
    looked like the history being wiped on every refresh.
    """
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == current_user.id)
        .order_by(Conversation.updated_at.desc().nullslast(),
                  Conversation.created_at.desc())
    )
    return result.scalars().all()


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

    from app.models.metrics import QueryLog
    msg_result = await db.execute(
        select(Message, QueryLog.rating)
        .outerjoin(QueryLog, Message.query_log_id == QueryLog.id)
        .where(Message.conversation_id == conv_id)
        .order_by(*_chronological())
    )
    
    messages_out = []
    for row in msg_result.all():
        msg_obj, rating = row
        msg_dict = {
            "id": msg_obj.id,
            "conversation_id": msg_obj.conversation_id,
            "sender": msg_obj.sender,
            "content": msg_obj.content,
            "citations": msg_obj.citations,
            "latency": msg_obj.latency,
            "retrieval_score": msg_obj.retrieval_score,
            "created_at": msg_obj.created_at,
            "query_log_id": msg_obj.query_log_id,
            "rating": rating
        }
        messages_out.append(msg_dict)
    return messages_out


def build_citation(idx: int, chunk: Dict[str, Any]) -> Dict[str, Any]:
    """A citation the UI can open: which document, which passage, a preview."""
    source = chunk.get("source")
    citation = {
        "index": idx + 1,
        "source_doc": chunk.get("filename", "unknown"),
        "page": chunk.get("page_number", 1),
        "score": chunk.get("similarity_score", 0.0),
        "snippet": (chunk.get("content") or "")[:600],
    }
    if chunk.get("doc_id"):
        citation["doc_id"] = str(chunk["doc_id"])
    if chunk.get("chunk_id"):
        citation["chunk_id"] = str(chunk["chunk_id"])
    # Carry the source URL for web results. Without it a web citation names a
    # page the reader has no way to open or check.
    if isinstance(source, str) and source.startswith(("http://", "https://")):
        citation["url"] = source
    return citation


async def _serve_cached_answer(db, query_in: ChatQuery, user_id: uuid.UUID, hit: Dict[str, Any], total_start: float, kb_id=None):
    """Stream a cached answer and record it like any other turn."""
    yield f"data: {json.dumps({'event': 'status', 'message': 'Found a matching answer from an earlier question...'})}\n\n"
    answer = hit["answer"]
    # Send in a few large pieces: instant, but still through the same token path.
    for i in range(0, len(answer), 400):
        yield f"data: {json.dumps({'event': 'token', 'text': answer[i:i + 400]})}\n\n"
    latency = time.time() - total_start
    citations = hit.get("citations", [])
    confidence = float(hit.get("confidence", 0.0))
    log_id = uuid.uuid4()
    asked_at, answered_at = _stamps(total_start)
    db.add(Message(conversation_id=query_in.conversation_id, sender="user", content=query_in.query, created_at=asked_at))
    db.add(Message(conversation_id=query_in.conversation_id, sender="assistant", content=answer, created_at=answered_at,
                   citations=citations, latency=latency,
                   retrieval_score=sum(c.get("score", 0.0) for c in citations) / len(citations) if citations else 0.0,
                   query_log_id=log_id))
    db.add(QueryLog(id=log_id, user_id=user_id, query=query_in.query, latency=latency,
                    embedding_latency=0.0, retrieval_latency=0.0,
                    hallucination_rate=round((100.0 - confidence) / 100.0, 4),
                    retrieval_score=0.0, kb_id=kb_id, cached=True, cost_usd=0.0, prompt_tokens=0, completion_tokens=0,
                    mode=query_in.mode or "detailed"))
    conv = (await db.execute(select(Conversation).where(Conversation.id == query_in.conversation_id))).scalar_one_or_none()
    if conv:
        conv.updated_at = func.now()
    await db.commit()
    await chat_memory.add_message(str(query_in.conversation_id), {"sender": "user", "content": query_in.query})
    await chat_memory.add_message(str(query_in.conversation_id), {"sender": "assistant", "content": answer, "citations": citations})
    yield f"data: {json.dumps({'event': 'metadata', 'query_log_id': str(log_id), 'citations': citations, 'confidence_score': round(confidence, 2), 'confidence_method': 'cached', 'cached': True, 'cache_similarity': hit.get('similarity'), 'latency': latency, 'latency_breakdown': {'cache': latency}})}\n\n"
    yield "data: [DONE]\n\n"


def _compare_instruction(chunks):
    names = []
    for c in chunks:
        n = c.get("filename")
        if n and n not in names:
            names.append(n)
    cols = " | ".join(names) if names else "each document"
    return (
        "6. The user wants a COMPARISON across these documents: " + ", ".join(names) + ".\n"
        "   Reply in this structure:\n"
        "   - A Markdown table whose first column is 'Aspect' followed by one column per document (" + cols + "), "
        "one row per point of comparison, citing [Source X] inside the cells. Write 'not stated' when a document has no information on that aspect.\n"
        "   - '**Key differences**': a short bullet list.\n"
        "   - '**Where they agree**': a short bullet list (or 'None found')."
    )


MODE_INSTRUCTIONS = {
    "quick": lambda chunks: "6. Answer in at most three sentences. No headings, no lists, just the direct answer with its citations.",
    "detailed": lambda chunks: "6. Give a complete answer. Use short headings or bullet points where they help, and include the specific figures, dates and names from the sources.",
    "compare": _compare_instruction,
}


@router.get("/conversations/{conv_id}/export")
async def export_conversation(
    conv_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Download a conversation as Markdown (citations become footnotes)."""
    conv = (await db.execute(select(Conversation).where(Conversation.id == conv_id, Conversation.user_id == current_user.id))).scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    msgs = (await db.execute(select(Message).where(Message.conversation_id == conv_id).order_by(*_chronological()))).scalars().all()
    kb_name = None
    if conv.kb_id:
        kb = (await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == conv.kb_id))).scalar_one_or_none()
        kb_name = kb.name if kb else None
    text = conversation_to_markdown(conv, msgs, kb_name)
    await audit.record(db, current_user, "conversation.export", "conversation", conv_id, {"title": conv.title, "messages": len(msgs)})
    safe = re.sub(r"[^\w\- ]+", "", conv.title).strip() or "conversation"
    return Response(content=text, media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{safe}.md"'})


# --- SSE Streaming Response Generator ---
async def stream_agentic_rag(
    query_in: ChatQuery, 
    user_id: uuid.UUID,
    kb_id: uuid.UUID
):
    total_start = time.time()
    
    # We open our own DB session for the duration of the stream
    async with SessionLocal() as db:
        # Step 0: Semantic answer cache. Only for the first question of a
        # conversation (follow-ups depend on earlier turns) and never for
        # web-search answers (those go stale).
        cache_embedding = None
        cache_eligible = False
        if settings.ANSWER_CACHE_ENABLED and not query_in.web_search_enabled and (query_in.mode or "detailed") == "detailed":
            prior = await chat_memory.get_history(str(query_in.conversation_id), limit=1)
            cache_eligible = not prior
        if cache_eligible:
            cache_embedding = await answer_cache.get_query_embedding(query_in.query)
            hit = await answer_cache.lookup(kb_id, query_in.query, cache_embedding, query_in.document_ids)
            if hit:
                async for event in _serve_cached_answer(db, query_in, user_id, hit, total_start, kb_id=kb_id):
                    yield event
                return

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
            "document_ids": query_in.document_ids,
            "mode": (query_in.mode or "detailed") if (query_in.mode in ("quick", "detailed", "compare")) else "detailed",
        }
        mode = state["mode"]
        usage_total = llm_helper.Usage()

        if mode == "compare" and len(query_in.document_ids or []) < 2:
            msg = "Compare mode needs at least two documents. Pick them in the document menu, then ask again."
            yield f"data: {json.dumps({'event': 'token', 'text': msg})}\n\n"
            yield f"data: {json.dumps({'event': 'metadata', 'citations': [], 'confidence_score': 0, 'latency': 0, 'latency_breakdown': {}, 'error': True})}\n\n"
            yield "data: [DONE]\n\n"
            return
        
        # Run classification
        class_res = await classify_query_node(state)
        state.update(class_res)
        
        # Step 2: Context Retrieval
        search_source = "Knowledge Base + Web Search" if state["needs_web_search"] else "Knowledge Base"
        yield f"data: {json.dumps({'event': 'status', 'message': f'Searching {search_source}...'})}\n\n"
        
        ret_res = await retrieve_context_node(state)
        state.update(ret_res)
        usage_total.add(state.get("helper_usage"))
        if state.get("sub_questions"):
            yield f"data: {json.dumps({'event': 'sub_questions', 'questions': state['sub_questions']})}\n\n"
            yield f"data: {json.dumps({'event': 'status', 'message': 'Searching as ' + str(len(state['sub_questions'])) + ' separate questions...'})}\n\n"
        
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
        # Prepare context and prompt
        context_str = ""
        citations = []
        
        # Filter chunks by rerank score to reduce hallucination (see RERANK_SCORE_THRESHOLD)
        threshold = settings.RERANK_SCORE_THRESHOLD
        relevant_chunks = [c for c in state["reranked_chunks"] if c.get("similarity_score", 0.0) >= threshold]

        # A cross-encoder scores how well a passage answers a QUESTION. Broad
        # instructions ("Summarize the key takeaways", "Show me any tables")
        # score near zero against every passage even when the passage is the
        # right one - the UI's own suggested prompts scored 3.7e-05 against a
        # chunk that contained the whole document.
        #
        # So an empty list after filtering means one of two different things,
        # and they must not be reported the same way:
        #   1. retrieval returned nothing at all  -> genuinely no information
        #   2. retrieval returned chunks, all below threshold -> weak match
        # Claiming "no relevant information" in case 2 is simply false; the
        # text was retrieved. Fall back to the best chunks and let the model
        # decide whether it can answer from them.
        weak_match = False
        if not relevant_chunks and state["reranked_chunks"]:
            weak_match = True
            relevant_chunks = state["reranked_chunks"][:settings.RERANK_TOP_N]
            logger.info(
                f"All {len(state['reranked_chunks'])} chunks scored below "
                f"{threshold}; proceeding with the top {len(relevant_chunks)} "
                f"as a weak match rather than reporting no information."
            )

        if not relevant_chunks:
            no_info_msg = "I could not find any relevant information in the uploaded documents to answer your question."
            yield f"data: {json.dumps({'event': 'token', 'text': no_info_msg})}\n\n"
            
            # Log to DB
            log_id = uuid.uuid4()
            user_msg = Message(
                conversation_id=query_in.conversation_id,
                sender="user",
                content=query_in.query,
                created_at=_stamps(total_start)[0],
            )
            assistant_msg = Message(
                conversation_id=query_in.conversation_id,
                sender="assistant",
                content=no_info_msg,
                created_at=_stamps(total_start)[1],
                citations=[],
                latency=time.time() - total_start,
                retrieval_score=0.0,
                query_log_id=log_id
            )
            query_log = QueryLog(
                id=log_id,
                user_id=user_id,
                query=query_in.query,
                latency=time.time() - total_start,
                embedding_latency=state["latency_breakdown"].get("embedding", 0.0),
                retrieval_latency=(
                    state["latency_breakdown"].get("vector_search", 0.0)
                    + state["latency_breakdown"].get("sparse_search", 0.0)
                ),
                hallucination_rate=0.0,  # 0% hallucination rate since "no info" is 100% faithful
                retrieval_score=0.0
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
            
            # Save to Redis
            await chat_memory.add_message(str(query_in.conversation_id), {"sender": "user", "content": query_in.query})
            await chat_memory.add_message(str(query_in.conversation_id), {"sender": "assistant", "content": no_info_msg, "citations": []})
            
            yield f"data: {json.dumps({'event': 'metadata', 'query_log_id': str(query_log.id), 'citations': [], 'confidence_score': 100.0, 'latency': time.time() - total_start, 'latency_breakdown': {}})}\n\n"
            yield "data: [DONE]\n\n"
            return
            
        # Sources go into the prompt tagged and with instruction-like text
        # neutralised, so an uploaded document cannot steer the assistant.
        context_str, injection_hits = build_context(relevant_chunks)
        if injection_hits:
            logger.warning(f"Prompt-injection guard removed {injection_hits} instruction-like span(s) from sources.")
        citations = [build_citation(idx, chunk) for idx, chunk in enumerate(relevant_chunks)]
            
        system_prompt = (
            "You are an expert Enterprise AI assistant. Answer the query using ONLY the facts explicitly mentioned in the provided sources. "
            "Follow these strict rules:\n"
            "1. Do NOT assume, extrapolate, or generalize facts not directly stated in the sources.\n"
            "2. Do NOT use any of your own outside or general training knowledge under any circumstances.\n"
            "3. If the sources do not contain the exact facts to answer the question, state clearly: 'I cannot find the answer in the provided documents.'\n"
            "4. Cite your sources exactly when presenting facts (e.g. at the end of the sentence use [Source X]).\n"
            "5. When a source contains a Markdown table, keep the relevant rows as a Markdown table in your answer instead of flattening them into prose.\n"
            f"{MODE_INSTRUCTIONS[mode](relevant_chunks)}\n\n"
            f"{SOURCE_RULES}\n\n"
            f"Sources:\n{context_str}"
        )
        
        full_response_text = ""
        gen_usage = None
        gen_start = time.time()
        
        # Fetch conversation history from Redis memory to prepend to LLM context
        history = await chat_memory.get_history(str(query_in.conversation_id), limit=6)
        formatted_history = []
        for msg in history:
            role = "user" if msg.get("sender") == "user" else "assistant"
            formatted_history.append({"role": role, "content": msg.get("content")})
        
        # Providers are tried in order rather than picked by whichever key
        # happens to be set. The previous if/elif meant a configured Gemini key
        # made the OpenAI branch unreachable, so an exhausted Gemini quota went
        # straight to local synthesis while a working OpenAI key sat unused.
        # Gemini leads because a single answer fits its free tier comfortably.
        providers = provider_chain()

        if providers:
            import openai

            answered = False
            last_failure = None

            for provider in providers:
                emitted = False
                try:
                    client = (
                        openai.AsyncOpenAI(
                            api_key=provider.api_key, base_url=provider.base_url
                        )
                        if provider.base_url
                        else openai.AsyncOpenAI(api_key=provider.api_key)
                    )
                    messages = [
                        {"role": "system", "content": system_prompt},
                        *formatted_history,
                        {"role": "user", "content": query_in.query}
                    ]
                    stream_kwargs = dict(model=provider.model, messages=messages, temperature=0.0, stream=True)
                    if provider.label == "OpenAI":
                        # Ask for the token count in the final chunk.
                        stream_kwargs["stream_options"] = {"include_usage": True}
                    stream = await client.chat.completions.create(**stream_kwargs)

                    reported_usage = None
                    async for chunk in stream:
                        if getattr(chunk, "usage", None):
                            reported_usage = chunk.usage
                        if not chunk.choices:
                            continue
                        token = chunk.choices[0].delta.content or ""
                        if token:
                            emitted = True
                            full_response_text += token
                            yield f"data: {json.dumps({'event': 'token', 'text': token})}\n\n"

                    gen_usage = llm_helper.usage_from_response(
                        provider.label, provider.model, reported_usage,
                        "".join(m["content"] for m in messages), full_response_text)
                    answered = True
                    break

                except Exception as e:
                    last_failure = describe_llm_failure(e, provider.label)
                    mark_exhausted(provider.label, e)
                    logger.error(f"{provider.label} stream generation failed: {e}")
                    # Tokens already on the wire cannot be unsent, so retrying
                    # with another provider here would splice two answers
                    # together. Keep the partial one instead.
                    if emitted:
                        answered = True
                        break

            if not answered:
                # Dumping the raw context with an "Error..." prefix was not a
                # synthesis and did not say what went wrong. Use the real local
                # synthesizer and name the actual cause - a quota clears on its
                # own, a bad key does not, and the user cannot tell them apart
                # from a generic failure message.
                full_response_text = synthesize_context_fallback(
                    query_in.query,
                    relevant_chunks,
                    reason=last_failure,
                )
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
        
        # Step 5: Fast Heuristic Evaluation for SSE Response & Async Deep Evaluation.
        # (No status event here: the answer is already on screen, and a
        # "Processing response metadata..." line made it look unfinished.)
        
        total_latency = time.time() - total_start
        avg_retrieval_score = sum(c.get("similarity_score", 0.0) for c in state["reranked_chunks"]) / len(state["reranked_chunks"]) if state["reranked_chunks"] else 0.0
        
        # Calculate fast token overlap heuristic score for immediate stream metadata
        import re
        words_list = re.findall(r'\w+', full_response_text.lower())
        overlap_scores = []
        for chunk in relevant_chunks:
            chunk_words = set(re.findall(r'\w+', chunk["content"].lower()))
            overlap = len([w for w in words_list if w in chunk_words])
            overlap_scores.append(overlap / len(words_list) if words_list else 0.0)
        avg_overlap = sum(overlap_scores) / len(overlap_scores) if overlap_scores else 0.0
        fast_confidence = (avg_overlap * 0.4 + avg_retrieval_score * 0.6) * 100
        
        # Step 6: Log Metrics & Store in PG + Redis
        # Insert User Message
        user_msg = Message(
            conversation_id=query_in.conversation_id,
            sender="user",
            content=query_in.query,
            created_at=_stamps(total_start)[0],
        )
        # Generate Log ID first to tie Message to QueryLog
        log_id = uuid.uuid4()
        # Insert Assistant Message
        assistant_msg = Message(
            conversation_id=query_in.conversation_id,
            sender="assistant",
            content=full_response_text,
            created_at=_stamps(total_start)[1],
            citations=citations,
            latency=total_latency,
            retrieval_score=avg_retrieval_score,
            query_log_id=log_id
        )
        
        # Save Log details to PostgreSQL `query_logs` for dashboards (use fast_confidence first)
        query_log = QueryLog(
            id=log_id,
            user_id=user_id,
            query=query_in.query,
            latency=total_latency,
            # Real measured stage timings (previously a fabricated 30/70 split
            # of the single retrieval figure).
            embedding_latency=state["latency_breakdown"].get("embedding", 0.0),
            retrieval_latency=(
                state["latency_breakdown"].get("vector_search", 0.0)
                + state["latency_breakdown"].get("sparse_search", 0.0)
            ),
            hallucination_rate=round((100.0 - fast_confidence) / 100.0, 4),
            retrieval_score=avg_retrieval_score,
            kb_id=kb_id,
            mode=mode,
            cached=False,
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
        await db.refresh(query_log)
        
        # Save to Redis memory for session continuity
        await chat_memory.add_message(str(query_in.conversation_id), {"sender": "user", "content": query_in.query})
        await chat_memory.add_message(str(query_in.conversation_id), {"sender": "assistant", "content": full_response_text, "citations": citations})
        
        # Yield final metadata packet. confidence_score here is provisional -
        # the judged figure follows in its own event a moment later, so
        # citations and latency do not wait on the judge.
        # weak_match tells the client these chunks were all below the rerank
        # threshold, so the answer rests on a loose match rather than nothing.
        yield f"data: {json.dumps({'event': 'metadata', 'query_log_id': str(query_log.id), 'citations': citations, 'confidence_score': round(fast_confidence, 2), 'confidence_method': 'provisional', 'weak_match': weak_match, 'latency': total_latency, 'latency_breakdown': state['latency_breakdown']})}\n\n"

        # The LLM faithfulness judgement used to run in a fire-and-forget task
        # that wrote to the database after the stream had closed, so the client
        # only ever saw fast_confidence - a lexical-overlap and rerank-score
        # blend displayed under the label "Confidence". An answer the judge
        # scored 100/100 showed as 14% because its chunks reranked low. Await
        # the judgement and send the real number before closing.
        state_copy = {k: v for k, v in state.items() if k != "db_session"}
        state_copy["response"] = full_response_text

        confidence = fast_confidence
        confidence_method = "heuristic"

        async def _judge():
            try:
                return await self_evaluate_node(state_copy)
            except Exception as eval_err:
                logger.error(f"Self-evaluation failed: {eval_err}")
                return {}

        async def _followups():
            if not settings.FOLLOW_UP_SUGGESTIONS:
                return [], None
            try:
                return await suggest_follow_ups(query_in.query, full_response_text, relevant_chunks)
            except Exception as e:
                logger.warning(f"Follow-up suggestions skipped: {e}")
                return [], None

        eval_res, (follow_ups, fu_usage) = await asyncio.gather(_judge(), _followups())
        usage_total.add(gen_usage).add(fu_usage)
        scored = (eval_res or {}).get("confidence_score")
        if isinstance(scored, (int, float)):
            confidence = float(scored)
            confidence_method = eval_res.get("confidence_method", "llm")

        if follow_ups:
            yield f"data: {json.dumps({'event': 'suggestions', 'questions': follow_ups})}\n\n"
        usage_payload = {'prompt_tokens': usage_total.prompt_tokens, 'completion_tokens': usage_total.completion_tokens,
                         'model': usage_total.model or None, 'cost_usd': usage_total.cost_usd}
        yield f"data: {json.dumps({'event': 'confidence', 'confidence_score': round(confidence, 2), 'confidence_method': confidence_method, 'usage': usage_payload})}\n\n"
        yield "data: [DONE]\n\n"

        # Remember confident, judged, non-weak answers for near-identical questions.
        if cache_eligible and not weak_match and not state.get("needs_web_search") and confidence_method != "heuristic":
            await answer_cache.store(kb_id, query_in.query, cache_embedding, full_response_text,
                                     citations, confidence, query_in.document_ids)

        # Persist the judged rate on a fresh session: the request session has
        # already committed and the response body is on its way out.
        try:
            async with SessionLocal() as background_db:
                result = await background_db.execute(
                    select(QueryLog).where(QueryLog.id == query_log.id)
                )
                qlog = result.scalar_one_or_none()
                if qlog:
                    qlog.hallucination_rate = round((100.0 - confidence) / 100.0, 4)
                    qlog.model = usage_total.model or None
                    qlog.prompt_tokens = usage_total.prompt_tokens
                    qlog.completion_tokens = usage_total.completion_tokens
                    qlog.cost_usd = usage_total.cost_usd
                    await background_db.commit()
        except Exception as persist_err:
            logger.error(f"Failed to persist judged confidence: {persist_err}")


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
