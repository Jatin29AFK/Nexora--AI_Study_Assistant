import json
import os
import re

from rank_bm25 import BM25Okapi
from langchain_community.vectorstores import FAISS

from config import (
    CHUNKS_FILE,
    DENSE_TOP_K,
    INDEX_DIR,
    MAX_CONTEXT_CHUNKS,
    RERANK_MODEL,
    RRF_K,
    SPARSE_TOP_K,
)
from llm_utils import generate_answer

_embeddings = None
_vectorstore = None
_chunk_store = None
_chunk_map = None
_bm25 = None
_reranker = None


def tokenize(text: str):
    return re.findall(r"[a-zA-Z0-9]+", text.lower())


def get_embedding_model():
    global _embeddings
    if _embeddings is None:
        from langchain_huggingface import HuggingFaceEmbeddings

        _embeddings = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2"
        )
    return _embeddings

def get_reranker():
    global _reranker
    if _reranker is None:
        from sentence_transformers import CrossEncoder

        _reranker = CrossEncoder(RERANK_MODEL)
    return _reranker

def load_vectorstore(force_reload=False):
    global _vectorstore

    if _vectorstore is None or force_reload:
        if not os.path.exists(INDEX_DIR):
            return None

        embeddings = get_embedding_model()
        _vectorstore = FAISS.load_local(
            INDEX_DIR,
            embeddings,
            allow_dangerous_deserialization=True,
        )

    return _vectorstore


def load_chunk_store(force_reload=False):
    global _chunk_store, _chunk_map

    if _chunk_store is None or _chunk_map is None or force_reload:
        if not os.path.exists(CHUNKS_FILE):
            return None, None

        with open(CHUNKS_FILE, "r", encoding="utf-8") as f:
            _chunk_store = json.load(f)

        _chunk_map = {item["chunk_id"]: item for item in _chunk_store}

    return _chunk_store, _chunk_map


def load_bm25(force_reload=False):
    global _bm25

    if _bm25 is None or force_reload:
        chunks, _ = load_chunk_store(force_reload=force_reload)
        if not chunks:
            return None

        tokenized_corpus = [tokenize(item["text"]) for item in chunks]
        _bm25 = BM25Okapi(tokenized_corpus)

    return _bm25


def clear_retrieval_cache():
    global _vectorstore, _chunk_store, _chunk_map, _bm25
    _vectorstore = None
    _chunk_store = None
    _chunk_map = None
    _bm25 = None


def detect_source_hint(query: str, chunks: list):
    q = query.lower().strip()

    for item in chunks:
        source_name = item["metadata"].get("source_file", "")
        if source_name and source_name.lower() in q:
            return source_name

    for item in chunks:
        source_name = item["metadata"].get("source_file", "")
        name_only = source_name.lower().replace("https://", "").replace("http://", "")
        name_only = name_only.replace("www.", "")
        if not name_only:
            continue

        key_parts = re.findall(r"[a-zA-Z0-9]+", name_only)
        key_parts = [p for p in key_parts if len(p) >= 3]

        if key_parts and any(part in q for part in key_parts):
            return source_name

    return None


def dense_retrieve(query: str):
    vectorstore = load_vectorstore()
    if vectorstore is None:
        return []

    results = vectorstore.similarity_search_with_score(query, k=DENSE_TOP_K)

    dense = []
    for rank, (doc, score) in enumerate(results, start=1):
        dense.append(
            {
                "chunk_id": doc.metadata.get("chunk_id"),
                "text": doc.page_content,
                "metadata": doc.metadata,
                "rank": rank,
                "score": float(score),
            }
        )

    return dense


def sparse_retrieve(query: str):
    bm25 = load_bm25()
    chunks, _ = load_chunk_store()

    if bm25 is None or not chunks:
        return []

    scores = bm25.get_scores(tokenize(query))
    ranked_indices = sorted(
        range(len(scores)),
        key=lambda i: scores[i],
        reverse=True,
    )[:SPARSE_TOP_K]

    sparse = []
    for rank, idx in enumerate(ranked_indices, start=1):
        item = chunks[idx]
        sparse.append(
            {
                "chunk_id": item["chunk_id"],
                "text": item["text"],
                "metadata": item["metadata"],
                "rank": rank,
                "score": float(scores[idx]),
            }
        )

    return sparse


def rrf_fuse(dense_results, sparse_results):
    fused = {}

    for result_set in [dense_results, sparse_results]:
        for rank, item in enumerate(result_set, start=1):
            chunk_id = item["chunk_id"]
            if chunk_id not in fused:
                fused[chunk_id] = {
                    "chunk_id": chunk_id,
                    "text": item["text"],
                    "metadata": item["metadata"],
                    "rrf_score": 0.0,
                }

            fused[chunk_id]["rrf_score"] += 1.0 / (RRF_K + rank)

    return sorted(
        fused.values(),
        key=lambda x: x["rrf_score"],
        reverse=True,
    )


def rerank_candidates(query: str, candidates):
    if not candidates:
        return []

    reranker = get_reranker()
    pairs = [(query, item["text"]) for item in candidates]
    scores = reranker.predict(pairs)

    reranked = []
    for item, score in zip(candidates, scores):
        enriched = dict(item)
        enriched["rerank_score"] = float(score)
        reranked.append(enriched)

    reranked.sort(key=lambda x: x["rerank_score"], reverse=True)
    return reranked


def get_answer_mode_settings(query: str, answer_mode: str):
    q = query.lower().strip()

    if answer_mode == "concise":
        return {
            "style_instruction": """
Give a short, direct answer in 2 to 4 sentences.
No bullet points unless absolutely necessary.
""",
            "max_tokens": 220,
        }

    if answer_mode == "detailed":
        return {
            "style_instruction": """
Give a structured answer in this format:
1. One-line direct answer
2. One short explanation paragraph
3. 4 to 6 bullet points of important details
4. One small example if relevant

Use simple language.
""",
            "max_tokens": 700,
        }

    if answer_mode == "bullet":
        return {
            "style_instruction": """
Answer only in bullet points.
Use 4 to 7 bullet points.
Keep each bullet short but informative.
""",
            "max_tokens": 350,
        }

    if answer_mode == "beginner":
        return {
            "style_instruction": """
Explain for a beginner.
Use simple words.
Avoid jargon where possible.
If a technical term is necessary, explain it briefly.
""",
            "max_tokens": 500,
        }

    if answer_mode == "exam":
        return {
            "style_instruction": """
Write in exam style:
1. Definition / direct answer first
2. Key points in bullets
3. Keep it clean, crisp, and study-friendly
""",
            "max_tokens": 550,
        }

    wants_detail = any(
        phrase in q
        for phrase in ["in detail", "explain", "elaborate", "detailed", "deeply"]
    )

    if wants_detail:
        return {
            "style_instruction": """
Give a structured answer:
1. One-line direct answer
2. One short explanation paragraph
3. 3 to 5 bullet points of key details

Use simple language.
""",
            "max_tokens": 600,
        }

    return {
        "style_instruction": """
Give a clear, useful answer in 2 to 5 sentences.
Use simple language.
""",
        "max_tokens": 320,
    }


def format_history(history):
    if not history:
        return ""

    lines = []
    for item in history[-6:]:
        role = item.role if hasattr(item, "role") else item.get("role", "user")
        text = item.text if hasattr(item, "text") else item.get("text", "")
        role_label = "User" if role == "user" else "Assistant"
        lines.append(f"{role_label}: {text}")

    return "\n".join(lines).strip()


def build_answer_payload(query: str, answer_mode: str = "balanced", history=None):
    if not os.path.exists(INDEX_DIR) or not os.path.exists(CHUNKS_FILE):
        return {
            "fallback_answer": "No indexed content available yet.",
            "sources": [],
        }

    chunks, _ = load_chunk_store()
    if not chunks:
        return {
            "fallback_answer": "No indexed content available yet.",
            "sources": [],
        }

    source_hint = detect_source_hint(query, chunks)

    dense_results = dense_retrieve(query)
    sparse_results = sparse_retrieve(query)
    fused_candidates = rrf_fuse(dense_results, sparse_results)

    if source_hint:
        source_filtered = [
            item
            for item in fused_candidates
            if item["metadata"].get("source_file") == source_hint
        ]
        if source_filtered:
            fused_candidates = source_filtered

    reranked = rerank_candidates(query, fused_candidates)
    final_chunks = reranked[:MAX_CONTEXT_CHUNKS]

    if not final_chunks:
        return {
            "fallback_answer": "I couldn't find relevant information in the uploaded PDFs or URLs.",
            "sources": [],
        }

    context = "\n\n".join([item["text"] for item in final_chunks])

    sources = []
    for item in final_chunks:
        source_name = item["metadata"].get("source_file", "Unknown source")
        if source_name not in sources:
            sources.append(source_name)

    formatted_history = format_history(history or [])

    mode_settings = get_answer_mode_settings(query, answer_mode)
    style_instruction = mode_settings["style_instruction"]
    answer_max_tokens = mode_settings["max_tokens"]

    prompt = f"""
You are an AI study assistant.

Use the uploaded PDFs/URLs as the main source of truth.

You are also given recent conversation history.
Use the history only to understand follow-up references like:
- "this"
- "that"
- "explain it simply"
- "compare with previous answer"

Do NOT answer from history alone if the retrieved context does not support it.

Rules:
- Answer ONLY from the provided context when giving factual content.
- Use conversation history only for resolving what the user is referring to.
- Do not say "based on the context".
- Do not be vague.
- If enough information is present, answer confidently and clearly.
- If information is insufficient, say: "I couldn't find enough information in the uploaded PDFs or URLs."
- {style_instruction}

Recent conversation:
{formatted_history if formatted_history else "No prior conversation"}

Context:
{context}

Current question:
{query}
"""

    return {
        "prompt": prompt,
        "sources": sources,
        "max_tokens": answer_max_tokens,
    }


def ask_question(query: str, answer_mode: str = "balanced", history=None):
    payload = build_answer_payload(query, answer_mode, history)

    if "fallback_answer" in payload:
        return {
            "answer": payload["fallback_answer"],
            "sources": payload["sources"],
        }

    answer = generate_answer(
        payload["prompt"],
        max_tokens=payload["max_tokens"],
    ).strip()

    if not answer:
        answer = "I couldn't find enough information in the uploaded PDFs or URLs."

    return {
        "answer": answer,
        "sources": payload["sources"],
    }