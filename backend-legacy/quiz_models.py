from typing import List, Optional, Literal
from pydantic import BaseModel, Field


class QuizSource(BaseModel):
    source_name: str
    source_type: Literal["pdf", "url"]


class QuizGenerateRequest(BaseModel):
    source_name: str = Field(..., min_length=1)
    num_questions: int = Field(default=5, ge=3, le=10)
    difficulty: Literal["easy", "medium", "hard"] = "medium"


class QuizQuestionPublic(BaseModel):
    question_id: str
    topic: str
    question: str
    options: List[str]


class QuizQuestionInternal(BaseModel):
    question_id: str
    topic: str
    question: str
    options: List[str]
    correct_answer_index: int
    explanation: str


class QuizPublic(BaseModel):
    quiz_id: str
    title: str
    source_name: str
    source_type: Literal["pdf", "url"]
    difficulty: Literal["easy", "medium", "hard"]
    questions: List[QuizQuestionPublic]


class QuizInternal(BaseModel):
    quiz_id: str
    title: str
    source_name: str
    source_type: Literal["pdf", "url"]
    difficulty: Literal["easy", "medium", "hard"]
    questions: List[QuizQuestionInternal]


class QuizAnswer(BaseModel):
    question_id: str
    selected_index: int = Field(..., ge=0, le=3)


class QuizSubmission(BaseModel):
    quiz_id: str
    answers: List[QuizAnswer]


class QuizQuestionResult(BaseModel):
    question_id: str
    topic: str
    selected_index: Optional[int] = None
    correct_answer_index: int
    is_correct: bool
    explanation: str


class QuizResult(BaseModel):
    quiz_id: str
    score: int
    total: int
    percentage: float
    performance_band: str
    answered_count: int
    unanswered_count: int
    weak_topics: List[str]
    results: List[QuizQuestionResult]