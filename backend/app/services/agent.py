import uuid
import time
import json
from typing import TypedDict, List, Dict, Any, Literal, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from langgraph.graph import StateGraph, END
import openai

from app.core.config import settings
from app.core.logging import logger
from app.services.search import retrieval_pipeline
from app.services.llm_providers import provider_chain, mark_exhausted
from app.services.llm_errors import describe_llm_failure
from tenacity import retry, wait_exponential, stop_after_attempt
import httpx

# Define the state shape
class AgentState(TypedDict):
    query: str
    kb_id: uuid.UUID
    db_session: AsyncSession  # Pass db session to allow nodes to perform DB queries
    web_search_enabled: bool
    needs_web_search: bool
    retrieved_chunks: List[Dict[str, Any]]
    reranked_chunks: List[Dict[str, Any]]
    response: str
    citations: List[Dict[str, Any]]
    confidence_score: float
    retry_count: int
    revised_query: str
    latency_breakdown: Dict[str, float]
    document_ids: Optional[List[uuid.UUID]]
    mode: Optional[str]


# --- NODE 1: Classify Query ---
async def classify_query_node(state: AgentState) -> Dict[str, Any]:
    logger.info(f"LangGraph Agent: Classifying query: '{state['query']}'")
    start_time = time.time()
    
    query = state["query"]
    web_enabled = state.get("web_search_enabled", False)
    
    # Classify whether we need web search
    # In production, we could call LLM for classification. For simplicity/speed, we check keyword-based triggers
    # and combine with user configurations.
    needs_web = False
    if web_enabled:
        needs_web = True

    latency = time.time() - start_time
    return {
        "needs_web_search": needs_web,
        "latency_breakdown": {"classification": latency},
        "retry_count": 0,
        "revised_query": query
    }


# --- NODE 2: Retrieve Context ---
async def retrieve_context_node(state: AgentState) -> Dict[str, Any]:
    logger.info("LangGraph Agent: Retrieving context...")
    start_time = time.time()
    
    db = state["db_session"]
    kb_id = state["kb_id"]
    query_to_search = state.get("revised_query", state["query"])
    needs_web = state.get("needs_web_search", False)
    doc_ids = state.get("document_ids", None)
    
    retrieved_chunks = []
    stage_timings: Dict[str, float] = {}
    mode = state.get("mode") or "detailed"
    sub_questions: List[str] = [query_to_search]
    extra_usage = None

    def _dedupe(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen, out = set(), []
        for c in chunks:
            key = c.get("chunk_id") or c.get("content")
            if key not in seen:
                seen.add(key)
                out.append(c)
        return out

    if mode == "compare" and doc_ids and len(doc_ids) >= 2:
        # Compare: retrieve for each document separately so every document
        # gets a fair share of the context, and tag the chunks by document.
        import asyncio as _asyncio
        per_doc = max(4, settings.RETRIEVAL_TOP_K // len(doc_ids))
        results = await _asyncio.gather(*[
            retrieval_pipeline.search_hybrid(db, kb_id, query_to_search, [d], top_k=per_doc, timings=stage_timings)
            for d in doc_ids
        ])
        for d, chunks in zip(doc_ids, results):
            for c in chunks:
                c["compare_doc"] = str(d)
            retrieved_chunks.extend(chunks)
        logger.info(f"Compare mode: retrieved {len(retrieved_chunks)} chunks across {len(doc_ids)} documents.")
    else:
        # 1. Search Knowledge Base (Hybrid Search), with query decomposition:
        # a compound question is also searched as its parts, and the
        # candidates are merged before reranking against the full question.
        if settings.QUERY_DECOMPOSITION and state.get("decompose", True):
            from app.services.decompose import decompose
            try:
                sub_questions, extra_usage = await decompose(query_to_search)
            except Exception as e:
                logger.warning(f"Query decomposition skipped: {e}")
                sub_questions = [query_to_search]
        queries = [query_to_search] + [q for q in sub_questions if q.strip().lower() != query_to_search.strip().lower()]
        import asyncio as _asyncio
        results = await _asyncio.gather(*[
            retrieval_pipeline.search_hybrid(db, kb_id, q, doc_ids, top_k=settings.RETRIEVAL_TOP_K, timings=stage_timings)
            for q in queries
        ])
        for chunks in results:
            retrieved_chunks.extend(chunks)
        retrieved_chunks = _dedupe(retrieved_chunks)
        logger.info(f"Retrieved {len(retrieved_chunks)} chunks from KB for {len(queries)} query variant(s).")
    
    # 2. Search Web if needed
    if needs_web:
        logger.info("Web search triggered. Querying public search API...")
        web_chunks = await run_web_search(query_to_search)
        retrieved_chunks.extend(web_chunks)

    latency = time.time() - start_time
    
    # Merge existing latencies, keeping the real measured stage breakdown
    latencies = state.get("latency_breakdown", {})
    latencies["retrieval"] = latency
    latencies["embedding"] = stage_timings.get("embedding", 0.0)
    latencies["vector_search"] = stage_timings.get("vector_search", 0.0)
    latencies["sparse_search"] = stage_timings.get("sparse_search", 0.0)

    return {
        "retrieved_chunks": retrieved_chunks,
        "latency_breakdown": latencies,
        "sub_questions": sub_questions if len(sub_questions) > 1 else [],
        "helper_usage": extra_usage,
    }


# --- NODE 3: Rerank Context ---
async def rerank_context_node(state: AgentState) -> Dict[str, Any]:
    logger.info("LangGraph Agent: Reranking candidate chunks...")
    start_time = time.time()
    
    query = state["query"]
    candidates = state["retrieved_chunks"]
    
    if not candidates:
        return {
            "reranked_chunks": [],
            "latency_breakdown": {**state.get("latency_breakdown", {}), "reranking": 0.0}
        }
        
    # Run CrossEncoder reranking
    passages = [c["content"] for c in candidates]
    pairs = [[query, p] for p in passages]
    
    import asyncio
    rerank_scores = await asyncio.to_thread(retrieval_pipeline.reranker.predict, pairs)
    rerank_scores = rerank_scores.tolist()
    
    # Associate scores and sort
    scored = []
    for idx, candidate in enumerate(candidates):
        c_copy = candidate.copy()
        c_copy["rerank_score"] = rerank_scores[idx]
        scored.append(c_copy)
        
    scored.sort(key=lambda x: x["rerank_score"], reverse=True)
    mode = state.get("mode") or "detailed"
    if mode == "compare" and any(c.get("compare_doc") for c in scored):
        # Keep the best few chunks of EVERY compared document.
        per_doc = 4
        counts: Dict[str, int] = {}
        top_5 = []
        for c in scored:
            key = c.get("compare_doc", "")
            if counts.get(key, 0) < per_doc:
                counts[key] = counts.get(key, 0) + 1
                top_5.append(c)
    elif mode == "quick":
        top_5 = scored[:min(3, settings.RERANK_TOP_N)]
    else:
        top_5 = scored[:settings.RERANK_TOP_N]
    
    # Rerank score is already a probability (0-1), use it directly
    for c in top_5:
        c["similarity_score"] = round(c["rerank_score"], 4)
        
    latency = time.time() - start_time
    latencies = state.get("latency_breakdown", {})
    latencies["reranking"] = latency
    
    return {
        "reranked_chunks": top_5,
        "latency_breakdown": latencies
    }


@retry(wait=wait_exponential(min=1, max=10), stop=stop_after_attempt(3))
async def _generate_llm_response(query: str, system_prompt: str) -> str:
    if settings.GEMINI_API_KEY:
        client = openai.AsyncOpenAI(
            api_key=settings.GEMINI_API_KEY,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            timeout=30.0
        )
        completion = await client.chat.completions.create(
            model=settings.GEMINI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query}
            ],
            temperature=0.0
        )
        return completion.choices[0].message.content
    elif settings.OPENAI_API_KEY:
        client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY, timeout=30.0)
        completion = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query}
            ],
            temperature=0.0
        )
        return completion.choices[0].message.content
    return ""

# --- NODE 4: Generate Response ---
async def generate_response_node(state: AgentState) -> Dict[str, Any]:
    logger.info("LangGraph Agent: Generating response with LLM...")
    start_time = time.time()
    
    query = state["query"]
    chunks = state["reranked_chunks"]
    
    # Filter chunks by rerank score to reduce hallucination (see RERANK_SCORE_THRESHOLD)
    relevant_chunks = [c for c in chunks if c.get("similarity_score", 0.0) >= settings.RERANK_SCORE_THRESHOLD]
    
    if not relevant_chunks:
        response_text = "I could not find any relevant information in the uploaded documents to answer your question."
        return {
            "response": response_text,
            "citations": [],
            "latency_breakdown": {**state.get("latency_breakdown", {}), "generation": time.time() - start_time}
        }
    
    # Build Context
    from app.services.guard import build_context, SOURCE_RULES
    context_str, _ = build_context(relevant_chunks)
    citations = [
        {"index": idx + 1, "source_doc": c["filename"], "page": c.get("page_number", 1),
         "score": c.get("similarity_score", 0.0), "snippet": (c.get("content") or "")[:600],
         **({"doc_id": str(c["doc_id"])} if c.get("doc_id") else {}),
         **({"chunk_id": str(c["chunk_id"])} if c.get("chunk_id") else {})}
        for idx, c in enumerate(relevant_chunks)
    ]
        
    system_prompt = (
        "You are an expert Enterprise AI assistant. Answer the query using ONLY the facts explicitly mentioned in the provided sources. "
        "Follow these strict rules:\n"
        "1. Do NOT assume, extrapolate, or generalize facts not directly stated in the sources.\n"
        "2. Do NOT use any of your own outside or general training knowledge under any circumstances.\n"
        "3. If the sources do not contain the exact facts to answer the question, state clearly: 'I cannot find the answer in the provided documents.'\n"
        "4. Cite your sources exactly when presenting facts (e.g. at the end of the sentence use [Source X]).\n\n"
        f"{SOURCE_RULES}\n\n"
        f"Sources:\n{context_str}"
    )
    
    response_text = ""
    if settings.GEMINI_API_KEY or settings.OPENAI_API_KEY:
        try:
            response_text = await _generate_llm_response(query, system_prompt)
        except Exception as e:
            logger.error(f"LLM Generation API error after retries: {str(e)}")
            response_text = f"Error generating answer via LLM. Falling back to local synthesis.\n\nContext:\n{context_str[:500]}..."
    else:
        # Fallback to local response generator (no OpenAI/Gemini key provided)
        response_text = synthesize_context_fallback(query, relevant_chunks)

    latency = time.time() - start_time
    latencies = state.get("latency_breakdown", {})
    latencies["generation"] = latency
    
    return {
        "response": response_text,
        "citations": citations,
        "latency_breakdown": latencies
    }


# --- NODE 5: Self Evaluate ---
async def self_evaluate_node(state: AgentState) -> Dict[str, Any]:
    logger.info("LangGraph Agent: Running self evaluation...")
    start_time = time.time()
    
    query = state["query"]
    response = state["response"]
    chunks = state["reranked_chunks"]
    
    context_str = ""
    for idx, chunk in enumerate(chunks):
        context_str += f"[Source {idx+1}] File: {chunk['filename']}, Page: {chunk.get('page_number', 'N/A')}\nContent: {chunk['content']}\n\n"
        
    confidence = None
    
    if (settings.GEMINI_API_KEY or settings.OPENAI_API_KEY) and chunks:
        try:
            eval_system_prompt = (
                "You are an expert RAG auditor. You will evaluate the faithfulness of an assistant's response given a set of retrieved source chunks. "
                "Faithfulness measures whether the response is fully factual and supported ONLY by the provided source chunks (no outside information, no hallucinations).\n"
                "Return a JSON object with keys 'score' (an integer from 0 to 100) and 'reasoning' (a brief sentence explaining the score)."
            )
            eval_user_prompt = (
                f"Retrieved Source Chunks:\n{context_str}\n\n"
                f"User Query: {query}\n\n"
                f"Assistant Response:\n{response}\n\n"
                "Evaluate and output JSON only."
            )
            
            # Walk the chain: a provider that is out of quota hands this to
            # the next one instead of dropping the whole audit to regex.
            for provider in provider_chain():
                try:
                    client = (
                        openai.AsyncOpenAI(
                            api_key=provider.api_key, base_url=provider.base_url
                        )
                        if provider.base_url
                        else openai.AsyncOpenAI(api_key=provider.api_key)
                    )
                    completion = await client.chat.completions.create(
                        model=provider.model,
                        messages=[
                            {"role": "system", "content": eval_system_prompt},
                            {"role": "user", "content": eval_user_prompt}
                        ],
                        temperature=0.0,
                        response_format={"type": "json_object"}
                    )
                    res_content = completion.choices[0].message.content
                    eval_data = json.loads(res_content)
                    confidence = float(eval_data.get("score", 80.0))
                    reasoning = eval_data.get("reasoning", "")
                    logger.info(
                        f"LangGraph Agent: LLM Self-Evaluation Score: {confidence:.2f}% "
                        f"({provider.label}) | Reasoning: {reasoning}"
                    )
                    break
                except Exception as e:
                    mark_exhausted(provider.label, e)
                    logger.warning(
                        f"Self-evaluation via {provider.label} failed: "
                        f"{describe_llm_failure(e, provider.label)}"
                    )
        except Exception as e:
            logger.error(f"Failed LLM self-evaluation: {str(e)}. Falling back to regex heuristics.")
            
    confidence_method = "llm" if confidence is not None else "heuristic"

    if confidence is None:
        # Calculate Faithfulness / Hallucination Rate using heuristics
        if not chunks:
            confidence = 0.0
        else:
            overlap_scores = []
            import re
            words = re.findall(r'\w+', response.lower())
            for chunk in chunks:
                chunk_words = set(re.findall(r'\w+', chunk["content"].lower()))
                overlap = len([w for w in words if w in chunk_words])
                overlap_scores.append(overlap / len(words) if words else 0.0)
                
            avg_overlap = sum(overlap_scores) / len(overlap_scores) if overlap_scores else 0.0
            avg_similarity = sum(c.get("similarity_score", 0.0) for c in chunks) / len(chunks)
            
            # Combined heuristic confidence (0-100%)
            confidence = (avg_overlap * 0.4 + avg_similarity * 0.6) * 100
            logger.info(f"Self-Evaluation (Heuristic) Confidence Score: {confidence:.2f}%")
            
    logger.info(f"Self-Evaluation Confidence Score: {confidence:.2f}%")
    
    latency = time.time() - start_time
    latencies = state.get("latency_breakdown", {})
    latencies["evaluation"] = latency
    
    return {
        "confidence_score": confidence,
        # Callers surface this: a judged score and a lexical-overlap proxy are
        # not the same measurement and must not be presented as one.
        "confidence_method": confidence_method,
        "latency_breakdown": latencies
    }


# --- NODE 6: Query Rewriter ---
async def rewrite_query_node(state: AgentState) -> Dict[str, Any]:
    logger.info("LangGraph Agent: Confidence under 80%. Rewriting query...")
    start_time = time.time()
    
    query = state["query"]
    
    # Query rewriting simulation
    # In production, ask LLM to rewrite. Here we extract keywords and append general search modifiers
    words = query.split()
    if len(words) > 3:
        revised = " ".join(words[:4]) + " definition explain details"
    else:
        revised = query + " details summary"
        
    logger.info(f"Rewrote query: '{query}' -> '{revised}'")
    
    latency = time.time() - start_time
    latencies = state.get("latency_breakdown", {})
    latencies["rewriting"] = latency
    
    return {
        "revised_query": revised,
        "retry_count": state["retry_count"] + 1,
        "latency_breakdown": latencies
    }


# --- Web Search Utility ---
@retry(wait=wait_exponential(min=1, max=10), stop=stop_after_attempt(3))
async def _tavily_search(query: str) -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        res = await client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": settings.TAVILY_API_KEY,
                "query": query,
                "max_results": settings.WEB_SEARCH_MAX_RESULTS,
            },
        )
        res.raise_for_status()
        results = res.json().get("results", [])

    web_chunks = []
    for idx, r in enumerate(results):
        url = r.get("url")
        if not url:
            # Without a real URL we cannot attribute the text, so drop it rather
            # than cite it to a placeholder domain.
            continue
        web_chunks.append({
            "content": r.get("content", ""),
            "page_number": 1,
            "chunk_index": idx,
            "filename": f"Web: {r.get('title', 'Search Result')}",
            "source": url,
        })
    return web_chunks


async def run_web_search(query: str) -> List[Dict[str, Any]]:
    """
    Real web search via Tavily, or no results at all.

    This deliberately returns [] instead of placeholder text when search is
    unavailable. The previous implementation synthesised a fake result and
    attributed it to https://google.com, which reached the user as a genuine
    citation — fabricated sources are worse than a missing answer.
    """
    if not settings.TAVILY_API_KEY:
        logger.warning(
            "Web search requested but TAVILY_API_KEY is not configured; "
            "returning no web results."
        )
        return []

    try:
        return await _tavily_search(query)
    except Exception as e:
        # Degrade to knowledge-base-only rather than failing the whole query.
        logger.error(f"Tavily search failed after retries: {e}. Continuing without web results.")
        return []


def synthesize_context_fallback(
    query: str,
    chunks: List[Dict[str, Any]],
    reason: Optional[str] = None,
) -> str:
    """Build a local markdown answer from retrieved context when no LLM answered.

    `reason` states why the LLM did not answer. It matters: a rate limit is
    temporary and clears itself, while a missing key needs the operator to act.
    Defaulting the message to "no OpenAI API key was detected" was wrong
    whenever the real cause was a quota or a network error.
    """
    if not chunks:
        return "I could not find any relevant information in the uploaded documents to answer your question."
        
    resp = f"### Synthesis of Retrieved Sources (Local Developer Offline Mode)\n\n"
    resp += f"Based on your query: *\"{query}\"*, I have analyzed the relevant pages and synthesized the following response:\n\n"
    
    for idx, chunk in enumerate(chunks):
        filename = chunk["filename"]
        page = chunk.get("page_number", 1)
        score = chunk.get("similarity_score", 0.0)
        
        # Truncate content for a cleaner presentation
        snippet = chunk["content"][:250].strip()
        resp += f"**{idx+1}. From {filename} (Page {page}, Similarity: {score:.2f})**:\n"
        resp += f"> {snippet}...\n\n"
        
    if reason is None:
        reason = "no LLM API key is configured in the backend `.env` file"
    resp += (
        "\n*Note: this response was assembled locally from document snippets, "
        f"not written by a language model, because {reason}.*"
    )
    return resp


# --- ROUTER DECISION LOGIC ---
def route_after_classification(state: AgentState) -> Literal["retrieve", "end"]:
    # Always proceed to retrieval
    return "retrieve"

def route_after_eval(state: AgentState) -> Literal["rewrite", "end"]:
    confidence = state["confidence_score"]
    retries = state["retry_count"]
    
    if confidence < 80.0:
        if retries < 1:
            logger.warning(f"Self-Evaluation confidence ({confidence:.2f}%) is under 80.0%. Routing to rewrite (attempt {retries + 1}).")
            return "rewrite"
        else:
            logger.warning(f"Self-Evaluation confidence ({confidence:.2f}%) is under 80.0%, but max retries ({retries}) reached. Ending.")
    return "end"


# --- BUILD THE STATE GRAPH ---
workflow = StateGraph(AgentState)

# Add Nodes
workflow.add_node("classify", classify_query_node)
workflow.add_node("retrieve", retrieve_context_node)
workflow.add_node("rerank", rerank_context_node)
workflow.add_node("generate", generate_response_node)
workflow.add_node("evaluate", self_evaluate_node)
workflow.add_node("rewrite", rewrite_query_node)

# Set Entry Point
workflow.set_entry_point("classify")

# Add Edges
workflow.add_edge("classify", "retrieve")
workflow.add_edge("retrieve", "rerank")
workflow.add_edge("rerank", "generate")
workflow.add_edge("generate", "evaluate")

# Add Conditional Edge from evaluation
workflow.add_conditional_edges(
    "evaluate",
    route_after_eval,
    {
        "rewrite": "rewrite",
        "end": END
    }
)

# Add Edge from rewrite back to retrieve
workflow.add_edge("rewrite", "retrieve")

# Compile
agent_graph = workflow.compile()
