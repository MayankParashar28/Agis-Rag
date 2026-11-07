import asyncio
import functools
import uuid
import time
import random
import re
from typing import Dict, Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException

from app.core.config import settings
from app.services.llm_errors import describe_llm_failure
from app.services.llm_providers import provider_chain, mark_exhausted
from app.core.logging import logger
from app.models.metrics import Evaluation, Message, Conversation
from app.models.knowledge import Document, DocumentChunk

class RagasEvaluator:
    def __init__(self):
        self.api_key = settings.OPENAI_API_KEY

    @property
    def has_judge_llm(self) -> bool:
        """True when a judge model is available for the real RAGAS metrics.

        Gemini counts: it is reached through its OpenAI-compatible endpoint, so
        langchain_openai's ChatOpenAI/OpenAIEmbeddings drive it directly and
        RAGAS needs no Google-specific integration.
        """
        return bool(settings.GEMINI_API_KEY or settings.OPENAI_API_KEY)

    def _judge_candidates(self) -> List[str]:
        """Judge providers to try, most reliable first.

        OpenAI leads despite costing money: one RAGAS run issues dozens of LLM
        calls (four metrics across every QA pair, plus a ground-truth
        generation each), which a 20-requests/day free tier cannot finish. A
        measured run on Gemini's free tier spent 196s working through 429s and
        timeouts to produce partial scores. Gemini stays as the fallback for
        when no OpenAI key is configured; the chat path still prefers it,
        because a single answer fits inside the free tier comfortably.
        """
        return [p.label.lower() for p in provider_chain(prefer_paid=True)]

    async def _probe_judge(self) -> tuple[Optional[str], Optional[str]]:
        """Return (usable provider, reason none is usable).

        Costs one small completion per candidate. That is cheap next to the
        dozens RAGAS issues per run, and it turns a long retry storm into an
        immediate, explainable fallback. Each candidate is probed in turn, so a
        provider whose quota is spent hands the run to the next one instead of
        forcing heuristics while a working key sits unused.
        """
        import openai

        candidates = self._judge_candidates()
        if not candidates:
            return None, "no judge LLM is configured"

        last_error = None
        for provider in candidates:
            if provider == "gemini":
                client = openai.AsyncOpenAI(
                    api_key=settings.GEMINI_API_KEY,
                    base_url=settings.GEMINI_OPENAI_BASE_URL,
                    max_retries=0,
                )
                model, label = settings.GEMINI_MODEL, "Gemini"
            else:
                client = openai.AsyncOpenAI(
                    api_key=settings.OPENAI_API_KEY, max_retries=0
                )
                model, label = settings.OPENAI_MODEL, "OpenAI"

            try:
                await client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": "ok"}],
                    max_tokens=1,
                    timeout=15.0,
                )
                return provider, None
            except Exception as e:
                last_error = describe_llm_failure(e, label)
                mark_exhausted(label, e)
                logger.warning(f"Judge candidate {label} unusable: {last_error}")

        return None, last_error

    def _build_judge(self, provider: str):
        """Return (llm, embeddings) wrapped for RAGAS, or (None, None).

        RAGAS needs BOTH a chat model and an embeddings model - faithfulness and
        context_recall use the LLM, answer_relevancy and context_precision use
        embeddings. Passing these explicitly is what stops RAGAS falling back to
        its default OpenAI judge, which is why a Gemini key alone used to end up
        computing nothing.

        `provider` is the one _probe_judge just proved reachable, so a dead
        Gemini key never builds the judge that the probe rejected.
        """
        from langchain_openai import ChatOpenAI, OpenAIEmbeddings
        from ragas.llms import LangchainLLMWrapper
        from ragas.embeddings import LangchainEmbeddingsWrapper

        if provider == "gemini":
            llm = ChatOpenAI(
                model=settings.GEMINI_MODEL,
                api_key=settings.GEMINI_API_KEY,
                base_url=settings.GEMINI_OPENAI_BASE_URL,
                temperature=0.0,
            )
            embeddings = OpenAIEmbeddings(
                model=settings.GEMINI_EMBEDDING_MODEL,
                api_key=settings.GEMINI_API_KEY,
                base_url=settings.GEMINI_OPENAI_BASE_URL,
                # Gemini's endpoint does not accept OpenAI's tokenised input
                # form, so leave the text unsplit.
                check_embedding_ctx_length=False,
            )
        elif settings.OPENAI_API_KEY:
            llm = ChatOpenAI(
                model=settings.OPENAI_MODEL,
                api_key=settings.OPENAI_API_KEY,
                temperature=0.0,
            )
            embeddings = OpenAIEmbeddings(api_key=settings.OPENAI_API_KEY)
        else:
            return None, None

        return LangchainLLMWrapper(llm), LangchainEmbeddingsWrapper(embeddings)

    async def _generate_ground_truth(
        self, question: str, contexts: List[str], provider: Optional[str] = None
    ) -> str:
        """
        Generates a factually correct reference ground truth answer using the LLM.

        `provider` is the one the probe proved reachable. Honouring it stops
        this from spending a failed call on a dead provider for every QA pair
        before falling through to the one that works.
        """
        context_text = "\n\n".join(contexts)
        prompt = (
            "You are a golden responder. Given the user's question and the source contexts, "
            "write a perfect, concise, and factually correct ground truth answer. "
            "If the contexts do not contain enough information, write 'Information not found in context'.\n\n"
            f"Question: {question}\n\n"
            f"Contexts:\n{context_text}"
        )
        
        import openai
        if settings.GEMINI_API_KEY and provider != "openai":
            try:
                client = openai.AsyncOpenAI(
                    api_key=settings.GEMINI_API_KEY,
                    base_url=settings.GEMINI_OPENAI_BASE_URL,
                )
                completion = await client.chat.completions.create(
                    model=settings.GEMINI_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                    timeout=20.0
                )
                return completion.choices[0].message.content.strip()
            except Exception as e:
                logger.error(f"Failed to generate ground truth with Gemini: {e}")
        
        if settings.OPENAI_API_KEY:
            try:
                client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
                completion = await client.chat.completions.create(
                    model=settings.OPENAI_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                    timeout=20.0
                )
                return completion.choices[0].message.content.strip()
            except Exception as e:
                logger.error(f"Failed to generate ground truth with OpenAI: {e}")
                
        return "No reference ground truth available."

    # Spelled-out numerals, so "three days" in an answer matches "3 days" in a
    # source and vice versa. Without this the two look like unrelated tokens.
    _NUMBER_WORDS = {
        "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
        "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
        "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
        "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17",
        "eighteen": "18", "nineteen": "19", "twenty": "20", "thirty": "30",
        "forty": "40", "fifty": "50", "sixty": "60", "seventy": "70",
        "eighty": "80", "ninety": "90", "hundred": "100", "thousand": "1000",
    }

    @staticmethod
    def _stem(word: str) -> str:
        """Crudely strip inflections so related word forms match.

        Exact matching counts "approval"/"approved" and "remote"/"remotely" as
        unrelated, which penalises a faithful answer for paraphrasing rather
        than quoting. This is deliberately shallow - enough to align obvious
        variants, not a real stemmer.
        """
        for suffix in ("ally", "edly", "ing", "ies", "ed", "ly", "al", "es", "s"):
            if len(word) > len(suffix) + 3 and word.endswith(suffix):
                return word[: -len(suffix)]
        return word

    @classmethod
    def _extract_claims(cls, text: str) -> set:
        """Pull out the checkable facts in a piece of text.

        Numbers carry most of the risk in a RAG answer - a wrong figure is both
        the commonest hallucination and the most damaging, and plain word
        overlap cannot see it: "five days" and "three days" differ by one token
        out of nine, so an answer that inverts the fact still scores ~0.95.

        Each number is paired with the word it qualifies, because a bare set of
        numbers is too easy to satisfy. A source saying "three days per week"
        and "five business days in advance" contains both 3 and 5, so the false
        answer "five days per week" would match on the number alone; pairing it
        as (5, "days") against the source's (3, "days") and (5, "business")
        catches it.

        Citation markers are stripped first. "[Source 1]" and "Page 2" are
        artefacts of our own formatting, not claims the document must support,
        and counting them would flag every correctly cited answer.
        """
        cleaned = re.sub(r"\[[^\]]*\]", " ", text)                  # [Source 1]
        cleaned = re.sub(r"\b(?:page|pg|p)\.?\s*\d+\b", " ", cleaned, flags=re.I)
        cleaned = cleaned.lower().replace(",", "")

        # Filler that sits between a number and the thing it measures.
        skip = {"to", "of", "the", "a", "an", "at", "least", "most", "up",
                "about", "approximately", "per", "and", "or", "than", "over",
                "under", "in", "on", "for", "within"}

        tokens = re.findall(r"[a-z]+|\d+(?:\.\d+)?", cleaned)
        claims = set()
        for i, tok in enumerate(tokens):
            if tok.isdigit() or re.fullmatch(r"\d+\.\d+", tok):
                value = tok
            elif tok in cls._NUMBER_WORDS:
                value = cls._NUMBER_WORDS[tok]
            else:
                continue
            unit = ""
            for nxt in tokens[i + 1:i + 4]:
                if nxt in skip or nxt.isdigit() or nxt in cls._NUMBER_WORDS:
                    continue
                unit = cls._stem(nxt)
                break
            claims.add((value, unit))
        return claims

    def _compute_real_local_heuristics(self, real_pairs: List[Dict[str, Any]]) -> Dict[str, float]:
        """
        Computes real, text-based heuristics on the actual questions, answers, and contexts.
        """
        total_faithfulness = 0.0
        total_precision = 0.0
        total_recall = 0.0
        total_relevancy = 0.0
        
        stopwords = {
            "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "to", "of", "in", "on", 
            "at", "by", "for", "with", "about", "against", "between", "into", "through", "during", 
            "before", "after", "above", "below", "from", "up", "down", "in", "out", "on", "off", "over", 
            "under", "again", "further", "then", "once", "here", "there", "when", "where", "why", "how"
        }
        
        for pair in real_pairs:
            q = pair["question"].lower()
            a = pair["answer"].lower()
            ctxs = [c.lower() for c in pair["contexts"]]
            combined_ctx = " ".join(ctxs)
            
            q_words = set(re.findall(r'\w+', q))
            a_words = set(re.findall(r'\w+', a))
            ctx_words = set(re.findall(r'\w+', combined_ctx))
            
            # Remove stopwords for meaningful analysis
            q_meaningful = {self._stem(w) for w in (q_words - stopwords)}
            a_meaningful = {self._stem(w) for w in (a_words - stopwords)}
            ctx_meaningful = {self._stem(w) for w in (ctx_words - stopwords)}
            
            # 1. Faithfulness: is what the answer asserts supported by the context?
            #
            # Word overlap alone cannot answer this. An answer that inverts a
            # fact ("five days" where the source says "three") reuses nearly
            # every word around it and still scores ~0.95, so the one token
            # that carries the error is diluted by the ones that do not.
            #
            # So check the answer's factual claims directly: any number the
            # context does not contain is an unsupported assertion, and that is
            # what faithfulness is meant to catch. Where an answer makes no
            # such claim there is nothing to verify this way, and lexical
            # overlap remains the only available signal.
            lexical_support = (
                len(a_meaningful.intersection(ctx_meaningful)) / len(a_meaningful)
                if a_meaningful else 1.0
            )
            answer_claims = self._extract_claims(a)
            context_claims = self._extract_claims(combined_ctx)
            if answer_claims:
                supported = answer_claims & context_claims
                claim_support = len(supported) / len(answer_claims)
                # Weighted towards the claim check, but not blind to wording:
                # an answer whose figures all check out but which otherwise
                # shares nothing with the source is still not well grounded.
                faithfulness = 0.8 * claim_support + 0.2 * lexical_support
            else:
                faithfulness = lexical_support
                
            # 2. Answer Relevancy: Word overlap between question and answer
            if q_meaningful and a_meaningful:
                relevancy = len(q_meaningful.intersection(a_meaningful)) / len(q_meaningful)
                relevancy = min(1.0, relevancy * 1.5) # boost scale
            else:
                relevancy = 0.8
                
            # 3. Context Precision: Weight overlapping words in top chunks
            precision_scores = []
            for idx, ctx in enumerate(ctxs):
                words = set(re.findall(r'\w+', ctx)) - stopwords
                if q_meaningful:
                    score = len(words.intersection(q_meaningful)) / len(q_meaningful)
                    precision_scores.append(score * (1.0 / (idx + 1)))
            precision = sum(precision_scores) / sum(1.0 / (i + 1) for i in range(len(ctxs))) if ctxs else 0.8
            
            # 4. Context Recall: Ratio of meaningful answer tokens found in contexts
            if a_meaningful:
                recall = len(a_meaningful.intersection(ctx_meaningful)) / len(a_meaningful)
            else:
                recall = 0.8
                
            # Deterministic smoothing. NOTE: these are lexical-overlap proxies,
            # not RAGAS metrics - they do not measure semantic faithfulness.
            # The API reports them under the same field names, so treat any run
            # without a judge LLM as indicative only.
            # No floor on faithfulness: an answer the context does not support
            # should be able to score ~0. A floor here reads as "slightly
            # faithful" for a claim that is simply false.
            total_faithfulness += round(faithfulness, 4)
            total_relevancy += round(0.15 + 0.80 * relevancy, 4)
            total_precision += round(0.10 + 0.85 * precision, 4)
            total_recall += round(0.10 + 0.85 * recall, 4)
            
        n = len(real_pairs)
        return {
            "faithfulness": round(total_faithfulness / n, 4),
            "context_precision": round(total_precision / n, 4),
            "context_recall": round(total_recall / n, 4),
            "answer_relevancy": round(total_relevancy / n, 4)
        }

    async def run_evaluation(self, db: AsyncSession, kb_id: uuid.UUID) -> Dict[str, Any]:
        """
        Gathers conversation history, formats it for RAGAS, and computes the 4 metrics.
        """
        logger.info(f"RagasEvaluator: Running real evaluation for Knowledge Base {kb_id}...")
        
        # 1. Fetch all messages in the KB sorted chronologically to pair them
        query = (
            select(Message.content, Message.sender, Message.citations, Message.conversation_id)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Conversation.kb_id == kb_id)
            .order_by(Message.conversation_id, Message.created_at.asc())
        )
        result = await db.execute(query)
        rows = result.all()
        
        # Group messages by conversation ID
        from collections import defaultdict
        conv_messages = defaultdict(list)
        for content, sender, citations, conv_id in rows:
            conv_messages[conv_id].append({
                "content": content,
                "sender": sender,
                "citations": citations
            })
            
        # Reconstruct QA pairs
        qa_pairs = []
        for conv_id, msgs in conv_messages.items():
            last_user_query = None
            for msg in msgs:
                if msg["sender"] == "user":
                    last_user_query = msg["content"]
                elif msg["sender"] == "assistant" and last_user_query:
                    qa_pairs.append({
                        "question": last_user_query,
                        "answer": msg["content"],
                        "citations": msg["citations"] or []
                    })
                    last_user_query = None

        if not qa_pairs:
            raise HTTPException(
                status_code=400,
                detail="No conversation history found in this Knowledge Base. Please send some messages in the Chat Console first!"
            )
            
        # 2. Look up the raw chunk content from PostgreSQL for each citation
        real_pairs = []
        for pair in qa_pairs:
            question = pair["question"]
            answer = pair["answer"]
            citations = pair["citations"]
            
            contexts = []
            if citations:
                for citation in citations:
                    source_doc = citation.get("source_doc")
                    page = citation.get("page", 1)
                    if source_doc:
                        chunk_query = (
                            select(DocumentChunk.content)
                            .join(Document, Document.id == DocumentChunk.doc_id)
                            .where(Document.kb_id == kb_id)
                            .where(Document.filename == source_doc)
                            .where(DocumentChunk.page_number == page)
                            .limit(1)
                        )
                        chunk_result = await db.execute(chunk_query)
                        chunk_content = chunk_result.scalar_one_or_none()
                        if chunk_content:
                            contexts.append(chunk_content)
                            
            if not contexts:
                contexts = ["No retrieved source content available."]
                
            real_pairs.append({
                "question": question,
                "answer": answer,
                "contexts": contexts
            })

        # 3. Perform evaluation using RAGAS if a judge is usable, otherwise
        #    fall back to local heuristics.
        scores = None
        method = None
        judge_error = None

        # A spent daily quota will not clear for hours, but RAGAS would still
        # work through max_retries=10 per job across every metric and row -
        # measured at 200s to reach a fallback it could have reached at once.
        # One cheap probe decides it instead.
        judge_provider = None
        if self.has_judge_llm:
            judge_provider, judge_error = await self._probe_judge()
            if judge_error:
                logger.warning(
                    f"Skipping RAGAS: {judge_error}. Computing local heuristics instead."
                )

        if judge_provider:
            try:
                # Generate reference ground truths using LLM
                ground_truths = []
                for p in real_pairs:
                    gt = await self._generate_ground_truth(
                        p["question"], p["contexts"], judge_provider
                    )
                    ground_truths.append(gt)
                
                from datasets import Dataset
                from ragas import evaluate
                from ragas.metrics import faithfulness, answer_relevancy, context_precision, context_recall
                
                dataset_dict = {
                    "question": [p["question"] for p in real_pairs],
                    "contexts": [p["contexts"] for p in real_pairs],
                    "answer": [p["answer"] for p in real_pairs],
                    "ground_truth": ground_truths
                }
                
                dataset = Dataset.from_dict(dataset_dict)
                logger.info(f"Running RAGAS evaluation on {len(real_pairs)} real conversation pairs...")
                judge_llm, judge_embeddings = self._build_judge(judge_provider)

                # evaluate() is synchronous and nests its own event loop, which
                # uvloop (uvicorn's default) refuses to do. Running it in a
                # worker thread gives it a clean standard loop - and keeps a
                # multi-second blocking call off the request event loop.
                # Defaults are max_retries=10 / max_wait=60 / timeout=180,
                # which turn a failing judge into minutes of backoff. The probe
                # above already proved the judge answers, so anything failing
                # here is worth a couple of quick retries, not a retry storm.
                # timeout is per job, and a 60s cap was dropping jobs on long
                # contexts - which shows up as a metric scored over fewer rows
                # than were submitted. Failing fast is the probe's job, so give
                # each job room to finish.
                from ragas.run_config import RunConfig
                run_config = RunConfig(timeout=150, max_retries=2, max_wait=8)

                result_eval = await asyncio.to_thread(
                    functools.partial(
                        evaluate,
                        dataset,
                        metrics=[faithfulness, answer_relevancy,
                                 context_precision, context_recall],
                        llm=judge_llm,
                        embeddings=judge_embeddings,
                        run_config=run_config,
                        raise_exceptions=False,
                        show_progress=False,
                    )
                )
                
                # A metric RAGAS did not return is missing data, not a good
                # score. Previously these defaulted to 0.85/0.88/0.80/0.90,
                # which published plausible-looking numbers nobody computed.
                # EvaluationResult is not a dict - it has no .get(). Its scores
                # come out via to_pandas(), one row per question.
                #
                # With raise_exceptions=False a metric that errored (rate limit,
                # timeout) lands as NaN. Averaging NaN as 0 would invent a
                # terrible score; dropping NaN and reporting None when a metric
                # failed everywhere keeps missing data distinguishable from a
                # real low score.
                import math

                df = result_eval.to_pandas()
                scores = {}
                for metric in ("faithfulness", "context_precision",
                               "context_recall", "answer_relevancy"):
                    if metric not in df.columns:
                        scores[metric] = None
                        continue
                    vals = [float(v) for v in df[metric].tolist()
                            if v is not None and not math.isnan(float(v))]
                    scores[metric] = round(sum(vals) / len(vals), 4) if vals else None

                if all(v is None for v in scores.values()):
                    raise ValueError(
                        "RAGAS produced no usable metrics (every judge call failed)"
                    )
                method = "ragas"
            except Exception as e:
                logger.error(f"RAGAS library evaluation failed: {e}. Falling back to real local heuristics.")
                scores = self._compute_real_local_heuristics(real_pairs)
                method = "heuristic"
        else:
            logger.info("No judge LLM configured (set GEMINI_API_KEY or OPENAI_API_KEY). Computing real local text-based heuristics...")
            scores = self._compute_real_local_heuristics(real_pairs)
            method = "heuristic"
            
        # 4. Save results to PostgreSQL
        eval_record = Evaluation(
            kb_id=kb_id,
            faithfulness=scores["faithfulness"],
            context_precision=scores["context_precision"],
            context_recall=scores["context_recall"],
            answer_relevancy=scores["answer_relevancy"],
            method=method
        )
        db.add(eval_record)
        await db.commit()
        await db.refresh(eval_record)
        
        logger.info(f"RagasEvaluator: Real evaluation completed and saved with ID {eval_record.id}.")
        return {
            "id": str(eval_record.id),
            **scores,
            "method": method,
            "message": "Evaluation run completed successfully."
        }

ragas_evaluator = RagasEvaluator()

