import json
import os
import re
import time
from collections import Counter
from statistics import mean

from query import ask_question

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GOLDEN_SET_PATH = os.path.join(BASE_DIR, "golden_set.json")
LATEST_REPORT_PATH = os.path.join(BASE_DIR, "latest_report.json")

STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "to", "of", "in", "on",
    "for", "and", "or", "that", "this", "with", "as", "by", "at", "from",
    "it", "be", "been", "being", "into", "about", "than", "then"
}


def normalize_text(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def tokenize(text: str):
    return [t for t in normalize_text(text).split() if t not in STOPWORDS]


def token_f1(reference: str, prediction: str) -> float:
    ref_tokens = tokenize(reference)
    pred_tokens = tokenize(prediction)

    if not ref_tokens or not pred_tokens:
        return 0.0

    ref_counter = Counter(ref_tokens)
    pred_counter = Counter(pred_tokens)

    common = sum((ref_counter & pred_counter).values())

    if common == 0:
        return 0.0

    precision = common / sum(pred_counter.values())
    recall = common / sum(ref_counter.values())

    if precision + recall == 0:
        return 0.0

    return 2 * precision * recall / (precision + recall)


def keyword_recall(required_keywords, answer: str) -> float:
    if not required_keywords:
        return 1.0

    answer_norm = normalize_text(answer)
    hits = 0

    for keyword in required_keywords:
        if normalize_text(keyword) in answer_norm:
            hits += 1

    return hits / len(required_keywords)


def source_hit(expected_sources, actual_sources) -> bool:
    if not expected_sources:
        return True

    expected_norm = [normalize_text(x) for x in expected_sources]
    actual_norm = [normalize_text(x) for x in actual_sources]

    for expected in expected_norm:
        for actual in actual_norm:
            if expected == actual or expected in actual or actual in expected:
                return True

    return False


def load_golden_set():
    if not os.path.exists(GOLDEN_SET_PATH):
        raise FileNotFoundError("golden_set.json not found in backend/evals")

    with open(GOLDEN_SET_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list) or len(data) == 0:
        raise ValueError("golden_set.json must contain a non-empty list of test cases")

    return data


def save_latest_report(report: dict):
    with open(LATEST_REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)


def load_latest_report():
    if not os.path.exists(LATEST_REPORT_PATH):
        return None

    with open(LATEST_REPORT_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def evaluate_single_case(case: dict):
    question = case["question"]
    reference_answer = case.get("reference_answer", "")
    expected_sources = case.get("expected_sources", [])
    required_keywords = case.get("required_keywords", [])

    start = time.perf_counter()
    result = ask_question(question)
    latency_ms = round((time.perf_counter() - start) * 1000, 2)

    answer = result.get("answer", "")
    sources = result.get("sources", [])

    return {
        "question": question,
        "reference_answer": reference_answer,
        "predicted_answer": answer,
        "expected_sources": expected_sources,
        "returned_sources": sources,
        "latency_ms": latency_ms,
        "source_hit": source_hit(expected_sources, sources),
        "keyword_recall": round(keyword_recall(required_keywords, answer), 4),
        "token_f1": round(token_f1(reference_answer, answer), 4),
    }


def run_evaluation():
    dataset = load_golden_set()
    results = [evaluate_single_case(case) for case in dataset]

    summary = {
        "total_cases": len(results),
        "avg_latency_ms": round(mean([r["latency_ms"] for r in results]), 2),
        "source_hit_rate": round(mean([1 if r["source_hit"] else 0 for r in results]), 4),
        "avg_keyword_recall": round(mean([r["keyword_recall"] for r in results]), 4),
        "avg_token_f1": round(mean([r["token_f1"] for r in results]), 4),
    }

    report = {
        "summary": summary,
        "results": results,
    }

    save_latest_report(report)
    return report


if __name__ == "__main__":
    report = run_evaluation()
    print(json.dumps(report["summary"], indent=2))