import json
import os
from collections import defaultdict
from uuid import uuid4

from config import CHUNKS_FILE
from llm_utils import generate_json
from quiz_models import (
    QuizGenerateRequest,
    QuizInternal,
    QuizPublic,
    QuizQuestionInternal,
    QuizQuestionPublic,
    QuizQuestionResult,
    QuizResult,
    QuizSource,
    QuizSubmission,
)

_QUIZ_STORE: dict[str, QuizInternal] = {}


def load_chunk_store():
    if not os.path.exists(CHUNKS_FILE):
        return []

    with open(CHUNKS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def list_quiz_sources():
    chunks = load_chunk_store()
    unique = {}

    for item in chunks:
        metadata = item.get("metadata", {})
        source_name = metadata.get("source_file")
        source_type = metadata.get("source_type", "pdf")

        if source_name and source_name not in unique:
            unique[source_name] = {
                "source_name": source_name,
                "source_type": source_type,
            }

    return [QuizSource(**value) for value in unique.values()]


def get_source_chunks(source_name: str):
    chunks = load_chunk_store()
    return [
        item
        for item in chunks
        if item.get("metadata", {}).get("source_file") == source_name
    ]


def build_context_for_source(source_name: str, max_chars: int = 14000):
    source_chunks = get_source_chunks(source_name)

    if not source_chunks:
        raise ValueError(
            "No indexed chunks found for this source. Upload and wait for processing first."
        )

    source_type = source_chunks[0].get("metadata", {}).get("source_type", "pdf")

    context_parts = []
    total_chars = 0

    for item in source_chunks:
        text = item.get("text", "").strip()
        if not text:
            continue

        if total_chars + len(text) > max_chars:
            remaining = max_chars - total_chars
            if remaining > 0:
                context_parts.append(text[:remaining])
            break

        context_parts.append(text)
        total_chars += len(text)

    context = "\n\n".join(context_parts).strip()

    if not context:
        raise ValueError("Could not build enough context from the selected source.")

    return context, source_type


def get_performance_band(percentage: float) -> str:
    if percentage >= 85:
        return "Excellent"
    if percentage >= 70:
        return "Good"
    if percentage >= 50:
        return "Fair"
    return "Needs Improvement"


def generate_quiz(request: QuizGenerateRequest) -> QuizPublic:
    context, source_type = build_context_for_source(request.source_name)

    difficulty_instruction = {
        "easy": "Keep questions direct, simple, and definition-oriented.",
        "medium": "Use concept-level questions with moderate reasoning.",
        "hard": "Use deeper conceptual or application-based questions.",
    }[request.difficulty]

    prompt = f"""
Return ONLY one valid JSON object.

Create exactly {request.num_questions} multiple-choice questions from the source below.

Difficulty: {request.difficulty}
Instruction: {difficulty_instruction}

JSON format:
{{
  "title": "Short quiz title",
  "source_name": "{request.source_name}",
  "source_type": "{source_type}",
  "difficulty": "{request.difficulty}",
  "questions": [
    {{
      "topic": "Short topic label",
      "question": "Question text",
      "options": ["Option A", "Option B", "Option C", "Option D"],
      "correct_answer_index": 0,
      "explanation": "Short explanation"
    }}
  ]
}}

Rules:
- Every question must be answerable from the context
- Exactly 4 options per question
- correct_answer_index must be 0, 1, 2, or 3
- topic should be short, like "Supervised Learning" or "Classification"
- No markdown
- No extra text

Context:
{context}
"""

    data = generate_json(prompt)

    if "questions" not in data or not isinstance(data["questions"], list):
        raise ValueError("Quiz generation failed: invalid question structure")

    internal_questions = []

    for idx, q in enumerate(data["questions"][: request.num_questions], start=1):
        question_text = q.get("question", "").strip()
        if not question_text:
            raise ValueError("Quiz generation failed: question text is empty")

        options = q.get("options", [])
        if not isinstance(options, list) or len(options) != 4:
            raise ValueError(
                "Quiz generation failed: each question must have exactly 4 options"
            )

        correct_index = q.get("correct_answer_index")
        if not isinstance(correct_index, int) or correct_index < 0 or correct_index > 3:
            raise ValueError(
                "Quiz generation failed: correct_answer_index must be 0 to 3"
            )

        explanation = q.get("explanation", "").strip() or "No explanation provided."
        topic = q.get("topic", "General").strip() or "General"

        internal_questions.append(
            QuizQuestionInternal(
                question_id=f"q{idx}",
                topic=topic,
                question=question_text,
                options=options,
                correct_answer_index=correct_index,
                explanation=explanation,
            )
        )

    if len(internal_questions) < request.num_questions:
        raise ValueError(
            "Quiz generation failed: not enough valid questions were produced"
        )

    quiz_id = str(uuid4())

    quiz_internal = QuizInternal(
        quiz_id=quiz_id,
        title=data.get("title", f"Quiz on {request.source_name}"),
        source_name=request.source_name,
        source_type=source_type,
        difficulty=request.difficulty,
        questions=internal_questions,
    )

    _QUIZ_STORE[quiz_id] = quiz_internal

    return QuizPublic(
        quiz_id=quiz_internal.quiz_id,
        title=quiz_internal.title,
        source_name=quiz_internal.source_name,
        source_type=quiz_internal.source_type,
        difficulty=quiz_internal.difficulty,
        questions=[
            QuizQuestionPublic(
                question_id=q.question_id,
                topic=q.topic,
                question=q.question,
                options=q.options,
            )
            for q in quiz_internal.questions
        ],
    )


def submit_quiz(submission: QuizSubmission) -> QuizResult:
    quiz = _QUIZ_STORE.get(submission.quiz_id)

    if quiz is None:
        raise ValueError("Quiz not found or session expired. Generate the quiz again.")

    answer_map = {a.question_id: a.selected_index for a in submission.answers}

    results = []
    score = 0
    answered_count = 0
    topic_stats = defaultdict(lambda: {"total": 0, "correct": 0})

    for question in quiz.questions:
        selected_index = answer_map.get(question.question_id)
        is_answered = selected_index is not None
        is_correct = selected_index == question.correct_answer_index

        if is_answered:
            answered_count += 1

        if is_correct:
            score += 1

        topic_stats[question.topic]["total"] += 1
        if is_correct:
            topic_stats[question.topic]["correct"] += 1

        results.append(
            QuizQuestionResult(
                question_id=question.question_id,
                topic=question.topic,
                selected_index=selected_index,
                correct_answer_index=question.correct_answer_index,
                is_correct=is_correct,
                explanation=question.explanation,
            )
        )

    total = len(quiz.questions)
    unanswered_count = total - answered_count
    percentage = round((score / total) * 100, 2) if total else 0.0
    performance_band = get_performance_band(percentage)

    weak_topics = []
    for topic, stats in topic_stats.items():
        if stats["total"] > 0:
            ratio = stats["correct"] / stats["total"]
            if ratio < 0.6:
                weak_topics.append(topic)

    return QuizResult(
        quiz_id=quiz.quiz_id,
        score=score,
        total=total,
        percentage=percentage,
        performance_band=performance_band,
        answered_count=answered_count,
        unanswered_count=unanswered_count,
        weak_topics=weak_topics,
        results=results,
    )