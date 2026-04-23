import json
import os
from collections import defaultdict

from config import CHUNKS_FILE, SUGGESTIONS_FILE, SUGGESTION_COUNT
from llm_utils import generate_json


def load_chunk_store():
    if not os.path.exists(CHUNKS_FILE):
        return []

    with open(CHUNKS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def ensure_suggestions_dir():
    directory = os.path.dirname(SUGGESTIONS_FILE)
    if directory:
        os.makedirs(directory, exist_ok=True)


def clear_suggested_questions():
    ensure_suggestions_dir()
    with open(SUGGESTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump({"suggestions": []}, f, indent=2, ensure_ascii=False)


def load_suggested_questions():
    if not os.path.exists(SUGGESTIONS_FILE):
        return []

    with open(SUGGESTIONS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data.get("suggestions", [])


def build_source_summaries(max_sources=4, max_chars_per_source=2500):
    chunks = load_chunk_store()
    if not chunks:
        return []

    grouped = defaultdict(list)

    for item in chunks:
        metadata = item.get("metadata", {})
        source_name = metadata.get("source_file")
        source_type = metadata.get("source_type", "pdf")
        text = item.get("text", "").strip()

        if source_name and text:
            grouped[source_name].append({
                "source_type": source_type,
                "text": text,
            })

    summaries = []

    for source_name, items in list(grouped.items())[:max_sources]:
        source_type = items[0]["source_type"]
        parts = []
        total = 0

        for item in items:
            text = item["text"]
            if total + len(text) > max_chars_per_source:
                remaining = max_chars_per_source - total
                if remaining > 0:
                    parts.append(text[:remaining])
                break

            parts.append(text)
            total += len(text)

        combined = "\n\n".join(parts).strip()

        if combined:
            summaries.append({
                "source_name": source_name,
                "source_type": source_type,
                "excerpt": combined,
            })

    return summaries


def fallback_suggestions(source_summaries):
    suggestions = []

    templates = [
        "What are the main topics covered in {source}?",
        "Summarize the key concepts from {source}.",
        "Explain the most important ideas in {source} in simple language.",
        "What definitions or terms should I know from {source}?",
        "Give me a bullet-point summary of {source}.",
        "What are the most exam-relevant points from {source}?",
    ]

    for source in source_summaries[:3]:
        for template in templates[:2]:
            suggestions.append({
                "question": template.format(source=source["source_name"]),
                "source_name": source["source_name"],
            })

            if len(suggestions) >= SUGGESTION_COUNT:
                return suggestions

    return suggestions[:SUGGESTION_COUNT]


def generate_suggested_questions():
    source_summaries = build_source_summaries()

    if not source_summaries:
        clear_suggested_questions()
        return []

    allowed_sources = {item["source_name"] for item in source_summaries}

    sources_block = "\n\n".join(
        [
            f"""Source Name: {item["source_name"]}
Source Type: {item["source_type"]}
Excerpt:
{item["excerpt"]}"""
            for item in source_summaries
        ]
    )

    prompt = f"""
Return ONLY one valid JSON object.

Generate {SUGGESTION_COUNT} user-friendly suggested questions that a student might naturally ask
after uploading the following sources.

JSON format:
{{
  "suggestions": [
    {{
      "question": "Question text",
      "source_name": "Exact source name from the list above"
    }}
  ]
}}

Rules:
- Use the exact source_name from the provided sources
- Make questions diverse:
  - summary
  - explanation
  - key concepts
  - definitions
  - exam prep
  - compare/understand topics
- Keep questions natural and useful
- Do not use markdown
- Do not include any extra text outside JSON

Sources:
{sources_block}
"""

    try:
        data = generate_json(prompt)
        raw_suggestions = data.get("suggestions", [])

        cleaned = []
        for item in raw_suggestions:
            question = str(item.get("question", "")).strip()
            source_name = str(item.get("source_name", "")).strip()

            if not question:
                continue
            if source_name not in allowed_sources:
                continue

            cleaned.append({
                "question": question,
                "source_name": source_name,
            })

        if not cleaned:
            cleaned = fallback_suggestions(source_summaries)

    except Exception:
        cleaned = fallback_suggestions(source_summaries)

    ensure_suggestions_dir()
    with open(SUGGESTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump({"suggestions": cleaned}, f, indent=2, ensure_ascii=False)

    return cleaned