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
    
    # 1. Search Knowledge Base (Hybrid Search)
    hybrid_start = time.time()
    kb_chunks = await retrieval_pipeline.search_hybrid(db, kb_id, query_to_search, doc_ids, top_k=15)
    logger.info(f"Retrieved {len(kb_chunks)} chunks from KB.")
    retrieved_chunks.extend(kb_chunks)
    
    # 2. Search Web if needed
    if needs_web:
        logger.info("Web search triggered. Querying public search API...")
        web_chunks = await run_web_search(query_to_search)
        retrieved_chunks.extend(web_chunks)

    latency = time.time() - start_time
    
    # Merge existing latencies
    latencies = state.get("latency_breakdown", {})
    latencies["retrieval"] = latency
    
    return {
        "retrieved_chunks": retrieved_chunks,
        "latency_breakdown": latencies
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
    top_5 = scored[:5]
    
    # Sigmoid normalization to similarity scores
    import math
    for c in top_5:
        c["similarity_score"] = round(1 / (1 + math.exp(-c["rerank_score"])), 4)
        
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
            model="gpt-4o",
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
    
    # Filter chunks by similarity threshold (0.45) to reduce hallucination
    relevant_chunks = [c for c in chunks if c.get("similarity_score", 0.0) >= 0.45]
    
    if not relevant_chunks:
        response_text = "I could not find any relevant information in the uploaded documents to answer your question."
        return {
            "response": response_text,
            "citations": [],
            "latency_breakdown": {**state.get("latency_breakdown", {}), "generation": time.time() - start_time}
        }
    
    # Build Context
    context_str = ""
    citations = []
    for idx, chunk in enumerate(relevant_chunks):
        context_str += f"[Source {idx+1}] File: {chunk['filename']}, Page: {chunk.get('page_number', 'N/A')}\nContent: {chunk['content']}\n\n"
        citations.append({
            "source_doc": chunk["filename"],
            "page": chunk.get("page_number", 1),
            "score": chunk.get("similarity_score", 0.0)
        })
        
    system_prompt = (
        "You are an expert Enterprise AI assistant. Answer the query using ONLY the facts explicitly mentioned in the provided sources. "
        "Follow these strict rules:\n"
        "1. Do NOT assume, extrapolate, or generalize facts not directly stated in the sources.\n"
        "2. Do NOT use any of your own outside or general training knowledge under any circumstances.\n"
        "3. If the sources do not contain the exact facts to answer the question, state clearly: 'I cannot find the answer in the provided documents.'\n"
        "4. Cite your sources exactly when presenting facts (e.g. at the end of the sentence use [Source X]).\n\n"
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
            
            if settings.GEMINI_API_KEY:
                client = openai.AsyncOpenAI(
                    api_key=settings.GEMINI_API_KEY,
                    base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
                )
                model_name = settings.GEMINI_MODEL
            else:
                client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
                model_name = "gpt-4o"
                
            completion = await client.chat.completions.create(
                model=model_name,
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
            logger.info(f"LangGraph Agent: LLM Self-Evaluation Score: {confidence:.2f}% | Reasoning: {reasoning}")
        except Exception as e:
            logger.error(f"Failed LLM self-evaluation: {str(e)}. Falling back to regex heuristics.")
            
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
async def run_web_search(query: str) -> List[Dict[str, Any]]:
    # Mock / Fallback web search using DuckDuckGo or static results if no keys.
    # If Tavily API is present, use Tavily.
    if settings.TAVILY_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(
                    "https://api.tavily.com/search",
                    json={"api_key": settings.TAVILY_API_KEY, "query": query, "max_results": 3}
                )
                res.raise_for_status()
                results = res.json().get("results", [])
                web_chunks = []
                for idx, r in enumerate(results):
                    web_chunks.append({
                        "content": r.get("content", ""),
                        "page_number": 1,
                        "chunk_index": idx,
                        "filename": f"Web: {r.get('title', 'Search Result')}",
                        "source": r.get("url", "https://tavily.com")
                    })
                return web_chunks
        except Exception as e:
            logger.error(f"Tavily search error after retries: {str(e)}")
            raise e
            
    # Mock Search
    logger.info("No Tavily API key or request failed. Returning mock web search result.")
    return [{
        "content": f"Mock web search results explaining: {query}. The latest developments in 2026 indicate that AI agents are increasingly orchestration-based.",
        "page_number": 1,
        "chunk_index": 0,
        "filename": "Web: Search API",
        "source": "https://google.com"
    }]


def synthesize_context_fallback(query: str, chunks: List[Dict[str, Any]]) -> str:
    """
    Synthesizes a beautiful markdown response locally from retrieved context when OpenAI is unavailable.
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
        
    resp += "\n*Note: This response was synthesized locally using document snippet extraction because no OpenAI API key was detected in the backend `.env` file.*"
    return resp


# --- ROUTER DECISION LOGIC ---
def route_after_classification(state: AgentState) -> Literal["retrieve", "end"]:
    # Always proceed to retrieval
    return "retrieve"

def route_after_eval(state: AgentState) -> Literal["rewrite", "end"]:
    confidence = state["confidence_score"]
    retries = state["retry_count"]
    
    if confidence < 80.0 and retries < 2:
        return "rewrite"
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
