import json
import os
import re


from dotenv import load_dotenv
from openai import OpenAI

from config import (
    LLM_PROVIDER,
    OLLAMA_MODEL,
    OLLAMA_KEEP_ALIVE,
    MAX_TOKENS,
    QUIZ_MAX_TOKENS,
)

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.groq.com/openai/v1")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

_openai_client = None


def get_openai_client():
    global _openai_client

    if _openai_client is None:
        if not GROQ_API_KEY:
            raise ValueError("GROQ_API_KEY is missing in backend environment variables.")

        _openai_client = OpenAI(
            api_key=GROQ_API_KEY,
            base_url=OPENAI_BASE_URL,
        )

    return _openai_client


def clean_llm_output(text: str) -> str:
    if not text:
        return ""

    text = text.strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    text = re.sub(r"^```json\s*", "", text)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def generate_answer(prompt: str, max_tokens: int | None = None) -> str:
    max_tokens = max_tokens or MAX_TOKENS

    if LLM_PROVIDER == "groq":
        client = get_openai_client()
        completion = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0.2,
        )
        content = completion.choices[0].message.content or ""
        return clean_llm_output(content)

    if LLM_PROVIDER == "ollama":
        import ollama
        
        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={
                "num_predict": max_tokens,
                "temperature": 0.2,
            },
            keep_alive=OLLAMA_KEEP_ALIVE,
        )

        content = response["message"]["content"]
        return clean_llm_output(content)

    raise ValueError(
        f"Unsupported LLM_PROVIDER: {LLM_PROVIDER}. Use 'groq' or 'ollama'."
    )


def chunk_text(text: str, words_per_chunk: int = 10):
    words = text.split()
    if not words:
        return

    for i in range(0, len(words), words_per_chunk):
        piece = " ".join(words[i : i + words_per_chunk])
        if i + words_per_chunk < len(words):
            piece += " "
        yield piece


def stream_answer(prompt: str, max_tokens: int | None = None):
    max_tokens = max_tokens or MAX_TOKENS

    if LLM_PROVIDER == "groq":
        client = get_openai_client()
        stream = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0.2,
            stream=True,
        )

        for event in stream:
            try:
                delta = event.choices[0].delta.content or ""
            except Exception:
                delta = ""

            if delta:
                yield delta
        return

    full_text = generate_answer(prompt, max_tokens=max_tokens)
    for piece in chunk_text(full_text, words_per_chunk=10):
        yield piece


def extract_json_from_text(text: str):
    text = clean_llm_output(text)

    try:
        return json.loads(text)
    except Exception:
        pass

    obj_match = re.search(r"(\{.*\})", text, re.DOTALL)
    arr_match = re.search(r"(\[.*\])", text, re.DOTALL)

    candidate = None
    if obj_match:
        candidate = obj_match.group(1)
    elif arr_match:
        candidate = arr_match.group(1)

    if candidate is None:
        raise ValueError("Could not find valid JSON in model response")

    return json.loads(candidate)


def generate_json(prompt: str):
    if LLM_PROVIDER == "groq":
        client = get_openai_client()
        completion = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=QUIZ_MAX_TOKENS,
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        content = completion.choices[0].message.content or ""

        try:
            return extract_json_from_text(content)
        except Exception:
            repair_prompt = f"""
Convert the following into one valid JSON object only.
Do not include markdown.
Do not include explanation.
Return only JSON.

Text:
{content}
"""
            repaired = generate_answer(repair_prompt, max_tokens=QUIZ_MAX_TOKENS)
            return extract_json_from_text(repaired)

    if LLM_PROVIDER == "ollama":
        content = generate_answer(prompt, max_tokens=QUIZ_MAX_TOKENS)

        try:
            return extract_json_from_text(content)
        except Exception:
            repair_prompt = f"""
Convert the following into one valid JSON object only.
Do not include markdown.
Do not include explanation.
Return only JSON.

Text:
{content}
"""
            repaired = generate_answer(repair_prompt, max_tokens=QUIZ_MAX_TOKENS)
            return extract_json_from_text(repaired)

    raise ValueError(
        f"Unsupported LLM_PROVIDER: {LLM_PROVIDER}. Use 'groq' or 'ollama'."
    )